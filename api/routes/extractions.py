"""
Extractions API Routes

Run and manage extraction runs on documents.
"""

import time
from datetime import datetime, timezone
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
        # HAIKU EXTRACTION (PRIMARY — Claude Haiku LLM)
        # Uses Claude Haiku API for accurate field extraction.
        # Falls back to zone_extractor if Claude API is unavailable.
        # =================================================================
        import logging

        logger = logging.getLogger(__name__)
        haiku_outputs = {}
        extraction_method = "none"

        if doc.file_path:
            # --- PRIMARY: HaikuExtractor ---
            try:
                from services.haiku_extractor import get_haiku_extractor, normalize_haiku_result

                haiku = get_haiku_extractor()

                if not haiku.api_key:
                    raise RuntimeError("ANTHROPIC_API_KEY not configured")

                logger.info(f"HAIKU EXTRACTION: Running Claude Haiku for doc {document_id}")
                haiku_result = haiku.extract(doc.file_path)

                if haiku_result.error:
                    raise RuntimeError(f"Haiku extraction error: {haiku_result.error}")

                haiku_outputs, haiku_sources = normalize_haiku_result(haiku_result)
                field_sources.update(haiku_sources)

                extraction_method = "haiku"
                metrics["extraction_method"] = "haiku"
                metrics["haiku_extraction"] = {
                    "model": haiku.MODEL,
                    "fields_count": len(haiku_outputs),
                    "confidence": haiku_result.confidence,
                    "cost_usd": haiku_result.cost_usd,
                    "tokens_input": haiku_result.tokens_used.input_tokens,
                    "tokens_output": haiku_result.tokens_used.output_tokens,
                    "cache_read_tokens": haiku_result.tokens_used.cache_read_tokens,
                    "cache_efficiency": haiku_result.tokens_used.cache_efficiency,
                }

                logger.info(
                    f"Haiku extraction: {len(haiku_outputs)} fields, "
                    f"confidence={haiku_result.confidence:.2f}, "
                    f"cost=${haiku_result.cost_usd:.4f}"
                )

            except Exception as haiku_err:
                logger.warning(f"Haiku extraction failed, falling back to zone: {haiku_err}")
                metrics["haiku_extraction_error"] = str(haiku_err)

                # --- FALLBACK: Zone extractor ---
                try:
                    from extractors.zone_extractor import get_zone_extractor

                    zone_extractor = get_zone_extractor()
                    logger.info(f"ZONE FALLBACK: Loading template from DB for {auction_type.code}")
                    zone_result = zone_extractor.extract_with_logging(doc.file_path, auction_type.code)

                    haiku_outputs = zone_result.fields
                    extraction_method = "zone_fallback"
                    metrics["extraction_method"] = "zone_fallback"
                    metrics["zone_extraction"] = {
                        "template_id": zone_result.template_id,
                        "confidence": zone_result.confidence,
                        "fields_count": len(zone_result.fields),
                        "warnings": zone_result.warnings,
                        "source": "database" if zone_result.template_id != "none" else "none",
                    }

                    for key, value in haiku_outputs.items():
                        if value is not None:
                            field_sources[key] = {
                                "value": value,
                                "source": "ZONE_EXTRACTED",
                                "confidence": zone_result.confidence,
                                "method": f"zone_extractor:{zone_result.template_id}",
                            }

                    logger.info(
                        f"Zone fallback: {len(haiku_outputs)} fields, "
                        f"confidence={zone_result.confidence}"
                    )

                except Exception as zone_err:
                    logger.error(f"Zone fallback also failed: {zone_err}")
                    metrics["zone_extraction_error"] = str(zone_err)
                    metrics["extraction_method"] = "all_failed"

        # Rename for downstream compatibility (was zone_outputs)
        zone_outputs = haiku_outputs

        # =================================================================
        # BLOCK EXTRACTION (FALLBACK - only for fields not found by haiku/zone)
        # Run layout-aware extraction as fallback
        # =================================================================
        block_outputs = {}

        # Only run block extraction if zone extraction didn't find key fields
        zone_has_required = (
            zone_outputs.get("vehicle_vin") and
            zone_outputs.get("pickup_city")
        )

        if doc.file_path and not zone_has_required:
            try:
                import logging
                logger = logging.getLogger(__name__)
                logger.info("Block extraction FALLBACK: Zone missing required fields")

                block_outputs, evidence_list = _run_block_extraction(
                    document_id=document_id,
                    run_id=run_id,
                    file_path=doc.file_path,
                    raw_text=raw_text,
                    metrics=metrics,
                )
                # Track block-extracted fields (lower priority than zone)
                for key, value in block_outputs.items():
                    if value is not None and key not in field_sources:
                        field_sources[key] = {
                            "value": value,
                            "source": "BLOCK_EXTRACTED",
                            "confidence": 0.75,
                            "method": "block_extractor_fallback",
                        }
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Block extraction error: {e}")
                metrics["block_extraction_error"] = str(e)
        else:
            metrics["block_extraction_skipped"] = "zone_had_required_fields"

        # =================================================================
        # PATTERN EXTRACTION (LAST RESORT - only if zone/block failed)
        # Uses regex patterns on raw text
        # =================================================================
        from extractors import ExtractorManager
        import logging

        pattern_logger = logging.getLogger(__name__)

        # Only run pattern extraction if we're missing critical fields
        zone_and_block_fields = {**zone_outputs, **block_outputs}
        missing_critical = not (
            zone_and_block_fields.get("vehicle_vin") and
            zone_and_block_fields.get("pickup_city")
        )

        if missing_critical:
            pattern_logger.info("Pattern extraction FALLBACK: Missing critical fields")

        manager = ExtractorManager()

        # Classify and extract - always for classification, but only fill missing fields
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

        # =================================================================
        # FINAL MERGE: HAIKU/ZONE OVERRIDE (HIGHEST PRIORITY)
        #
        # Priority order (highest to lowest):
        # 1. HAIKU_EXTRACTED - Claude Haiku LLM (primary)
        #    or ZONE_EXTRACTED - Zone templates (fallback)
        # 2. BLOCK_EXTRACTED - Fallback layout-aware extraction
        # 3. PATTERN_EXTRACTED - Last resort regex patterns
        # =================================================================
        if zone_outputs:
            import logging
            merge_logger = logging.getLogger(__name__)
            merge_logger.info(f"MERGE: Zone outputs override - {len(zone_outputs)} fields")

            for field_key, zone_value in zone_outputs.items():
                if zone_value is not None and str(zone_value).strip():
                    old_value = outputs.get(field_key)

                    # Zone extraction ALWAYS overrides pattern/block for ALL fields
                    outputs[field_key] = zone_value

                    # Update field_sources if zone value is different from pattern value
                    if old_value != zone_value and field_key in field_sources:
                        merge_logger.info(f"  {field_key}: '{old_value}' -> '{zone_value}' (zone override)")

                    # Ensure field_sources reflects zone extraction
                    if field_key not in field_sources or field_sources[field_key].get("source") not in ("ZONE_EXTRACTED", "TRAINING_RULE"):
                        field_sources[field_key] = {
                            "value": zone_value,
                            "source": "ZONE_EXTRACTED",
                            "confidence": metrics.get("zone_extraction", {}).get("confidence", 0.8),
                            "method": f"zone_extractor:{metrics.get('zone_extraction', {}).get('template_id', 'unknown')}",
                        }

        # Store extraction method in outputs for UI display
        outputs["extraction_method"] = extraction_method

        # =================================================================
        # POST-EXTRACTION: Update auction type from Haiku's auction_source
        # Haiku reads actual document content and is the AUTHORITY on type.
        # =================================================================
        haiku_auction = outputs.get("auction_source", "").upper()
        if haiku_auction in ("COPART", "IAA", "MANHEIM"):
            if haiku_auction != auction_type.code:
                detected_at = AuctionTypeRepository.get_by_code(haiku_auction)
                if detected_at:
                    DocumentRepository.update(document_id, auction_type_id=detected_at.id)
                    ExtractionRunRepository.update(run_id, auction_type_id=detected_at.id)
                    auction_type_id = detected_at.id
                    auction_type = detected_at

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

        # Invariant 2: Classification should succeed
        # detected_source must be set with reasonable confidence
        # Note: downgraded to warning when fields were extracted (e.g. IAA listing pages
        # contain useful vehicle data but don't match invoice patterns)
        if not metrics.get("detected_source"):
            classification_issue = {
                "code": "INV_CLASSIFICATION",
                "message": "Document classification failed - unknown auction type",
                "details": f"classification_score={metrics.get('classification_score', 0)}",
            }
            # If outputs have at least some fields, treat as warning not error
            if outputs and len(outputs) >= 3:
                classification_issue["severity"] = "warning"
                # Will be added to warnings below after anchor check
                _classification_warning = classification_issue
            else:
                invariant_errors.append(classification_issue)
                _classification_warning = None
        elif metrics.get("classification_score", 0) < 0.1:
            invariant_errors.append(
                {
                    "code": "INV_CLASSIFICATION_LOW",
                    "message": "Document classification confidence too low",
                    "details": f"classification_score={metrics.get('classification_score', 0)}, detected={metrics.get('detected_source')}",
                }
            )
            _classification_warning = None
        else:
            _classification_warning = None

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

        # Track which anchors passed/failed for debugging
        metrics["anchors_breakdown"] = {
            "vehicle_id": bool(
                outputs.get("vehicle_vin")
                or outputs.get("vehicle_lot")
                or outputs.get("reference_id")
            ),
            "city_state": bool(outputs.get("pickup_city") and outputs.get("pickup_state")),
            "address_or_name": bool(outputs.get("pickup_address") or outputs.get("pickup_name")),
        }

        # P0.2: Relaxed anchor validation
        # - 3/3 anchors: fully ready for review
        # - 2/3 anchors: needs_review with warning (not blocking)
        # - < 2 anchors: failed (not enough data)
        invariant_warnings = []

        # Add classification warning if classification failed but fields were extracted
        if _classification_warning is not None:
            invariant_warnings.append(_classification_warning)

        if anchor_count < 2:
            # Critical failure - not enough data to proceed
            invariant_errors.append(
                {
                    "code": "INV_ANCHOR_FIELDS",
                    "message": f"Only {anchor_count}/3 anchor fields extracted",
                    "details": "Need at least: vehicle identifier AND (city/state OR address/name). Check debug endpoint for details.",
                    "severity": "error",
                }
            )
        elif anchor_count < 3:
            # Warning - can proceed but some data missing
            invariant_warnings.append(
                {
                    "code": "WARN_ANCHOR_FIELDS",
                    "message": f"Partial extraction: {anchor_count}/3 anchor fields",
                    "details": "Some fields may need manual entry. Check: "
                    + ", ".join(k for k, v in metrics["anchors_breakdown"].items() if not v),
                    "severity": "warning",
                }
            )

        # Store invariant check results in metrics
        metrics["invariants_passed"] = len(invariant_errors) == 0
        metrics["invariant_errors"] = [e["code"] for e in invariant_errors]
        metrics["invariant_warnings"] = [w["code"] for w in invariant_warnings]

        # Determine status based on extraction quality and invariants
        if not outputs:
            run_status = "failed"
            errors_to_save = [{"error": "No fields extracted"}]
        elif invariant_errors:
            # Critical invariants failed - mark as failed
            run_status = "failed"
            errors_to_save = invariant_errors
        else:
            # Ready for review (may have warnings but not blocking errors)
            run_status = "needs_review"
            # Store warnings in errors_json for visibility but don't block
            errors_to_save = invariant_warnings if invariant_warnings else None

        # =================================================================
        # AUTO-SET pickup_location_type for auction sources
        # COPART/IAA/MANHEIM → pickup_location_type = AUCTION
        # =================================================================
        auction_source = outputs.get("auction_source", "").upper() or auction_type.code
        if auction_source in ("COPART", "IAA", "MANHEIM"):
            if not outputs.get("pickup_location_type"):
                outputs["pickup_location_type"] = "AUCTION"
                field_sources["pickup_location_type"] = {
                    "value": "AUCTION",
                    "source": "AUCTION_CONST",
                    "confidence": 1.0,
                    "method": "auto_set_for_auction_source",
                }

        # =================================================================
        # MANHEIM: Release date → available_date propagation
        # If Manheim doc has a release date, use it as available_date.
        # If no release document, flag for manual review.
        # =================================================================
        if auction_source == "MANHEIM" or outputs.get("auction_type", "").upper() == "MANHEIM":
            release_date = outputs.get("manheim_release_date")
            if release_date and release_date not in ("AVAILABLE_NOW", "NO_RELEASE_DOCUMENT"):
                # ISO date like "2026-02-03" → set as available_date
                if not outputs.get("available_date"):
                    outputs["available_date"] = release_date
                    field_sources["available_date"] = {
                        "value": release_date,
                        "source": "EXTRACTED",
                        "confidence": 0.95,
                        "method": "manheim_release_date_propagation",
                    }
            elif release_date == "AVAILABLE_NOW":
                # Vehicle available immediately — use today
                if not outputs.get("available_date"):
                    import time as _time
                    outputs["available_date"] = _time.strftime("%Y-%m-%d")
                    field_sources["available_date"] = {
                        "value": outputs["available_date"],
                        "source": "EXTRACTED",
                        "confidence": 0.9,
                        "method": "manheim_available_now",
                    }
            elif release_date == "NO_RELEASE_DOCUMENT":
                # No release document — add warning for manual review
                if not outputs.get("available_date"):
                    outputs["manheim_release_warning"] = "No release document found — set available date manually"

            # Manheim offsite: override pickup with offsite address if present
            if outputs.get("manheim_offsite") is True:
                offsite_addr = outputs.get("offsite_pickup_address")
                offsite_city = outputs.get("offsite_pickup_city")
                offsite_state = outputs.get("offsite_pickup_state")
                offsite_zip = outputs.get("offsite_pickup_zip")
                if offsite_addr and offsite_city:
                    outputs["pickup_address"] = offsite_addr
                    outputs["pickup_city"] = offsite_city
                    if offsite_state:
                        outputs["pickup_state"] = offsite_state
                    if offsite_zip:
                        outputs["pickup_zip"] = offsite_zip
                    outputs["pickup_location_type"] = "BUSINESS"
                    field_sources["pickup_address"] = {
                        "value": offsite_addr,
                        "source": "EXTRACTED",
                        "confidence": 0.9,
                        "method": "manheim_offsite_override",
                    }

        # =================================================================
        # INHERIT OPERATOR DATA FROM PREVIOUS RUNS
        # Carry over gate_pass, warehouse_id, and other operator-set fields
        # from the most recent previous run for the same document.
        # These are set by the email worker or operator — not by extraction.
        # =================================================================
        _inherit_fields = [
            "gate_pass", "warehouse_id",
            "delivery_name", "delivery_address", "delivery_city",
            "delivery_state", "delivery_zip",
        ]
        missing_inherit = [f for f in _inherit_fields if not outputs.get(f)]
        if missing_inherit:
            try:
                import json
                from api.database import get_connection
                with get_connection() as conn:
                    prev = conn.execute(
                        "SELECT outputs_json FROM extraction_runs "
                        "WHERE document_id = ? AND id != ? AND outputs_json IS NOT NULL "
                        "ORDER BY id DESC LIMIT 1",
                        (document_id, run_id),
                    ).fetchone()
                if prev and prev[0]:
                    prev_outputs = json.loads(prev[0])
                    for field in missing_inherit:
                        if prev_outputs.get(field) and not outputs.get(field):
                            outputs[field] = prev_outputs[field]
            except Exception as e:
                logger.debug("Gate pass / operator field inheritance failed: %s", e)

        # Also try email_log as a gate_pass source
        if not outputs.get("gate_pass"):
            try:
                import json
                from api.database import get_connection
                with get_connection() as conn:
                    email_gp = conn.execute(
                        "SELECT gate_pass FROM email_log "
                        "WHERE extraction_run_ids LIKE ? AND gate_pass IS NOT NULL LIMIT 1",
                        (f"%{run_id}%",),
                    ).fetchone()
                    if not email_gp:
                        # Try matching by document's email metadata
                        doc_email = conn.execute(
                            "SELECT email_metadata_json FROM documents WHERE id = ?",
                            (document_id,),
                        ).fetchone()
                        if doc_email and doc_email[0]:
                            meta = json.loads(doc_email[0])
                            msg_id = meta.get("message_id")
                            if msg_id:
                                email_gp = conn.execute(
                                    "SELECT gate_pass FROM email_log "
                                    "WHERE message_id = ? AND gate_pass IS NOT NULL LIMIT 1",
                                    (msg_id,),
                                ).fetchone()
                    if email_gp and email_gp[0]:
                        outputs["gate_pass"] = email_gp[0]
            except Exception as e:
                logger.debug("Email log gate_pass lookup failed: %s", e)

        # =================================================================
        # AUTO-GENERATE LOAD ID
        # Generate unique load_id from make+model if extraction succeeded
        # =================================================================
        if not outputs.get("load_id"):
            make = outputs.get("vehicle_make")
            model = outputs.get("vehicle_model")
            if make and model:
                try:
                    from api.routes.listings import create_load_id
                    result = create_load_id(make, model)
                    if result:
                        outputs["load_id"] = result[0]
                except Exception:
                    pass  # Don't fail extraction if load_id generation fails

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


