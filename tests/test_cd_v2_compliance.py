"""
Central Dispatch API V2 Compliance Tests

Tests validation rules for CD Listings API V2:
- Exactly 2 stops (pickup and delivery)
- 1-12 vehicles per listing
- No duplicate VINs
- Required fields for stops and vehicles
- Field length limits
"""

import pytest
from datetime import datetime, timedelta

from api.listing_fields import (
    ListingFieldRegistry,
    build_cd_payload,
    get_registry,
    FieldCategory,
)


@pytest.fixture
def registry():
    """Get fresh registry instance."""
    return ListingFieldRegistry()


@pytest.fixture
def minimal_valid_data():
    """Minimal data that should pass validation."""
    return {
        "vehicle_vin": "1HGBH41JXMN109186",
        "vehicle_year": 2021,
        "vehicle_make": "TOYOTA",
        "vehicle_model": "CAMRY",
        "vehicle_type": "SEDAN",
        "vehicle_condition": "OPERABLE",
        "pickup_address": "123 Auction Way",
        "pickup_city": "Los Angeles",
        "pickup_state": "CA",
        "pickup_zip": "90001",
        "delivery_address": "456 Warehouse Blvd",
        "delivery_city": "Newark",
        "delivery_state": "NJ",
        "delivery_zip": "07102",
        "trailer_type": "OPEN",
        "available_date": datetime.now().strftime("%Y-%m-%d"),
    }


class TestStopsValidation:
    """Test CD V2 requirement: exactly 2 stops."""

    def test_valid_two_stops(self, registry, minimal_valid_data):
        """Should pass with complete pickup and delivery."""
        issues = registry.get_blocking_issues(
            minimal_valid_data, warehouse_selected=True, mode="export"
        )
        stops_issues = [i for i in issues if i["field"] == "stops"]
        assert len(stops_issues) == 0, f"Unexpected stops issues: {stops_issues}"

    def test_missing_pickup_city(self, registry, minimal_valid_data):
        """Should fail when pickup city is missing."""
        data = {**minimal_valid_data, "pickup_city": ""}
        issues = registry.get_blocking_issues(data, warehouse_selected=True, mode="export")
        assert any("pickup" in i["issue"].lower() for i in issues)

    def test_missing_pickup_state(self, registry, minimal_valid_data):
        """Should fail when pickup state is missing."""
        data = {**minimal_valid_data, "pickup_state": ""}
        issues = registry.get_blocking_issues(data, warehouse_selected=True, mode="export")
        assert any("pickup" in i["issue"].lower() or "state" in i["issue"].lower() for i in issues)

    def test_missing_pickup_zip(self, registry, minimal_valid_data):
        """Should fail when pickup zip is missing."""
        data = {**minimal_valid_data, "pickup_zip": ""}
        issues = registry.get_blocking_issues(data, warehouse_selected=True, mode="export")
        assert any("pickup" in i["issue"].lower() or "zip" in i["issue"].lower() for i in issues)

    def test_missing_delivery_without_warehouse(self, registry, minimal_valid_data):
        """Should fail when delivery is incomplete and no warehouse selected."""
        data = {**minimal_valid_data}
        del data["delivery_city"]
        del data["delivery_state"]
        del data["delivery_zip"]
        issues = registry.get_blocking_issues(data, warehouse_selected=False, mode="export")
        assert any("delivery" in i["issue"].lower() or "warehouse" in i["issue"].lower() for i in issues)

    def test_delivery_ok_with_warehouse_selected(self, registry, minimal_valid_data):
        """Delivery fields skipped when warehouse is selected."""
        data = {**minimal_valid_data}
        del data["delivery_city"]
        del data["delivery_state"]
        del data["delivery_zip"]
        # With warehouse_selected=True, delivery validation is skipped
        issues = registry.get_blocking_issues(data, warehouse_selected=True, mode="export")
        delivery_issues = [i for i in issues if "delivery" in i.get("field", "").lower()]
        assert len(delivery_issues) == 0


