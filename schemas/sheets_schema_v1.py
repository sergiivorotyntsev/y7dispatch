"""
Google Sheets Schema v1 - Source of Truth for Pickups

This module defines the complete schema for the Pickups sheet,
including column ownership classes, upsert rules, and final value computation.

Schema Version: 1
Last Updated: 2024-01

Column Classes:
- IMMUTABLE: Never change after row creation
- SYSTEM: Can be updated by import/parser
- USER: Only editable by humans, never touched by import

Final Value Rule:
- field_final = field_override if field_override else field_base
"""

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ColumnClass(Enum):
    """Column ownership class."""

    IMMUTABLE = "immutable"  # Never change after creation
    SYSTEM = "system"  # Updated by import/parser
    USER = "user"  # Only human-editable


class ColumnType(Enum):
    """Column data type."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"  # ISO format YYYY-MM-DD
    DATETIME = "datetime"  # ISO format YYYY-MM-DDTHH:MM:SS
    ENUM = "enum"
    JSON = "json"


@dataclass
class ColumnDef:
    """Column definition."""

    name: str
    col_type: ColumnType
    col_class: ColumnClass
    description: str = ""
    enum_values: list[str] = field(default_factory=list)
    computed_from: Optional[str] = None  # For *_final columns
    default: Optional[str] = None


# =============================================================================
# SCHEMA DEFINITION
# =============================================================================

SCHEMA_VERSION = 1

# Status enum values
STATUS_VALUES = [
    "NEW",  # Just imported, not reviewed
    "NEEDS_REVIEW",  # Requires human attention
    "READY_FOR_CD",  # Ready to export to Central Dispatch
    "EXPORTED_TO_CD",  # Successfully exported
    "FAILED",  # Export failed
    "LOCKED",  # Locked from further imports
]

CD_EXPORT_STATUS_VALUES = [
    "NOT_READY",
    "READY",
    "SENT",
    "ERROR",
]

AUCTION_VALUES = ["COPART", "IAA", "MANHEIM", "UNKNOWN"]

VEHICLE_TYPE_VALUES = ["car", "suv", "truck", "van", "motorcycle", "other"]

RUNNING_VALUES = ["yes", "no", "unknown"]

TRAILER_TYPE_VALUES = ["open", "enclosed", "driveaway"]


# Column definitions organized by category
COLUMNS: list[ColumnDef] = [
    # =========================================================================
    # 1. IDENTIFICATION & SOURCES (immutable/system)
    # =========================================================================
    ColumnDef(
        name="pickup_uid",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.IMMUTABLE,
        description="Primary key. SHA1 hash of auction|gate_pass or fallback.",
    ),
    ColumnDef(
        name="status",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.USER,
        enum_values=STATUS_VALUES,
        default="NEW",
        description="Row status. User-owned.",
    ),
    ColumnDef(
        name="created_at",
        col_type=ColumnType.DATETIME,
        col_class=ColumnClass.IMMUTABLE,
        description="Row creation timestamp.",
    ),
    ColumnDef(
        name="last_ingested_at",
        col_type=ColumnType.DATETIME,
        col_class=ColumnClass.SYSTEM,
        description="Last import/ingest timestamp.",
    ),
    ColumnDef(
        name="auction_detected",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.SYSTEM,
        enum_values=AUCTION_VALUES,
        description="Detected auction source.",
    ),
    ColumnDef(
        name="auction_ref_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Lot/stock/order ID as parsed.",
    ),
    ColumnDef(
        name="gate_pass_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Gate pass code as parsed.",
    ),
    ColumnDef(
        name="source_email_message_id",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.IMMUTABLE,
        description="Original email Message-ID.",
    ),
    ColumnDef(
        name="source_email_date",
        col_type=ColumnType.DATETIME,
        col_class=ColumnClass.SYSTEM,
        description="Email received date.",
    ),
    ColumnDef(
        name="attachment_name",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="PDF attachment filename.",
    ),
    ColumnDef(
        name="attachment_hash",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.IMMUTABLE,
        description="SHA256 hash of attachment.",
    ),
    # =========================================================================
    # 2. VEHICLE (base/override/final)
    # =========================================================================
    ColumnDef(
        name="vin_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="VIN from parser.",
    ),
    ColumnDef(
        name="vin_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="VIN manual override.",
    ),
    ColumnDef(
        name="vin_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="vin",
        description="Final VIN = override or base.",
    ),
    ColumnDef(
        name="year_base",
        col_type=ColumnType.INTEGER,
        col_class=ColumnClass.SYSTEM,
        description="Vehicle year from parser.",
    ),
    ColumnDef(
        name="year_override",
        col_type=ColumnType.INTEGER,
        col_class=ColumnClass.USER,
        description="Year manual override.",
    ),
    ColumnDef(
        name="year_final",
        col_type=ColumnType.INTEGER,
        col_class=ColumnClass.SYSTEM,
        computed_from="year",
        description="Final year = override or base.",
    ),
    ColumnDef(
        name="make_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Vehicle make from parser.",
    ),
    ColumnDef(
        name="make_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="Make manual override.",
    ),
    ColumnDef(
        name="make_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="make",
        description="Final make = override or base.",
    ),
    ColumnDef(
        name="model_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Vehicle model from parser.",
    ),
    ColumnDef(
        name="model_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="Model manual override.",
    ),
    ColumnDef(
        name="model_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="model",
        description="Final model = override or base.",
    ),
    ColumnDef(
        name="vehicle_type_base",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.SYSTEM,
        enum_values=VEHICLE_TYPE_VALUES,
        description="Vehicle type from parser.",
    ),
    ColumnDef(
        name="vehicle_type_override",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.USER,
        enum_values=VEHICLE_TYPE_VALUES,
        description="Vehicle type manual override.",
    ),
    ColumnDef(
        name="vehicle_type_final",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.SYSTEM,
        enum_values=VEHICLE_TYPE_VALUES,
        computed_from="vehicle_type",
        description="Final vehicle type.",
    ),
    ColumnDef(
        name="running_base",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.SYSTEM,
        enum_values=RUNNING_VALUES,
        description="Running status from parser.",
    ),
    ColumnDef(
        name="running_override",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.USER,
        enum_values=RUNNING_VALUES,
        description="Running status manual override.",
    ),
    ColumnDef(
        name="running_final",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.SYSTEM,
        enum_values=RUNNING_VALUES,
        computed_from="running",
        description="Final running status.",
    ),
    ColumnDef(
        name="mileage_base",
        col_type=ColumnType.INTEGER,
        col_class=ColumnClass.SYSTEM,
        description="Mileage from parser.",
    ),
    ColumnDef(
        name="mileage_override",
        col_type=ColumnType.INTEGER,
        col_class=ColumnClass.USER,
        description="Mileage manual override.",
    ),
    ColumnDef(
        name="mileage_final",
        col_type=ColumnType.INTEGER,
        col_class=ColumnClass.SYSTEM,
        computed_from="mileage",
        description="Final mileage.",
    ),
    ColumnDef(
        name="color_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Vehicle color from parser.",
    ),
    ColumnDef(
        name="color_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="Color manual override.",
    ),
    ColumnDef(
        name="color_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="color",
        description="Final color.",
    ),
    # =========================================================================
    # 3. PICKUP LOCATION (base/override/final)
    # =========================================================================
    ColumnDef(
        name="pickup_address1_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Pickup street address from parser.",
    ),
    ColumnDef(
        name="pickup_address1_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="Pickup address manual override.",
    ),
    ColumnDef(
        name="pickup_address1_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="pickup_address1",
        description="Final pickup address.",
    ),
    ColumnDef(
        name="pickup_city_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Pickup city from parser.",
    ),
    ColumnDef(
        name="pickup_city_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="Pickup city manual override.",
    ),
    ColumnDef(
        name="pickup_city_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="pickup_city",
        description="Final pickup city.",
    ),
    ColumnDef(
        name="pickup_state_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Pickup state from parser.",
    ),
    ColumnDef(
        name="pickup_state_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="Pickup state manual override.",
    ),
    ColumnDef(
        name="pickup_state_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="pickup_state",
        description="Final pickup state.",
    ),
    ColumnDef(
        name="pickup_zip_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Pickup ZIP from parser.",
    ),
    ColumnDef(
        name="pickup_zip_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="Pickup ZIP manual override.",
    ),
    ColumnDef(
        name="pickup_zip_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="pickup_zip",
        description="Final pickup ZIP.",
    ),
    ColumnDef(
        name="pickup_contact_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Pickup contact name from parser.",
    ),
    ColumnDef(
        name="pickup_contact_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="Pickup contact manual override.",
    ),
    ColumnDef(
        name="pickup_contact_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="pickup_contact",
        description="Final pickup contact.",
    ),
    ColumnDef(
        name="pickup_phone_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Pickup phone from parser.",
    ),
    ColumnDef(
        name="pickup_phone_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="Pickup phone manual override.",
    ),
    ColumnDef(
        name="pickup_phone_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="pickup_phone",
        description="Final pickup phone.",
    ),
    # =========================================================================
    # 4. DELIVERY / WAREHOUSE (base/override/final)
    # =========================================================================
    ColumnDef(
        name="warehouse_id_base",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Suggested warehouse ID from routing.",
    ),
    ColumnDef(
        name="warehouse_id_override",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="Warehouse ID manual override.",
    ),
    ColumnDef(
        name="warehouse_id_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        computed_from="warehouse_id",
        description="Final warehouse ID.",
    ),
    ColumnDef(
        name="warehouse_name_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Warehouse name (computed from Warehouses sheet).",
    ),
    ColumnDef(
        name="delivery_address1_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Delivery address (from warehouse).",
    ),
    ColumnDef(
        name="delivery_city_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Delivery city (from warehouse).",
    ),
    ColumnDef(
        name="delivery_state_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Delivery state (from warehouse).",
    ),
    ColumnDef(
        name="delivery_zip_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Delivery ZIP (from warehouse).",
    ),
    ColumnDef(
        name="delivery_contact_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Delivery contact (from warehouse).",
    ),
    ColumnDef(
        name="delivery_phone_final",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Delivery phone (from warehouse).",
    ),
    # =========================================================================
    # 5. PRICING / TRAILER / DATES (base/override/final)
    # =========================================================================
    ColumnDef(
        name="price_base",
        col_type=ColumnType.FLOAT,
        col_class=ColumnClass.SYSTEM,
        description="Price from parser or calculation.",
    ),
    ColumnDef(
        name="price_override",
        col_type=ColumnType.FLOAT,
        col_class=ColumnClass.USER,
        description="Price manual override.",
    ),
    ColumnDef(
        name="price_final",
        col_type=ColumnType.FLOAT,
        col_class=ColumnClass.SYSTEM,
        computed_from="price",
        description="Final price for CD export.",
    ),
    ColumnDef(
        name="currency",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        default="USD",
        description="Currency code (always USD).",
    ),
    ColumnDef(
        name="trailer_type_base",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.SYSTEM,
        enum_values=TRAILER_TYPE_VALUES,
        description="Trailer type from derivation.",
    ),
    ColumnDef(
        name="trailer_type_override",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.USER,
        enum_values=TRAILER_TYPE_VALUES,
        description="Trailer type manual override.",
    ),
    ColumnDef(
        name="trailer_type_final",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.SYSTEM,
        enum_values=TRAILER_TYPE_VALUES,
        computed_from="trailer_type",
        description="Final trailer type.",
    ),
    ColumnDef(
        name="pickup_date_base",
        col_type=ColumnType.DATE,
        col_class=ColumnClass.SYSTEM,
        description="Pickup date from parser.",
    ),
    ColumnDef(
        name="pickup_date_override",
        col_type=ColumnType.DATE,
        col_class=ColumnClass.USER,
        description="Pickup date manual override.",
    ),
    ColumnDef(
        name="pickup_date_final",
        col_type=ColumnType.DATE,
        col_class=ColumnClass.SYSTEM,
        computed_from="pickup_date",
        description="Final pickup date.",
    ),
    ColumnDef(
        name="delivery_date_base",
        col_type=ColumnType.DATE,
        col_class=ColumnClass.SYSTEM,
        description="Delivery date from calculation.",
    ),
    ColumnDef(
        name="delivery_date_override",
        col_type=ColumnType.DATE,
        col_class=ColumnClass.USER,
        description="Delivery date manual override.",
    ),
    ColumnDef(
        name="delivery_date_final",
        col_type=ColumnType.DATE,
        col_class=ColumnClass.SYSTEM,
        computed_from="delivery_date",
        description="Final delivery date.",
    ),
    # =========================================================================
    # 6. CENTRAL DISPATCH EXPORT (system-owned)
    # =========================================================================
    ColumnDef(
        name="cd_export_enabled",
        col_type=ColumnType.BOOLEAN,
        col_class=ColumnClass.USER,
        default="TRUE",
        description="Enable/disable CD export for this row.",
    ),
    ColumnDef(
        name="cd_export_status",
        col_type=ColumnType.ENUM,
        col_class=ColumnClass.SYSTEM,
        enum_values=CD_EXPORT_STATUS_VALUES,
        default="NOT_READY",
        description="CD export status.",
    ),
    ColumnDef(
        name="cd_listing_id",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Central Dispatch listing ID after export.",
    ),
    ColumnDef(
        name="cd_last_export_at",
        col_type=ColumnType.DATETIME,
        col_class=ColumnClass.SYSTEM,
        description="Last CD export timestamp.",
    ),
    ColumnDef(
        name="cd_last_error",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Last CD export error message.",
    ),
    ColumnDef(
        name="cd_payload_json",
        col_type=ColumnType.JSON,
        col_class=ColumnClass.SYSTEM,
        description="CD payload snapshot (JSON).",
    ),
    ColumnDef(
        name="cd_payload_hash",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Hash of final fields for change detection.",
    ),
    ColumnDef(
        name="cd_fields_version",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Version of cd_field_mapping.yaml used.",
    ),
    # =========================================================================
    # 7. CLICKUP EXPORT (system-owned)
    # =========================================================================
    ColumnDef(
        name="clickup_task_id",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="ClickUp task ID.",
    ),
    ColumnDef(
        name="clickup_task_url",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="ClickUp task URL.",
    ),
    ColumnDef(
        name="clickup_status",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="ClickUp sync status.",
    ),
    ColumnDef(
        name="clickup_last_error",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Last ClickUp error.",
    ),
    # =========================================================================
    # 8. QUALITY CONTROL / AUDIT
    # =========================================================================
    ColumnDef(
        name="extraction_score",
        col_type=ColumnType.FLOAT,
        col_class=ColumnClass.SYSTEM,
        description="Extraction confidence score 0.0-1.0.",
    ),
    ColumnDef(
        name="validation_errors",
        col_type=ColumnType.JSON,
        col_class=ColumnClass.SYSTEM,
        description="Validation errors JSON array.",
    ),
    ColumnDef(
        name="lock_import",
        col_type=ColumnType.BOOLEAN,
        col_class=ColumnClass.USER,
        default="FALSE",
        description="Lock row from import updates.",
    ),
    ColumnDef(
        name="notes_user",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.USER,
        description="User notes/comments.",
    ),
    ColumnDef(
        name="automation_version",
        col_type=ColumnType.STRING,
        col_class=ColumnClass.SYSTEM,
        description="Version of automation that created/updated row.",
    ),
]


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_column_names() -> list[str]:
    """Get ordered list of column names."""
    return [col.name for col in COLUMNS]


def get_column_by_name(name: str) -> Optional[ColumnDef]:
    """Get column definition by name."""
    for col in COLUMNS:
        if col.name == name:
            return col
    return None


def get_columns_by_class(col_class: ColumnClass) -> list[ColumnDef]:
    """Get all columns of a specific class."""
    return [col for col in COLUMNS if col.col_class == col_class]


def get_immutable_columns() -> list[str]:
    """Get names of immutable columns."""
    return [col.name for col in COLUMNS if col.col_class == ColumnClass.IMMUTABLE]


def get_system_columns() -> list[str]:
    """Get names of system-owned columns."""
    return [col.name for col in COLUMNS if col.col_class == ColumnClass.SYSTEM]


def get_user_columns() -> list[str]:
    """Get names of user-owned columns."""
    return [col.name for col in COLUMNS if col.col_class == ColumnClass.USER]


def get_base_override_final_fields() -> list[str]:
    """Get list of field names that have base/override/final triplets."""
    fields = set()
    for col in COLUMNS:
        if col.computed_from:
            fields.add(col.computed_from)
    return sorted(fields)


def get_column_index(name: str) -> int:
    """Get 0-based column index by name."""
    names = get_column_names()
    try:
        return names.index(name)
    except ValueError:
        return -1


def column_index_to_letter(index: int) -> str:
    """Convert 0-based column index to Excel-style letter (A, B, ..., Z, AA, AB, ...)."""
    result = ""
    while index >= 0:
        result = chr(index % 26 + ord("A")) + result
        index = index // 26 - 1
    return result


def get_column_letter(name: str) -> str:
    """Get Excel-style column letter for a column name."""
    index = get_column_index(name)
    if index < 0:
        raise ValueError(f"Unknown column: {name}")
    return column_index_to_letter(index)


# =============================================================================
# UPSERT RANGES - Which columns to update during upsert
# =============================================================================


def get_upsert_system_range() -> tuple:
    """
    Get the range of columns that can be updated during upsert.
    Returns (start_col_letter, end_col_letter).

    This includes SYSTEM columns but excludes:
    - IMMUTABLE columns (pickup_uid, created_at, etc.)
    - USER columns (status, *_override, lock_import, etc.)
    """
    # Find first and last system column that's not computed
    system_cols = []
    for i, col in enumerate(COLUMNS):
        if col.col_class == ColumnClass.SYSTEM and not col.computed_from:
            system_cols.append((i, col.name))

    if not system_cols:
        return None

    # We'll return individual column letters for selective update
    return [column_index_to_letter(i) for i, _ in system_cols]


def get_updatable_columns_on_ingest() -> list[str]:
    """
    Get list of column names that can be updated during ingest.
    Excludes: immutable, user-owned, and computed columns.
    """
    return [
        col.name
        for col in COLUMNS
        if col.col_class == ColumnClass.SYSTEM
        and not col.computed_from
        and col.name not in ("pickup_uid", "created_at")
    ]


# =============================================================================
# PICKUP UID GENERATION
# =============================================================================


def compute_pickup_uid(
    auction: str,
    gate_pass: Optional[str] = None,
    lot_number: Optional[str] = None,
    stock_number: Optional[str] = None,
    vin: Optional[str] = None,
    attachment_hash: Optional[str] = None,
) -> str:
    """
    Compute the pickup_uid (primary key) using the defined algorithm.

    Priority:
    1. auction + gate_pass
    2. auction + lot_number or stock_number
    3. auction + vin
    4. auction + attachment_hash (fallback)

    Returns: 16-character hex string (first 16 chars of SHA1)
    """
    auction_lower = (auction or "UNKNOWN").lower().strip()

    # Priority 1: auction + gate_pass
    if gate_pass and gate_pass.strip():
        key = f"{auction_lower}|{gate_pass.strip().lower()}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    # Priority 2: auction + lot/stock
    lot_or_stock = lot_number or stock_number
    if lot_or_stock and lot_or_stock.strip():
        key = f"{auction_lower}|{lot_or_stock.strip().lower()}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    # Priority 3: auction + vin
    if vin and vin.strip():
        key = f"{auction_lower}|{vin.strip().upper()}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    # Priority 4: fallback to attachment_hash
    if attachment_hash and attachment_hash.strip():
        key = f"{auction_lower}|{attachment_hash.strip().lower()}"
        return hashlib.sha1(key.encode()).hexdigest()[:16]

    # Last resort: random-ish key (should not happen in practice)
    import uuid

    key = f"{auction_lower}|{uuid.uuid4().hex}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def compute_final_value(base_value, override_value):
    """
    Compute the final value using the override rule.
    final = override if override is not empty, else base
    """
    if override_value is not None and str(override_value).strip():
        return override_value
    return base_value


def compute_payload_hash(final_fields: dict) -> str:
    """
    Compute hash of final fields for change detection.
    Used to determine if a row needs re-export to CD.
    """
    import json

    # Sort keys for consistent hashing
    content = json.dumps(final_fields, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# =============================================================================
# HEADER ROW
# =============================================================================


def get_header_row() -> list[str]:
    """Get the header row for the Pickups sheet."""
    return get_column_names()


# =============================================================================
# SCHEMA INFO
# =============================================================================

SCHEMA_INFO = {
    "version": SCHEMA_VERSION,
    "total_columns": len(COLUMNS),
    "immutable_count": len(get_immutable_columns()),
    "system_count": len(get_system_columns()),
    "user_count": len(get_user_columns()),
    "base_override_final_fields": get_base_override_final_fields(),
}


if __name__ == "__main__":
    # Print schema info
    print(f"Schema Version: {SCHEMA_VERSION}")
    print(f"Total Columns: {len(COLUMNS)}")
    print(f"Immutable: {len(get_immutable_columns())}")
    print(f"System: {len(get_system_columns())}")
    print(f"User: {len(get_user_columns())}")
    print(f"\nBase/Override/Final fields: {get_base_override_final_fields()}")
    print(f"\nColumn headers:\n{get_header_row()}")
