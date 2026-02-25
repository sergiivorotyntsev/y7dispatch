"""SQLite database for Run History and API state."""

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Database path - can be overridden via DATABASE_PATH environment variable
_default_db_path = Path(__file__).parent.parent / "data" / "control_panel.db"
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(_default_db_path)))


def init_db():
    """Initialize the database with required tables."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        # Legacy tables 'runs' and 'logs' removed (2026-02-25). See extraction_runs and audit_events.

        # Config snapshots — reserved for future use, CRUD in save_config_snapshot()
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



# Legacy classes RunRecord, RunHistory, RunLogs removed (2026-02-25).
# See ExtractionRunRepository in api/models.py and AuditLogRepository in api/audit_log.py.


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
