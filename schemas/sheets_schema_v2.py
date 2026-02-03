"""
Google Sheets Schema v2 - Source of Truth for CD Listings API V2

This schema is designed to map directly to the Central Dispatch Listings API V2:
- ListingRequest: stops[], vehicles[], marketplaces[], price, trailerType, etc.
- 1 row = 1 vehicle = 1 listing (single-vehicle mode)

Schema Version: 2
Last Updated: 2024-01

Column Classes:
- REQUIRED: Must be filled for READY status
- SYSTEM: Updated by automation
- PROTECTED: Never overwritten if has value (override_* fields)
- LOCK: Boolean flags that protect groups of fields
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class ColumnClass(Enum):
    """Column ownership/protection class."""

    REQUIRED = "required"  # Must be filled for export
    SYSTEM = "system"  # Updated by automation
    PROTECTED = "protected"  # Never overwritten if has value
    LOCK = "lock"  # Boolean flag protecting a group


class RowStatus(Enum):
    """Row lifecycle status (state machine)."""

    NEW = "NEW"  # Just imported, not reviewed
    READY = "READY"  # Validated, ready for CD export
    HOLD = "HOLD"  # On hold, don't export
    ERROR = "ERROR"  # Validation or export error
    EXPORTED = "EXPORTED"  # Successfully exported to CD
    RETRY = "RETRY"  # Manual retry requested
    CANCELLED = "CANCELLED"  # Cancelled, don't process


class AuctionSource(Enum):
    """Auction source types."""

    COPART = "COPART"
    IAA = "IAA"
    MANHEIM = "MANHEIM"
    UNKNOWN = "UNKNOWN"


class WarehouseMode(Enum):
    """Warehouse selection mode."""

    AUTO = "AUTO"  # Auto-selected by routing
    MANUAL = "MANUAL"  # Manually selected by operator


SCHEMA_VERSION = 2


@dataclass
class ColumnDef:
    """Column definition."""

    name: str
    col_class: ColumnClass
    required: bool = False
    description: str = ""
    default: Optional[str] = None
    cd_field: Optional[str] = None  # Mapping to CD API field


# =============================================================================
# SCHEMA COLUMNS - Organized by CD Listings API V2 structure
# =============================================================================

COLUMNS: list[ColumnDef] = [
    # =========================================================================
    # 1. IDENTITY & SOURCES
    # =========================================================================
    ColumnDef(
        name="dispatch_id",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Primary key. Format: DC-YYYYMMDD-AUCTION-HASH",
        cd_field="shipperReferenceNumber",
    ),
    ColumnDef(
        name="row_status",
        col_class=ColumnClass.SYSTEM,
        required=True,
        default="NEW",
        description="Row lifecycle: NEW|READY|HOLD|ERROR|EXPORTED|RETRY|CANCELLED",
    ),
    ColumnDef(
        name="auction_source",
        col_class=ColumnClass.SYSTEM,
        required=True,
        description="COPART|IAA|MANHEIM|UNKNOWN",
    ),
    ColumnDef(
        name="auction_reference",
        col_class=ColumnClass.SYSTEM,
        description="Lot/order/release ID from auction",
    ),
    ColumnDef(
        name="gate_pass",
        col_class=ColumnClass.SYSTEM,
        description="Gate pass code",
    ),
    ColumnDef(
        name="attachment_hash",
        col_class=ColumnClass.SYSTEM,
        description="SHA256 of source PDF",
    ),
    ColumnDef(
        name="email_message_id",
        col_class=ColumnClass.SYSTEM,
        description="Source email Message-ID",
    ),
    ColumnDef(
        name="ingested_at",
        col_class=ColumnClass.SYSTEM,
        description="First import timestamp",
    ),
    ColumnDef(
        name="updated_at",
        col_class=ColumnClass.SYSTEM,
        description="Last update timestamp",
    ),
    ColumnDef(
        name="extraction_score",
        col_class=ColumnClass.SYSTEM,
        description="Parser confidence 0.0-1.0",
    ),
    # =========================================================================
    # 2. VEHICLE (vehicles[0] in CD API)
    # =========================================================================
    ColumnDef(
        name="vin",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Vehicle Identification Number",
        cd_field="vehicles[0].vin",
    ),
    ColumnDef(
        name="year",
        col_class=ColumnClass.SYSTEM,
        description="Vehicle year",
        cd_field="vehicles[0].year",
    ),
    ColumnDef(
        name="make",
        col_class=ColumnClass.SYSTEM,
        description="Vehicle make",
        cd_field="vehicles[0].make",
    ),
    ColumnDef(
        name="model",
        col_class=ColumnClass.SYSTEM,
        description="Vehicle model",
        cd_field="vehicles[0].model",
    ),
    ColumnDef(
        name="vehicle_type",
        col_class=ColumnClass.SYSTEM,
        description="Vehicle type (car/suv/truck/van/motorcycle)",
        cd_field="vehicles[0].vehicleType",
    ),
    ColumnDef(
        name="operable",
        col_class=ColumnClass.SYSTEM,
        description="Is vehicle operable (TRUE/FALSE)",
        cd_field="vehicles[0].operable",
    ),
    ColumnDef(
        name="notes_vehicle",
        col_class=ColumnClass.SYSTEM,
        description="Vehicle notes",
        cd_field="vehicles[0].notes",
    ),
    # Vehicle overrides
    ColumnDef(
        name="override_vin",
        col_class=ColumnClass.PROTECTED,
        description="Manual VIN override",
    ),
    ColumnDef(
        name="override_year",
        col_class=ColumnClass.PROTECTED,
        description="Manual year override",
    ),
    ColumnDef(
        name="override_make",
        col_class=ColumnClass.PROTECTED,
        description="Manual make override",
    ),
    ColumnDef(
        name="override_model",
        col_class=ColumnClass.PROTECTED,
        description="Manual model override",
    ),
    ColumnDef(
        name="override_operable",
        col_class=ColumnClass.PROTECTED,
        description="Manual operable override",
    ),
    # =========================================================================
    # 3. PICKUP STOP (stops[0] in CD API)
    # =========================================================================
    ColumnDef(
        name="pickup_site_id",
        col_class=ColumnClass.SYSTEM,
        description="Pickup site ID (optional)",
        cd_field="stops[0].siteId",
    ),
    ColumnDef(
        name="pickup_street1",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Pickup street address line 1",
        cd_field="stops[0].location.street1",
    ),
    ColumnDef(
        name="pickup_street2",
        col_class=ColumnClass.SYSTEM,
        description="Pickup street address line 2",
        cd_field="stops[0].location.street2",
    ),
    ColumnDef(
        name="pickup_city",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Pickup city",
        cd_field="stops[0].location.city",
    ),
    ColumnDef(
        name="pickup_state",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Pickup state (2-letter)",
        cd_field="stops[0].location.state",
    ),
    ColumnDef(
        name="pickup_postal_code",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Pickup ZIP/postal code",
        cd_field="stops[0].location.postalCode",
    ),
    ColumnDef(
        name="pickup_country",
        col_class=ColumnClass.REQUIRED,
        required=True,
        default="US",
        description="Pickup country (US|CA)",
        cd_field="stops[0].location.country",
    ),
    ColumnDef(
        name="pickup_phone",
        col_class=ColumnClass.SYSTEM,
        description="Pickup location phone",
        cd_field="stops[0].location.phone",
    ),
    ColumnDef(
        name="pickup_phone2",
        col_class=ColumnClass.SYSTEM,
        description="Pickup location phone 2",
        cd_field="stops[0].location.phone2",
    ),
    ColumnDef(
        name="pickup_phone3",
        col_class=ColumnClass.SYSTEM,
        description="Pickup location phone 3",
        cd_field="stops[0].location.phone3",
    ),
    ColumnDef(
        name="pickup_contact_name",
        col_class=ColumnClass.SYSTEM,
        description="Pickup contact name",
        cd_field="stops[0].contact.name",
    ),
    ColumnDef(
        name="pickup_contact_phone",
        col_class=ColumnClass.SYSTEM,
        description="Pickup contact phone",
        cd_field="stops[0].contact.phone",
    ),
    ColumnDef(
        name="pickup_contact_cell",
        col_class=ColumnClass.SYSTEM,
        description="Pickup contact cell",
        cd_field="stops[0].contact.cellPhone",
    ),
    ColumnDef(
        name="pickup_instructions",
        col_class=ColumnClass.SYSTEM,
        description="Pickup instructions",
        cd_field="stops[0].instructions",
    ),
    # Pickup overrides
    ColumnDef(
        name="override_pickup_street1",
        col_class=ColumnClass.PROTECTED,
        description="Manual pickup address override",
    ),
    ColumnDef(
        name="override_pickup_city",
        col_class=ColumnClass.PROTECTED,
        description="Manual pickup city override",
    ),
    ColumnDef(
        name="override_pickup_state",
        col_class=ColumnClass.PROTECTED,
        description="Manual pickup state override",
    ),
    ColumnDef(
        name="override_pickup_postal_code",
        col_class=ColumnClass.PROTECTED,
        description="Manual pickup ZIP override",
    ),
    # =========================================================================
    # 4. DELIVERY STOP (stops[1] in CD API)
    # =========================================================================
    ColumnDef(
        name="delivery_warehouse_id",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Delivery warehouse ID (FK to Warehouses)",
    ),
    ColumnDef(
        name="delivery_street1",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Delivery street address line 1",
        cd_field="stops[1].location.street1",
    ),
    ColumnDef(
        name="delivery_street2",
        col_class=ColumnClass.SYSTEM,
        description="Delivery street address line 2",
        cd_field="stops[1].location.street2",
    ),
    ColumnDef(
        name="delivery_city",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Delivery city",
        cd_field="stops[1].location.city",
    ),
    ColumnDef(
        name="delivery_state",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Delivery state (2-letter)",
        cd_field="stops[1].location.state",
    ),
    ColumnDef(
        name="delivery_postal_code",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Delivery ZIP/postal code",
        cd_field="stops[1].location.postalCode",
    ),
    ColumnDef(
        name="delivery_country",
        col_class=ColumnClass.REQUIRED,
        required=True,
        default="US",
        description="Delivery country (US|CA)",
        cd_field="stops[1].location.country",
    ),
    ColumnDef(
        name="delivery_phone",
        col_class=ColumnClass.SYSTEM,
        description="Delivery location phone",
        cd_field="stops[1].location.phone",
    ),
    ColumnDef(
        name="delivery_contact_name",
        col_class=ColumnClass.SYSTEM,
        description="Delivery contact name",
        cd_field="stops[1].contact.name",
    ),
    ColumnDef(
        name="delivery_contact_phone",
        col_class=ColumnClass.SYSTEM,
        description="Delivery contact phone",
        cd_field="stops[1].contact.phone",
    ),
    ColumnDef(
        name="delivery_instructions",
        col_class=ColumnClass.SYSTEM,
        description="Delivery instructions",
        cd_field="stops[1].instructions",
    ),
    # Delivery overrides
    ColumnDef(
        name="override_delivery_street1",
        col_class=ColumnClass.PROTECTED,
        description="Manual delivery address override",
    ),
    ColumnDef(
        name="override_delivery_city",
        col_class=ColumnClass.PROTECTED,
        description="Manual delivery city override",
    ),
    ColumnDef(
        name="override_delivery_state",
        col_class=ColumnClass.PROTECTED,
        description="Manual delivery state override",
    ),
    ColumnDef(
        name="override_delivery_postal_code",
        col_class=ColumnClass.PROTECTED,
        description="Manual delivery ZIP override",
    ),
    # =========================================================================
    # 5. WAREHOUSE SELECTION
    # =========================================================================
    ColumnDef(
        name="warehouse_recommended_id",
        col_class=ColumnClass.SYSTEM,
        description="Auto-recommended warehouse ID",
    ),
    ColumnDef(
        name="warehouse_recommended_distance_mi",
        col_class=ColumnClass.SYSTEM,
        description="Distance to recommended warehouse (miles)",
    ),
    ColumnDef(
        name="warehouse_selected_mode",
        col_class=ColumnClass.SYSTEM,
        default="AUTO",
        description="Selection mode: AUTO|MANUAL",
    ),
    ColumnDef(
        name="warehouse_selected_at",
        col_class=ColumnClass.SYSTEM,
        description="When warehouse was selected",
    ),
    # =========================================================================
    # 6. DATES / AVAILABILITY (ListingRequest)
    # =========================================================================
    ColumnDef(
        name="available_datetime",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="When vehicle is available for pickup",
        cd_field="availableDateTime",
    ),
    ColumnDef(
        name="expiration_datetime",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Listing expiration datetime",
        cd_field="expirationDateTime",
    ),
    ColumnDef(
        name="override_available_datetime",
        col_class=ColumnClass.PROTECTED,
        description="Manual available datetime override",
    ),
    ColumnDef(
        name="override_expiration_datetime",
        col_class=ColumnClass.PROTECTED,
        description="Manual expiration datetime override",
    ),
    # =========================================================================
    # 7. TRAILER / LOAD FLAGS (ListingRequest)
    # =========================================================================
    ColumnDef(
        name="trailer_type",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Trailer type (OPEN|ENCLOSED|DRIVEAWAY)",
        cd_field="trailerType",
    ),
    ColumnDef(
        name="allow_full_load",
        col_class=ColumnClass.SYSTEM,
        default="TRUE",
        description="Allow full load",
        cd_field="allowFullLoad",
    ),
    ColumnDef(
        name="allow_ltl",
        col_class=ColumnClass.SYSTEM,
        default="TRUE",
        description="Allow less than load",
        cd_field="allowLtl",
    ),
    ColumnDef(
        name="override_trailer_type",
        col_class=ColumnClass.PROTECTED,
        description="Manual trailer type override",
    ),
    # =========================================================================
    # 8. PRICE (ListingRequest.price)
    # =========================================================================
    ColumnDef(
        name="price_type",
        col_class=ColumnClass.REQUIRED,
        required=True,
        default="TOTAL",
        description="Price type (TOTAL|PER_MILE|PER_VEHICLE)",
        cd_field="price.type",
    ),
    ColumnDef(
        name="price_currency",
        col_class=ColumnClass.REQUIRED,
        required=True,
        default="USD",
        description="Price currency",
        cd_field="price.currency",
    ),
    ColumnDef(
        name="price_amount",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Price amount",
        cd_field="price.amount",
    ),
    ColumnDef(
        name="override_price_amount",
        col_class=ColumnClass.PROTECTED,
        description="Manual price override",
    ),
    # COD (Cash on Delivery)
    ColumnDef(
        name="cod_type",
        col_class=ColumnClass.SYSTEM,
        description="COD type",
        cd_field="price.cod.type",
    ),
    ColumnDef(
        name="cod_amount",
        col_class=ColumnClass.SYSTEM,
        description="COD amount",
        cd_field="price.cod.amount",
    ),
    ColumnDef(
        name="cod_payment_method",
        col_class=ColumnClass.SYSTEM,
        description="COD payment method",
        cd_field="price.cod.paymentMethod",
    ),
    ColumnDef(
        name="cod_payment_note",
        col_class=ColumnClass.SYSTEM,
        description="COD payment note",
        cd_field="price.cod.paymentMethodNote",
    ),
    ColumnDef(
        name="cod_aux_payment_method",
        col_class=ColumnClass.SYSTEM,
        description="COD auxiliary payment method",
        cd_field="price.cod.auxiliaryPaymentMethod",
    ),
    ColumnDef(
        name="cod_aux_payment_note",
        col_class=ColumnClass.SYSTEM,
        description="COD auxiliary payment note",
        cd_field="price.cod.auxiliaryPaymentMethodNote",
    ),
    # Balance
    ColumnDef(
        name="balance_type",
        col_class=ColumnClass.SYSTEM,
        description="Balance type",
        cd_field="price.balance.type",
    ),
    ColumnDef(
        name="balance_amount",
        col_class=ColumnClass.SYSTEM,
        description="Balance amount",
        cd_field="price.balance.amount",
    ),
    ColumnDef(
        name="balance_payment_method",
        col_class=ColumnClass.SYSTEM,
        description="Balance payment method",
        cd_field="price.balance.paymentMethod",
    ),
    ColumnDef(
        name="balance_payment_note",
        col_class=ColumnClass.SYSTEM,
        description="Balance payment note",
        cd_field="price.balance.paymentMethodNote",
    ),
    # =========================================================================
    # 9. MARKETPLACE / SLA / COMPANY (ListingRequest)
    # =========================================================================
    ColumnDef(
        name="company_name",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Company name for listing",
        cd_field="companyName",
    ),
    ColumnDef(
        name="marketplace_ids",
        col_class=ColumnClass.REQUIRED,
        required=True,
        description="Marketplace IDs (comma-separated or JSON)",
        cd_field="marketplaces",
    ),
    ColumnDef(
        name="sla_duration",
        col_class=ColumnClass.SYSTEM,
        description="SLA duration",
        cd_field="sla.duration",
    ),
    ColumnDef(
        name="sla_timezone_offset",
        col_class=ColumnClass.SYSTEM,
        description="SLA timezone offset",
        cd_field="sla.timeZoneOffset",
    ),
    ColumnDef(
        name="sla_rollover_time",
        col_class=ColumnClass.SYSTEM,
        description="SLA rollover time",
        cd_field="sla.rolloverTime",
    ),
    ColumnDef(
        name="sla_include_current_day",
        col_class=ColumnClass.SYSTEM,
        description="Include current day after rollover",
        cd_field="sla.includeCurrentDayAfterRollOver",
    ),
    # =========================================================================
    # 10. RELEASE NOTES / TAGS
    # =========================================================================
    ColumnDef(
        name="release_notes",
        col_class=ColumnClass.SYSTEM,
        description="Release notes text",
        cd_field="notes",
    ),
    ColumnDef(
        name="tags_json",
        col_class=ColumnClass.SYSTEM,
        description="Tags as JSON array",
        cd_field="tags",
    ),
    # =========================================================================
    # 11. EXPORT RESULTS / AUDIT
    # =========================================================================
    ColumnDef(
        name="cd_listing_id",
        col_class=ColumnClass.SYSTEM,
        description="CD listing ID after export",
    ),
    ColumnDef(
        name="cd_exported_at",
        col_class=ColumnClass.SYSTEM,
        description="When exported to CD",
    ),
    ColumnDef(
        name="cd_last_error",
        col_class=ColumnClass.SYSTEM,
        description="Last CD export error",
    ),
    ColumnDef(
        name="cd_last_attempt_at",
        col_class=ColumnClass.SYSTEM,
        description="Last CD export attempt",
    ),
    ColumnDef(
        name="cd_payload_snapshot",
        col_class=ColumnClass.SYSTEM,
        description="Sent payload JSON snapshot",
    ),
    ColumnDef(
        name="clickup_task_url",
        col_class=ColumnClass.SYSTEM,
        description="ClickUp task URL",
    ),
    ColumnDef(
        name="clickup_task_id",
        col_class=ColumnClass.SYSTEM,
        description="ClickUp task ID",
    ),
    # =========================================================================
    # 12. LOCK FLAGS (protection controls)
    # =========================================================================
    ColumnDef(
        name="lock_release_notes",
        col_class=ColumnClass.LOCK,
        default="FALSE",
        description="Lock release_notes from import updates",
    ),
    ColumnDef(
        name="lock_delivery",
        col_class=ColumnClass.LOCK,
        default="FALSE",
        description="Lock delivery_* fields from import updates",
    ),
    ColumnDef(
        name="lock_all",
        col_class=ColumnClass.LOCK,
        default="FALSE",
        description="Lock all fields except audit from import",
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


def get_column_index(name: str) -> int:
    """Get 0-based column index by name."""
    names = get_column_names()
    try:
        return names.index(name)
    except ValueError:
        return -1


def column_index_to_letter(index: int) -> str:
    """Convert 0-based column index to Excel-style letter."""
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


def get_required_columns() -> list[str]:
    """Get names of required columns."""
    return [col.name for col in COLUMNS if col.required]


def get_protected_columns() -> list[str]:
    """Get names of protected (override_*) columns."""
    return [col.name for col in COLUMNS if col.col_class == ColumnClass.PROTECTED]


def get_lock_columns() -> list[str]:
    """Get names of lock flag columns."""
    return [col.name for col in COLUMNS if col.col_class == ColumnClass.LOCK]


def get_cd_field_mapping() -> dict[str, str]:
    """Get mapping of column names to CD API fields."""
    return {col.name: col.cd_field for col in COLUMNS if col.cd_field}


# =============================================================================
# DISPATCH_ID GENERATION
# =============================================================================


def generate_dispatch_id(
    auction_source: str,
    gate_pass: Optional[str] = None,
    auction_reference: Optional[str] = None,
    vin: Optional[str] = None,
    attachment_hash: Optional[str] = None,
    date: Optional[datetime] = None,
) -> str:
    """
    Generate dispatch_id (primary key).

    Format: DC-YYYYMMDD-AUCTION-HASH

    The HASH part is computed from:
    1. gate_pass (if available)
    2. auction_reference (if available)
    3. vin (if available)
    4. attachment_hash (fallback)
    """
    # Date part
    dt = date or datetime.now()
    date_str = dt.strftime("%Y%m%d")

    # Auction part (normalized)
    auction = auction_source.upper() if auction_source else "UNK"
    if auction not in ("COPART", "IAA", "MANHEIM"):
        auction = "UNK"

    # Hash part - use first available identifier
    hash_input = None
    if gate_pass and gate_pass.strip():
        hash_input = f"gp:{gate_pass.strip().lower()}"
    elif auction_reference and auction_reference.strip():
        hash_input = f"ref:{auction_reference.strip().lower()}"
    elif vin and vin.strip():
        hash_input = f"vin:{vin.strip().upper()}"
    elif attachment_hash and attachment_hash.strip():
        hash_input = f"hash:{attachment_hash.strip().lower()}"
    else:
        # Fallback to timestamp
        hash_input = f"ts:{dt.isoformat()}"

    short_hash = hashlib.sha1(hash_input.encode()).hexdigest()[:8].upper()

    return f"DC-{date_str}-{auction}-{short_hash}"


# =============================================================================
# FINAL VALUE RESOLUTION
# =============================================================================


def get_final_value(row: dict[str, Any], field: str) -> Any:
    """
    Get the final value for a field, considering overrides.

    If override_{field} exists and has a value, use it.
    Otherwise, use the base field value.
    """
    override_key = f"override_{field}"
    override_value = row.get(override_key)

    if override_value is not None and str(override_value).strip():
        return override_value

    return row.get(field)


def apply_overrides(row: dict[str, Any]) -> dict[str, Any]:
    """
    Apply all overrides to get final values.
    Returns a dict with resolved values.
    """
    result = dict(row)

    # List of fields that can have overrides
    override_fields = [
        "vin",
        "year",
        "make",
        "model",
        "operable",
        "pickup_street1",
        "pickup_city",
        "pickup_state",
        "pickup_postal_code",
        "delivery_street1",
        "delivery_city",
        "delivery_state",
        "delivery_postal_code",
        "available_datetime",
        "expiration_datetime",
        "trailer_type",
        "price_amount",
    ]

    for field in override_fields:
        final = get_final_value(row, field)
        if final is not None:
            result[f"_final_{field}"] = final

    return result


# =============================================================================
# VALIDATION
# =============================================================================


def validate_row_for_ready(row: dict[str, Any]) -> list[str]:
    """
    Validate a row before setting status to READY.
    Returns list of error messages (empty if valid).
    """
    errors = []
    row = apply_overrides(row)

    # Required fields check
    required_checks = [
        ("dispatch_id", "dispatch_id is required"),
        ("vin", "VIN is required"),
        ("pickup_street1", "Pickup street address is required"),
        ("pickup_city", "Pickup city is required"),
        ("pickup_state", "Pickup state is required"),
        ("pickup_postal_code", "Pickup postal code is required"),
        ("delivery_warehouse_id", "Delivery warehouse is required"),
        ("delivery_street1", "Delivery street address is required"),
        ("delivery_city", "Delivery city is required"),
        ("delivery_state", "Delivery state is required"),
        ("delivery_postal_code", "Delivery postal code is required"),
        ("available_datetime", "Available datetime is required"),
        ("expiration_datetime", "Expiration datetime is required"),
        ("trailer_type", "Trailer type is required"),
        ("price_amount", "Price amount is required"),
        ("company_name", "Company name is required"),
        ("marketplace_ids", "Marketplace IDs is required"),
    ]

    for field, msg in required_checks:
        # Check both base and final value
        value = row.get(f"_final_{field}") or row.get(field)
        if not value or not str(value).strip():
            errors.append(msg)

    # VIN validation (17 chars)
    vin = row.get("_final_vin") or row.get("vin")
    if vin and len(str(vin).strip()) != 17:
        errors.append(f"VIN must be 17 characters (got {len(str(vin).strip())})")

    # Price validation
    price = row.get("_final_price_amount") or row.get("price_amount")
    try:
        if price and float(str(price).replace(",", "").replace("$", "")) <= 0:
            errors.append("Price amount must be greater than 0")
    except ValueError:
        errors.append("Price amount must be a valid number")

    # Date validation
    avail = row.get("_final_available_datetime") or row.get("available_datetime")
    expir = row.get("_final_expiration_datetime") or row.get("expiration_datetime")
    if avail and expir:
        try:
            # Simple string comparison for ISO dates
            if str(expir) <= str(avail):
                errors.append("Expiration datetime must be after available datetime")
        except Exception:
            pass

    # Trailer type validation
    trailer = row.get("_final_trailer_type") or row.get("trailer_type")
    if trailer and str(trailer).upper() not in ("OPEN", "ENCLOSED", "DRIVEAWAY"):
        errors.append(f"Invalid trailer type: {trailer}")

    return errors


# =============================================================================
# SCHEMA INFO
# =============================================================================

SCHEMA_INFO = {
    "version": SCHEMA_VERSION,
    "total_columns": len(COLUMNS),
    "required_columns": len(get_required_columns()),
    "protected_columns": len(get_protected_columns()),
    "lock_columns": len(get_lock_columns()),
}


if __name__ == "__main__":
    print(f"Schema Version: {SCHEMA_VERSION}")
    print(f"Total Columns: {len(COLUMNS)}")
    print(f"Required: {len(get_required_columns())}")
    print(f"Protected (override_*): {len(get_protected_columns())}")
    print(f"Lock flags: {len(get_lock_columns())}")
    print(f"\nSample dispatch_id: {generate_dispatch_id('COPART', gate_pass='ABC123')}")
