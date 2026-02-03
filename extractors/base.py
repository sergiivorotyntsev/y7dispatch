"""Base extractor class for auction invoices."""

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pdfplumber

from models.vehicle import (
    Address,
    AuctionInvoice,
    AuctionSource,
    VehicleType,
)

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of PDF extraction with metadata."""

    invoice: Optional[AuctionInvoice]
    source: AuctionSource
    score: float  # 0.0 to 1.0 confidence
    text_length: int
    needs_ocr: bool = False
    matched_patterns: list[str] = None
    learned_rules_applied: list[str] = None  # Track which learned rules were used

    def __post_init__(self):
        if self.matched_patterns is None:
            self.matched_patterns = []
        if self.learned_rules_applied is None:
            self.learned_rules_applied = []


@dataclass
class LearnedRule:
    """A learned extraction rule for a specific field."""

    field_key: str
    rule_type: str  # 'label_below', 'label_inline', 'regex', 'position'
    label_patterns: list[str]
    exclude_patterns: list[str]
    confidence: float

    def matches_label(self, text: str) -> bool:
        """Check if any label pattern matches in the text."""
        for pattern in self.label_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    def should_exclude(self, text: str) -> bool:
        """Check if text matches any exclude pattern."""
        for pattern in self.exclude_patterns:
            if pattern.lower() in text.lower():
                return True
        return False


class BaseExtractor(ABC):
    """Base class for auction document extractors."""

    # Minimum text length to consider document valid (vs scan/image)
    MIN_TEXT_LENGTH = 100

    # Score threshold for confident detection
    SCORE_THRESHOLD = 0.6

    # Learned rules cache
    _learned_rules: dict[str, LearnedRule] = None
    _rules_loaded: bool = False

    @property
    @abstractmethod
    def source(self) -> AuctionSource:
        pass

    @property
    def auction_type_code(self) -> str:
        """Return auction type code (e.g., 'COPART', 'IAA')."""
        return self.source.value.upper() if self.source else "UNKNOWN"

    @property
    @abstractmethod
    def indicators(self) -> list[str]:
        """List of text patterns that indicate this document type."""
        pass

    @property
    def indicator_weights(self) -> dict:
        """Optional weights for indicators (default: equal weight)."""
        return {}

    def load_learned_rules(self) -> dict[str, LearnedRule]:
        """
        Load learned extraction rules from the training database.

        Returns a dict of field_key -> LearnedRule
        """
        if self._rules_loaded and self._learned_rules is not None:
            return self._learned_rules

        self._learned_rules = {}

        try:
            # Try to load rules from training database
            from api.training_db import get_session
            from services.training_service import TrainingService

            with get_session() as session:
                service = TrainingService(session)
                rules_data = service.get_rules_for_extractor(self.auction_type_code)

                for field_key, rule_info in rules_data.items():
                    self._learned_rules[field_key] = LearnedRule(
                        field_key=field_key,
                        rule_type=rule_info.get("rule_type", "label_below"),
                        label_patterns=rule_info.get("label_patterns", []),
                        exclude_patterns=rule_info.get("exclude_patterns", []),
                        confidence=rule_info.get("confidence", 0.5),
                    )

                logger.info(
                    f"Loaded {len(self._learned_rules)} learned rules for {self.auction_type_code}"
                )
        except Exception as e:
            logger.warning(f"Could not load learned rules: {e}")
            self._learned_rules = {}

        self._rules_loaded = True
        return self._learned_rules

    def get_learned_rule(self, field_key: str) -> Optional[LearnedRule]:
        """Get a learned rule for a specific field."""
        rules = self.load_learned_rules()
        return rules.get(field_key)

    def extract_with_learned_rules(
        self, text: str, field_key: str, default_labels: list[str] = None, default_extract_func=None
    ) -> tuple[Optional[str], bool]:
        """
        Extract a field value using learned rules with fallback to defaults.

        Args:
            text: Document text to search
            field_key: Field being extracted (e.g., 'pickup_address')
            default_labels: Default label patterns if no learned rule
            default_extract_func: Default extraction function

        Returns:
            (extracted_value, used_learned_rule)
        """
        rule = self.get_learned_rule(field_key)

        if rule and rule.label_patterns:
            # Use learned rule
            value = self._extract_value_with_rule(text, rule)
            if value:
                logger.debug(f"Extracted {field_key} using learned rule: {value[:50]}...")
                return value, True

        # Fallback to default extraction
        if default_extract_func:
            value = default_extract_func(text)
            return value, False

        if default_labels:
            # Try default labels
            from extractors.address_parser import extract_lines_after_label

            for label in default_labels:
                lines = extract_lines_after_label(text, label)
                if lines:
                    return "\n".join(lines[:3]), False

        return None, False

    def _extract_value_with_rule(self, text: str, rule: LearnedRule) -> Optional[str]:
        """Extract a value using a learned rule."""
        from extractors.address_parser import extract_lines_after_label

        for label_pattern in rule.label_patterns:
            try:
                lines = extract_lines_after_label(text, label_pattern)
                if lines:
                    # Filter out excluded patterns
                    filtered_lines = []
                    for line in lines:
                        if not rule.should_exclude(line):
                            filtered_lines.append(line)

                    if filtered_lines:
                        return "\n".join(filtered_lines[:3])
            except Exception as e:
                logger.warning(f"Error applying rule for {rule.field_key}: {e}")
                continue

        return None

    def score(self, text: str) -> tuple[float, list[str]]:
        """
        Calculate confidence score for this extractor.
        Returns (score, matched_patterns) where score is 0.0 to 1.0.
        """
        if not text or len(text) < self.MIN_TEXT_LENGTH:
            return 0.0, []

        text_lower = text.lower()
        matched = []
        total_weight = 0.0
        matched_weight = 0.0

        for indicator in self.indicators:
            weight = self.indicator_weights.get(indicator, 1.0)
            total_weight += weight

            if indicator.lower() in text_lower:
                matched.append(indicator)
                matched_weight += weight

        if total_weight == 0:
            return 0.0, []

        score = matched_weight / total_weight
        return score, matched

    def can_extract(self, text: str) -> bool:
        """Check if this extractor can handle the document."""
        score, _ = self.score(text)
        return score >= self.SCORE_THRESHOLD

    @abstractmethod
    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        pass

    def extract_with_result(self, pdf_path: str, text: str = None) -> ExtractionResult:
        """Extract with full result metadata."""
        if text is None:
            text = self.extract_text(pdf_path)

        score, matched = self.score(text)
        needs_ocr = len(text) < self.MIN_TEXT_LENGTH

        if needs_ocr:
            logger.warning(f"Document has insufficient text ({len(text)} chars), may need OCR")

        invoice = None
        learned_rules_applied = []

        if score >= self.SCORE_THRESHOLD:
            try:
                # Load learned rules before extraction
                self.load_learned_rules()
                invoice = self.extract(pdf_path)

                # Track which learned rules were applied
                for field_key, rule in (self._learned_rules or {}).items():
                    if rule.confidence > 0.5:
                        learned_rules_applied.append(field_key)

            except Exception as e:
                logger.error(f"Extraction failed: {e}")

        return ExtractionResult(
            invoice=invoice,
            source=self.source,
            score=score,
            text_length=len(text),
            needs_ocr=needs_ocr,
            matched_patterns=matched,
            learned_rules_applied=learned_rules_applied,
        )

    def extract_text(self, pdf_path: str) -> str:
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text

    def extract_pages_text(self, pdf_path: str) -> list[str]:
        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                pages.append(page_text or "")
        return pages

    @staticmethod
    def clean_text(text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @staticmethod
    def extract_vin(text: str) -> Optional[str]:
        pattern = r"\b[A-HJ-NPR-Z0-9]{17}\b"
        match = re.search(pattern, text)
        return match.group(0) if match else None

    @staticmethod
    def extract_phone(text: str) -> Optional[str]:
        patterns = [r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", r"\d{3}[-.\s]\d{3}[-.\s]\d{4}"]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None

    @staticmethod
    def extract_zip(text: str) -> Optional[str]:
        pattern = r"\b\d{5}(?:-\d{4})?\b"
        match = re.search(pattern, text)
        return match.group(0) if match else None

    @staticmethod
    def parse_address(text: str) -> tuple[str, str, str]:
        """
        Parse city, state, zip from a text line.

        For more robust address extraction from documents, use the shared
        address_parser module functions like extract_pickup_address().

        Returns: (city, state, zip_code)
        """
        # Import and use the shared parser for better handling of various formats
        from extractors.address_parser import parse_city_state_zip

        city, state, zip_code = parse_city_state_zip(text)
        if city and state:
            return city, state, zip_code or ""

        # Fallback to basic pattern
        pattern = r"([A-Za-z\s]+)[,\s]+([A-Z]{2})[\s.,]+(\d{5}(?:-\d{4})?)"
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip(), match.group(2), match.group(3)
        return "", "", ""

    @staticmethod
    def detect_vehicle_type(make: str, model: str) -> VehicleType:
        combined = f"{make} {model}".upper()

        suv_keywords = [
            "SUV",
            "XC90",
            "XC60",
            "XC40",
            "DURANGO",
            "CHEROKEE",
            "TUCSON",
            "KONA",
            "EXPLORER",
            "TAHOE",
            "SUBURBAN",
        ]
        car_keywords = ["SEDAN", "COUPE", "HARDTOP", "GIULIA", "E 300", "CAMRY", "ACCORD"]
        truck_keywords = ["TRUCK", "F-150", "SILVERADO", "RAM", "TUNDRA"]
        van_keywords = ["VAN", "CARAVAN", "ODYSSEY", "SIENNA"]

        for keyword in suv_keywords:
            if keyword in combined:
                return VehicleType.SUV
        for keyword in car_keywords:
            if keyword in combined:
                return VehicleType.CAR
        for keyword in truck_keywords:
            if keyword in combined:
                return VehicleType.TRUCK
        for keyword in van_keywords:
            if keyword in combined:
                return VehicleType.VAN

        return VehicleType.SUV

    @staticmethod
    def extract_year(text: str) -> Optional[int]:
        pattern = r"\b(19|20)\d{2}\b"
        match = re.search(pattern, text)
        if match:
            return int(match.group(0))
        return None

    @staticmethod
    def extract_mileage(text: str) -> Optional[int]:
        patterns = [
            # Match "Mileage: 123456" or "Mileage: 123,456" - \d+ first for non-comma numbers
            r"Mileage[:\s]+(\d+(?:,\d{3})*|\d+)",
            r"(\d{1,3}(?:,\d{3})+|\d+)\s*(?:Miles|Mi\.?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                mileage = match.group(1).replace(",", "")
                return int(mileage)
        return None

    @staticmethod
    def extract_amount(text: str, keyword: str = None) -> Optional[float]:
        if keyword:
            pattern = rf"{keyword}[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)"
        else:
            pattern = r"\$\s*([\d,]+(?:\.\d{2})?)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = match.group(1).replace(",", "")
            return float(amount)
        return None

    # =========================================================================
    # UNIVERSAL ADDRESS EXTRACTION (for all auction types)
    # =========================================================================

    def extract_pickup_address_universal(
        self,
        text: str,
        pdf_path: str = None,
        label_patterns: list[str] = None,
        source_name: str = None,
    ) -> Optional[Address]:
        """
        Universal pickup address extraction using multiple strategies.

        Works for all auction types (Copart, IAA, Manheim).

        Strategies (in order):
        1. Learned rules from training
        2. Spatial parsing (block-based, if pdf_path provided)
        3. Text-based extraction with label patterns
        4. Fallback to generic address parser

        Args:
            text: Document text
            pdf_path: Optional PDF path for spatial parsing
            label_patterns: Custom label patterns for this auction type
            source_name: Source name (Copart, IAA, etc.) for Address object

        Returns:
            Address object or None
        """
        from extractors.address_parser import extract_lines_after_label, extract_pickup_address

        # Default label patterns that work for most auction documents
        default_patterns = [
            r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT[:\s]*",
            r"LOT\s*(?:LOCATION|ADDRESS)[:\s]*",
            r"PICKUP\s*(?:LOCATION|ADDRESS)[:\s]*",
            r"BRANCH[:\s]*",
            r"YARD\s*(?:LOCATION|ADDRESS)[:\s]*",
        ]

        patterns = label_patterns or default_patterns
        source = source_name or self.auction_type_code

        # Strategy 1: Check for learned rules first
        rule = self.get_learned_rule("pickup_address")
        if rule and rule.label_patterns:
            logger.debug(f"Using learned rule for pickup_address: {rule.label_patterns}")
            for label_pattern in rule.label_patterns:
                lines = extract_lines_after_label(text, label_pattern)
                if lines:
                    addr = self._parse_address_from_lines(lines, rule.exclude_patterns, source)
                    if addr and (addr.street or addr.city):
                        return addr

        # Strategy 2: Try spatial parsing if we have the PDF path
        if pdf_path:
            try:
                from extractors.spatial_parser import parse_document

                structure = parse_document(pdf_path)
                addr = self._extract_address_spatial(structure, patterns, source)
                if addr and (addr.street or addr.city):
                    logger.debug(
                        f"Extracted address using spatial parsing: {addr.city}, {addr.state}"
                    )
                    return addr
            except Exception as e:
                logger.warning(f"Spatial parsing failed: {e}")

        # Strategy 3: Text-based extraction with label patterns
        for pattern in patterns:
            lines = extract_lines_after_label(text, pattern, max_lines=4)
            if lines:
                addr = self._parse_address_from_lines(lines, source_name=source)
                if addr and (addr.street or addr.city):
                    return addr

        # Strategy 4: Final fallback to shared parser
        return extract_pickup_address(text, source=source, custom_labels=patterns)

    def _extract_address_spatial(
        self, structure: "DocumentStructure", label_patterns: list[str], source_name: str = None
    ) -> Optional[Address]:
        """Extract address using spatial document structure."""
        for pattern in label_patterns:
            block = structure.get_block_by_label(pattern)
            if block:
                lines = block.lines
                # Find lines after the label
                found_label = False
                address_lines = []

                for line in lines:
                    if re.search(pattern, line, re.IGNORECASE):
                        found_label = True
                        # Check for inline value
                        after = re.split(pattern, line, flags=re.IGNORECASE)[-1].strip()
                        after = re.sub(r"^[:\s]+", "", after)
                        if after and len(after) > 3:
                            address_lines.append(after)
                        continue

                    if found_label and line.strip():
                        # Skip common noise patterns
                        if re.search(
                            r"SELLER|SOLD\s*THROUGH|INSURANCE|MEMBER|BUYER", line, re.IGNORECASE
                        ):
                            break
                        address_lines.append(line.strip())
                        if len(address_lines) >= 3:
                            break

                if address_lines:
                    return self._parse_address_from_lines(address_lines, source_name=source_name)

        return None

    def _parse_address_from_lines(
        self, lines: list[str], exclude_patterns: list[str] = None, source_name: str = None
    ) -> Optional[Address]:
        """
        Parse an Address object from extracted text lines.

        Args:
            lines: List of text lines (street, city/state/zip, etc.)
            exclude_patterns: Patterns to filter out
            source_name: Source name for Address object

        Returns:
            Address object or None
        """
        if not lines:
            return None

        # Filter out excluded patterns
        if exclude_patterns:
            filtered_lines = []
            for line in lines:
                excluded = False
                for pattern in exclude_patterns:
                    if pattern.lower() in line.lower():
                        excluded = True
                        break
                if not excluded:
                    filtered_lines.append(line)
            lines = filtered_lines

        if not lines:
            return None

        # First line is usually street address
        street = lines[0].strip() if lines else ""

        # Look for city/state/zip in remaining lines
        city, state, zip_code = "", "", ""
        for line in lines[1:]:
            parsed_city, parsed_state, parsed_zip = self.parse_address(line)
            if parsed_city and parsed_state:
                city, state, zip_code = parsed_city, parsed_state, parsed_zip
                break

        # If no city/state found in subsequent lines, try parsing the first line
        if not city and not state and len(lines) == 1:
            # Single line address like "123 Main St, Dallas TX 75001"
            parts = lines[0].split(",")
            if len(parts) >= 2:
                street = parts[0].strip()
                parsed_city, parsed_state, parsed_zip = self.parse_address(parts[-1])
                if parsed_city and parsed_state:
                    city, state, zip_code = parsed_city, parsed_state, parsed_zip

        # If we still don't have city/state, try parsing the second line if exists
        if not city and not state and len(lines) >= 2:
            parsed_city, parsed_state, parsed_zip = self.parse_address(lines[1])
            city, state, zip_code = parsed_city, parsed_state, parsed_zip

        if street or (city and state):
            return Address(
                name=source_name or self.auction_type_code,
                street=street,
                city=city,
                state=state,
                postal_code=zip_code,
            )

        return None
