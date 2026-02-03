"""
Database Models for ML-Ready MVP

This module extends the database schema to support:
- AuctionType management (including custom types)
- Document upload with train/test split
- Extraction runs with model versioning
- Review workflow with corrections
- Training examples and model versioning
- Export jobs to Central Dispatch

Schema Version: 4
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from api.database import get_connection

# =============================================================================
# ENUMS
# =============================================================================


class DatasetSplit(str, Enum):
    """Dataset split types."""

    TRAIN = "train"
    TEST = "test"


class ExtractorKind(str, Enum):
    """Type of extractor used."""

    RULE = "rule"  # Rule-based pattern matching
    ML = "ml"  # ML model inference


class RunStatus(str, Enum):
    """Extraction run status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class ReviewStatus(str, Enum):
    """Review item status."""

    PENDING = "pending"
    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class ModelStatus(str, Enum):
    """Model version status."""

    TRAINING = "training"
    READY = "ready"
    ACTIVE = "active"
    ARCHIVED = "archived"
    FAILED = "failed"


class JobStatus(str, Enum):
    """Training/Export job status."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportStatus(str, Enum):
    """Export job status."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    SUCCESS = "success"
    FAILED = "failed"
    VALIDATION_ERROR = "validation_error"


class TextSourceType(str, Enum):
    """Source of text extraction."""

    NATIVE = "native"  # Text layer from PDF
    OCR = "ocr"  # OCR processed
    HYBRID = "hybrid"  # Mix of native and OCR


class FieldValueSource(str, Enum):
    """Source of field value (precedence order high to low)."""

    USER_OVERRIDE = "user_override"  # Manual user correction
    WAREHOUSE_CONST = "warehouse_const"  # Warehouse-specific constant
    AUCTION_CONST = "auction_const"  # Auction profile constant
    EXTRACTED = "extracted"  # Extracted from document
    DEFAULT = "default"  # Default value from field mapping


# =============================================================================
# SCHEMA INITIALIZATION
# =============================================================================