def _create_review_items_for_all_fields(
    run_id: int, auction_type_id: int, outputs: dict, mode: str = "training"
):
    """
    Create review items for ALL configured field mappings.

    This ensures consistent field display - all fields appear in Review page,
    using extracted values where available and empty for fields not extracted.

    Uses the centralized ListingFieldRegistry for field definitions, ensuring
    consistency with CD API requirements and field taxonomy.

    Args:
        run_id: Extraction run ID
        auction_type_id: Auction type ID for field mappings
        outputs: Dict of extracted field values (may be incomplete)
        mode: Pipeline mode - "training", "review", or "export"

    Pipeline Modes (Option C implementation):
        - training: Show only extracted/user_input fields, skip export_only fields
        - review: Show all fields including warehouse-sourced delivery fields
        - export: Full CD API field set with strict validation
    """
    from api.database import get_connection
    from api.listing_fields import FieldCategory, get_registry

    # Get centralized field registry
    registry = get_registry()

    # Get custom field mappings for this auction type (if configured)
    with get_connection() as conn:
        mappings = conn.execute(
            "SELECT * FROM field_mappings WHERE auction_type_id = ? AND is_active = TRUE ORDER BY display_order",
            (auction_type_id,),
        ).fetchall()

    # Build list of all fields to create
    review_items = []
    used_keys = set()

    if mappings:
        # Use configured mappings (custom per auction type)
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
        # Use centralized field registry (single source of truth)
        # Filter fields based on mode
        fields = registry.get_fields_for_mode(mode)

        for field in fields:
            source_key = field.key
            used_keys.add(source_key)
            value = outputs.get(source_key)

            # Determine if this field should be exported to CD API
            export_field = field.category != FieldCategory.INTERNAL
            if value is not None:
                export_field = True  # Always export if we have a value

            review_items.append(
                {
                    "source_key": source_key,
                    "internal_key": source_key,
                    "cd_key": field.cd_api_key,
                    "predicted_value": str(value) if value is not None else None,
                    "is_match_ok": False,
                    "export_field": export_field,
                    "confidence": 0.5 if value is not None else 0.0,
                    # Note: Field metadata (category, source_type, required, export_only)
                    # comes from ListingFieldRegistry at query time, not stored here.
                }
            )

    # Also include any extracted fields that weren't in mappings/registry
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


