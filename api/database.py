"""SQLite database for Run History and API state."""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Database path - can be overridden via DATABASE_PATH environment variable
_default_db_path = Path(__file__).parent.parent / "data" / "control_panel.db"
DB_PATH = Path(os.environ.get("DATABASE_PATH", str(_default_db_path)))

# Thread-local storage for connection reuse.
# Each thread gets at most one open connection. Nested get_connection() calls
# within the same thread reuse the existing connection instead of opening a new one.
# This reduces connection overhead from ~9 per Review page request to 1.
_local = threading.local()


def _apply_pragmas(conn):
    """Apply SQLite performance PRAGMAs to a new connection."""
    conn.execute("PRAGMA journal_mode=WAL")         # Concurrent reads during writes
    conn.execute("PRAGMA busy_timeout=5000")         # 5s wait instead of instant SQLITE_BUSY
    conn.execute("PRAGMA synchronous=NORMAL")        # Safe with WAL, ~2x faster than FULL
    conn.execute("PRAGMA cache_size=-8000")           # 8MB cache (default 2MB)
    conn.execute("PRAGMA temp_store=MEMORY")          # Temp tables in RAM
    conn.execute("PRAGMA foreign_keys=ON")              # Enforce referential integrity


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
    """Get a database connection, reusing within the same thread.

    Thread-local connection reuse: the first call in a thread creates a connection
    and applies PRAGMAs. Nested calls (e.g. Repository methods called within a
    route handler's ``with get_connection()`` block) reuse the same connection.
    The connection is closed only when the outermost context manager exits.
    """
    # Nested call — reuse existing connection
    if getattr(_local, 'conn', None) is not None:
        _local.depth += 1
        try:
            yield _local.conn
        finally:
            _local.depth -= 1
        return

    # First call in this thread — create new connection
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)

    _local.conn = conn
    _local.depth = 1
    try:
        yield conn
    finally:
        _local.depth -= 1
        if _local.depth == 0:
            _local.conn = None
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
