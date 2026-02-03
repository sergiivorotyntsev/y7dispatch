"""Central Dispatch exporter with defaults and validation.

Features:
1. Load field mapping from cd_field_mapping.yaml
2. Apply constants, variables, and derived fields
3. Generate templates per auction source (Copart/IAA/Manheim)
4. Validate payload using configurable rules
5. Export records from Google Sheets with READY_FOR_CD status
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yaml

from services.central_dispatch import CentralDispatchClient
from services.sheets import PickupRecord, PickupStatus, SheetsClient

logger = logging.getLogger(__name__)


@dataclass
class CDFieldMapping:
    """Loaded field mapping configuration from YAML."""

    version: str
    constants: dict[str, Any]
    variables: dict[str, dict[str, Any]]
    derived: dict[str, dict[str, Any]]
    templates: dict[str, Any]
    auction_overrides: dict[str, dict[str, Any]]
    default_tags: list[dict[str, Any]]
    validation: dict[str, Any]
    sla: dict[str, Any]
    payment: dict[str, Any]
    error_handling: dict[str, Any]


class CDFieldMapper:
    """Loads and applies CD field mapping configuration."""

    DEFAULT_MAPPING_FILE = "cd_field_mapping.yaml"
    LUXURY_MAKES = {
        "BMW",
        "MERCEDES",
        "MERCEDES-BENZ",
        "PORSCHE",
        "AUDI",
        "LEXUS",
        "TESLA",
        "MASERATI",
        "FERRARI",
        "LAMBORGHINI",
        "BENTLEY",
        "ROLLS-ROYCE",
        "ASTON MARTIN",
    }

    def __init__(self, mapping_file: Optional[str] = None):
        self.mapping_file = mapping_file or self.DEFAULT_MAPPING_FILE
        self.mapping: Optional[CDFieldMapping] = None
        self._load_mapping()

    def _load_mapping(self):
        """Load field mapping from YAML file."""
        path = Path(self.mapping_file)
        if not path.exists():
            logger.warning(f"Mapping file {self.mapping_file} not found, using defaults")
            self._use_defaults()
            return

        try:
            with open(path) as f:
                data = yaml.safe_load(f)

            self.mapping = CDFieldMapping(
                version=data.get("version", "1.0"),
                constants=data.get("constants", {}),
                variables=data.get("variables", {}),
                derived=data.get("derived", {}),
                templates=data.get("templates", {}),
                auction_overrides=data.get("auction_overrides", {}),
                default_tags=data.get("default_tags", []),
                validation=data.get("validation", {}),
                sla=data.get("sla", {}),
                payment=data.get("payment", {}),
                error_handling=data.get("error_handling", {}),
            )
            logger.info(f"Loaded CD field mapping v{self.mapping.version}")
        except Exception as e:
            logger.error(f"Failed to load mapping: {e}")
            self._use_defaults()

    def _use_defaults(self):
        """Initialize with default mapping values."""
        self.mapping = CDFieldMapping(
            version="1.0",
            constants={
                "trailer_type": "OPEN",
                "total_currency": "USD",
                "country": "US",
                "marketplace": {"id": 10000, "searchable": True},
                "available_date_offset_days": 0,
                "expiration_days": 14,
            },
            variables={},
            derived={},
            templates={},
            auction_overrides={},
            default_tags=[],
            validation={"required_fields": ["vin", "vehicle_year", "vehicle_make"]},
            sla={"enabled": False},
            payment={"cod": {"enabled": True, "payment_method": "CASH_CERTIFIED_FUNDS"}},
            error_handling={},
        )

    def get_constant(self, key: str, default: Any = None) -> Any:
        """Get a constant value from mapping."""
        keys = key.split(".")
        value = self.mapping.constants
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def get_variable_config(self, section: str, field: str) -> dict[str, Any]:
        """Get variable configuration for a field."""
        section_config = self.mapping.variables.get(section, {})
        return section_config.get(field, {})

    def extract_variable(
        self, record: PickupRecord, source: str, warehouse: Optional[dict] = None
    ) -> Any:
        """Extract a variable value from record or warehouse."""
        if source is None:
            return None

        if source.startswith("warehouse."):
            if warehouse is None:
                return None
            field = source.split(".", 1)[1]
            return warehouse.get(field)

        return getattr(record, source, None)

    def calculate_derived(
        self,
        record: PickupRecord,
        warehouse: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Calculate all derived fields."""
        result = {}

        # Available date
        offset_days = self.get_constant("available_date_offset_days", 0)
        available_date = datetime.utcnow() + timedelta(days=offset_days)
        result["available_date"] = available_date.strftime("%Y-%m-%dT00:00:00Z")

        # Expiration date
        exp_days = self.get_constant("expiration_days", 14)
        expiration_date = available_date + timedelta(days=exp_days)
        result["expiration_date"] = expiration_date.strftime("%Y-%m-%dT00:00:00Z")

        # Trailer type (with luxury override)
        vehicle_make = (record.vehicle_make or "").upper()
        luxury_makes = self.mapping.derived.get("trailer_type_final", {}).get(
            "luxury_makes", list(self.LUXURY_MAKES)
        )
        if vehicle_make in [m.upper() for m in luxury_makes]:
            result["trailer_type"] = "ENCLOSED"
        else:
            result["trailer_type"] = self.get_constant("trailer_type", "OPEN")

        # Has inoperable vehicle
        is_operable = getattr(record, "is_operable", True)
        result["has_inop_vehicle"] = not is_operable if is_operable is not None else False

        return result

    def render_template(
        self,
        auction_source: str,
        record: PickupRecord,
    ) -> str:
        """Render transportation release notes template for auction."""
        templates = self.mapping.templates.get("transportation_release_notes", {})
        source_key = auction_source.lower() if auction_source else "unknown"
        template = templates.get(source_key, templates.get("unknown", ""))

        if not template:
            return ""

        # Build substitution dict
        subs = {
            "lot_number": record.lot_number or "",
            "gate_pass": record.gate_pass or "",
            "release_id": record.lot_number or "",  # Manheim uses release_id
            "location_type": "ONSITE",  # Default
            "offsite_note": "",
        }

        # Handle Manheim offsite
        if source_key == "manheim":
            overrides = self.mapping.auction_overrides.get("manheim", {})
            overrides.get("location_type_handling", {})
            # Could be extended to detect offsite from record

        # Substitute placeholders
        try:
            result = template.format(**subs)
            return result.strip()
        except KeyError as e:
            logger.warning(f"Template placeholder not found: {e}")
            return template

    def get_auction_tags(self, auction_source: str) -> list[dict[str, str]]:
        """Get tags specific to auction source."""
        if not auction_source:
            return []

        source_key = auction_source.lower()
        overrides = self.mapping.auction_overrides.get(source_key, {})
        return overrides.get("tags", [])

    def build_tags(
        self,
        record: PickupRecord,
        warehouse: Optional[dict] = None,
        extraction_score: Optional[float] = None,
    ) -> list[dict[str, str]]:
        """Build complete tags list."""
        tags = []

        # Default tags
        for tag_config in self.mapping.default_tags:
            name = tag_config.get("name")
            if not name:
                continue

            if "value" in tag_config:
                # Static value
                tags.append({"name": name, "value": str(tag_config["value"])})
            elif "source" in tag_config:
                # Dynamic value from record
                source = tag_config["source"]
                if source == "extraction_score" and extraction_score is not None:
                    fmt = tag_config.get("format", "{}")
                    tags.append({"name": name, "value": fmt.format(extraction_score)})
                else:
                    value = self.extract_variable(record, source, warehouse)
                    if value is not None:
                        tags.append({"name": name, "value": str(value)})

        # Auction-specific tags
        tags.extend(self.get_auction_tags(record.auction_source))

        return tags

    def get_company_name_prefix(self, auction_source: str) -> str:
        """Get company name prefix for auction."""
        if not auction_source:
            return ""

        source_key = auction_source.lower()
        overrides = self.mapping.auction_overrides.get(source_key, {})
        pickup_overrides = overrides.get("pickup_stop", {})
        return pickup_overrides.get("company_name_prefix", "")


