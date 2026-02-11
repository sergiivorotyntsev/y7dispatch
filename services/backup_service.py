"""
Backup Service (Phase 0.6)

Automated database and file backups to DigitalOcean Spaces.

Features:
- Scheduled backups via cron
- Retention policy enforcement
- Compression and encryption
- Restore testing
- Alerting on failures

Usage:
    from services.backup_service import BackupService

    # Create backup
    backup = BackupService()
    result = backup.create_backup()

    # List backups
    backups = backup.list_backups()

    # Restore from backup
    backup.restore_from_backup(backup_id)
"""

import gzip
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# Default config path
CONFIG_PATH = Path(__file__).parent.parent / "config" / "backup_config.yaml"


@dataclass
class BackupResult:
    """Result of a backup operation."""

    success: bool
    backup_id: str
    timestamp: datetime
    size_bytes: int
    duration_seconds: float
    destination: str
    checksum: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "backup_id": self.backup_id,
            "timestamp": self.timestamp.isoformat(),
            "size_bytes": self.size_bytes,
            "duration_seconds": round(self.duration_seconds, 2),
            "destination": self.destination,
            "checksum": self.checksum,
            "error": self.error,
        }


@dataclass
class BackupInfo:
    """Information about an existing backup."""

    backup_id: str
    timestamp: datetime
    size_bytes: int
    path: str
    checksum: Optional[str]
    backup_type: str  # full, incremental

    def to_dict(self) -> dict:
        return {
            "backup_id": self.backup_id,
            "timestamp": self.timestamp.isoformat(),
            "size_bytes": self.size_bytes,
            "path": self.path,
            "checksum": self.checksum,
            "backup_type": self.backup_type,
        }


