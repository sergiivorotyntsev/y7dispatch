"""
Listing Field Registry - Single Source of Truth for CD Listings API

This module defines all fields for Central Dispatch Listings API V2.
It serves as the canonical source for:
- Frontend form rendering
- Backend validation
- CD API payload building

Schema Reference: Central Dispatch Listings API V2
Content-Type: application/vnd.coxauto.v2+json
"""

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FieldSection(str, Enum):
    """Logical sections for grouping fields in UI."""

    VEHICLE = "vehicle"
    PICKUP = "pickup"
    DELIVERY = "delivery"
    PRICING = "pricing"
    ADDITIONAL = "additional"
    NOTES = "notes"


class FieldType(str, Enum):
    """Field input types."""

    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    TEXTAREA = "textarea"
    BOOLEAN = "boolean"


class FieldCategory(str, Enum):
    """
    Field taxonomy for Central Dispatch integration.

    CD_REQUIRED: Required for CD API submission (blocking if missing)
    CD_OPTIONAL: Optional in CD API (enhances listing quality)
    INTERNAL: Never sent to CD API (for internal tracking only)
    """

    CD_REQUIRED = "cd_required"
    CD_OPTIONAL = "cd_optional"
    INTERNAL = "internal"


class FieldSourceType(str, Enum):
    """
    Default data source for a field (where the value typically comes from).

    EXTRACTED: Value extracted from document (PDF/image)
    CONSTANT: Static value (e.g., auction type defaults)
    WAREHOUSE_REF: Value from warehouse reference data
    USER_INPUT: Value entered manually by user
    COMPUTED: Value computed from other fields
    """

    EXTRACTED = "extracted"
    CONSTANT = "constant"
    WAREHOUSE_REF = "warehouse_ref"
    USER_INPUT = "user_input"
    COMPUTED = "computed"


class ValueSource(str, Enum):
    """Source of field value (for runtime priority resolution)."""

    USER_OVERRIDE = "user_override"  # Manual edit in production
    WAREHOUSE_CONSTANT = "warehouse"  # From warehouse settings
    AUCTION_TYPE_CONSTANT = "auction"  # From auction type defaults
    EXTRACTED = "extracted"  # From ML/rule extraction
    DEFAULT = "default"  # Field default value
    EMPTY = "empty"  # No value


@dataclass
class ListingField:
    """Definition of a single listing field."""

    key: str  # Internal field key (e.g., "vehicle_vin")
    label: str  # Display label
    section: FieldSection  # UI section
    cd_api_key: str  # CD API path (e.g., "vehicles[0].vin"), None for internal fields
    field_type: FieldType = FieldType.TEXT
    required: bool = False  # Required for CD submission
    export_only: bool = False  # If True, only required at export time (not during training)
    display_order: int = 0  # Order within section

    # Field taxonomy and source configuration
    category: FieldCategory = FieldCategory.CD_OPTIONAL  # CD_REQUIRED, CD_OPTIONAL, INTERNAL
    source_type: FieldSourceType = FieldSourceType.EXTRACTED  # Default data source

    # Validation rules
    validation_regex: Optional[str] = None
    validation_message: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    options: list[str] = field(default_factory=list)  # For SELECT type
    default_value: Optional[str] = None
    help_text: Optional[str] = None
    extraction_hint: Optional[str] = None  # Hint for extractors

    # Runtime configuration (can be overridden in settings)
    editable_in_review: bool = True  # Can user edit in Review UI
    visible_in_training: bool = True  # Show in Training mode


# =============================================================================
# FIELD DEFINITIONS - Central Dispatch Listings API V2
# =============================================================================

