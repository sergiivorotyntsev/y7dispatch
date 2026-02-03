"""
Audit Log Module (M3.Export)

Provides comprehensive audit trail for all export operations.
Tracks request/response details, ETag handling, and duplicate detection.

Features:
- Full audit trail per export event
- Payload hashing for change detection
- Request ID tracking
- ETag lifecycle tracking
- No sensitive data (tokens redacted)
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from api.database import get_connection


class AuditEventType(str, Enum):
    """Types of audit events."""

    UPLOAD = "UPLOAD"
    EXTRACT = "EXTRACT"
    OCR = "OCR"
    RESOLVE = "RESOLVE"
    VALIDATE = "VALIDATE"
    POST_CREATE = "POST_CREATE"
    POST_UPDATE = "POST_UPDATE"
    POST_FAIL = "POST_FAIL"
    POST_RETRY = "POST_RETRY"
    POST_DUPLICATE = "POST_DUPLICATE"
    ETAG_REFRESH = "ETAG_REFRESH"
    ETAG_CONFLICT = "ETAG_CONFLICT"
    BATCH_START = "BATCH_START"
    BATCH_END = "BATCH_END"
    CORRECTION = "CORRECTION"


@dataclass
class AuditEvent:
    """An audit event record."""

    id: int = None
    event_type: str = None
    entity_type: str = None  # document, run, listing
    entity_id: int = None
    run_id: Optional[int] = None
    document_id: Optional[int] = None
    request_id: Optional[str] = None
    payload_hash: Optional[str] = None
    metadata_json: Optional[dict] = None
    response_status: Optional[int] = None
    response_snippet: Optional[str] = None
    cd_listing_id: Optional[str] = None
    etag_before: Optional[str] = None
    etag_after: Optional[str] = None
    created_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "run_id": self.run_id,
            "document_id": self.document_id,
            "request_id": self.request_id,
            "payload_hash": self.payload_hash,
            "metadata": self.metadata_json,
            "response_status": self.response_status,
            "response_snippet": self.response_snippet,
            "cd_listing_id": self.cd_listing_id,
            "etag_before": self.etag_before,
            "etag_after": self.etag_after,
            "created_at": self.created_at,
        }


def _init_audit_table():
    """Initialize audit_events table."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entity_type TEXT,
                entity_id INTEGER,
                run_id INTEGER,
                document_id INTEGER,
                request_id TEXT,
                payload_hash TEXT,
                metadata_json TEXT,
                response_status INTEGER,
                response_snippet TEXT,
                cd_listing_id TEXT,
                etag_before TEXT,
                etag_after TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Indexes for common queries
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_run
            ON audit_events(run_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_document
            ON audit_events(document_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_listing
            ON audit_events(cd_listing_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_type_time
            ON audit_events(event_type, created_at)
        """)
        conn.commit()


class AuditLogRepository:
    """Repository for audit log operations."""

    @staticmethod
    def create(
        event_type: str,
        entity_type: str = None,
        entity_id: int = None,
        run_id: int = None,
        document_id: int = None,
        request_id: str = None,
        payload_hash: str = None,
        metadata: dict = None,
        response_status: int = None,
        response_snippet: str = None,
        cd_listing_id: str = None,
        etag_before: str = None,
        etag_after: str = None,
    ) -> int:
        """Create a new audit event."""
        _init_audit_table()

        # Redact sensitive info from metadata
        if metadata:
            metadata = _redact_sensitive(metadata)

        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO audit_events
                   (event_type, entity_type, entity_id, run_id, document_id,
                    request_id, payload_hash, metadata_json, response_status,
                    response_snippet, cd_listing_id, etag_before, etag_after)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_type,
                    entity_type,
                    entity_id,
                    run_id,
                    document_id,
                    request_id,
                    payload_hash,
                    json.dumps(metadata) if metadata else None,
                    response_status,
                    response_snippet[:500] if response_snippet else None,
                    cd_listing_id,
                    etag_before,
                    etag_after,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_run(run_id: int) -> list[AuditEvent]:
        """Get all audit events for an extraction run."""
        _init_audit_table()

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE run_id = ? ORDER BY created_at ASC", (run_id,)
            ).fetchall()

        events = []
        for row in rows:
            data = dict(row)
            if data.get("metadata_json"):
                data["metadata_json"] = json.loads(data["metadata_json"])
            events.append(AuditEvent(**data))

        return events

    @staticmethod
    def get_by_listing(cd_listing_id: str) -> list[AuditEvent]:
        """Get all audit events for a CD listing."""
        _init_audit_table()

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE cd_listing_id = ? ORDER BY created_at ASC",
                (cd_listing_id,),
            ).fetchall()

        events = []
        for row in rows:
            data = dict(row)
            if data.get("metadata_json"):
                data["metadata_json"] = json.loads(data["metadata_json"])
            events.append(AuditEvent(**data))

        return events

    @staticmethod
    def get_recent(
        event_type: str = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Get recent audit events."""
        _init_audit_table()

        sql = "SELECT * FROM audit_events WHERE 1=1"
        params = []

        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        events = []
        for row in rows:
            data = dict(row)
            if data.get("metadata_json"):
                data["metadata_json"] = json.loads(data["metadata_json"])
            events.append(AuditEvent(**data))

        return events


def _redact_sensitive(data: dict) -> dict:
    """Redact sensitive information from data."""
    sensitive_keys = {"token", "password", "secret", "api_key", "authorization"}
    result = {}

    for key, value in data.items():
        key_lower = key.lower()
        if any(s in key_lower for s in sensitive_keys):
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = _redact_sensitive(value)
        elif isinstance(value, list):
            result[key] = [_redact_sensitive(v) if isinstance(v, dict) else v for v in value]
        else:
            result[key] = value

    return result


def compute_payload_hash(payload: dict) -> str:
    """Compute deterministic hash of payload for change detection."""
    # Sort keys for deterministic ordering
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def generate_request_id() -> str:
    """Generate a unique request ID for tracing."""
    return str(uuid.uuid4())[:12]


# Convenience functions for logging audit events


def log_post_create(
    run_id: int,
    payload: dict,
    response_status: int,
    response_body: dict,
    cd_listing_id: str = None,
    etag: str = None,
    request_id: str = None,
) -> int:
    """Log a successful POST create event."""
    return AuditLogRepository.create(
        event_type=AuditEventType.POST_CREATE.value,
        entity_type="listing",
        run_id=run_id,
        request_id=request_id or generate_request_id(),
        payload_hash=compute_payload_hash(payload),
        metadata={
            "vehicles_count": len(payload.get("vehicles", [])),
            "stops_count": len(payload.get("stops", [])),
            "external_id": payload.get("externalId"),
        },
        response_status=response_status,
        response_snippet=json.dumps(response_body)[:500] if response_body else None,
        cd_listing_id=cd_listing_id,
        etag_after=etag,
    )


def log_post_update(
    run_id: int,
    payload: dict,
    response_status: int,
    response_body: dict,
    cd_listing_id: str,
    etag_before: str = None,
    etag_after: str = None,
    request_id: str = None,
) -> int:
    """Log a successful PUT update event."""
    return AuditLogRepository.create(
        event_type=AuditEventType.POST_UPDATE.value,
        entity_type="listing",
        run_id=run_id,
        request_id=request_id or generate_request_id(),
        payload_hash=compute_payload_hash(payload),
        metadata={
            "vehicles_count": len(payload.get("vehicles", [])),
            "external_id": payload.get("externalId"),
        },
        response_status=response_status,
        response_snippet=json.dumps(response_body)[:500] if response_body else None,
        cd_listing_id=cd_listing_id,
        etag_before=etag_before,
        etag_after=etag_after,
    )


def log_post_fail(
    run_id: int,
    payload: dict,
    response_status: int,
    error_message: str,
    cd_listing_id: str = None,
    request_id: str = None,
) -> int:
    """Log a failed POST/PUT event."""
    return AuditLogRepository.create(
        event_type=AuditEventType.POST_FAIL.value,
        entity_type="listing",
        run_id=run_id,
        request_id=request_id or generate_request_id(),
        payload_hash=compute_payload_hash(payload),
        metadata={"error": error_message},
        response_status=response_status,
        response_snippet=error_message[:500],
        cd_listing_id=cd_listing_id,
    )


def log_etag_conflict(
    run_id: int,
    cd_listing_id: str,
    etag_used: str,
    request_id: str = None,
) -> int:
    """Log an ETag conflict (412) event."""
    return AuditLogRepository.create(
        event_type=AuditEventType.ETAG_CONFLICT.value,
        entity_type="listing",
        run_id=run_id,
        request_id=request_id or generate_request_id(),
        metadata={"etag_used": etag_used},
        response_status=412,
        cd_listing_id=cd_listing_id,
        etag_before=etag_used,
    )


def log_etag_refresh(
    run_id: int,
    cd_listing_id: str,
    old_etag: str,
    new_etag: str,
    request_id: str = None,
) -> int:
    """Log an ETag refresh event."""
    return AuditLogRepository.create(
        event_type=AuditEventType.ETAG_REFRESH.value,
        entity_type="listing",
        run_id=run_id,
        request_id=request_id or generate_request_id(),
        cd_listing_id=cd_listing_id,
        etag_before=old_etag,
        etag_after=new_etag,
    )


def log_duplicate_detected(
    run_id: int,
    external_id: str,
    existing_listing_id: str,
    request_id: str = None,
) -> int:
    """Log a duplicate listing detection event."""
    return AuditLogRepository.create(
        event_type=AuditEventType.POST_DUPLICATE.value,
        entity_type="listing",
        run_id=run_id,
        request_id=request_id or generate_request_id(),
        metadata={
            "external_id": external_id,
            "existing_listing_id": existing_listing_id,
        },
        cd_listing_id=existing_listing_id,
    )


def get_audit_trail(run_id: int) -> list[dict]:
    """Get complete audit trail for an extraction run."""
    events = AuditLogRepository.get_by_run(run_id)
    return [e.to_dict() for e in events]
