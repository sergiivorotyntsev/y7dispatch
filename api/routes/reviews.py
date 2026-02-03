"""
Review API Routes

Manage review items and submit corrections for training.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.models import (
    AuctionTypeRepository,
    DocumentRepository,
    ExtractionRunRepository,
    FieldEvidenceRepository,
    LayoutBlockRepository,
    ReviewItemRepository,
    TrainingExampleRepository,
)

router = APIRouter(prefix="/api/review", tags=["Review"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class ReviewItemResponse(BaseModel):
    """A single review item."""

    id: int
    run_id: int
    source_key: str
    internal_key: Optional[str] = None
    cd_key: Optional[str] = None
    predicted_value: Optional[str] = None
    corrected_value: Optional[str] = None
    is_match_ok: bool = False
    export_field: bool = True
    confidence: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class ReviewRunResponse(BaseModel):
    """Response for a review run with all items."""

    run_id: int
    document_id: int
    document_filename: Optional[str] = None
    auction_type_id: int
    auction_type_code: Optional[str] = None
    status: str
    extraction_score: Optional[float] = None
    items: list[ReviewItemResponse]
    reviewed_count: int
    total_count: int


class ReviewItemUpdate(BaseModel):
    """Update a single review item. Item_id is REQUIRED for proper binding."""

    item_id: int = Field(..., description="Review item ID (required)")
    corrected_value: Optional[str] = Field(
        None, description="Corrected value (if different from predicted)"
    )
    is_match_ok: bool = Field(..., description="True if predicted value is correct")
    export_field: bool = Field(True, description="Include this field in export")


class ReviewSubmitRequest(BaseModel):
    """Submit review corrections for a run."""

    run_id: int = Field(..., description="Extraction run ID")
    items: list[ReviewItemUpdate] = Field(..., description="Updated review items")
    mark_as_reviewed: bool = Field(True, description="Mark run as reviewed after submit")


class ReviewSubmitResponse(BaseModel):
    """Response after submitting review."""

    run_id: int
    status: str
    items_updated: int
    training_examples_created: int
    message: str


class TrainingExampleResponse(BaseModel):
    """A training example created from review."""

    id: int
    document_id: int
    auction_type_id: int
    field_key: str
    predicted_value: Optional[str] = None
    gold_value: Optional[str] = None
    is_correct: bool
    source_text_snippet: Optional[str] = None
    created_at: Optional[str] = None


class TrainingExamplesListResponse(BaseModel):
    """Response for training examples list."""

    items: list[TrainingExampleResponse]
    total: int


class BboxResponse(BaseModel):
    """Bounding box coordinates."""

    x0: float
    y0: float
    x1: float
    y1: float


class FieldEvidenceResponse(BaseModel):
    """Evidence for a single field extraction."""

    id: int
    field_key: str
    block_id: Optional[int] = None
    text_snippet: Optional[str] = None
    page_num: Optional[int] = None
    bbox: Optional[BboxResponse] = None
    extraction_method: Optional[str] = None
    confidence: float = 1.0
    value_source: str = "extracted"


class LayoutBlockResponse(BaseModel):
    """A layout block from the document."""

    id: int
    block_id: Optional[str] = None
    page_num: int
    bbox: BboxResponse
    text: Optional[str] = None
    block_type: str = "data"
    label: Optional[str] = None


class RunEvidenceResponse(BaseModel):
    """All evidence and layout blocks for a run."""

    run_id: int
    document_id: int
    evidence: list[FieldEvidenceResponse]
    blocks: list[LayoutBlockResponse]
    evidence_by_field: dict  # {field_key: [evidence_items]}


class PreflightIssue(BaseModel):
    """A preflight validation issue."""

    field_key: str
    issue: str
    severity: str  # "blocking", "warning"
    cd_key: Optional[str] = None


class PreflightResponse(BaseModel):
    """Preflight validation result for a run."""

    run_id: int
    is_ready: bool
    blocking_count: int
    warning_count: int
    issues: list[PreflightIssue]


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/{run_id}", response_model=ReviewRunResponse)
async def get_review_for_run(run_id: int):
    """
    Get all review items for an extraction run.

    Returns the extraction run info and all review items to be reviewed.
    """
    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    doc = DocumentRepository.get_by_id(run.document_id)
    at = AuctionTypeRepository.get_by_id(run.auction_type_id)

    items = ReviewItemRepository.get_by_run(run_id)

    item_responses = [
        ReviewItemResponse(
            id=item.id,
            run_id=item.run_id,
            source_key=item.source_key,
            internal_key=item.internal_key,
            cd_key=item.cd_key,
            predicted_value=item.predicted_value,
            corrected_value=item.corrected_value,
            is_match_ok=item.is_match_ok,
            export_field=item.export_field,
            confidence=item.confidence,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in items
    ]

    reviewed_count = sum(1 for item in items if item.is_match_ok or item.corrected_value)

    return ReviewRunResponse(
        run_id=run.id,
        document_id=run.document_id,
        document_filename=doc.filename if doc else None,
        auction_type_id=run.auction_type_id,
        auction_type_code=at.code if at else None,
        status=run.status,
        extraction_score=run.extraction_score,
        items=item_responses,
        reviewed_count=reviewed_count,
        total_count=len(items),
    )


@router.put("/{run_id}/item/{item_id}", response_model=ReviewItemResponse)
async def update_review_item(run_id: int, item_id: int, data: ReviewItemUpdate):
    """
    Update a single review item.

    Mark as correct (is_match_ok=true) or provide a corrected value.
    """
    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    item = ReviewItemRepository.get_by_id(item_id)
    if not item or item.run_id != run_id:
        raise HTTPException(status_code=404, detail="Review item not found")

    # Update the item
    ReviewItemRepository.update(
        item_id,
        corrected_value=data.corrected_value,
        is_match_ok=data.is_match_ok,
        export_field=data.export_field,
    )

    # Get updated item
    item = ReviewItemRepository.get_by_id(item_id)

    return ReviewItemResponse(
        id=item.id,
        run_id=item.run_id,
        source_key=item.source_key,
        internal_key=item.internal_key,
        cd_key=item.cd_key,
        predicted_value=item.predicted_value,
        corrected_value=item.corrected_value,
        is_match_ok=item.is_match_ok,
        export_field=item.export_field,
        confidence=item.confidence,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.post("/submit", response_model=ReviewSubmitResponse)
async def submit_review(data: ReviewSubmitRequest):
    """
    Submit review corrections for an extraction run.

    This endpoint:
    1. Updates review items by item_id (required for proper binding)
    2. Creates TrainingExamples from the corrected data
    3. Optionally marks the run as reviewed

    Each item in the request MUST include item_id to identify which
    review item to update. This prevents mismatches.

    TrainingExamples are used for future ML model training.
    """
    run = ExtractionRunRepository.get_by_id(data.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    doc = DocumentRepository.get_by_id(run.document_id)
    if not doc:
        raise HTTPException(status_code=400, detail="Document not found")

    # Get existing review items indexed by ID
    existing_items = ReviewItemRepository.get_by_run(data.run_id)
    item_by_id = {item.id: item for item in existing_items}

    items_updated = 0
    training_examples_created = 0
    errors = []

    # Get raw text snippet for training examples
    raw_text = doc.raw_text or ""
    text_snippet = raw_text[:500] if raw_text else None

    # Process each update BY ITEM_ID (P0 requirement)
    for update in data.items:
        # Validate item_id exists and belongs to this run
        item = item_by_id.get(update.item_id)
        if not item:
            errors.append(f"Item ID {update.item_id} not found in run {data.run_id}")
            continue

        # Update review item
        ReviewItemRepository.update(
            item.id,
            corrected_value=update.corrected_value,
            is_match_ok=update.is_match_ok,
            export_field=update.export_field,
        )
        items_updated += 1

        # Determine gold value for training
        gold_value = update.corrected_value if update.corrected_value else item.predicted_value
        is_correct = update.is_match_ok

        # Create training example if we have data to train on
        if gold_value is not None and update.export_field:
            TrainingExampleRepository.create(
                document_id=doc.id,
                auction_type_id=run.auction_type_id,
                run_id=run.id,
                field_key=item.source_key,
                predicted_value=item.predicted_value,
                gold_value=gold_value,
                is_correct=is_correct,
                source_text_snippet=text_snippet,
            )
            training_examples_created += 1

    # Return 400 if any item_id was invalid
    if errors:
        raise HTTPException(
            status_code=400, detail={"message": "Some items not found", "errors": errors}
        )

    # Mark run as reviewed
    if data.mark_as_reviewed:
        ExtractionRunRepository.update(data.run_id, status="reviewed")

    return ReviewSubmitResponse(
        run_id=data.run_id,
        status="reviewed" if data.mark_as_reviewed else run.status,
        items_updated=items_updated,
        training_examples_created=training_examples_created,
        message=f"Review submitted. {items_updated} items updated, {training_examples_created} training examples created.",
    )


@router.post("/{run_id}/approve")
async def approve_run(run_id: int):
    """
    Mark an extraction run as reviewed/approved.

    Use this after all items have been reviewed.
    """
    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    ExtractionRunRepository.update(run_id, status="reviewed")

    return {"run_id": run_id, "status": "reviewed", "message": "Run marked as reviewed"}


@router.get("/training-examples/", response_model=TrainingExamplesListResponse)
async def list_training_examples(
    auction_type_id: Optional[int] = Query(None),
    field_key: Optional[str] = Query(None),
    is_correct: Optional[bool] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    List training examples for ML training.

    Filter by auction type, field, or correctness.
    """
    from api.database import get_connection

    sql = "SELECT * FROM training_examples WHERE 1=1"
    params = []

    if auction_type_id:
        sql += " AND auction_type_id = ?"
        params.append(auction_type_id)
    if field_key:
        sql += " AND field_key = ?"
        params.append(field_key)
    if is_correct is not None:
        sql += " AND is_correct = ?"
        params.append(is_correct)

    # Count total
    count_sql = sql.replace("SELECT *", "SELECT COUNT(*)")

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(count_sql, params[:-2] if params else []).fetchone()[0]

    items = [
        TrainingExampleResponse(
            id=row["id"],
            document_id=row["document_id"],
            auction_type_id=row["auction_type_id"],
            field_key=row["field_key"],
            predicted_value=row["predicted_value"],
            gold_value=row["gold_value"],
            is_correct=bool(row["is_correct"]),
            source_text_snippet=row["source_text_snippet"],
            created_at=row["created_at"],
        )
        for row in rows
    ]

    return TrainingExamplesListResponse(items=items, total=total)