LISTING_FIELDS: list[ListingField] = [
    # -------------------------------------------------------------------------
    # VEHICLE INFORMATION
    # -------------------------------------------------------------------------
    ListingField(
        key="vehicle_vin",
        label="VIN",
        section=FieldSection.VEHICLE,
        cd_api_key="vehicles[0].vin",
        field_type=FieldType.TEXT,
        required=True,
        display_order=1,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.EXTRACTED,
        validation_regex=r"^[A-HJ-NPR-Z0-9]{17}$",
        validation_message="VIN must be exactly 17 alphanumeric characters (no I, O, Q)",
        min_length=17,
        max_length=17,
        help_text="17-character Vehicle Identification Number",
        extraction_hint="Look for 17-character alphanumeric string, often labeled VIN",
    ),
    ListingField(
        key="vehicle_year",
        label="Year",
        section=FieldSection.VEHICLE,
        cd_api_key="vehicles[0].year",
        field_type=FieldType.NUMBER,
        required=True,
        display_order=2,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.EXTRACTED,
        min_value=1900,
        max_value=2030,
        help_text="Model year (1900-2030)",
        extraction_hint="4-digit year near make/model",
    ),
    ListingField(
        key="vehicle_make",
        label="Make",
        section=FieldSection.VEHICLE,
        cd_api_key="vehicles[0].make",
        field_type=FieldType.TEXT,
        required=True,
        display_order=3,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.EXTRACTED,
        max_length=50,
        help_text="Vehicle manufacturer (e.g., Toyota, Ford)",
        extraction_hint="Manufacturer name, usually before model",
    ),
    ListingField(
        key="vehicle_model",
        label="Model",
        section=FieldSection.VEHICLE,
        cd_api_key="vehicles[0].model",
        field_type=FieldType.TEXT,
        required=True,
        display_order=4,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.EXTRACTED,
        max_length=50,
        help_text="Vehicle model name",
        extraction_hint="Model name after make",
    ),
    ListingField(
        key="vehicle_color",
        label="Color",
        section=FieldSection.VEHICLE,
        cd_api_key="vehicles[0].color",
        field_type=FieldType.TEXT,
        required=False,
        display_order=5,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.EXTRACTED,
        max_length=30,
        help_text="Exterior color",
    ),
    ListingField(
        key="vehicle_type",
        label="Vehicle Type",
        section=FieldSection.VEHICLE,
        cd_api_key="vehicles[0].vehicleType",
        field_type=FieldType.SELECT,
        required=True,
        export_only=True,
        display_order=6,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        options=[
            "SEDAN",
            "SUV",
            "TRUCK",
            "VAN",
            "MOTORCYCLE",
            "COUPE",
            "CONVERTIBLE",
            "WAGON",
            "OTHER",
        ],
        default_value="SEDAN",
        help_text="Vehicle body type",
    ),
    ListingField(
        key="vehicle_condition",
        label="Condition",
        section=FieldSection.VEHICLE,
        cd_api_key="vehicles[0].isOperable",
        field_type=FieldType.SELECT,
        required=True,
        export_only=True,
        display_order=7,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        options=["OPERABLE", "INOPERABLE"],
        default_value="OPERABLE",
        help_text="Can the vehicle be driven onto a trailer?",
    ),
    ListingField(
        key="vehicle_is_inoperable",
        label="Inoperable",
        section=FieldSection.VEHICLE,
        cd_api_key="hasInOpVehicle",
        field_type=FieldType.BOOLEAN,
        required=False,
        display_order=7,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.EXTRACTED,
        default_value="false",
        help_text="Is the vehicle inoperable/non-running? Extracted from document keywords.",
    ),
    ListingField(
        key="vehicle_lot",
        label="Lot/Stock Number",
        section=FieldSection.VEHICLE,
        cd_api_key="vehicles[0].lotNumber",
        field_type=FieldType.TEXT,
        required=False,
        display_order=8,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.EXTRACTED,
        max_length=50,
        help_text="Auction lot number (Copart: Lot #, IAA: Stock #)",
        extraction_hint="LOT, LOT #, LOT NUMBER, STOCK, STOCK #, STOCK NUMBER",
    ),
    ListingField(
        key="vehicle_additional_info",
        label="Additional Vehicle Info",
        section=FieldSection.VEHICLE,
        cd_api_key="vehicles[0].additionalInfo",
        field_type=FieldType.TEXTAREA,
        required=False,
        display_order=9,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.COMPUTED,
        max_length=500,
        help_text="Notes visible to assigned carrier (includes Gate Pass)",
    ),
    # -------------------------------------------------------------------------
    # PICKUP LOCATION (Stop 1) - Extracted from auction document
    # -------------------------------------------------------------------------
    ListingField(
        key="pickup_location_type",
        label="Location Type",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].locationType",
        field_type=FieldType.SELECT,
        required=True,
        export_only=True,
        display_order=0,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        options=[
            "Auction",
            "Dealership",
            "Warehouse",
            "Residence",
            "Port",
            "Terminal",
            "Other",
        ],
        default_value="Auction",
        help_text="Type of pickup location (CD API V2 validated values)",
    ),
    ListingField(
        key="pickup_name",
        label="Location Name",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].locationName",
        field_type=FieldType.TEXT,
        required=False,
        display_order=1,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.EXTRACTED,
        max_length=100,
        help_text="Business or auction name",
        extraction_hint="Name of auction facility",
    ),
    ListingField(
        key="pickup_address",
        label="Street Address",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].address.street",
        field_type=FieldType.TEXT,
        required=True,
        display_order=2,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.EXTRACTED,
        max_length=200,
        help_text="Street address for pickup",
        extraction_hint="Physical address, street line",
    ),
    ListingField(
        key="pickup_city",
        label="City",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].address.city",
        field_type=FieldType.TEXT,
        required=True,
        display_order=3,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.EXTRACTED,
        max_length=100,
        help_text="City name",
    ),
    ListingField(
        key="pickup_state",
        label="State",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].address.state",
        field_type=FieldType.TEXT,
        required=True,
        display_order=4,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.EXTRACTED,
        validation_regex=r"^[A-Z]{2}$",
        validation_message="State must be 2-letter code (e.g., CA, NY)",
        min_length=2,
        max_length=2,
        help_text="2-letter state code",
    ),
    ListingField(
        key="pickup_zip",
        label="ZIP Code",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].address.postalCode",
        field_type=FieldType.TEXT,
        required=True,
        display_order=5,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.EXTRACTED,
        validation_regex=r"^\d{5}(-\d{4})?$",
        validation_message="ZIP must be 5 digits or 5+4 format",
        help_text="5-digit or 9-digit ZIP code",
    ),
    ListingField(
        key="pickup_phone",
        label="Phone",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].phone",
        field_type=FieldType.TEXT,
        required=False,
        display_order=6,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.EXTRACTED,
        max_length=20,
        help_text="Contact phone number",
    ),
    ListingField(
        key="pickup_contact",
        label="Contact Name",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].contact.name",
        field_type=FieldType.TEXT,
        required=False,
        display_order=7,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.EXTRACTED,
        max_length=100,
        help_text="Contact person name",
    ),
    ListingField(
        key="pickup_hours",
        label="Operating Hours",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].operatingHours",
        field_type=FieldType.TEXT,
        required=False,
        display_order=8,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.CONSTANT,
        max_length=200,
        help_text="Business hours for pickup",
    ),
    ListingField(
        key="pickup_buyer_number",
        label="Buyer Reference Number",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].buyerReferenceNumber",
        field_type=FieldType.TEXT,
        required=False,
        display_order=9,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.EXTRACTED,
        max_length=50,
        help_text="Buyer ID / Member number for auction pickup",
        extraction_hint="MEMBER, BUYER ID, MEMBER #, BUYER NUMBER",
    ),
    ListingField(
        key="pickup_email",
        label="Email",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].email",
        field_type=FieldType.TEXT,
        required=False,
        display_order=10,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.CONSTANT,
        max_length=100,
        help_text="Email address for pickup contact",
    ),
    ListingField(
        key="pickup_notes",
        label="Pickup Notes",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].notes",
        field_type=FieldType.TEXTAREA,
        required=False,
        display_order=11,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.USER_INPUT,
        max_length=1000,
        help_text="Special instructions for pickup (includes operating hours)",
    ),
    # -------------------------------------------------------------------------
    # DELIVERY LOCATION (Stop 2) - From warehouse reference data
    # -------------------------------------------------------------------------
    ListingField(
        key="delivery_location_type",
        label="Location Type",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].locationType",
        field_type=FieldType.SELECT,
        required=True,
        export_only=True,
        display_order=0,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.WAREHOUSE_REF,
        options=[
            "Auction",
            "Dealership",
            "Warehouse",
            "Residence",
            "Port",
            "Terminal",
            "Other",
        ],
        default_value="Warehouse",
        help_text="Type of delivery location (CD API V2 validated values)",
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_name",
        label="Location Name",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].locationName",
        field_type=FieldType.TEXT,
        required=False,
        display_order=1,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.WAREHOUSE_REF,
        max_length=100,
        help_text="Warehouse or destination name",
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_address",
        label="Street Address",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].address.street",
        field_type=FieldType.TEXT,
        required=True,
        export_only=True,
        display_order=2,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.WAREHOUSE_REF,
        max_length=200,
        help_text="Street address for delivery",
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_city",
        label="City",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].address.city",
        field_type=FieldType.TEXT,
        required=True,
        export_only=True,
        display_order=3,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.WAREHOUSE_REF,
        max_length=100,
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_state",
        label="State",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].address.state",
        field_type=FieldType.TEXT,
        required=True,
        export_only=True,
        display_order=4,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.WAREHOUSE_REF,
        validation_regex=r"^[A-Z]{2}$",
        validation_message="State must be 2-letter code",
        min_length=2,
        max_length=2,
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_zip",
        label="ZIP Code",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].address.postalCode",
        field_type=FieldType.TEXT,
        required=True,
        export_only=True,
        display_order=5,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.WAREHOUSE_REF,
        validation_regex=r"^\d{5}(-\d{4})?$",
        validation_message="ZIP must be 5 digits or 5+4 format",
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_phone",
        label="Facility Phone",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].phone",
        field_type=FieldType.TEXT,
        required=False,
        display_order=6,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.WAREHOUSE_REF,
        max_length=20,
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_contact_phone",
        label="Contact Phone",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].contactPhone",
        field_type=FieldType.TEXT,
        required=False,
        display_order=7,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.WAREHOUSE_REF,
        max_length=20,
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_contact",
        label="Contact Name",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].contactName",
        field_type=FieldType.TEXT,
        required=False,
        display_order=8,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.WAREHOUSE_REF,
        max_length=100,
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_hours",
        label="Operating Hours",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].operatingHours",
        field_type=FieldType.TEXT,
        required=False,
        display_order=8,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.WAREHOUSE_REF,
        max_length=200,
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_email",
        label="Email",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].email",
        field_type=FieldType.TEXT,
        required=False,
        display_order=9,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.WAREHOUSE_REF,
        max_length=100,
        help_text="Email address for delivery contact",
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_buyer_number",
        label="Buyer Reference Number",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].buyerReferenceNumber",
        field_type=FieldType.TEXT,
        required=False,
        display_order=10,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.WAREHOUSE_REF,
        max_length=50,
        help_text="Broker buyer reference code (e.g., DAYTONACARGO)",
        editable_in_review=False,
    ),
    ListingField(
        key="delivery_notes",
        label="Delivery Notes",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].notes",
        field_type=FieldType.TEXTAREA,
        required=False,
        display_order=11,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.USER_INPUT,
        max_length=1000,
        help_text="Special instructions for delivery",
    ),
    # -------------------------------------------------------------------------
    # PRICING - User input or computed from Market Intelligence API
    # -------------------------------------------------------------------------
    ListingField(
        key="price_total",
        label="Total Price",
        section=FieldSection.PRICING,
        cd_api_key="price.total",
        field_type=FieldType.NUMBER,
        required=False,
        display_order=1,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.USER_INPUT,
        min_value=0,
        help_text="Total transport price in USD",
    ),
    ListingField(
        key="price_cod_amount",
        label="COD Amount",
        section=FieldSection.PRICING,
        cd_api_key="price.cod.amount",
        field_type=FieldType.NUMBER,
        required=False,
        display_order=2,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.USER_INPUT,
        min_value=0,
        help_text="Cash on delivery amount",
    ),
    ListingField(
        key="price_cod_method",
        label="COD Payment Method",
        section=FieldSection.PRICING,
        cd_api_key="price.cod.paymentMethod",
        field_type=FieldType.SELECT,
        required=False,
        display_order=3,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.CONSTANT,
        options=["CASH", "CHECK", "CERTIFIED_CHECK", "MONEY_ORDER", "COMCHECK", "ACH"],
        default_value="CASH",
    ),
    ListingField(
        key="balance_payment_method",
        label="Balance Payment Method",
        section=FieldSection.PRICING,
        cd_api_key="price.balance.balancePaymentMethod",
        field_type=FieldType.SELECT,
        required=False,
        display_order=4,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.CONSTANT,
        options=[
            "CASH",
            "CHECK",
            "CERTIFIED_FUNDS",
            "COMCHECK",
            "ACH",
            "COMPANY_CHECK",
        ],
        default_value="CERTIFIED_FUNDS",
        help_text="Payment method for balance (after COD)",
    ),
    ListingField(
        key="balance_payment_time",
        label="Balance Payment Time",
        section=FieldSection.PRICING,
        cd_api_key="price.balance.paymentTime",
        field_type=FieldType.SELECT,
        required=False,
        display_order=5,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.CONSTANT,
        options=[
            "IMMEDIATELY",
            "TWO_BUSINESS_DAYS",
            "FIVE_BUSINESS_DAYS",
            "TEN_BUSINESS_DAYS",
            "FIFTEEN_BUSINESS_DAYS",
            "THIRTY_BUSINESS_DAYS",
        ],
        default_value="TWO_BUSINESS_DAYS",
        help_text="When balance payment is due (CD API V2 spelled-out format)",
    ),
    ListingField(
        key="balance_terms_begin_on",
        label="Balance Terms Begin On",
        section=FieldSection.PRICING,
        cd_api_key="price.balance.balancePaymentTermsBeginOn",
        field_type=FieldType.SELECT,
        required=False,
        display_order=6,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.CONSTANT,
        options=[
            "RECEIVING_SIGNED_BOL",
            "VEHICLE_PICKUP",
            "VEHICLE_DELIVERY",
        ],
        default_value="RECEIVING_SIGNED_BOL",
        help_text="Event that starts the payment term countdown",
    ),
    # -------------------------------------------------------------------------
    # ADDITIONAL INFORMATION
    # -------------------------------------------------------------------------
    ListingField(
        key="external_id",
        label="External ID",
        section=FieldSection.ADDITIONAL,
        cd_api_key="externalId",
        field_type=FieldType.TEXT,
        required=False,
        display_order=1,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.COMPUTED,
        max_length=50,  # CD API limit is 50 characters
        help_text="Your internal reference ID (max 50 chars)",
    ),
    ListingField(
        key="available_date",
        label="Available Date",
        section=FieldSection.ADDITIONAL,
        cd_api_key="availableDate",
        field_type=FieldType.DATE,
        required=True,
        export_only=True,
        display_order=2,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        default_value="today",
        help_text="Date vehicle is available for pickup (today to 30 days)",
    ),
    ListingField(
        key="expiration_date",
        label="Expiration Date",
        section=FieldSection.ADDITIONAL,
        cd_api_key="expirationDate",
        field_type=FieldType.DATE,
        required=False,
        display_order=3,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.USER_INPUT,
        help_text="Listing expiration date",
    ),
    ListingField(
        key="trailer_type",
        label="Trailer Type",
        section=FieldSection.ADDITIONAL,
        cd_api_key="trailerType",
        field_type=FieldType.SELECT,
        required=True,
        export_only=True,
        display_order=4,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        options=["OPEN", "ENCLOSED", "DRIVEAWAY"],
        default_value="OPEN",
        help_text="OPEN: Standard car hauler. ENCLOSED: Protected transport. DRIVEAWAY: Vehicle driven to destination",
    ),
    # -------------------------------------------------------------------------
    # INTERNAL FIELDS - Extracted from document, NOT sent to CD API
    # -------------------------------------------------------------------------
    ListingField(
        key="buyer_id",
        label="Buyer ID",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,  # Not sent to CD
        field_type=FieldType.TEXT,
        required=False,
        display_order=5,
        category=FieldCategory.INTERNAL,
        source_type=FieldSourceType.EXTRACTED,
        help_text="Auction buyer ID (internal use)",
        extraction_hint="MEMBER ID, BUYER ID, MEMBER #",
    ),
    ListingField(
        key="buyer_name",
        label="Buyer Name",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,  # Not sent to CD
        field_type=FieldType.TEXT,
        required=False,
        display_order=6,
        category=FieldCategory.INTERNAL,
        source_type=FieldSourceType.EXTRACTED,
        help_text="Buyer name (internal use)",
    ),
    ListingField(
        key="sale_date",
        label="Sale Date",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,  # Not sent to CD
        field_type=FieldType.DATE,
        required=False,
        display_order=7,
        category=FieldCategory.INTERNAL,
        source_type=FieldSourceType.EXTRACTED,
        help_text="Original sale/purchase date",
        extraction_hint="SALE DATE, DATE SOLD",
    ),
    ListingField(
        key="total_amount",
        label="Purchase Amount",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,  # Not sent to CD
        field_type=FieldType.NUMBER,
        required=False,
        display_order=8,
        category=FieldCategory.INTERNAL,
        source_type=FieldSourceType.EXTRACTED,
        help_text="Total purchase amount (internal use)",
        extraction_hint="TOTAL, AMOUNT DUE, GRAND TOTAL",
    ),
    ListingField(
        key="seller_name",
        label="Seller Name",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,
        field_type=FieldType.TEXT,
        required=False,
        display_order=9,
        category=FieldCategory.INTERNAL,
        source_type=FieldSourceType.EXTRACTED,
        help_text="Insurance company / seller (internal use)",
    ),
    ListingField(
        key="load_id",
        label="Your Load ID",
        section=FieldSection.ADDITIONAL,
        cd_api_key="externalId",
        field_type=FieldType.TEXT,
        required=False,
        display_order=10,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.COMPUTED,
        max_length=50,
        editable_in_review=False,
        help_text="Auto-generated Load ID (M+DD+Make3+Model2+Seq)",
    ),
    ListingField(
        key="manheim_release_date",
        label="Manheim Release Date",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,
        field_type=FieldType.TEXT,
        required=False,
        display_order=11,
        category=FieldCategory.INTERNAL,
        source_type=FieldSourceType.EXTRACTED,
        help_text="Manheim vehicle release date. Affects available_date. Values: ISO date, AVAILABLE_NOW, or NO_RELEASE_DOCUMENT.",
    ),
    ListingField(
        key="manheim_offsite",
        label="Manheim Offsite",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,
        field_type=FieldType.BOOLEAN,
        required=False,
        display_order=12,
        category=FieldCategory.INTERNAL,
        source_type=FieldSourceType.EXTRACTED,
        default_value="false",
        help_text="Vehicle is not located at a Manheim facility",
    ),
    ListingField(
        key="gate_pass",
        label="Gate Pass",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,
        field_type=FieldType.TEXT,
        required=False,
        display_order=13,
        category=FieldCategory.INTERNAL,
        source_type=FieldSourceType.EXTRACTED,
        help_text="Gate pass code from email (added to additionalInfo for carrier)",
    ),
    ListingField(
        key="requires_inspection",
        label="Request Carrier Use CD App",
        section=FieldSection.ADDITIONAL,
        cd_api_key="requiresInspection",
        field_type=FieldType.BOOLEAN,
        required=False,
        display_order=14,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.CONSTANT,
        default_value="true",
        help_text="Request carrier to use CD App for inspections (default checked)",
    ),
    # -------------------------------------------------------------------------
    # PRICING AND PAYMENT
    # -------------------------------------------------------------------------
    ListingField(
        key="cod_amount",
        label="COP/COD Amount",
        section=FieldSection.PRICING,
        cd_api_key="price.cod.amount",
        field_type=FieldType.NUMBER,
        required=True,
        export_only=True,
        display_order=20,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        default_value="0",
        help_text="Cash on delivery amount. Default 0 (full balance payment).",
    ),
    ListingField(
        key="cod_payment_method",
        label="COP/COD Payment Method",
        section=FieldSection.PRICING,
        cd_api_key="price.cod.paymentMethod",
        field_type=FieldType.SELECT,
        required=False,
        export_only=True,
        display_order=21,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        options=["CASH_CERTIFIED_FUNDS", "CHECK", "CASH", "CERTIFIED_CHECK"],
        default_value="CASH_CERTIFIED_FUNDS",
        help_text="Payment method for COD (only relevant if COD > 0)",
    ),
    ListingField(
        key="cod_payment_location",
        label="COP/COD Location",
        section=FieldSection.PRICING,
        cd_api_key="price.cod.paymentLocation",
        field_type=FieldType.SELECT,
        required=False,
        export_only=True,
        display_order=22,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        options=["PICKUP", "DELIVERY"],
        default_value="DELIVERY",
        help_text="Where COD is collected (only relevant if COD > 0)",
    ),
    ListingField(
        key="balance_payment_method",
        label="Balance Payment Method",
        section=FieldSection.PRICING,
        cd_api_key="price.balance.paymentMethod",
        field_type=FieldType.SELECT,
        required=True,
        export_only=True,
        display_order=23,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        options=["CERTIFIED_FUNDS", "CHECK", "ACH", "CASH"],
        default_value="CERTIFIED_FUNDS",
        help_text="How the balance is paid after delivery",
    ),
    ListingField(
        key="balance_payment_time",
        label="Balance Payment Time",
        section=FieldSection.PRICING,
        cd_api_key="price.balance.paymentTime",
        field_type=FieldType.SELECT,
        required=True,
        export_only=True,
        display_order=24,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        options=[
            "IMMEDIATELY",
            "TWO_BUSINESS_DAYS",
            "FIVE_BUSINESS_DAYS",
            "TEN_BUSINESS_DAYS",
            "FIFTEEN_BUSINESS_DAYS",
            "THIRTY_BUSINESS_DAYS",
        ],
        default_value="TWO_BUSINESS_DAYS",
        help_text="When balance is paid (CD API V2 spelled-out format)",
    ),
    ListingField(
        key="balance_terms_begin_on",
        label="Balance Terms Begin On",
        section=FieldSection.PRICING,
        cd_api_key="price.balance.balancePaymentTermsBeginOn",
        field_type=FieldType.SELECT,
        required=True,
        export_only=True,
        display_order=25,
        category=FieldCategory.CD_REQUIRED,
        source_type=FieldSourceType.CONSTANT,
        options=[
            "PICKUP",
            "DELIVERY",
            "RECEIVING_SIGNED_BOL",
        ],
        default_value="RECEIVING_SIGNED_BOL",
        help_text="When balance payment terms begin counting",
    ),
    # F2 fix: DEPRECATED - Use vehicle_lot instead
    # Kept for backward compatibility with old data
    ListingField(
        key="stock_number",
        label="Stock Number (Deprecated)",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,  # Not sent to CD - use vehicle_lot
        field_type=FieldType.TEXT,
        required=False,
        display_order=9,
        category=FieldCategory.INTERNAL,
        source_type=FieldSourceType.EXTRACTED,
        help_text="DEPRECATED: Use vehicle_lot. Normalized by field_resolver.",
        extraction_hint="STOCK #, STOCK NUMBER",
    ),
    ListingField(
        key="gate_pass",
        label="Gate Pass",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,  # Not sent to CD
        field_type=FieldType.TEXT,
        required=False,
        display_order=10,
        category=FieldCategory.INTERNAL,
        source_type=FieldSourceType.EXTRACTED,
        help_text="Gate pass or release code",
        extraction_hint="GATE PASS, RELEASE, CLAIM NUMBER",
    ),
    # -------------------------------------------------------------------------
    # NOTES - User input
    # -------------------------------------------------------------------------
    ListingField(
        key="notes",
        label="General Notes",
        section=FieldSection.NOTES,
        cd_api_key="notes",
        field_type=FieldType.TEXTAREA,
        required=False,
        display_order=1,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.USER_INPUT,
        max_length=2000,
    ),
    ListingField(
        key="transport_special_instructions",
        label="Special Instructions",
        section=FieldSection.NOTES,
        cd_api_key="transportationReleaseNotes",
        field_type=FieldType.TEXTAREA,
        required=False,
        display_order=2,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.USER_INPUT,
        max_length=2000,
        help_text="Special transport instructions",
    ),
    ListingField(
        key="load_specific_terms",
        label="Load-Specific Terms",
        section=FieldSection.NOTES,
        cd_api_key="loadSpecificTerms",
        field_type=FieldType.TEXTAREA,
        required=False,
        display_order=3,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.USER_INPUT,
        max_length=500,
        help_text="Per-load terms template (auto-generated if empty)",
    ),
    ListingField(
        key="shipper_order_id",
        label="Shipper Order ID",
        section=FieldSection.NOTES,
        cd_api_key="shipperOrderId",
        field_type=FieldType.TEXT,
        required=False,
        display_order=4,
        category=FieldCategory.CD_OPTIONAL,
        source_type=FieldSourceType.COMPUTED,
        max_length=50,
        help_text="Matches externalId (Load ID) for CD order tracking",
    ),
]


