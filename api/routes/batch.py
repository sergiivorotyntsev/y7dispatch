"""
Batch Operations API Routes

Bulk approve, hold, and archive operations for documents/extraction runs.
Reuses existing single-item logic from reviews.py and documents.py.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.database import get_connection
from api.models import DocumentRepository, ExtractionRunRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/batch", tags=["Batch Operations"])

MAX_BATCH_SIZE = 50


# --- Request / Response Models ---

class BatchApproveRequest(BaseModel):
    run_ids: List[int] = Field(..., max_length=MAX_BATCH_SIZE)


class BatchHoldRequest(BaseModel):
    document_ids: List[int] = Field(..., max_length=MAX_BATCH_SIZE)
    reason: str
    note: Optional[str] = None


class BatchArchiveRequest(BaseModel):
    document_ids: List[int] = Field(..., max_length=MAX_BATCH_SIZE)


class ItemResult(BaseModel):
    id: int
    success: bool
    error: Optional[str] = None


class BatchResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: List[ItemResult]


# --- Endpoints ---

@router.post("/approve", response_model=BatchResponse)
async def batch_approve(request: BatchApproveRequest):
    """Approve multiple extraction runs in bulk.

    Reuses the same logic as POST /api/review/{run_id}/approve:
    sets extraction_runs.status = 'reviewed' and review_items.status = 'approved'.
    """
    if len(request.run_ids) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail=f"Max {MAX_BATCH_SIZE} items per batch")

    results = []
    for run_id in request.run_ids:
        try:
            run = ExtractionRunRepository.get_by_id(run_id)
            if not run:
                results.append(ItemResult(id=run_id, success=False, error="Extraction run not found"))
                continue

            if run.status == "reviewed":
                results.append(ItemResult(id=run_id, success=True, error=None))
                continue

            ExtractionRunRepository.update(run_id, status="reviewed")

            with get_connection() as conn:
                conn.execute(
                    "UPDATE review_items SET status = 'approved' WHERE run_id = ? AND status = 'pending'",
                    (run_id,),
                )
                conn.commit()

            results.append(ItemResult(id=run_id, success=True))
        except Exception as e:
            logger.warning("Batch approve failed for run %d: %s", run_id, e)
            results.append(ItemResult(id=run_id, success=False, error=str(e)))

    succeeded = sum(1 for r in results if r.success)
    return BatchResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


@router.post("/hold", response_model=BatchResponse)
async def batch_hold(request: BatchHoldRequest):
    """Put multiple documents on hold in bulk.

    Reuses the same logic as POST /api/documents/{id}/set-hold.
    """
    if len(request.document_ids) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail=f"Max {MAX_BATCH_SIZE} items per batch")

    now = datetime.now(timezone.utc).isoformat() + "Z"
    results = []

    for doc_id in request.document_ids:
        try:
            doc = DocumentRepository.get_by_id(doc_id)
            if not doc:
                results.append(ItemResult(id=doc_id, success=False, error="Document not found"))
                continue

            with get_connection() as conn:
                conn.execute(
                    "UPDATE documents SET hold_reason = ?, hold_note = ?, hold_since = ? WHERE id = ?",
                    (request.reason, request.note, now, doc_id),
                )
                conn.commit()

            results.append(ItemResult(id=doc_id, success=True))
        except Exception as e:
            logger.warning("Batch hold failed for doc %d: %s", doc_id, e)
            results.append(ItemResult(id=doc_id, success=False, error=str(e)))

    succeeded = sum(1 for r in results if r.success)
    return BatchResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )


@router.post("/archive", response_model=BatchResponse)
async def batch_archive(request: BatchArchiveRequest):
    """Archive multiple documents in bulk.

    Reuses the same logic as POST /api/documents/{id}/archive.
    """
    if len(request.document_ids) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail=f"Max {MAX_BATCH_SIZE} items per batch")

    now = datetime.now(timezone.utc).isoformat() + "Z"
    results = []

    for doc_id in request.document_ids:
        try:
            doc = DocumentRepository.get_by_id(doc_id)
            if not doc:
                results.append(ItemResult(id=doc_id, success=False, error="Document not found"))
                continue

            with get_connection() as conn:
                conn.execute(
                    "UPDATE documents SET archived_at = ? WHERE id = ?",
                    (now, doc_id),
                )
                conn.commit()

            results.append(ItemResult(id=doc_id, success=True))
        except Exception as e:
            logger.warning("Batch archive failed for doc %d: %s", doc_id, e)
            results.append(ItemResult(id=doc_id, success=False, error=str(e)))

    succeeded = sum(1 for r in results if r.success)
    return BatchResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results,
    )
