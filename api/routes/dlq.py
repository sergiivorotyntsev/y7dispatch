"""
DLQ (Dead Letter Queue) API Routes (Phase 0.7)

Provides endpoints for managing failed email processing entries.

Endpoints:
    GET  /api/dlq/summary        - Get DLQ summary statistics
    GET  /api/dlq/entries        - List DLQ entries with filters
    GET  /api/dlq/entries/{id}   - Get single DLQ entry
    POST /api/dlq/entries/{id}/retry   - Retry processing
    POST /api/dlq/entries/{id}/resolve - Mark as resolved
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.dlq import (
    DLQEntry,
    DLQService,
    DLQStatus,
    DLQSummary,
    FailureReason,
    get_dlq_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dlq", tags=["dlq"])


# =============================================================================
# Response Models
# =============================================================================


class DLQEntryResponse(BaseModel):
    """Response model for a DLQ entry."""

    id: str
    email_id: str
    email_subject: str
    email_from: Optional[str]
    email_date: Optional[str]
    failure_reason: str
    failure_details: str
    attachment_filename: Optional[str]
    status: str
    retry_count: int
    max_retries: int
    next_retry_at: Optional[str]
    created_at: str
    updated_at: str
    resolved_at: Optional[str]
    resolved_by: Optional[str]
    resolution_notes: Optional[str]


class DLQSummaryResponse(BaseModel):
    """Response model for DLQ summary."""

    total_entries: int
    pending_count: int
    retrying_count: int
    resolved_count: int
    exhausted_count: int
    by_reason: dict
    oldest_pending_at: Optional[str]


class DLQListResponse(BaseModel):
    """Response model for DLQ entry list."""

    entries: list[DLQEntryResponse]
    total: int
    has_more: bool


class ResolveRequest(BaseModel):
    """Request to resolve a DLQ entry."""

    resolved_by: str
    resolution_notes: Optional[str] = None


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/summary", response_model=DLQSummaryResponse)
async def get_dlq_summary():
    """
    Get DLQ summary statistics.

    Returns counts by status and failure reason.
    """
    dlq = get_dlq_service()
    summary = dlq.get_summary()

    return DLQSummaryResponse(
        total_entries=summary.total_entries,
        pending_count=summary.pending_count,
        retrying_count=summary.retrying_count,
        resolved_count=summary.resolved_count,
        exhausted_count=summary.exhausted_count,
        by_reason=summary.by_reason,
        oldest_pending_at=(
            summary.oldest_pending_at.isoformat()
            if summary.oldest_pending_at
            else None
        ),
    )


@router.get("/entries", response_model=DLQListResponse)
async def list_dlq_entries(
    status: Optional[str] = Query(None, description="Filter by status"),
    failure_reason: Optional[str] = Query(None, description="Filter by failure reason"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    List DLQ entries with optional filters.

    Supports filtering by status and failure reason.
    """
    dlq = get_dlq_service()

    # Parse filters
    status_filter = None
    if status:
        try:
            status_filter = DLQStatus(status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    reason_filter = None
    if failure_reason:
        try:
            reason_filter = FailureReason(failure_reason)
        except ValueError:
            raise HTTPException(400, f"Invalid failure_reason: {failure_reason}")

    entries = dlq.list_entries(
        status=status_filter,
        failure_reason=reason_filter,
        limit=limit + 1,  # Fetch one extra to check has_more
        offset=offset,
    )

    has_more = len(entries) > limit
    if has_more:
        entries = entries[:limit]

    return DLQListResponse(
        entries=[_entry_to_response(e) for e in entries],
        total=len(entries),
        has_more=has_more,
    )


@router.get("/entries/{entry_id}", response_model=DLQEntryResponse)
async def get_dlq_entry(entry_id: str):
    """
    Get a single DLQ entry by ID.
    """
    dlq = get_dlq_service()
    entry = dlq.get_entry(entry_id)

    if not entry:
        raise HTTPException(404, f"DLQ entry not found: {entry_id}")

    return _entry_to_response(entry)


@router.post("/entries/{entry_id}/retry")
async def retry_dlq_entry(entry_id: str):
    """
    Retry processing a DLQ entry.

    Triggers reprocessing of the failed email/document.
    """
    dlq = get_dlq_service()
    entry = dlq.get_entry(entry_id)

    if not entry:
        raise HTTPException(404, f"DLQ entry not found: {entry_id}")

    if entry.status not in (DLQStatus.PENDING, DLQStatus.EXHAUSTED):
        raise HTTPException(
            400, f"Entry cannot be retried in status: {entry.status.value}"
        )

    # For now, just increment retry count
    # Actual processing would be done by a background worker
    success = dlq.retry_entry(entry_id)

    return {
        "success": success,
        "message": "Retry initiated" if success else "Retry failed",
        "entry_id": entry_id,
    }


@router.post("/entries/{entry_id}/resolve")
async def resolve_dlq_entry(entry_id: str, request: ResolveRequest):
    """
    Mark a DLQ entry as resolved.

    Used when issue is manually addressed or intentionally skipped.
    """
    dlq = get_dlq_service()
    entry = dlq.get_entry(entry_id)

    if not entry:
        raise HTTPException(404, f"DLQ entry not found: {entry_id}")

    if entry.status == DLQStatus.RESOLVED:
        raise HTTPException(400, "Entry is already resolved")

    success = dlq.resolve_entry(
        entry_id=entry_id,
        resolved_by=request.resolved_by,
        resolution_notes=request.resolution_notes,
    )

    if not success:
        raise HTTPException(500, "Failed to resolve entry")

    return {
        "success": True,
        "message": "Entry resolved",
        "entry_id": entry_id,
        "resolved_by": request.resolved_by,
    }


@router.get("/pending")
async def get_pending_entries():
    """
    Get all entries pending retry.

    Useful for background workers to pick up work.
    """
    dlq = get_dlq_service()
    entries = dlq.get_pending_entries()

    return {
        "count": len(entries),
        "entries": [_entry_to_response(e) for e in entries],
    }


# =============================================================================
# Helpers
# =============================================================================


def _entry_to_response(entry: DLQEntry) -> DLQEntryResponse:
    """Convert DLQEntry to response model."""
    return DLQEntryResponse(
        id=entry.id,
        email_id=entry.email_id,
        email_subject=entry.email_subject,
        email_from=entry.email_from,
        email_date=entry.email_date.isoformat() if entry.email_date else None,
        failure_reason=entry.failure_reason.value,
        failure_details=entry.failure_details,
        attachment_filename=entry.attachment_filename,
        status=entry.status.value,
        retry_count=entry.retry_count,
        max_retries=entry.max_retries,
        next_retry_at=entry.next_retry_at.isoformat() if entry.next_retry_at else None,
        created_at=entry.created_at.isoformat(),
        updated_at=entry.updated_at.isoformat(),
        resolved_at=entry.resolved_at.isoformat() if entry.resolved_at else None,
        resolved_by=entry.resolved_by,
        resolution_notes=entry.resolution_notes,
    )