@dataclass
class CDDefaults:
    """Default values for Central Dispatch listings."""

    trailer_type: str = "OPEN"
    payment_method: str = "CASH_CERTIFIED_FUNDS"
    payment_location: str = "DELIVERY"
    marketplace_id: int = 10000

    # Company info (shipper)
    company_name: str = ""
    company_address: str = ""
    company_city: str = ""
    company_state: str = ""
    company_zip: str = ""
    company_phone: str = ""
    company_contact: str = ""

    # Availability
    available_date_offset_days: int = 0  # 0 = today
    expiration_days: int = 14

    # Notes templates
    pickup_instructions: str = ""
    delivery_instructions: str = ""


@dataclass
class CDRule:
    """Conditional rule for CD listings."""

    name: str
    condition: dict[str, Any]  # e.g., {"auction_source": "COPART"}
    overrides: dict[str, Any]  # Values to override


class CDDefaultsLoader:
    """Loads CD defaults and rules from YAML config."""

    DEFAULT_CONFIG = {
        "defaults": {
            "trailer_type": "OPEN",
            "payment_method": "CASH_CERTIFIED_FUNDS",
            "payment_location": "DELIVERY",
            "marketplace_id": 10000,
            "available_date_offset_days": 0,
            "expiration_days": 14,
        },
        "rules": [
            {
                "name": "enclosed_for_luxury",
                "condition": {"vehicle_make": ["BMW", "MERCEDES", "PORSCHE", "AUDI"]},
                "overrides": {"trailer_type": "ENCLOSED"},
            },
        ],
    }

    def __init__(self, config_file: Optional[str] = "cd_defaults.yaml"):
        self.config_file = config_file
        self.defaults = CDDefaults()
        self.rules: list[CDRule] = []
        self._load_config()

    def _load_config(self):
        """Load configuration from file or use defaults."""
        config = self.DEFAULT_CONFIG.copy()

        if self.config_file and Path(self.config_file).exists():
            try:
                with open(self.config_file) as f:
                    file_config = yaml.safe_load(f)
                    if file_config:
                        config.update(file_config)
                logger.info(f"Loaded CD defaults from {self.config_file}")
            except Exception as e:
                logger.warning(f"Failed to load CD defaults: {e}")

        # Parse defaults
        defaults_dict = config.get("defaults", {})
        for key, value in defaults_dict.items():
            if hasattr(self.defaults, key):
                setattr(self.defaults, key, value)

        # Parse rules
        for rule_dict in config.get("rules", []):
            self.rules.append(
                CDRule(
                    name=rule_dict.get("name", ""),
                    condition=rule_dict.get("condition", {}),
                    overrides=rule_dict.get("overrides", {}),
                )
            )

    def apply_rules(self, record: PickupRecord) -> dict[str, Any]:
        """Apply rules to a record and return overrides."""
        overrides = {}

        for rule in self.rules:
            if self._matches_condition(record, rule.condition):
                logger.debug(f"Rule '{rule.name}' matched for {record.vin}")
                overrides.update(rule.overrides)

        return overrides

    @staticmethod
    def _matches_condition(record: PickupRecord, condition: dict[str, Any]) -> bool:
        """Check if a record matches a rule condition."""
        for field_name, expected in condition.items():
            actual = getattr(record, field_name, None)

            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False

        return True