@router.get("/training-examples/export")
async def export_training_data(
    auction_type_id: Optional[int] = Query(None, description="Filter by auction type"),
    format: str = Query("jsonl", description="Export format: jsonl or csv"),
):
    """
    Export training examples for ML training.

    Returns JSONL or CSV format suitable for fine-tuning.
    """
    import io
    import json

    from fastapi.responses import StreamingResponse

    from api.database import get_connection

    sql = """
        SELECT te.*, d.filename, at.code as auction_type_code
        FROM training_examples te
        JOIN documents d ON te.document_id = d.id
        JOIN auction_types at ON te.auction_type_id = at.id
        WHERE 1=1
    """
    params = []

    if auction_type_id:
        sql += " AND te.auction_type_id = ?"
        params.append(auction_type_id)

    sql += " ORDER BY te.created_at"

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    if format == "csv":
        import csv

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "id",
                "document_id",
                "auction_type_code",
                "field_key",
                "predicted_value",
                "gold_value",
                "is_correct",
                "source_text_snippet",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row["id"],
                    row["document_id"],
                    row["auction_type_code"],
                    row["field_key"],
                    row["predicted_value"],
                    row["gold_value"],
                    row["is_correct"],
                    row["source_text_snippet"][:200] if row["source_text_snippet"] else "",
                ]
            )

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=training_examples.csv"},
        )

    else:  # jsonl
        lines = []
        for row in rows:
            record = {
                "id": row["id"],
                "document_id": row["document_id"],
                "auction_type_code": row["auction_type_code"],
                "field_key": row["field_key"],
                "predicted_value": row["predicted_value"],
                "gold_value": row["gold_value"],
                "is_correct": bool(row["is_correct"]),
                "source_text": row["source_text_snippet"],
            }
            lines.append(json.dumps(record))

        content = "\n".join(lines)
        return StreamingResponse(
            iter([content]),
            media_type="application/x-jsonlines",
            headers={"Content-Disposition": "attachment; filename=training_examples.jsonl"},
        )


