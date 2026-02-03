"""SQLite database for Run History and API state."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Database path
DB_PATH = Path(__file__).parent.parent / "data" / "control_panel.db"


def init_db():
    """Initialize the database with required tables."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        # Runs table - main history
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source_type TEXT NOT NULL,
                status TEXT NOT NULL,
                email_message_id TEXT,
                attachment_hash TEXT,
                attachment_name TEXT,
                auction_detected TEXT,
                extraction_score REAL,
                warehouse_id TEXT,
                warehouse_reason TEXT,
                clickup_task_id TEXT,
                clickup_task_url TEXT,
                cd_listing_id TEXT,
                cd_payload_summary TEXT,
                sheets_spreadsheet_id TEXT,
                sheets_row_index INTEGER,
                error_message TEXT,
                config_version TEXT,
                metadata TEXT
            )
        """)

        # Logs table - detailed logs per run
        conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            )
        """)

        # Config snapshots - for versioning
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config_snapshots (
                id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                config_type TEXT NOT NULL,
                config_data TEXT NOT NULL,
                description TEXT
            )
        """)

        conn.commit()


@contextmanager
def get_connection():
    """Get a database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@dataclass
class RunRecord:
    """A single run record."""

    id: str
    created_at: str
    source_type: str  # 'email', 'upload', 'batch'
    status: str  # 'pending', 'processing', 'ok', 'failed', 'error'
    email_message_id: Optional[str] = None
    attachment_hash: Optional[str] = None
    attachment_name: Optional[str] = None
    auction_detected: Optional[str] = None
    extraction_score: Optional[float] = None
    warehouse_id: Optional[str] = None
    warehouse_reason: Optional[str] = None
    clickup_task_id: Optional[str] = None
    clickup_task_url: Optional[str] = None
    cd_listing_id: Optional[str] = None
    cd_payload_summary: Optional[str] = None
    sheets_spreadsheet_id: Optional[str] = None
    sheets_row_index: Optional[int] = None
    error_message: Optional[str] = None
    config_version: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class RunHistory:
    """Manage run history in the database."""

    @staticmethod
    def create_run(
        source_type: str,
        attachment_name: str = None,
        attachment_hash: str = None,
        email_message_id: str = None,
    ) -> str:
        """Create a new run record. Returns the run ID."""
        run_id = str(uuid.uuid4())[:8]

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO runs (id, source_type, status, attachment_name, attachment_hash, email_message_id)
                   VALUES (?, ?, 'pending', ?, ?, ?)""",
                (run_id, source_type, attachment_name, attachment_hash, email_message_id),
            )
            conn.commit()

        return run_id

    @staticmethod
    def update_run(run_id: str, **kwargs):
        """Update a run record with new values."""
        if not kwargs:
            return

        # Handle metadata separately
        if "metadata" in kwargs and isinstance(kwargs["metadata"], dict):
            kwargs["metadata"] = json.dumps(kwargs["metadata"])

        # Build update query
        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [run_id]

        with get_connection() as conn:
            conn.execute(f"UPDATE runs SET {set_clause} WHERE id = ?", values)
            conn.commit()

    @staticmethod
    def get_run(run_id: str) -> Optional[RunRecord]:
        """Get a single run by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

            if row:
                data = dict(row)
                if data.get("metadata"):
                    data["metadata"] = json.loads(data["metadata"])
                return RunRecord(**data)
            return None

    @staticmethod
    def list_runs(
        limit: int = 50,
        offset: int = 0,
        source_type: str = None,
        status: str = None,
        auction: str = None,
    ) -> list[RunRecord]:
        """List runs with optional filtering."""
        query = "SELECT * FROM runs WHERE 1=1"
        params = []

        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)
        if status:
            query += " AND status = ?"
            params.append(status)
        if auction:
            query += " AND auction_detected = ?"
            params.append(auction)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            runs = []
            for row in rows:
                data = dict(row)
                if data.get("metadata"):
                    data["metadata"] = json.loads(data["metadata"])
                runs.append(RunRecord(**data))
            return runs

    @staticmethod
    def get_stats() -> dict[str, Any]:
        """Get run statistics."""
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

            by_status = dict(
                conn.execute("SELECT status, COUNT(*) FROM runs GROUP BY status").fetchall()
            )

            by_auction = dict(
                conn.execute(
                    "SELECT auction_detected, COUNT(*) FROM runs WHERE auction_detected IS NOT NULL GROUP BY auction_detected"
                ).fetchall()
            )

            by_source = dict(
                conn.execute(
                    "SELECT source_type, COUNT(*) FROM runs GROUP BY source_type"
                ).fetchall()
            )

            recent = conn.execute(
                "SELECT COUNT(*) FROM runs WHERE created_at > datetime('now', '-24 hours')"
            ).fetchone()[0]

            return {
                "total": total,
                "last_24h": recent,
                "by_status": by_status,
                "by_auction": by_auction,
                "by_source": by_source,
            }


class RunLogs:
    """Manage logs for runs."""

    @staticmethod
    def add_log(run_id: str, level: str, message: str, details: dict = None):
        """Add a log entry for a run."""
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO logs (run_id, level, message, details)
                   VALUES (?, ?, ?, ?)""",
                (run_id, level, message, json.dumps(details) if details else None),
            )
            conn.commit()

    @staticmethod
    def get_logs(run_id: str) -> list[dict]:
        """Get all logs for a run."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM logs WHERE run_id = ? ORDER BY timestamp", (run_id,)
            ).fetchall()

            logs = []
            for row in rows:
                log = dict(row)
                if log.get("details"):
                    log["details"] = json.loads(log["details"])
                logs.append(log)
            return logs

    @staticmethod
    def search_logs(
        query: str = None,
        run_id: str = None,
        level: str = None,
        limit: int = 100,
    ) -> list[dict]:
        """Search logs with filters."""
        sql = "SELECT * FROM logs WHERE 1=1"
        params = []

        if run_id:
            sql += " AND run_id = ?"
            params.append(run_id)
        if level:
            sql += " AND level = ?"
            params.append(level)
        if query:
            sql += " AND message LIKE ?"
            params.append(f"%{query}%")

        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]


class ConfigSnapshots:
    """Manage configuration snapshots."""

    @staticmethod
    def save_snapshot(config_type: str, config_data: dict, description: str = None) -> str:
        """Save a configuration snapshot. Returns snapshot ID."""
        snapshot_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        with get_connection() as conn:
            conn.execute(
                """INSERT INTO config_snapshots (id, config_type, config_data, description)
                   VALUES (?, ?, ?, ?)""",
                (snapshot_id, config_type, json.dumps(config_data), description),
            )
            conn.commit()

        return snapshot_id

    @staticmethod
    def get_snapshot(snapshot_id: str) -> Optional[dict]:
        """Get a configuration snapshot."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM config_snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()

            if row:
                data = dict(row)
                data["config_data"] = json.loads(data["config_data"])
                return data
            return None

    @staticmethod
    def list_snapshots(config_type: str = None, limit: int = 20) -> list[dict]:
        """List configuration snapshots."""
        sql = "SELECT id, created_at, config_type, description FROM config_snapshots"
        params = []

        if config_type:
            sql += " WHERE config_type = ?"
            params.append(config_type)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with get_connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]