class CDPayloadValidator:
    """Validates CD listing payload before sending.

    Can use validation rules from CDFieldMapper or fall back to defaults.
    """

    REQUIRED_FIELDS = [
        "trailerType",
        "availableDate",
        "price",
        "stops",
        "vehicles",
    ]

    REQUIRED_STOP_FIELDS = ["city", "state", "postalCode"]
    REQUIRED_VEHICLE_FIELDS = ["vin", "year", "make", "model"]

    # Default validation patterns
    DEFAULT_PATTERNS = {
        "vin": r"^[A-HJ-NPR-Z0-9]{17}$",
        "state": r"^[A-Z]{2}$",
        "postal_code": r"^\d{5}(-\d{4})?$",
    }

    def __init__(self, field_mapper: Optional[CDFieldMapper] = None):
        self.field_mapper = field_mapper
        self._load_validation_rules()

    def _load_validation_rules(self):
        """Load validation rules from field mapper or use defaults."""
        self.patterns = self.DEFAULT_PATTERNS.copy()
        self.price_min = 1.0
        self.price_max = 100000.0
        self.year_min = 1900
        self.year_max = 2030

        if self.field_mapper and self.field_mapper.mapping:
            validation = self.field_mapper.mapping.validation

            # VIN pattern
            vin_config = validation.get("vin", {})
            if vin_config.get("pattern"):
                self.patterns["vin"] = vin_config["pattern"]

            # State pattern
            state_config = validation.get("state", {})
            if state_config.get("pattern"):
                self.patterns["state"] = state_config["pattern"]

            # Postal code pattern
            postal_config = validation.get("postal_code", {})
            if postal_config.get("pattern"):
                self.patterns["postal_code"] = postal_config["pattern"]

            # Price limits
            price_config = validation.get("price", {})
            self.price_min = price_config.get("min", self.price_min)
            self.price_max = price_config.get("max", self.price_max)

            # Year limits
            year_config = validation.get("year", {})
            self.year_min = year_config.get("min", self.year_min)
            self.year_max = year_config.get("max", self.year_max)

    def validate(self, payload: dict[str, Any]) -> list[str]:
        """Validate payload. Returns list of error messages."""
        errors = []

        # Check required top-level fields
        for field_name in self.REQUIRED_FIELDS:
            if field_name not in payload:
                errors.append(f"Missing required field: {field_name}")

        # Validate stops
        stops = payload.get("stops", [])
        if len(stops) < 2:
            errors.append("At least 2 stops (pickup and delivery) required")

        for i, stop in enumerate(stops):
            for field_name in self.REQUIRED_STOP_FIELDS:
                if not stop.get(field_name):
                    errors.append(f"Stop {i + 1} missing required field: {field_name}")

            # Validate state format
            state = stop.get("state", "")
            if state and not re.match(self.patterns["state"], state):
                errors.append(f"Stop {i + 1} has invalid state format: {state}")

            # Validate postal code format
            postal = stop.get("postalCode", "")
            if postal and not re.match(self.patterns["postal_code"], postal):
                errors.append(f"Stop {i + 1} has invalid postal code: {postal}")

        # Validate vehicles
        vehicles = payload.get("vehicles", [])
        if not vehicles:
            errors.append("At least 1 vehicle required")

        for i, vehicle in enumerate(vehicles):
            for field_name in self.REQUIRED_VEHICLE_FIELDS:
                if not vehicle.get(field_name):
                    errors.append(f"Vehicle {i + 1} missing required field: {field_name}")

            # Validate VIN format
            vin = vehicle.get("vin", "")
            if vin and not re.match(self.patterns["vin"], vin):
                errors.append(f"Vehicle {i + 1} has invalid VIN: {vin}")

            # Validate year
            year = vehicle.get("year")
            if year and (year < self.year_min or year > self.year_max):
                errors.append(
                    f"Vehicle {i + 1} year {year} outside valid range "
                    f"({self.year_min}-{self.year_max})"
                )

        # Validate price
        price = payload.get("price", {})
        total = price.get("total", 0)
        if not total or total < self.price_min:
            errors.append(f"Price total must be at least ${self.price_min}")
        elif total > self.price_max:
            errors.append(f"Price total exceeds maximum ${self.price_max}")

        return errors

    def validate_record(self, record: PickupRecord) -> list[str]:
        """Validate a PickupRecord before building payload."""
        errors = []

        # Required fields from mapping
        if self.field_mapper and self.field_mapper.mapping:
            required = self.field_mapper.mapping.validation.get("required_fields", [])
            for field_name in required:
                value = getattr(record, field_name, None)
                if not value:
                    errors.append(f"Missing required field: {field_name}")

        # VIN validation
        if record.vin:
            if not re.match(self.patterns["vin"], record.vin):
                errors.append(f"Invalid VIN format: {record.vin}")

        return errors