class TestVehicleValidation:
    """Test CD V2 requirement: 1-12 vehicles, no duplicate VINs."""

    def test_valid_single_vehicle(self, registry, minimal_valid_data):
        """Should pass with one valid vehicle."""
        issues = registry.get_blocking_issues(minimal_valid_data, warehouse_selected=True, mode="export")
        vehicle_issues = [i for i in issues if i["field"] == "vehicles" or i["field"] == "vehicle_vin"]
        assert len(vehicle_issues) == 0, f"Unexpected vehicle issues: {vehicle_issues}"

    def test_missing_vin(self, registry, minimal_valid_data):
        """Should fail when VIN is missing."""
        data = {**minimal_valid_data, "vehicle_vin": ""}
        issues = registry.get_blocking_issues(data, warehouse_selected=True, mode="export")
        assert any("vin" in i["issue"].lower() or "vehicle" in i["issue"].lower() for i in issues)

    def test_invalid_vin_length(self, registry, minimal_valid_data):
        """Should fail when VIN is not 17 characters."""
        data = {**minimal_valid_data, "vehicle_vin": "1HGBH41JXMN10918"}  # 16 chars
        issues = registry.get_blocking_issues(data, warehouse_selected=True, mode="export")
        assert any("17" in i["issue"] for i in issues)

    def test_vin_format_invalid_chars(self, registry, minimal_valid_data):
        """Should fail when VIN contains I, O, or Q."""
        # VIN with invalid char 'I'
        data = {**minimal_valid_data, "vehicle_vin": "1HGBH41IXMN109186"}
        issues = registry.get_blocking_issues(data, warehouse_selected=True, mode="export")
        # The regex ^[A-HJ-NPR-Z0-9]{17}$ should catch this
        vin_issues = [i for i in issues if "vin" in i["field"].lower()]
        assert len(vin_issues) > 0, "Invalid VIN chars should be caught"


class TestPayloadBuilder:
    """Test CD payload builder produces valid V2 structure."""

    def test_payload_structure(self, minimal_valid_data):
        """Payload should have required V2 structure."""
        payload, warnings = build_cd_payload(minimal_valid_data, run_id=123)

        assert "externalId" in payload
        assert "trailerType" in payload
        assert "availableDate" in payload
        assert "stops" in payload
        assert "vehicles" in payload

        assert len(payload["stops"]) == 2
        assert len(payload["vehicles"]) == 1

    def test_stop_numbers(self, minimal_valid_data):
        """Stops should have correct stop numbers."""
        payload, _ = build_cd_payload(minimal_valid_data, run_id=123)

        assert payload["stops"][0]["stopNumber"] == 1
        assert payload["stops"][1]["stopNumber"] == 2

    def test_pickup_stop_structure(self, minimal_valid_data):
        """Pickup stop should have address structure."""
        payload, _ = build_cd_payload(minimal_valid_data, run_id=123)

        pickup = payload["stops"][0]
        assert "locationType" in pickup
        assert "address" in pickup
        assert "city" in pickup["address"]
        assert "state" in pickup["address"]
        assert "postalCode" in pickup["address"]

    def test_vehicle_structure(self, minimal_valid_data):
        """Vehicle should have required fields."""
        payload, _ = build_cd_payload(minimal_valid_data, run_id=123)

        vehicle = payload["vehicles"][0]
        assert vehicle["vin"] == "1HGBH41JXMN109186"
        assert vehicle["year"] == 2021
        assert vehicle["make"] == "TOYOTA"
        assert vehicle["model"] == "CAMRY"
        assert "vehicleType" in vehicle
        assert "isOperable" in vehicle

    def test_external_id_truncation(self, minimal_valid_data):
        """External ID should be truncated to 50 chars."""
        data = {**minimal_valid_data, "external_id": "X" * 100}
        payload, warnings = build_cd_payload(data, run_id=123)

        assert len(payload["externalId"]) <= 50
        assert any("truncated" in w.lower() for w in warnings)

    def test_partner_reference_id(self, minimal_valid_data):
        """Partner reference ID should be generated for retry safety."""
        payload, _ = build_cd_payload(minimal_valid_data, run_id=456)

        assert "partnerReferenceId" in payload
        assert "456" in payload["partnerReferenceId"]

    def test_trailer_type_default(self, minimal_valid_data):
        """Trailer type should default to OPEN."""
        data = {**minimal_valid_data}
        del data["trailer_type"]
        payload, _ = build_cd_payload(data, run_id=123)

        assert payload["trailerType"] == "OPEN"

    def test_inoperable_vehicle(self, minimal_valid_data):
        """Inoperable vehicle should set hasInOpVehicle=true."""
        data = {**minimal_valid_data, "vehicle_condition": "INOPERABLE"}
        payload, _ = build_cd_payload(data, run_id=123)

        assert payload["hasInOpVehicle"] is True
        assert payload["vehicles"][0]["isOperable"] is False