def _create_empty_review_items(run_id: int, auction_type_id: int, mode: str = "training"):
    """Create empty review items for manual data entry (failed extractions)."""
    _create_review_items_for_all_fields(run_id, auction_type_id, {}, mode=mode)


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
    is_test: Optional[bool] = Query(None, description="Filter by test/training documents"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List extraction runs with optional filtering.

    Parameters:
    - is_test: If True, returns only training/test document runs.
               If False, returns only production document runs.
               If None, returns all.
    """
    from api.database import get_connection

    # Base query with optional join to documents for is_test filter
    if is_test is not None:
        sql = """
            SELECT er.* FROM extraction_runs er
            JOIN documents d ON er.document_id = d.id
            WHERE 1=1
        """
        if is_test:
            sql += " AND (d.is_test = 1 OR d.source = 'test_lab')"
        else:
            sql += " AND (d.is_test = 0 OR d.is_test IS NULL) AND (d.source != 'test_lab' OR d.source IS NULL)"
    else:
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
        yesterday = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
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
    import logging

    logger = logging.getLogger(__name__)

    try:
        run = ExtractionRunRepository.get_by_id(id)
        if not run:
            raise HTTPException(status_code=404, detail="Extraction run not found")

        doc = DocumentRepository.get_by_id(run.document_id)
        at = AuctionTypeRepository.get_by_id(run.auction_type_id)

        # Get review items (extracted fields) with safe type conversion
        review_items = ReviewItemRepository.get_by_run(run.id)
        fields = []
        for item in review_items:
            try:
                # Ensure predicted_value is a string
                value = item.predicted_value
                if value is not None and not isinstance(value, str):
                    value = str(value)

                # Ensure confidence is a float or None
                confidence = item.confidence
                if confidence is not None:
                    try:
                        confidence = float(confidence)
                    except (TypeError, ValueError):
                        confidence = None

                fields.append(
                    ExtractionFieldOutput(
                        source_key=item.source_key or "",
                        internal_key=item.internal_key,
                        cd_key=item.cd_key,
                        value=value,
                        confidence=confidence,
                    )
                )
            except Exception as field_err:
                logger.warning(f"Skipping field {item.source_key}: {field_err}")
                continue

        # Ensure outputs_json is a dict
        outputs = run.outputs_json
        if outputs is None:
            outputs = {}
        elif isinstance(outputs, str):
            import json

            try:
                outputs = json.loads(outputs)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse outputs_json for run {id}")
                outputs = {}

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
            outputs=outputs,
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
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching extraction {id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


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
    When warehouse_id is provided, automatically populates delivery fields.
    """
    import json

    from api.database import get_connection

    run = ExtractionRunRepository.get_by_id(id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    # Can't update exported runs
    if run.status == "exported" and data.status != "exported":
        raise HTTPException(status_code=400, detail="Cannot modify exported extraction")

    # Build updates
    updates = {}

    # Get existing outputs
    existing_outputs = run.outputs_json or {}
    if isinstance(existing_outputs, str):
        existing_outputs = json.loads(existing_outputs)

    # Start with existing, merge new outputs if provided
    merged = {**existing_outputs}
    if data.outputs_json is not None:
        merged = {**merged, **data.outputs_json}

    # Handle warehouse_id - populate delivery fields from warehouse
    if data.warehouse_id is not None:
        merged["warehouse_id"] = data.warehouse_id

        # Fetch warehouse from database and populate delivery fields
        with get_connection() as conn:
            wh_row = conn.execute(
                "SELECT * FROM warehouses WHERE id = ?", (data.warehouse_id,)
            ).fetchone()

        if wh_row:
            wh = dict(wh_row)
            merged["delivery_name"] = wh.get("name")
            merged["delivery_address"] = wh.get("address")
            merged["delivery_city"] = wh.get("city")
            merged["delivery_state"] = wh.get("state")
            merged["delivery_zip"] = wh.get("zip_code")
            merged["delivery_location_type"] = wh.get("location_type") or "CROSS_DOCK"
            if wh.get("buyer_reference"):
                merged["delivery_buyer_number"] = wh.get("buyer_reference")

    # Only update if something changed
    if data.outputs_json is not None or data.warehouse_id is not None:
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


class PipelineDiagnosticResponse(BaseModel):
    """Comprehensive pipeline diagnostic response."""

    # Basic info
    extraction_id: int
    document_id: Optional[int] = None
    document_filename: Optional[str] = None
    auction_type: Optional[str] = None

    # Step-by-step status
    steps: list[dict] = []

    # Data counts
    outputs_json_fields: int = 0
    review_items_count: int = 0
    field_mappings_count: int = 0
    field_evidence_count: int = 0

    # Raw data samples
    outputs_sample: Optional[dict] = None
    review_items_sample: list[dict] = []

    # Recommendations
    issues_found: list[str] = []
    fix_actions: list[str] = []


@router.get("/{id}/diagnose")
async def diagnose_extraction_pipeline(id: int) -> PipelineDiagnosticResponse:
    """
    Full pipeline diagnostic for troubleshooting.

    Checks every step from document to displayed fields:
    1. Document exists and has file
    2. Text extraction worked
    3. Extractor classification
    4. Extraction run status
    5. outputs_json populated
    6. review_items created
    7. field_mappings exist

    Returns step-by-step diagnosis with recommended fixes.
    """
    import json
    import os

    from api.database import get_connection

    response = PipelineDiagnosticResponse(extraction_id=id)
    issues = []
    fixes = []

    # Step 1: Get extraction run
    run = ExtractionRunRepository.get_by_id(id)
    if not run:
        response.steps.append(
            {
                "step": "1. Get extraction run",
                "status": "FAILED",
                "detail": f"Extraction run {id} not found in database",
            }
        )
        issues.append("Extraction run does not exist")
        fixes.append(
            "Check if document was uploaded. Run extraction via POST /api/extractions/run with document_id"
        )
        response.issues_found = issues
        response.fix_actions = fixes
        return response

    response.steps.append(
        {
            "step": "1. Get extraction run",
            "status": "OK",
            "detail": f"Run ID={run.id}, status={run.status}, created={run.created_at}",
        }
    )
    response.document_id = run.document_id

    # Step 2: Get document
    doc = DocumentRepository.get_by_id(run.document_id) if run.document_id else None
    if not doc:
        response.steps.append(
            {
                "step": "2. Get document",
                "status": "FAILED",
                "detail": f"Document ID={run.document_id} not found",
            }
        )
        issues.append("Document record missing from database")
        fixes.append("Re-upload the document")
    else:
        response.document_filename = doc.filename
        file_exists = os.path.exists(doc.file_path) if doc.file_path else False
        response.steps.append(
            {
                "step": "2. Get document",
                "status": "OK" if file_exists else "WARNING",
                "detail": f"filename={doc.filename}, file_exists={file_exists}, path={doc.file_path}",
            }
        )
        if not file_exists:
            issues.append("PDF file not found on disk")
            fixes.append(f"Re-upload the document. Expected path: {doc.file_path}")

    # Step 3: Get auction type
    at = AuctionTypeRepository.get_by_id(run.auction_type_id) if run.auction_type_id else None
    if not at:
        response.steps.append(
            {
                "step": "3. Get auction type",
                "status": "FAILED",
                "detail": f"Auction type ID={run.auction_type_id} not found",
            }
        )
        issues.append("Auction type not found")
        fixes.append("Check auction_types table is seeded. Restart server to re-seed.")
    else:
        response.auction_type = at.code
        response.steps.append(
            {
                "step": "3. Get auction type",
                "status": "OK",
                "detail": f"code={at.code}, name={at.name}",
            }
        )

    # Step 4: Check extraction status
    status_ok = run.status in ("needs_review", "reviewed", "exported")
    response.steps.append(
        {
            "step": "4. Extraction status",
            "status": "OK" if status_ok else "FAILED",
            "detail": f"status={run.status}, score={run.extraction_score}, time_ms={run.processing_time_ms}",
        }
    )
    if run.status == "failed":
        issues.append(f"Extraction failed: {run.errors_json}")
        fixes.append("Check extraction errors. May need OCR or different extractor.")
    elif run.status == "pending":
        issues.append("Extraction never ran")
        fixes.append("Run extraction via POST /api/extractions/run")

    # Step 5: Check outputs_json
    outputs = run.outputs_json or {}
    if isinstance(outputs, str):
        try:
            outputs = json.loads(outputs)
        except Exception:
            outputs = {}

    response.outputs_json_fields = len(outputs)
    response.outputs_sample = dict(list(outputs.items())[:10]) if outputs else None

    if not outputs:
        response.steps.append(
            {
                "step": "5. Check outputs_json",
                "status": "FAILED",
                "detail": "outputs_json is empty - no fields extracted",
            }
        )
        issues.append("No fields were extracted from document")
        fixes.append("Check debug endpoint for text quality. Document may need OCR.")
    else:
        response.steps.append(
            {
                "step": "5. Check outputs_json",
                "status": "OK",
                "detail": f"{len(outputs)} fields extracted: {list(outputs.keys())[:5]}...",
            }
        )

    # Step 6: Check review_items
    review_items = ReviewItemRepository.get_by_run(id)
    response.review_items_count = len(review_items)
    response.review_items_sample = [
        {"key": r.source_key, "value": r.predicted_value, "confidence": r.confidence}
        for r in review_items[:5]
    ]

    if not review_items:
        response.steps.append(
            {
                "step": "6. Check review_items",
                "status": "FAILED",
                "detail": "No review_items created for this extraction",
            }
        )
        issues.append("review_items table is empty for this run")
        fixes.append(
            "review_items are created by _create_review_items_for_all_fields(). Check if extraction completed."
        )
    else:
        filled = sum(1 for r in review_items if r.predicted_value)
        response.steps.append(
            {
                "step": "6. Check review_items",
                "status": "OK",
                "detail": f"{len(review_items)} items, {filled} with values",
            }
        )

    # Step 7: Check field_mappings
    with get_connection() as conn:
        mappings = conn.execute(
            "SELECT COUNT(*) as cnt FROM field_mappings WHERE auction_type_id = ?",
            (run.auction_type_id,),
        ).fetchone()
        mapping_count = mappings["cnt"] if mappings else 0

    response.field_mappings_count = mapping_count

    if mapping_count == 0:
        response.steps.append(
            {
                "step": "7. Check field_mappings",
                "status": "WARNING",
                "detail": f"No field_mappings for auction_type_id={run.auction_type_id}. Using defaults.",
            }
        )
        issues.append("field_mappings not seeded for this auction type")
        fixes.append("Restart server to re-seed field_mappings. Or use default fields.")
    else:
        response.steps.append(
            {
                "step": "7. Check field_mappings",
                "status": "OK",
                "detail": f"{mapping_count} field mappings configured",
            }
        )

    # Step 8: Check field_evidence
    evidence = FieldEvidenceRepository.get_by_run(id)
    response.field_evidence_count = len(evidence)
    response.steps.append(
        {
            "step": "8. Check field_evidence",
            "status": "OK" if evidence else "INFO",
            "detail": f"{len(evidence)} evidence records (for PDF highlighting)",
        }
    )

    # Step 9: Check metrics for OCR/text issues
    metrics = run.metrics_json or {}
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics)
        except Exception:
            metrics = {}

    text_length = metrics.get("raw_text_length", 0)
    ocr_applied = metrics.get("ocr_applied", False)
    needs_ocr = metrics.get("needs_ocr", False)

    if text_length < 100 and not ocr_applied:
        response.steps.append(
            {
                "step": "9. Text quality",
                "status": "FAILED",
                "detail": f"Only {text_length} chars extracted, OCR not applied",
            }
        )
        issues.append("Document has very little text and OCR was not applied")
        fixes.append("Install ocrmypdf for OCR support, or manually enter data")
    elif needs_ocr and not ocr_applied:
        response.steps.append(
            {
                "step": "9. Text quality",
                "status": "WARNING",
                "detail": f"OCR recommended but not applied. text_length={text_length}",
            }
        )
    else:
        response.steps.append(
            {
                "step": "9. Text quality",
                "status": "OK",
                "detail": f"text_length={text_length}, ocr_applied={ocr_applied}",
            }
        )

    # Summary
    response.issues_found = issues
    response.fix_actions = fixes

    return response


# =============================================================================
# Email Context + Vision Extract Endpoints
# =============================================================================


class EmailContextResponse(BaseModel):
    """Email context for a document linked to an extraction run."""
    sender: Optional[str] = None
    subject: Optional[str] = None
    date: Optional[str] = None
    body: Optional[str] = None
    attachments: list[dict] = Field(default_factory=list)
    source: str = "email"


@router.get("/{run_id}/email-context", response_model=EmailContextResponse)
async def get_email_context(run_id: int):
    """
    Get email context for an extraction run.

    Returns sender, subject, date, body text, and attachment list
    from the originating email (if the document was sourced from email).
    """
    import json
    from api.database import get_connection

    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    doc = DocumentRepository.get_by_id(run.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.source != "email":
        return EmailContextResponse(source="upload")

    # Get email metadata from document
    email_meta = {}
    if doc.email_metadata_json:
        try:
            email_meta = json.loads(doc.email_metadata_json) if isinstance(doc.email_metadata_json, str) else doc.email_metadata_json
        except (json.JSONDecodeError, TypeError):
            pass

    # Look up full email from email_log by matching extraction_run_ids
    body = None
    email_attachments = []
    with get_connection() as conn:
        # Try to find email_log entry that references this run.
        # Use exact JSON array element match to avoid LIKE false positives
        # (e.g., run_id=48 matching "[348]", "[480]", etc.)
        try:
            row = None
            # Try exact JSON match patterns: [48], [48,...], [...,48], [...,48,...]
            for pattern in [
                f"[{run_id}]",
                f"[{run_id},%",
                f"%, {run_id}]",
                f"%, {run_id},%",
            ]:
                row = conn.execute(
                    "SELECT sender, subject, body_preview, attachment_names, received_date "
                    "FROM email_log WHERE extraction_run_ids LIKE ?",
                    (pattern,),
                ).fetchone()
                if row:
                    break
        except Exception:
            row = None

        if row:
            body = row["body_preview"]
            sender = row["sender"] or email_meta.get("sender")
            subject = row["subject"] or email_meta.get("subject")
            date = row["received_date"] or email_meta.get("date")

            # Build run-attachment lookup for view URLs
            # Key by both sanitized and original filenames to handle mismatch
            run_att_map = {}
            try:
                att_row = conn.execute(
                    "SELECT attachments_json FROM extraction_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                if att_row and att_row["attachments_json"]:
                    for ra in json.loads(att_row["attachments_json"]):
                        fname = ra.get("filename", "")
                        run_att_map[fname] = ra
                        # Also key by original name (with spaces) for cross-lookup
                        orig = ra.get("original_filename", "")
                        if orig and orig != fname:
                            run_att_map[orig] = ra
                        # Also key by normalized form (spaces→underscores)
                        normalized = fname.replace(" ", "_")
                        if normalized != fname:
                            run_att_map[normalized] = ra
            except Exception:
                pass

            def _normalize_filename(name):
                """Normalize filename for dedup: lowercase, spaces→underscores, strip (N) suffixes."""
                import re
                n = (name or "").lower().strip().replace(" ", "_")
                # Strip parenthetical copy suffixes: "file_(1).pdf" → "file.pdf"
                n = re.sub(r'_?\(\d+\)', '', n)
                # Strip \r\n from email-mangled filenames
                n = n.replace('\r', '').replace('\n', '')
                return n

            # Parse attachment names and deduplicate
            att_names_raw = row["attachment_names"]
            if att_names_raw:
                try:
                    att_names = json.loads(att_names_raw) if isinstance(att_names_raw, str) else att_names_raw
                except (json.JSONDecodeError, TypeError):
                    att_names = []

                from pathlib import Path
                att_base = Path("data/attachments")
                seen_normalized = set()

                for att_name in att_names:
                    # Deduplicate by normalized filename
                    norm = _normalize_filename(att_name)
                    if norm in seen_normalized:
                        continue
                    seen_normalized.add(norm)

                    is_main = att_name in (doc.filename or "")
                    # Also check sanitized version against doc filename
                    if not is_main:
                        sanitized = att_name.replace(" ", "_")
                        is_main = sanitized in (doc.filename or "")

                    # Resolve view_url: main doc → document file, others → run attachment
                    # Try both original and sanitized names for lookup
                    if is_main:
                        view_url = f"/api/documents/{doc.id}/file"
                    elif att_name in run_att_map:
                        view_url = run_att_map[att_name].get("url")
                    elif att_name.replace(" ", "_") in run_att_map:
                        view_url = run_att_map[att_name.replace(" ", "_")].get("url")
                    else:
                        # Check if file exists on disk (try both original and sanitized names)
                        candidate = att_base / str(run_id) / Path(att_name).name
                        candidate_sanitized = att_base / str(run_id) / Path(att_name.replace(" ", "_")).name
                        if candidate.exists():
                            view_url = f"/api/documents/{run_id}/attachments/{att_name}"
                        elif candidate_sanitized.exists():
                            view_url = f"/api/documents/{run_id}/attachments/{att_name.replace(' ', '_')}"
                        else:
                            view_url = None
                    # Determine attachment type from run attachment or file extension
                    att_type = None
                    if att_name in run_att_map:
                        att_type = run_att_map[att_name].get("type")
                    elif att_name.replace(" ", "_") in run_att_map:
                        att_type = run_att_map[att_name.replace(" ", "_")].get("type")
                    if not att_type:
                        ext = att_name.rsplit(".", 1)[-1].lower() if "." in att_name else ""
                        if ext == "pdf":
                            att_type = "pdf"
                        elif ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp", "tiff"):
                            att_type = "image"
                        else:
                            att_type = "other"
                    email_attachments.append({
                        "filename": att_name,
                        "is_main_document": is_main,
                        "view_url": view_url,
                        "type": att_type,
                    })
        else:
            sender = email_meta.get("sender")
            subject = email_meta.get("subject")
            date = email_meta.get("date")

    return EmailContextResponse(
        sender=sender,
        subject=subject,
        date=date,
        body=body,
        attachments=email_attachments,
        source="email",
    )


class VisionExtractResponse(BaseModel):
    """Result of vision-based extraction."""
    fields: dict = Field(default_factory=dict)
    extraction_mode: str = "vision"
    page_count: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None


@router.post("/{run_id}/vision-extract", response_model=VisionExtractResponse)
async def vision_extract(run_id: int, auto_save: bool = Query(False, description="Save results to DB and set status to needs_review")):
    """
    Run vision-based extraction on a scanned PDF.

    Converts PDF pages to images and sends to Claude Haiku Vision API.
    Returns extracted fields for operator review.

    If auto_save=true, saves extracted fields to the run's outputs_json
    and changes status from manual_required to needs_review.
    """
    import base64
    import json
    import logging
    from pathlib import Path

    from api.database import get_connection

    logger = logging.getLogger(__name__)

    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    doc = DocumentRepository.get_by_id(run.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    pdf_path = doc.file_path
    if not pdf_path or not Path(pdf_path).exists():
        raise HTTPException(status_code=404, detail=f"PDF file not found: {pdf_path}")

    # Convert PDF to images using PyMuPDF (fitz)
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="PyMuPDF (fitz) not installed. Run: pip install PyMuPDF",
        )

    try:
        pdf_doc = fitz.open(str(pdf_path))
        page_count = len(pdf_doc)

        # Convert pages to base64 PNG images (max 5 pages)
        image_contents = []
        for page_num in range(min(page_count, 5)):
            page = pdf_doc[page_num]
            # Render at 200 DPI for good quality
            mat = fitz.Matrix(200 / 72, 200 / 72)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            b64_image = base64.b64encode(img_bytes).decode("utf-8")
            image_contents.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64_image,
                },
            })
        pdf_doc.close()
    except Exception as e:
        logger.error(f"Failed to convert PDF to images: {e}")
        raise HTTPException(status_code=500, detail=f"PDF to image conversion failed: {e}")

    # Build vision extraction prompt
    from services.haiku_extractor import EXTRACTION_PROMPT, HaikuExtractor

    extractor = HaikuExtractor()
    if not extractor.api_key:
        raise HTTPException(status_code=500, detail="Anthropic API key not configured")

    # Build messages with images + extraction prompt
    user_content = list(image_contents)
    user_content.append({
        "type": "text",
        "text": (
            "This is a scanned auction document. Extract the fields from the images above.\n\n"
            + EXTRACTION_PROMPT.replace("{document_text}", "[See images above]")
        ),
    })

    try:
        response = extractor.client.messages.create(
            model=extractor.MODEL,
            max_tokens=2000,
            system=extractor.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )

        # Parse response
        response_text = response.content[0].text
        parsed = extractor._parse_response(response_text)

        # Calculate cost
        from services.haiku_extractor import TokenUsage
        tokens = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        cost = tokens.calculate_cost(extractor.MODEL)

        if not parsed:
            return VisionExtractResponse(
                error="Failed to parse extraction response",
                page_count=page_count,
                cost_usd=cost,
            )

        # Flatten fields for frontend consumption
        fields = {}
        fields_data = parsed.get("fields", {})
        if fields_data:
            for key, val in fields_data.items():
                if isinstance(val, dict):
                    fields[key] = val.get("value")
                else:
                    fields[key] = val
        else:
            # Flat format
            for key, val in parsed.items():
                if key not in ("auction_type", "error"):
                    fields[key] = val
            if parsed.get("auction_type"):
                fields["auction_type"] = parsed["auction_type"]

        # Auto-save: persist to DB and update status
        if auto_save and fields:
            import json as json_mod
            with get_connection() as conn:
                # Merge vision fields into existing outputs
                existing = conn.execute(
                    "SELECT outputs_json FROM extraction_runs WHERE id = ?", (run_id,)
                ).fetchone()
                existing_outputs = json_mod.loads(existing[0]) if existing and existing[0] else {}
                existing_outputs.update(fields)

                conn.execute(
                    "UPDATE extraction_runs SET outputs_json = ?, status = 'needs_review', "
                    "extractor_kind = 'vision' WHERE id = ?",
                    (json_mod.dumps(existing_outputs), run_id),
                )
                conn.commit()
            logger.info(f"Vision auto-save: run {run_id} updated with {len(fields)} fields, status → needs_review")

        return VisionExtractResponse(
            fields=fields,
            extraction_mode="vision",
            page_count=page_count,
            cost_usd=cost,
        )

    except Exception as e:
        logger.error(f"Vision extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Vision extraction failed: {e}")