class CDExporter:
    """Exports records to Central Dispatch from Google Sheets.

    Supports two modes:
    1. Legacy mode with CDDefaultsLoader (cd_defaults.yaml)
    2. New mode with CDFieldMapper (cd_field_mapping.yaml)
    """

    def __init__(
        self,
        cd_client: CentralDispatchClient,
        sheets_client: Optional[SheetsClient],
        defaults_loader: Optional[CDDefaultsLoader] = None,
        field_mapper: Optional[CDFieldMapper] = None,
    ):
        self.cd_client = cd_client
        self.sheets_client = sheets_client
        self.defaults_loader = defaults_loader or CDDefaultsLoader()
        self.field_mapper = field_mapper or CDFieldMapper()
        self.validator = CDPayloadValidator(field_mapper=self.field_mapper)

    def build_listing_payload(
        self,
        record: PickupRecord,
        delivery_address: dict[str, str],
        price: float,
        extraction_score: Optional[float] = None,
    ) -> dict[str, Any]:
        """Build CD listing payload from a pickup record.

        Uses field mapping configuration for:
        - Constants (trailer type, currency, marketplace settings)
        - Derived fields (dates, trailer type override for luxury)
        - Templates (transportation release notes per auction)
        - Tags (auction source, gate pass, automation version)
        """
        mapper = self.field_mapper
        defaults = self.defaults_loader.defaults

        # Calculate derived fields
        derived = mapper.calculate_derived(record, delivery_address)

        # Get payment configuration
        payment_config = mapper.mapping.payment
        cod_config = payment_config.get("cod", {})
        payment_method = cod_config.get("payment_method", defaults.payment_method)
        payment_location = cod_config.get("payment_location", defaults.payment_location)

        # Get marketplace configuration
        marketplace_config = mapper.get_constant("marketplace", {})
        marketplace_id = marketplace_config.get("id", defaults.marketplace_id)

        # Build pickup stop with company name prefix
        company_prefix = mapper.get_company_name_prefix(record.auction_source)
        pickup_name = record.pickup_name or ""
        if company_prefix and not pickup_name.startswith(company_prefix):
            pickup_name = f"{company_prefix}{pickup_name}"

        pickup_stop = {
            "stopNumber": 1,
            "city": record.pickup_city,
            "state": record.pickup_state,
            "postalCode": record.pickup_zip,
            "country": mapper.get_constant("country", "US"),
        }
        if pickup_name:
            pickup_stop["locationName"] = pickup_name
        if record.pickup_address_raw:
            pickup_stop["address"] = record.pickup_address_raw

        # Build delivery stop (from warehouse or provided address)
        delivery_stop = {
            "stopNumber": 2,
            "city": delivery_address.get("city", ""),
            "state": delivery_address.get("state", ""),
            "postalCode": delivery_address.get("zip", delivery_address.get("zip_code", "")),
            "country": mapper.get_constant("country", "US"),
        }
        if delivery_address.get("name"):
            delivery_stop["locationName"] = delivery_address["name"]
        if delivery_address.get("address"):
            delivery_stop["address"] = delivery_address["address"]
        if delivery_address.get("contact"):
            delivery_stop["contactName"] = delivery_address["contact"]
        if delivery_address.get("phone"):
            delivery_stop["contactPhone"] = delivery_address["phone"]

        # Get vehicle type default
        vehicle_config = mapper.get_constant("vehicle", {})
        vehicle_type = vehicle_config.get("type", "AUTO")
        is_operable = getattr(record, "is_operable", vehicle_config.get("is_operable", True))

        # Build vehicle
        vehicle = {
            "pickupStopNumber": 1,
            "dropoffStopNumber": 2,
            "vin": record.vin,
            "year": int(record.vehicle_year) if record.vehicle_year else 2020,
            "make": record.vehicle_make,
            "model": record.vehicle_model,
            "vehicleType": vehicle_type,
            "isInoperable": not is_operable if is_operable is not None else False,
        }
        if record.vehicle_color:
            vehicle["color"] = record.vehicle_color
        if record.lot_number:
            vehicle["lotNumber"] = record.lot_number

        # Build payload
        payload = {
            "trailerType": derived["trailer_type"],
            "hasInOpVehicle": derived["has_inop_vehicle"],
            "availableDate": derived["available_date"],
            "expirationDate": derived["expiration_date"],
            "price": {
                "total": price,
                "currency": mapper.get_constant("total_currency", "USD"),
                "cod": {
                    "amount": price,
                    "paymentMethod": payment_method,
                    "paymentLocation": payment_location,
                },
            },
            "stops": [pickup_stop, delivery_stop],
            "vehicles": [vehicle],
            "marketplaces": [
                {
                    "marketplaceId": marketplace_id,
                    "searchable": marketplace_config.get("searchable", True),
                    "makeOffersEnabled": marketplace_config.get("make_offers_enabled", True),
                }
            ],
        }

        # Add external references
        if record.clickup_task_id:
            payload["shipperOrderId"] = record.clickup_task_id
        if record.idempotency_key:
            payload["externalId"] = record.idempotency_key
        if record.lot_number:
            payload["partnerReferenceId"] = record.lot_number

        # Generate transportation release notes from template
        transport_notes = mapper.render_template(record.auction_source, record)
        if transport_notes:
            payload["transportationReleaseNotes"] = transport_notes
        else:
            # Fallback to legacy format
            notes_parts = []
            if record.auction_source:
                if record.auction_source == "COPART" and record.lot_number:
                    notes_parts.append(f"LOT#: {record.lot_number}")
                elif record.auction_source == "IAA" and record.lot_number:
                    notes_parts.append(f"Stock#: {record.lot_number}")
                elif record.auction_source == "MANHEIM":
                    notes_parts.append(f"Release ID: {record.lot_number}")
            if record.gate_pass:
                notes_parts.append(f"Gate Pass: {record.gate_pass}")
            if defaults.pickup_instructions:
                notes_parts.append(defaults.pickup_instructions)
            if notes_parts:
                payload["transportationReleaseNotes"] = " | ".join(notes_parts)

        # Add tags
        tags = mapper.build_tags(record, delivery_address, extraction_score)
        if tags:
            payload["tags"] = tags

        # Add inspection/verification flags
        if mapper.get_constant("requires_inspection"):
            payload["requiresInspection"] = True
        if mapper.get_constant("requires_driver_verification_at_pickup"):
            payload["requiresDriverVerificationAtPickup"] = True

        return payload

    def export_record(
        self,
        record: PickupRecord,
        delivery_address: dict[str, str],
        price: float,
        row_number: Optional[int] = None,
        extraction_score: Optional[float] = None,
    ) -> dict[str, Any]:
        """Export a single record to Central Dispatch.

        Args:
            record: PickupRecord with vehicle and pickup information
            delivery_address: Destination warehouse/address dict
            price: Transport price
            row_number: Optional row number in Google Sheets for status updates
            extraction_score: Optional parser confidence score (0.0-1.0)

        Returns:
            Dict with success status and listing_id or error message
        """
        # Pre-validate record
        record_errors = self.validator.validate_record(record)
        if record_errors:
            error_msg = "; ".join(record_errors)
            logger.error(f"Record validation failed for {record.vin}: {error_msg}")

            if self.sheets_client and row_number:
                self.sheets_client.update_status(
                    row_number, PickupStatus.ERROR, error_message=f"Record: {error_msg}"
                )

            return {"success": False, "error": error_msg}

        # Build payload
        payload = self.build_listing_payload(record, delivery_address, price, extraction_score)

        # Validate payload
        payload_errors = self.validator.validate(payload)
        if payload_errors:
            error_msg = "; ".join(payload_errors)
            logger.error(f"Payload validation failed for {record.vin}: {error_msg}")

            if self.sheets_client and row_number:
                self.sheets_client.update_status(
                    row_number, PickupStatus.ERROR, error_message=f"Payload: {error_msg}"
                )

            return {"success": False, "error": error_msg}

        # Log payload for debugging
        logger.debug(f"CD payload for {record.vin}: {payload}")

        # Send to CD
        try:
            result = self.cd_client.create_listing_raw(payload)

            if result.get("success"):
                listing_id = result.get("listing_id", "")
                logger.info(f"Created CD listing {listing_id} for {record.vin}")

                if self.sheets_client and row_number:
                    self.sheets_client.update_status(
                        row_number,
                        PickupStatus.CD_CREATED,
                        cd_listing_id=listing_id,
                    )

                return {
                    "success": True,
                    "listing_id": listing_id,
                    "etag": result.get("etag"),
                    "location": result.get("location"),
                }
            else:
                error_msg = result.get("error", "Unknown error")
                logger.error(f"CD API error for {record.vin}: {error_msg}")

                if self.sheets_client and row_number:
                    self.sheets_client.update_status(
                        row_number, PickupStatus.ERROR, error_message=f"CD API: {error_msg}"
                    )

                return {"success": False, "error": error_msg}

        except Exception as e:
            logger.error(f"Exception exporting {record.vin}: {e}")
            if self.sheets_client and row_number:
                self.sheets_client.update_status(
                    row_number, PickupStatus.ERROR, error_message=str(e)
                )
            return {"success": False, "error": str(e)}

    def export_pending_from_sheets(
        self,
        delivery_address: dict[str, str],
        default_price: float = 500.0,
    ) -> dict[str, Any]:
        """Export all READY_FOR_CD records from Google Sheets."""
        if not self.sheets_client:
            return {"error": "Sheets client not configured"}

        records = self.sheets_client.get_records_by_status(PickupStatus.READY_FOR_CD)
        logger.info(f"Found {len(records)} records ready for CD export")

        results = {"exported": 0, "failed": 0, "errors": []}

        for row_number, record in records:
            result = self.export_record(record, delivery_address, default_price, row_number)

            if result.get("success"):
                results["exported"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(
                    {
                        "vin": record.vin,
                        "error": result.get("error"),
                    }
                )

        return results


# Add create_listing_raw method to CentralDispatchClient if not exists
def _add_create_listing_raw():
    """Monkey-patch CentralDispatchClient to add create_listing_raw method."""
    from services.central_dispatch import CentralDispatchClient

    if not hasattr(CentralDispatchClient, "create_listing_raw"):

        def create_listing_raw(self, payload: dict[str, Any]) -> dict[str, Any]:
            """Create a listing from raw payload dict."""
            response = self._make_request("POST", "/listings", data=payload)
            if response.status_code == 201:
                location = response.headers.get("Location", "")
                listing_id = location.split("/")[-1] if location else None
                return {
                    "success": True,
                    "listing_id": listing_id,
                    "etag": response.headers.get("ETag"),
                    "location": location,
                }
            else:
                return {"success": False, "error": response.text}

        CentralDispatchClient.create_listing_raw = create_listing_raw


_add_create_listing_raw()
