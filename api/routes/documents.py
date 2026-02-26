"""
Documents API Routes

Upload and manage documents for extraction and training.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.models import (
    AuctionTypeRepository,
    Document,
    DocumentRepository,
)

router = APIRouter(prefix="/api/documents", tags=["Documents"])

# Upload directory
UPLOAD_DIR = Path(__file__).parent.parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# FILENAME + EMAIL AUCTION CLASSIFICATION
# =============================================================================

def _classify_from_filename(filename: str) -> Optional[str]:
    """
    Detect auction type from filename patterns.
    FALLBACK ONLY — used for scanned PDFs when text classification fails.
    Returns auction code (COPART, IAA, MANHEIM) or None.
    """
    if not filename:
        return None
    fn = filename.lower()

    # Copart patterns
    if "copart" in fn:
        return "COPART"

    # IAA patterns — "ShowReport" is IAA's standard export filename
    if "iaa" in fn or "showreport" in fn or "buyer_receipt" in fn:
        return "IAA"

    # Manheim patterns — includes PSI reports
    if "manheim" in fn or "psi_report" in fn or "pre_sale_inspection" in fn:
        return "MANHEIM"

    return None


def _classify_from_text(raw_text: str) -> Optional[str]:
    """
    Detect auction type from PDF text content.
    PRIMARY classification method — reads actual document content.
    Returns auction code (COPART, IAA, MANHEIM) or None.
    """
    if not raw_text or len(raw_text) < 100:
        return None

    text_lower = raw_text.lower()

    # Copart patterns
    if "copart" in text_lower or "sold through copart" in text_lower or "copart.com" in text_lower:
        return "COPART"

    # IAA patterns
    if ("insurance auto auctions" in text_lower or "iaai.com" in text_lower
            or "\niaa " in text_lower or text_lower.startswith("iaa ")):
        return "IAA"

    # Manheim patterns
    if "manheim" in text_lower or "manheim.com" in text_lower:
        return "MANHEIM"

    return None


def _classify_from_email_context(email_metadata_json: Optional[str]) -> Optional[str]:
    """
    Detect auction type from email metadata (subject, sender).
    Returns auction code or None.
    """
    if not email_metadata_json:
        return None
    try:
        meta = json.loads(email_metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None

    subject = (meta.get("subject") or "").lower()
    sender = (meta.get("sender") or "").lower()
    context = f"{subject} {sender}"

    if "copart" in context:
        return "COPART"
    if "iaa" in context or "insurance auto auction" in context:
        return "IAA"
    if "manheim" in context:
        return "MANHEIM"

    return None


def find_vin_duplicate(vin: str, exclude_run_id: int = None) -> Optional[dict]:
    """
    Check if VIN already exists in another extraction run.

    Returns info about the duplicate if found, None otherwise.
    """
    if not vin or len(vin) < 10:  # Skip invalid VINs
        return None

    from api.database import get_connection

    with get_connection() as conn:
        # Search for the VIN in other extraction runs' outputs
        query = """
            SELECT
                er.id as run_id,
                er.document_id,
                d.filename as document_filename,
                er.outputs_json,
                er.created_at
            FROM extraction_runs er
            JOIN documents d ON d.id = er.document_id
            WHERE er.outputs_json LIKE ?
              AND er.status NOT IN ('failed', 'cancelled')
        """
        params = [f'%"vehicle_vin": "{vin}"%']

        if exclude_run_id:
            query += " AND er.id != ?"
            params.append(exclude_run_id)

        query += " ORDER BY er.created_at DESC LIMIT 1"

        row = conn.execute(query, params).fetchone()

        if row:
            outputs = {}
            if row["outputs_json"]:
                try:
                    outputs = (
                        json.loads(row["outputs_json"])
                        if isinstance(row["outputs_json"], str)
                        else row["outputs_json"]
                    )
                except (json.JSONDecodeError, TypeError):
                    pass

            return {
                "run_id": row["run_id"],
                "document_id": row["document_id"],
                "document_filename": row["document_filename"],
                "vin": vin,
                "vehicle_year": outputs.get("vehicle_year"),
                "vehicle_make": outputs.get("vehicle_make"),
                "vehicle_model": outputs.get("vehicle_model"),
                "created_at": row["created_at"],
            }

    return None


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class DocumentResponse(BaseModel):
    """Response model for document."""

    id: int
    uuid: str
    auction_type_id: int
    auction_type_code: Optional[str] = None
    dataset_split: str
    filename: str
    file_size: Optional[int] = None
    sha256: Optional[str] = None
    mime_type: str = "application/pdf"
    page_count: Optional[int] = None
    has_ocr: bool = False
    source: str = "upload"  # upload, email, batch, test_lab
    created_at: Optional[str] = None
    email_received_date: Optional[str] = None
    uploaded_by: Optional[str] = None

    # Pending/hold status
    pending_reason: Optional[str] = None
    hold_reason: Optional[str] = None
    hold_note: Optional[str] = None
    hold_since: Optional[str] = None
    archived_at: Optional[str] = None

    # Enriched fields from latest extraction run
    load_id: Optional[str] = None
    vin: Optional[str] = None
    vehicle_year: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_lot: Optional[str] = None
    pickup_city: Optional[str] = None
    pickup_state: Optional[str] = None
    pickup_name: Optional[str] = None
    gate_pass: Optional[str] = None
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    price_total: Optional[float] = None
    transport_price: Optional[float] = None
    auction_cost: Optional[float] = None
    distance_miles: Optional[float] = None
    rate_per_mile: Optional[float] = None
    extraction_status: Optional[str] = None
    extraction_run_id: Optional[int] = None

    # Full extraction outputs for frontend (avoids separate extraction API call)
    outputs: Optional[dict] = None

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Response model for document list."""

    items: list[DocumentResponse]
    total: int
    train_count: int = 0
    test_count: int = 0


class VinDuplicateInfo(BaseModel):
    """Info about a duplicate VIN found in another document."""

    run_id: int
    document_id: int
    document_filename: str
    vin: str
    vehicle_year: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    created_at: Optional[str] = None


