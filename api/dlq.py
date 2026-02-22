"""
Dead Letter Queue (DLQ) Infrastructure (Phase 0.7)

Handles failed email processing with:
- Persistent storage of failed items
- Retry mechanism with exponential backoff
- Manual resolution workflow
- Alerting integration

Usage:
    from api.dlq import DLQService, get_dlq_service

    dlq = get_dlq_service()
    dlq.add_entry(
        email_id="msg_123",
        email_subject="Copart Invoice",
        failure_reason=FailureReason.CORRUPTED_PDF,
        failure_details="pdfplumber failed: invalid stream",
    )

    # Retry failed items
    dlq.retry_entry(entry_id)

    # Manual resolution
    dlq.resolve_entry(entry_id, resolved_by="admin@y7agency.com")
"""

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Optional
from uuid import uuid4

from api.database import get_connection

logger = logging.getLogger(__name__)


class FailureReason(str, Enum):
    """Categorized failure reasons for DLQ entries."""

    CORRUPTED_PDF = "corrupted_pdf"  # PDF couldn't be parsed
    EXTRACTION_FAILED = "extraction_failed"  # Extraction returned no results
    VALIDATION_FAILED = "validation_failed"  # Extracted data failed validation
    API_ERROR = "api_error"  # External API error (Claude, CD, etc.)
    UNKNOWN_FORMAT = "unknown_format"  # No extractor matched
    DUPLICATE = "duplicate"  # Duplicate email detected
    TIMEOUT = "timeout"  # Processing timed out
    INTERNAL_ERROR = "internal_error"  # Unexpected internal error


class DLQStatus(str, Enum):
    """Status of a DLQ entry."""

    PENDING = "pending"  # Awaiting retry or manual resolution
    RETRYING = "retrying"  # Currently being retried
    RESOLVED = "resolved"  # Manually resolved
    EXHAUSTED = "exhausted"  # Max retries exceeded


@dataclass
class DLQEntry:
    """A dead letter queue entry."""

    id: str
    email_id: str
    email_subject: str
    email_from: Optional[str]
    email_date: Optional[datetime]
    failure_reason: FailureReason
    failure_details: str
    attachment_filename: Optional[str]
    attachment_hash: Optional[str]
    status: DLQStatus
    retry_count: int
    max_retries: int
    next_retry_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime]
    resolved_by: Optional[str]
    resolution_notes: Optional[str]
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email_id": self.email_id,
            "email_subject": self.email_subject,
            "email_from": self.email_from,
            "email_date": self.email_date.isoformat() if self.email_date else None,
            "failure_reason": self.failure_reason.value,
            "failure_details": self.failure_details,
            "attachment_filename": self.attachment_filename,
            "attachment_hash": self.attachment_hash,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "next_retry_at": (
                self.next_retry_at.isoformat() if self.next_retry_at else None
            ),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "resolved_at": (
                self.resolved_at.isoformat() if self.resolved_at else None
            ),
            "resolved_by": self.resolved_by,
            "resolution_notes": self.resolution_notes,
            "metadata": self.metadata,
        }


@dataclass
class DLQSummary:
    """Summary statistics for DLQ."""

    total_entries: int = 0
    pending_count: int = 0
    retrying_count: int = 0
    resolved_count: int = 0
    exhausted_count: int = 0
    by_reason: dict = field(default_factory=dict)
    oldest_pending_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "total_entries": self.total_entries,
            "pending_count": self.pending_count,
            "retrying_count": self.retrying_count,
            "resolved_count": self.resolved_count,
            "exhausted_count": self.exhausted_count,
            "by_reason": self.by_reason,
            "oldest_pending_at": (
                self.oldest_pending_at.isoformat() if self.oldest_pending_at else None
            ),
        }


# Retry configuration
RETRY_CONFIG = {
    "max_retries": 3,
    "base_delay_seconds": 300,  # 5 minutes
    "max_delay_seconds": 3600,  # 1 hour
    "exponential_base": 2,
}


def calculate_next_retry(retry_count: int) -> datetime:
    """Calculate next retry time with exponential backoff."""
    delay = min(
        RETRY_CONFIG["base_delay_seconds"]
        * (RETRY_CONFIG["exponential_base"] ** retry_count),
        RETRY_CONFIG["max_delay_seconds"],
    )
    return datetime.now(timezone.utc) + timedelta(seconds=delay)


