"""Test/Sandbox endpoints for PDF upload, preview, and dry-run."""

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter()


# ----- Pydantic Models -----


class VehiclePreview(BaseModel):
    """Preview of extracted vehicle data."""

    vin: str
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    lot_number: Optional[str] = None
    mileage: Optional[int] = None
    is_operable: Optional[bool] = None
    color: Optional[str] = None


class PickupLocation(BaseModel):
    """Pickup location details."""

    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None


class ExtractionPreview(BaseModel):
    """Full extraction preview response."""

    status: str  # 'ok', 'needs_review', 'fail', 'error'
    auction: str
    confidence_score: float
    matched_patterns: list[str]
    text_length: int
    needs_ocr: bool

    # Extracted data
    vehicles: list[VehiclePreview]
    pickup_location: Optional[PickupLocation] = None
    gate_pass: Optional[str] = None
    buyer_id: Optional[str] = None
    reference_id: Optional[str] = None
    total_amount: Optional[float] = None

    # Warnings
    warnings: list[str] = []

    # File info
    attachment_hash: str
    attachment_name: str


class CDPayloadPreview(BaseModel):
    """Preview of Central Dispatch listing payload."""

    endpoint: str
    method: str
    payload: dict[str, Any]
    validation_errors: list[str] = []
    warnings: list[str] = []


class SheetsRowPreview(BaseModel):
    """Preview of Google Sheets row."""

    columns: list[str]
    values: list[Any]
    row_dict: dict[str, Any]


class DryRunResult(BaseModel):
    """Result of a dry run."""

    extraction: ExtractionPreview
    cd_payload: Optional[CDPayloadPreview] = None
    sheets_row: Optional[SheetsRowPreview] = None
    warehouse_routing: Optional[dict[str, Any]] = None
    would_create: list[str]  # List of what would be created
    errors: list[str] = []


# ----- Helper Functions -----


def compute_file_hash(content: bytes) -> str:
    """Compute SHA256 hash of file content."""
    return hashlib.sha256(content).hexdigest()


def get_status_from_score(score: float) -> str:
    """Determine status based on extraction score."""
    if score >= 0.7:
        return "ok"
    elif score >= 0.3:
        return "needs_review"
    else:
        return "fail"


# ----- Endpoints -----


class UploadAndExtractResponse(BaseModel):
    """Full response for upload with extraction and run creation."""

    # Extraction preview data
    extraction: ExtractionPreview

    # Document and run info (when auto-created)
    document_id: Optional[int] = None
    run_id: Optional[int] = None
    run_status: Optional[str] = None

    # Invoice data for UI display (legacy format)
    invoice: Optional[dict[str, Any]] = None