class TestFieldRegistry:
    """Test field registry configuration."""

    def test_cd_required_fields_exist(self, registry):
        """CD_REQUIRED fields should include critical fields."""
        required = registry.get_fields_by_category(FieldCategory.CD_REQUIRED)
        required_keys = [f.key for f in required]

        assert "vehicle_vin" in required_keys
        assert "vehicle_year" in required_keys
        assert "vehicle_make" in required_keys
        assert "vehicle_model" in required_keys
        assert "pickup_city" in required_keys
        assert "pickup_state" in required_keys

    def test_delivery_fields_are_warehouse_ref(self, registry):
        """Delivery fields should have WAREHOUSE_REF source type."""
        from api.listing_fields import FieldSourceType

        delivery_fields = [
            "delivery_address",
            "delivery_city",
            "delivery_state",
            "delivery_zip",
        ]
        for key in delivery_fields:
            field = registry.get_field(key)
            assert field is not None, f"Field {key} not found"
            assert field.source_type == FieldSourceType.WAREHOUSE_REF, f"{key} should be WAREHOUSE_REF"

    def test_internal_fields_not_in_cd(self, registry):
        """Internal fields should not be sent to CD API."""
        internal = registry.get_fields_by_category(FieldCategory.INTERNAL)
        for field in internal:
            assert field.cd_api_key is None, f"{field.key} should not have cd_api_key"


class TestTrainingModeValidation:
    """Test that training mode skips export-only validations."""

    def test_training_mode_skips_delivery(self, registry, minimal_valid_data):
        """Training mode should not require delivery fields."""
        data = {**minimal_valid_data}
        del data["delivery_address"]
        del data["delivery_city"]
        del data["delivery_state"]
        del data["delivery_zip"]

        issues = registry.get_blocking_issues(data, warehouse_selected=False, mode="training")
        delivery_issues = [i for i in issues if "delivery" in i.get("field", "").lower()]
        assert len(delivery_issues) == 0, "Training mode should skip delivery validation"

    def test_training_mode_skips_trailer_type(self, registry, minimal_valid_data):
        """Training mode should not require trailer_type."""
        data = {**minimal_valid_data}
        del data["trailer_type"]

        issues = registry.get_blocking_issues(data, warehouse_selected=False, mode="training")
        trailer_issues = [i for i in issues if "trailer" in i.get("issue", "").lower()]
        assert len(trailer_issues) == 0, "Training mode should skip trailer_type validation"


class TestDateValidation:
    """Test date validation for CD API requirements."""

    def test_available_date_in_past(self, registry, minimal_valid_data):
        """Should fail when available_date is in the past."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        data = {**minimal_valid_data, "available_date": yesterday}

        issues = registry.get_blocking_issues(data, warehouse_selected=True, mode="export")
        assert any("past" in i["issue"].lower() for i in issues)

    def test_available_date_too_far_future(self, registry, minimal_valid_data):
        """Should fail when available_date is more than 30 days ahead."""
        far_future = (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d")
        data = {**minimal_valid_data, "available_date": far_future}

        issues = registry.get_blocking_issues(data, warehouse_selected=True, mode="export")
        assert any("30 days" in i["issue"].lower() for i in issues)

    def test_valid_available_date(self, registry, minimal_valid_data):
        """Should pass with today's date."""
        today = datetime.now().strftime("%Y-%m-%d")
        data = {**minimal_valid_data, "available_date": today}

        issues = registry.get_blocking_issues(data, warehouse_selected=True, mode="export")
        date_issues = [i for i in issues if "available_date" in i.get("field", "")]
        assert len(date_issues) == 0