# =============================================================================
# EVIDENCE & PREFLIGHT ENDPOINTS (M3.P2)
# =============================================================================


@router.get("/{run_id}/evidence", response_model=RunEvidenceResponse)
async def get_run_evidence(run_id: int):
    """
    Get all field evidence and layout blocks for a run.

    Returns bbox coordinates for highlighting in the PDF viewer.
    Used by the frontend to show where extracted values came from.
    """
    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    # Get field evidence
    evidence_list = FieldEvidenceRepository.get_by_run(run_id)

    # Get layout blocks for the document
    blocks = LayoutBlockRepository.get_by_document(run.document_id)

    # Build evidence responses
    evidence_responses = []
    evidence_by_field = {}

    for ev in evidence_list:
        bbox = None
        if ev.bbox_json:
            bbox = BboxResponse(
                x0=ev.bbox_json.get("x0", 0),
                y0=ev.bbox_json.get("y0", 0),
                x1=ev.bbox_json.get("x1", 0),
                y1=ev.bbox_json.get("y1", 0),
            )

        ev_response = FieldEvidenceResponse(
            id=ev.id,
            field_key=ev.field_key,
            block_id=ev.block_id,
            text_snippet=ev.text_snippet,
            page_num=ev.page_num,
            bbox=bbox,
            extraction_method=ev.extraction_method,
            confidence=ev.confidence,
            value_source=ev.value_source,
        )
        evidence_responses.append(ev_response)

        # Group by field
        if ev.field_key not in evidence_by_field:
            evidence_by_field[ev.field_key] = []
        evidence_by_field[ev.field_key].append(ev_response.model_dump())

    # Build block responses
    block_responses = []
    for block in blocks:
        block_responses.append(
            LayoutBlockResponse(
                id=block.id,
                block_id=block.block_id,
                page_num=block.page_num,
                bbox=BboxResponse(
                    x0=block.x0,
                    y0=block.y0,
                    x1=block.x1,
                    y1=block.y1,
                ),
                text=block.text,
                block_type=block.block_type,
                label=block.label,
            )
        )

    return RunEvidenceResponse(
        run_id=run_id,
        document_id=run.document_id,
        evidence=evidence_responses,
        blocks=block_responses,
        evidence_by_field=evidence_by_field,
    )