class DocumentUploadResponse(BaseModel):
    """Response model for document upload."""

    document: DocumentResponse
    is_duplicate: bool = False
    raw_text_preview: Optional[str] = None

    # Extraction run info (auto-created on upload)
    run_id: Optional[int] = None
    run_status: Optional[str] = None
    needs_ocr: bool = False
    text_length: int = 0

    # Classification info
    detected_source: Optional[str] = None
    classification_score: Optional[float] = None

    # VIN duplicate detection
    vin_duplicate: Optional[VinDuplicateInfo] = None


class DocumentStatsResponse(BaseModel):
    """Response model for document statistics."""

    auction_type_id: int
    auction_type_name: str
    train_count: int
    test_count: int
    total: int


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(..., description="PDF document to upload"),
    auction_type_id: Optional[int] = Form(
        None, description="Auction type ID (optional, auto-detect if not provided)"
    ),
    dataset_split: str = Form("train", description="Dataset split: train or test"),
    uploaded_by: Optional[str] = Form(None, description="Uploader identifier"),
    auto_extract: bool = Form(True, description="Automatically run extraction after upload"),
    source: str = Form("upload", description="Source: upload, email, batch, test_lab"),
    is_test: bool = Form(False, description="Mark as test document (blocks export)"),
    auto_classify: bool = Form(True, description="Auto-detect auction type from document"),
):
    """
    Upload a document for extraction and training.

    The document is associated with an auction type and marked as train or test.
    Duplicate detection is performed using SHA256 hash.

    Parameters:
    - auction_type_id: Optional. If not provided, document will be auto-classified.
    - auto_classify: If true (default), auto-detect auction type from document content.
    - source: upload (manual), email (ingestion), batch (bulk), test_lab (testing)
    - is_test: If true, document cannot be exported to Central Dispatch

    IMPORTANT: This endpoint automatically creates an ExtractionRun after upload.
    - If text_length >= 100: runs extraction, status = needs_review
    - If text_length < 100: marks as manual_required (needs OCR)
    """
    from api.models import ExtractionRunRepository

    # We'll validate auction_type after classification if needed
    auction_type = None
    if auction_type_id:
        auction_type = AuctionTypeRepository.get_by_id(auction_type_id)
        if not auction_type:
            raise HTTPException(status_code=400, detail="Invalid auction_type_id")

    # Validate dataset split
    if dataset_split not in ("train", "test"):
        raise HTTPException(status_code=400, detail="dataset_split must be 'train' or 'test'")

    # Validate source
    valid_sources = ("upload", "email", "batch", "test_lab")
    if source not in valid_sources:
        raise HTTPException(
            status_code=400, detail=f"source must be one of: {', '.join(valid_sources)}"
        )

    # Auto-set is_test for test_lab source
    if source == "test_lab":
        is_test = True

    # Validate file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Calculate SHA256
    sha256 = hashlib.sha256(content).hexdigest()

    # Check for duplicate
    existing = DocumentRepository.get_by_sha256(sha256)
    if existing:
        # For duplicates, get the existing auction type and run info
        existing_auction_type = AuctionTypeRepository.get_by_id(existing.auction_type_id)
        from api.database import get_connection

        with get_connection() as conn:
            run_row = conn.execute(
                "SELECT id, status FROM extraction_runs WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
                (existing.id,),
            ).fetchone()

        # If auto_extract is enabled and no successful run exists, create a new extraction run
        new_run_id = None
        new_run_status = None
        if auto_extract:
            # Check if we should re-extract (no run, or last run failed)
            should_reextract = not run_row or run_row["status"] in ("failed", "manual_required")
            if should_reextract:
                from api.models import ExtractionRunRepository

                new_run_id = ExtractionRunRepository.create(
                    document_id=existing.id,
                    auction_type_id=existing.auction_type_id,
                    extractor_kind="rule",
                )
                # Run extraction
                try:
                    from api.routes.extractions import run_extraction

                    run_extraction(new_run_id, existing.id, existing.auction_type_id, "rule", None)
                    run = ExtractionRunRepository.get_by_id(new_run_id)
                    new_run_status = run.status if run else "failed"
                except Exception as e:
                    ExtractionRunRepository.update(
                        new_run_id,
                        status="failed",
                        error_message=str(e),
                    )
                    new_run_status = "failed"

        return DocumentUploadResponse(
            document=DocumentResponse(
                **existing.__dict__,
                auction_type_code=existing_auction_type.code if existing_auction_type else None,
            ),
            is_duplicate=True,
            run_id=new_run_id or (run_row["id"] if run_row else None),
            run_status=new_run_status or (run_row["status"] if run_row else None),
        )

    # Validate PDF structure BEFORE saving (P0 requirement)
    import io

    page_count = 0
    raw_text = ""
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            page_count = len(pdf.pages)
            if page_count == 0:
                raise HTTPException(status_code=422, detail="Invalid PDF: Document has no pages")
            # Extract text to validate PDF is readable
            text_parts = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            raw_text = "\n".join(text_parts)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=422, detail=f"Invalid PDF: {str(e)}. Please upload a valid PDF document."
        )

    # Save file only after validation passed
    file_path = UPLOAD_DIR / f"{sha256[:16]}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(content)

    # Determine if OCR is needed (text too short)
    text_length = len(raw_text) if raw_text else 0
    needs_ocr = text_length < 100

    # Auto-classify document if auction_type not provided
    detected_source = None
    classification_score = None

    if auto_classify and not auction_type_id:
        # Step 1: Try text-based classification (PRIMARY — reads PDF content)
        if raw_text and text_length >= 100:
            text_code = _classify_from_text(raw_text)
            if text_code:
                detected_type = AuctionTypeRepository.get_by_code(text_code)
                if detected_type:
                    auction_type_id = detected_type.id
                    auction_type = detected_type
                    detected_source = text_code

        # Step 2: Try ExtractorManager scoring (if text classification didn't match)
        if not auction_type_id and raw_text and text_length >= 100:
            try:
                from extractors import ExtractorManager

                manager = ExtractorManager()
                classification = manager.classify(str(file_path))
                if classification:
                    detected_source = classification.source.value
                    classification_score = round(classification.score * 100, 1)
                    detected_type = AuctionTypeRepository.get_by_code(detected_source.upper())
                    if detected_type:
                        auction_type_id = detected_type.id
                        auction_type = detected_type
            except Exception:
                pass

        # Step 3: Try filename-based classification (FALLBACK for scanned PDFs)
        if not auction_type_id:
            fn_code = _classify_from_filename(file.filename)
            if fn_code:
                detected_type = AuctionTypeRepository.get_by_code(fn_code)
                if detected_type:
                    auction_type_id = detected_type.id
                    auction_type = detected_type
                    detected_source = fn_code

        # Step 4: Try email context if still unclassified
        if not auction_type_id and source == "email":
            email_code = _classify_from_email_context(email_metadata_json)
            if email_code:
                detected_type = AuctionTypeRepository.get_by_code(email_code)
                if detected_type:
                    auction_type_id = detected_type.id
                    auction_type = detected_type
                    detected_source = email_code

    # If still no auction type, use "OTHER" as fallback
    if not auction_type_id:
        other_type = AuctionTypeRepository.get_by_code("OTHER")
        if other_type:
            auction_type_id = other_type.id
            auction_type = other_type
        else:
            # Create "OTHER" if doesn't exist
            auction_type_id = 4  # Default to ID 4
            auction_type = AuctionTypeRepository.get_by_id(4)

    # Create document record with all fields
    doc_id = DocumentRepository.create(
        auction_type_id=auction_type_id,
        dataset_split=dataset_split,
        filename=file.filename,
        file_path=str(file_path),
        file_size=file_size,
        sha256=sha256,
        raw_text=raw_text,
        uploaded_by=uploaded_by,
        source=source,
        is_test=is_test,
        page_count=page_count,
    )

    doc = DocumentRepository.get_by_id(doc_id)

    # Auto-create extraction run
    run_id = None
    run_status = None
    # Keep detected_source and classification_score from earlier auto-classification

    if auto_extract:
        # Create extraction run
        run_id = ExtractionRunRepository.create(
            document_id=doc_id,
            auction_type_id=auction_type_id,
            extractor_kind="rule",
        )

        if needs_ocr:
            # Mark as manual_required - can't extract without OCR
            ExtractionRunRepository.update(
                run_id,
                status="manual_required",
                error_message="Document has insufficient text for extraction. OCR processing required.",
            )
            run_status = "manual_required"
        else:
            # Run classification if not already done
            try:
                if not detected_source:
                    from extractors import ExtractorManager

                    manager = ExtractorManager()
                    classification = manager.classify(str(file_path))
                    if classification:
                        detected_source = classification.source.value
                        classification_score = round(classification.score * 100, 1)

                # Run extraction
                from api.routes.extractions import run_extraction

                run_extraction(run_id, doc_id, auction_type_id, "rule", None)

                # Get updated status
                run = ExtractionRunRepository.get_by_id(run_id)
                run_status = run.status if run else "failed"
            except Exception as e:
                # Mark as failed if extraction crashes
                ExtractionRunRepository.update(
                    run_id,
                    status="failed",
                    error_message=str(e),
                )
                run_status = "failed"

    # Check for VIN duplicates after extraction
    vin_duplicate_info = None
    if run_id and run_status not in ("failed", "manual_required"):
        run = ExtractionRunRepository.get_by_id(run_id)
        if run and run.outputs_json:
            outputs = (
                json.loads(run.outputs_json)
                if isinstance(run.outputs_json, str)
                else run.outputs_json
            )
            vin = outputs.get("vehicle_vin")
            if vin:
                dup = find_vin_duplicate(vin, exclude_run_id=run_id)
                if dup:
                    vin_duplicate_info = VinDuplicateInfo(**dup)

    return DocumentUploadResponse(
        document=DocumentResponse(
            **doc.__dict__,
            auction_type_code=auction_type.code if auction_type else None,
        ),
        is_duplicate=False,
        raw_text_preview=raw_text[:500] if raw_text else None,
        run_id=run_id,
        run_status=run_status,
        needs_ocr=needs_ocr,
        text_length=text_length,
        detected_source=detected_source,
        classification_score=classification_score,
        vin_duplicate=vin_duplicate_info,
    )


