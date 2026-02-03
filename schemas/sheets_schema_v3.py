"""
Google Sheets Schema v3 - Source of Truth for CD Listings API V2

This schema is designed to EXACTLY match Central Dispatch Listings API V2:
- externalId (dispatch_id) as primary key
- Flat stops[] structure (address, city, state, postalCode, country)
- vehicles[] with pickupStopNumber, dropoffStopNumber, isInoperable
- price.total, cod{}, balance{} structure
- marketplaces[] with marketplaceId (int) and flags

Schema Version: 3
Based on: CD Listings API V2 (Create Listing endpoint)

Column Classes:
- PK: Primary key (dispatch_id)
- SYSTEM: Updated by automation (timestamps, hashes, scores)
- AUDIT: Export tracking (cd_listing_id, cd_exported_at, etc.)
- LOCK: Boolean flags that protect groups of fields
- BASE: Business data from extraction (can be filled by ingestion)
- OVERRIDE: Manual corrections (never written by ingestion)
"""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Optional


class ColumnClass(Enum):
    """Column ownership/protection class."""

    PK = "pk"  # Primary key
    SYSTEM = "system"  # Updated by automation
    AUDIT = "audit"  # Export tracking
    LOCK = "lock"  # Boolean protection flags
    BASE = "base"  # Business data from extraction
    OVERRIDE = "override"  # Manual corrections (never written by ingestion)


class RowStatus(Enum):
    """Row lifecycle status (state machine)."""

    NEW = "NEW"  # Just imported, not reviewed
    READY = "READY"  # Validated, ready for CD export
    HOLD = "HOLD"  # On hold, don't export
    ERROR = "ERROR"  # Validation or export error
    EXPORTED = "EXPORTED"  # Successfully exported to CD
    RETRY = "RETRY"  # Manual retry requested
    CANCELLED = "CANCELLED"  # Cancelled, don't process


# Valid state transitions
VALID_TRANSITIONS = {
    RowStatus.NEW: [RowStatus.READY, RowStatus.HOLD, RowStatus.CANCELLED],
    RowStatus.READY: [RowStatus.EXPORTED, RowStatus.ERROR, RowStatus.HOLD, RowStatus.CANCELLED],
    RowStatus.ERROR: [RowStatus.RETRY, RowStatus.HOLD, RowStatus.CANCELLED],
    RowStatus.RETRY: [RowStatus.EXPORTED, RowStatus.ERROR, RowStatus.HOLD],
    RowStatus.HOLD: [RowStatus.READY, RowStatus.CANCELLED],
    RowStatus.EXPORTED: [],  # Terminal by default
    RowStatus.CANCELLED: [],  # Terminal
}


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


class TrailerType(Enum):
    """Trailer types for CD API."""

    OPEN = "OPEN"
    ENCLOSED = "ENCLOSED"
    DRIVEAWAY = "DRIVEAWAY"


class PaymentMethod(Enum):
    """Payment methods for CD API."""

    CASH = "CASH"
    CHECK = "CHECK"
    ACH = "ACH"
    WIRE = "WIRE"
    USHIP_PAYMENTS = "USHIP_PAYMENTS"
    COMCHECK = "COMCHECK"
    TCHECKS = "TCHECKS"
    COMPANY_CHECK = "COMPANY_CHECK"
    CASHIERS_CHECK = "CASHIERS_CHECK"
    MONEY_ORDER = "MONEY_ORDER"
    OTHER = "OTHER"


class PaymentLocation(Enum):
    """COD payment locations."""

    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class PaymentTime(Enum):
    """Balance payment time."""

    IMMEDIATELY = "IMMEDIATELY"
    UPON_PICKUP = "UPON_PICKUP"
    UPON_DELIVERY = "UPON_DELIVERY"
    DAYS_AFTER_PICKUP = "DAYS_AFTER_PICKUP"
    DAYS_AFTER_DELIVERY = "DAYS_AFTER_DELIVERY"


class BalanceTermsBeginOn(Enum):
    """Balance terms begin on."""

    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class LocationType(Enum):
    """Stop location types."""

    BUSINESS = "BUSINESS"
    RESIDENCE = "RESIDENCE"
    AUCTION = "AUCTION"
    PORT = "PORT"
    AIRPORT = "AIRPORT"
    DEALER = "DEALER"
    STORAGE = "STORAGE"
    OTHER = "OTHER"


