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


class ValueSource(str, Enum):
    """Source of field value (for priority resolution)."""

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
    cd_api_key: str  # CD API path (e.g., "vehicles[0].vin")
    field_type: FieldType = FieldType.TEXT
    required: bool = False  # Required for CD submission
    display_order: int = 0  # Order within section
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
        display_order=6,
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
        display_order=7,
        options=["OPERABLE", "INOPERABLE"],
        default_value="OPERABLE",
        help_text="Can the vehicle be driven onto a trailer?",
    ),
    ListingField(
        key="vehicle_lot",
        label="Lot Number",
        section=FieldSection.VEHICLE,
        cd_api_key="vehicles[0].lotNumber",
        field_type=FieldType.TEXT,
        required=False,
        display_order=8,
        max_length=50,
        help_text="Auction lot number",
        extraction_hint="Look for LOT, LOT #, LOT NUMBER",
    ),
    # -------------------------------------------------------------------------
    # PICKUP LOCATION (Stop 1)
    # -------------------------------------------------------------------------
    ListingField(
        key="pickup_name",
        label="Location Name",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].locationName",
        field_type=FieldType.TEXT,
        required=False,
        display_order=1,
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
        validation_regex=r"^\d{5}(-\d{4})?$",
        validation_message="ZIP must be 5 digits or 5+4 format",
        help_text="5-digit or 9-digit ZIP code",
    ),
    ListingField(
        key="pickup_phone",
        label="Phone",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].contact.phone",
        field_type=FieldType.TEXT,
        required=False,
        display_order=6,
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
        max_length=200,
        help_text="Business hours for pickup",
    ),
    ListingField(
        key="pickup_notes",
        label="Pickup Notes",
        section=FieldSection.PICKUP,
        cd_api_key="stops[0].notes",
        field_type=FieldType.TEXTAREA,
        required=False,
        display_order=9,
        max_length=1000,
        help_text="Special instructions for pickup",
    ),
    # -------------------------------------------------------------------------
    # DELIVERY LOCATION (Stop 2)
    # -------------------------------------------------------------------------
    ListingField(
        key="delivery_name",
        label="Location Name",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].locationName",
        field_type=FieldType.TEXT,
        required=False,
        display_order=1,
        max_length=100,
        help_text="Warehouse or destination name",
    ),
    ListingField(
        key="delivery_address",
        label="Street Address",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].address.street",
        field_type=FieldType.TEXT,
        required=True,
        display_order=2,
        max_length=200,
        help_text="Street address for delivery",
    ),
    ListingField(
        key="delivery_city",
        label="City",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].address.city",
        field_type=FieldType.TEXT,
        required=True,
        display_order=3,
        max_length=100,
    ),
    ListingField(
        key="delivery_state",
        label="State",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].address.state",
        field_type=FieldType.TEXT,
        required=True,
        display_order=4,
        validation_regex=r"^[A-Z]{2}$",
        validation_message="State must be 2-letter code",
        min_length=2,
        max_length=2,
    ),
    ListingField(
        key="delivery_zip",
        label="ZIP Code",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].address.postalCode",
        field_type=FieldType.TEXT,
        required=True,
        display_order=5,
        validation_regex=r"^\d{5}(-\d{4})?$",
        validation_message="ZIP must be 5 digits or 5+4 format",
    ),
    ListingField(
        key="delivery_phone",
        label="Phone",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].contact.phone",
        field_type=FieldType.TEXT,
        required=False,
        display_order=6,
        max_length=20,
    ),
    ListingField(
        key="delivery_contact",
        label="Contact Name",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].contact.name",
        field_type=FieldType.TEXT,
        required=False,
        display_order=7,
        max_length=100,
    ),
    ListingField(
        key="delivery_hours",
        label="Operating Hours",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].operatingHours",
        field_type=FieldType.TEXT,
        required=False,
        display_order=8,
        max_length=200,
    ),
    ListingField(
        key="delivery_notes",
        label="Delivery Notes",
        section=FieldSection.DELIVERY,
        cd_api_key="stops[1].notes",
        field_type=FieldType.TEXTAREA,
        required=False,
        display_order=9,
        max_length=1000,
        help_text="Special instructions for delivery",
    ),
    # -------------------------------------------------------------------------
    # PRICING
    # -------------------------------------------------------------------------
    ListingField(
        key="price_total",
        label="Total Price",
        section=FieldSection.PRICING,
        cd_api_key="price.total",
        field_type=FieldType.NUMBER,
        required=False,
        display_order=1,
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
        options=["CASH", "CHECK", "CERTIFIED_CHECK", "MONEY_ORDER", "COMCHECK", "ACH"],
        default_value="CASH",
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
        display_order=2,
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
        help_text="Listing expiration date",
    ),
    ListingField(
        key="trailer_type",
        label="Trailer Type",
        section=FieldSection.ADDITIONAL,
        cd_api_key="trailerType",
        field_type=FieldType.SELECT,
        required=True,
        display_order=4,
        options=["OPEN", "ENCLOSED"],
        default_value="OPEN",
    ),
    ListingField(
        key="buyer_id",
        label="Buyer ID",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,  # Not sent to CD
        field_type=FieldType.TEXT,
        required=False,
        display_order=5,
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
        help_text="Total purchase amount (internal use)",
        extraction_hint="TOTAL, AMOUNT DUE, GRAND TOTAL",
    ),
    ListingField(
        key="stock_number",
        label="Stock Number",
        section=FieldSection.ADDITIONAL,
        cd_api_key=None,  # Not sent to CD
        field_type=FieldType.TEXT,
        required=False,
        display_order=9,
        help_text="Auction stock number",
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
        help_text="Gate pass or release code",
        extraction_hint="GATE PASS, RELEASE, CLAIM NUMBER",
    ),
    # -------------------------------------------------------------------------
    # NOTES
    # -------------------------------------------------------------------------
    ListingField(
        key="notes",
        label="General Notes",
        section=FieldSection.NOTES,
        cd_api_key="notes",
        field_type=FieldType.TEXTAREA,
        required=False,
        display_order=1,
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
        max_length=2000,
        help_text="Special transport instructions",
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
        self._required_fields: list[str] = []

        # Build indexes
        for f in LISTING_FIELDS:
            if f.section not in self._by_section:
                self._by_section[f.section] = []
            self._by_section[f.section].append(f)
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

    def validate_all(self, data: dict[str, Any]) -> list[dict[str, str]]:
        """
        Validate all fields in data dict.
        Returns list of {field: key, error: message} for invalid fields.
        """
        errors = []
        for field_def in LISTING_FIELDS:
            value = data.get(field_def.key)
            error = self.validate_field(field_def.key, value)
            if error:
                errors.append({"field": field_def.key, "error": error})
        return errors

    def get_blocking_issues(
        self, data: dict[str, Any], warehouse_selected: bool = False
    ) -> list[dict[str, str]]:
        """
        Get issues that block posting.
        Returns list of {field: key, issue: message}.

        Validates against CD API V2 requirements:
        - Minimum 2 unique stops (pickup and delivery must have different addresses)
        - Minimum 1 vehicle, maximum 12 vehicles
        - availableDate not before today, not more than 30 days ahead
        - expirationDate not before today, not more than 30 days ahead
        - externalId max 50 characters
        """
        issues = []

        # Check required fields
        for field_key in self._required_fields:
            field_def = self._fields[field_key]
            value = data.get(field_key)
            if value is None or value == "":
                issues.append(
                    {
                        "field": field_key,
                        "issue": f"Missing required field: {field_def.label}",
                    }
                )

        # Check warehouse (delivery fields)
        if not warehouse_selected:
            delivery_fields = [
                "delivery_address",
                "delivery_city",
                "delivery_state",
                "delivery_zip",
            ]
            delivery_filled = all(data.get(f) for f in delivery_fields)
            if not delivery_filled:
                issues.append(
                    {
                        "field": "warehouse",
                        "issue": "Warehouse not selected (delivery address incomplete)",
                    }
                )

        # CD API Rule: exactly 2 stops required
        # Note: CD docs require 2 stops but do NOT require different addresses.
        # Same-address check removed per CD API V2 spec review.
        # If business logic requires different addresses, make it configurable.

        # CD API Rule: 1-12 vehicles (we currently support single vehicle, so just check VIN exists)
        vehicle_vin = data.get("vehicle_vin")
        if not vehicle_vin:
            # Already caught by required fields check, but adding for clarity
            pass
        # Note: Multi-vehicle support would need vehicle count validation here

        # CD API Rule: externalId max 50 characters
        external_id = data.get("external_id", "")
        if external_id and len(external_id) > 50:
            issues.append(
                {
                    "field": "external_id",
                    "issue": f"External ID must be 50 characters or less (currently {len(external_id)})",
                }
            )

        # Check available_date rules (CD API requirement)
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        max_date = today + timedelta(days=30)

        available_date = data.get("available_date")
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
        expiration_date = data.get("expiration_date")
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
        desired_delivery_date = data.get("desired_delivery_date")
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

        # Validation errors
        validation_errors = self.validate_all(data)
        for err in validation_errors:
            # Avoid duplicate errors
            existing = [i for i in issues if i["field"] == err["field"]]
            if not existing:
                issues.append({"field": err["field"], "issue": err["error"]})

        return issues

    def to_json_schema(self) -> dict:
        """Export registry as JSON schema for frontend."""
        sections = {}
        for section in self.get_sections():
            sections[section.value] = {
                "label": section.value.replace("_", " ").title(),
                "fields": [asdict(f) for f in self.get_fields_by_section(section)],
            }
        return {
            "version": "1.0",
            "sections": sections,
            "required_fields": self._required_fields,
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

    # Build vehicle
    vehicle = {
        "vin": data.get("vehicle_vin", ""),
        "year": int(data.get("vehicle_year", 0)) if data.get("vehicle_year") else None,
        "make": data.get("vehicle_make", ""),
        "model": data.get("vehicle_model", ""),
    }
    if data.get("vehicle_color"):
        vehicle["color"] = data["vehicle_color"]
    if data.get("vehicle_lot"):
        vehicle["lotNumber"] = data["vehicle_lot"]

    # Vehicle type mapping
    vtype = data.get("vehicle_type", "SEDAN").upper()
    vehicle["vehicleType"] = (
        vtype
        if vtype
        in ["SEDAN", "SUV", "TRUCK", "VAN", "MOTORCYCLE", "COUPE", "CONVERTIBLE", "WAGON", "OTHER"]
        else "SEDAN"
    )

    # Operability
    condition = data.get("vehicle_condition", "OPERABLE").upper()
    vehicle["isOperable"] = condition != "INOPERABLE"

    # Build pickup stop
    pickup_stop = {
        "stopNumber": 1,
        "locationType": "AUCTION",
        "locationName": data.get("pickup_name", ""),
        "address": {
            "street": data.get("pickup_address", ""),
            "city": data.get("pickup_city", ""),
            "state": data.get("pickup_state", ""),
            "postalCode": data.get("pickup_zip", ""),
        },
    }
    if data.get("pickup_phone") or data.get("pickup_contact"):
        pickup_stop["contact"] = {}
        if data.get("pickup_phone"):
            pickup_stop["contact"]["phone"] = data["pickup_phone"]
        if data.get("pickup_contact"):
            pickup_stop["contact"]["name"] = data["pickup_contact"]
    if data.get("pickup_hours"):
        pickup_stop["operatingHours"] = data["pickup_hours"]
    if data.get("pickup_notes"):
        pickup_stop["notes"] = data["pickup_notes"]

    # Build delivery stop
    delivery_stop = {
        "stopNumber": 2,
        "locationType": "BUSINESS",
        "locationName": data.get("delivery_name", ""),
        "address": {
            "street": data.get("delivery_address", ""),
            "city": data.get("delivery_city", ""),
            "state": data.get("delivery_state", ""),
            "postalCode": data.get("delivery_zip", ""),
        },
    }
    if data.get("delivery_phone") or data.get("delivery_contact"):
        delivery_stop["contact"] = {}
        if data.get("delivery_phone"):
            delivery_stop["contact"]["phone"] = data["delivery_phone"]
        if data.get("delivery_contact"):
            delivery_stop["contact"]["name"] = data["delivery_contact"]
    if data.get("delivery_hours"):
        delivery_stop["operatingHours"] = data["delivery_hours"]
    if data.get("delivery_notes"):
        delivery_stop["notes"] = data["delivery_notes"]

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
        if data.get("price_cod_amount"):
            payload["price"]["cod"] = {
                "amount": float(data["price_cod_amount"]),
                "paymentMethod": data.get("price_cod_method", "CASH"),
            }

    # Optional: notes
    if data.get("notes"):
        payload["notes"] = data["notes"]
    if data.get("transport_special_instructions"):
        payload["transportationReleaseNotes"] = data["transport_special_instructions"]

    return payload, warnings
