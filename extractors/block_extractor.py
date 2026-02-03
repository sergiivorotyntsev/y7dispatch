"""
Block-Based Field Extraction with Key-Value Proximity

Provides layout-aware field extraction using spatial relationships
between labels and values. Tracks extraction evidence for transparency.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RelativePosition(Enum):
    """Relative position of value to label."""

    INLINE = "inline"  # Value on same line after label
    BELOW = "below"  # Value on line(s) below label
    RIGHT = "right"  # Value to the right (adjacent block)
    BELOW_RIGHT = "below_right"  # Value below and possibly right


class ExtractionMethod(Enum):
    """Method used for extraction."""

    PATTERN = "pattern"  # Regex pattern matching
    SPATIAL = "spatial"  # Spatial/layout-based
    KEY_VALUE = "key_value"  # Key-value proximity
    LEARNED_RULE = "learned_rule"  # ML or learned rule
    DEFAULT = "default"  # Default value


@dataclass
class ExtractionEvidence:
    """Evidence of where a field value was extracted from."""

    field_key: str
    value: str
    block_id: Optional[str] = None
    db_block_id: Optional[int] = None  # Database ID from layout_blocks
    text_snippet: str = ""
    page_num: int = 0
    bbox: Optional[tuple[float, float, float, float]] = None  # x0, y0, x1, y1
    rule_id: Optional[str] = None
    extraction_method: str = "pattern"
    confidence: float = 1.0
    label_matched: Optional[str] = None
    position_type: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "field_key": self.field_key,
            "value": self.value,
            "block_id": self.db_block_id,  # Use db_block_id for storage
            "text_snippet": self.text_snippet[:200] if self.text_snippet else None,
            "page_num": self.page_num,
            "bbox": (
                {"x0": self.bbox[0], "y0": self.bbox[1], "x1": self.bbox[2], "y1": self.bbox[3]}
                if self.bbox
                else None
            ),
            "rule_id": self.rule_id,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "value_source": "extracted",
        }


@dataclass
class BlockExtractionResult:
    """Result of block-based extraction for a field."""

    field_key: str
    value: Optional[str] = None
    evidence: Optional[ExtractionEvidence] = None
    success: bool = False
    alternatives: list[ExtractionEvidence] = field(default_factory=list)


class BlockExtractor:
    """
    Extracts field values using block-based key-value proximity.

    Uses spatial relationships between labels (keys) and values
    to accurately extract fields from structured documents.
    """

    # Default label patterns for common fields
    LABEL_PATTERNS = {
        "vehicle_vin": [
            r"VIN\s*[:#]?",
            r"Vehicle\s*ID\s*[:#]?",
            r"VIN:",
        ],
        "vehicle_year": [r"Year\s*[:#]?", r"YMMT", r"VEHICLE\s*[:#]?"],
        "vehicle_make": [r"Make\s*[:#]?", r"YMMT", r"VEHICLE\s*[:#]?"],
        "vehicle_model": [r"Model\s*[:#]?", r"YMMT", r"VEHICLE\s*[:#]?"],
        "vehicle_color": [r"Color\s*[:#]?", r"Ext\s*Color"],
        "vehicle_lot": [
            r"LOT\s*#\s*[:#]?",
            r"LOT#\s*[:#]?",
            r"Stock\s*[:#]?",
            r"Lot\s*Number",
        ],
        "pickup_address": [
            r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?(?:LOT)?",
            r"PICKUP\s*(?:LOCATION|ADDRESS)",
            r"LOCATION\s*[:#]?",
            r"SELLER\s*[:#]?",  # Copart uses SELLER for pickup location
        ],
        "pickup_city": [r"City\s*[:#]?"],
        "pickup_state": [r"State\s*[:#]?"],
        "pickup_zip": [r"ZIP\s*(?:Code)?\s*[:#]?", r"Postal\s*[:#]?"],
        "sale_date": [
            r"Sale\s*Date\s*[:#]?",
            r"Date\s*[:#]?",
            r"Sale\s*[:#]?",
            r"SALE\s+DATE",
        ],
        "buyer_id": [
            r"MEMBER\s*[:#]?",
            r"Buyer\s*(?:ID|#)\s*[:#]?",
            r"Member\s*ID",
        ],
        "buyer_name": [r"BUYER\s*[:#]?", r"Buyer\s*Name\s*[:#]?"],
        "reference_id": [
            r"LOT\s*#\s*[:#]?",
            r"LOT#\s*[:#]?",
            r"Ref(?:erence)?\s*[:#]?",
        ],
        "total_amount": [
            r"TOTAL\s*[:#]?",
            r"Amount\s*Due\s*[:#]?",
            r"Total\s*Charges",
        ],
    }

    # Value validation patterns
    VALUE_PATTERNS = {
        "vehicle_vin": r"^[A-HJ-NPR-Z0-9]{17}$",
        "vehicle_year": r"^(19|20)\d{2}$",
        "pickup_state": r"^[A-Z]{2}$",
        "pickup_zip": r"^\d{5}(-\d{4})?$",
        "sale_date": r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        "total_amount": r"^\$?[\d,]+\.?\d*$",
    }

    # Proximity thresholds (in points)
    VERTICAL_PROXIMITY = 30  # Max vertical distance for "below" relationship
    HORIZONTAL_PROXIMITY = 150  # Max horizontal distance for "right" relationship
    INLINE_GAP = 10  # Gap between label and inline value

    def __init__(self):
        self._custom_patterns: dict[str, list[str]] = {}

    def add_label_patterns(self, field_key: str, patterns: list[str]) -> None:
        """Add custom label patterns for a field."""
        if field_key not in self._custom_patterns:
            self._custom_patterns[field_key] = []
        self._custom_patterns[field_key].extend(patterns)

    def get_label_patterns(self, field_key: str) -> list[str]:
        """Get all label patterns for a field."""
        patterns = list(self.LABEL_PATTERNS.get(field_key, []))
        patterns.extend(self._custom_patterns.get(field_key, []))
        return patterns

    def extract_from_structure(
        self,
        structure: "DocumentStructure",
        field_key: str,
        label_patterns: list[str] = None,
        position_hint: RelativePosition = None,
        max_lines: int = 3,
    ) -> BlockExtractionResult:
        """
        Extract a field value from a parsed document structure.

        Args:
            structure: Parsed DocumentStructure from spatial_parser
            field_key: Field to extract (e.g., "vehicle_vin")
            label_patterns: Custom label patterns (uses defaults if None)
            position_hint: Expected position of value relative to label
            max_lines: Maximum lines to capture for multi-line values

        Returns:
            BlockExtractionResult with value and evidence
        """
        if label_patterns is None:
            label_patterns = self.get_label_patterns(field_key)

        result = BlockExtractionResult(field_key=field_key)
        candidates = []

        for pattern in label_patterns:
            # Find block containing the label
            block = structure.get_block_by_label(pattern)
            if not block:
                continue

            # Try inline extraction first
            inline_value = self._extract_inline_value(block, pattern)
            if inline_value:
                evidence = ExtractionEvidence(
                    field_key=field_key,
                    value=inline_value,
                    block_id=block.id,
                    text_snippet=block.text[:200],
                    page_num=block.page,
                    bbox=(block.x0, block.y0, block.x1, block.y1),
                    extraction_method=ExtractionMethod.KEY_VALUE.value,
                    label_matched=pattern,
                    position_type=RelativePosition.INLINE.value,
                    confidence=self._calculate_confidence(field_key, inline_value),
                )
                candidates.append(evidence)

            # Try below extraction
            below_lines = self._extract_lines_below(block, pattern, max_lines)
            if below_lines:
                value = self._join_lines(below_lines, field_key)
                evidence = ExtractionEvidence(
                    field_key=field_key,
                    value=value,
                    block_id=block.id,
                    text_snippet="\n".join(below_lines),
                    page_num=block.page,
                    bbox=(block.x0, block.y0, block.x1, block.y1),
                    extraction_method=ExtractionMethod.KEY_VALUE.value,
                    label_matched=pattern,
                    position_type=RelativePosition.BELOW.value,
                    confidence=self._calculate_confidence(field_key, value),
                )
                candidates.append(evidence)

            # Try adjacent block (right or below)
            for direction in ["right", "below"]:
                from extractors.spatial_parser import get_spatial_parser

                parser = get_spatial_parser()
                adjacent = parser.get_adjacent_block(structure, pattern, direction)
                if adjacent:
                    value = adjacent.text.strip()
                    if value and len(value) > 1:
                        pos = (
                            RelativePosition.RIGHT
                            if direction == "right"
                            else RelativePosition.BELOW
                        )
                        evidence = ExtractionEvidence(
                            field_key=field_key,
                            value=value,
                            block_id=adjacent.id,
                            text_snippet=adjacent.text[:200],
                            page_num=adjacent.page,
                            bbox=(adjacent.x0, adjacent.y0, adjacent.x1, adjacent.y1),
                            extraction_method=ExtractionMethod.SPATIAL.value,
                            label_matched=pattern,
                            position_type=pos.value,
                            confidence=self._calculate_confidence(field_key, value) * 0.9,
                        )
                        candidates.append(evidence)

        # Select best candidate based on confidence and position hint
        if candidates:
            candidates.sort(key=lambda e: e.confidence, reverse=True)

            # Apply position hint preference
            if position_hint:
                for candidate in candidates:
                    if candidate.position_type == position_hint.value:
                        result.value = candidate.value
                        result.evidence = candidate
                        result.success = True
                        result.alternatives = [c for c in candidates if c != candidate]
                        return result

            # Use highest confidence
            result.value = candidates[0].value
            result.evidence = candidates[0]
            result.success = True
            result.alternatives = candidates[1:]

        return result

    def extract_all_fields(
        self,
        structure: "DocumentStructure",
        fields: list[str] = None,
        use_fallback: bool = True,
    ) -> dict[str, BlockExtractionResult]:
        """
        Extract multiple fields from a document structure.

        Args:
            structure: Parsed DocumentStructure
            fields: List of field keys to extract (all known fields if None)
            use_fallback: Whether to use text-based fallback extraction

        Returns:
            Dict mapping field_key -> BlockExtractionResult
        """
        if fields is None:
            fields = list(self.LABEL_PATTERNS.keys())

        results = {}
        for field_key in fields:
            if use_fallback:
                results[field_key] = self.extract_with_fallback(structure, field_key)
            else:
                results[field_key] = self.extract_from_structure(structure, field_key)

        return results

    def _extract_inline_value(self, block, pattern: str) -> Optional[str]:
        """Extract value that appears on the same line after the label."""
        for line in block.lines:
            if re.search(pattern, line, re.IGNORECASE):
                # Get text after the label
                after = re.split(pattern, line, flags=re.IGNORECASE)[-1].strip()
                # Clean up common separators
                after = re.sub(r"^[:\s=]+", "", after).strip()

                # Stop at known field markers
                field_markers = [
                    r"\s+(?:VIN|LOT|MEMBER|BUYER|SELLER|TOTAL|Date|Sale|Row|Item)",
                    r"\s+(?:agrees|Document|evidences)",
                    r"\s+_+",  # Underscores often indicate form fields
                ]
                for marker in field_markers:
                    match = re.search(marker, after, re.IGNORECASE)
                    if match:
                        after = after[: match.start()].strip()

                if after and len(after) > 1 and not after.startswith("_"):
                    return after
        return None

    def _extract_lines_below(self, block, pattern: str, max_lines: int = 3) -> list[str]:
        """Extract lines appearing below the label line."""
        lines = block.lines
        result = []
        found_label = False

        for line in lines:
            if re.search(pattern, line, re.IGNORECASE):
                found_label = True
                continue

            if found_label:
                cleaned = line.strip()
                if cleaned:
                    # Stop at noise patterns
                    if self._is_noise_line(cleaned):
                        break
                    result.append(cleaned)
                    if len(result) >= max_lines:
                        break

        return result

    def _is_noise_line(self, line: str) -> bool:
        """Check if a line is likely noise/separator."""
        noise_patterns = [
            r"^[-_=*]{3,}$",  # Separator lines
            r"^(SELLER|BUYER|MEMBER|SOLD\s*THROUGH)",
            r"^Page\s+\d+",
            r"^(Total|Amount|Charges)",
        ]
        for pattern in noise_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                return True
        return False

    def _join_lines(self, lines: list[str], field_key: str) -> str:
        """Join multiple lines appropriately for the field type."""
        if not lines:
            return ""

        # For addresses, join with comma
        if "address" in field_key or "street" in field_key:
            return ", ".join(lines)

        # For most fields, take just the first line
        if field_key in [
            "vehicle_vin",
            "vehicle_year",
            "vehicle_make",
            "sale_date",
            "reference_id",
            "buyer_id",
        ]:
            return lines[0]

        # Default: join with space
        return " ".join(lines)

    def _calculate_confidence(self, field_key: str, value: str) -> float:
        """Calculate confidence score for an extracted value."""
        if not value:
            return 0.0

        base_confidence = 0.8

        # Validate against known patterns
        validation_pattern = self.VALUE_PATTERNS.get(field_key)
        if validation_pattern:
            if re.match(validation_pattern, value.strip(), re.IGNORECASE):
                base_confidence = 0.95
            else:
                base_confidence = 0.6

        # Penalize very short values
        if len(value) < 2:
            base_confidence *= 0.5

        # Penalize values that look like labels
        if re.match(r"^[A-Z\s]{2,10}:?$", value):
            base_confidence *= 0.5

        return min(1.0, base_confidence)

    def extract_from_text(
        self,
        text: str,
        field_key: str,
        page_num: int = 0,
    ) -> BlockExtractionResult:
        """
        Extract a field value using pattern matching on raw text.

        Fallback when spatial block extraction doesn't find the field.

        Args:
            text: Raw document text
            field_key: Field to extract
            page_num: Page number for evidence tracking

        Returns:
            BlockExtractionResult with value and evidence
        """
        result = BlockExtractionResult(field_key=field_key)

        # Direct value extraction patterns (not label-based)
        DIRECT_PATTERNS = {
            "vehicle_vin": r"\b([A-HJ-NPR-Z0-9]{17})\b",
            "vehicle_year": r"(?:VEHICLE|YMMT)[:\s]+(\d{4})\s+[A-Z]",
            "vehicle_lot": r"LOT#?\s*:?\s*(\d{6,10})\b",
            "sale_date": r"(?:Sale|Date)[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            "buyer_id": r"MEMBER\s*:\s*(\d{4,10})\b",  # MEMBER:535527 format
            "buyer_name": r"MEMBER\s*:\s*\d+\s+(?:SELLER[:\s]*)?\s*(?:LOT[:\s]*)?\s*([A-Z][A-Za-z\s\-]+)",
            "total_amount": r"(?:Sale\s*Price|TOTAL|Net\s*Due)[:\s]*\$?([\d,]+\.\d{2})\b",
        }

        # Try direct pattern extraction
        pattern = DIRECT_PATTERNS.get(field_key)
        if pattern:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1)
                evidence = ExtractionEvidence(
                    field_key=field_key,
                    value=value,
                    text_snippet=text[max(0, match.start() - 20) : match.end() + 20],
                    page_num=page_num,
                    extraction_method=ExtractionMethod.PATTERN.value,
                    confidence=self._calculate_confidence(field_key, value),
                )
                result.value = value
                result.evidence = evidence
                result.success = True
                return result

        # Try label-based extraction on raw text
        label_patterns = self.get_label_patterns(field_key)
        for label_pattern in label_patterns:
            # Find label and extract value after it
            label_match = re.search(label_pattern, text, re.IGNORECASE)
            if label_match:
                # Get text after label (up to end of line or next label)
                after_label = text[label_match.end() :]
                line_end = after_label.find("\n")
                if line_end > 0:
                    line_text = after_label[:line_end].strip()
                else:
                    line_text = after_label[:100].strip()

                # Clean up value
                value = re.sub(r"^[:\s=]+", "", line_text).strip()
                if value and len(value) > 1:
                    # Validate value looks reasonable
                    if not self._looks_like_label(value):
                        evidence = ExtractionEvidence(
                            field_key=field_key,
                            value=value,
                            text_snippet=text[
                                max(0, label_match.start() - 10) : label_match.end() + 60
                            ],
                            page_num=page_num,
                            extraction_method=ExtractionMethod.PATTERN.value,
                            label_matched=label_pattern,
                            position_type=RelativePosition.INLINE.value,
                            confidence=self._calculate_confidence(field_key, value) * 0.85,
                        )
                        result.value = value
                        result.evidence = evidence
                        result.success = True
                        return result

        return result

    def _looks_like_label(self, text: str) -> bool:
        """Check if text looks like a label rather than a value."""
        label_indicators = [
            r"^[A-Z\s]{2,15}:?$",  # ALL CAPS short text
            r"^(?:SELLER|BUYER|MEMBER|LOT|VIN|DATE|TOTAL)",
            r"^(?:ADDRESS|CITY|STATE|ZIP|PHONE)",
        ]
        for pattern in label_indicators:
            if re.match(pattern, text.strip(), re.IGNORECASE):
                return True
        return False

    def extract_with_fallback(
        self,
        structure: "DocumentStructure",
        field_key: str,
        label_patterns: list[str] = None,
    ) -> BlockExtractionResult:
        """
        Extract field using both block-based and pattern extraction,
        selecting the best result based on confidence.

        Args:
            structure: Parsed DocumentStructure
            field_key: Field to extract
            label_patterns: Custom label patterns

        Returns:
            BlockExtractionResult with highest confidence value
        """
        # Try both extraction methods
        block_result = self.extract_from_structure(structure, field_key, label_patterns)
        pattern_result = self.extract_from_text(structure.raw_text, field_key)

        # Get confidence scores
        block_conf = block_result.evidence.confidence if block_result.success else 0.0
        pattern_conf = pattern_result.evidence.confidence if pattern_result.success else 0.0

        # Fields that should prefer pattern extraction when available
        pattern_preferred = ["buyer_id", "vehicle_vin", "vehicle_lot", "total_amount"]

        # Select best result
        if field_key in pattern_preferred and pattern_result.success:
            # Prefer pattern for specific fields if it finds a value
            if block_result.success:
                pattern_result.alternatives = [block_result.evidence]
            return pattern_result

        if block_result.success and pattern_result.success:
            # Both found values - use higher confidence
            if pattern_conf > block_conf + 0.1:  # Pattern needs higher confidence
                pattern_result.alternatives = [block_result.evidence]
                return pattern_result
            else:
                block_result.alternatives = [pattern_result.evidence]
                return block_result

        # Return whichever succeeded
        if block_result.success:
            return block_result
        return pattern_result


def extract_with_evidence(
    pdf_path: str,
    fields: list[str] = None,
    document_id: int = None,
) -> tuple[dict[str, Any], list[dict]]:
    """
    High-level function to extract fields with evidence tracking.

    Args:
        pdf_path: Path to PDF document
        fields: List of field keys to extract (all if None)
        document_id: Optional database document ID for linking evidence

    Returns:
        Tuple of (extracted_fields dict, evidence_list)
    """
    from extractors.spatial_parser import parse_document

    # Parse document structure
    structure = parse_document(pdf_path)

    # Extract fields
    extractor = BlockExtractor()
    results = extractor.extract_all_fields(structure, fields)

    # Build outputs
    extracted_fields = {}
    evidence_list = []

    for field_key, result in results.items():
        if result.success and result.value:
            extracted_fields[field_key] = result.value

            if result.evidence:
                evidence_dict = result.evidence.to_dict()
                evidence_list.append(evidence_dict)

    return extracted_fields, evidence_list


def save_extraction_evidence(
    run_id: int,
    evidence_list: list[dict],
    document_id: int = None,
) -> int:
    """
    Save extraction evidence to database.

    Args:
        run_id: Extraction run ID
        evidence_list: List of evidence dicts from extract_with_evidence
        document_id: Optional document ID for linking to layout blocks

    Returns:
        Number of evidence records saved
    """
    from api.models import FieldEvidenceRepository, LayoutBlockRepository

    # If we have document_id, try to link evidence to stored layout blocks
    if document_id:
        stored_blocks = LayoutBlockRepository.get_by_document(document_id)
        block_map = {b.block_id: b.id for b in stored_blocks}

        for evidence in evidence_list:
            if evidence.get("block_id") is None:
                # Try to find matching block by ID
                block_str_id = evidence.get("_block_str_id")
                if block_str_id and block_str_id in block_map:
                    evidence["block_id"] = block_map[block_str_id]

    # Save evidence
    ids = FieldEvidenceRepository.create_batch(run_id, evidence_list)
    return len(ids)


# Singleton instance
_block_extractor = None


def get_block_extractor() -> BlockExtractor:
    """Get or create the block extractor singleton."""
    global _block_extractor
    if _block_extractor is None:
        _block_extractor = BlockExtractor()
    return _block_extractor
