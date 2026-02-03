"""Idempotency storage for email deduplication."""

import hashlib
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class IdempotencyStore:
    def __init__(self, db_path: str = "processed_emails.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    thread_root_id TEXT,
                    message_id TEXT,
                    attachment_hash TEXT,
                    source_type TEXT,
                    result_type TEXT,
                    result_id TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)
            conn.commit()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def compute_attachment_hash(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def extract_thread_root_id(
        message_id: Optional[str], in_reply_to: Optional[str], references: Optional[str]
    ) -> str:
        if references:
            refs = references.strip().split()
            if refs:
                return refs[0].strip("<>")
        if in_reply_to:
            return in_reply_to.strip("<>")
        if message_id:
            return message_id.strip("<>")
        return f"unknown-{datetime.utcnow().isoformat()}"

    def generate_idempotency_key(
        self, thread_root_id: str, attachment_hash: str, namespace: str = "email"
    ) -> str:
        """Generate idempotency key with optional namespace.

        Namespaces:
        - email: Email processing (default)
        - google_sheets: Sheets export deduplication
        - clickup: ClickUp task creation
        - cd: Central Dispatch listings
        """
        return f"{namespace}:{thread_root_id}:{attachment_hash}"

    def is_processed(self, idempotency_key: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM processed_items WHERE idempotency_key = ?", (idempotency_key,)
            )
            return cursor.fetchone() is not None

    def is_processed_in_namespace(
        self,
        attachment_hash: str,
        namespace: str,
        auction: str = None,
        gate_pass: str = None,
    ) -> tuple[bool, Optional[str]]:
        """Check if an attachment has been processed in a specific namespace.

        For sheets namespace, key = namespace:hash:auction[:gate_pass]
        """
        # Build key components
        key_parts = [namespace, attachment_hash]
        if auction:
            key_parts.append(auction)
        if gate_pass:
            key_parts.append(gate_pass)

        key_prefix = ":".join(key_parts)

        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT result_id FROM processed_items WHERE idempotency_key LIKE ?",
                (f"{key_prefix}%",),
            )
            row = cursor.fetchone()
            if row:
                return True, row["result_id"]
            return False, None

    def mark_processed_in_namespace(
        self,
        attachment_hash: str,
        namespace: str,
        result_id: str,
        auction: str = None,
        gate_pass: str = None,
        metadata: Optional[str] = None,
    ) -> bool:
        """Mark an attachment as processed in a namespace."""
        key_parts = [namespace, attachment_hash]
        if auction:
            key_parts.append(auction)
        if gate_pass:
            key_parts.append(gate_pass)

        key = ":".join(key_parts)

        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT INTO processed_items
                       (idempotency_key, attachment_hash, source_type, result_type, result_id, metadata)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (key, attachment_hash, namespace, namespace, result_id, metadata),
                )
                conn.commit()
                logger.debug(f"Marked as processed: {key} -> {result_id}")
                return True
        except sqlite3.IntegrityError:
            logger.debug(f"Already processed: {key}")
            return False

    def is_attachment_processed_in_thread(
        self, thread_root_id: str, attachment_hash: str
    ) -> tuple[bool, Optional[str]]:
        key = self.generate_idempotency_key(thread_root_id, attachment_hash)
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT result_id FROM processed_items WHERE idempotency_key = ?", (key,)
            )
            row = cursor.fetchone()
            if row:
                return True, row["result_id"]
            return False, None

    def mark_processed(
        self,
        thread_root_id: str,
        message_id: str,
        attachment_hash: str,
        source_type: str,
        result_type: str,
        result_id: str,
        metadata: Optional[str] = None,
    ) -> bool:
        key = self.generate_idempotency_key(thread_root_id, attachment_hash)
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT INTO processed_items (idempotency_key, thread_root_id, message_id, attachment_hash, source_type, result_type, result_id, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        key,
                        thread_root_id,
                        message_id,
                        attachment_hash,
                        source_type,
                        result_type,
                        result_id,
                        metadata,
                    ),
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False