# =============================================================================
# REGISTRY CLASS
# =============================================================================


class ListingFieldRegistry:
    """Central registry for all listing fields."""

    def __init__(self):
        self._fields = {f.key: f for f in LISTING_FIELDS}
        self._by_section: dict[FieldSection, list[ListingField]] = {}
        self._by_category: dict[FieldCategory, list[ListingField]] = {}
        self._by_source_type: dict[FieldSourceType, list[ListingField]] = {}
        self._required_fields: list[str] = []

        # Build indexes
        for f in LISTING_FIELDS:
            # By section
            if f.section not in self._by_section:
                self._by_section[f.section] = []
            self._by_section[f.section].append(f)

            # By category
            if f.category not in self._by_category:
                self._by_category[f.category] = []
            self._by_category[f.category].append(f)

            # By source type
            if f.source_type not in self._by_source_type:
                self._by_source_type[f.source_type] = []
            self._by_source_type[f.source_type].append(f)

            if f.required:
                self._required_fields.append(f.key)

        # Sort by display_order
        for section in self._by_section:
            self._by_section[section].sort(key=lambda x: x.display_order)

    def get_field(self, key: str) -> Optional[ListingField]:
        """Get field definition by key."""
        return self._fields.get(key)

    def get_all_fields(self) -> list[ListingField]:
        """Get all field definitions."""
        return LISTING_FIELDS

    def get_fields_by_section(self, section: FieldSection) -> list[ListingField]:
        """Get fields for a specific section."""
        return self._by_section.get(section, [])

    def get_required_fields(self) -> list[str]:
        """Get list of required field keys."""
        return self._required_fields.copy()

    def get_sections(self) -> list[FieldSection]:
        """Get all sections in order."""
        return [
            FieldSection.VEHICLE,
            FieldSection.PICKUP,
            FieldSection.DELIVERY,
            FieldSection.PRICING,
            FieldSection.ADDITIONAL,
            FieldSection.NOTES,
        ]

    def get_fields_by_category(self, category: FieldCategory) -> list[ListingField]:
        """Get fields for a specific category (CD_REQUIRED, CD_OPTIONAL, INTERNAL)."""
        return self._by_category.get(category, [])

    def get_fields_by_source_type(self, source_type: FieldSourceType) -> list[ListingField]:
        """Get fields for a specific source type (EXTRACTED, CONSTANT, etc)."""
        return self._by_source_type.get(source_type, [])

    def get_extracted_fields(self) -> list[ListingField]:
        """Get all fields that should be extracted from documents."""
        return self.get_fields_by_source_type(FieldSourceType.EXTRACTED)

    def get_cd_fields(self) -> list[ListingField]:
        """Get all fields that are sent to CD API (CD_REQUIRED + CD_OPTIONAL)."""
        cd_fields = []
        cd_fields.extend(self.get_fields_by_category(FieldCategory.CD_REQUIRED))
        cd_fields.extend(self.get_fields_by_category(FieldCategory.CD_OPTIONAL))
        return cd_fields

    def get_internal_fields(self) -> list[ListingField]:
        """Get all internal fields (not sent to CD API)."""
        return self.get_fields_by_category(FieldCategory.INTERNAL)

    def get_warehouse_fields(self) -> list[ListingField]:
        """Get fields that come from warehouse reference data."""
        return self.get_fields_by_source_type(FieldSourceType.WAREHOUSE_REF)

    def get_fields_for_mode(self, mode: str) -> list[ListingField]:
        """
        Get fields relevant for a specific mode.

        Modes:
        - training: Show extracted + user_input fields, hide export_only
        - review: Show all fields except hidden ones
        - export: Show all CD fields (required + optional)
        """
        if mode == "training":
            return [f for f in LISTING_FIELDS if f.visible_in_training and not f.export_only]
        elif mode == "review":
            return [f for f in LISTING_FIELDS if f.visible_in_training]
        else:  # export
            return self.get_cd_fields()

    def validate_field(self, key: str, value: Any) -> Optional[str]:
        """
        Validate a single field value.
        Returns error message if invalid, None if valid.
        """
        field_def = self._fields.get(key)
        if not field_def:
            return None  # Unknown fields pass validation

        if field_def.required and (value is None or value == ""):
            return f"{field_def.label} is required"

        if value is None or value == "":
            return None  # Optional empty values are valid

        # Normalize ZIP codes before validation
        if key in ("pickup_zip", "delivery_zip"):
            if isinstance(value, (int, float)):
                value = str(int(value)).zfill(5)
            elif isinstance(value, str):
                value = value.strip()
                # Extract just digits and hyphen
                zip_match = re.match(r"^(\d{5})[-\s]?(\d{4})?", value)
                if zip_match:
                    value = zip_match.group(1)
                    if zip_match.group(2):
                        value += "-" + zip_match.group(2)

        # String validations
        if isinstance(value, str):
            if field_def.min_length and len(value) < field_def.min_length:
                return f"{field_def.label} must be at least {field_def.min_length} characters"
            if field_def.max_length and len(value) > field_def.max_length:
                return f"{field_def.label} must be at most {field_def.max_length} characters"
            if field_def.validation_regex:
                if not re.match(field_def.validation_regex, value):
                    return field_def.validation_message or f"{field_def.label} format is invalid"

        # Number validations
        if field_def.field_type == FieldType.NUMBER:
            try:
                num_val = float(value)
                if field_def.min_value is not None and num_val < field_def.min_value:
                    return f"{field_def.label} must be at least {field_def.min_value}"
                if field_def.max_value is not None and num_val > field_def.max_value:
                    return f"{field_def.label} must be at most {field_def.max_value}"
            except (TypeError, ValueError):
                return f"{field_def.label} must be a number"

        # Select validations
        if field_def.field_type == FieldType.SELECT and field_def.options:
            if str(value).upper() not in [o.upper() for o in field_def.options]:
                return f"{field_def.label} must be one of: {', '.join(field_def.options)}"

        return None

    def validate_all(self, data: dict[str, Any], skip_internal: bool = True) -> list[dict[str, str]]:
        """
        Validate all fields in data dict.
        Returns list of {field: key, error: message} for invalid fields.

        Args:
            data: Field values dict
            skip_internal: If True, skip INTERNAL fields (not sent to CD API)
        """
        errors = []
        for field_def in LISTING_FIELDS:
            # Skip INTERNAL fields - they're not sent to CD API
            if skip_internal and field_def.category == FieldCategory.INTERNAL:
                continue
            value = data.get(field_def.key)
            error = self.validate_field(field_def.key, value)
            if error:
                errors.append({"field": field_def.key, "error": error})
        return errors

    def apply_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Apply default values to empty fields.
        Returns a copy of data with defaults filled in.

        Special handling:
        - "today" default_value is resolved to current date string (YYYY-MM-DD)
        - ZIP codes are normalized to string format (preserves leading zeros)
        - pickup_location_type defaults to AUCTION for auction sources
        """
        result = dict(data)
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Normalize ZIP codes to ensure they're strings with proper format
        for zip_field in ["pickup_zip", "delivery_zip"]:
            if zip_field in result and result[zip_field] is not None:
                zip_val = result[zip_field]
                # Convert to string if numeric
                if isinstance(zip_val, (int, float)):
                    zip_val = str(int(zip_val)).zfill(5)  # Pad with leading zeros
                elif isinstance(zip_val, str):
                    # Clean up: remove spaces, keep only digits and hyphen
                    zip_val = zip_val.strip()
                    # Extract just the ZIP portion (handle formats like "89115-1234", "89115 1234")
                    zip_match = re.match(r"^(\d{5})[-\s]?(\d{4})?", zip_val)
                    if zip_match:
                        zip_val = zip_match.group(1)
                        if zip_match.group(2):
                            zip_val += "-" + zip_match.group(2)
                result[zip_field] = zip_val

        # Auto-set pickup_location_type to AUCTION for auction sources
        auction_source = result.get("auction_source", "").upper()
        if auction_source in ("COPART", "IAA", "MANHEIM"):
            if not result.get("pickup_location_type"):
                result["pickup_location_type"] = "AUCTION"

        for field_def in LISTING_FIELDS:
            value = result.get(field_def.key)
            if (value is None or value == "") and field_def.default_value:
                default = field_def.default_value
                if default == "today":
                    default = today_str
                result[field_def.key] = default
        return result

    def get_blocking_issues(
        self,
        data: dict[str, Any],
        warehouse_selected: bool = False,
        warehouse_data: dict[str, Any] = None,
        mode: str = "export",
    ) -> list[dict[str, str]]:
        """
        Get issues that block posting.
        Returns list of {field: key, issue: message}.

        Args:
            data: Field values dict
            warehouse_selected: Whether a warehouse has been selected
            warehouse_data: Warehouse data dict to apply to delivery fields
            mode: "export" for full CD API validation, "training" for extraction review only

        In "training" mode, fields marked export_only=True are skipped
        (delivery address from warehouse, vehicle_type/condition with defaults,
        available_date, trailer_type).

        Validates against CD API V2 requirements:
        - Minimum 2 unique stops (pickup and delivery must have different addresses)
        - Minimum 1 vehicle, maximum 12 vehicles
        - availableDate not before today, not more than 30 days ahead
        - expirationDate not before today, not more than 30 days ahead
        - externalId max 50 characters
        """
        issues = []

        # Normalize mode: "production" is equivalent to "export"
        if mode == "production":
            mode = "export"

        # Apply defaults before validation
        effective_data = self.apply_defaults(data)

        # Apply warehouse data to delivery fields if provided
        if warehouse_data:
            warehouse_selected = True
            field_mapping = {
                "delivery_name": "name",
                "delivery_address": "address",
                "delivery_city": "city",
                "delivery_state": "state",
                "delivery_zip": "zip_code",
                "delivery_phone": "phone",
                "delivery_contact": "contact_name",
            }
            for field_key, wh_key in field_mapping.items():
                if wh_key in warehouse_data and warehouse_data[wh_key]:
                    effective_data[field_key] = warehouse_data[wh_key]

        # Check required fields
        for field_key in self._required_fields:
            field_def = self._fields[field_key]

            # Skip INTERNAL fields - they're not sent to CD API
            if field_def.category == FieldCategory.INTERNAL:
                continue

            # In training mode, skip fields that are only required at export
            if mode == "training" and field_def.export_only:
                continue

            # Skip delivery fields if warehouse is selected (they come from warehouse)
            if warehouse_selected and field_key.startswith("delivery_"):
                continue

            value = effective_data.get(field_key)
            if value is None or value == "":
                issues.append(
                    {
                        "field": field_key,
                        "issue": f"Missing required field: {field_def.label}",
                    }
                )

        # Check warehouse (delivery fields) — only in export mode
        if mode == "export" and not warehouse_selected:
            delivery_fields = [
                "delivery_address",
                "delivery_city",
                "delivery_state",
                "delivery_zip",
            ]
            delivery_filled = all(effective_data.get(f) for f in delivery_fields)
            if not delivery_filled:
                issues.append(
                    {
                        "field": "warehouse",
                        "issue": "Warehouse not selected (delivery address incomplete)",
                    }
                )

        # CD API Rule: exactly 2 stops required with all required fields
        # Stop 1 = Pickup, Stop 2 = Delivery
        pickup_required = ["pickup_city", "pickup_state", "pickup_zip"]
        delivery_required = ["delivery_city", "delivery_state", "delivery_zip"]

        pickup_complete = all(
            effective_data.get(f) and effective_data.get(f) not in ("TBD", "")
            for f in pickup_required
        )
        delivery_complete = all(
            effective_data.get(f) and effective_data.get(f) not in ("TBD", "")
            for f in delivery_required
        )

        if mode == "export":
            if not pickup_complete:
                missing_pickup = [f for f in pickup_required if not effective_data.get(f)]
                issues.append(
                    {
                        "field": "stops",
                        "issue": f"Pickup stop incomplete. Missing: {', '.join(missing_pickup)}",
                    }
                )
            if not delivery_complete and not warehouse_selected:
                issues.append(
                    {
                        "field": "stops",
                        "issue": "Delivery stop incomplete. Please select a warehouse.",
                    }
                )

        # CD API Rule: 1-12 vehicles, no duplicate VINs
        # Currently single-vehicle mode - validate VIN exists and format
        vehicle_vin = effective_data.get("vehicle_vin", "")
        if mode == "export":
            if not vehicle_vin:
                issues.append(
                    {
                        "field": "vehicles",
                        "issue": "At least 1 vehicle required. VIN is missing.",
                    }
                )
            elif len(vehicle_vin) != 17:
                issues.append(
                    {
                        "field": "vehicle_vin",
                        "issue": f"VIN must be exactly 17 characters (got {len(vehicle_vin)})",
                    }
                )

        # CD API Rule: externalId max 50 characters
        external_id = effective_data.get("external_id", "")
        if external_id and len(external_id) > 50:
            issues.append(
                {
                    "field": "external_id",
                    "issue": f"External ID must be 50 characters or less (currently {len(external_id)})",
                }
            )

        # Date and advanced validations only apply in export mode
        if mode == "training":
            return issues

        # Check available_date rules (CD API requirement)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        max_date = today + timedelta(days=30)

        available_date = effective_data.get("available_date")
        if available_date:
            try:
                if isinstance(available_date, str):
                    # Handle various date formats
                    date_str = available_date.replace("Z", "+00:00")
                    if "T" in date_str:
                        av_date = datetime.fromisoformat(date_str)
                    else:
                        av_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
                else:
                    av_date = available_date

                av_date_naive = (
                    av_date.replace(tzinfo=None) if hasattr(av_date, "tzinfo") else av_date
                )
                if av_date_naive < today:
                    issues.append(
                        {
                            "field": "available_date",
                            "issue": "Available date cannot be in the past (CD API requirement)",
                        }
                    )
                if av_date_naive > max_date:
                    issues.append(
                        {
                            "field": "available_date",
                            "issue": "Available date cannot be more than 30 days in the future (CD API requirement)",
                        }
                    )
            except Exception:
                issues.append(
                    {
                        "field": "available_date",
                        "issue": "Invalid date format",
                    }
                )

        # Check expiration_date rules (CD API requirement)
        expiration_date = effective_data.get("expiration_date")
        if expiration_date:
            try:
                if isinstance(expiration_date, str):
                    date_str = expiration_date.replace("Z", "+00:00")
                    if "T" in date_str:
                        exp_date = datetime.fromisoformat(date_str)
                    else:
                        exp_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
                else:
                    exp_date = expiration_date

                exp_date_naive = (
                    exp_date.replace(tzinfo=None) if hasattr(exp_date, "tzinfo") else exp_date
                )
                if exp_date_naive < today:
                    issues.append(
                        {
                            "field": "expiration_date",
                            "issue": "Expiration date cannot be in the past (CD API requirement)",
                        }
                    )
                if exp_date_naive > max_date:
                    issues.append(
                        {
                            "field": "expiration_date",
                            "issue": "Expiration date cannot be more than 30 days in the future (CD API requirement)",
                        }
                    )
            except Exception:
                pass  # Expiration date is optional

        # Check desiredDeliveryDate rules (CD API requirement)
        # Must be: >= availableDate, >= today, <= today + 30 days
        desired_delivery_date = effective_data.get("desired_delivery_date")
        if desired_delivery_date:
            try:
                if isinstance(desired_delivery_date, str):
                    date_str = desired_delivery_date.replace("Z", "+00:00")
                    if "T" in date_str:
                        dd_date = datetime.fromisoformat(date_str)
                    else:
                        dd_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
                else:
                    dd_date = desired_delivery_date

                dd_date_naive = (
                    dd_date.replace(tzinfo=None) if hasattr(dd_date, "tzinfo") else dd_date
                )

                if dd_date_naive < today:
                    issues.append(
                        {
                            "field": "desired_delivery_date",
                            "issue": "Desired delivery date cannot be in the past (CD API requirement)",
                        }
                    )
                if dd_date_naive > max_date:
                    issues.append(
                        {
                            "field": "desired_delivery_date",
                            "issue": "Desired delivery date cannot be more than 30 days in the future (CD API requirement)",
                        }
                    )

                # desiredDeliveryDate must be >= availableDate
                if available_date and "av_date_naive" in dir():
                    if dd_date_naive < av_date_naive:
                        issues.append(
                            {
                                "field": "desired_delivery_date",
                                "issue": "Desired delivery date must be on or after available date (CD API requirement)",
                            }
                        )
            except Exception:
                pass  # Desired delivery date is optional

        # Validation errors (format/regex checks)
        validation_errors = self.validate_all(effective_data)
        for err in validation_errors:
            field_def = self._fields.get(err["field"])
            # In training mode, skip validation errors for export_only fields
            if mode == "training" and field_def and field_def.export_only:
                continue
            # Skip delivery fields if warehouse is selected (they come from warehouse)
            if warehouse_selected and err["field"].startswith("delivery_"):
                continue
            # Avoid duplicate errors
            existing = [i for i in issues if i["field"] == err["field"]]
            if not existing:
                issues.append({"field": err["field"], "issue": err["error"]})

        return issues

    def to_json_schema(self) -> dict:
        """Export registry as JSON schema for frontend."""
        sections = {}
        for section in self.get_sections():
            fields_data = []
            for f in self.get_fields_by_section(section):
                field_dict = asdict(f)
                # Convert enums to string values for JSON serialization
                field_dict["section"] = f.section.value
                field_dict["field_type"] = f.field_type.value
                field_dict["category"] = f.category.value
                field_dict["source_type"] = f.source_type.value
                fields_data.append(field_dict)
            sections[section.value] = {
                "label": section.value.replace("_", " ").title(),
                "fields": fields_data,
            }
        return {
            "version": "2.0",
            "sections": sections,
            "required_fields": self._required_fields,
            "categories": [c.value for c in FieldCategory],
            "source_types": [s.value for s in FieldSourceType],
        }

    def get_taxonomy_summary(self) -> dict:
        """Get summary of field taxonomy for Settings UI."""
        return {
            "cd_required": {
                "count": len(self.get_fields_by_category(FieldCategory.CD_REQUIRED)),
                "fields": [f.key for f in self.get_fields_by_category(FieldCategory.CD_REQUIRED)],
            },
            "cd_optional": {
                "count": len(self.get_fields_by_category(FieldCategory.CD_OPTIONAL)),
                "fields": [f.key for f in self.get_fields_by_category(FieldCategory.CD_OPTIONAL)],
            },
            "internal": {
                "count": len(self.get_fields_by_category(FieldCategory.INTERNAL)),
                "fields": [f.key for f in self.get_fields_by_category(FieldCategory.INTERNAL)],
            },
            "by_source": {
                "extracted": [
                    f.key for f in self.get_fields_by_source_type(FieldSourceType.EXTRACTED)
                ],
                "constant": [
                    f.key for f in self.get_fields_by_source_type(FieldSourceType.CONSTANT)
                ],
                "warehouse_ref": [
                    f.key for f in self.get_fields_by_source_type(FieldSourceType.WAREHOUSE_REF)
                ],
                "user_input": [
                    f.key for f in self.get_fields_by_source_type(FieldSourceType.USER_INPUT)
                ],
                "computed": [
                    f.key for f in self.get_fields_by_source_type(FieldSourceType.COMPUTED)
                ],
            },
        }


# Singleton instance
_registry: Optional[ListingFieldRegistry] = None


def get_registry() -> ListingFieldRegistry:
    """Get the singleton registry instance."""
    global _registry
    if _registry is None:
        _registry = ListingFieldRegistry()
    return _registry


# =============================================================================
# CD API PAYLOAD BUILDER
# =============================================================================


def build_cd_payload(data: dict[str, Any], run_id: int = None) -> tuple[dict[str, Any], list[str]]:
    """
    Build Central Dispatch Listings API V2 payload from extracted data.

    Args:
        data: Dictionary of field values
        run_id: Optional extraction run ID for external reference

    Returns:
        Tuple of (CD API payload dictionary, list of warnings)

    Warnings are returned for:
    - Field truncation (externalId, partnerReferenceId, shipperOrderId > 50 chars)
    """
    get_registry()
    warnings = []

    # Generate external ID (CD API limit: 50 characters max)
    external_id = data.get("external_id")
    if not external_id:
        parts = ["DC"]
        parts.append(datetime.now().strftime("%Y%m%d"))
        if data.get("vehicle_make"):
            parts.append(data["vehicle_make"][:3].upper())
        if data.get("vehicle_lot"):
            parts.append(str(data["vehicle_lot"])[:10])
        elif run_id:
            parts.append(str(run_id))
        external_id = "-".join(parts)

    # Enforce CD API limit of 50 characters with warning
    if len(external_id) > 50:
        original_len = len(external_id)
        external_id = external_id[:50]
        warnings.append(f"externalId truncated from {original_len} to 50 characters")
        logger.warning(f"externalId truncated: {original_len} -> 50 chars")

    # Generate partnerReferenceId for retry-safe POST (CD API limit: 50 chars)
    # This is a stable key based on run_id or document identifiers
    partner_ref_id = None
    if run_id:
        partner_ref_id = f"CD-RUN-{run_id}"
    elif data.get("vehicle_vin"):
        # Fallback: use VIN + date as stable reference
        partner_ref_id = f"CD-{data['vehicle_vin'][:17]}-{datetime.now().strftime('%Y%m%d')}"

    if partner_ref_id and len(partner_ref_id) > 50:
        original_len = len(partner_ref_id)
        partner_ref_id = partner_ref_id[:50]
        warnings.append(f"partnerReferenceId truncated from {original_len} to 50 characters")
        logger.warning(f"partnerReferenceId truncated: {original_len} -> 50 chars")

    # Build vehicle - only include non-empty required fields
    vehicle = {}

    # Required vehicle fields
    if data.get("vehicle_vin"):
        vehicle["vin"] = data["vehicle_vin"]
    if data.get("vehicle_year"):
        try:
            vehicle["year"] = int(data["vehicle_year"])
        except (ValueError, TypeError):
            pass
    if data.get("vehicle_make"):
        vehicle["make"] = data["vehicle_make"]
    if data.get("vehicle_model"):
        vehicle["model"] = data["vehicle_model"]

    # Optional vehicle fields
    if data.get("vehicle_color"):
        vehicle["color"] = data["vehicle_color"]
    if data.get("vehicle_lot"):
        vehicle["lotNumber"] = str(data["vehicle_lot"])

    # Vehicle type - required with valid enum value
    vtype = data.get("vehicle_type", "SEDAN")
    if vtype:
        vtype = str(vtype).upper()
    valid_types = [
        "SEDAN",
        "SUV",
        "TRUCK",
        "VAN",
        "MOTORCYCLE",
        "COUPE",
        "CONVERTIBLE",
        "WAGON",
        "OTHER",
    ]
    vehicle["vehicleType"] = vtype if vtype in valid_types else "SEDAN"

    # Operability - boolean, defaults to operable
    condition = data.get("vehicle_condition", "OPERABLE")
    if condition:
        condition = str(condition).upper()
    vehicle["isOperable"] = condition != "INOPERABLE"

    # Additional vehicle info - includes gate pass for carrier reference
    additional_info = data.get("vehicle_additional_info")
    if not additional_info and data.get("gate_pass"):
        additional_info = f"Gate Pass: {data['gate_pass']}"
    if additional_info:
        vehicle["additionalInfo"] = additional_info

    # Helper to build address object, excluding empty fields
    def build_address(street, city, state, postal_code):
        addr = {}
        if street:
            addr["street"] = street
        if city:
            addr["city"] = city
        if state:
            addr["state"] = state
        if postal_code:
            addr["postalCode"] = postal_code
        return addr

    # Build pickup stop — normalize to CD API V2 accepted values
    pickup_location_type = data.get("pickup_location_type", "AUCTION")
    # CD API V2 valid locationType values (verified against live API)
    _LOCATION_TYPE_MAP = {
        "AUCTION": "Auction", "DEALER": "Dealership", "DEALERSHIP": "Dealership",
        "BUSINESS": "Dealership", "WAREHOUSE": "Warehouse", "RESIDENCE": "Residence",
        "PORT": "Port", "TERMINAL": "Terminal", "CROSS_DOCK": "Warehouse",
        "STORAGE_FACILITY": "Warehouse", "BODY_SHOP": "Other", "OTHER": "Other",
    }
    pickup_location_type = _LOCATION_TYPE_MAP.get(
        pickup_location_type.upper() if pickup_location_type else "AUCTION", "Auction"
    )

    pickup_stop = {
        "stopNumber": 1,
        "locationType": pickup_location_type,
        "address": build_address(
            data.get("pickup_address"),
            data.get("pickup_city"),
            data.get("pickup_state"),
            data.get("pickup_zip"),
        ),
    }
    if data.get("pickup_name"):
        pickup_stop["locationName"] = data["pickup_name"]
    if data.get("pickup_phone") or data.get("pickup_contact"):
        pickup_stop["contact"] = {}
        if data.get("pickup_phone"):
            pickup_stop["contact"]["phone"] = data["pickup_phone"]
        if data.get("pickup_contact"):
            pickup_stop["contact"]["name"] = data["pickup_contact"]
    if data.get("pickup_hours"):
        pickup_stop["operatingHours"] = data["pickup_hours"]
    if data.get("pickup_email"):
        pickup_stop["email"] = data["pickup_email"]
    if data.get("pickup_buyer_number"):
        pickup_stop["buyerReferenceNumber"] = data["pickup_buyer_number"]
    # Notes include operating hours as special instructions per V2 spec
    pickup_notes = data.get("pickup_notes", "")
    if data.get("pickup_hours") and pickup_notes:
        pickup_notes = f"Hours: {data['pickup_hours']}\n{pickup_notes}"
    elif data.get("pickup_hours"):
        pickup_notes = f"Hours: {data['pickup_hours']}"
    if pickup_notes:
        pickup_stop["notes"] = pickup_notes

    # Build delivery stop — normalize to CD API V2 accepted values
    delivery_location_type = data.get("delivery_location_type", "CROSS_DOCK")
    delivery_location_type = _LOCATION_TYPE_MAP.get(
        delivery_location_type.upper() if delivery_location_type else "TERMINAL", "Terminal"
    )

    delivery_stop = {
        "stopNumber": 2,
        "locationType": delivery_location_type,
        "address": build_address(
            data.get("delivery_address"),
            data.get("delivery_city"),
            data.get("delivery_state"),
            data.get("delivery_zip"),
        ),
    }
    if data.get("delivery_name"):
        delivery_stop["locationName"] = data["delivery_name"]
    if data.get("delivery_phone") or data.get("delivery_contact"):
        delivery_stop["contact"] = {}
        if data.get("delivery_phone"):
            delivery_stop["contact"]["phone"] = data["delivery_phone"]
        if data.get("delivery_contact"):
            delivery_stop["contact"]["name"] = data["delivery_contact"]
    if data.get("delivery_hours"):
        delivery_stop["operatingHours"] = data["delivery_hours"]
    if data.get("delivery_email"):
        delivery_stop["email"] = data["delivery_email"]
    if data.get("delivery_buyer_number"):
        delivery_stop["buyerReferenceNumber"] = data["delivery_buyer_number"]
    # Notes include operating hours as special instructions
    delivery_notes = data.get("delivery_notes", "")
    if data.get("delivery_hours") and delivery_notes:
        delivery_notes = f"Hours: {data['delivery_hours']}\n{delivery_notes}"
    elif data.get("delivery_hours"):
        delivery_notes = f"Hours: {data['delivery_hours']}"
    if delivery_notes:
        delivery_stop["notes"] = delivery_notes

    # Available date (default to today)
    available_date = data.get("available_date")
    if not available_date:
        available_date = datetime.now().strftime("%Y-%m-%d")

    # Build payload
    payload = {
        "externalId": external_id,
        "trailerType": data.get("trailer_type", "OPEN"),
        "hasInOpVehicle": not vehicle.get("isOperable", True),
        "availableDate": available_date,
        "stops": [pickup_stop, delivery_stop],
        "vehicles": [vehicle],
    }

    # Add partnerReferenceId for retry-safe POST (prevents duplicates)
    if partner_ref_id:
        payload["partnerReferenceId"] = partner_ref_id

    # Optional: shipperOrderId (also limited to 50 chars)
    shipper_order_id = data.get("shipper_order_id")
    if shipper_order_id:
        if len(shipper_order_id) > 50:
            original_len = len(shipper_order_id)
            shipper_order_id = shipper_order_id[:50]
            warnings.append(f"shipperOrderId truncated from {original_len} to 50 characters")
            logger.warning(f"shipperOrderId truncated: {original_len} -> 50 chars")
        payload["shipperOrderId"] = shipper_order_id

    # Optional: expiration date
    if data.get("expiration_date"):
        payload["expirationDate"] = data["expiration_date"]

    # Optional: pricing
    if data.get("price_total"):
        payload["price"] = {"total": float(data["price_total"])}
        # COD payment
        if data.get("price_cod_amount"):
            payload["price"]["cod"] = {
                "amount": float(data["price_cod_amount"]),
                "paymentMethod": data.get("price_cod_method", "CASH"),
            }
        # Balance payment (for carrier payment terms)
        balance = {}
        if data.get("balance_payment_method"):
            balance["balancePaymentMethod"] = data["balance_payment_method"]
        if data.get("balance_payment_time"):
            # Normalize to CD API V2 spelled-out format
            _PAYMENT_TIME_MAP = {
                "IMMEDIATELY": "IMMEDIATELY",
                "2_BUSINESS_DAYS": "TWO_BUSINESS_DAYS",
                "2_BUSINESS_DAYS_QUICK_PAY": "TWO_BUSINESS_DAYS",
                "5_BUSINESS_DAYS": "FIVE_BUSINESS_DAYS",
                "10_BUSINESS_DAYS": "TEN_BUSINESS_DAYS",
                "15_BUSINESS_DAYS": "FIFTEEN_BUSINESS_DAYS",
                "30_BUSINESS_DAYS": "THIRTY_BUSINESS_DAYS",
            }
            pt = data["balance_payment_time"]
            balance["paymentTime"] = _PAYMENT_TIME_MAP.get(pt, pt)
        if data.get("balance_terms_begin_on"):
            balance["balancePaymentTermsBeginOn"] = data["balance_terms_begin_on"]
        if balance:
            payload["price"]["balance"] = balance

    # Optional: notes
    if data.get("notes"):
        payload["notes"] = data["notes"]
    if data.get("transport_special_instructions"):
        payload["transportationReleaseNotes"] = data["transport_special_instructions"]

    return payload, warnings