@router.get("/check-vin-duplicate/{vin}")
async def check_vin_duplicate(vin: str, exclude_run_id: Optional[int] = None):
    """
    Check if a VIN already exists in another extraction run.

    Returns duplicate info if found, null otherwise.
    """
    dup = find_vin_duplicate(vin, exclude_run_id=exclude_run_id)
    if dup:
        return {"is_duplicate": True, "duplicate": VinDuplicateInfo(**dup)}
    return {"is_duplicate": False, "duplicate": None}


def _enrich_doc_with_extraction(doc_dict: dict, conn) -> dict:
    """Enrich a document dict with fields from its latest extraction run."""
    doc_id = doc_dict.get("id")
    if not doc_id:
        return doc_dict

    row = conn.execute(
        """SELECT id, status, outputs_json FROM extraction_runs
           WHERE document_id = ? ORDER BY id DESC LIMIT 1""",
        (doc_id,),
    ).fetchone()

    if not row:
        return doc_dict

    doc_dict["extraction_run_id"] = row["id"]
    doc_dict["extraction_status"] = row["status"]

    outputs = {}
    if row["outputs_json"]:
        try:
            outputs = json.loads(row["outputs_json"])
        except Exception:
            pass

    def _str(val):
        return str(val) if val is not None else None

    doc_dict["load_id"] = _str(outputs.get("load_id"))
    doc_dict["vin"] = _str(outputs.get("vehicle_vin"))
    doc_dict["vehicle_year"] = _str(outputs.get("vehicle_year"))
    doc_dict["vehicle_make"] = _str(outputs.get("vehicle_make"))
    doc_dict["vehicle_model"] = _str(outputs.get("vehicle_model"))
    doc_dict["vehicle_lot"] = _str(outputs.get("vehicle_lot"))
    doc_dict["pickup_city"] = _str(outputs.get("pickup_city"))
    doc_dict["pickup_state"] = _str(outputs.get("pickup_state"))
    doc_dict["pickup_name"] = _str(outputs.get("pickup_name"))
    doc_dict["gate_pass"] = _str(outputs.get("gate_pass"))

    # Transport price — ONLY carrier transport price, never auction purchase price.
    # price_total = user override from Documents inline edit
    # final_price = user override from Review approve
    # total_amount = AUCTION PURCHASE PRICE — must NOT appear in Transport column
    # Use explicit None checks to avoid treating 0 as falsy
    price = outputs.get("price_total")
    if price is None:
        price = outputs.get("final_price")
    # Intentionally do NOT fall back to total_amount — that's auction cost, not transport price
    doc_dict["price_total"] = float(price) if price is not None else None

    # Auction cost (vehicle purchase price) — separate from transport price
    auction_cost = outputs.get("total_amount")
    doc_dict["auction_cost"] = float(auction_cost) if auction_cost is not None else None

    # Distance for $/mile calculation — try outputs first, then distance_cache
    distance = outputs.get("distance_miles")
    if distance is None:
        pickup_zip = outputs.get("pickup_zip")
        wh_id_for_dist = outputs.get("warehouse_id")
        if pickup_zip and wh_id_for_dist:
            dist_row = conn.execute(
                "SELECT distance_miles FROM distance_cache WHERE origin_zip = ? AND destination_warehouse_id = ?",
                (str(pickup_zip), int(wh_id_for_dist)),
            ).fetchone()
            if dist_row:
                distance = dist_row["distance_miles"]
    doc_dict["distance_miles"] = float(distance) if distance is not None else None

    # Warehouse selection (set during review)
    wh_id = outputs.get("warehouse_id")
    if wh_id is not None:
        doc_dict["warehouse_id"] = int(wh_id)
        # Resolve warehouse name for display
        wh_row = conn.execute(
            "SELECT name FROM warehouses WHERE id = ?", (int(wh_id),)
        ).fetchone()
        doc_dict["warehouse_name"] = wh_row["name"] if wh_row else None
    else:
        doc_dict["warehouse_id"] = None
        doc_dict["warehouse_name"] = None

    return doc_dict


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    auction_type_id: Optional[int] = Query(None, description="Filter by auction type"),
    dataset_split: Optional[str] = Query(None, description="Filter by split: train or test"),
    search: Optional[str] = Query(None, description="Search by VIN, make, model, or lot"),
    status: Optional[str] = Query(None, description="Filter by status: needs_review, reviewed, exported, hold, pending, archived, etc."),
    exclude_test_lab: bool = Query(True, description="Exclude Test Lab documents from list"),
    include_archived: bool = Query(False, description="Include archived documents"),
    sort_by: str = Query("created_at", description="Sort field: created_at, filename, status"),
    sort_order: str = Query("desc", description="Sort direction: asc or desc"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List documents with optional filtering and search."""
    from api.database import get_connection

    with get_connection() as conn:
        # Pre-load auction types into a dict (typically <10 rows) to avoid N+1
        at_rows = conn.execute("SELECT id, code FROM auction_types").fetchall()
        at_code_map = {r["id"]: r["code"] for r in at_rows}

        # Base query with LEFT JOIN to get extraction data in single query
        base_join = """
            SELECT d.*, er.outputs_json AS _outputs_json, er.id AS _run_id, er.status AS _run_status
            FROM documents d
            LEFT JOIN extraction_runs er ON er.document_id = d.id
                AND er.id = (SELECT MAX(e2.id) FROM extraction_runs e2 WHERE e2.document_id = d.id)
        """
        base_where = " WHERE (d.is_test IS NULL OR d.is_test = 0) AND (d.source IS NULL OR d.source != 'test_lab')"
        params = []

        # Server-side status filter (must run before archived exclusion)
        if status:
            if status == "hold":
                base_where += " AND d.hold_reason IS NOT NULL AND d.hold_reason != ''"
            elif status == "pending":
                base_where += " AND d.pending_reason IS NOT NULL AND d.pending_reason != '' AND (d.hold_reason IS NULL OR d.hold_reason = '')"
            elif status == "archived":
                include_archived = True
                base_where += " AND d.archived_at IS NOT NULL AND d.archived_at != ''"
            else:
                base_where += " AND er.status = ?"
                params.append(status)

        # Exclude archived unless explicitly requested
        if not include_archived:
            base_where += " AND (d.archived_at IS NULL OR d.archived_at = '')"

        if search and search.strip():
            q = f"%{search.strip()}%"
            q_upper = f"%{search.strip().upper()}%"
            base_where += """
                AND (
                    json_extract(er.outputs_json, '$.vehicle_vin') LIKE ?
                    OR json_extract(er.outputs_json, '$.vehicle_make') LIKE ?
                    OR json_extract(er.outputs_json, '$.vehicle_model') LIKE ?
                    OR json_extract(er.outputs_json, '$.vehicle_lot') LIKE ?
                    OR json_extract(er.outputs_json, '$.gate_pass') LIKE ?
                    OR d.filename LIKE ?
                )
            """
            params.extend([q_upper, q, q, q, q, q])
        elif auction_type_id:
            base_where += " AND d.auction_type_id = ?"
            params.append(auction_type_id)

        # Server-side sort with whitelist
        _SORT_WHITELIST = {
            "created_at": "d.created_at",
            "filename": "d.filename",
            "status": "COALESCE(er.status, '')",
        }
        sort_col = _SORT_WHITELIST.get(sort_by, "d.created_at")
        sort_dir = "ASC" if sort_order == "asc" else "DESC"

        # Count query (reuses same WHERE clause)
        total = conn.execute(f"SELECT COUNT(*) FROM documents d LEFT JOIN extraction_runs er ON er.document_id = d.id AND er.id = (SELECT MAX(e2.id) FROM extraction_runs e2 WHERE e2.document_id = d.id){base_where}", params).fetchone()[0]

        # Main query with pagination
        sql = f"{base_join}{base_where} ORDER BY {sort_col} {sort_dir} LIMIT ? OFFSET ?"
        rows = conn.execute(sql, params + [limit, offset]).fetchall()

        # Build response using JOIN data — no N+1 enrichment
        items = []
        for row in rows:
            d = dict(row)
            outputs_json_raw = d.pop("_outputs_json", None)
            run_id = d.pop("_run_id", None)
            run_status = d.pop("_run_status", None)

            # Parse extraction outputs once
            outputs = {}
            if outputs_json_raw:
                try:
                    outputs = json.loads(outputs_json_raw)
                except Exception:
                    pass

            def _str(val):
                return str(val) if val is not None else None

            # Enrich from joined extraction data (inline, no separate query)
            d["extraction_run_id"] = run_id
            d["extraction_status"] = run_status
            d["load_id"] = _str(outputs.get("load_id"))
            d["vin"] = _str(outputs.get("vehicle_vin"))
            d["vehicle_year"] = _str(outputs.get("vehicle_year"))
            d["vehicle_make"] = _str(outputs.get("vehicle_make"))
            d["vehicle_model"] = _str(outputs.get("vehicle_model"))
            d["vehicle_lot"] = _str(outputs.get("vehicle_lot"))
            d["pickup_city"] = _str(outputs.get("pickup_city"))
            d["pickup_state"] = _str(outputs.get("pickup_state"))
            d["pickup_name"] = _str(outputs.get("pickup_name"))
            d["gate_pass"] = _str(outputs.get("gate_pass"))
            d["auction_type_code"] = at_code_map.get(d.get("auction_type_id"))

            # Email received date — extract from email_metadata_json
            email_received_date = None
            email_meta_raw = d.get("email_metadata_json")
            if email_meta_raw:
                try:
                    email_meta = json.loads(email_meta_raw)
                    email_received_date = email_meta.get("date")
                except Exception:
                    pass
            d["email_received_date"] = email_received_date

            # Transport price (canonical: price_total in DB, transport_price in API)
            price = outputs.get("price_total")
            if price is None:
                price = outputs.get("final_price")
            transport_price = float(price) if price is not None else None
            d["price_total"] = transport_price
            d["transport_price"] = transport_price

            # Auction cost (vehicle purchase price)
            auction_cost = outputs.get("total_amount")
            d["auction_cost"] = float(auction_cost) if auction_cost is not None else None

            # Distance — try outputs, then distance_cache
            distance = outputs.get("distance_miles")
            if distance is None:
                pickup_zip = outputs.get("pickup_zip")
                wh_id_for_dist = outputs.get("warehouse_id")
                if pickup_zip and wh_id_for_dist:
                    dist_row = conn.execute(
                        "SELECT distance_miles FROM distance_cache WHERE origin_zip = ? AND destination_warehouse_id = ?",
                        (str(pickup_zip), int(wh_id_for_dist)),
                    ).fetchone()
                    if dist_row:
                        distance = dist_row["distance_miles"]
            dist_val = float(distance) if distance is not None else None
            d["distance_miles"] = dist_val

            # Rate per mile (computed)
            d["rate_per_mile"] = round(transport_price / dist_val, 2) if transport_price and dist_val and dist_val > 0 else None

            # Warehouse
            wh_id = outputs.get("warehouse_id")
            if wh_id is not None:
                d["warehouse_id"] = int(wh_id)
                wh_row = conn.execute(
                    "SELECT name FROM warehouses WHERE id = ?", (int(wh_id),)
                ).fetchone()
                d["warehouse_name"] = wh_row["name"] if wh_row else None
            else:
                d["warehouse_id"] = None
                d["warehouse_name"] = None

            # Full extraction outputs (avoids separate extraction API call)
            d["outputs"] = outputs if outputs else None

            items.append(DocumentResponse(**d))

        # Counts for split badges
        count_filter = " AND (is_test IS NULL OR is_test = 0) AND (source IS NULL OR source != 'test_lab')"
        train_count = conn.execute(
            f"SELECT COUNT(*) FROM documents WHERE dataset_split = 'train'{count_filter}"
        ).fetchone()[0]
        test_count = conn.execute(
            f"SELECT COUNT(*) FROM documents WHERE dataset_split = 'test'{count_filter}"
        ).fetchone()[0]

    return DocumentListResponse(
        items=items,
        total=total,
        train_count=train_count,
        test_count=test_count,
    )


@router.get("/training/list")
async def list_training_documents(
    auction_type_id: Optional[int] = None,
    limit: int = Query(default=50, le=100),
    offset: int = 0,
):
    """
    List documents for training/testing purposes only.

    Returns documents that are marked as test or from test_lab source.
    These are separate from production documents and used for
    zone configuration, extraction testing, and model training.
    """
    from api.database import get_connection

    sql = "SELECT * FROM documents WHERE (is_test = 1 OR source = 'test_lab')"
    params = []

    if auction_type_id:
        sql += " AND auction_type_id = ?"
        params.append(auction_type_id)

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        docs = [Document(**dict(row)) for row in rows]

        total = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE (is_test = 1 OR source = 'test_lab')"
        ).fetchone()[0]

    items = []
    for doc in docs:
        at = AuctionTypeRepository.get_by_id(doc.auction_type_id)
        items.append(
            DocumentResponse(
                **doc.__dict__,
                auction_type_code=at.code if at else None,
            )
        )

    return {
        "items": items,
        "total": total,
    }


@router.get("/{id}", response_model=DocumentResponse)
async def get_document(id: int):
    """Get a single document by ID."""
    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    at = AuctionTypeRepository.get_by_id(doc.auction_type_id)

    # Extract email received date
    email_received_date = None
    if doc.email_metadata_json:
        try:
            email_meta = json.loads(doc.email_metadata_json)
            email_received_date = email_meta.get("date")
        except Exception:
            pass

    return DocumentResponse(
        **doc.__dict__,
        auction_type_code=at.code if at else None,
        email_received_date=email_received_date,
    )


@router.get("/{id}/text")
async def get_document_text(id: int):
    """Get the raw extracted text from a document."""
    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "id": doc.id,
        "filename": doc.filename,
        "raw_text": doc.raw_text,
        "page_count": doc.page_count,
    }


@router.get("/{id}/file")
async def get_document_file(id: int):
    """
    Get the PDF file for viewing/downloading.

    Returns the original PDF document for display in a PDF viewer.
    """
    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not doc.file_path:
        raise HTTPException(status_code=404, detail="Document file path not found")

    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="Document file not found on disk")

    return FileResponse(
        doc.file_path,
        media_type="application/pdf",
        filename=doc.filename,
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


@router.get("/stats/by-auction-type", response_model=list[DocumentStatsResponse])
async def get_document_stats():
    """Get document counts by auction type."""
    auction_types = AuctionTypeRepository.list_all()
    stats = []

    for at in auction_types:
        counts = DocumentRepository.count_by_auction_type(at.id)
        train_count = counts.get("train", 0)
        test_count = counts.get("test", 0)
        stats.append(
            DocumentStatsResponse(
                auction_type_id=at.id,
                auction_type_name=at.name,
                train_count=train_count,
                test_count=test_count,
                total=train_count + test_count,
            )
        )

    return stats


@router.get("/{id}/export-preview")
async def get_document_export_preview(id: int):
    """
    Get document export preview with all fields ready for Central Dispatch.

    Returns:
    - Document metadata
    - Latest extraction with all fields
    - Export validation status
    - Field mapping information
    """
    from api.database import get_connection

    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    at = AuctionTypeRepository.get_by_id(doc.auction_type_id)

    # Check if document can be exported
    can_export = True
    blocking_issues = []

    if doc.is_test:
        can_export = False
        blocking_issues.append("Document is marked as test - cannot export to production")

    # Get latest extraction run
    with get_connection() as conn:
        run_row = conn.execute(
            """
            SELECT * FROM extraction_runs
            WHERE document_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """,
            (id,),
        ).fetchone()

        extraction = None
        extracted_fields = {}
        if run_row:
            extraction = dict(run_row)

            # Get extraction outputs from outputs_json field
            outputs_json = extraction.get("outputs_json")
            if outputs_json:
                try:
                    outputs = (
                        json.loads(outputs_json) if isinstance(outputs_json, str) else outputs_json
                    )
                    for field_key, value in outputs.items():
                        if isinstance(value, dict):
                            extracted_fields[field_key] = value
                        else:
                            extracted_fields[field_key] = {
                                "value": value,
                                "confidence": 1.0,
                                "source": "extracted",
                                "is_corrected": False,
                            }
                except (json.JSONDecodeError, TypeError):
                    pass

            # Also check review_items for corrected values
            review_rows = conn.execute(
                """
                SELECT source_key, predicted_value, corrected_value, is_match_ok
                FROM review_items
                WHERE run_id = ?
            """,
                (extraction["id"],),
            ).fetchall()

            for review_row in review_rows:
                r = dict(review_row)
                field_key = r["source_key"]
                # Use corrected value if available, otherwise predicted
                value = r["corrected_value"] if r["corrected_value"] else r["predicted_value"]
                if value:
                    extracted_fields[field_key] = {
                        "value": value,
                        "confidence": 1.0 if r["is_match_ok"] else 0.5,
                        "source": "corrected" if r["corrected_value"] else "extracted",
                        "is_corrected": bool(r["corrected_value"]),
                    }

            # Check extraction status
            if extraction["status"] not in ["approved", "reviewed"]:
                can_export = False
                blocking_issues.append(
                    f"Extraction status is '{extraction['status']}' - needs review"
                )

        else:
            can_export = False
            blocking_issues.append("No extraction run found - please run extraction first")

        # Get field mappings for this auction type
        field_mappings = []
        mapping_rows = conn.execute(
            """
            SELECT * FROM field_mappings
            WHERE auction_type_id = ?
            ORDER BY display_order, cd_key
        """,
            (doc.auction_type_id,),
        ).fetchall()

        if mapping_rows:
            for m_row in mapping_rows:
                m = dict(m_row)
                # Use cd_key as the field key (maps to Central Dispatch API field)
                field_key = m.get("cd_key") or m.get("source_key") or m.get("internal_key")
                if not field_key:
                    continue

                field_data = extracted_fields.get(field_key, {})
                # Also try to find by source_key if not found by cd_key
                if not field_data.get("value") and m.get("source_key"):
                    field_data = extracted_fields.get(m["source_key"], {})

                # Check if required field is missing
                if (
                    m.get("is_required")
                    and not field_data.get("value")
                    and not m.get("default_value")
                ):
                    can_export = False
                    blocking_issues.append(f"Required field '{field_key}' is empty")

                field_mappings.append(
                    {
                        "cd_field": field_key,
                        "display_name": m.get("description") or field_key.replace("_", " ").title(),
                        "source": "constant" if m.get("default_value") else "extracted",
                        "is_required": m.get("is_required", False),
                        "is_active": m.get("is_active", True),
                        "value": field_data.get("value") or m.get("default_value"),
                        "confidence": field_data.get("confidence"),
                        "default_value": m.get("default_value"),
                    }
                )
        else:
            # Fallback: build fields directly from extracted data
            for field_key, field_info in extracted_fields.items():
                field_mappings.append(
                    {
                        "cd_field": field_key,
                        "display_name": field_key.replace("_", " ").title(),
                        "source": field_info.get("source", "extracted"),
                        "is_required": False,
                        "is_active": True,
                        "value": field_info.get("value"),
                        "confidence": field_info.get("confidence"),
                        "default_value": None,
                    }
                )

    return {
        "document": {
            "id": doc.id,
            "filename": doc.filename,
            "auction_type": at.code if at else None,
            "auction_type_name": at.name if at else None,
            "is_test": doc.is_test,
            "created_at": doc.created_at,
        },
        "extraction": extraction,
        "fields": field_mappings,
        "can_export": can_export,
        "blocking_issues": blocking_issues,
        "order_id": extracted_fields.get("order_id", {}).get("value"),
    }


class SetPendingRequest(BaseModel):
    """Request model for setting pending status."""
    reason: str


@router.post("/{id}/set-pending")
async def set_pending(id: int, request: SetPendingRequest):
    """Mark a document as pending with a reason (e.g. awaiting gate pass, vehicle release)."""
    from api.database import get_connection

    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    with get_connection() as conn:
        conn.execute(
            "UPDATE documents SET pending_reason = ? WHERE id = ?",
            (request.reason, id),
        )
        conn.commit()

    return {"success": True, "id": id, "pending_reason": request.reason}


@router.post("/{id}/clear-pending")
async def clear_pending(id: int):
    """Clear the pending status from a document."""
    from api.database import get_connection

    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    with get_connection() as conn:
        conn.execute(
            "UPDATE documents SET pending_reason = NULL WHERE id = ?",
            (id,),
        )
        conn.commit()

    return {"success": True, "id": id, "pending_reason": None}


# =============================================================================
# HOLD STATUS
# =============================================================================

class SetHoldRequest(BaseModel):
    """Request model for setting hold status."""
    reason: str  # awaiting_gate_pass, awaiting_payment, awaiting_title, other
    note: Optional[str] = None


@router.post("/{id}/set-hold")
async def set_hold(id: int, request: SetHoldRequest):
    """Put a document on hold with a reason and optional note."""
    from datetime import datetime, timezone

    from api.database import get_connection

    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    now = datetime.now(timezone.utc).isoformat() + "Z"

    with get_connection() as conn:
        conn.execute(
            "UPDATE documents SET hold_reason = ?, hold_note = ?, hold_since = ? WHERE id = ?",
            (request.reason, request.note, now, id),
        )
        conn.commit()

    return {"success": True, "id": id, "hold_reason": request.reason,
            "hold_note": request.note, "hold_since": now}


@router.post("/{id}/release-hold")
async def release_hold(id: int):
    """Release a document from hold."""
    from api.database import get_connection

    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    with get_connection() as conn:
        conn.execute(
            "UPDATE documents SET hold_reason = NULL, hold_note = NULL, hold_since = NULL WHERE id = ?",
            (id,),
        )
        conn.commit()

    return {"success": True, "id": id, "hold_reason": None}


# =============================================================================
# ARCHIVE
# =============================================================================


@router.post("/{id}/archive")
async def archive_document(id: int):
    """Archive a document (soft-delete for exported docs)."""
    from datetime import datetime, timezone

    from api.database import get_connection

    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    now = datetime.now(timezone.utc).isoformat() + "Z"

    with get_connection() as conn:
        conn.execute(
            "UPDATE documents SET archived_at = ? WHERE id = ?",
            (now, id),
        )
        conn.commit()

    return {"success": True, "id": id, "archived_at": now}


@router.post("/{id}/unarchive")
async def unarchive_document(id: int):
    """Restore an archived document."""
    from api.database import get_connection

    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    with get_connection() as conn:
        conn.execute(
            "UPDATE documents SET archived_at = NULL WHERE id = ?",
            (id,),
        )
        conn.commit()

    return {"success": True, "id": id, "archived_at": None}


@router.post("/reclassify-other")
async def reclassify_other_documents():
    """
    Re-classify documents currently typed as OTHER using content-based classification.

    Priority order:
    1. Haiku's auction_source from extraction outputs (most accurate)
    2. PDF text content patterns (_classify_from_text)
    3. Filename patterns (fallback for scanned PDFs)

    Safe to run multiple times — only updates documents that match a known pattern.
    """
    from api.database import get_connection

    updated = 0
    skipped = 0

    other_type = AuctionTypeRepository.get_by_code("OTHER")
    if not other_type:
        return {"updated": 0, "skipped": 0, "message": "No OTHER type found"}

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT d.id, d.filename, d.email_metadata_json, d.raw_text,
                      er.outputs_json
               FROM documents d
               LEFT JOIN extraction_runs er ON er.document_id = d.id
                 AND er.id = (SELECT MAX(e2.id) FROM extraction_runs e2 WHERE e2.document_id = d.id)
               WHERE d.auction_type_id = ?""",
            (other_type.id,),
        ).fetchall()

    for row in rows:
        doc_id = row["id"]
        filename = row["filename"]
        raw_text = row["raw_text"] or ""

        new_code = None

        # 1. Check Haiku's auction_source (highest authority)
        if row["outputs_json"]:
            try:
                outputs = json.loads(row["outputs_json"])
                haiku_source = (outputs.get("auction_source") or "").upper()
                if haiku_source in ("COPART", "IAA", "MANHEIM"):
                    new_code = haiku_source
            except (json.JSONDecodeError, TypeError):
                pass

        # 2. Check PDF text content
        if not new_code:
            new_code = _classify_from_text(raw_text)

        # 3. Filename fallback (only for scanned PDFs)
        if not new_code and len(raw_text.strip()) < 100:
            new_code = _classify_from_filename(filename)

        if new_code:
            new_type = AuctionTypeRepository.get_by_code(new_code)
            if new_type:
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE documents SET auction_type_id = ? WHERE id = ?",
                        (new_type.id, doc_id),
                    )
                    # Also update extraction run's auction_type_id
                    conn.execute(
                        "UPDATE extraction_runs SET auction_type_id = ? WHERE document_id = ? AND id = (SELECT MAX(id) FROM extraction_runs WHERE document_id = ?)",
                        (new_type.id, doc_id, doc_id),
                    )
                    conn.commit()
                updated += 1
                continue

        skipped += 1

    return {"updated": updated, "skipped": skipped, "total_checked": len(rows)}


