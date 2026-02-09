"""
Zone-Based Document Extraction

Extracts data from specific zones/regions of PDF documents based on templates.
This approach provides 100% accuracy for known document layouts by extracting
text only from the correct regions (e.g., pickup address from center column,
not from seller column).

Key concepts:
- DocumentZone: A rectangular region on a page with specific field mappings
- DocumentTemplate: A collection of zones for a specific document type
- ZoneExtractor: Extracts text from zones and parses fields

Usage:
    extractor = ZoneExtractor()
    result = extractor.extract("invoice.pdf", "COPART")
    print(result["pickup_city"])  # "LAS VEGAS" (from correct zone)
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import pdfplumber

logger = logging.getLogger(__name__)


class FieldType(str, Enum):
    """Field data types for validation and parsing"""

    TEXT = "text"
    ADDRESS = "address"
    CITY_STATE_ZIP = "city_state_zip"
    VIN = "vin"
    DATE = "date"
    CURRENCY = "currency"
    PHONE = "phone"
    NUMBER = "number"


# Default field configurations for common field keys
# These are used when fields from database don't have complete metadata
DEFAULT_FIELD_CONFIGS = {
    "vehicle_vin": {
        "field_type": FieldType.VIN,
        "pattern": r"\b([A-HJ-NPR-Z0-9]{17})\b",
        "required": True,
    },
    "vehicle_year": {
        "field_type": FieldType.NUMBER,
        "pattern": r"\b(19[89]\d|20[0-2]\d)\b",
    },
    "vehicle_make": {"field_type": FieldType.TEXT},
    "vehicle_model": {"field_type": FieldType.TEXT},
    "vehicle_lot": {
        "field_type": FieldType.TEXT,
        "pattern": r"(?:LOT|STOCK)\s*#?\s*:?\s*(\d{6,10})",
    },
    "pickup_address": {"field_type": FieldType.ADDRESS, "required": True},
    "pickup_city": {"field_type": FieldType.TEXT, "required": True},
    "pickup_state": {
        "field_type": FieldType.TEXT,
        "pattern": r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b",
        "required": True,
    },
    "pickup_zip": {
        "field_type": FieldType.TEXT,
        "pattern": r"\b(\d{5}(?:-\d{4})?)\b",
        "required": True,
    },
    "pickup_phone": {
        "field_type": FieldType.PHONE,
        "pattern": r"(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})",
    },
    "buyer_id": {
        "field_type": FieldType.TEXT,
        "pattern": r"(?:Member|MEMBER|Buyer)\s*#?\s*:?\s*(\d+)",
    },
    "total_amount": {
        "field_type": FieldType.CURRENCY,
        "pattern": r"(?:Total|Amount\s*Due)[:\s]*\$?([\d,]+\.?\d*)",
    },
    "sale_date": {
        "field_type": FieldType.DATE,
        "pattern": r"(?:Sale|Sold)\s*Date[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})",
    },
}


@dataclass
class ZoneField:
    """A field to extract from a zone"""

    key: str  # Field key (e.g., "pickup_city")
    field_type: FieldType = FieldType.TEXT
    pattern: Optional[str] = None  # Optional regex pattern
    label: Optional[str] = None  # Label to look for (e.g., "City:")
    label_patterns: list[str] = field(default_factory=list)  # Multiple label patterns (e.g., ["Stock\\s*No", "StockNo"])
    extract_strategy: str = "after_label"  # How to extract: after_label, regex, full_zone
    required: bool = False

    def apply_defaults(self):
        """Apply default configuration from DEFAULT_FIELD_CONFIGS if available"""
        defaults = DEFAULT_FIELD_CONFIGS.get(self.key, {})
        if defaults:
            if self.field_type == FieldType.TEXT and "field_type" in defaults:
                self.field_type = defaults["field_type"]
            if not self.pattern and "pattern" in defaults:
                self.pattern = defaults["pattern"]
            if not self.required and defaults.get("required"):
                self.required = defaults["required"]


@dataclass
class DocumentZone:
    """
    A rectangular zone on a document page.

    Coordinates are percentages (0-100) of page dimensions:
    - x0, y0: top-left corner
    - x1, y1: bottom-right corner

    This allows templates to work across different page sizes.
    """

    name: str
    x0: float  # Left edge (0-100%)
    y0: float  # Top edge (0-100%)
    x1: float  # Right edge (0-100%)
    y1: float  # Bottom edge (0-100%)
    fields: list[ZoneField] = field(default_factory=list)
    description: Optional[str] = None

    def to_bbox(self, page_width: float, page_height: float) -> tuple[float, float, float, float]:
        """
        Convert percentage coordinates to absolute bbox.
        Returns (x0, y0, x1, y1) in PDF points.
        Ensures coordinates are in correct order (x0 < x1, y0 < y1).
        """
        # Ensure coordinates are in correct order
        x0, x1 = min(self.x0, self.x1), max(self.x0, self.x1)
        y0, y1 = min(self.y0, self.y1), max(self.y0, self.y1)

        return (
            page_width * x0 / 100,
            page_height * y0 / 100,
            page_width * x1 / 100,
            page_height * y1 / 100,
        )

    def to_dict(self) -> dict:
        """Serialize to dict for storage"""
        return {
            "name": self.name,
            "x0": self.x0,
            "y0": self.y0,
            "x1": self.x1,
            "y1": self.y1,
            "fields": [
                {
                    "key": f.key,
                    "field_type": f.field_type.value,
                    "pattern": f.pattern,
                    "label": f.label,
                    "label_patterns": f.label_patterns,
                    "extract_strategy": f.extract_strategy,
                    "required": f.required,
                }
                for f in self.fields
            ],
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentZone":
        """Deserialize from dict"""
        fields = [
            ZoneField(
                key=f["key"],
                field_type=FieldType(f.get("field_type", "text")),
                pattern=f.get("pattern"),
                label=f.get("label"),
                label_patterns=f.get("label_patterns", []),
                extract_strategy=f.get("extract_strategy", "after_label"),
                required=f.get("required", False),
            )
            for f in data.get("fields", [])
        ]
        return cls(
            name=data["name"],
            x0=data["x0"],
            y0=data["y0"],
            x1=data["x1"],
            y1=data["y1"],
            fields=fields,
            description=data.get("description"),
        )


@dataclass
class DocumentTemplate:
    """
    Template for extracting data from a specific document type.

    Contains multiple zones, each with its own field mappings.
    """

    template_id: str
    name: str
    auction_type: str
    version: int = 1
    zones: list[DocumentZone] = field(default_factory=list)
    description: Optional[str] = None
    is_active: bool = True

    def to_dict(self) -> dict:
        """Serialize to dict for storage"""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "auction_type": self.auction_type,
            "version": self.version,
            "zones": [z.to_dict() for z in self.zones],
            "description": self.description,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentTemplate":
        """Deserialize from dict"""
        zones = [DocumentZone.from_dict(z) for z in data.get("zones", [])]
        return cls(
            template_id=data["template_id"],
            name=data["name"],
            auction_type=data["auction_type"],
            version=data.get("version", 1),
            zones=zones,
            description=data.get("description"),
            is_active=data.get("is_active", True),
        )


@dataclass
class ExtractionResult:
    """Result of zone-based extraction"""

    fields: dict[str, Any]
    zone_texts: dict[str, str]  # Raw text from each zone
    confidence: float
    template_id: str
    warnings: list[str] = field(default_factory=list)


class ZoneExtractor:
    """
    Extracts data from PDF documents using zone-based templates.

    This approach:
    1. Identifies document type (COPART, IAA, etc.)
    2. Loads the appropriate template with zone definitions
    3. Extracts text from each zone using pdfplumber crop
    4. Parses fields from zone text using patterns/labels

    Benefits:
    - 100% accuracy when zones are correctly defined
    - No confusion between columns (seller vs pickup address)
    - Fast - just crops and extracts text
    - Works with native PDFs (no OCR needed)
    """

    # US States for address parsing
    US_STATES = r"AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"

    def __init__(self):
        self.templates: dict[str, DocumentTemplate] = {}
        self._load_default_templates()
        # Load templates from database (overrides defaults)
        self._load_database_templates()

    def _load_default_templates(self):
        """Load default templates for known auction types"""
        # These serve as fallbacks if no database templates exist

        # COPART Invoice Template
        self.templates["COPART"] = self._create_copart_template()
        self.templates["IAA"] = self._create_iaa_template()
        self.templates["MANHEIM"] = self._create_manheim_template()

    def _load_database_templates(self):
        """
        Load templates from database, overriding defaults.
        This allows users to customize zone definitions via the UI.
        """
        try:
            from api.routes.templates import TemplateRepository
            import json

            templates = TemplateRepository.list_all(active_only=True)
            for row in templates:
                try:
                    auction_type = row.get("auction_type", "").upper()
                    if not auction_type:
                        continue

                    # Parse zones from JSON
                    zones_data = json.loads(row.get("zones_json", "[]"))
                    zones = []

                    for zd in zones_data:
                        # Convert field definitions
                        fields = []
                        for fd in zd.get("fields", []):
                            # Handle both dict and ZoneField formats
                            if isinstance(fd, dict):
                                field_type_str = fd.get("field_type", "text").lower()
                                # Convert string to FieldType enum by value
                                field_type = FieldType.TEXT  # default
                                for ft in FieldType:
                                    if ft.value == field_type_str:
                                        field_type = ft
                                        break

                                zone_field = ZoneField(
                                    key=fd.get("key", ""),
                                    field_type=field_type,
                                    pattern=fd.get("pattern"),
                                    label=fd.get("label"),
                                    label_patterns=fd.get("label_patterns", []),
                                    extract_strategy=fd.get("extract_strategy", "after_label"),
                                    required=fd.get("required", False),
                                )
                                # Apply default patterns/types for known fields
                                zone_field.apply_defaults()
                                fields.append(zone_field)

                        zone = DocumentZone(
                            name=zd.get("name", ""),
                            x0=float(zd.get("x0", 0)),
                            y0=float(zd.get("y0", 0)),
                            x1=float(zd.get("x1", 100)),
                            y1=float(zd.get("y1", 100)),
                            description=zd.get("description", ""),
                            fields=fields,
                        )
                        zones.append(zone)

                    if zones:
                        template = DocumentTemplate(
                            template_id=row.get("template_id", ""),
                            name=row.get("name", ""),
                            auction_type=auction_type,
                            version=row.get("version", 1),
                            description=row.get("description", ""),
                            zones=zones,
                        )
                        self.templates[auction_type] = template
                        logger.info(f"Loaded template from database: {auction_type} with {len(zones)} zones")

                except Exception as e:
                    logger.warning(f"Failed to parse template {row.get('template_id')}: {e}")

        except Exception as e:
            # Database might not be available during tests
            logger.debug(f"Could not load templates from database: {e}")

    def reload_templates(self):
        """Reload templates from database. Call after user updates templates."""
        self._load_default_templates()
        self._load_database_templates()

    def get_template_from_db(self, auction_type: str) -> Optional[DocumentTemplate]:
        """
        Load template directly from database (bypassing cache).
        This ensures we always use the latest user-configured zones.

        Returns None if no template found in DB - caller should use defaults.
        """
        import json
        try:
            from api.routes.templates import TemplateRepository

            # Get template from database
            row = TemplateRepository.get_by_auction_type(auction_type.upper())
            if not row:
                logger.info(f"No template in DB for {auction_type}, will use default")
                return None

            # Parse zones from JSON
            zones_data = json.loads(row.get("zones_json", "[]"))
            if not zones_data:
                logger.warning(f"Template {row.get('template_id')} has no zones defined")
                return None

            zones = []
            for zd in zones_data:
                fields = []
                for fd in zd.get("fields", []):
                    if isinstance(fd, dict):
                        field_type_str = fd.get("field_type", "text").lower()
                        field_type = FieldType.TEXT
                        for ft in FieldType:
                            if ft.value == field_type_str:
                                field_type = ft
                                break

                        zone_field = ZoneField(
                            key=fd.get("key", ""),
                            field_type=field_type,
                            pattern=fd.get("pattern"),
                            label=fd.get("label"),
                            label_patterns=fd.get("label_patterns", []),
                            extract_strategy=fd.get("extract_strategy", "after_label"),
                            required=fd.get("required", False),
                        )
                        zone_field.apply_defaults()
                        fields.append(zone_field)

                zone = DocumentZone(
                    name=zd.get("name", ""),
                    x0=float(zd.get("x0", 0)),
                    y0=float(zd.get("y0", 0)),
                    x1=float(zd.get("x1", 100)),
                    y1=float(zd.get("y1", 100)),
                    description=zd.get("description", ""),
                    fields=fields,
                )
                zones.append(zone)

            template = DocumentTemplate(
                template_id=row.get("template_id", ""),
                name=row.get("name", ""),
                auction_type=auction_type.upper(),
                version=row.get("version", 1),
                description=row.get("description", ""),
                zones=zones,
            )

            logger.info(f"Loaded template from DB: {template.template_id} with {len(zones)} zones")
            for z in zones:
                logger.info(f"  Zone '{z.name}': ({z.x0:.1f}, {z.y0:.1f}) -> ({z.x1:.1f}, {z.y1:.1f}), fields: {[f.key for f in z.fields]}")

            return template

        except Exception as e:
            logger.error(f"Error loading template from DB for {auction_type}: {e}")
            return None

    def extract_with_logging(self, pdf_path: str, auction_type: str, page_num: int = 0) -> ExtractionResult:
        """
        Extract with detailed logging for debugging.
        Always loads template fresh from DB.
        """
        logger.info(f"=" * 60)
        logger.info(f"ZONE EXTRACTION START: {auction_type}")
        logger.info(f"PDF: {pdf_path}")
        logger.info(f"=" * 60)

        # Try to load from database first
        template = self.get_template_from_db(auction_type)

        if not template:
            # Fall back to cached/default template
            template = self.templates.get(auction_type.upper())
            if template:
                logger.info(f"Using DEFAULT template: {template.template_id}")
            else:
                logger.warning(f"NO TEMPLATE FOUND for {auction_type}!")
                return ExtractionResult(
                    fields={"auction_source": auction_type},
                    zone_texts={},
                    confidence=0.0,
                    template_id="none",
                    warnings=[f"No template found for auction type: {auction_type}"],
                )
        else:
            logger.info(f"Using DATABASE template: {template.template_id}")

        fields = {}
        zone_texts = {}
        warnings = []
        required_found = 0
        required_total = 0

        # Extract from each zone
        for zone in template.zones:
            logger.info(f"-" * 40)
            logger.info(f"Processing zone: {zone.name}")
            logger.info(f"  Coordinates: ({zone.x0:.1f}%, {zone.y0:.1f}%) -> ({zone.x1:.1f}%, {zone.y1:.1f}%)")
            logger.info(f"  Fields to extract: {[f.key for f in zone.fields]}")

            zone_text = self.extract_zone_text(pdf_path, zone, page_num)
            zone_texts[zone.name] = zone_text

            if zone_text:
                logger.info(f"  Extracted text ({len(zone_text)} chars):")
                for line in zone_text.split('\n')[:5]:
                    logger.info(f"    | {line[:80]}")
                if len(zone_text.split('\n')) > 5:
                    logger.info(f"    | ... ({len(zone_text.split(chr(10)))-5} more lines)")
            else:
                logger.warning(f"  NO TEXT extracted from zone {zone.name}!")
                warnings.append(f"Empty text in zone: {zone.name}")
                continue

            # Parse fields from zone
            for field_def in zone.fields:
                if field_def.required:
                    required_total += 1

                # Special handling for city/state/zip
                if field_def.key in ("pickup_city", "pickup_state", "pickup_zip"):
                    if "pickup_city" not in fields:
                        city, state, zip_code = self._parse_city_state_zip(zone_text)
                        if city:
                            fields["pickup_city"] = city
                            required_found += 1
                            logger.info(f"  Found pickup_city: {city}")
                        if state:
                            fields["pickup_state"] = state
                            required_found += 1
                            logger.info(f"  Found pickup_state: {state}")
                        if zip_code:
                            fields["pickup_zip"] = zip_code
                            required_found += 1
                            logger.info(f"  Found pickup_zip: {zip_code}")
                    continue

                value = self.parse_field_from_text(zone_text, field_def)

                if value:
                    fields[field_def.key] = value
                    if field_def.required:
                        required_found += 1
                    logger.info(f"  Found {field_def.key}: {value}")
                elif field_def.required:
                    warnings.append(f"Required field not found: {field_def.key} in zone {zone.name}")
                    logger.warning(f"  MISSING required field: {field_def.key}")

        # Calculate confidence
        confidence = required_found / required_total if required_total > 0 else 0.5

        # Add auction source
        fields["auction_source"] = auction_type
        fields["pickup_location_type"] = "AUCTION"

        # MANHEIM Page 4 extraction
        if auction_type.upper() == "MANHEIM":
            logger.info("Attempting Manheim Page 4 pickup extraction")
            page4_pickup = self._extract_manheim_page4_pickup(pdf_path)
            if page4_pickup:
                for key, value in page4_pickup.items():
                    if value and key.startswith("pickup_"):
                        fields[key] = value
                        logger.info(f"Page 4 pickup: {key}={value}")

        logger.info(f"=" * 60)
        logger.info(f"EXTRACTION COMPLETE: {len(fields)} fields, confidence={confidence:.2f}")
        logger.info(f"Fields: {list(fields.keys())}")
        if warnings:
            logger.info(f"Warnings: {warnings}")
        logger.info(f"=" * 60)

        return ExtractionResult(
            fields=fields,
            zone_texts=zone_texts,
            confidence=confidence,
            template_id=template.template_id,
            warnings=warnings,
        )

    def _create_copart_template(self) -> DocumentTemplate:
        """
        Create template for Copart invoices.

        Copart layout (analyzed from actual PDFs - 612x792 pts):
        ┌────────────────┬─────────────────────┬────────────────┐
        │    MEMBER      │ PHYSICAL ADDRESS    │    SELLER      │
        │   (0-28.6%)    │   OF LOT (28.6-58.8%)│  (58.8-100%)  │
        │                │   = PICKUP LOCATION │                │
        └────────────────┴─────────────────────┴────────────────┘
        Header section: Y = 7.6% - 16.4%

        Column boundaries (from PDF coordinate analysis):
        - MEMBER: starts at X=6% (36.75 pts)
        - PHYSICAL ADDRESS: starts at X=29.4% (179.74 pts)
        - SELLER: starts at X=59.7% (365.21 pts)
        """
        return DocumentTemplate(
            template_id="copart_invoice_v1",
            name="Copart Invoice",
            auction_type="COPART",
            version=2,  # Updated version with correct coordinates
            description="Standard Copart invoice with 3-column header layout",
            zones=[
                # Zone 1: Member/Buyer Info (LEFT column) - 0% to 28.6%
                DocumentZone(
                    name="member_info",
                    x0=0,
                    y0=7.5,
                    x1=28.6,
                    y1=20,
                    description="Buyer/Member information (left column)",
                    fields=[
                        ZoneField(
                            key="buyer_id",
                            field_type=FieldType.TEXT,
                            pattern=r"(?:Member|MEMBER)[:\s#]*(\d+)",
                            label="Member",
                        ),
                        ZoneField(key="buyer_name", field_type=FieldType.TEXT),
                        ZoneField(key="buyer_address", field_type=FieldType.ADDRESS),
                    ],
                ),
                # Zone 2: Physical Address of Lot (CENTER column) - PICKUP LOCATION
                # CRITICAL: This is the correct zone for pickup address (28.6% to 58.8%)
                DocumentZone(
                    name="lot_address",
                    x0=28.6,
                    y0=7.5,
                    x1=58.8,
                    y1=20,
                    description="Physical address of lot - PICKUP LOCATION (center column)",
                    fields=[
                        ZoneField(key="pickup_name", field_type=FieldType.TEXT, label="Copart"),
                        ZoneField(
                            key="pickup_address", field_type=FieldType.ADDRESS, required=True
                        ),
                        ZoneField(key="pickup_city", field_type=FieldType.TEXT, required=True),
                        ZoneField(key="pickup_state", field_type=FieldType.TEXT, required=True),
                        ZoneField(key="pickup_zip", field_type=FieldType.TEXT, required=True),
                    ],
                ),
                # Zone 3: Seller Info (RIGHT column) - NOT pickup!
                DocumentZone(
                    name="seller_info",
                    x0=58.8,
                    y0=7.5,
                    x1=100,
                    y1=20,
                    description="Seller information (right column) - NOT pickup location",
                    fields=[
                        ZoneField(key="seller_id", field_type=FieldType.TEXT, pattern=r"(\d{6,})"),
                        ZoneField(key="seller_name", field_type=FieldType.TEXT),
                    ],
                ),
                # Zone 4: Vehicle Information (full width, middle section)
                DocumentZone(
                    name="vehicle_info",
                    x0=0,
                    y0=18,
                    x1=100,
                    y1=50,
                    description="Vehicle details (VIN, Year, Make, Model, Lot)",
                    fields=[
                        ZoneField(
                            key="vehicle_vin",
                            field_type=FieldType.VIN,
                            required=True,
                            pattern=r"\b([A-HJ-NPR-Z0-9]{17})\b",
                        ),
                        ZoneField(
                            key="vehicle_year",
                            field_type=FieldType.NUMBER,
                            pattern=r"\b(19[89]\d|20[0-2]\d)\b",
                        ),
                        ZoneField(key="vehicle_make", field_type=FieldType.TEXT),
                        ZoneField(key="vehicle_model", field_type=FieldType.TEXT),
                        ZoneField(
                            key="vehicle_lot",
                            field_type=FieldType.TEXT,
                            pattern=r"Lot\s*#?\s*[:\s]*(\d+)",
                            label="Lot",
                        ),
                    ],
                ),
                # Zone 5: Financial Information (bottom section)
                DocumentZone(
                    name="financial_info",
                    x0=0,
                    y0=45,
                    x1=100,
                    y1=95,
                    description="Sale price, fees, totals",
                    fields=[
                        ZoneField(
                            key="sale_price",
                            field_type=FieldType.CURRENCY,
                            pattern=r"Sale\s*Price[:\s]*\$?([\d,]+\.?\d*)",
                        ),
                        ZoneField(
                            key="total_amount",
                            field_type=FieldType.CURRENCY,
                            pattern=r"(?:Net\s*Due|Total\s*Due|Total)[:\s]*\$?([\d,]+\.?\d*)",
                        ),
                        ZoneField(
                            key="sale_date",
                            field_type=FieldType.DATE,
                            pattern=r"Sale\s*Date[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})",
                        ),
                    ],
                ),
            ],
        )

    def _create_iaa_template(self) -> DocumentTemplate:
        """
        Create template for IAA Buyer Receipt.

        IAA layout (analyzed from actual PDFs - 612x792 pts):
        ┌──────────────────────────────────────────┐
        │            HEADER (0-12.5%)              │
        │     "Buyer Receipt" + Receipt Info       │
        ├────────────────────┬─────────────────────┤
        │   PICKUP LOCATION  │    BUYER INFO       │
        │   (0-42% X)        │    (42-100% X)      │
        │   (15-28% Y)       │    (17-30% Y)       │
        ├────────────────────┴─────────────────────┤
        │   VEHICLE DATA ROW (32-38% Y)            │
        │   Stock | Year | Make | Model | VIN     │
        ├────────────────────┬─────────────────────┤
        │   INVOICE TO       │  FINANCIAL CHARGES  │
        │   (0-35% X)        │  (35-100% X)        │
        │   (36-55% Y)       │                     │
        └────────────────────┴─────────────────────┘

        Key markers:
        - "Pick-Up Location:" at Y=16.1%
        - "Buyer #" at Y=18.9%, X=61%
        - Vehicle row headers at Y=32.8%
        - "Bid Amount" at Y=39%, X=66%
        """
        return DocumentTemplate(
            template_id="iaa_buyer_receipt_v1",
            name="IAA Buyer Receipt",
            auction_type="IAA",
            version=2,  # Updated with correct coordinates
            description="Standard IAA buyer receipt layout",
            zones=[
                # Header
                DocumentZone(
                    name="header_info",
                    x0=0,
                    y0=0,
                    x1=100,
                    y1=12.5,
                    description="Header with IAA branding and receipt info",
                    fields=[
                        ZoneField(
                            key="reference_id",
                            field_type=FieldType.TEXT,
                            pattern=r"Stock\s*#?\s*[:\s]*(\d+)",
                        ),
                    ],
                ),
                # Pickup Location (LEFT side, 0-42% X, 15-28% Y)
                DocumentZone(
                    name="pickup_location",
                    x0=0,
                    y0=15,
                    x1=42,
                    y1=32,
                    description="Pick-Up Location section (left column)",
                    fields=[
                        ZoneField(
                            key="pickup_name",
                            field_type=FieldType.TEXT,
                            pattern=r"(?:IAA\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*,",
                        ),
                        ZoneField(
                            key="pickup_address", field_type=FieldType.ADDRESS, required=True
                        ),
                        ZoneField(key="pickup_city", field_type=FieldType.TEXT, required=True),
                        ZoneField(key="pickup_state", field_type=FieldType.TEXT, required=True),
                        ZoneField(key="pickup_zip", field_type=FieldType.TEXT, required=True),
                        ZoneField(
                            key="pickup_phone",
                            field_type=FieldType.PHONE,
                            pattern=r"(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})",
                        ),
                    ],
                ),
                # Buyer Info (RIGHT side, 42-100% X, 17-30% Y)
                DocumentZone(
                    name="buyer_info",
                    x0=42,
                    y0=15,
                    x1=100,
                    y1=32,
                    description="Buyer/Bidder information (right column)",
                    fields=[
                        ZoneField(
                            key="buyer_id",
                            field_type=FieldType.TEXT,
                            pattern=r"Buyer\s*#[:\s]*(\d+)",
                        ),
                        ZoneField(
                            key="buyer_name",
                            field_type=FieldType.TEXT,
                            pattern=r"Buyer\s*Name[:\s]*([^\n]+)",
                        ),
                        ZoneField(
                            key="sale_date",
                            field_type=FieldType.DATE,
                            pattern=r"Sale\s*Date[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})",
                        ),
                    ],
                ),
                # Vehicle Data Row (full width, 32-38% Y)
                DocumentZone(
                    name="vehicle_info",
                    x0=0,
                    y0=32,
                    x1=100,
                    y1=42,
                    description="Vehicle data row (Stock, Year, Make, Model, VIN)",
                    fields=[
                        ZoneField(
                            key="vehicle_vin",
                            field_type=FieldType.VIN,
                            required=True,
                            pattern=r"\b([A-HJ-NPR-Z0-9]{17})\b",
                        ),
                        ZoneField(
                            key="vehicle_year",
                            field_type=FieldType.NUMBER,
                            pattern=r"\b(19[89]\d|20[0-2]\d)\b",
                        ),
                        ZoneField(key="vehicle_make", field_type=FieldType.TEXT),
                        ZoneField(key="vehicle_model", field_type=FieldType.TEXT),
                        ZoneField(
                            key="vehicle_lot", field_type=FieldType.TEXT, pattern=r"(\d{8})"
                        ),  # Stock numbers are typically 8 digits
                    ],
                ),
                # Financial Info (right side, 35-100% X, 36-55% Y)
                DocumentZone(
                    name="financial_info",
                    x0=35,
                    y0=36,
                    x1=100,
                    y1=60,
                    description="Financial charges (Bid Amount, Fees, Total)",
                    fields=[
                        ZoneField(
                            key="bid_amount",
                            field_type=FieldType.CURRENCY,
                            pattern=r"Bid\s*Amount[:\s]*\$?([\d,]+\.?\d*)",
                        ),
                        ZoneField(
                            key="total_amount",
                            field_type=FieldType.CURRENCY,
                            pattern=r"(?:Total|Amount\s*Due)[:\s]*\$?([\d,]+\.?\d*)",
                        ),
                    ],
                ),
            ],
        )

    def _create_manheim_template(self) -> DocumentTemplate:
        """
        Create template for Manheim documents.

        IMPORTANT: Manheim documents typically have 4 pages:
        - Page 1: Bill of Sale (Landscape 792x612) - has vehicle info and sale price
        - Page 2: Invoice (Landscape 792x612) - has fees and total
        - Page 3: Payment Receipt (Portrait 612x792)
        - Page 4: Vehicle Release (Portrait 612x792) - BEST source for pickup location!

        The pickup location on Page 1 is the AUCTION address (e.g., Atlanta, GA)
        The pickup location on Page 4 is the ACTUAL pickup location (e.g., Manheim Portland, OR)

        We use multi-page extraction to get the best data from each page.
        """
        return DocumentTemplate(
            template_id="manheim_invoice_v1",
            name="Manheim Invoice",
            auction_type="MANHEIM",
            version=2,  # Updated with multi-page support
            description="Multi-page Manheim document (Bill of Sale + Vehicle Release)",
            zones=[
                # Page 1: Bill of Sale (Landscape orientation - 792x612)
                # Header with "BILL OF SALE"
                DocumentZone(
                    name="header",
                    x0=0,
                    y0=0,
                    x1=100,
                    y1=12,
                    description="Bill of Sale header (Page 1)",
                    fields=[
                        ZoneField(
                            key="document_type",
                            field_type=FieldType.TEXT,
                            pattern=r"(BILL\s+OF\s+SALE)",
                        ),
                    ],
                ),
                # Page 1: Vehicle Info (middle section of Bill of Sale)
                # "Vehicle Information" section contains VIN, Year, Make, Model
                DocumentZone(
                    name="vehicle_info",
                    x0=0,
                    y0=38,
                    x1=50,
                    y1=65,
                    description="Vehicle Information section (Page 1)",
                    fields=[
                        ZoneField(
                            key="vehicle_vin",
                            field_type=FieldType.VIN,
                            required=True,
                            pattern=r"\b([A-HJ-NPR-Z0-9]{17})\b",
                        ),
                        ZoneField(
                            key="vehicle_year",
                            field_type=FieldType.NUMBER,
                            pattern=r"\b(19[89]\d|20[0-2]\d)\b",
                        ),
                        ZoneField(key="vehicle_make", field_type=FieldType.TEXT),
                        ZoneField(key="vehicle_model", field_type=FieldType.TEXT),
                    ],
                ),
                # Page 1: Sale Price (center-right area)
                DocumentZone(
                    name="sale_price_section",
                    x0=35,
                    y0=17,
                    x1=75,
                    y1=35,
                    description="Sale price section (Page 1)",
                    fields=[
                        ZoneField(
                            key="sale_date",
                            field_type=FieldType.DATE,
                            pattern=r"Sale\s*Date[:\s]*(\d{1,2}-[A-Z]{3}-\d{4})",
                        ),
                        ZoneField(
                            key="sale_price",
                            field_type=FieldType.CURRENCY,
                            pattern=r"(?:Final\s+)?Sale\s*Price[:\s]*\$?\s*([\d,]+\.?\d*)",
                        ),
                        ZoneField(
                            key="total_amount",
                            field_type=FieldType.CURRENCY,
                            pattern=r"Final\s+Sale\s+Price[:\s]*\$?\s*([\d,]+\.?\d*)",
                        ),
                    ],
                ),
                # Page 1: Auction location (left side) - NOT the real pickup!
                # This is the auction house address (e.g., Atlanta, GA)
                DocumentZone(
                    name="auction_location",
                    x0=0,
                    y0=12,
                    x1=35,
                    y1=35,
                    description="Auction location (NOT actual pickup - Page 1)",
                    fields=[
                        # We extract this for reference but DON'T use it as pickup
                        ZoneField(key="auction_name", field_type=FieldType.TEXT),
                    ],
                ),
            ],
        )

    def register_template(self, template: DocumentTemplate):
        """Register a new template or update existing"""
        self.templates[template.auction_type] = template
        logger.info(f"Registered template: {template.template_id} for {template.auction_type}")

    def get_template(self, auction_type: str) -> Optional[DocumentTemplate]:
        """Get template for auction type"""
        return self.templates.get(auction_type)

    def extract_zone_text(self, pdf_path: str, zone: DocumentZone, page_num: int = 0) -> str:
        """
        Extract text from a specific zone on a PDF page.

        Uses pdfplumber's crop functionality to isolate the zone,
        then extracts text with layout preservation.
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                if page_num >= len(pdf.pages):
                    logger.warning(f"Page {page_num} not found in PDF")
                    return ""

                page = pdf.pages[page_num]
                bbox = zone.to_bbox(page.width, page.height)

                logger.info(
                    f"Extracting zone '{zone.name}' from bbox {bbox} (page size: {page.width}x{page.height})"
                )

                # Crop the page to the zone
                cropped = page.crop(bbox)

                # Extract text with layout preservation
                text = cropped.extract_text(layout=True) or ""

                logger.info(f"Zone '{zone.name}' extracted {len(text)} chars: {text[:200]}...")
                return text

        except Exception as e:
            logger.error(f"Error extracting zone '{zone.name}': {e}")
            import traceback

            logger.error(traceback.format_exc())
            return ""

    def parse_field_from_text(self, text: str, field_def: ZoneField) -> Optional[str]:
        """
        Parse a specific field from zone text.

        Strategies (in order of priority):
        1. If pattern is defined, use regex
        2. If label_patterns array is defined, try each pattern to find value after label
        3. If single label is defined, look for "Label: Value" format
        4. For ADDRESS type, use special address parsing
        5. For CITY_STATE_ZIP, extract city/state/zip pattern
        """
        if not text:
            return None

        text_upper = text.upper()

        # Strategy 1: Use regex pattern if defined
        if field_def.pattern:
            match = re.search(field_def.pattern, text, re.IGNORECASE)
            if match:
                try:
                    # Try to get group 1 (capturing group)
                    return match.group(1).strip()
                except IndexError:
                    # Pattern has no capturing group, return full match
                    return match.group(0).strip()

        # Strategy 2: Try each label_pattern (learned from training)
        if field_def.label_patterns:
            for label_pattern in field_def.label_patterns:
                try:
                    # Build pattern to extract value after label
                    # Handle different extract strategies
                    if field_def.extract_strategy == "regex":
                        # Use label_pattern directly as regex
                        match = re.search(label_pattern, text, re.IGNORECASE)
                        if match:
                            try:
                                return match.group(1).strip()
                            except IndexError:
                                return match.group(0).strip()
                    else:
                        # Default: after_label - look for value after label
                        # Pattern: label followed by optional colon/spaces and capture value
                        value_pattern = rf"{label_pattern}[:\s]*([^\n]+)"
                        match = re.search(value_pattern, text, re.IGNORECASE)
                        if match:
                            value = match.group(1).strip()
                            # Clean up common trailing garbage
                            value = re.sub(r"\s{2,}.*$", "", value)  # Stop at multiple spaces
                            if value and len(value) >= 2:
                                logger.debug(f"Found {field_def.key} via label_pattern '{label_pattern}': {value}")
                                return value
                except re.error as e:
                    logger.warning(f"Invalid regex in label_pattern '{label_pattern}': {e}")
                    continue

        # Strategy 3: Look for single label
        if field_def.label:
            label_pattern = rf"{re.escape(field_def.label)}[:\s]*([^\n]+)"
            match = re.search(label_pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        # Strategy 4: Type-specific parsing
        if field_def.field_type == FieldType.VIN:
            vin_match = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", text_upper)
            if vin_match:
                return vin_match.group(1)

        elif field_def.field_type == FieldType.ADDRESS:
            return self._parse_address_from_text(text)

        elif field_def.field_type == FieldType.CURRENCY:
            currency_match = re.search(r"\$?([\d,]+\.?\d*)", text)
            if currency_match:
                return currency_match.group(1).replace(",", "")

        elif field_def.field_type == FieldType.PHONE:
            phone_match = re.search(r"(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})", text)
            if phone_match:
                return phone_match.group(1)

        return None

    def _parse_address_from_text(self, text: str) -> Optional[str]:
        """
        Parse street address from text.

        Looks for patterns like:
        - "1234 N. MAIN STREET"
        - "4810 N. LAMB BLVD"
        - "123 US ROUTE 1"
        """
        # Street address pattern: number + street name + optional suffix
        street_types = r"(?:ROAD|RD|STREET|ST|AVENUE|AVE|DRIVE|DR|HIGHWAY|HWY|BLVD|BOULEVARD|WAY|LANE|LN|COURT|CT|PARKWAY|PKWY|ROUTE|RT)"

        # Pattern 1: Standard street address
        pattern1 = rf"(\d{{1,5}}\s+[A-Z0-9\.\s]+?{street_types})"
        match = re.search(pattern1, text.upper())
        if match:
            addr = match.group(1).strip()
            # Clean up multiple spaces
            addr = re.sub(r"\s+", " ", addr)
            return addr.title()

        # Pattern 2: US Route/Highway
        pattern2 = r"(\d+\s+(?:US\s+)?(?:ROUTE|RT|HWY|HIGHWAY)\s+\d+)"
        match = re.search(pattern2, text.upper())
        if match:
            return match.group(1).title()

        return None

    def _parse_city_state_zip(
        self, text: str
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Parse city, state, ZIP from text"""
        # Normalize whitespace - replace newlines with spaces
        text_normalized = re.sub(r"[\n\r]+", " ", text)
        text_normalized = re.sub(r"\s+", " ", text_normalized)
        text_upper = text_normalized.upper()

        # Pattern 1: CITY STATE ZIP (standard format)
        # Match city name (1-3 words), state code, and ZIP
        pattern1 = rf"([A-Z][A-Z]+(?:\s+[A-Z]+)*?)\s+({self.US_STATES})\s+(\d{{5}}(?:-\d{{4}})?)"
        match = re.search(pattern1, text_upper)

        if match:
            city = match.group(1).strip()
            state = match.group(2).upper()
            zip_code = match.group(3)

            # Clean up city - remove leading/trailing directionals and numbers
            city = re.sub(r"^(?:NORTH|SOUTH|EAST|WEST|N|S|E|W)\s+", "", city)
            city = re.sub(r"\s+(?:NORTH|SOUTH|EAST|WEST|N|S|E|W)$", "", city)
            city = re.sub(r"\s+\d+$", "", city)  # Remove trailing numbers
            city = re.sub(r"^\d+\s+", "", city)  # Remove leading numbers
            city = city.strip().title()

            if len(city) >= 2:
                return city, state, zip_code

        # Pattern 2: Look for state-zip pattern and work backwards for city
        pattern2 = rf"({self.US_STATES})\s+(\d{{5}}(?:-\d{{4}})?)"
        match = re.search(pattern2, text_upper)

        if match:
            state = match.group(1).upper()
            zip_code = match.group(2)

            # Find text before state - look for city name
            before_state = text_upper[: match.start()].strip()
            # Get last word(s) that look like a city name (letters only)
            city_match = re.search(r"([A-Z][A-Z]+(?:\s+[A-Z]+)*)$", before_state)
            if city_match:
                city = city_match.group(1).strip()
                # Clean up - remove directionals
                city = re.sub(r"^(?:NORTH|SOUTH|EAST|WEST|N|S|E|W)\s+", "", city)
                city = re.sub(r"\s+(?:NORTH|SOUTH|EAST|WEST|N|S|E|W)$", "", city)
                city = city.strip().title()
                if len(city) >= 2:
                    return city, state, zip_code

        return None, None, None

    def _extract_manheim_page4_pickup(self, pdf_path: str) -> dict[str, str]:
        """
        Extract pickup location from Manheim Page 4 (Vehicle Release).

        Page 4 contains the ACTUAL pickup location (e.g., Manheim Portland)
        while Page 1 contains the auction house address (e.g., Atlanta GA).

        Page 4 Layout (Portrait 612x792):
        - "Pickup Location" section at Y=40-60%
        - Contains: Name, Address, City, State, ZIP, Phone

        Returns dict with pickup_name, pickup_address, pickup_city, pickup_state, pickup_zip, pickup_phone
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) < 4:
                    logger.info("Manheim PDF has fewer than 4 pages, skipping Page 4 extraction")
                    return {}

                page = pdf.pages[3]  # Page 4 (0-indexed)
                page_width = page.width
                page_height = page.height

                logger.info(
                    f"Extracting Manheim Page 4 pickup (page size: {page_width}x{page_height})"
                )

                # Pickup Location zone on Page 4
                # Based on analysis: X=0-100%, Y=40-60%
                pickup_bbox = (0, page_height * 0.40, page_width, page_height * 0.60)
                cropped = page.crop(pickup_bbox)
                text = cropped.extract_text(layout=True) or ""

                logger.info(f"Page 4 pickup zone text: {text[:300]}...")

                if not text:
                    return {}

                result = {}

                # Extract Manheim location name (e.g., "Manheim Portland")
                name_match = re.search(
                    r"(Manheim\s+[A-Za-z\s]+?)(?:\s*\n|\s{2,})", text, re.IGNORECASE
                )
                if name_match:
                    result["pickup_name"] = name_match.group(1).strip()

                # Extract street address
                addr_match = re.search(
                    r"(\d+\s+[A-Z0-9\.\s]+(?:ROAD|RD|STREET|ST|AVENUE|AVE|DRIVE|DR|HIGHWAY|HWY|BLVD|BOULEVARD|WAY|LANE|LN))",
                    text.upper(),
                )
                if addr_match:
                    result["pickup_address"] = addr_match.group(1).strip().title()

                # Extract city, state, zip
                csz_pattern = rf"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*,?\s*({self.US_STATES})\s+(\d{{5}}(?:-\d{{4}})?)"
                csz_match = re.search(csz_pattern, text.upper())
                if csz_match:
                    result["pickup_city"] = csz_match.group(1).strip().title()
                    result["pickup_state"] = csz_match.group(2).upper()
                    result["pickup_zip"] = csz_match.group(3)

                # Extract phone
                phone_match = re.search(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", text)
                if phone_match:
                    result["pickup_phone"] = phone_match.group(0)

                logger.info(f"Page 4 extracted pickup: {result}")
                return result

        except Exception as e:
            logger.error(f"Error extracting Manheim Page 4: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {}

    def extract(self, pdf_path: str, auction_type: str, page_num: int = 0) -> ExtractionResult:
        """
        Extract all fields from a PDF using zone-based template.

        Args:
            pdf_path: Path to PDF file
            auction_type: Type of auction (COPART, IAA, MANHEIM)
            page_num: Page number to extract from (default: 0)

        Returns:
            ExtractionResult with extracted fields and metadata
        """
        logger.info(f"Starting zone extraction for {auction_type} from {pdf_path}")

        template = self.templates.get(auction_type)
        if not template:
            logger.warning(f"No template found for auction type: {auction_type}")
            return ExtractionResult(
                fields={},
                zone_texts={},
                confidence=0.0,
                template_id="none",
                warnings=[f"No template found for auction type: {auction_type}"],
            )

        fields = {}
        zone_texts = {}
        warnings = []
        required_found = 0
        required_total = 0

        # Extract from each zone
        for zone in template.zones:
            zone_text = self.extract_zone_text(pdf_path, zone, page_num)
            zone_texts[zone.name] = zone_text

            if not zone_text:
                warnings.append(f"Empty text in zone: {zone.name}")
                continue

            # Parse fields from zone
            for field_def in zone.fields:
                if field_def.required:
                    required_total += 1

                # Special handling for city/state/zip
                if field_def.key in ("pickup_city", "pickup_state", "pickup_zip"):
                    if "pickup_city" not in fields:
                        city, state, zip_code = self._parse_city_state_zip(zone_text)
                        if city:
                            fields["pickup_city"] = city
                            required_found += 1
                        if state:
                            fields["pickup_state"] = state
                            required_found += 1
                        if zip_code:
                            fields["pickup_zip"] = zip_code
                            required_found += 1
                    continue

                value = self.parse_field_from_text(zone_text, field_def)

                if value:
                    fields[field_def.key] = value
                    if field_def.required:
                        required_found += 1
                elif field_def.required:
                    warnings.append(
                        f"Required field not found: {field_def.key} in zone {zone.name}"
                    )

        # Calculate confidence based on required fields found
        confidence = required_found / required_total if required_total > 0 else 0.5

        # Add auction source
        fields["auction_source"] = auction_type
        fields["pickup_location_type"] = "AUCTION"

        # MANHEIM-specific: Extract pickup from Page 4 (Vehicle Release)
        if auction_type == "MANHEIM":
            logger.info("Attempting Manheim Page 4 pickup extraction")
            page4_pickup = self._extract_manheim_page4_pickup(pdf_path)
            if page4_pickup:
                # Page 4 pickup takes priority over Page 1 auction address
                for key, value in page4_pickup.items():
                    if value and key.startswith("pickup_"):
                        fields[key] = value
                        logger.info(f"Using Page 4 pickup: {key}={value}")

        logger.info(f"Zone extraction complete: {len(fields)} fields, confidence={confidence:.2f}")

        return ExtractionResult(
            fields=fields,
            zone_texts=zone_texts,
            confidence=confidence,
            template_id=template.template_id,
            warnings=warnings,
        )

    def visualize_zones(self, pdf_path: str, auction_type: str, output_path: str = None):
        """
        Create a visualization of zones on the PDF for debugging.

        Draws rectangles around each zone with labels.
        """
        template = self.templates.get(auction_type)
        if not template:
            logger.error(f"No template for {auction_type}")
            return None

        try:
            with pdfplumber.open(pdf_path) as pdf:
                page = pdf.pages[0]

                # Create image with zones drawn
                im = page.to_image(resolution=150)

                # Define colors for different zones
                colors = [
                    (255, 0, 0, 100),  # Red
                    (0, 255, 0, 100),  # Green
                    (0, 0, 255, 100),  # Blue
                    (255, 255, 0, 100),  # Yellow
                    (255, 0, 255, 100),  # Magenta
                    (0, 255, 255, 100),  # Cyan
                ]

                for i, zone in enumerate(template.zones):
                    bbox = zone.to_bbox(page.width, page.height)
                    color = colors[i % len(colors)]

                    # Draw rectangle
                    im.draw_rect(bbox, fill=color[:3] + (50,), stroke=color[:3])

                    # Add label (using annotate or similar)
                    # Note: pdfplumber's image doesn't have direct text annotation
                    # Would need PIL/Pillow for that

                if output_path:
                    im.save(output_path)
                    logger.info(f"Zone visualization saved to {output_path}")

                return im

        except Exception as e:
            logger.error(f"Error visualizing zones: {e}")
            return None


# Singleton instance
_zone_extractor = None


def get_zone_extractor() -> ZoneExtractor:
    """Get singleton ZoneExtractor instance"""
    global _zone_extractor
    if _zone_extractor is None:
        _zone_extractor = ZoneExtractor()
    return _zone_extractor
