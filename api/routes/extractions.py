"""
Extractions API Routes

Run and manage extraction runs on documents.
"""

import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

if TYPE_CHECKING:
    from extractors.spatial_parser import DocumentStructure
from pydantic import BaseModel, Field

from api.models import (
    AuctionTypeRepository,
    DocumentRepository,
    ExtractionRunRepository,
    FieldEvidenceRepository,
    LayoutBlockRepository,
    ModelVersionRepository,
    ReviewItemRepository,
)

router = APIRouter(prefix="/api/extractions", tags=["Extractions"])


# =============================================================================
# BLOCK EXTRACTION IMPORTS (M3.P0.1)
# =============================================================================


def _get_block_extractor():
    """Lazy import for block extractor."""
    from extractors.block_extractor import get_block_extractor

    return get_block_extractor()


def _get_spatial_parser():
    """Lazy import for spatial parser."""
    from extractors.spatial_parser import get_spatial_parser

    return get_spatial_parser()


def _get_field_resolver():
    """Lazy import for field resolver."""
    from extractors.field_resolver import get_field_resolver

    return get_field_resolver()


def _get_ocr_strategy():
    """Lazy import for OCR strategy."""
    from extractors.ocr_strategy import get_ocr_strategy

    return get_ocr_strategy()


def _run_ocr_if_needed(
    file_path: str,
    raw_text: str,
    metrics: dict,
    timeout_seconds: int = 120,
) -> tuple[str, bool]:
    """
    Run OCR if needed based on text quality assessment (M3.P0.3).

    Uses OCRmyPDF to add/replace OCR layer in the PDF, then
    re-extracts text from the resulting file.

    Args:
        file_path: Path to PDF file
        raw_text: Pre-extracted native text
        metrics: Metrics dict to update
        timeout_seconds: OCR timeout

    Returns:
        Tuple of (text after OCR, was_ocr_applied)
    """
    import logging
    import os
    import tempfile
    import time

    logger = logging.getLogger(__name__)

    # Analyze text quality
    ocr_strategy = _get_ocr_strategy()
    quality_before = ocr_strategy.analyze_text_quality(raw_text)

    metrics["text_quality_score_before"] = quality_before.quality.value
    metrics["text_quality_metrics"] = quality_before.to_dict()

    # Check if OCR is needed
    should_ocr, reason = ocr_strategy.should_use_ocr(raw_text)

    if not should_ocr:
        metrics["ocr_applied"] = False
        metrics["ocr_skip_reason"] = reason
        metrics["text_mode"] = "native"
        return raw_text, False

    # OCR is recommended
    logger.info(f"OCR recommended: {reason}")
    metrics["ocr_reason"] = reason

    # Try to run OCRmyPDF
    try:
        import subprocess

        # Check if ocrmypdf is available
        which_result = subprocess.run(["which", "ocrmypdf"], capture_output=True, text=True)
        if which_result.returncode != 0:
            logger.warning("ocrmypdf not found, skipping OCR")
            metrics["ocr_applied"] = False
            metrics["ocr_error"] = "ocrmypdf not installed"
            return raw_text, False

        # Create temp file for OCR output
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            ocr_output_path = tmp.name

        start_time = time.time()

        # Run OCRmyPDF
        # --skip-text: Only OCR pages without text layer
        # --redo-ocr: Redo OCR even if text exists (for hybrid mode)
        # --force-ocr: Always OCR (for full OCR mode)
        ocr_cmd = [
            "ocrmypdf",
            "--skip-text",  # Don't OCR pages that already have text
            "--deskew",  # Straighten tilted pages
            "--clean",  # Clean up pages before OCR
            "--quiet",  # Reduce output
            "-l",
            "eng",  # English language
            file_path,
            ocr_output_path,
        ]

        result = subprocess.run(ocr_cmd, capture_output=True, text=True, timeout=timeout_seconds)

        ocr_duration_ms = int((time.time() - start_time) * 1000)
        metrics["ocr_duration_ms"] = ocr_duration_ms

        if result.returncode != 0:
            # OCR failed
            logger.warning(f"OCRmyPDF failed: {result.stderr[:200]}")
            metrics["ocr_applied"] = False
            metrics["ocr_error"] = result.stderr[:200] if result.stderr else "Unknown error"

            # Cleanup temp file
            if os.path.exists(ocr_output_path):
                os.remove(ocr_output_path)

            return raw_text, False

        # OCR succeeded - extract text from OCR'd PDF
        import pdfplumber

        ocr_text_parts = []
        pages_ocrd = 0

        with pdfplumber.open(ocr_output_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    ocr_text_parts.append(page_text)
                    pages_ocrd += 1

        ocr_text = "\n".join(ocr_text_parts)

        # Cleanup temp file
        if os.path.exists(ocr_output_path):
            os.remove(ocr_output_path)

        # Analyze quality after OCR
        quality_after = ocr_strategy.analyze_text_quality(ocr_text)

        metrics["ocr_applied"] = True
        metrics["pages_ocrd_count"] = pages_ocrd
        metrics["text_quality_score_after"] = quality_after.quality.value
        metrics["text_mode"] = "hybrid" if quality_before.total_chars > 50 else "ocr"
        metrics["raw_text_length_after_ocr"] = len(ocr_text)
        metrics["words_count_after_ocr"] = len(ocr_text.split()) if ocr_text else 0

        logger.info(
            f"OCR completed: {ocr_duration_ms}ms, "
            f"quality {quality_before.quality.value} -> {quality_after.quality.value}"
        )

        # Use OCR text if it's better, otherwise keep original
        if len(ocr_text) > len(raw_text) * 1.2:  # OCR text significantly longer
            return ocr_text, True
        elif quality_after.quality.value in (
            "excellent",
            "good",
        ) and quality_before.quality.value in ("poor", "unusable"):
            return ocr_text, True
        else:
            # Merge: use longer of the two
            if len(ocr_text) > len(raw_text):
                return ocr_text, True
            else:
                metrics["ocr_text_not_used"] = "native text better"
                return raw_text, True

    except subprocess.TimeoutExpired:
        logger.warning(f"OCR timed out after {timeout_seconds}s")
        metrics["ocr_applied"] = False
        metrics["ocr_error"] = f"Timeout after {timeout_seconds}s"
        return raw_text, False

    except Exception as e:
        logger.error(f"OCR error: {e}")
        metrics["ocr_applied"] = False
        metrics["ocr_error"] = str(e)
        return raw_text, False


def _run_block_extraction(
    document_id: int,
    run_id: int,
    file_path: str,
    raw_text: str,
    metrics: dict,
) -> tuple[dict, list]:
    """
    Run block-based extraction (M3.P0.1).

    This is the new default extraction path using layout-aware extraction.
    Falls back to pattern extraction when block extraction fails.

    Args:
        document_id: Document database ID
        run_id: Extraction run ID
        file_path: Path to PDF file
        raw_text: Pre-extracted raw text
        metrics: Metrics dict to update

    Returns:
        Tuple of (extracted_fields dict, evidence_list)
    """
    import logging

    logger = logging.getLogger(__name__)
    extracted_fields = {}
    evidence_list = []

    try:
        # 1. Parse document structure with spatial awareness
        parser = _get_spatial_parser()
        structure = parser.parse(file_path)

        # Update metrics with layout info (M3.P1.1 column detection)
        metrics["layout_blocks_count"] = len(structure.blocks)
        metrics["detected_columns_count"] = structure.column_count
        metrics["reading_order_strategy"] = structure.reading_order_strategy
        if structure.detected_columns:
            metrics["column_boundaries"] = [
                {"start": c[0], "end": c[1]} for c in structure.detected_columns
            ]

        # 2. Store layout blocks in database
        if structure.blocks and document_id:
            _store_layout_blocks(document_id, structure)

        # 3. Run block-based extraction
        extractor = _get_block_extractor()
        results = extractor.extract_all_fields(structure, use_fallback=True)

        # 4. Collect extracted values and evidence
        for field_key, result in results.items():
            if result.success and result.value:
                extracted_fields[field_key] = result.value

                if result.evidence:
                    evidence_dict = result.evidence.to_dict()
                    evidence_list.append(evidence_dict)

        # 5. Update metrics
        metrics["block_extraction_used"] = True
        metrics["fields_from_blocks"] = sum(
            1
            for r in results.values()
            if r.success and r.evidence and r.evidence.extraction_method != "pattern"
        )
        metrics["fields_from_patterns"] = sum(
            1
            for r in results.values()
            if r.success and r.evidence and r.evidence.extraction_method == "pattern"
        )
        metrics["evidence_coverage"] = (
            len(evidence_list) / len(extracted_fields) * 100 if extracted_fields else 0
        )

        logger.info(
            f"Block extraction: {len(extracted_fields)} fields, "
            f"{len(evidence_list)} evidence records"
        )

    except Exception as e:
        logger.warning(f"Block extraction failed, falling back to pattern: {e}")
        metrics["block_extraction_used"] = False
        metrics["block_extraction_error"] = str(e)

    return extracted_fields, evidence_list


def _store_layout_blocks(document_id: int, structure: "DocumentStructure") -> int:
    """
    Store layout blocks from DocumentStructure to database.

    Args:
        document_id: Document database ID
        structure: Parsed DocumentStructure

    Returns:
        Number of blocks stored
    """
    import logging

    logger = logging.getLogger(__name__)

    blocks_to_store = []

    for block in structure.blocks:
        blocks_to_store.append(
            {
                "block_id": block.id,
                "page_num": block.page,
                "x0": block.x0,
                "y0": block.y0,
                "x1": block.x1,
                "y1": block.y1,
                "text": block.text[:1000] if block.text else None,  # Truncate for DB
                "block_type": block.block_type,
                "label": block.label,
                "text_source": "native",
                "confidence": 1.0,
            }
        )

    if blocks_to_store:
        try:
            # Clear existing blocks for this document first
            LayoutBlockRepository.delete_by_document(document_id)
            # Store new blocks (document_id passed separately)
            ids = LayoutBlockRepository.create_batch(document_id, blocks_to_store)
            logger.info(f"Stored {len(ids)} layout blocks for document {document_id}")
            return len(ids)
        except Exception as e:
            logger.error(f"Failed to store layout blocks: {e}")
            return 0

    return 0


def _store_field_evidence(run_id: int, evidence_list: list, document_id: int = None) -> int:
    """
    Store field evidence from extraction.

    Args:
        run_id: Extraction run ID
        evidence_list: List of evidence dicts
        document_id: Optional document ID for linking to blocks

    Returns:
        Number of evidence records stored
    """
    import logging

    logger = logging.getLogger(__name__)

    if not evidence_list:
        return 0

    # If we have document_id, try to link evidence to stored layout blocks
    if document_id:
        stored_blocks = LayoutBlockRepository.get_by_document(document_id)
        block_map = {b.block_id: b.id for b in stored_blocks}

        for evidence in evidence_list:
            block_str_id = evidence.get("_block_str_id") or evidence.get("block_id")
            if block_str_id and isinstance(block_str_id, str) and block_str_id in block_map:
                evidence["block_id"] = block_map[block_str_id]

    try:
        ids = FieldEvidenceRepository.create_batch(run_id, evidence_list)
        logger.info(f"Stored {len(ids)} evidence records for run {run_id}")
        return len(ids)
    except Exception as e:
        logger.error(f"Failed to store field evidence: {e}")
        return 0


def generate_order_id(make: str, model: str, sale_date: datetime = None) -> str:
    """
    Generate custom Order ID in format: MMDD + MAKE(3) + MODEL(1) + SEQ

    Example: February 1st + Jeep Grand Cherokee = 21JEEG1
    - 21 = Month 2, Day 1 (concatenated, not padded)
    - JEE = First 3 letters of Make (JEEP)
    - G = First letter of Model (GRAND)
    - 1 = Sequence number (incremented for duplicates)

    Args:
        make: Vehicle make (e.g., "Jeep", "Toyota")
        model: Vehicle model (e.g., "Grand Cherokee", "Camry")
        sale_date: Date to use (defaults to today)

    Returns:
        Order ID string like "21JEEG1"
    """
    if sale_date is None:
        sale_date = datetime.now()

    # Month + Day (as digits, e.g., February 1 = "21")
    month = str(sale_date.month)  # 1-12, no zero padding
    day = str(sale_date.day)  # 1-31, no zero padding
    date_part = month + day

    # Make: first 3 letters, uppercase
    make_clean = "".join(c for c in make.upper() if c.isalpha())[:3]
    make_part = make_clean.ljust(3, "X")  # Pad with X if too short

    # Model: first letter, uppercase
    model_clean = "".join(c for c in model.upper() if c.isalpha())
    model_part = model_clean[0] if model_clean else "X"

    # Base ID without sequence
    base_id = f"{date_part}{make_part}{model_part}"

    # Find next sequence number by checking existing runs
    from api.database import get_connection

    with get_connection() as conn:
        # Count existing orders with same base
        result = conn.execute(
            """SELECT COUNT(*) FROM extraction_runs
               WHERE outputs_json LIKE ?
               AND date(created_at) = date(?)""",
            (f'%"order_id": "{base_id}%', sale_date.strftime("%Y-%m-%d")),
        ).fetchone()
        seq = (result[0] if result else 0) + 1

    return f"{base_id}{seq}"


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class ExtractionRunRequest(BaseModel):
    """Request model for running extraction."""

    document_id: int = Field(..., description="Document ID to extract from")
    force_ml: bool = Field(False, description="Force ML extraction even if no active model")


class ExtractionRunResponse(BaseModel):
    """Response model for extraction run."""

    id: int
    uuid: str
    document_id: int
    document_filename: Optional[str] = None
    auction_type_id: int
    auction_type_code: Optional[str] = None
    extractor_kind: str = "rule"
    model_version_id: Optional[int] = None
    model_version_tag: Optional[str] = None
    status: str = "pending"
    extraction_score: Optional[float] = None
    outputs: Optional[dict] = None
    errors: Optional[list] = None
    processing_time_ms: Optional[int] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None

    class Config:
        from_attributes = True


class ExtractionRunListResponse(BaseModel):
    """Response model for extraction run list."""

    items: list[ExtractionRunResponse]
    total: int


class ExtractionFieldOutput(BaseModel):
    """A single extracted field."""

    source_key: str
    internal_key: Optional[str] = None
    cd_key: Optional[str] = None
    value: Optional[str] = None
    confidence: Optional[float] = None
    source_location: Optional[str] = None


class ExtractionDetailResponse(BaseModel):
    """Detailed extraction response with field-level outputs."""

    run: ExtractionRunResponse
    fields: list[ExtractionFieldOutput]
    raw_text_preview: Optional[str] = None


class ExtractionMetricsResponse(BaseModel):
    """Extraction metrics for diagnostics."""

    raw_text_length: int = 0
    words_count: int = 0
    text_mode: str = "native"
    pages_count: int = 0
    detected_source: Optional[str] = None
    classification_score: float = 0.0
    classification_patterns: list[str] = []
    fields_extracted_count: int = 0
    fields_filled_count: int = 0
    required_fields_filled: int = 0
    required_fields_total: int = 0
    needs_ocr: bool = False
    has_pickup_address: bool = False
    has_vehicle_vin: bool = False
    has_vehicle_ymm: bool = False
    extractor_version: str = "1.0"
    extraction_timestamp: Optional[str] = None


class FieldSourceInfo(BaseModel):
    """Source info for a single field."""

    field_key: str
    value: Optional[str] = None
    source: str  # "EXTRACTED", "USER_OVERRIDE", "WAREHOUSE_CONST", "AUCTION_CONST", "DEFAULT"
    confidence: Optional[float] = None
    extractor_method: Optional[str] = None  # Which extraction method produced this value


class ExtractionDebugResponse(BaseModel):
    """Debug response for extraction diagnostics."""

    run_id: int
    document_id: int
    document_filename: Optional[str] = None
    auction_type: Optional[str] = None

    # Status and scoring
    status: str
    extraction_score: Optional[float] = None
    processing_time_ms: Optional[int] = None

    # Metrics
    metrics: Optional[ExtractionMetricsResponse] = None

    # Field sources - where each value came from
    field_sources: list[FieldSourceInfo] = []

    # Errors if any
    errors: Optional[list] = None

    # Raw text preview
    raw_text_preview: Optional[str] = None
    raw_text_length: int = 0

    # Classification details
    all_scores: list[dict] = []  # Scores from all extractors for comparison

    # Recommendations
    recommendations: list[str] = []


# =============================================================================
# EXTRACTION LOGIC
# =============================================================================


def run_extraction(
    run_id: int,
    document_id: int,
    auction_type_id: int,
    extractor_kind: str = "rule",
    model_version_id: int = None,
):
    """
    Execute extraction on a document.

    This function is called synchronously or as a background task.
    Tracks extraction metrics and field sources for diagnostics.
    """
    start_time = time.time()

    # Initialize metrics tracking
    metrics = {
        "raw_text_length": 0,
        "words_count": 0,
        "text_mode": "native",
        "pages_count": 0,
        "detected_source": None,
        "classification_score": 0.0,
        "classification_patterns": [],
        "fields_extracted_count": 0,
        "fields_filled_count": 0,
        "required_fields_filled": 0,
        "required_fields_total": 4,  # vin, pickup_address, pickup_city, pickup_state
        "needs_ocr": False,
        "has_pickup_address": False,
        "has_vehicle_vin": False,
        "has_vehicle_ymm": False,
        "extractor_version": "1.0",
        "extraction_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # Initialize field sources tracking
    field_sources = {}

    # Get document
    doc = DocumentRepository.get_by_id(document_id)
    if not doc:
        ExtractionRunRepository.update(
            run_id,
            status="failed",
            errors_json=[{"error": "Document not found"}],
            metrics_json=metrics,
        )
        return

    # Get auction type
    auction_type = AuctionTypeRepository.get_by_id(auction_type_id)
    if not auction_type:
        ExtractionRunRepository.update(
            run_id,
            status="failed",
            errors_json=[{"error": "Auction type not found"}],
            metrics_json=metrics,
        )
        return

    # Update status to processing
    ExtractionRunRepository.update(run_id, status="processing")

    try:
        # Get raw text from document
        raw_text = doc.raw_text or ""
        pages_count = 0

        if not raw_text and doc.file_path:
            # Try to extract text
            import pdfplumber

            with pdfplumber.open(doc.file_path) as pdf:
                pages_count = len(pdf.pages)
                text_parts = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                raw_text = "\n".join(text_parts)

        # Update metrics with text info
        metrics["raw_text_length"] = len(raw_text)
        metrics["words_count"] = len(raw_text.split()) if raw_text else 0
        metrics["pages_count"] = pages_count
        metrics["needs_ocr"] = len(raw_text) < 100

        # =================================================================
        # M3.P0.3: OCR STRATEGY - Run OCR if needed
        # Analyze text quality and apply OCR if native extraction is poor
        # =================================================================
        if doc.file_path:
            try:
                raw_text, ocr_applied = _run_ocr_if_needed(
                    doc.file_path, raw_text, metrics, timeout_seconds=120
                )
                # Update metrics after OCR
                if ocr_applied:
                    metrics["raw_text_length"] = len(raw_text)
                    metrics["words_count"] = len(raw_text.split()) if raw_text else 0
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(f"OCR strategy error: {e}")
                metrics["ocr_error"] = str(e)

        if not raw_text:
            ExtractionRunRepository.update(
                run_id,
                status="failed",
                errors_json=[{"error": "Could not extract text from document"}],
                metrics_json=metrics,
            )
            return

        # Run extraction based on kind
        if extractor_kind == "ml" and model_version_id:
            # TODO: Implement ML extraction
            # For now, fall back to rule-based
            extractor_kind = "rule"

        # Rule-based extraction
        outputs = {}
        extraction_score = 0.0
        evidence_list = []

        # =================================================================
        # M3.P0.1: BLOCK EXTRACTION (default path)
        # Run layout-aware extraction first, then fall back to pattern
        # =================================================================
        block_outputs = {}
        if doc.file_path:
            try:
                block_outputs, evidence_list = _run_block_extraction(
                    document_id=document_id,
                    run_id=run_id,
                    file_path=doc.file_path,
                    raw_text=raw_text,
                    metrics=metrics,
                )
                # Track block-extracted fields
                for key, value in block_outputs.items():
                    if value is not None:
                        field_sources[key] = {
                            "value": value,
                            "source": "EXTRACTED",
                            "confidence": 0.85,
                            "method": "block_extractor",
                        }
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(f"Block extraction error: {e}")
                metrics["block_extraction_error"] = str(e)

        # =================================================================
        # PATTERN EXTRACTION (fallback/supplement)
        # =================================================================
        from extractors import ExtractorManager

        manager = ExtractorManager()

        # Classify and extract
        classification = manager.get_extractor_for_text(raw_text)
        if classification:
            extractor = classification
            score, patterns = extractor.score(raw_text)
            metrics["classification_score"] = score
            metrics["classification_patterns"] = patterns[:10] if patterns else []
            metrics["detected_source"] = extractor.source.value

            result = extractor.extract_with_result(doc.file_path, raw_text)

            if result.invoice:
                inv = result.invoice
                # Map invoice to outputs with field source tracking
                outputs = {
                    "auction_source": result.source.value if result.source else auction_type.code,
                    "reference_id": inv.reference_id,
                    "buyer_id": inv.buyer_id,
                    "buyer_name": inv.buyer_name,
                    "sale_date": inv.sale_date,
                    "total_amount": inv.total_amount,
                }

                # Track field sources for base fields
                for key, value in outputs.items():
                    field_sources[key] = {
                        "value": value,
                        "source": "EXTRACTED" if value is not None else "DEFAULT",
                        "confidence": 0.7 if value is not None else 0.0,
                        "method": f"{extractor.source.value.lower()}_extractor",
                    }

                # Pickup address
                if inv.pickup_address:
                    addr = inv.pickup_address
                    # pickup_address should be street address; fallback to location name if no street
                    # Central Dispatch requires pickup_address, so provide best available info
                    street_address = addr.street
                    if not street_address and addr.name:
                        # Use location name as fallback (e.g., "IAA Tampa South")
                        street_address = addr.name

                    pickup_fields = {
                        "pickup_name": addr.name,
                        "pickup_address": street_address,
                        "pickup_city": addr.city,
                        "pickup_state": addr.state,
                        "pickup_zip": addr.postal_code,
                        "pickup_phone": addr.phone,
                    }
                    outputs.update(pickup_fields)

                    # Track pickup field sources
                    for key, value in pickup_fields.items():
                        field_sources[key] = {
                            "value": value,
                            "source": "EXTRACTED" if value else "DEFAULT",
                            "confidence": 0.6 if value else 0.0,
                            "method": "address_extractor",
                        }

                    metrics["has_pickup_address"] = bool(street_address)

                # Vehicles
                if inv.vehicles:
                    v = inv.vehicles[0]
                    vehicle_fields = {
                        "vehicle_vin": v.vin,
                        "vehicle_year": v.year,
                        "vehicle_make": v.make,
                        "vehicle_model": v.model,
                        "vehicle_color": v.color,
                        "vehicle_lot": v.lot_number,
                        "vehicle_mileage": v.mileage,
                        "vehicle_is_inoperable": v.is_inoperable,
                    }
                    outputs.update(vehicle_fields)

                    # Track vehicle field sources
                    for key, value in vehicle_fields.items():
                        field_sources[key] = {
                            "value": value,
                            "source": "EXTRACTED" if value is not None else "DEFAULT",
                            "confidence": 0.8 if value is not None else 0.0,
                            "method": "vehicle_extractor",
                        }

                    metrics["has_vehicle_vin"] = bool(v.vin)
                    metrics["has_vehicle_ymm"] = bool(v.year and v.make and v.model)

                    # Generate custom Order ID: MMDD + Make(3) + Model(1) + Seq
                    # Example: 21JEEG1 for Feb 1, Jeep Grand Cherokee, order #1
                    try:
                        order_date = inv.sale_date or datetime.now()
                        order_id = generate_order_id(v.make, v.model, order_date)
                        outputs["order_id"] = order_id
                        field_sources["order_id"] = {
                            "value": order_id,
                            "source": "GENERATED",
                            "confidence": 1.0,
                            "method": "order_id_generator",
                        }
                    except Exception:
                        # Don't fail extraction if order_id generation fails
                        outputs["order_id"] = None

                extraction_score = result.score

                # =================================================================
                # M3.P0.1: MERGE BLOCK + PATTERN EXTRACTION RESULTS
                # Block extraction takes precedence for high-confidence fields
                # =================================================================
                block_preferred_fields = [
                    "vehicle_vin",
                    "vehicle_lot",
                    "buyer_id",
                    "total_amount",
                    "reference_id",
                    "sale_date",
                ]

                for field_key, block_value in block_outputs.items():
                    if block_value is not None and str(block_value).strip():
                        # Block extraction takes precedence for preferred fields
                        if field_key in block_preferred_fields:
                            if outputs.get(field_key) != block_value:
                                outputs[field_key] = block_value
                                field_sources[field_key] = {
                                    "value": block_value,
                                    "source": "EXTRACTED",
                                    "confidence": 0.9,
                                    "method": "block_extractor",
                                }
                        # For other fields, use block value if pattern didn't find it
                        elif not outputs.get(field_key):
                            outputs[field_key] = block_value
                            field_sources[field_key] = {
                                "value": block_value,
                                "source": "EXTRACTED",
                                "confidence": 0.85,
                                "method": "block_extractor",
                            }

                # Update document's auction_type_id if detected source differs
                if result.source:
                    detected_source = result.source.value  # e.g., "COPART", "IAA", "MANHEIM"
                    if detected_source != auction_type.code:
                        # Find the matching auction type by code
                        detected_type = AuctionTypeRepository.get_by_code(detected_source)
                        if detected_type:
                            # Update document to use detected auction type
                            DocumentRepository.update(document_id, auction_type_id=detected_type.id)
                            # Also update the extraction run's auction_type_id
                            auction_type_id = detected_type.id
                            # Update the run as well
                            ExtractionRunRepository.update(run_id, auction_type_id=detected_type.id)

        # Calculate field metrics
        metrics["fields_extracted_count"] = len(outputs)
        metrics["fields_filled_count"] = sum(
            1 for v in outputs.values() if v is not None and v != ""
        )

        # Count required fields filled
        required_fields = ["vehicle_vin", "pickup_address", "pickup_city", "pickup_state"]
        metrics["required_fields_filled"] = sum(1 for f in required_fields if outputs.get(f))

        processing_time_ms = int((time.time() - start_time) * 1000)

        # =================================================================
        # PIPELINE INVARIANT CHECKS (M0.2)
        # Must pass for extraction to be considered valid for review
        # =================================================================
        invariant_errors = []

        # Invariant 1: Text extraction must succeed
        # raw_text_length > 0 OR (ocr_applied AND words_count > 0)
        if metrics["raw_text_length"] < 50:
            if not metrics.get("ocr_applied", False) or metrics["words_count"] < 10:
                invariant_errors.append(
                    {
                        "code": "INV_TEXT_EXTRACTION",
                        "message": "Text extraction failed - document may need OCR",
                        "details": f"raw_text_length={metrics['raw_text_length']}, words_count={metrics['words_count']}",
                    }
                )

        # Invariant 2: Classification must succeed
        # detected_source must be set with reasonable confidence
        if not metrics.get("detected_source"):
            invariant_errors.append(
                {
                    "code": "INV_CLASSIFICATION",
                    "message": "Document classification failed - unknown auction type",
                    "details": f"classification_score={metrics.get('classification_score', 0)}",
                }
            )
        elif metrics.get("classification_score", 0) < 0.1:
            invariant_errors.append(
                {
                    "code": "INV_CLASSIFICATION_LOW",
                    "message": "Document classification confidence too low",
                    "details": f"classification_score={metrics.get('classification_score', 0)}, detected={metrics.get('detected_source')}",
                }
            )

        # Invariant 3: At least 3 anchor fields must be extracted
        # Anchor fields: VIN/lot/stock (one of), pickup city/state, facility name/address
        anchor_count = 0

        # Check vehicle anchor (VIN, lot, or stock)
        if outputs.get("vehicle_vin") or outputs.get("vehicle_lot") or outputs.get("reference_id"):
            anchor_count += 1

        # Check location anchor (city and state)
        if outputs.get("pickup_city") and outputs.get("pickup_state"):
            anchor_count += 1

        # Check facility anchor (address or name)
        if outputs.get("pickup_address") or outputs.get("pickup_name"):
            anchor_count += 1

        metrics["anchor_fields_count"] = anchor_count

        if anchor_count < 3:
            invariant_errors.append(
                {
                    "code": "INV_ANCHOR_FIELDS",
                    "message": f"Only {anchor_count}/3 anchor fields extracted",
                    "details": "Need: vehicle identifier, city/state, and facility. Check debug endpoint for details.",
                }
            )

        # Store invariant check results in metrics
        metrics["invariants_passed"] = len(invariant_errors) == 0
        metrics["invariant_errors"] = [e["code"] for e in invariant_errors]

        # Determine status based on extraction quality and invariants
        if not outputs:
            run_status = "failed"
            errors_to_save = [{"error": "No fields extracted"}]
        elif invariant_errors:
            # Invariants failed - mark as failed with details
            run_status = "failed"
            errors_to_save = invariant_errors
        else:
            # All invariants pass - ready for review
            run_status = "needs_review"
            errors_to_save = None

        # Update run with results including metrics and field sources
        update_kwargs = {
            "status": run_status,
            "extraction_score": extraction_score,
            "outputs_json": outputs,
            "metrics_json": metrics,
            "field_sources_json": field_sources,
            "processing_time_ms": processing_time_ms,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if errors_to_save:
            update_kwargs["errors_json"] = errors_to_save

        ExtractionRunRepository.update(run_id, **update_kwargs)

        # =================================================================
        # M3.P0.1: STORE FIELD EVIDENCE
        # Store extraction evidence for transparency and debugging
        # =================================================================
        if evidence_list:
            try:
                evidence_count = _store_field_evidence(run_id, evidence_list, document_id)
                metrics["evidence_records_stored"] = evidence_count
            except Exception as e:
                import logging

                logging.getLogger(__name__).warning(f"Failed to store evidence: {e}")

        # Create review items from outputs
        # CRITICAL: Always create review items for ALL configured field mappings,
        # not just the extracted fields. This ensures consistent field display.
        if True:  # Always create review items, even if outputs is empty
            _create_review_items_for_all_fields(run_id, auction_type_id, outputs or {})

    except Exception as e:
        import traceback

        error_details = {
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
        # Update metrics with error info
        metrics["extraction_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")

        ExtractionRunRepository.update(
            run_id,
            status="failed",
            errors_json=[error_details],
            metrics_json=metrics,
            completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )

        # Create empty review items for failed extractions so user can manually enter data
        _create_empty_review_items(run_id, auction_type_id)


def _create_review_items_for_all_fields(run_id: int, auction_type_id: int, outputs: dict):
    """
    Create review items for ALL configured field mappings.

    This ensures consistent field display - all fields appear in Review page,
    using extracted values where available and empty for fields not extracted.

    Args:
        run_id: Extraction run ID
        auction_type_id: Auction type ID for field mappings
        outputs: Dict of extracted field values (may be incomplete)
    """
    from api.database import get_connection

    # Get ALL field mappings for this auction type (ordered for consistent display)
    with get_connection() as conn:
        mappings = conn.execute(
            "SELECT * FROM field_mappings WHERE auction_type_id = ? AND is_active = TRUE ORDER BY display_order",
            (auction_type_id,),
        ).fetchall()

    # Default field set if no mappings configured
    DEFAULT_FIELDS = [
        # Key fields for Central Dispatch
        ("auction_source", "auction_source", None, False),
        ("order_id", "order_id", None, False),
        ("reference_id", "reference_id", "externalId", False),
        # Vehicle
        ("vehicle_vin", "vehicle_vin", "vehicles[0].vin", True),
        ("vehicle_year", "vehicle_year", "vehicles[0].year", True),
        ("vehicle_make", "vehicle_make", "vehicles[0].make", True),
        ("vehicle_model", "vehicle_model", "vehicles[0].model", True),
        ("vehicle_color", "vehicle_color", "vehicles[0].color", False),
        ("vehicle_lot", "vehicle_lot", "vehicles[0].lotNumber", False),
        ("vehicle_mileage", "vehicle_mileage", None, False),
        ("vehicle_is_inoperable", "vehicle_is_inoperable", "vehicles[0].isInoperable", False),
        # Pickup location
        ("pickup_name", "pickup_name", "stops[0].locationName", False),
        ("pickup_address", "pickup_address", "stops[0].address", True),
        ("pickup_city", "pickup_city", "stops[0].city", True),
        ("pickup_state", "pickup_state", "stops[0].state", True),
        ("pickup_zip", "pickup_zip", "stops[0].postalCode", True),
        ("pickup_phone", "pickup_phone", "stops[0].phone", False),
        # Delivery location (usually filled from warehouse)
        ("delivery_name", "delivery_name", "stops[1].locationName", False),
        ("delivery_address", "delivery_address", "stops[1].address", False),
        ("delivery_city", "delivery_city", "stops[1].city", False),
        ("delivery_state", "delivery_state", "stops[1].state", False),
        ("delivery_zip", "delivery_zip", "stops[1].postalCode", False),
        ("delivery_phone", "delivery_phone", "stops[1].phone", False),
        # Buyer/Sale info
        ("buyer_id", "buyer_id", None, False),
        ("buyer_name", "buyer_name", None, False),
        ("sale_date", "sale_date", None, False),
        ("total_amount", "total_amount", None, False),
    ]

    # Build list of all fields to create
    review_items = []
    used_keys = set()

    if mappings:
        # Use configured mappings
        for m in mappings:
            source_key = m["source_key"]
            used_keys.add(source_key)

            # Get value from outputs if available
            value = outputs.get(source_key)

            review_items.append(
                {
                    "source_key": source_key,
                    "internal_key": m["internal_key"] or source_key,
                    "cd_key": m["cd_key"],
                    "predicted_value": str(value) if value is not None else None,
                    "is_match_ok": False,
                    "export_field": m["is_required"] or value is not None,
                    "confidence": 0.5 if value is not None else 0.0,
                }
            )
    else:
        # Use default fields
        for source_key, internal_key, cd_key, is_required in DEFAULT_FIELDS:
            used_keys.add(source_key)
            value = outputs.get(source_key)

            review_items.append(
                {
                    "source_key": source_key,
                    "internal_key": internal_key,
                    "cd_key": cd_key,
                    "predicted_value": str(value) if value is not None else None,
                    "is_match_ok": False,
                    "export_field": is_required or value is not None,
                    "confidence": 0.5 if value is not None else 0.0,
                }
            )

    # Also include any extracted fields that weren't in mappings
    # (in case extraction found additional fields)
    for key, value in outputs.items():
        if key not in used_keys and value is not None:
            review_items.append(
                {
                    "source_key": key,
                    "internal_key": key,
                    "cd_key": None,
                    "predicted_value": str(value) if value is not None else None,
                    "is_match_ok": False,
                    "export_field": True,
                    "confidence": 0.5,
                }
            )

    if review_items:
        ReviewItemRepository.create_batch(run_id, review_items)


def _create_empty_review_items(run_id: int, auction_type_id: int):
    """Create empty review items for manual data entry (failed extractions)."""
    _create_review_items_for_all_fields(run_id, auction_type_id, {})


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/run", response_model=ExtractionRunResponse, status_code=201)
async def run_extraction_endpoint(
    data: ExtractionRunRequest,
    background_tasks: BackgroundTasks,
    sync: bool = Query(True, description="Run synchronously (wait for result)"),
):
    """
    Run extraction on a document.

    Creates an extraction run and executes the extraction.
    By default runs synchronously. Set sync=false for background execution.
    """
    # Validate document
    doc = DocumentRepository.get_by_id(data.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get auction type
    auction_type = AuctionTypeRepository.get_by_id(doc.auction_type_id)
    if not auction_type:
        raise HTTPException(status_code=400, detail="Invalid auction type")

    # Check for active ML model
    extractor_kind = "rule"
    model_version_id = None

    if data.force_ml:
        active_model = ModelVersionRepository.get_active(doc.auction_type_id)
        if active_model:
            extractor_kind = "ml"
            model_version_id = active_model.id

    # Create run
    run_id = ExtractionRunRepository.create(
        document_id=data.document_id,
        auction_type_id=doc.auction_type_id,
        extractor_kind=extractor_kind,
        model_version_id=model_version_id,
    )

    if sync:
        # Run synchronously
        run_extraction(
            run_id, data.document_id, doc.auction_type_id, extractor_kind, model_version_id
        )
    else:
        # Run in background
        background_tasks.add_task(
            run_extraction,
            run_id,
            data.document_id,
            doc.auction_type_id,
            extractor_kind,
            model_version_id,
        )

    # Get result
    run = ExtractionRunRepository.get_by_id(run_id)

    return ExtractionRunResponse(
        id=run.id,
        uuid=run.uuid,
        document_id=run.document_id,
        document_filename=doc.filename,
        auction_type_id=run.auction_type_id,
        auction_type_code=auction_type.code,
        extractor_kind=run.extractor_kind,
        model_version_id=run.model_version_id,
        status=run.status,
        extraction_score=run.extraction_score,
        outputs=run.outputs_json,
        errors=run.errors_json,
        processing_time_ms=run.processing_time_ms,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get("/", response_model=ExtractionRunListResponse)
async def list_extraction_runs(
    document_id: Optional[int] = Query(None),
    auction_type_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List extraction runs with optional filtering."""
    from api.database import get_connection

    sql = "SELECT * FROM extraction_runs WHERE 1=1"
    params = []

    if document_id:
        sql += " AND document_id = ?"
        params.append(document_id)
    if auction_type_id:
        sql += " AND auction_type_id = ?"
        params.append(auction_type_id)
    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM extraction_runs WHERE 1=1").fetchone()[0]

    items = []
    for row in rows:
        data = dict(row)
        if data.get("outputs_json"):
            import json

            data["outputs_json"] = json.loads(data["outputs_json"])
        if data.get("errors_json"):
            import json

            data["errors_json"] = json.loads(data["errors_json"])

        # Get related entities
        doc = DocumentRepository.get_by_id(data["document_id"])
        at = AuctionTypeRepository.get_by_id(data["auction_type_id"])

        items.append(
            ExtractionRunResponse(
                id=data["id"],
                uuid=data["uuid"],
                document_id=data["document_id"],
                document_filename=doc.filename if doc else None,
                auction_type_id=data["auction_type_id"],
                auction_type_code=at.code if at else None,
                extractor_kind=data["extractor_kind"],
                model_version_id=data.get("model_version_id"),
                status=data["status"],
                extraction_score=data.get("extraction_score"),
                outputs=data.get("outputs_json"),
                errors=data.get("errors_json"),
                processing_time_ms=data.get("processing_time_ms"),
                created_at=data.get("created_at"),
                completed_at=data.get("completed_at"),
            )
        )

    return ExtractionRunListResponse(items=items, total=total)


class ExtractionStatsResponse(BaseModel):
    """Response model for extraction run statistics."""

    total: int
    last_24h: int
    by_status: dict
    by_auction_type: dict
    needs_review_count: int


@router.get("/stats", response_model=ExtractionStatsResponse)
async def get_extraction_stats():
    """
    Get extraction run statistics.

    Returns aggregate counts by status and auction type.
    """
    from datetime import datetime, timedelta

    from api.database import get_connection

    with get_connection() as conn:
        # Total count
        total = conn.execute("SELECT COUNT(*) FROM extraction_runs").fetchone()[0]

        # Last 24h
        yesterday = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        last_24h = conn.execute(
            "SELECT COUNT(*) FROM extraction_runs WHERE created_at >= ?", (yesterday,)
        ).fetchone()[0]

        # By status
        status_rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM extraction_runs GROUP BY status"
        ).fetchall()
        by_status = {row["status"]: row["cnt"] for row in status_rows}

        # By auction type
        auction_rows = conn.execute("""
            SELECT at.code, COUNT(*) as cnt
            FROM extraction_runs er
            JOIN auction_types at ON er.auction_type_id = at.id
            GROUP BY at.code
        """).fetchall()
        by_auction_type = {row["code"]: row["cnt"] for row in auction_rows}

        # Needs review count
        needs_review_count = by_status.get("needs_review", 0)

    return ExtractionStatsResponse(
        total=total,
        last_24h=last_24h,
        by_status=by_status,
        by_auction_type=by_auction_type,
        needs_review_count=needs_review_count,
    )


@router.get("/needs-review", response_model=ExtractionRunListResponse)
async def list_runs_needing_review(
    limit: int = Query(50, ge=1, le=500),
):
    """List extraction runs that need review."""
    runs = ExtractionRunRepository.list_needs_review(limit=limit)

    items = []
    for run in runs:
        doc = DocumentRepository.get_by_id(run.document_id)
        at = AuctionTypeRepository.get_by_id(run.auction_type_id)

        items.append(
            ExtractionRunResponse(
                id=run.id,
                uuid=run.uuid,
                document_id=run.document_id,
                document_filename=doc.filename if doc else None,
                auction_type_id=run.auction_type_id,
                auction_type_code=at.code if at else None,
                extractor_kind=run.extractor_kind,
                model_version_id=run.model_version_id,
                status=run.status,
                extraction_score=run.extraction_score,
                outputs=run.outputs_json,
                errors=run.errors_json,
                processing_time_ms=run.processing_time_ms,
                created_at=run.created_at,
                completed_at=run.completed_at,
            )
        )

    return ExtractionRunListResponse(items=items, total=len(items))


@router.get("/{id}", response_model=ExtractionDetailResponse)
async def get_extraction_run(id: int):
    """Get detailed extraction run with field-level outputs."""
    run = ExtractionRunRepository.get_by_id(id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    doc = DocumentRepository.get_by_id(run.document_id)
    at = AuctionTypeRepository.get_by_id(run.auction_type_id)

    # Get review items (extracted fields)
    review_items = ReviewItemRepository.get_by_run(run.id)
    fields = [
        ExtractionFieldOutput(
            source_key=item.source_key,
            internal_key=item.internal_key,
            cd_key=item.cd_key,
            value=item.predicted_value,
            confidence=item.confidence,
        )
        for item in review_items
    ]

    run_response = ExtractionRunResponse(
        id=run.id,
        uuid=run.uuid,
        document_id=run.document_id,
        document_filename=doc.filename if doc else None,
        auction_type_id=run.auction_type_id,
        auction_type_code=at.code if at else None,
        extractor_kind=run.extractor_kind,
        model_version_id=run.model_version_id,
        status=run.status,
        extraction_score=run.extraction_score,
        outputs=run.outputs_json,
        errors=run.errors_json,
        processing_time_ms=run.processing_time_ms,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )

    return ExtractionDetailResponse(
        run=run_response,
        fields=fields,
        raw_text_preview=doc.raw_text[:1000] if doc and doc.raw_text else None,
    )


class ExtractionUpdateRequest(BaseModel):
    """Request model for updating extraction run."""

    outputs_json: Optional[dict] = Field(None, description="Updated extracted fields")
    status: Optional[str] = Field(None, description="New status")
    warehouse_id: Optional[int] = Field(None, description="Selected warehouse ID")


@router.put("/{id}", response_model=ExtractionRunResponse)
async def update_extraction_run(id: int, data: ExtractionUpdateRequest):
    """
    Update extraction run with corrected field values or status change.

    Used by the Review & Listing page to save field edits before export.
    """
    import json

    run = ExtractionRunRepository.get_by_id(id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    # Can't update exported runs
    if run.status == "exported" and data.status != "exported":
        raise HTTPException(status_code=400, detail="Cannot modify exported extraction")

    # Build updates
    updates = {}

    if data.outputs_json is not None:
        # Merge with existing outputs
        existing_outputs = run.outputs_json or {}
        if isinstance(existing_outputs, str):
            existing_outputs = json.loads(existing_outputs)

        # Merge new outputs
        merged = {**existing_outputs, **data.outputs_json}

        # Add warehouse_id if provided
        if data.warehouse_id is not None:
            merged["warehouse_id"] = data.warehouse_id

        updates["outputs_json"] = json.dumps(merged)

    if data.status is not None:
        updates["status"] = data.status

    if updates:
        ExtractionRunRepository.update(id, **updates)

    # Reload and return
    run = ExtractionRunRepository.get_by_id(id)
    doc = DocumentRepository.get_by_id(run.document_id)
    at = AuctionTypeRepository.get_by_id(run.auction_type_id)

    return ExtractionRunResponse(
        id=run.id,
        uuid=run.uuid,
        document_id=run.document_id,
        document_filename=doc.filename if doc else None,
        auction_type_id=run.auction_type_id,
        auction_type_code=at.code if at else None,
        extractor_kind=run.extractor_kind,
        model_version_id=run.model_version_id,
        status=run.status,
        extraction_score=run.extraction_score,
        outputs=run.outputs_json,
        errors=run.errors_json,
        processing_time_ms=run.processing_time_ms,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.get("/{id}/debug", response_model=ExtractionDebugResponse)
async def get_extraction_debug(id: int):
    """
    Get detailed debug information for an extraction run.

    Returns comprehensive diagnostics including:
    - Extraction metrics (text length, word count, pages)
    - Classification scores from all extractors
    - Field sources (where each value came from)
    - OCR status and recommendations
    - Raw text preview

    This endpoint is designed for troubleshooting extraction issues
    and understanding why fields may be empty or incorrect.
    """
    import os

    run = ExtractionRunRepository.get_by_id(id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    doc = DocumentRepository.get_by_id(run.document_id)
    at = AuctionTypeRepository.get_by_id(run.auction_type_id)

    # Initialize response
    response = ExtractionDebugResponse(
        run_id=run.id,
        document_id=run.document_id,
        document_filename=doc.filename if doc else None,
        auction_type=at.code if at else None,
        status=run.status,
        extraction_score=run.extraction_score,
        processing_time_ms=run.processing_time_ms,
        errors=run.errors_json,
    )

    # Get raw text from document
    raw_text = doc.raw_text or "" if doc else ""
    response.raw_text_length = len(raw_text)
    response.raw_text_preview = raw_text[:2000] if raw_text else None

    # Load stored metrics if available
    if run.metrics_json:
        response.metrics = ExtractionMetricsResponse(**run.metrics_json)
    else:
        # Calculate metrics on the fly if not stored
        words = raw_text.split() if raw_text else []
        response.metrics = ExtractionMetricsResponse(
            raw_text_length=len(raw_text),
            words_count=len(words),
            text_mode="native",  # Assume native if not stored
            needs_ocr=len(raw_text) < 100,
        )

    # Get field sources from stored data or compute from outputs
    field_sources = []
    if run.field_sources_json:
        for key, info in run.field_sources_json.items():
            field_sources.append(
                FieldSourceInfo(
                    field_key=key,
                    value=str(info.get("value")) if info.get("value") is not None else None,
                    source=info.get("source", "EXTRACTED"),
                    confidence=info.get("confidence"),
                    extractor_method=info.get("method"),
                )
            )
    elif run.outputs_json:
        # Generate field sources from outputs
        for key, value in run.outputs_json.items():
            field_sources.append(
                FieldSourceInfo(
                    field_key=key,
                    value=str(value) if value is not None else None,
                    source="EXTRACTED" if value is not None else "DEFAULT",
                    confidence=0.5 if value is not None else 0.0,
                )
            )
    response.field_sources = field_sources

    # Get classification scores from all extractors
    all_scores = []
    if doc and doc.file_path and os.path.exists(doc.file_path):
        try:
            from extractors import ExtractorManager

            manager = ExtractorManager()

            for extractor in manager.extractors:
                score, patterns = extractor.score(raw_text)
                all_scores.append(
                    {
                        "source": extractor.source.value,
                        "score": score,
                        "matched_patterns": patterns[:5] if patterns else [],
                        "is_selected": (at and extractor.source.value == at.code),
                    }
                )
        except Exception as e:
            all_scores.append({"error": str(e)})
    response.all_scores = all_scores

    # Generate recommendations
    recommendations = []

    # Check text length
    if len(raw_text) < 100:
        recommendations.append("Document has very little text. OCR may be required.")

    # Check for missing required fields
    outputs = run.outputs_json or {}
    required_fields = ["vehicle_vin", "pickup_address", "pickup_city", "pickup_state"]
    missing_required = [f for f in required_fields if not outputs.get(f)]
    if missing_required:
        recommendations.append(f"Missing required fields: {', '.join(missing_required)}")

    # Check extraction score
    if run.extraction_score and run.extraction_score < 0.3:
        recommendations.append(
            "Low extraction score. Document format may not match expected template."
        )

    # Check if extractor was selected
    if not at:
        recommendations.append("No auction type assigned. Classification may have failed.")

    # Check for errors
    if run.errors_json:
        recommendations.append(f"Extraction errors occurred: {len(run.errors_json)} error(s)")

    # Check vehicle info
    if not outputs.get("vehicle_vin"):
        recommendations.append("VIN not extracted. Check if VIN is present in document.")
    if not outputs.get("vehicle_year") or not outputs.get("vehicle_make"):
        recommendations.append("Vehicle year/make/model incomplete.")

    # Check pickup address
    if not outputs.get("pickup_address"):
        recommendations.append("Pickup address not extracted. May require manual entry.")

    response.recommendations = recommendations

    return response