class DLQService:
    """
    Dead Letter Queue service for managing failed processing.
    """

    def __init__(self):
        self._ensure_table()
        self._alert_callbacks: list[Callable[[DLQEntry], None]] = []

    def _ensure_table(self):
        """Create DLQ table if not exists."""
        with get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dlq_entries (
                    id TEXT PRIMARY KEY,
                    email_id TEXT NOT NULL,
                    email_subject TEXT,
                    email_from TEXT,
                    email_date TEXT,
                    failure_reason TEXT NOT NULL,
                    failure_details TEXT,
                    attachment_filename TEXT,
                    attachment_hash TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    next_retry_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    resolved_at TEXT,
                    resolved_by TEXT,
                    resolution_notes TEXT,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dlq_status ON dlq_entries(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dlq_reason ON dlq_entries(failure_reason)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dlq_next_retry ON dlq_entries(next_retry_at)
            """)
            conn.commit()

    def add_entry(
        self,
        email_id: str,
        email_subject: str,
        failure_reason: FailureReason,
        failure_details: str,
        email_from: Optional[str] = None,
        email_date: Optional[datetime] = None,
        attachment_filename: Optional[str] = None,
        attachment_hash: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> DLQEntry:
        """
        Add a new entry to the dead letter queue.

        Returns:
            Created DLQEntry
        """
        now = datetime.now(timezone.utc)
        entry = DLQEntry(
            id=str(uuid4()),
            email_id=email_id,
            email_subject=email_subject,
            email_from=email_from,
            email_date=email_date,
            failure_reason=failure_reason,
            failure_details=failure_details,
            attachment_filename=attachment_filename,
            attachment_hash=attachment_hash,
            status=DLQStatus.PENDING,
            retry_count=0,
            max_retries=RETRY_CONFIG["max_retries"],
            next_retry_at=calculate_next_retry(0),
            created_at=now,
            updated_at=now,
            resolved_at=None,
            resolved_by=None,
            resolution_notes=None,
            metadata=metadata or {},
        )

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO dlq_entries (
                    id, email_id, email_subject, email_from, email_date,
                    failure_reason, failure_details, attachment_filename,
                    attachment_hash, status, retry_count, max_retries,
                    next_retry_at, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id,
                    entry.email_id,
                    entry.email_subject,
                    entry.email_from,
                    entry.email_date.isoformat() if entry.email_date else None,
                    entry.failure_reason.value,
                    entry.failure_details,
                    entry.attachment_filename,
                    entry.attachment_hash,
                    entry.status.value,
                    entry.retry_count,
                    entry.max_retries,
                    entry.next_retry_at.isoformat() if entry.next_retry_at else None,
                    entry.created_at.isoformat(),
                    entry.updated_at.isoformat(),
                    json.dumps(entry.metadata),
                ),
            )
            conn.commit()

        logger.warning(
            f"DLQ entry created: {entry.id} - {failure_reason.value} - {email_subject}"
        )

        # Trigger alerts
        for callback in self._alert_callbacks:
            try:
                callback(entry)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

        return entry

    def get_entry(self, entry_id: str) -> Optional[DLQEntry]:
        """Get a DLQ entry by ID."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM dlq_entries WHERE id = ?", (entry_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_entry(row)

    def list_entries(
        self,
        status: Optional[DLQStatus] = None,
        failure_reason: Optional[FailureReason] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DLQEntry]:
        """
        List DLQ entries with optional filters.
        """
        with get_connection() as conn:
            query = "SELECT * FROM dlq_entries WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status.value)

            if failure_reason:
                query += " AND failure_reason = ?"
                params.append(failure_reason.value)

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            return [self._row_to_entry(row) for row in rows]

    def get_pending_entries(self) -> list[DLQEntry]:
        """Get entries that are pending and ready for retry."""
        with get_connection() as conn:
            now = datetime.now(timezone.utc).isoformat()

            rows = conn.execute(
                """
                SELECT * FROM dlq_entries
                WHERE status = 'pending'
                AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY created_at ASC
                """,
                (now,),
            ).fetchall()

            return [self._row_to_entry(row) for row in rows]

    def retry_entry(
        self,
        entry_id: str,
        processor: Optional[Callable[[DLQEntry], bool]] = None,
    ) -> bool:
        """
        Retry processing a DLQ entry.

        Args:
            entry_id: Entry to retry
            processor: Optional callback to process the entry

        Returns:
            True if retry succeeded, False otherwise
        """
        entry = self.get_entry(entry_id)
        if not entry:
            logger.warning(f"DLQ entry not found: {entry_id}")
            return False

        if entry.status not in (DLQStatus.PENDING, DLQStatus.EXHAUSTED):
            logger.warning(f"DLQ entry {entry_id} not in retryable state: {entry.status}")
            return False

        # Update status to retrying
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE dlq_entries
                SET status = 'retrying', updated_at = ?
                WHERE id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), entry_id),
            )
            conn.commit()

        # Try to process
        success = False
        if processor:
            try:
                success = processor(entry)
            except Exception as e:
                logger.error(f"Retry processing failed for {entry_id}: {e}")
                success = False

        if success:
            # Mark as resolved
            self.resolve_entry(entry_id, resolved_by="auto_retry")
        else:
            # Increment retry count
            new_retry_count = entry.retry_count + 1
            new_status = (
                DLQStatus.EXHAUSTED
                if new_retry_count >= entry.max_retries
                else DLQStatus.PENDING
            )

            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE dlq_entries
                    SET status = ?, retry_count = ?, next_retry_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        new_status.value,
                        new_retry_count,
                        calculate_next_retry(new_retry_count).isoformat(),
                        datetime.now(timezone.utc).isoformat(),
                        entry_id,
                    ),
                )
                conn.commit()

        return success

    def resolve_entry(
        self,
        entry_id: str,
        resolved_by: str,
        resolution_notes: Optional[str] = None,
    ) -> bool:
        """
        Mark a DLQ entry as resolved.

        Args:
            entry_id: Entry to resolve
            resolved_by: User/system that resolved it
            resolution_notes: Optional notes about resolution

        Returns:
            True if resolved successfully
        """
        with get_connection() as conn:
            now = datetime.now(timezone.utc).isoformat()

            result = conn.execute(
                """
                UPDATE dlq_entries
                SET status = 'resolved',
                    resolved_at = ?,
                    resolved_by = ?,
                    resolution_notes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, resolved_by, resolution_notes, now, entry_id),
            )
            conn.commit()

            if result.rowcount > 0:
                logger.info(f"DLQ entry resolved: {entry_id} by {resolved_by}")
                return True

            return False

    def get_summary(self) -> DLQSummary:
        """Get summary statistics for the DLQ."""
        with get_connection() as conn:
            summary = DLQSummary()

            # Total count
            row = conn.execute("SELECT COUNT(*) FROM dlq_entries").fetchone()
            summary.total_entries = row[0]

            # Count by status
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM dlq_entries GROUP BY status"
            ).fetchall()

            for row in rows:
                status = row[0]
                count = row[1]
                if status == "pending":
                    summary.pending_count = count
                elif status == "retrying":
                    summary.retrying_count = count
                elif status == "resolved":
                    summary.resolved_count = count
                elif status == "exhausted":
                    summary.exhausted_count = count

            # Count by reason
            rows = conn.execute(
                """
                SELECT failure_reason, COUNT(*)
                FROM dlq_entries
                WHERE status IN ('pending', 'exhausted')
                GROUP BY failure_reason
                """
            ).fetchall()

            summary.by_reason = {row[0]: row[1] for row in rows}

            # Oldest pending
            row = conn.execute(
                """
                SELECT MIN(created_at) FROM dlq_entries
                WHERE status = 'pending'
                """
            ).fetchone()

            if row[0]:
                summary.oldest_pending_at = datetime.fromisoformat(row[0])

            return summary

    def register_alert_callback(self, callback: Callable[[DLQEntry], None]):
        """Register a callback to be called when entries are added."""
        self._alert_callbacks.append(callback)

    def _row_to_entry(self, row) -> DLQEntry:
        """Convert a database row to DLQEntry."""
        return DLQEntry(
            id=row[0],
            email_id=row[1],
            email_subject=row[2],
            email_from=row[3],
            email_date=datetime.fromisoformat(row[4]) if row[4] else None,
            failure_reason=FailureReason(row[5]),
            failure_details=row[6],
            attachment_filename=row[7],
            attachment_hash=row[8],
            status=DLQStatus(row[9]),
            retry_count=row[10],
            max_retries=row[11],
            next_retry_at=datetime.fromisoformat(row[12]) if row[12] else None,
            created_at=datetime.fromisoformat(row[13]),
            updated_at=datetime.fromisoformat(row[14]),
            resolved_at=datetime.fromisoformat(row[15]) if row[15] else None,
            resolved_by=row[16],
            resolution_notes=row[17],
            metadata=json.loads(row[18]) if row[18] else {},
        )


# Singleton instance
_dlq_service: Optional[DLQService] = None
_dlq_lock = threading.Lock()


def get_dlq_service() -> DLQService:
    """Get or create the DLQ service singleton."""
    global _dlq_service

    with _dlq_lock:
        if _dlq_service is None:
            _dlq_service = DLQService()

        return _dlq_service


def compute_dedup_hash(email_message_id: str, attachment_bytes: bytes) -> str:
    """
    Compute deduplication hash for email + attachment.

    Args:
        email_message_id: Email Message-ID header
        attachment_bytes: Raw attachment bytes

    Returns:
        SHA256 hash string
    """
    attachment_hash = hashlib.sha256(attachment_bytes).hexdigest()
    content = f"{email_message_id}:{attachment_hash}"
    return hashlib.sha256(content.encode()).hexdigest()