def init_extended_schema():
    """Initialize extended database schema for ML-ready MVP."""
    with get_connection() as conn:
        # -----------------------------------------------------------------
        # AUCTION TYPES
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auction_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                code TEXT NOT NULL UNIQUE,
                parent_id INTEGER,
                is_base BOOLEAN DEFAULT FALSE,
                is_custom BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                description TEXT,
                extractor_config TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (parent_id) REFERENCES auction_types(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_auction_types_code ON auction_types(code)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_auction_types_parent ON auction_types(parent_id)
        """)

        # -----------------------------------------------------------------
        # DOCUMENTS (uploaded files)
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL UNIQUE,
                auction_type_id INTEGER NOT NULL,
                dataset_split TEXT NOT NULL CHECK (dataset_split IN ('train', 'test')),
                filename TEXT NOT NULL,
                file_path TEXT,
                file_size INTEGER,
                sha256 TEXT,
                mime_type TEXT DEFAULT 'application/pdf',
                page_count INTEGER,
                has_ocr BOOLEAN DEFAULT FALSE,
                raw_text TEXT,
                source TEXT DEFAULT 'upload' CHECK (source IN ('upload', 'email', 'batch', 'test_lab')),
                is_test BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_by TEXT,
                FOREIGN KEY (auction_type_id) REFERENCES auction_types(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_auction_type ON documents(auction_type_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_split ON documents(dataset_split)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256)
        """)

        # -----------------------------------------------------------------
        # EXTRACTION RUNS
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL UNIQUE,
                document_id INTEGER NOT NULL,
                auction_type_id INTEGER NOT NULL,
                extractor_kind TEXT DEFAULT 'rule' CHECK (extractor_kind IN ('rule', 'ml')),
                model_version_id INTEGER,
                status TEXT DEFAULT 'pending',
                extraction_score REAL,
                outputs_json TEXT,
                errors_json TEXT,
                metrics_json TEXT,
                field_sources_json TEXT,
                processing_time_ms INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id),
                FOREIGN KEY (auction_type_id) REFERENCES auction_types(id),
                FOREIGN KEY (model_version_id) REFERENCES model_versions(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_extraction_runs_document ON extraction_runs(document_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_extraction_runs_auction_type ON extraction_runs(auction_type_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_extraction_runs_status ON extraction_runs(status)
        """)

        # -----------------------------------------------------------------
        # FIELD MAPPINGS (per auction type)
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS field_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_type_id INTEGER NOT NULL,
                source_key TEXT NOT NULL,
                internal_key TEXT NOT NULL,
                cd_key TEXT,
                transform TEXT,
                is_required BOOLEAN DEFAULT FALSE,
                default_value TEXT,
                validation_regex TEXT,
                description TEXT,
                display_order INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (auction_type_id) REFERENCES auction_types(id),
                UNIQUE(auction_type_id, source_key)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_field_mappings_auction_type ON field_mappings(auction_type_id)
        """)

        # -----------------------------------------------------------------
        # REVIEW ITEMS (corrections and approvals)
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                source_key TEXT NOT NULL,
                internal_key TEXT,
                cd_key TEXT,
                predicted_value TEXT,
                corrected_value TEXT,
                is_match_ok BOOLEAN DEFAULT FALSE,
                export_field BOOLEAN DEFAULT TRUE,
                confidence REAL,
                status TEXT DEFAULT 'pending',
                reviewer TEXT,
                review_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES extraction_runs(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_review_items_run ON review_items(run_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_review_items_status ON review_items(status)
        """)

        # -----------------------------------------------------------------
        # TRAINING EXAMPLES (generated from reviews)
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS training_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL UNIQUE,
                auction_type_id INTEGER NOT NULL,
                document_id INTEGER,
                input_text TEXT NOT NULL,
                input_chunks_json TEXT,
                labels_json TEXT NOT NULL,
                source_review_item_ids TEXT,
                quality_score REAL,
                is_validated BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (auction_type_id) REFERENCES auction_types(id),
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_examples_auction_type ON training_examples(auction_type_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_examples_validated ON training_examples(is_validated)
        """)

        # -----------------------------------------------------------------
        # MODEL VERSIONS
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL UNIQUE,
                auction_type_id INTEGER NOT NULL,
                version_tag TEXT NOT NULL,
                base_model TEXT NOT NULL,
                adapter_type TEXT DEFAULT 'lora',
                adapter_uri TEXT,
                config_json TEXT,
                metrics_json TEXT,
                status TEXT DEFAULT 'training',
                training_examples_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                trained_at TIMESTAMP,
                promoted_at TIMESTAMP,
                FOREIGN KEY (auction_type_id) REFERENCES auction_types(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_model_versions_auction_type ON model_versions(auction_type_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_model_versions_status ON model_versions(status)
        """)

        # -----------------------------------------------------------------
        # TRAINING JOBS
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS training_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL UNIQUE,
                auction_type_id INTEGER NOT NULL,
                model_version_id INTEGER NOT NULL,
                status TEXT DEFAULT 'queued',
                progress REAL DEFAULT 0.0,
                current_step INTEGER DEFAULT 0,
                total_steps INTEGER,
                logs_uri TEXT,
                config_json TEXT,
                error_message TEXT,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (auction_type_id) REFERENCES auction_types(id),
                FOREIGN KEY (model_version_id) REFERENCES model_versions(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_jobs_status ON training_jobs(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_training_jobs_model ON training_jobs(model_version_id)
        """)

        # -----------------------------------------------------------------
        # EXPORT JOBS (to Central Dispatch)
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS export_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL UNIQUE,
                run_id INTEGER NOT NULL,
                dispatch_id TEXT,
                cd_listing_id TEXT,
                status TEXT DEFAULT 'pending',
                payload_json TEXT,
                response_json TEXT,
                error_json TEXT,
                validation_errors_json TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                submitted_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES extraction_runs(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_export_jobs_run ON export_jobs(run_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_export_jobs_status ON export_jobs(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_export_jobs_dispatch_id ON export_jobs(dispatch_id)
        """)

        # -----------------------------------------------------------------
        # LAYOUT BLOCKS (spatial document structure)
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS layout_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                block_id TEXT NOT NULL,
                page_num INTEGER NOT NULL DEFAULT 0,
                x0 REAL NOT NULL,
                y0 REAL NOT NULL,
                x1 REAL NOT NULL,
                y1 REAL NOT NULL,
                text TEXT,
                block_type TEXT DEFAULT 'data',
                label TEXT,
                text_source TEXT DEFAULT 'native' CHECK (text_source IN ('native', 'ocr', 'hybrid')),
                confidence REAL DEFAULT 1.0,
                element_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id),
                UNIQUE(document_id, block_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_layout_blocks_document ON layout_blocks(document_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_layout_blocks_label ON layout_blocks(label)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_layout_blocks_type ON layout_blocks(block_type)
        """)

        # -----------------------------------------------------------------
        # FIELD EVIDENCE (tracks which blocks contributed to field values)
        # -----------------------------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS field_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                field_key TEXT NOT NULL,
                block_id INTEGER,
                text_snippet TEXT,
                page_num INTEGER,
                bbox_json TEXT,
                rule_id TEXT,
                extraction_method TEXT,
                confidence REAL DEFAULT 1.0,
                value_source TEXT DEFAULT 'extracted',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES extraction_runs(id),
                FOREIGN KEY (block_id) REFERENCES layout_blocks(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_field_evidence_run ON field_evidence(run_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_field_evidence_field ON field_evidence(field_key)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_field_evidence_block ON field_evidence(block_id)
        """)

        conn.commit()


# =============================================================================
# SEED DATA
# =============================================================================


def seed_base_auction_types():
    """Seed the 3 base auction types + Other."""
    base_types = [
        {
            "name": "Copart",
            "code": "COPART",
            "is_base": True,
            "is_custom": False,
            "description": "Copart vehicle auctions - Sales Receipt/Bill of Sale documents",
            "extractor_config": json.dumps(
                {
                    "extractor_class": "CopartExtractor",
                    "patterns": ["COPART", "SOLD THROUGH COPART", "copart.com"],
                }
            ),
        },
        {
            "name": "IAA (Insurance Auto Auctions)",
            "code": "IAA",
            "is_base": True,
            "is_custom": False,
            "description": "IAA insurance auto auction documents",
            "extractor_config": json.dumps(
                {
                    "extractor_class": "IAAExtractor",
                    "patterns": ["IAA", "INSURANCE AUTO AUCTIONS"],
                }
            ),
        },
        {
            "name": "Manheim",
            "code": "MANHEIM",
            "is_base": True,
            "is_custom": False,
            "description": "Manheim wholesale auto auction documents",
            "extractor_config": json.dumps(
                {
                    "extractor_class": "ManheimExtractor",
                    "patterns": ["MANHEIM", "MANHEIM AUCTIONS"],
                }
            ),
        },
        {
            "name": "Other",
            "code": "OTHER",
            "is_base": True,
            "is_custom": False,
            "description": "Other/unknown auction types - base for custom subtypes",
            "extractor_config": json.dumps(
                {
                    "extractor_class": None,
                    "patterns": [],
                }
            ),
        },
    ]

    with get_connection() as conn:
        for auction_type in base_types:
            # Check if already exists
            existing = conn.execute(
                "SELECT id FROM auction_types WHERE code = ?", (auction_type["code"],)
            ).fetchone()

            if not existing:
                conn.execute(
                    """INSERT INTO auction_types
                       (name, code, is_base, is_custom, description, extractor_config)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        auction_type["name"],
                        auction_type["code"],
                        auction_type["is_base"],
                        auction_type["is_custom"],
                        auction_type["description"],
                        auction_type["extractor_config"],
                    ),
                )

        conn.commit()


def seed_default_field_mappings():
    """Seed default field mappings for base auction types."""
    # Common fields for all auction types
    common_fields = [
        # Vehicle fields
        ("vehicle_vin", "vin", "vehicles[0].vin", True, "Vehicle VIN (17 chars)"),
        ("vehicle_year", "year", "vehicles[0].year", False, "Vehicle year"),
        ("vehicle_make", "make", "vehicles[0].make", False, "Vehicle make"),
        ("vehicle_model", "model", "vehicles[0].model", False, "Vehicle model"),
        ("vehicle_color", "color", "vehicles[0].color", False, "Vehicle color"),
        ("vehicle_lot", "lot_number", "vehicles[0].lotNumber", False, "Lot number"),
        (
            "vehicle_is_inoperable",
            "is_inoperable",
            "vehicles[0].isInoperable",
            False,
            "Is inoperable",
        ),
        # Pickup fields
        ("pickup_name", "pickup_name", "stops[0].locationName", False, "Pickup location name"),
        ("pickup_address", "pickup_address", "stops[0].address", True, "Pickup address"),
        ("pickup_city", "pickup_city", "stops[0].city", True, "Pickup city"),
        ("pickup_state", "pickup_state", "stops[0].state", True, "Pickup state"),
        ("pickup_zip", "pickup_postal_code", "stops[0].postalCode", True, "Pickup ZIP"),
        ("pickup_phone", "pickup_phone", "stops[0].phone", False, "Pickup phone"),
        # Reference fields
        ("reference_id", "reference_id", "externalId", False, "Reference ID"),
        ("gate_pass", "gate_pass", None, False, "Gate pass code"),
        ("buyer_id", "buyer_id", None, False, "Buyer ID"),
        ("buyer_name", "buyer_name", None, False, "Buyer name"),
        # Dates
        ("sale_date", "sale_date", None, False, "Sale date"),
        ("available_date", "available_date", "availableDate", True, "Available date"),
    ]

    with get_connection() as conn:
        # Get base auction types
        auction_types = conn.execute(
            "SELECT id, code FROM auction_types WHERE is_base = TRUE"
        ).fetchall()

        for at in auction_types:
            auction_type_id = at["id"]
            at["code"]

            for i, (source_key, internal_key, cd_key, is_required, description) in enumerate(
                common_fields
            ):
                # Check if exists
                existing = conn.execute(
                    "SELECT id FROM field_mappings WHERE auction_type_id = ? AND source_key = ?",
                    (auction_type_id, source_key),
                ).fetchone()

                if not existing:
                    conn.execute(
                        """INSERT INTO field_mappings
                           (auction_type_id, source_key, internal_key, cd_key, is_required, description, display_order)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            auction_type_id,
                            source_key,
                            internal_key,
                            cd_key,
                            is_required,
                            description,
                            i,
                        ),
                    )

        conn.commit()


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class AuctionType:
    """Auction type entity."""

    id: int
    name: str
    code: str
    parent_id: Optional[int] = None
    is_base: bool = False
    is_custom: bool = False
    is_active: bool = True
    description: Optional[str] = None
    extractor_config: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Document:
    """Uploaded document entity."""

    id: int
    uuid: str
    auction_type_id: int
    dataset_split: str
    filename: str
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    sha256: Optional[str] = None
    mime_type: str = "application/pdf"
    page_count: Optional[int] = None
    has_ocr: bool = False
    raw_text: Optional[str] = None
    source: str = "upload"  # upload, email, batch, test_lab
    is_test: bool = False
    created_at: Optional[str] = None
    uploaded_by: Optional[str] = None


@dataclass
class ExtractionRun:
    """Extraction run entity."""

    id: int
    uuid: str
    document_id: int
    auction_type_id: int
    extractor_kind: str = "rule"
    model_version_id: Optional[int] = None
    status: str = "pending"
    extraction_score: Optional[float] = None
    outputs_json: Optional[dict] = None
    errors_json: Optional[list] = None
    metrics_json: Optional[dict] = None
    field_sources_json: Optional[dict] = None
    processing_time_ms: Optional[int] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class ExtractionMetrics:
    """
    Extraction metrics for diagnostics and observability.

    These metrics are tracked during extraction and stored in metrics_json.
    Used for monitoring extraction quality and debugging issues.
    """

    # Text extraction metrics
    raw_text_length: int = 0
    words_count: int = 0
    text_mode: str = "native"  # "native", "ocr", "hybrid"
    pages_count: int = 0

    # Classification metrics
    detected_source: Optional[str] = None
    classification_score: float = 0.0
    classification_patterns: list[str] = field(default_factory=list)

    # Extraction metrics
    fields_extracted_count: int = 0
    fields_filled_count: int = 0
    required_fields_filled: int = 0
    required_fields_total: int = 0

    # Quality indicators
    needs_ocr: bool = False
    has_pickup_address: bool = False
    has_vehicle_vin: bool = False
    has_vehicle_ymm: bool = False  # year, make, model

    # Processing info
    extractor_version: str = "1.0"
    extraction_timestamp: Optional[str] = None


@dataclass
class FieldMapping:
    """Field mapping entity."""

    id: int
    auction_type_id: int
    source_key: str
    internal_key: str
    cd_key: Optional[str] = None
    transform: Optional[str] = None
    is_required: bool = False
    default_value: Optional[str] = None
    validation_regex: Optional[str] = None
    description: Optional[str] = None
    display_order: int = 0
    is_active: bool = True


@dataclass
class ReviewItem:
    """Review item entity."""

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
    status: str = "pending"
    reviewer: Optional[str] = None
    review_notes: Optional[str] = None
    created_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    updated_at: Optional[str] = None  # alias for reviewed_at


@dataclass
class TrainingExample:
    """Training example entity."""

    id: int
    uuid: str
    auction_type_id: int
    document_id: Optional[int] = None
    input_text: str = ""
    input_chunks_json: Optional[list] = None
    labels_json: dict = field(default_factory=dict)
    source_review_item_ids: Optional[list[int]] = None
    quality_score: Optional[float] = None
    is_validated: bool = False
    created_at: Optional[str] = None


@dataclass
class ModelVersion:
    """Model version entity."""

    id: int
    uuid: str
    auction_type_id: int
    version_tag: str
    base_model: str
    adapter_type: str = "lora"
    adapter_path: Optional[str] = None  # alias for adapter_uri
    config_json: Optional[dict] = None
    metrics_json: Optional[dict] = None
    status: str = "training"
    training_examples_count: int = 0
    training_job_id: Optional[int] = None
    created_at: Optional[str] = None
    trained_at: Optional[str] = None
    promoted_at: Optional[str] = None


@dataclass
class TrainingJob:
    """Training job entity."""

    id: int
    uuid: str
    auction_type_id: int
    model_version_id: int = 0
    status: str = "queued"
    config_json: Optional[dict] = None
    metrics_json: Optional[dict] = None
    log_path: Optional[str] = None  # alias for logs_uri
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None  # alias for finished_at
    created_at: Optional[str] = None


@dataclass
class ExportJob:
    """Export job entity."""

    id: int
    uuid: str
    run_id: int
    target: str = "central_dispatch"
    dispatch_id: Optional[str] = None
    cd_listing_id: Optional[str] = None
    status: str = "pending"
    payload_json: Optional[dict] = None
    response_json: Optional[dict] = None
    error_json: Optional[dict] = None
    error_message: Optional[str] = None
    validation_errors_json: Optional[list] = None
    retry_count: int = 0
    created_at: Optional[str] = None
    submitted_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class LayoutBlock:
    """
    Layout block entity for spatial document structure.

    Represents a logical block/region in a document with bounding box
    coordinates and text content. Used for layout-aware extraction.
    """

    id: int
    document_id: int
    block_id: str
    page_num: int = 0
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    text: Optional[str] = None
    block_type: str = "data"  # header, label, data, table, footer
    label: Optional[str] = None
    text_source: str = "native"  # native, ocr, hybrid
    confidence: float = 1.0
    element_count: int = 0
    created_at: Optional[str] = None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Get bounding box as tuple (x0, y0, x1, y1)."""
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class FieldEvidence:
    """
    Field evidence entity tracks which blocks contributed to field values.

    Links extracted field values to their source blocks in the document,
    enabling transparency and debugging of extraction logic.
    """

    id: int
    run_id: int
    field_key: str
    block_id: Optional[int] = None
    text_snippet: Optional[str] = None
    page_num: Optional[int] = None
    bbox_json: Optional[dict] = None  # {x0, y0, x1, y1}
    rule_id: Optional[str] = None
    extraction_method: Optional[str] = None  # pattern, spatial, ml, learned_rule
    confidence: float = 1.0
    value_source: str = (
        "extracted"  # user_override, warehouse_const, auction_const, extracted, default
    )
    created_at: Optional[str] = None


# =============================================================================
# REPOSITORY CLASSES
# =============================================================================


class AuctionTypeRepository:
    """Repository for AuctionType operations."""

    @staticmethod
    def create(
        name: str,
        code: str,
        parent_id: int = None,
        is_custom: bool = True,
        description: str = None,
        extractor_config: dict = None,
    ) -> int:
        """Create a new auction type."""
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO auction_types
                   (name, code, parent_id, is_base, is_custom, description, extractor_config)
                   VALUES (?, ?, ?, FALSE, ?, ?, ?)""",
                (
                    name,
                    code.upper(),
                    parent_id,
                    is_custom,
                    description,
                    json.dumps(extractor_config) if extractor_config else None,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(id: int) -> Optional[AuctionType]:
        """Get auction type by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM auction_types WHERE id = ?", (id,)).fetchone()
            if row:
                data = dict(row)
                if data.get("extractor_config"):
                    data["extractor_config"] = json.loads(data["extractor_config"])
                return AuctionType(**data)
            return None

    @staticmethod
    def get_by_code(code: str) -> Optional[AuctionType]:
        """Get auction type by code."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM auction_types WHERE code = ?", (code.upper(),)
            ).fetchone()
            if row:
                data = dict(row)
                if data.get("extractor_config"):
                    data["extractor_config"] = json.loads(data["extractor_config"])
                return AuctionType(**data)
            return None

    @staticmethod
    def list_all(include_inactive: bool = False) -> list[AuctionType]:
        """List all auction types."""
        sql = "SELECT * FROM auction_types"
        if not include_inactive:
            sql += " WHERE is_active = TRUE"
        sql += " ORDER BY is_base DESC, name ASC"

        with get_connection() as conn:
            rows = conn.execute(sql).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                if data.get("extractor_config"):
                    data["extractor_config"] = json.loads(data["extractor_config"])
                result.append(AuctionType(**data))
            return result

    @staticmethod
    def update(id: int, **kwargs) -> bool:
        """Update auction type."""
        if not kwargs:
            return False

        if "extractor_config" in kwargs and isinstance(kwargs["extractor_config"], dict):
            kwargs["extractor_config"] = json.dumps(kwargs["extractor_config"])

        kwargs["updated_at"] = datetime.utcnow().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [id]

        with get_connection() as conn:
            conn.execute(f"UPDATE auction_types SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return True

    @staticmethod
    def delete(id: int) -> bool:
        """Soft delete (deactivate) auction type."""
        with get_connection() as conn:
            # Check if it's a base type
            row = conn.execute("SELECT is_base FROM auction_types WHERE id = ?", (id,)).fetchone()
            if row and row["is_base"]:
                return False  # Cannot delete base types

            conn.execute(
                "UPDATE auction_types SET is_active = FALSE, updated_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), id),
            )
            conn.commit()
            return True


class DocumentRepository:
    """Repository for Document operations."""

    @staticmethod
    def create(
        auction_type_id: int,
        dataset_split: str,
        filename: str,
        file_path: str = None,
        file_size: int = None,
        sha256: str = None,
        raw_text: str = None,
        uploaded_by: str = None,
        source: str = "upload",
        is_test: bool = False,
        page_count: int = None,
    ) -> int:
        """Create a new document."""
        doc_uuid = str(uuid.uuid4())

        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO documents
                   (uuid, auction_type_id, dataset_split, filename, file_path, file_size, sha256, raw_text, uploaded_by, source, is_test, page_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc_uuid,
                    auction_type_id,
                    dataset_split,
                    filename,
                    file_path,
                    file_size,
                    sha256,
                    raw_text,
                    uploaded_by,
                    source,
                    is_test,
                    page_count,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(id: int) -> Optional[Document]:
        """Get document by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (id,)).fetchone()
            if row:
                return Document(**dict(row))
            return None

    @staticmethod
    def get_by_sha256(sha256: str) -> Optional[Document]:
        """Get document by SHA256 hash (for deduplication)."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)).fetchone()
            if row:
                return Document(**dict(row))
            return None

    @staticmethod
    def list_by_auction_type(
        auction_type_id: int, dataset_split: str = None, limit: int = 100, offset: int = 0
    ) -> list[Document]:
        """List documents for an auction type."""
        sql = "SELECT * FROM documents WHERE auction_type_id = ?"
        params = [auction_type_id]

        if dataset_split:
            sql += " AND dataset_split = ?"
            params.append(dataset_split)

        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [Document(**dict(row)) for row in rows]

    @staticmethod
    def count_by_auction_type(auction_type_id: int) -> dict[str, int]:
        """Count documents by split for an auction type."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT dataset_split, COUNT(*) as count
                   FROM documents WHERE auction_type_id = ? GROUP BY dataset_split""",
                (auction_type_id,),
            ).fetchall()
            return {row["dataset_split"]: row["count"] for row in rows}

    @staticmethod
    def update(id: int, **kwargs) -> bool:
        """Update document."""
        if not kwargs:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [id]

        with get_connection() as conn:
            conn.execute(f"UPDATE documents SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return True

    @staticmethod
    def delete(id: int) -> bool:
        """Delete document and associated data."""
        with get_connection() as conn:
            # Delete related extraction runs first
            conn.execute(
                "DELETE FROM review_items WHERE run_id IN (SELECT id FROM extraction_runs WHERE document_id = ?)",
                (id,),
            )
            conn.execute("DELETE FROM extraction_runs WHERE document_id = ?", (id,))
            conn.execute("DELETE FROM documents WHERE id = ?", (id,))
            conn.commit()
            return True

    @staticmethod
    def list_all(
        auction_type_id: int = None,
        dataset_split: str = None,
        is_test: bool = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Document]:
        """List all documents with optional filtering."""
        sql = "SELECT * FROM documents WHERE 1=1"
        params = []

        if auction_type_id:
            sql += " AND auction_type_id = ?"
            params.append(auction_type_id)
        if dataset_split:
            sql += " AND dataset_split = ?"
            params.append(dataset_split)
        if is_test is not None:
            sql += " AND is_test = ?"
            params.append(is_test)

        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [Document(**dict(row)) for row in rows]


class ExtractionRunRepository:
    """Repository for ExtractionRun operations."""

    @staticmethod
    def create(
        document_id: int,
        auction_type_id: int,
        extractor_kind: str = "rule",
        model_version_id: int = None,
    ) -> int:
        """Create a new extraction run."""
        run_uuid = str(uuid.uuid4())

        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO extraction_runs
                   (uuid, document_id, auction_type_id, extractor_kind, model_version_id, status)
                   VALUES (?, ?, ?, ?, ?, 'pending')""",
                (run_uuid, document_id, auction_type_id, extractor_kind, model_version_id),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(id: int) -> Optional[ExtractionRun]:
        """Get extraction run by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM extraction_runs WHERE id = ?", (id,)).fetchone()
            if row:
                data = dict(row)
                if data.get("outputs_json"):
                    data["outputs_json"] = json.loads(data["outputs_json"])
                if data.get("errors_json"):
                    data["errors_json"] = json.loads(data["errors_json"])
                if data.get("metrics_json"):
                    data["metrics_json"] = json.loads(data["metrics_json"])
                if data.get("field_sources_json"):
                    data["field_sources_json"] = json.loads(data["field_sources_json"])
                return ExtractionRun(**data)
            return None

    @staticmethod
    def update(id: int, **kwargs) -> bool:
        """Update extraction run."""
        if not kwargs:
            return False

        # Custom JSON serializer for datetime objects
        def json_serializer(obj):
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            elif hasattr(obj, "__str__"):
                return str(obj)
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        if "outputs_json" in kwargs and isinstance(kwargs["outputs_json"], dict):
            kwargs["outputs_json"] = json.dumps(kwargs["outputs_json"], default=json_serializer)
        if "errors_json" in kwargs and isinstance(kwargs["errors_json"], list):
            kwargs["errors_json"] = json.dumps(kwargs["errors_json"], default=json_serializer)
        if "metrics_json" in kwargs and isinstance(kwargs["metrics_json"], dict):
            kwargs["metrics_json"] = json.dumps(kwargs["metrics_json"], default=json_serializer)
        if "field_sources_json" in kwargs and isinstance(kwargs["field_sources_json"], dict):
            kwargs["field_sources_json"] = json.dumps(
                kwargs["field_sources_json"], default=json_serializer
            )

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [id]

        with get_connection() as conn:
            conn.execute(f"UPDATE extraction_runs SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return True

    @staticmethod
    def list_by_document(document_id: int) -> list[ExtractionRun]:
        """List extraction runs for a document."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM extraction_runs WHERE document_id = ? ORDER BY created_at DESC",
                (document_id,),
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                if data.get("outputs_json"):
                    data["outputs_json"] = json.loads(data["outputs_json"])
                if data.get("errors_json"):
                    data["errors_json"] = json.loads(data["errors_json"])
                if data.get("metrics_json"):
                    data["metrics_json"] = json.loads(data["metrics_json"])
                if data.get("field_sources_json"):
                    data["field_sources_json"] = json.loads(data["field_sources_json"])
                result.append(ExtractionRun(**data))
            return result

    @staticmethod
    def list_needs_review(limit: int = 50) -> list[ExtractionRun]:
        """List runs that need review."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM extraction_runs
                   WHERE status IN ('completed', 'needs_review')
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                if data.get("outputs_json"):
                    data["outputs_json"] = json.loads(data["outputs_json"])
                result.append(ExtractionRun(**data))
            return result


class ReviewItemRepository:
    """Repository for ReviewItem operations."""

    @staticmethod
    def create_batch(run_id: int, items: list[dict]) -> list[int]:
        """Create multiple review items for a run."""
        ids = []
        with get_connection() as conn:
            for item in items:
                cursor = conn.execute(
                    """INSERT INTO review_items
                       (run_id, source_key, internal_key, cd_key, predicted_value,
                        corrected_value, is_match_ok, export_field, confidence)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        item.get("source_key"),
                        item.get("internal_key"),
                        item.get("cd_key"),
                        item.get("predicted_value"),
                        item.get("corrected_value"),
                        item.get("is_match_ok", False),
                        item.get("export_field", True),
                        item.get("confidence"),
                    ),
                )
                ids.append(cursor.lastrowid)
            conn.commit()
        return ids

    @staticmethod
    def get_by_run(run_id: int) -> list[ReviewItem]:
        """Get all review items for a run."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM review_items WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                data.setdefault("updated_at", data.get("reviewed_at"))
                result.append(ReviewItem(**data))
            return result

    @staticmethod
    def get_by_id(id: int) -> Optional[ReviewItem]:
        """Get review item by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM review_items WHERE id = ?", (id,)).fetchone()
            if row:
                data = dict(row)
                data.setdefault("updated_at", data.get("reviewed_at"))
                return ReviewItem(**data)
            return None

    @staticmethod
    def update(id: int, **kwargs) -> bool:
        """Update review item."""
        if not kwargs:
            return False

        kwargs["reviewed_at"] = datetime.utcnow().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [id]

        with get_connection() as conn:
            conn.execute(f"UPDATE review_items SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return True

    @staticmethod
    def update_batch(items: list[dict]) -> int:
        """Update multiple review items."""
        updated = 0
        now = datetime.utcnow().isoformat()

        with get_connection() as conn:
            for item in items:
                if "id" not in item:
                    continue

                conn.execute(
                    """UPDATE review_items SET
                       corrected_value = ?,
                       is_match_ok = ?,
                       export_field = ?,
                       status = ?,
                       reviewer = ?,
                       review_notes = ?,
                       reviewed_at = ?
                       WHERE id = ?""",
                    (
                        item.get("corrected_value"),
                        item.get("is_match_ok", False),
                        item.get("export_field", True),
                        item.get("status", "pending"),
                        item.get("reviewer"),
                        item.get("review_notes"),
                        now,
                        item["id"],
                    ),
                )
                updated += 1
            conn.commit()
        return updated

    @staticmethod
    def submit_review(run_id: int, items: list[dict], reviewer: str = None) -> dict:
        """Submit a complete review for a run."""
        now = datetime.utcnow().isoformat()
        updated = 0
        approved = 0
        corrected = 0

        with get_connection() as conn:
            for item in items:
                status = "approved" if item.get("is_match_ok") else "corrected"
                if item.get("corrected_value") and item.get("corrected_value") != item.get(
                    "predicted_value"
                ):
                    status = "corrected"
                    corrected += 1
                else:
                    approved += 1

                if "id" in item:
                    conn.execute(
                        """UPDATE review_items SET
                           corrected_value = ?,
                           is_match_ok = ?,
                           export_field = ?,
                           status = ?,
                           reviewer = ?,
                           reviewed_at = ?
                           WHERE id = ?""",
                        (
                            item.get("corrected_value"),
                            item.get("is_match_ok", False),
                            item.get("export_field", True),
                            status,
                            reviewer,
                            now,
                            item["id"],
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO review_items
                           (run_id, source_key, internal_key, cd_key, predicted_value,
                            corrected_value, is_match_ok, export_field, status, reviewer, reviewed_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            run_id,
                            item.get("source_key"),
                            item.get("internal_key"),
                            item.get("cd_key"),
                            item.get("predicted_value"),
                            item.get("corrected_value"),
                            item.get("is_match_ok", False),
                            item.get("export_field", True),
                            status,
                            reviewer,
                            now,
                        ),
                    )
                updated += 1

            conn.commit()

        return {
            "run_id": run_id,
            "total": updated,
            "approved": approved,
            "corrected": corrected,
            "reviewed_at": now,
        }


class TrainingExampleRepository:
    """Repository for TrainingExample operations."""

    @staticmethod
    def create(
        document_id: int,
        auction_type_id: int,
        run_id: int = None,
        field_key: str = None,
        predicted_value: str = None,
        gold_value: str = None,
        is_correct: bool = True,
        source_text_snippet: str = None,
    ) -> int:
        """Create a training example from review correction."""
        example_uuid = str(uuid.uuid4())

        # Build labels as a simple dict
        labels = {field_key: gold_value} if field_key and gold_value else {}

        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO training_examples
                   (uuid, auction_type_id, document_id, input_text, labels_json,
                    source_review_item_ids, is_validated)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    example_uuid,
                    auction_type_id,
                    document_id,
                    source_text_snippet or "",
                    json.dumps(labels),
                    json.dumps([run_id]) if run_id else None,
                    is_correct,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def create_from_review(run_id: int) -> Optional[int]:
        """Create a training example from a completed review."""
        with get_connection() as conn:
            # Get the run details
            run = conn.execute(
                """SELECT er.*, d.raw_text, d.auction_type_id as doc_auction_type_id
                   FROM extraction_runs er
                   JOIN documents d ON er.document_id = d.id
                   WHERE er.id = ?""",
                (run_id,),
            ).fetchone()

            if not run:
                return None

            # Get reviewed items
            items = conn.execute(
                "SELECT * FROM review_items WHERE run_id = ? AND status IN ('approved', 'corrected')",
                (run_id,),
            ).fetchall()

            if not items:
                return None

            # Build labels
            labels = {}
            review_item_ids = []
            for item in items:
                final_value = (
                    item["corrected_value"] if item["corrected_value"] else item["predicted_value"]
                )
                if final_value:
                    labels[item["source_key"]] = final_value
                    review_item_ids.append(item["id"])

            # Create training example
            example_uuid = str(uuid.uuid4())
            cursor = conn.execute(
                """INSERT INTO training_examples
                   (uuid, auction_type_id, document_id, input_text, labels_json, source_review_item_ids)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    example_uuid,
                    run["auction_type_id"],
                    run["document_id"],
                    run["raw_text"] or "",
                    json.dumps(labels),
                    json.dumps(review_item_ids),
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def list_by_auction_type(
        auction_type_id: int, validated_only: bool = False, limit: int = 1000
    ) -> list[TrainingExample]:
        """List training examples for an auction type."""
        sql = "SELECT * FROM training_examples WHERE auction_type_id = ?"
        params = [auction_type_id]

        if validated_only:
            sql += " AND is_validated = TRUE"

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                if data.get("labels_json"):
                    data["labels_json"] = json.loads(data["labels_json"])
                if data.get("input_chunks_json"):
                    data["input_chunks_json"] = json.loads(data["input_chunks_json"])
                if data.get("source_review_item_ids"):
                    data["source_review_item_ids"] = json.loads(data["source_review_item_ids"])
                result.append(TrainingExample(**data))
            return result

    @staticmethod
    def count_by_auction_type(auction_type_id: int) -> dict[str, int]:
        """Count training examples by auction type."""
        with get_connection() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM training_examples WHERE auction_type_id = ?",
                (auction_type_id,),
            ).fetchone()[0]
            validated = conn.execute(
                "SELECT COUNT(*) FROM training_examples WHERE auction_type_id = ? AND is_validated = TRUE",
                (auction_type_id,),
            ).fetchone()[0]
            return {"total": total, "validated": validated}


class ModelVersionRepository:
    """Repository for ModelVersion operations."""

    @staticmethod
    def create(
        auction_type_id: int,
        version_tag: str,
        base_model: str,
        adapter_type: str = "lora",
        config: dict = None,
        training_job_id: int = None,
    ) -> int:
        """Create a new model version."""
        model_uuid = str(uuid.uuid4())

        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO model_versions
                   (uuid, auction_type_id, version_tag, base_model, adapter_type, config_json, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'training')""",
                (
                    model_uuid,
                    auction_type_id,
                    version_tag,
                    base_model,
                    adapter_type,
                    json.dumps(config) if config else None,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def _row_to_model(row) -> ModelVersion:
        """Convert a database row to a ModelVersion object."""
        data = dict(row)
        if data.get("config_json"):
            data["config_json"] = json.loads(data["config_json"])
        if data.get("metrics_json"):
            data["metrics_json"] = json.loads(data["metrics_json"])
        # Handle field name differences
        data.setdefault("adapter_path", data.get("adapter_uri"))
        data.setdefault("training_job_id", None)
        # Remove fields not in dataclass
        data.pop("adapter_uri", None)
        return ModelVersion(**data)

    @staticmethod
    def get_by_id(id: int) -> Optional[ModelVersion]:
        """Get model version by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM model_versions WHERE id = ?", (id,)).fetchone()
            if row:
                return ModelVersionRepository._row_to_model(row)
            return None

    @staticmethod
    def get_active(auction_type_id: int) -> Optional[ModelVersion]:
        """Get the active model version for an auction type."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM model_versions WHERE auction_type_id = ? AND status = 'active'",
                (auction_type_id,),
            ).fetchone()
            if row:
                return ModelVersionRepository._row_to_model(row)
            return None

    @staticmethod
    def promote(id: int) -> bool:
        """Promote a model version to active (and archive previous active)."""
        now = datetime.utcnow().isoformat()

        with get_connection() as conn:
            # Get the model to promote
            model = conn.execute(
                "SELECT auction_type_id, status FROM model_versions WHERE id = ?", (id,)
            ).fetchone()

            if not model or model["status"] not in ("ready", "active"):
                return False

            # Archive current active
            conn.execute(
                """UPDATE model_versions SET status = 'archived'
                   WHERE auction_type_id = ? AND status = 'active'""",
                (model["auction_type_id"],),
            )

            # Promote new one
            conn.execute(
                "UPDATE model_versions SET status = 'active', promoted_at = ? WHERE id = ?",
                (now, id),
            )
            conn.commit()
            return True

    @staticmethod
    def update(id: int, **kwargs) -> bool:
        """Update model version."""
        if not kwargs:
            return False

        if "config_json" in kwargs and isinstance(kwargs["config_json"], dict):
            kwargs["config_json"] = json.dumps(kwargs["config_json"])
        if "metrics_json" in kwargs and isinstance(kwargs["metrics_json"], dict):
            kwargs["metrics_json"] = json.dumps(kwargs["metrics_json"])

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [id]

        with get_connection() as conn:
            conn.execute(f"UPDATE model_versions SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return True

    @staticmethod
    def update_metrics(id: int, metrics: dict) -> bool:
        """Update model metrics."""
        with get_connection() as conn:
            conn.execute(
                "UPDATE model_versions SET metrics_json = ?, status = 'ready', trained_at = ? WHERE id = ?",
                (json.dumps(metrics), datetime.utcnow().isoformat(), id),
            )
            conn.commit()
            return True

    @staticmethod
    def list_by_auction_type(auction_type_id: int) -> list[ModelVersion]:
        """List all model versions for an auction type."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM model_versions WHERE auction_type_id = ? ORDER BY created_at DESC",
                (auction_type_id,),
            ).fetchall()
            return [ModelVersionRepository._row_to_model(row) for row in rows]


class ExportJobRepository:
    """Repository for ExportJob operations."""

    @staticmethod
    def create(
        run_id: int,
        target: str = "central_dispatch",
        dispatch_id: str = None,
        payload_json: dict = None,
    ) -> int:
        """Create a new export job."""
        job_uuid = str(uuid.uuid4())

        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO export_jobs
                   (uuid, run_id, dispatch_id, payload_json, status)
                   VALUES (?, ?, ?, ?, 'pending')""",
                (job_uuid, run_id, dispatch_id, json.dumps(payload_json) if payload_json else None),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def _row_to_job(row) -> ExportJob:
        """Convert a database row to an ExportJob object."""
        data = dict(row)
        for key in ["payload_json", "response_json", "error_json"]:
            if data.get(key):
                data[key] = json.loads(data[key])
        if data.get("validation_errors_json"):
            data["validation_errors_json"] = json.loads(data["validation_errors_json"])
        # Handle field name differences
        data.setdefault("target", "central_dispatch")
        data.setdefault("error_message", None)
        return ExportJob(**data)

    @staticmethod
    def get_by_id(id: int) -> Optional[ExportJob]:
        """Get export job by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM export_jobs WHERE id = ?", (id,)).fetchone()
            if row:
                return ExportJobRepository._row_to_job(row)
            return None

    @staticmethod
    def update(id: int, **kwargs) -> bool:
        """Update export job."""
        if not kwargs:
            return False

        if "payload_json" in kwargs and isinstance(kwargs["payload_json"], dict):
            kwargs["payload_json"] = json.dumps(kwargs["payload_json"])
        if "response_json" in kwargs and isinstance(kwargs["response_json"], dict):
            kwargs["response_json"] = json.dumps(kwargs["response_json"])
        if "error_json" in kwargs and isinstance(kwargs["error_json"], dict):
            kwargs["error_json"] = json.dumps(kwargs["error_json"])

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [id]

        with get_connection() as conn:
            conn.execute(f"UPDATE export_jobs SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return True

    @staticmethod
    def update_status(
        id: int,
        status: str,
        cd_listing_id: str = None,
        response: dict = None,
        error: dict = None,
        validation_errors: list = None,
    ) -> bool:
        """Update export job status."""
        now = datetime.utcnow().isoformat()

        with get_connection() as conn:
            updates = {"status": status}
            if cd_listing_id:
                updates["cd_listing_id"] = cd_listing_id
            if response:
                updates["response_json"] = json.dumps(response)
            if error:
                updates["error_json"] = json.dumps(error)
            if validation_errors:
                updates["validation_errors_json"] = json.dumps(validation_errors)

            if status == "submitted":
                updates["submitted_at"] = now
            elif status in ("success", "failed", "validation_error"):
                updates["completed_at"] = now

            set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
            values = list(updates.values()) + [id]

            conn.execute(f"UPDATE export_jobs SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return True

    @staticmethod
    def list_by_run(run_id: int) -> list[ExportJob]:
        """List export jobs for a run."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM export_jobs WHERE run_id = ? ORDER BY created_at DESC", (run_id,)
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                for key in ["payload_json", "response_json", "error_json"]:
                    if data.get(key):
                        data[key] = json.loads(data[key])
                result.append(ExportJob(**data))
            return result

    @staticmethod
    def list_pending(limit: int = 50) -> list[ExportJob]:
        """List pending export jobs."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM export_jobs WHERE status = 'pending' ORDER BY created_at LIMIT ?",
                (limit,),
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                if data.get("payload_json"):
                    data["payload_json"] = json.loads(data["payload_json"])
                result.append(ExportJob(**data))
            return result


# =============================================================================
# TRAINING JOB REPOSITORY
# =============================================================================


class TrainingJobRepository:
    """Repository for TrainingJob operations."""

    @staticmethod
    def create(auction_type_id: int, config_json: dict = None) -> int:
        """Create a new training job."""
        job_uuid = str(uuid.uuid4())

        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO training_jobs
                   (uuid, auction_type_id, model_version_id, config_json, status)
                   VALUES (?, ?, 0, ?, 'pending')""",
                (job_uuid, auction_type_id, json.dumps(config_json) if config_json else None),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(id: int) -> Optional[TrainingJob]:
        """Get training job by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM training_jobs WHERE id = ?", (id,)).fetchone()
            if row:
                data = dict(row)
                if data.get("config_json"):
                    data["config_json"] = json.loads(data["config_json"])
                # Handle field name differences
                data.setdefault("log_path", data.get("logs_uri"))
                data.setdefault("metrics_json", None)
                data.setdefault("completed_at", data.get("finished_at"))
                # Remove fields not in dataclass
                for key in ["logs_uri", "finished_at", "progress", "current_step", "total_steps"]:
                    data.pop(key, None)
                return TrainingJob(**data)
            return None

    @staticmethod
    def update(id: int, **kwargs) -> bool:
        """Update training job."""
        if not kwargs:
            return False

        if "config_json" in kwargs and isinstance(kwargs["config_json"], dict):
            kwargs["config_json"] = json.dumps(kwargs["config_json"])
        if "metrics_json" in kwargs and isinstance(kwargs["metrics_json"], dict):
            kwargs["metrics_json"] = json.dumps(kwargs["metrics_json"])

        set_clause = ", ".join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [id]

        with get_connection() as conn:
            conn.execute(f"UPDATE training_jobs SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return True


# =============================================================================
# LAYOUT BLOCK REPOSITORY
# =============================================================================


class LayoutBlockRepository:
    """Repository for LayoutBlock operations (spatial document structure)."""

    @staticmethod
    def create(
        document_id: int,
        block_id: str,
        page_num: int,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        text: str = None,
        block_type: str = "data",
        label: str = None,
        text_source: str = "native",
        confidence: float = 1.0,
        element_count: int = 0,
    ) -> int:
        """Create a new layout block."""
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO layout_blocks
                   (document_id, block_id, page_num, x0, y0, x1, y1,
                    text, block_type, label, text_source, confidence, element_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    document_id,
                    block_id,
                    page_num,
                    x0,
                    y0,
                    x1,
                    y1,
                    text,
                    block_type,
                    label,
                    text_source,
                    confidence,
                    element_count,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def create_batch(document_id: int, blocks: list[dict]) -> list[int]:
        """Create multiple layout blocks for a document."""
        ids = []
        with get_connection() as conn:
            for block in blocks:
                cursor = conn.execute(
                    """INSERT INTO layout_blocks
                       (document_id, block_id, page_num, x0, y0, x1, y1,
                        text, block_type, label, text_source, confidence, element_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        document_id,
                        block.get("block_id", f"block_{len(ids)}"),
                        block.get("page_num", 0),
                        block.get("x0", 0),
                        block.get("y0", 0),
                        block.get("x1", 0),
                        block.get("y1", 0),
                        block.get("text"),
                        block.get("block_type", "data"),
                        block.get("label"),
                        block.get("text_source", "native"),
                        block.get("confidence", 1.0),
                        block.get("element_count", 0),
                    ),
                )
                ids.append(cursor.lastrowid)
            conn.commit()
        return ids

    @staticmethod
    def get_by_id(id: int) -> Optional[LayoutBlock]:
        """Get layout block by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM layout_blocks WHERE id = ?", (id,)).fetchone()
            if row:
                return LayoutBlock(**dict(row))
            return None

    @staticmethod
    def get_by_document(document_id: int) -> list[LayoutBlock]:
        """Get all layout blocks for a document."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM layout_blocks
                   WHERE document_id = ?
                   ORDER BY page_num, y0, x0""",
                (document_id,),
            ).fetchall()
            return [LayoutBlock(**dict(row)) for row in rows]

    @staticmethod
    def get_by_label(document_id: int, label_pattern: str) -> list[LayoutBlock]:
        """Get blocks matching a label pattern."""
        import re

        blocks = LayoutBlockRepository.get_by_document(document_id)
        pattern = re.compile(label_pattern, re.IGNORECASE)
        return [b for b in blocks if b.label and pattern.search(b.label)]

    @staticmethod
    def get_by_type(document_id: int, block_type: str) -> list[LayoutBlock]:
        """Get blocks by type."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM layout_blocks
                   WHERE document_id = ? AND block_type = ?
                   ORDER BY page_num, y0, x0""",
                (document_id, block_type),
            ).fetchall()
            return [LayoutBlock(**dict(row)) for row in rows]

    @staticmethod
    def delete_by_document(document_id: int) -> int:
        """Delete all layout blocks for a document."""
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM layout_blocks WHERE document_id = ?", (document_id,))
            conn.commit()
            return cursor.rowcount

    @staticmethod
    def save_from_spatial_parser(document_id: int, structure) -> int:
        """
        Save layout blocks from a spatial parser DocumentStructure.

        Args:
            document_id: Database document ID
            structure: DocumentStructure from spatial_parser

        Returns:
            Number of blocks saved
        """
        # First delete existing blocks
        LayoutBlockRepository.delete_by_document(document_id)

        blocks = []
        for block in structure.blocks:
            blocks.append(
                {
                    "block_id": block.id,
                    "page_num": block.page,
                    "x0": block.x0,
                    "y0": block.y0,
                    "x1": block.x1,
                    "y1": block.y1,
                    "text": block.text,
                    "block_type": block.block_type,
                    "label": block.label,
                    "text_source": "native",  # Default; could be enhanced
                    "confidence": 1.0,
                    "element_count": len(block.elements),
                }
            )

        if blocks:
            LayoutBlockRepository.create_batch(document_id, blocks)

        return len(blocks)


# =============================================================================
# FIELD EVIDENCE REPOSITORY
# =============================================================================


class FieldEvidenceRepository:
    """Repository for FieldEvidence operations (extraction provenance)."""

    @staticmethod
    def create(
        run_id: int,
        field_key: str,
        block_id: int = None,
        text_snippet: str = None,
        page_num: int = None,
        bbox: dict = None,
        rule_id: str = None,
        extraction_method: str = None,
        confidence: float = 1.0,
        value_source: str = "extracted",
    ) -> int:
        """Create a new field evidence record."""
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO field_evidence
                   (run_id, field_key, block_id, text_snippet, page_num,
                    bbox_json, rule_id, extraction_method, confidence, value_source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    field_key,
                    block_id,
                    text_snippet,
                    page_num,
                    json.dumps(bbox) if bbox else None,
                    rule_id,
                    extraction_method,
                    confidence,
                    value_source,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def create_batch(run_id: int, evidence_items: list[dict]) -> list[int]:
        """Create multiple field evidence records for an extraction run."""
        ids = []
        with get_connection() as conn:
            for item in evidence_items:
                bbox = item.get("bbox")
                cursor = conn.execute(
                    """INSERT INTO field_evidence
                       (run_id, field_key, block_id, text_snippet, page_num,
                        bbox_json, rule_id, extraction_method, confidence, value_source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        item.get("field_key"),
                        item.get("block_id"),
                        item.get("text_snippet"),
                        item.get("page_num"),
                        json.dumps(bbox) if bbox else None,
                        item.get("rule_id"),
                        item.get("extraction_method"),
                        item.get("confidence", 1.0),
                        item.get("value_source", "extracted"),
                    ),
                )
                ids.append(cursor.lastrowid)
            conn.commit()
        return ids

    @staticmethod
    def get_by_id(id: int) -> Optional[FieldEvidence]:
        """Get field evidence by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM field_evidence WHERE id = ?", (id,)).fetchone()
            if row:
                data = dict(row)
                if data.get("bbox_json"):
                    data["bbox_json"] = json.loads(data["bbox_json"])
                return FieldEvidence(**data)
            return None

    @staticmethod
    def get_by_run(run_id: int) -> list[FieldEvidence]:
        """Get all field evidence for an extraction run."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM field_evidence WHERE run_id = ? ORDER BY field_key", (run_id,)
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                if data.get("bbox_json"):
                    data["bbox_json"] = json.loads(data["bbox_json"])
                result.append(FieldEvidence(**data))
            return result

    @staticmethod
    def get_by_field(run_id: int, field_key: str) -> list[FieldEvidence]:
        """Get evidence for a specific field in a run."""
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM field_evidence WHERE run_id = ? AND field_key = ?",
                (run_id, field_key),
            ).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                if data.get("bbox_json"):
                    data["bbox_json"] = json.loads(data["bbox_json"])
                result.append(FieldEvidence(**data))
            return result

    @staticmethod
    def get_evidence_summary(run_id: int) -> dict[str, Any]:
        """Get summary of field evidence for a run."""
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT field_key, value_source, extraction_method,
                          COUNT(*) as count, AVG(confidence) as avg_confidence
                   FROM field_evidence WHERE run_id = ?
                   GROUP BY field_key, value_source, extraction_method""",
                (run_id,),
            ).fetchall()

            summary = {}
            for row in rows:
                field = row["field_key"]
                if field not in summary:
                    summary[field] = []
                summary[field].append(
                    {
                        "value_source": row["value_source"],
                        "extraction_method": row["extraction_method"],
                        "count": row["count"],
                        "avg_confidence": row["avg_confidence"],
                    }
                )

            return summary

    @staticmethod
    def delete_by_run(run_id: int) -> int:
        """Delete all field evidence for a run."""
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM field_evidence WHERE run_id = ?", (run_id,))
            conn.commit()
            return cursor.rowcount


# =============================================================================
# SCHEMA INITIALIZATION ALIAS
# =============================================================================


def init_schema():
    """Initialize the extended database schema. Alias for init_extended_schema."""
    init_extended_schema()
    seed_default_field_mappings()
    _run_migrations()


def _run_migrations():
    """Run database migrations for new columns."""
    with get_connection() as conn:
        # Migration: Add source column to documents
        try:
            conn.execute("ALTER TABLE documents ADD COLUMN source TEXT DEFAULT 'upload'")
        except Exception:
            pass  # Column already exists

        # Migration: Add is_test column to documents
        try:
            conn.execute("ALTER TABLE documents ADD COLUMN is_test BOOLEAN DEFAULT FALSE")
        except Exception:
            pass  # Column already exists

        # Migration: Add source index
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source)")
        except Exception:
            pass

        # Migration: Add is_test index
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_is_test ON documents(is_test)")
        except Exception:
            pass

        conn.commit()