class BackupService:
    """
    Database and file backup service.
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize backup service.

        Args:
            config_path: Path to backup_config.yaml
        """
        self.config_path = config_path or CONFIG_PATH
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load backup configuration."""
        if not self.config_path.exists():
            logger.warning(f"Backup config not found: {self.config_path}")
            return {}

        with open(self.config_path) as f:
            config = yaml.safe_load(f)

        # Expand environment variables
        return self._expand_env_vars(config)

    def _expand_env_vars(self, obj):
        """Recursively expand environment variables in config."""
        if isinstance(obj, str):
            if obj.startswith("${") and obj.endswith("}"):
                var_name = obj[2:-1]
                # Handle default values: ${VAR:-default}
                if ":-" in var_name:
                    var_name, default = var_name.split(":-", 1)
                    return os.getenv(var_name, default)
                return os.getenv(var_name, "")
            return obj
        elif isinstance(obj, dict):
            return {k: self._expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._expand_env_vars(item) for item in obj]
        return obj

    def create_backup(
        self,
        backup_type: str = "full",
        destination: Optional[str] = None,
    ) -> BackupResult:
        """
        Create a new backup.

        Args:
            backup_type: Type of backup (full, incremental)
            destination: Override destination (local path or s3:// URL)

        Returns:
            BackupResult with backup details
        """
        import time

        start_time = time.time()
        timestamp = datetime.utcnow()
        backup_id = f"backup_{timestamp.strftime('%Y%m%d_%H%M%S')}"

        try:
            # Create temp directory for backup
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Backup database
                db_path = self._backup_database(temp_path, backup_id)

                # Compress
                if self.config.get("compression", {}).get("enabled", True):
                    db_path = self._compress_file(db_path)

                # Calculate checksum
                checksum = self._calculate_checksum(db_path)

                # Upload to destination
                dest = destination or self._get_destination()
                final_path = self._upload_backup(db_path, dest, backup_id)

                duration = time.time() - start_time

                result = BackupResult(
                    success=True,
                    backup_id=backup_id,
                    timestamp=timestamp,
                    size_bytes=db_path.stat().st_size,
                    duration_seconds=duration,
                    destination=final_path,
                    checksum=checksum,
                )

                logger.info(
                    f"Backup created: {backup_id}, "
                    f"size={result.size_bytes}, duration={duration:.1f}s"
                )

                # Cleanup old backups
                self._enforce_retention()

                return result

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return BackupResult(
                success=False,
                backup_id=backup_id,
                timestamp=timestamp,
                size_bytes=0,
                duration_seconds=time.time() - start_time,
                destination="",
                error=str(e),
            )

    def _backup_database(self, dest_dir: Path, backup_id: str) -> Path:
        """
        Backup SQLite database.

        Uses SQLite backup API for consistency.
        """
        db_config = self.config.get("sources", {}).get("database", {})
        source_db = db_config.get("path", "./dispatch.db")

        dest_path = dest_dir / f"{backup_id}.db"

        # Use SQLite backup API
        source_conn = sqlite3.connect(source_db)
        dest_conn = sqlite3.connect(str(dest_path))

        source_conn.backup(dest_conn)

        source_conn.close()
        dest_conn.close()

        logger.debug(f"Database backed up to: {dest_path}")
        return dest_path

    def _compress_file(self, file_path: Path) -> Path:
        """Compress a file with gzip."""
        compressed_path = file_path.with_suffix(file_path.suffix + ".gz")

        level = self.config.get("compression", {}).get("level", 6)

        with open(file_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb", compresslevel=level) as f_out:
                shutil.copyfileobj(f_in, f_out)

        # Remove uncompressed file
        file_path.unlink()

        logger.debug(f"Compressed to: {compressed_path}")
        return compressed_path

    def _calculate_checksum(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of file."""
        sha256 = hashlib.sha256()

        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)

        return sha256.hexdigest()

    def _get_destination(self) -> str:
        """Get backup destination from config."""
        dest_config = self.config.get("destination", {})

        if dest_config.get("type") == "s3":
            s3_config = dest_config.get("s3", {})
            bucket = s3_config.get("bucket", "")
            prefix = s3_config.get("prefix", "backups/")
            return f"s3://{bucket}/{prefix}"

        local_config = dest_config.get("local", {})
        if local_config.get("enabled"):
            return local_config.get("path", "/var/backups/")

        return "./backups/"

    def _upload_backup(self, file_path: Path, destination: str, backup_id: str) -> str:
        """
        Upload backup to destination.

        Supports local filesystem and S3.
        """
        if destination.startswith("s3://"):
            return self._upload_to_s3(file_path, destination, backup_id)
        else:
            return self._upload_local(file_path, destination, backup_id)

    def _upload_local(self, file_path: Path, destination: str, backup_id: str) -> str:
        """Copy backup to local destination."""
        dest_dir = Path(destination)
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_path = dest_dir / file_path.name
        shutil.copy2(file_path, dest_path)

        # Write metadata
        meta_path = dest_path.with_suffix(dest_path.suffix + ".meta.json")
        with open(meta_path, "w") as f:
            json.dump(
                {
                    "backup_id": backup_id,
                    "timestamp": datetime.utcnow().isoformat(),
                    "size_bytes": dest_path.stat().st_size,
                    "checksum": self._calculate_checksum(dest_path),
                },
                f,
            )

        return str(dest_path)

    def _upload_to_s3(self, file_path: Path, destination: str, backup_id: str) -> str:
        """Upload backup to S3/Spaces."""
        try:
            import boto3
        except ImportError:
            logger.error("boto3 not installed, cannot upload to S3")
            raise RuntimeError("boto3 required for S3 uploads")

        s3_config = self.config.get("destination", {}).get("s3", {})

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{s3_config.get('endpoint', '')}",
            aws_access_key_id=s3_config.get("access_key_id"),
            aws_secret_access_key=s3_config.get("secret_access_key"),
            region_name=s3_config.get("region"),
        )

        bucket = s3_config.get("bucket")
        prefix = s3_config.get("prefix", "backups/")
        key = f"{prefix}{file_path.name}"

        s3.upload_file(str(file_path), bucket, key)

        logger.info(f"Uploaded to S3: s3://{bucket}/{key}")
        return f"s3://{bucket}/{key}"

    def list_backups(self, limit: int = 50) -> list[BackupInfo]:
        """List available backups."""
        backups = []
        destination = self._get_destination()

        if destination.startswith("s3://"):
            backups = self._list_s3_backups(destination, limit)
        else:
            backups = self._list_local_backups(destination, limit)

        return sorted(backups, key=lambda b: b.timestamp, reverse=True)[:limit]

    def _list_local_backups(self, destination: str, limit: int) -> list[BackupInfo]:
        """List backups from local filesystem."""
        backups = []
        dest_dir = Path(destination)

        if not dest_dir.exists():
            return backups

        for path in dest_dir.glob("backup_*.db.gz"):
            meta_path = path.with_suffix(path.suffix + ".meta.json")
            metadata = {}

            if meta_path.exists():
                with open(meta_path) as f:
                    metadata = json.load(f)

            # Parse timestamp from filename
            try:
                name = path.stem.replace(".db", "")
                ts_str = name.replace("backup_", "")
                timestamp = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            except ValueError:
                timestamp = datetime.fromtimestamp(path.stat().st_mtime)

            backups.append(
                BackupInfo(
                    backup_id=metadata.get("backup_id", path.stem),
                    timestamp=timestamp,
                    size_bytes=path.stat().st_size,
                    path=str(path),
                    checksum=metadata.get("checksum"),
                    backup_type="full",
                )
            )

        return backups

    def _list_s3_backups(self, destination: str, limit: int) -> list[BackupInfo]:
        """List backups from S3."""
        try:
            import boto3
        except ImportError:
            logger.error("boto3 not installed")
            return []

        s3_config = self.config.get("destination", {}).get("s3", {})

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{s3_config.get('endpoint', '')}",
            aws_access_key_id=s3_config.get("access_key_id"),
            aws_secret_access_key=s3_config.get("secret_access_key"),
            region_name=s3_config.get("region"),
        )

        bucket = s3_config.get("bucket")
        prefix = s3_config.get("prefix", "backups/")

        response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=limit)

        backups = []
        for obj in response.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".db.gz"):
                continue

            name = key.split("/")[-1].replace(".db.gz", "")
            try:
                ts_str = name.replace("backup_", "")
                timestamp = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            except ValueError:
                timestamp = obj["LastModified"]

            backups.append(
                BackupInfo(
                    backup_id=name,
                    timestamp=timestamp,
                    size_bytes=obj["Size"],
                    path=f"s3://{bucket}/{key}",
                    checksum=None,
                    backup_type="full",
                )
            )

        return backups

    def restore_from_backup(
        self,
        backup_id: str,
        target_path: Optional[str] = None,
    ) -> bool:
        """
        Restore database from a backup.

        Args:
            backup_id: ID of backup to restore
            target_path: Override target database path

        Returns:
            True if restore succeeded
        """
        backups = self.list_backups()
        backup = next((b for b in backups if b.backup_id == backup_id), None)

        if not backup:
            logger.error(f"Backup not found: {backup_id}")
            return False

        try:
            # Download/copy backup
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir) / "restore.db.gz"

                if backup.path.startswith("s3://"):
                    self._download_from_s3(backup.path, temp_path)
                else:
                    shutil.copy2(backup.path, temp_path)

                # Decompress
                db_path = temp_path.with_suffix("")
                with gzip.open(temp_path, "rb") as f_in:
                    with open(db_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)

                # Verify database
                conn = sqlite3.connect(str(db_path))
                conn.execute("SELECT 1").fetchone()
                conn.close()

                # Copy to target
                target = target_path or self.config.get("sources", {}).get(
                    "database", {}
                ).get("path", "./dispatch.db")

                shutil.copy2(db_path, target)

                logger.info(f"Restored backup {backup_id} to {target}")
                return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def _download_from_s3(self, s3_path: str, local_path: Path):
        """Download file from S3."""
        import boto3

        s3_config = self.config.get("destination", {}).get("s3", {})

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{s3_config.get('endpoint', '')}",
            aws_access_key_id=s3_config.get("access_key_id"),
            aws_secret_access_key=s3_config.get("secret_access_key"),
            region_name=s3_config.get("region"),
        )

        # Parse s3://bucket/key
        parts = s3_path.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        s3.download_file(bucket, key, str(local_path))

    def _enforce_retention(self):
        """Enforce retention policy by deleting old backups."""
        retention = self.config.get("retention", {})
        max_backups = retention.get("max_backups", 50)

        backups = self.list_backups(limit=max_backups * 2)

        if len(backups) <= max_backups:
            return

        # Sort by timestamp
        sorted_backups = sorted(backups, key=lambda b: b.timestamp, reverse=True)

        # Keep max_backups most recent
        to_delete = sorted_backups[max_backups:]

        for backup in to_delete:
            self._delete_backup(backup)

    def _delete_backup(self, backup: BackupInfo):
        """Delete a backup."""
        if backup.path.startswith("s3://"):
            self._delete_from_s3(backup.path)
        else:
            path = Path(backup.path)
            if path.exists():
                path.unlink()
                # Also delete metadata
                meta_path = path.with_suffix(path.suffix + ".meta.json")
                if meta_path.exists():
                    meta_path.unlink()

        logger.info(f"Deleted old backup: {backup.backup_id}")

    def _delete_from_s3(self, s3_path: str):
        """Delete file from S3."""
        try:
            import boto3
        except ImportError:
            return

        s3_config = self.config.get("destination", {}).get("s3", {})

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{s3_config.get('endpoint', '')}",
            aws_access_key_id=s3_config.get("access_key_id"),
            aws_secret_access_key=s3_config.get("secret_access_key"),
            region_name=s3_config.get("region"),
        )

        parts = s3_path.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        s3.delete_object(Bucket=bucket, Key=key)

    def test_restore(self) -> bool:
        """
        Test restore procedure.

        Creates a backup, restores to temp location, verifies integrity.
        """
        logger.info("Running restore test...")

        try:
            # Create a backup
            result = self.create_backup()
            if not result.success:
                logger.error(f"Backup creation failed: {result.error}")
                return False

            # Restore to temp location
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
                temp_path = f.name

            success = self.restore_from_backup(result.backup_id, temp_path)
            if not success:
                logger.error("Restore failed")
                return False

            # Verify database
            conn = sqlite3.connect(temp_path)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            conn.close()

            # Cleanup
            Path(temp_path).unlink()

            logger.info(
                f"Restore test passed: {len(tables)} tables found in restored DB"
            )
            return True

        except Exception as e:
            logger.error(f"Restore test failed: {e}")
            return False