@router.get("/{run_id}/preflight", response_model=PreflightResponse)
async def get_run_preflight(run_id: int):
    """
    Get preflight validation for a run before export.

    Checks for blocking issues like missing required fields,
    warehouse not selected, etc.
    """
    import json

    from api.listing_fields import get_registry

    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    # Get outputs
    outputs = run.outputs_json or {}
    if isinstance(outputs, str):
        outputs = json.loads(outputs)

    # Check if warehouse is selected
    warehouse_selected = bool(outputs.get("warehouse_id") or outputs.get("delivery_address"))

    # Get blocking issues from field registry
    registry = get_registry()
    raw_issues = registry.get_blocking_issues(outputs, warehouse_selected=warehouse_selected)

    # Build issue list
    issues = []
    blocking_count = 0
    warning_count = 0

    for issue_data in raw_issues:
        severity = "blocking" if issue_data.get("is_blocking", True) else "warning"
        if severity == "blocking":
            blocking_count += 1
        else:
            warning_count += 1

        issues.append(
            PreflightIssue(
                field_key=issue_data.get("field_key", "unknown"),
                issue=issue_data.get("issue", "Unknown issue"),
                severity=severity,
                cd_key=issue_data.get("cd_key"),
            )
        )

    # Also check for low confidence fields
    review_items = ReviewItemRepository.get_by_run(run_id)
    for item in review_items:
        if item.confidence is not None and item.confidence < 0.5:
            if not item.corrected_value and not item.is_match_ok:
                warning_count += 1
                issues.append(
                    PreflightIssue(
                        field_key=item.source_key,
                        issue=f"Low confidence ({item.confidence:.0%}), needs review",
                        severity="warning",
                        cd_key=item.cd_key,
                    )
                )

    return PreflightResponse(
        run_id=run_id,
        is_ready=blocking_count == 0,
        blocking_count=blocking_count,
        warning_count=warning_count,
        issues=issues,
    )
