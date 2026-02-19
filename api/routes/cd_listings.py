"""
Central Dispatch Listings endpoints.

  GET  /api/documents/{id}/cd-payload   — Preview the CD API v2 payload
  POST /api/central-dispatch/listings   — Push listing to CD (saves snapshot + listingId)
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from models.cd_enums import LUXURY_MAKES
from models.cd_listing import CDListingDraft, CDPayloadPreviewResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Central Dispatch"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_draft_from_run(run_id: int, warehouse_code: str | None = None) -> tuple[dict, list[str]]:
    """
    Build a CDListingDraft dict from an extraction run.

    Re-uses the existing field resolution pipeline from exports.py,
    then validates through CDListingDraft Pydantic model.

    Returns (payload_dict, validation_errors).
    """
    from api.routes.exports import build_cd_payload

    raw_payload, legacy_errors = build_cd_payload(run_id, warehouse_code)
    if not raw_payload:
        return {}, legacy_errors

    # Separate warnings from blocking errors
    errors: list[str] = [e for e in legacy_errors if not e.startswith("[WARNING]")]
    if errors:
        return raw_payload, errors

    # Enrich: apply trailer type rule based on vehicle make
    vehicles = raw_payload.get("vehicles", [])
    trailer_type = raw_payload.get("trailerType", "OPEN")
    for v in vehicles:
        make_upper = (v.get("make") or "").upper()
        if make_upper in LUXURY_MAKES:
            trailer_type = "ENCLOSED"
            break
    raw_payload["trailerType"] = trailer_type

    # Ensure availableDate / expirationDate are present
    if "availableDate" not in raw_payload or not raw_payload["availableDate"]:
        raw_payload["availableDate"] = date.today().isoformat()
    if "expirationDate" not in raw_payload or not raw_payload["expirationDate"]:
        avail = date.fromisoformat(str(raw_payload["availableDate"]))
        raw_payload["expirationDate"] = (avail + timedelta(days=14)).isoformat()

    # Ensure stops have locationType
    for stop in raw_payload.get("stops", []):
        if "locationType" not in stop:
            stop["locationType"] = "AUCTION" if stop.get("stopNumber") == 1 else "BUSINESS"

    # Ensure price.cod exists
    price = raw_payload.get("price", {})
    if "cod" not in price or price["cod"] is None:
        price["cod"] = {
            "amount": price.get("total", 0),
            "paymentMethod": "CASH_CERTIFIED_FUNDS",
            "paymentLocation": "DELIVERY",
        }
        raw_payload["price"] = price

    # Add default marketplace if missing
    if not raw_payload.get("marketplaces"):
        try:
            from services.credential_store import get_credential_for_service
            cd_creds = get_credential_for_service("cd_api")
            _mp_id = int(cd_creds.get("marketplace_id", "10000")) if cd_creds else 10000
        except Exception:
            _mp_id = 10000
        raw_payload["marketplaces"] = [{"marketplaceId": _mp_id, "searchable": True}]

    # Validate through Pydantic model
    try:
        draft = CDListingDraft(**raw_payload)
        return draft.to_api_dict(), []
    except ValidationError as exc:
        pydantic_errors = [
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        ]
        return raw_payload, pydantic_errors


# ---------------------------------------------------------------------------
# Preview endpoint
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    warehouse_code: str | None = None


@router.get("/api/documents/{document_id}/cd-payload", response_model=CDPayloadPreviewResponse)
async def preview_cd_payload(document_id: int, warehouse_code: str | None = None):
    """
    Preview the CD API v2 payload for a document.

    Runs the full field resolution + validation pipeline and returns
    the payload that *would* be sent to Central Dispatch.
    """
    from api.models import DocumentRepository, ExtractionRunRepository

    doc = DocumentRepository.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    # Find the latest completed extraction run
    runs = ExtractionRunRepository.get_by_document(document_id)
    completed = [r for r in runs if r.status == "completed"]
    if not completed:
        raise HTTPException(
            status_code=400,
            detail=f"No completed extraction run for document {document_id}",
        )

    run = completed[-1]  # latest
    payload, errors = _build_draft_from_run(run.id, warehouse_code)

    return CDPayloadPreviewResponse(
        document_id=document_id,
        run_id=run.id,
        payload=payload,
        validation_errors=errors,
        is_valid=len(errors) == 0,
    )


# ---------------------------------------------------------------------------
# Push endpoint
# ---------------------------------------------------------------------------


class PushListingRequest(BaseModel):
    """Request body for pushing a listing to CD."""

    document_id: int
    warehouse_code: str | None = None
    dry_run: bool = Field(default=False, description="Validate only, don't send")


class PushListingResponse(BaseModel):
    """Response after pushing (or dry-running) a listing."""

    success: bool
    listing_id: str | None = None
    external_id: str | None = None
    location: str | None = None
    etag: str | None = None
    payload_snapshot: dict = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)
    message: str = ""


@router.post("/api/central-dispatch/listings", response_model=PushListingResponse)
async def push_listing(req: PushListingRequest):
    """
    Push a listing to Central Dispatch.

    1. Builds and validates the payload via CDListingDraft
    2. If dry_run=True, returns the validated payload without sending
    3. Otherwise sends to CD API, saves snapshot + listingId + etag
    """
    from api.models import DocumentRepository, ExtractionRunRepository

    doc = DocumentRepository.get_by_id(req.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {req.document_id} not found")

    runs = ExtractionRunRepository.get_by_document(req.document_id)
    completed = [r for r in runs if r.status == "completed"]
    if not completed:
        raise HTTPException(
            status_code=400,
            detail=f"No completed extraction run for document {req.document_id}",
        )

    run = completed[-1]
    payload, errors = _build_draft_from_run(run.id, req.warehouse_code)

    if errors:
        return PushListingResponse(
            success=False,
            payload_snapshot=payload,
            validation_errors=errors,
            message=f"Validation failed: {len(errors)} error(s)",
        )

    if req.dry_run:
        return PushListingResponse(
            success=True,
            external_id=payload.get("externalId"),
            payload_snapshot=payload,
            message="Dry run: payload is valid, not sent to CD",
        )

    # Actually send to CD
    from api.cd_client import CDClient

    client = CDClient()
    response = client.create_listing(payload)

    if not response.success:
        # Save failed attempt
        _save_listing_snapshot(
            run_id=run.id,
            payload=payload,
            status="failed",
            error=response.error,
        )
        return PushListingResponse(
            success=False,
            external_id=payload.get("externalId"),
            payload_snapshot=payload,
            validation_errors=[response.error or "Unknown CD API error"],
            message=f"CD API error (HTTP {response.status_code})",
        )

    # Extract listingId from Location header (last segment)
    listing_id = response.listing_id or ""
    location = ""
    etag = response.etag

    # Save successful listing
    _save_listing_snapshot(
        run_id=run.id,
        payload=payload,
        status="success",
        cd_listing_id=listing_id,
        etag=etag,
    )

    return PushListingResponse(
        success=True,
        listing_id=listing_id,
        external_id=payload.get("externalId"),
        location=location,
        etag=etag,
        payload_snapshot=payload,
        message=f"Listing created: {listing_id}",
    )


def _save_listing_snapshot(
    run_id: int,
    payload: dict,
    status: str,
    cd_listing_id: str | None = None,
    etag: str | None = None,
    error: str | None = None,
) -> None:
    """Persist the payload snapshot and CD response to cd_listings table."""
    from api.routes.exports import _init_cd_listings_table, save_cd_listing_info

    _init_cd_listings_table()

    if cd_listing_id:
        save_cd_listing_info(
            run_id=run_id,
            cd_listing_id=cd_listing_id,
            etag=etag,
            external_id=payload.get("externalId", ""),
        )

    # Also log to export_jobs for audit trail
    from api.database import get_connection

    try:
        with get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO export_jobs
                   (run_id, target, status, payload_json, error_message, created_at)
                   VALUES (?, 'central_dispatch', ?, ?, ?, CURRENT_TIMESTAMP)""",
                (run_id, status, json.dumps(payload), error),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to save export job for run %d", run_id)