class VehicleType(Enum):
    """Vehicle types for CD API."""

    SEDAN = "SEDAN"
    COUPE = "COUPE"
    CONVERTIBLE = "CONVERTIBLE"
    HATCHBACK = "HATCHBACK"
    STATION_WAGON = "STATION_WAGON"
    VAN = "VAN"
    MINIVAN = "MINIVAN"
    SPORT_UTILITY = "SPORT_UTILITY"
    PICKUP = "PICKUP"
    MOTORCYCLE = "MOTORCYCLE"
    ATV = "ATV"
    BOAT = "BOAT"
    RV = "RV"
    OTHER = "OTHER"


SCHEMA_VERSION = 3


@dataclass
class ColumnDef:
    """Column definition."""

    name: str
    col_class: ColumnClass
    required_for_ready: bool = False
    description: str = ""
    default: Optional[str] = None
    cd_field: Optional[str] = None  # Mapping to CD API field path


# =============================================================================
# SCHEMA COLUMNS - Organized by CD Listings API V2 structure
# =============================================================================

COLUMNS: list[ColumnDef] = [
    # =========================================================================
    # 1. IDENTITY & SYSTEM FIELDS
    # =========================================================================
    ColumnDef(
        name="dispatch_id",
        col_class=ColumnClass.PK,
        required_for_ready=True,
        description="Primary key. Format: DC-YYYYMMDD-AUCTION-HASH. Maps to externalId (<=50)",
        cd_field="externalId",
    ),
    ColumnDef(
        name="row_status",
        col_class=ColumnClass.SYSTEM,
        required_for_ready=True,
        default="NEW",
        description="Row lifecycle: NEW|READY|HOLD|ERROR|EXPORTED|RETRY|CANCELLED",
    ),
    ColumnDef(
        name="auction_source",
        col_class=ColumnClass.SYSTEM,
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
        name="ingested_at",
        col_class=ColumnClass.SYSTEM,
        description="First import timestamp (ISO 8601)",
    ),
    ColumnDef(
        name="updated_at",
        col_class=ColumnClass.SYSTEM,
        description="Last update timestamp (ISO 8601)",
    ),
    ColumnDef(
        name="extraction_score",
        col_class=ColumnClass.SYSTEM,
        description="Parser confidence 0-100",
    ),
    # =========================================================================
    # 2. WAREHOUSE SELECTION
    # =========================================================================
    ColumnDef(
        name="warehouse_selected_mode",
        col_class=ColumnClass.SYSTEM,
        default="AUTO",
        description="Selection mode: AUTO|MANUAL. MANUAL blocks delivery updates.",
    ),
    ColumnDef(
        name="delivery_warehouse_id",
        col_class=ColumnClass.BASE,
        description="Selected warehouse ID (FK to warehouses.yaml)",
    ),
    ColumnDef(
        name="warehouse_recommended_id",
        col_class=ColumnClass.SYSTEM,
        description="Auto-recommended warehouse ID",
    ),
    # =========================================================================
    # 3. AUDIT / EXPORT TRACKING
    # =========================================================================
    ColumnDef(
        name="cd_listing_id",
        col_class=ColumnClass.AUDIT,
        description="CD listing ID after export",
    ),
    ColumnDef(
        name="cd_exported_at",
        col_class=ColumnClass.AUDIT,
        description="When exported to CD (ISO 8601)",
    ),
    ColumnDef(
        name="cd_last_error",
        col_class=ColumnClass.AUDIT,
        description="Last CD export error message",
    ),
    ColumnDef(
        name="cd_last_attempt_at",
        col_class=ColumnClass.AUDIT,
        description="Last CD export attempt (ISO 8601)",
    ),
    ColumnDef(
        name="cd_payload_snapshot",
        col_class=ColumnClass.AUDIT,
        description="Sent payload JSON snapshot (for debugging)",
    ),
    # =========================================================================
    # 4. LOCK FLAGS (Protection Controls)
    # =========================================================================
    ColumnDef(
        name="lock_all",
        col_class=ColumnClass.LOCK,
        default="FALSE",
        description="Lock ALL fields (only SYSTEM/AUDIT updated by ingestion)",
    ),
    ColumnDef(
        name="lock_delivery",
        col_class=ColumnClass.LOCK,
        default="FALSE",
        description="Lock delivery stop + warehouse fields",
    ),
    ColumnDef(
        name="lock_release_notes",
        col_class=ColumnClass.LOCK,
        default="FALSE",
        description="Lock transportation_release_notes + load_specific_terms",
    ),
    # =========================================================================
    # 5. LISTING IDENTIFIERS (CD API)
    # =========================================================================
    ColumnDef(
        name="shipper_order_id",
        col_class=ColumnClass.BASE,
        description="Optional shipper order ID",
        cd_field="shipperOrderId",
    ),
    ColumnDef(
        name="partner_reference_id",
        col_class=ColumnClass.BASE,
        description="Optional partner reference ID",
        cd_field="partnerReferenceId",
    ),
    # =========================================================================
    # 6. LISTING FLAGS (CD API)
    # =========================================================================
    ColumnDef(
        name="trailer_type",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Trailer type: OPEN|ENCLOSED|DRIVEAWAY",
        cd_field="trailerType",
    ),
    ColumnDef(
        name="has_inop_vehicle",
        col_class=ColumnClass.BASE,
        default="FALSE",
        description="Has inoperable vehicle flag",
        cd_field="hasInOpVehicle",
    ),
    ColumnDef(
        name="load_specific_terms",
        col_class=ColumnClass.BASE,
        description="Load-specific terms text",
        cd_field="loadSpecificTerms",
    ),
    # =========================================================================
    # 7. DATES (CD API) - availableDate, expirationDate, desiredDeliveryDate
    # =========================================================================
    ColumnDef(
        name="available_date",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="When vehicle available for pickup (YYYY-MM-DD). Must be today..+30days.",
        cd_field="availableDate",
    ),
    ColumnDef(
        name="expiration_date",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Listing expiration date (YYYY-MM-DD). Must be > availableDate.",
        cd_field="expirationDate",
    ),
    ColumnDef(
        name="desired_delivery_date",
        col_class=ColumnClass.BASE,
        description="Desired delivery date (YYYY-MM-DD, optional)",
        cd_field="desiredDeliveryDate",
    ),
    # =========================================================================
    # 8. TRANSPORTATION RELEASE NOTES
    # =========================================================================
    ColumnDef(
        name="transportation_release_notes",
        col_class=ColumnClass.BASE,
        description="Transportation release notes text",
        cd_field="transportationReleaseNotes",
    ),
    # =========================================================================
    # 9. PRICE (CD API: price.total, cod{}, balance{})
    # =========================================================================
    ColumnDef(
        name="price_total",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Total price amount (decimal)",
        cd_field="price.total",
    ),
    # COD
    ColumnDef(
        name="cod_amount",
        col_class=ColumnClass.BASE,
        description="COD amount (decimal)",
        cd_field="price.cod.amount",
    ),
    ColumnDef(
        name="cod_payment_method",
        col_class=ColumnClass.BASE,
        description="COD payment method (CASH|CHECK|ACH|WIRE|...)",
        cd_field="price.cod.paymentMethod",
    ),
    ColumnDef(
        name="cod_payment_location",
        col_class=ColumnClass.BASE,
        description="COD payment location (PICKUP|DELIVERY)",
        cd_field="price.cod.paymentLocation",
    ),
    # Balance
    ColumnDef(
        name="balance_amount",
        col_class=ColumnClass.BASE,
        description="Balance amount (decimal)",
        cd_field="price.balance.amount",
    ),
    ColumnDef(
        name="balance_payment_time",
        col_class=ColumnClass.BASE,
        description="Balance payment time (IMMEDIATELY|UPON_PICKUP|UPON_DELIVERY|...)",
        cd_field="price.balance.paymentTime",
    ),
    ColumnDef(
        name="balance_terms_begin_on",
        col_class=ColumnClass.BASE,
        description="Balance terms begin on (PICKUP|DELIVERY)",
        cd_field="price.balance.balancePaymentTermsBeginOn",
    ),
    ColumnDef(
        name="balance_payment_method",
        col_class=ColumnClass.BASE,
        description="Balance payment method",
        cd_field="price.balance.balancePaymentMethod",
    ),
    # =========================================================================
    # 10. SLA (CD API: sla{})
    # =========================================================================
    ColumnDef(
        name="sla_duration",
        col_class=ColumnClass.BASE,
        description="SLA duration (integer days)",
        cd_field="sla.duration",
    ),
    ColumnDef(
        name="sla_time_zone_offset",
        col_class=ColumnClass.BASE,
        description="SLA timezone offset (e.g., -05:00)",
        cd_field="sla.timeZoneOffset",
    ),
    ColumnDef(
        name="sla_rollover_time",
        col_class=ColumnClass.BASE,
        description="SLA rollover time (e.g., 17:00:00)",
        cd_field="sla.rolloverTime",
    ),
    ColumnDef(
        name="sla_include_current_day_after_rollover",
        col_class=ColumnClass.BASE,
        default="FALSE",
        description="Include current day after rollover (TRUE|FALSE)",
        cd_field="sla.includeCurrentDayAfterRollOver",
    ),
    # =========================================================================
    # 11. PICKUP STOP (stops[0]) - Flat structure per CD V2
    # =========================================================================
    ColumnDef(
        name="pickup_stop_number",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        default="1",
        description="Pickup stop number (always 1)",
        cd_field="stops[0].stopNumber",
    ),
    ColumnDef(
        name="pickup_location_name",
        col_class=ColumnClass.BASE,
        description="Pickup location name",
        cd_field="stops[0].locationName",
    ),
    ColumnDef(
        name="pickup_address",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Pickup street address",
        cd_field="stops[0].address",
    ),
    ColumnDef(
        name="pickup_city",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Pickup city",
        cd_field="stops[0].city",
    ),
    ColumnDef(
        name="pickup_state",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Pickup state (2-letter)",
        cd_field="stops[0].state",
    ),
    ColumnDef(
        name="pickup_postal_code",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Pickup ZIP/postal code",
        cd_field="stops[0].postalCode",
    ),
    ColumnDef(
        name="pickup_country",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        default="US",
        description="Pickup country (US|CA)",
        cd_field="stops[0].country",
    ),
    ColumnDef(
        name="pickup_phone",
        col_class=ColumnClass.BASE,
        description="Pickup location phone",
        cd_field="stops[0].phone",
    ),
    ColumnDef(
        name="pickup_contact_name",
        col_class=ColumnClass.BASE,
        description="Pickup contact name",
        cd_field="stops[0].contactName",
    ),
    ColumnDef(
        name="pickup_contact_phone",
        col_class=ColumnClass.BASE,
        description="Pickup contact phone",
        cd_field="stops[0].contactPhone",
    ),
    ColumnDef(
        name="pickup_location_type",
        col_class=ColumnClass.BASE,
        description="Pickup location type (BUSINESS|RESIDENCE|AUCTION|...)",
        cd_field="stops[0].locationType",
    ),
    # =========================================================================
    # 12. DROPOFF STOP (stops[1]) - Flat structure per CD V2
    # =========================================================================
    ColumnDef(
        name="dropoff_stop_number",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        default="2",
        description="Dropoff stop number (always 2)",
        cd_field="stops[1].stopNumber",
    ),
    ColumnDef(
        name="dropoff_location_name",
        col_class=ColumnClass.BASE,
        description="Dropoff location name",
        cd_field="stops[1].locationName",
    ),
    ColumnDef(
        name="dropoff_address",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Dropoff street address",
        cd_field="stops[1].address",
    ),
    ColumnDef(
        name="dropoff_city",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Dropoff city",
        cd_field="stops[1].city",
    ),
    ColumnDef(
        name="dropoff_state",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Dropoff state (2-letter)",
        cd_field="stops[1].state",
    ),
    ColumnDef(
        name="dropoff_postal_code",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Dropoff ZIP/postal code",
        cd_field="stops[1].postalCode",
    ),
    ColumnDef(
        name="dropoff_country",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        default="US",
        description="Dropoff country (US|CA)",
        cd_field="stops[1].country",
    ),
    ColumnDef(
        name="dropoff_phone",
        col_class=ColumnClass.BASE,
        description="Dropoff location phone",
        cd_field="stops[1].phone",
    ),
    ColumnDef(
        name="dropoff_contact_name",
        col_class=ColumnClass.BASE,
        description="Dropoff contact name",
        cd_field="stops[1].contactName",
    ),
    ColumnDef(
        name="dropoff_contact_phone",
        col_class=ColumnClass.BASE,
        description="Dropoff contact phone",
        cd_field="stops[1].contactPhone",
    ),
    ColumnDef(
        name="dropoff_location_type",
        col_class=ColumnClass.BASE,
        description="Dropoff location type (BUSINESS|RESIDENCE|...)",
        cd_field="stops[1].locationType",
    ),
    # =========================================================================
    # 13. VEHICLE (vehicles[0]) - Per CD V2 structure
    # =========================================================================
    ColumnDef(
        name="vehicle_external_vehicle_id",
        col_class=ColumnClass.BASE,
        description="External vehicle ID",
        cd_field="vehicles[0].externalVehicleId",
    ),
    ColumnDef(
        name="vehicle_vin",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Vehicle VIN (17 characters)",
        cd_field="vehicles[0].vin",
    ),
    ColumnDef(
        name="vehicle_year",
        col_class=ColumnClass.BASE,
        description="Vehicle year",
        cd_field="vehicles[0].year",
    ),
    ColumnDef(
        name="vehicle_make",
        col_class=ColumnClass.BASE,
        description="Vehicle make",
        cd_field="vehicles[0].make",
    ),
    ColumnDef(
        name="vehicle_model",
        col_class=ColumnClass.BASE,
        description="Vehicle model",
        cd_field="vehicles[0].model",
    ),
    ColumnDef(
        name="vehicle_trim",
        col_class=ColumnClass.BASE,
        description="Vehicle trim",
        cd_field="vehicles[0].trim",
    ),
    ColumnDef(
        name="vehicle_type",
        col_class=ColumnClass.BASE,
        description="Vehicle type (SEDAN|COUPE|SUV|PICKUP|...)",
        cd_field="vehicles[0].vehicleType",
    ),
    ColumnDef(
        name="vehicle_color",
        col_class=ColumnClass.BASE,
        description="Vehicle color",
        cd_field="vehicles[0].color",
    ),
    ColumnDef(
        name="vehicle_license_plate",
        col_class=ColumnClass.BASE,
        description="Vehicle license plate",
        cd_field="vehicles[0].licensePlate",
    ),
    ColumnDef(
        name="vehicle_license_plate_state",
        col_class=ColumnClass.BASE,
        description="License plate state (2-letter)",
        cd_field="vehicles[0].licensePlateState",
    ),
    ColumnDef(
        name="vehicle_lot_number",
        col_class=ColumnClass.BASE,
        description="Vehicle lot number",
        cd_field="vehicles[0].lotNumber",
    ),
    ColumnDef(
        name="vehicle_is_inoperable",
        col_class=ColumnClass.BASE,
        default="FALSE",
        description="Is vehicle inoperable (TRUE|FALSE)",
        cd_field="vehicles[0].isInoperable",
    ),
    ColumnDef(
        name="vehicle_tariff",
        col_class=ColumnClass.BASE,
        description="Vehicle tariff amount",
        cd_field="vehicles[0].tariff",
    ),
    ColumnDef(
        name="vehicle_additional_info",
        col_class=ColumnClass.BASE,
        description="Vehicle additional info text",
        cd_field="vehicles[0].additionalInfo",
    ),
    # =========================================================================
    # 14. MARKETPLACE (marketplaces[0]) - Per CD V2 structure
    # =========================================================================
    ColumnDef(
        name="marketplace_id",
        col_class=ColumnClass.BASE,
        required_for_ready=True,
        description="Marketplace ID (integer)",
        cd_field="marketplaces[0].marketplaceId",
    ),
    ColumnDef(
        name="digital_offers_enabled",
        col_class=ColumnClass.BASE,
        default="TRUE",
        description="Enable digital offers (TRUE|FALSE)",
        cd_field="marketplaces[0].digitalOffersEnabled",
    ),
    ColumnDef(
        name="searchable",
        col_class=ColumnClass.BASE,
        default="TRUE",
        description="Is listing searchable (TRUE|FALSE)",
        cd_field="marketplaces[0].searchable",
    ),
    ColumnDef(
        name="offers_auto_accept_enabled",
        col_class=ColumnClass.BASE,
        default="FALSE",
        description="Auto-accept offers (TRUE|FALSE)",
        cd_field="marketplaces[0].offersAutoAcceptEnabled",
    ),
    ColumnDef(
        name="auto_dispatch_on_offer_accepted",
        col_class=ColumnClass.BASE,
        default="FALSE",
        description="Auto-dispatch on offer accepted (TRUE|FALSE)",
        cd_field="marketplaces[0].autoDispatchOnOfferAccepted",
    ),
    ColumnDef(
        name="predispatch_notes",
        col_class=ColumnClass.BASE,
        description="Pre-dispatch notes",
        cd_field="marketplaces[0].predispatchNotes",
    ),
    ColumnDef(
        name="customers_excluded_from_offers_json",
        col_class=ColumnClass.BASE,
        description="Customers excluded from offers (JSON array)",
        cd_field="marketplaces[0].customersExcludedFromOffers",
    ),
    # =========================================================================
    # 15. TAGS (CD API: tags[])
    # =========================================================================
    ColumnDef(
        name="tags_json",
        col_class=ColumnClass.BASE,
        description="Tags as JSON array of strings",
        cd_field="tags",
    ),
    # =========================================================================
    # 16. OVERRIDE FIELDS (Manual corrections, never written by ingestion)
    # =========================================================================
    # Listing overrides
    ColumnDef(
        name="override_trailer_type",
        col_class=ColumnClass.OVERRIDE,
        description="Manual trailer type override",
    ),
    ColumnDef(
        name="override_available_date",
        col_class=ColumnClass.OVERRIDE,
        description="Manual available date override",
    ),
    ColumnDef(
        name="override_expiration_date",
        col_class=ColumnClass.OVERRIDE,
        description="Manual expiration date override",
    ),
    ColumnDef(
        name="override_desired_delivery_date",
        col_class=ColumnClass.OVERRIDE,
        description="Manual desired delivery date override",
    ),
    ColumnDef(
        name="override_price_total",
        col_class=ColumnClass.OVERRIDE,
        description="Manual price total override",
    ),
    ColumnDef(
        name="override_transportation_release_notes",
        col_class=ColumnClass.OVERRIDE,
        description="Manual release notes override",
    ),
    # Pickup overrides
    ColumnDef(
        name="override_pickup_address",
        col_class=ColumnClass.OVERRIDE,
        description="Manual pickup address override",
    ),
    ColumnDef(
        name="override_pickup_city",
        col_class=ColumnClass.OVERRIDE,
        description="Manual pickup city override",
    ),
    ColumnDef(
        name="override_pickup_state",
        col_class=ColumnClass.OVERRIDE,
        description="Manual pickup state override",
    ),
    ColumnDef(
        name="override_pickup_postal_code",
        col_class=ColumnClass.OVERRIDE,
        description="Manual pickup postal code override",
    ),
    # Dropoff overrides
    ColumnDef(
        name="override_dropoff_address",
        col_class=ColumnClass.OVERRIDE,
        description="Manual dropoff address override",
    ),
    ColumnDef(
        name="override_dropoff_city",
        col_class=ColumnClass.OVERRIDE,
        description="Manual dropoff city override",
    ),
    ColumnDef(
        name="override_dropoff_state",
        col_class=ColumnClass.OVERRIDE,
        description="Manual dropoff state override",
    ),
    ColumnDef(
        name="override_dropoff_postal_code",
        col_class=ColumnClass.OVERRIDE,
        description="Manual dropoff postal code override",
    ),
    # Vehicle overrides
    ColumnDef(
        name="override_vehicle_vin",
        col_class=ColumnClass.OVERRIDE,
        description="Manual VIN override",
    ),
    ColumnDef(
        name="override_vehicle_year",
        col_class=ColumnClass.OVERRIDE,
        description="Manual vehicle year override",
    ),
    ColumnDef(
        name="override_vehicle_make",
        col_class=ColumnClass.OVERRIDE,
        description="Manual vehicle make override",
    ),
    ColumnDef(
        name="override_vehicle_model",
        col_class=ColumnClass.OVERRIDE,
        description="Manual vehicle model override",
    ),
    ColumnDef(
        name="override_vehicle_is_inoperable",
        col_class=ColumnClass.OVERRIDE,
        description="Manual isInoperable override",
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


def get_columns_by_class(col_class: ColumnClass) -> list[str]:
    """Get column names by class."""
    return [col.name for col in COLUMNS if col.col_class == col_class]


def get_required_columns() -> list[str]:
    """Get names of required columns for READY status."""
    return [col.name for col in COLUMNS if col.required_for_ready]


def get_override_columns() -> list[str]:
    """Get names of override columns."""
    return get_columns_by_class(ColumnClass.OVERRIDE)


def get_lock_columns() -> list[str]:
    """Get names of lock flag columns."""
    return get_columns_by_class(ColumnClass.LOCK)


def get_base_columns() -> list[str]:
    """Get names of base (business data) columns."""
    return get_columns_by_class(ColumnClass.BASE)


def get_system_audit_columns() -> list[str]:
    """Get names of SYSTEM and AUDIT columns (always updatable)."""
    return get_columns_by_class(ColumnClass.SYSTEM) + get_columns_by_class(ColumnClass.AUDIT)


def get_delivery_columns() -> list[str]:
    """Get names of delivery-related columns (protected by lock_delivery)."""
    return [col.name for col in COLUMNS if col.name.startswith("dropoff_")]


def get_release_notes_columns() -> list[str]:
    """Get names of release notes columns (protected by lock_release_notes)."""
    return ["transportation_release_notes", "load_specific_terms"]


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

    The HASH part is computed from (in priority order):
    1. gate_pass (if available)
    2. auction_reference (if available)
    3. vin (if available)
    4. attachment_hash (fallback)

    Note: dispatch_id maps to CD externalId (<=50 chars)
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
# FINAL VALUE RESOLUTION (Override Pattern)
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


def get_final_value_with_mapping(row: dict[str, Any], base_field: str, override_field: str) -> Any:
    """
    Get the final value using explicit base and override field names.
    Useful when override naming doesn't follow pattern (e.g., vehicle_vin -> override_vehicle_vin).
    """
    override_value = row.get(override_field)

    if override_value is not None and str(override_value).strip():
        return override_value

    return row.get(base_field)


# Field to override mapping for export
OVERRIDE_MAPPINGS = {
    "trailer_type": "override_trailer_type",
    "available_date": "override_available_date",
    "expiration_date": "override_expiration_date",
    "desired_delivery_date": "override_desired_delivery_date",
    "price_total": "override_price_total",
    "transportation_release_notes": "override_transportation_release_notes",
    "pickup_address": "override_pickup_address",
    "pickup_city": "override_pickup_city",
    "pickup_state": "override_pickup_state",
    "pickup_postal_code": "override_pickup_postal_code",
    "dropoff_address": "override_dropoff_address",
    "dropoff_city": "override_dropoff_city",
    "dropoff_state": "override_dropoff_state",
    "dropoff_postal_code": "override_dropoff_postal_code",
    "vehicle_vin": "override_vehicle_vin",
    "vehicle_year": "override_vehicle_year",
    "vehicle_make": "override_vehicle_make",
    "vehicle_model": "override_vehicle_model",
    "vehicle_is_inoperable": "override_vehicle_is_inoperable",
}


def apply_all_overrides(row: dict[str, Any]) -> dict[str, Any]:
    """
    Apply all overrides to get final values for export.
    Returns a new dict with _final_{field} keys added.
    """
    result = dict(row)

    for base_field, override_field in OVERRIDE_MAPPINGS.items():
        final_value = get_final_value_with_mapping(row, base_field, override_field)
        if final_value is not None:
            result[f"_final_{base_field}"] = final_value

    return result


# =============================================================================
# VALIDATION FOR READY STATUS (CD V2 Requirements)
# =============================================================================


def validate_row_for_ready(row: dict[str, Any]) -> list[str]:
    """
    Validate a row before setting status to READY.
    Returns list of error messages (empty if valid).

    CD V2 Requirements:
    - dispatch_id (<=50 chars)
    - trailer_type (OPEN|ENCLOSED|DRIVEAWAY)
    - available_date (today..+30 days)
    - expiration_date (> available_date)
    - price_total (> 0)
    - marketplace_id (integer)
    - pickup stop: address/city/state/postalCode/country + stopNumber=1
    - dropoff stop: address/city/state/postalCode/country + stopNumber=2
    - vehicle: vin (17 chars), pickupStopNumber=1, dropoffStopNumber=2
    """
    errors = []
    row = apply_all_overrides(row)

    def get_val(field: str) -> Any:
        """Get final value for field."""
        return row.get(f"_final_{field}") or row.get(field)

    # 1. dispatch_id (required, <=50)
    dispatch_id = get_val("dispatch_id")
    if not dispatch_id:
        errors.append("dispatch_id is required")
    elif len(str(dispatch_id)) > 50:
        errors.append(f"dispatch_id must be <=50 chars (got {len(str(dispatch_id))})")

    # 2. trailer_type (required, valid enum)
    trailer_type = get_val("trailer_type")
    if not trailer_type:
        errors.append("trailer_type is required")
    elif str(trailer_type).upper() not in ("OPEN", "ENCLOSED", "DRIVEAWAY"):
        errors.append(f"Invalid trailer_type: {trailer_type}")

    # 3. available_date (required, today..+30 days)
    available_date = get_val("available_date")
    if not available_date:
        errors.append("available_date is required")
    else:
        try:
            if isinstance(available_date, str):
                avail_dt = datetime.strptime(available_date, "%Y-%m-%d").date()
            elif isinstance(available_date, date):
                avail_dt = available_date
            else:
                avail_dt = None
                errors.append(f"Invalid available_date format: {available_date}")

            if avail_dt:
                today = date.today()
                max_date = today + timedelta(days=30)
                if avail_dt < today:
                    errors.append(f"available_date cannot be in the past (got {avail_dt})")
                elif avail_dt > max_date:
                    errors.append(
                        f"available_date cannot be more than 30 days from today (got {avail_dt})"
                    )
        except ValueError as e:
            errors.append(f"Invalid available_date: {e}")

    # 4. expiration_date (required, > available_date)
    expiration_date = get_val("expiration_date")
    if not expiration_date:
        errors.append("expiration_date is required")
    else:
        try:
            if isinstance(expiration_date, str):
                exp_dt = datetime.strptime(expiration_date, "%Y-%m-%d").date()
            elif isinstance(expiration_date, date):
                exp_dt = expiration_date
            else:
                exp_dt = None
                errors.append(f"Invalid expiration_date format: {expiration_date}")

            if exp_dt and available_date:
                try:
                    if isinstance(available_date, str):
                        avail_dt = datetime.strptime(available_date, "%Y-%m-%d").date()
                    else:
                        avail_dt = available_date
                    if exp_dt <= avail_dt:
                        errors.append("expiration_date must be after available_date")
                except ValueError:
                    pass  # Already handled above
        except ValueError as e:
            errors.append(f"Invalid expiration_date: {e}")

    # 5. price_total (required, > 0)
    price_total = get_val("price_total")
    if not price_total:
        errors.append("price_total is required")
    else:
        try:
            price_val = float(str(price_total).replace(",", "").replace("$", ""))
            if price_val <= 0:
                errors.append("price_total must be greater than 0")
        except ValueError:
            errors.append(f"price_total must be a valid number: {price_total}")

    # 6. marketplace_id (required, integer)
    marketplace_id = get_val("marketplace_id")
    if not marketplace_id:
        errors.append("marketplace_id is required")
    else:
        try:
            int(marketplace_id)
        except ValueError:
            errors.append(f"marketplace_id must be an integer: {marketplace_id}")

    # 7. Pickup stop (required fields)
    pickup_required = [
        ("pickup_address", "Pickup address"),
        ("pickup_city", "Pickup city"),
        ("pickup_state", "Pickup state"),
        ("pickup_postal_code", "Pickup postal code"),
        ("pickup_country", "Pickup country"),
    ]
    for field, label in pickup_required:
        if not get_val(field):
            errors.append(f"{label} is required")

    # Pickup stop number (should be 1)
    pickup_stop_num = get_val("pickup_stop_number") or "1"
    if str(pickup_stop_num) != "1":
        errors.append(f"pickup_stop_number must be 1 (got {pickup_stop_num})")

    # 8. Dropoff stop (required fields)
    dropoff_required = [
        ("dropoff_address", "Dropoff address"),
        ("dropoff_city", "Dropoff city"),
        ("dropoff_state", "Dropoff state"),
        ("dropoff_postal_code", "Dropoff postal code"),
        ("dropoff_country", "Dropoff country"),
    ]
    for field, label in dropoff_required:
        if not get_val(field):
            errors.append(f"{label} is required")

    # Dropoff stop number (should be 2)
    dropoff_stop_num = get_val("dropoff_stop_number") or "2"
    if str(dropoff_stop_num) != "2":
        errors.append(f"dropoff_stop_number must be 2 (got {dropoff_stop_num})")

    # 9. Vehicle (required: VIN 17 chars)
    vehicle_vin = get_val("vehicle_vin")
    if not vehicle_vin:
        errors.append("vehicle_vin is required")
    elif len(str(vehicle_vin).strip()) != 17:
        errors.append(f"vehicle_vin must be 17 characters (got {len(str(vehicle_vin).strip())})")

    return errors


def can_transition_to(current_status: RowStatus, new_status: RowStatus) -> bool:
    """Check if state transition is allowed."""
    allowed = VALID_TRANSITIONS.get(current_status, [])
    return new_status in allowed


# =============================================================================
# CSV HEADER GENERATION
# =============================================================================


def get_csv_header() -> str:
    """Get CSV header line for sheet template."""
    return ",".join(get_column_names())


# =============================================================================
# SCHEMA INFO
# =============================================================================

SCHEMA_INFO = {
    "version": SCHEMA_VERSION,
    "total_columns": len(COLUMNS),
    "pk_columns": len(get_columns_by_class(ColumnClass.PK)),
    "system_columns": len(get_columns_by_class(ColumnClass.SYSTEM)),
    "audit_columns": len(get_columns_by_class(ColumnClass.AUDIT)),
    "lock_columns": len(get_columns_by_class(ColumnClass.LOCK)),
    "base_columns": len(get_columns_by_class(ColumnClass.BASE)),
    "override_columns": len(get_columns_by_class(ColumnClass.OVERRIDE)),
    "required_for_ready": len(get_required_columns()),
}


if __name__ == "__main__":
    print(f"Schema Version: {SCHEMA_VERSION}")
    print(f"Total Columns: {len(COLUMNS)}")
    print(f"  PK: {SCHEMA_INFO['pk_columns']}")
    print(f"  SYSTEM: {SCHEMA_INFO['system_columns']}")
    print(f"  AUDIT: {SCHEMA_INFO['audit_columns']}")
    print(f"  LOCK: {SCHEMA_INFO['lock_columns']}")
    print(f"  BASE: {SCHEMA_INFO['base_columns']}")
    print(f"  OVERRIDE: {SCHEMA_INFO['override_columns']}")
    print(f"Required for READY: {SCHEMA_INFO['required_for_ready']}")
    print(f"\nSample dispatch_id: {generate_dispatch_id('COPART', gate_pass='ABC123')}")
    print(f"\nCSV Header ({len(get_column_names())} columns):")
    print(get_csv_header())