@router.post("/auto-assign-warehouse")
async def auto_assign_warehouse(request: Request):
    """
    Auto-assign best warehouse to documents without warehouse_id.

    Accepts optional document_ids list. If empty, processes all
    needs_review/approved extraction runs missing a warehouse.
    Uses DistanceService to pick the closest/cheapest warehouse.
    """
    import json as _json

    from api.database import get_connection

    body = await request.json()
    doc_ids = body.get("document_ids", [])

    with get_connection() as conn:
        if doc_ids:
            placeholders = ",".join("?" * len(doc_ids))
            rows = conn.execute(
                f"""SELECT id, document_id, outputs_json FROM extraction_runs
                    WHERE document_id IN ({placeholders})
                    AND status IN ('needs_review', 'approved')
                    ORDER BY id DESC""",
                doc_ids,
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, document_id, outputs_json FROM extraction_runs
                   WHERE status IN ('needs_review', 'approved')
                   ORDER BY id DESC"""
            ).fetchall()

    # Deduplicate: keep latest run per document
    seen_docs = set()
    runs = []
    for row in rows:
        r = dict(row)
        if r["document_id"] in seen_docs:
            continue
        seen_docs.add(r["document_id"])
        outputs = r["outputs_json"]
        if isinstance(outputs, str):
            try:
                outputs = _json.loads(outputs)
            except (ValueError, TypeError):
                outputs = {}
        r["outputs"] = outputs or {}
        runs.append(r)

    # Filter to runs without warehouse
    unassigned = [r for r in runs if not r["outputs"].get("warehouse_id")]

    if not unassigned:
        return {"assigned": 0, "skipped": 0, "errors": [], "message": "All documents already have a warehouse"}

    # Load distance service once
    from services.distance_service import DistanceService

    svc = DistanceService()
    assigned = 0
    skipped = 0
    errors = []

    for run in unassigned:
        outputs = run["outputs"]
        pickup_zip = outputs.get("pickup_zip", "")
        pickup_city = outputs.get("pickup_city", "")
        pickup_state = outputs.get("pickup_state", "")

        if not pickup_zip and not pickup_city:
            skipped += 1
            continue

        try:
            options = svc.get_warehouse_options(pickup_zip, pickup_city, pickup_state)
            if not options:
                skipped += 1
                continue

            best = options[0]  # best_value=True, sorted by price/distance
            wh_id = best.warehouse_id

            # Fetch full warehouse record for delivery fields
            from api.routes.warehouses import _get_warehouse_by_id

            wh = _get_warehouse_by_id(wh_id)
            if not wh:
                skipped += 1
                continue

            # Merge into outputs
            merged = {**outputs}
            merged["warehouse_id"] = wh_id
            merged["delivery_name"] = wh.get("name", "")
            merged["delivery_address"] = wh.get("address", "")
            merged["delivery_city"] = wh.get("city", "")
            merged["delivery_state"] = wh.get("state", "")
            merged["delivery_zip"] = wh.get("zip_code", "")
            merged["delivery_location_type"] = wh.get("location_type") or "CROSS_DOCK"
            if wh.get("buyer_reference"):
                merged["delivery_buyer_number"] = wh.get("buyer_reference")

            # Save
            from api.models import ExtractionRunRepository

            ExtractionRunRepository.update(run["id"], outputs_json=merged)
            assigned += 1

        except Exception as e:
            errors.append({"run_id": run["id"], "doc_id": run["document_id"], "error": str(e)})

    return {
        "assigned": assigned,
        "skipped": skipped,
        "total": len(unassigned),
        "errors": errors,
    }


@router.delete("/{id}", status_code=204)
async def delete_document(id: int):
    """
    Delete a document and all related data.

    This will cascade delete:
    - Extraction runs for this document
    - Review items for those extraction runs
    - The document file from disk
    """
    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete file if exists
    if doc.file_path and os.path.exists(doc.file_path):
        os.remove(doc.file_path)

    # Delete from database with cascade
    from api.database import get_connection

    with get_connection() as conn:
        # First get extraction run IDs for this document
        run_ids = conn.execute(
            "SELECT id FROM extraction_runs WHERE document_id = ?", (id,)
        ).fetchall()
        run_ids = [r[0] for r in run_ids]

        # Delete review items for these runs
        if run_ids:
            placeholders = ",".join("?" * len(run_ids))
            conn.execute(f"DELETE FROM review_items WHERE run_id IN ({placeholders})", run_ids)

        # Delete extraction runs
        conn.execute("DELETE FROM extraction_runs WHERE document_id = ?", (id,))

        # Delete the document
        conn.execute("DELETE FROM documents WHERE id = ?", (id,))
        conn.commit()

    return None


@router.delete("/test-lab/clear-all", status_code=200)
async def clear_all_test_lab_documents():
    """
    Delete ALL Test Lab documents and their related data.

    This is a bulk operation that removes:
    - All documents with source='test_lab' or is_test=true
    - All extraction runs for those documents
    - All review items for those runs
    - All files from disk

    Use with caution - this cannot be undone!
    """
    from api.database import get_connection

    deleted_count = 0
    with get_connection() as conn:
        # Get all test lab documents
        docs = conn.execute("""
            SELECT id, file_path FROM documents
            WHERE source = 'test_lab' OR is_test = 1
        """).fetchall()

        for doc in docs:
            doc_id = doc[0]
            file_path = doc[1]

            # Delete file if exists
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass  # Continue even if file deletion fails

            # Get extraction run IDs for this document
            run_ids = conn.execute(
                "SELECT id FROM extraction_runs WHERE document_id = ?", (doc_id,)
            ).fetchall()
            run_ids = [r[0] for r in run_ids]

            # Delete review items for these runs
            if run_ids:
                placeholders = ",".join("?" * len(run_ids))
                conn.execute(f"DELETE FROM review_items WHERE run_id IN ({placeholders})", run_ids)

            # Delete extraction runs
            conn.execute("DELETE FROM extraction_runs WHERE document_id = ?", (doc_id,))

            deleted_count += 1

        # Delete all test lab documents
        conn.execute("DELETE FROM documents WHERE source = 'test_lab' OR is_test = 1")
        conn.commit()

    return {
        "success": True,
        "deleted_count": deleted_count,
        "message": f"Deleted {deleted_count} test documents",
    }


@router.get("/{id}/page/{page_num}/image")
async def get_document_page_image(
    id: int,
    page_num: int = 1,
    dpi: int = Query(default=150, ge=72, le=300, description="Resolution in DPI"),
):
    """
    Get a specific page of a PDF document as a PNG image.

    Used by the visual zone editor to display the document background.

    Args:
        id: Document ID
        page_num: Page number (1-indexed)
        dpi: Image resolution (default 150)

    Returns:
        PNG image of the requested page
    """
    import io

    from fastapi.responses import Response

    doc = DocumentRepository.get_by_id(id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not doc.file_path:
        raise HTTPException(status_code=404, detail="Document file path not found")

    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail=f"Document file not found on disk: {doc.file_path}")

    try:
        # Try pdf2image first (requires poppler)
        from pdf2image import convert_from_path

        images = convert_from_path(
            doc.file_path,
            dpi=dpi,
            first_page=page_num,
            last_page=page_num,
        )

        if not images:
            raise HTTPException(status_code=404, detail=f"Page {page_num} not found in document")

        # Convert to PNG bytes
        img_buffer = io.BytesIO()
        images[0].save(img_buffer, format="PNG")
        img_buffer.seek(0)

        return Response(
            content=img_buffer.getvalue(),
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",
                "Content-Disposition": f'inline; filename="page_{page_num}.png"',
            },
        )
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="pdf2image is not installed. Run: pip install pdf2image"
        )
    except Exception as e:
        error_msg = str(e)
        if "poppler" in error_msg.lower() or "pdftoppm" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Poppler is not installed. On Ubuntu: apt-get install poppler-utils. On macOS: brew install poppler"
            )
        raise HTTPException(status_code=500, detail=f"Failed to render page: {error_msg}")