@router.post("/upload")
async def upload_and_extract(
    file: UploadFile = File(...),
    auto_save: bool = Form(default=False),
    auction_type_id: Optional[int] = Form(default=None),
):
    """
    Upload a PDF and extract data.

    Returns extraction preview with confidence scores and warnings.

    Options:
    - auto_save: If true, saves document and creates extraction run
    - auction_type_id: Required if auto_save=true, auction type for the document
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    # Read file content
    content = await file.read()
    file_hash = compute_file_hash(content)

    # Save to temp file for extraction
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from extractors import ExtractorManager

        manager = ExtractorManager()

        # Classify first
        classification = manager.classify(tmp_path)
        text = classification.text
        text_length = len(text) if text else 0

        # Check if OCR is needed
        needs_ocr = text_length < 100

        # Extract
        result = manager.extract_with_result(tmp_path)

        # Build response
        vehicles = []
        pickup_location = None
        gate_pass = None
        buyer_id = None
        reference_id = None
        total_amount = None
        warnings = []

        if result.invoice:
            inv = result.invoice

            for v in inv.vehicles:
                vehicles.append(
                    VehiclePreview(
                        vin=v.vin,
                        year=v.year,
                        make=v.make,
                        model=v.model,
                        lot_number=v.lot_number,
                        mileage=v.mileage,
                        is_operable=v.is_operable,
                        color=v.color,
                    )
                )

            if inv.pickup_address:
                loc = inv.pickup_address
                pickup_location = PickupLocation(
                    name=loc.name,
                    address=loc.street,
                    city=loc.city,
                    state=loc.state,
                    zip_code=loc.postal_code,
                    phone=loc.phone,
                )

            gate_pass = getattr(inv, "gate_pass", None) or getattr(inv, "release_id", None)
            buyer_id = inv.buyer_id
            reference_id = inv.reference_id
            total_amount = inv.total_amount

            # Check for warnings
            has_critical_missing = not inv.pickup_address or not inv.buyer_id or not inv.vehicles
            if has_critical_missing:
                warnings.append("Missing critical fields - needs review")

            for v in inv.vehicles:
                if not v.vin or len(v.vin) != 17:
                    warnings.append(f"Invalid VIN: {v.vin or 'missing'}")
        else:
            warnings.append("Extraction failed - no data extracted")

        # Determine auction source string
        if needs_ocr or classification.score < 0.3:
            auction_source = "UNKNOWN"
        else:
            auction_source = classification.source.value

        extraction_preview = ExtractionPreview(
            status=get_status_from_score(result.score),
            auction=auction_source,
            confidence_score=round(result.score * 100, 1),
            matched_patterns=classification.matched_patterns,
            text_length=text_length,
            needs_ocr=needs_ocr,
            vehicles=vehicles,
            pickup_location=pickup_location,
            gate_pass=gate_pass,
            buyer_id=buyer_id,
            reference_id=reference_id,
            total_amount=total_amount,
            warnings=warnings,
            attachment_hash=file_hash,
            attachment_name=file.filename,
        )

        # Build invoice dict for legacy UI format
        invoice_dict = None
        if result.invoice:
            inv = result.invoice
            invoice_dict = {
                "source": auction_source,
                "reference_id": inv.reference_id,
                "buyer_id": inv.buyer_id,
                "total_amount": inv.total_amount,
                "vehicles": [
                    {
                        "vin": v.vin,
                        "year": v.year,
                        "make": v.make,
                        "model": v.model,
                        "lot_number": v.lot_number,
                        "mileage": v.mileage,
                        "color": v.color,
                        "is_operable": v.is_operable,
                    }
                    for v in inv.vehicles
                ],
                "pickup_address": (
                    {
                        "name": inv.pickup_address.name,
                        "street": inv.pickup_address.street,
                        "city": inv.pickup_address.city,
                        "state": inv.pickup_address.state,
                        "postal_code": inv.pickup_address.postal_code,
                        "phone": inv.pickup_address.phone,
                    }
                    if inv.pickup_address
                    else None
                ),
            }

        # Optional: auto-save document and create run
        document_id = None
        run_id = None
        run_status = None

        if auto_save:
            from api.models import (
                AuctionTypeRepository,
                DocumentRepository,
                ExtractionRunRepository,
            )

            # Get auction type (use provided or try to match from classification)
            at_id = auction_type_id
            if not at_id:
                # Try to find auction type by source code
                at = AuctionTypeRepository.get_by_code(auction_source)
                if at:
                    at_id = at.id

            if not at_id:
                # Default to first active auction type
                from api.database import get_connection

                with get_connection() as conn:
                    row = conn.execute(
                        "SELECT id FROM auction_types WHERE is_active = TRUE LIMIT 1"
                    ).fetchone()
                    if row:
                        at_id = row["id"]

            if at_id:
                # Save document
                upload_path = Path(tmp_path).parent / f"{file_hash[:16]}_{file.filename}"
                with open(upload_path, "wb") as f:
                    f.write(content)

                document_id = DocumentRepository.create(
                    auction_type_id=at_id,
                    dataset_split="train",
                    filename=file.filename,
                    file_path=str(upload_path),
                    file_size=len(content),
                    sha256=file_hash,
                    raw_text=text,
                    uploaded_by="test_lab",
                )

                # Create and run extraction
                run_id = ExtractionRunRepository.create(
                    document_id=document_id,
                    auction_type_id=at_id,
                    extractor_kind="rule",
                )

                # Run extraction
                from api.routes.extractions import run_extraction

                run_extraction(run_id, document_id, at_id, "rule", None)

                # Get updated run status
                run = ExtractionRunRepository.get_by_id(run_id)
                run_status = run.status if run else None

        return {
            "extraction": extraction_preview.model_dump(),
            "document_id": document_id,
            "run_id": run_id,
            "run_status": run_status,
            "invoice": invoice_dict,
        }

    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.post("/preview-cd", response_model=CDPayloadPreview)
async def preview_cd_payload(
    file: UploadFile = File(...),
):
    """
    Preview the Central Dispatch listing payload.

    Shows exactly what would be sent to CD API without actually creating the listing.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    content = await file.read()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from extractors import ExtractorManager

        manager = ExtractorManager()
        result = manager.extract_with_result(tmp_path)

        if not result.invoice or not result.invoice.vehicles:
            raise HTTPException(status_code=400, detail="No vehicles extracted from PDF")

        inv = result.invoice
        vehicle = inv.vehicles[0]

        # Build CD payload
        validation_errors = []
        warnings = []

        # Check required fields
        if not vehicle.vin or len(vehicle.vin) != 17:
            validation_errors.append("Invalid or missing VIN")

        if not inv.pickup_address or not inv.pickup_address.city:
            validation_errors.append("Missing pickup location")

        # Build payload structure (based on CD Listings API V2)
        payload = {
            "vehicle": {
                "vin": vehicle.vin or "",
                "year": vehicle.year,
                "make": vehicle.make or "",
                "model": vehicle.model or "",
                "is_operable": vehicle.is_operable if vehicle.is_operable is not None else True,
            },
            "origin": {
                "city": inv.pickup_address.city if inv.pickup_address else "",
                "state": inv.pickup_address.state if inv.pickup_address else "",
                "zip": inv.pickup_address.postal_code if inv.pickup_address else "",
            },
            "destination": {
                "city": "",  # Needs warehouse routing
                "state": "",
                "zip": "",
            },
            "notes": f"Gate Pass: {inv.gate_pass}" if inv.gate_pass else "",
            "price": {
                "amount": 0,
                "type": "open",
            },
        }

        if not payload["destination"]["city"]:
            warnings.append("Destination not set - needs warehouse routing")

        return CDPayloadPreview(
            endpoint="/api/v2/listings",
            method="POST",
            payload=payload,
            validation_errors=validation_errors,
            warnings=warnings,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build CD payload: {str(e)}")
    finally:
        os.unlink(tmp_path)


@router.post("/preview-sheets-row", response_model=SheetsRowPreview)
async def preview_sheets_row(
    file: UploadFile = File(...),
):
    """
    Preview the Google Sheets row that would be written.

    Shows the exact data that would appear in the spreadsheet.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    content = await file.read()
    file_hash = compute_file_hash(content)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from extractors import ExtractorManager
        from services.sheets_exporter import load_schema

        manager = ExtractorManager()
        classification = manager.classify(tmp_path)
        result = manager.extract_with_result(tmp_path)

        # Load schema for column names
        schema = load_schema()
        column_names = [col["name"] for col in schema["columns"]]

        # Build row dict
        row_dict = {
            "run_id": "preview",
            "row_id": "preview",
            "processed_at": "preview",
            "source_type": "upload",
            "attachment_name": file.filename,
            "attachment_hash": file_hash[:16] + "...",
            "auction": classification.source.value,
            "extraction_score": round(result.score * 100, 1),
            "status": get_status_from_score(result.score),
            "matched_patterns": ", ".join(classification.matched_patterns),
        }

        if result.invoice:
            inv = result.invoice
            if inv.vehicles:
                v = inv.vehicles[0]
                row_dict.update(
                    {
                        "vin": v.vin,
                        "vehicle_year": v.year,
                        "vehicle_make": v.make,
                        "vehicle_model": v.model,
                        "lot_number": v.lot_number,
                        "mileage": v.mileage,
                        "is_operable": v.is_operable,
                        "vehicle_color": v.color,
                    }
                )

            if inv.pickup_address:
                loc = inv.pickup_address
                row_dict.update(
                    {
                        "pickup_name": loc.name,
                        "pickup_address": loc.street,
                        "pickup_city": loc.city,
                        "pickup_state": loc.state,
                        "pickup_zip": loc.postal_code,
                        "pickup_phone": loc.phone,
                    }
                )

            row_dict.update(
                {
                    "gate_pass": getattr(inv, "gate_pass", None) or inv.release_id,
                    "buyer_id": inv.buyer_id,
                    "reference_id": inv.reference_id,
                    "total_amount": inv.total_amount,
                }
            )

        # Build values list in column order
        values = []
        for col in column_names:
            values.append(row_dict.get(col, ""))

        return SheetsRowPreview(
            columns=column_names,
            values=values,
            row_dict=row_dict,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build Sheets row: {str(e)}")
    finally:
        os.unlink(tmp_path)


@router.post("/dry-run", response_model=DryRunResult)
async def dry_run(
    file: UploadFile = File(...),
    include_cd: bool = Form(default=True),
    include_sheets: bool = Form(default=True),
    include_warehouse: bool = Form(default=True),
):
    """
    Perform a complete dry run of the pipeline.

    Shows what would happen if this PDF was processed, including:
    - Extraction results
    - CD payload (if enabled)
    - Sheets row (if enabled)
    - Warehouse routing (if enabled)

    Does NOT actually create anything - purely for preview.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    content = await file.read()
    file_hash = compute_file_hash(content)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from extractors import ExtractorManager
        from services.sheets_exporter import load_schema

        manager = ExtractorManager()
        classification = manager.classify(tmp_path)
        result = manager.extract_with_result(tmp_path)

        errors = []
        would_create = []

        # Build extraction preview
        vehicles = []
        pickup_location = None
        warnings = []

        if result.invoice:
            inv = result.invoice
            for v in inv.vehicles:
                vehicles.append(
                    VehiclePreview(
                        vin=v.vin,
                        year=v.year,
                        make=v.make,
                        model=v.model,
                        lot_number=v.lot_number,
                        mileage=v.mileage,
                        is_operable=v.is_operable,
                        color=v.color,
                    )
                )

            if inv.pickup_address:
                loc = inv.pickup_address
                pickup_location = PickupLocation(
                    name=loc.name,
                    address=loc.street,
                    city=loc.city,
                    state=loc.state,
                    zip_code=loc.postal_code,
                    phone=loc.phone,
                )

        extraction = ExtractionPreview(
            status=get_status_from_score(result.score),
            auction=classification.source.value,
            confidence_score=round(result.score * 100, 1),
            matched_patterns=classification.matched_patterns,
            text_length=result.text_length,
            needs_ocr=result.needs_ocr,
            vehicles=vehicles,
            pickup_location=pickup_location,
            gate_pass=(
                (
                    getattr(result.invoice, "gate_pass", None)
                    or getattr(result.invoice, "release_id", None)
                )
                if result.invoice
                else None
            ),
            buyer_id=result.invoice.buyer_id if result.invoice else None,
            reference_id=result.invoice.reference_id if result.invoice else None,
            total_amount=result.invoice.total_amount if result.invoice else None,
            warnings=warnings,
            attachment_hash=file_hash,
            attachment_name=file.filename,
        )

        # CD Payload preview
        cd_payload = None
        if include_cd and result.invoice and result.invoice.vehicles:
            vehicle = result.invoice.vehicles[0]
            inv = result.invoice

            payload = {
                "vehicle": {
                    "vin": vehicle.vin or "",
                    "year": vehicle.year,
                    "make": vehicle.make or "",
                    "model": vehicle.model or "",
                },
                "origin": {
                    "city": inv.pickup_address.city if inv.pickup_address else "",
                    "state": inv.pickup_address.state if inv.pickup_address else "",
                },
            }

            cd_payload = CDPayloadPreview(
                endpoint="/api/v2/listings",
                method="POST",
                payload=payload,
                validation_errors=[],
                warnings=[],
            )
            would_create.append("Central Dispatch listing")

        # Sheets row preview
        sheets_row = None
        if include_sheets:
            schema = load_schema()
            column_names = [col["name"] for col in schema["columns"]]

            row_dict = {
                "auction": classification.source.value,
                "extraction_score": round(result.score * 100, 1),
                "status": get_status_from_score(result.score),
                "attachment_name": file.filename,
                "attachment_hash": file_hash[:16] + "...",
            }

            if result.invoice:
                inv = result.invoice
                if inv.vehicles:
                    v = inv.vehicles[0]
                    row_dict.update(
                        {
                            "vin": v.vin,
                            "vehicle_year": v.year,
                            "vehicle_make": v.make,
                            "vehicle_model": v.model,
                        }
                    )

            values = [row_dict.get(col, "") for col in column_names]

            sheets_row = SheetsRowPreview(
                columns=column_names,
                values=values,
                row_dict=row_dict,
            )
            would_create.append("Google Sheets row")

        # Warehouse routing
        warehouse_routing = None
        if include_warehouse and result.invoice and result.invoice.pickup_address:
            # For now, just show what we'd route
            loc = result.invoice.pickup_address
            warehouse_routing = {
                "pickup_location": {
                    "city": loc.city,
                    "state": loc.state,
                    "zip": loc.postal_code,
                },
                "message": "Warehouse routing would be determined based on pickup location",
            }

        return DryRunResult(
            extraction=extraction,
            cd_payload=cd_payload,
            sheets_row=sheets_row,
            warehouse_routing=warehouse_routing,
            would_create=would_create,
            errors=errors,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dry run failed: {str(e)}")
    finally:
        os.unlink(tmp_path)


@router.post("/classify")
async def classify_pdf(file: UploadFile = File(...)):
    """
    Classify a PDF to determine the auction source.

    Returns classification result with:
    - source: detected auction source (IAA, COPART, MANHEIM, UNKNOWN)
    - score: confidence percentage (0-100)
    - extractor: extractor name or None
    - needs_ocr: true if text extraction failed (scanned PDF)
    - text_length: number of characters extracted
    - matched_patterns: list of patterns that matched
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    content = await file.read()

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from extractors import ExtractorManager

        manager = ExtractorManager()

        # Get full classification with text
        classification = manager.classify(tmp_path)
        text_length = len(classification.text) if classification.text else 0

        # Determine if OCR is needed (text too short for reliable extraction)
        needs_ocr = text_length < 100

        # Determine source - UNKNOWN if score too low or needs_ocr
        if needs_ocr or classification.score < 0.3:
            source = "UNKNOWN"
            extractor_name = None
            score = 0.0
            matched_patterns = []
        else:
            source = classification.source.value
            extractor_name = (
                classification.extractor.__class__.__name__ if classification.extractor else None
            )
            score = classification.score
            matched_patterns = classification.matched_patterns

        # Get all scores for detailed view
        all_scores = manager.get_all_scores(tmp_path)

        return {
            # Primary classification result (UI expects these)
            "source": source,
            "score": round(score * 100, 1),
            "extractor": extractor_name,
            "needs_ocr": needs_ocr,
            "text_length": text_length,
            "matched_patterns": matched_patterns,
            # Detailed scores for all extractors
            "all_scores": [
                {
                    "source": s.value,
                    "score": round(sc * 100, 1),
                    "patterns": p,
                }
                for s, sc, p in all_scores
            ],
            # File info
            "filename": file.filename,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Classification failed: {str(e)}")
    finally:
        os.unlink(tmp_path)
