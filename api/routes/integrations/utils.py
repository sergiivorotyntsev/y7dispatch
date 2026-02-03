"""
Integration Utilities

Shared utilities for all integration modules:
- Secret encryption/decryption
- Audit logging
- Common models
"""

import base64
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from cryptography.fernet import Fernet
from pydantic import BaseModel

from api.database import get_connection

# =============================================================================
# ENCRYPTION UTILS
# =============================================================================


def get_encryption_key() -> bytes:
    """Get or create encryption key for secrets."""
    key_file = Path("config/.secret_key")
    if key_file.exists():
        return key_file.read_bytes()

    key = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(key)
    os.chmod(key_file, 0o600)
    return key


def encrypt_secret(value: str) -> str:
    """Encrypt a secret value."""
    if not value:
        return ""
    try:
        f = Fernet(get_encryption_key())
        return f.encrypt(value.encode()).decode()
    except Exception:
        return base64.b64encode(value.encode()).decode()


def decrypt_secret(encrypted: str) -> str:
    """Decrypt a secret value."""
    if not encrypted:
        return ""
    try:
        f = Fernet(get_encryption_key())
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        try:
            return base64.b64decode(encrypted.encode()).decode()
        except Exception:
            return encrypted


def mask_secret(value: str) -> str:
    """Mask a secret for display."""
    if not value:
        return ""
    if len(value) <= 8:
        return "●●●●●●●●"
    return value[:4] + "●●●●" + value[-4:]


# =============================================================================
# AUDIT LOG
# =============================================================================


class AuditLogEntry(BaseModel):
    """Audit log entry for integration actions."""

    id: str
    timestamp: str
    integration: str
    action: str
    status: str
    user: Optional[str] = None
    request_id: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None


def init_audit_log_table():
    """Initialize the audit log table."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS integration_audit_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                integration TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                user TEXT,
                request_id TEXT,
                details_json TEXT,
                error TEXT,
                duration_ms INTEGER
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_log_integration
            ON integration_audit_log(integration)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
            ON integration_audit_log(timestamp DESC)
        """)
        conn.commit()


def log_integration_action(
    integration: str,
    action: str,
    status: str,
    details: dict[str, Any] = None,
    error: str = None,
    duration_ms: int = None,
    request_id: str = None,
) -> str:
    """Log an integration action to the audit log."""
    entry_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow().isoformat() + "Z"

    with get_connection() as conn:
        init_audit_log_table()
        conn.execute(
            """
            INSERT INTO integration_audit_log
            (id, timestamp, integration, action, status, user, request_id, details_json, error, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                entry_id,
                timestamp,
                integration,
                action,
                status,
                None,
                request_id,
                json.dumps(details) if details else None,
                error,
                duration_ms,
            ),
        )
        conn.commit()

    return entry_id


def get_audit_log(
    integration: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> list[AuditLogEntry]:
    """Get audit log entries."""
    sql = "SELECT * FROM integration_audit_log WHERE 1=1"
    params = []

    if integration:
        sql += " AND integration = ?"
        params.append(integration)
    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    try:
        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            AuditLogEntry(
                id=row["id"],
                timestamp=row["timestamp"],
                integration=row["integration"],
                action=row["action"],
                status=row["status"],
                user=row["user"],
                request_id=row["request_id"],
                details=json.loads(row["details_json"]) if row["details_json"] else None,
                error=row["error"],
                duration_ms=row["duration_ms"],
            )
            for row in rows
        ]
    except Exception:
        return []


# =============================================================================
# COMMON MODELS
# =============================================================================


class TestConnectionResponse(BaseModel):
    """Standard response for connection tests."""

    status: str
    message: str
    details: Optional[dict[str, Any]] = None
    duration_ms: Optional[int] = None
