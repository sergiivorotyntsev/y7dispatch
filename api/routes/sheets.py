"""
Sheets Override API — Webhook endpoint for Google Sheets → DB field overrides.

Receives field corrections from Google Sheets and stores them as
USER_OVERRIDE values in the DB (source of truth).
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.models import ExportJobRepository, ReviewItemRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sheets", tags=["Sheets"])


class SheetOverrideRequest(BaseModel):
    """Request body for a Sheets field override."""

    dispatch_id: str = Field(..., description="CD dispatch/export job ID")
    field: str = Field(..., description="Field key to override (source_key or cd_key)")
    new_value: str = Field(..., description="New value from Sheets")


class SheetOverrideResponse(BaseModel):
    """Response for a Sheets field override."""

    status: str
    dispatch_id: str
    field: str
    old_value: Optional[str] = None
    new_value: str
    review_item_id: Optional[int] = None


@router.post("/override", response_model=SheetOverrideResponse)
async def sheets_override(data: SheetOverrideRequest):
    """
    Accept a field override from Google Sheets and apply it to the DB.

    Looks up the export job by dispatch_id, finds the corresponding
    review item by field key, and sets corrected_value as USER_OVERRIDE.
    """
    # Find export job by dispatch_id
    job = ExportJobRepository.get_by_dispatch_id(data.dispatch_id)
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Export job not found for dispatch_id={data.dispatch_id}",
        )

    run_id = job.run_id

    # Find the review item by field key (try source_key, then cd_key)
    items = ReviewItemRepository.get_by_run(run_id)
    target = None
    for item in items:
        if item.source_key == data.field or item.cd_key == data.field:
            target = item
            break

    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"Review item not found for field={data.field} in run_id={run_id}",
        )

    old_value = target.corrected_value or target.predicted_value

    # Apply override
    ReviewItemRepository.update(
        target.id,
        corrected_value=data.new_value,
        is_match_ok=False,
        status="override",
    )

    logger.info(
        f"Sheets override applied: dispatch_id={data.dispatch_id} "
        f"field={data.field} old={old_value} new={data.new_value}"
    )

    return SheetOverrideResponse(
        status="applied",
        dispatch_id=data.dispatch_id,
        field=data.field,
        old_value=old_value,
        new_value=data.new_value,
        review_item_id=target.id,
    )
