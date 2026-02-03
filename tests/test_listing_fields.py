"""
Tests for Listing Field Registry

Tests the single source of truth for CD Listings API fields.
"""

from datetime import datetime, timedelta

from api.listing_fields import (
    LISTING_FIELDS,
    FieldSection,
    FieldType,
    ListingField,
    build_cd_payload,
    get_registry,
)


class TestListingFieldRegistry:
    """Tests for ListingFieldRegistry."""

    def test_get_registry_singleton(self):
        """Registry should be singleton."""
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_get_all_fields(self):
        """Should return all fields."""
        registry = get_registry()
        fields = registry.get_all_fields()
        assert len(fields) > 0
        assert all(isinstance(f, ListingField) for f in fields)

    def test_get_required_fields(self):
        """Should return required field keys."""
        registry = get_registry()
        required = registry.get_required_fields()
        assert "vehicle_vin" in required
        assert "vehicle_year" in required
        assert "pickup_address" in required
        assert "pickup_city" in required

    def test_get_fields_by_section(self):
        """Should return fields grouped by section."""
        registry = get_registry()

        vehicle_fields = registry.get_fields_by_section(FieldSection.VEHICLE)
        assert len(vehicle_fields) > 0
        assert all(f.section == FieldSection.VEHICLE for f in vehicle_fields)

        pickup_fields = registry.get_fields_by_section(FieldSection.PICKUP)
        assert len(pickup_fields) > 0
        assert all(f.section == FieldSection.PICKUP for f in pickup_fields)

    def test_get_field_by_key(self):
        """Should return field by key."""
        registry = get_registry()

        vin_field = registry.get_field("vehicle_vin")
        assert vin_field is not None
        assert vin_field.key == "vehicle_vin"
        assert vin_field.required is True

        unknown_field = registry.get_field("unknown_field")
        assert unknown_field is None

    def test_validate_vin(self):
        """Should validate VIN format."""
        registry = get_registry()

        # Valid VIN
        error = registry.validate_field("vehicle_vin", "KM8JCCD18RU178398")
        assert error is None

        # Too short
        error = registry.validate_field("vehicle_vin", "ABC123")
        assert error is not None
        assert "must be at least 17" in error

        # Empty (required)
        error = registry.validate_field("vehicle_vin", "")
        assert error is not None
        assert "required" in error.lower()

    def test_validate_year(self):
        """Should validate year range."""
        registry = get_registry()

        # Valid year
        error = registry.validate_field("vehicle_year", 2024)
        assert error is None

        # Too old
        error = registry.validate_field("vehicle_year", 1800)
        assert error is not None
        assert "at least 1900" in error

    def test_validate_state(self):
        """Should validate state format."""
        registry = get_registry()

        # Valid state
        error = registry.validate_field("pickup_state", "TX")
        assert error is None

        # Invalid format
        error = registry.validate_field("pickup_state", "Texas")
        assert error is not None

    def test_validate_all(self):
        """Should validate all fields."""
        registry = get_registry()

        data = {
            "vehicle_vin": "ABC",  # Invalid
            "vehicle_year": 2024,
            "pickup_address": "",  # Missing required
        }

        errors = registry.validate_all(data)
        assert len(errors) > 0

        error_fields = [e["field"] for e in errors]
        assert "vehicle_vin" in error_fields
        assert "pickup_address" in error_fields

    def test_get_blocking_issues(self):
        """Should return blocking issues for posting."""
        registry = get_registry()

        # Missing required fields
        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            # Missing pickup_address, etc.
        }

        issues = registry.get_blocking_issues(data, warehouse_selected=False)
        assert len(issues) > 0

        issue_fields = [i["field"] for i in issues]
        assert "warehouse" in issue_fields  # Warehouse not selected
        assert any("pickup" in f for f in issue_fields)

    def test_same_address_allowed(self):
        """Same addresses should NOT be blocked (CD only requires 2 stops, not different addresses)."""
        registry = get_registry()

        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "vehicle_type": "SUV",
            "vehicle_condition": "OPERABLE",
            "pickup_address": "123 Main St",
            "pickup_city": "Dallas",
            "pickup_state": "TX",
            "pickup_zip": "75001",
            "delivery_address": "123 Main St",  # Same as pickup - should be allowed
            "delivery_city": "Dallas",
            "delivery_state": "TX",
            "delivery_zip": "75001",
            "available_date": datetime.now().strftime("%Y-%m-%d"),
            "trailer_type": "OPEN",
        }

        issues = registry.get_blocking_issues(data, warehouse_selected=True)
        issue_messages = [i["issue"] for i in issues]
        # Should NOT contain any "different addresses" error
        assert not any("different" in msg.lower() for msg in issue_messages)

    def test_blocking_issues_external_id_too_long(self):
        """Should block when external_id exceeds 50 characters."""
        registry = get_registry()

        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "vehicle_type": "SUV",
            "vehicle_condition": "OPERABLE",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
            "available_date": datetime.now().strftime("%Y-%m-%d"),
            "trailer_type": "OPEN",
            "external_id": "X" * 60,  # 60 chars, exceeds 50 limit
        }

        issues = registry.get_blocking_issues(data, warehouse_selected=True)
        issue_fields = [i["field"] for i in issues]
        assert "external_id" in issue_fields

    def test_blocking_issues_date_in_past(self):
        """Should block when available_date is in the past."""
        registry = get_registry()

        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "vehicle_type": "SUV",
            "vehicle_condition": "OPERABLE",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
            "available_date": "2020-01-01",  # In the past
            "trailer_type": "OPEN",
        }

        issues = registry.get_blocking_issues(data, warehouse_selected=True)
        issue_fields = [i["field"] for i in issues]
        assert "available_date" in issue_fields

    def test_blocking_issues_date_too_far_future(self):
        """Should block when available_date is more than 30 days ahead."""
        registry = get_registry()

        future_date = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "vehicle_type": "SUV",
            "vehicle_condition": "OPERABLE",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
            "available_date": future_date,  # 60 days ahead
            "trailer_type": "OPEN",
        }

        issues = registry.get_blocking_issues(data, warehouse_selected=True)
        issue_fields = [i["field"] for i in issues]
        assert "available_date" in issue_fields

    def test_blocking_issues_desired_delivery_date_in_past(self):
        """Should block when desired_delivery_date is in the past."""
        registry = get_registry()

        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "vehicle_type": "SUV",
            "vehicle_condition": "OPERABLE",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
            "available_date": datetime.now().strftime("%Y-%m-%d"),
            "desired_delivery_date": "2020-01-01",  # In the past
            "trailer_type": "OPEN",
        }

        issues = registry.get_blocking_issues(data, warehouse_selected=True)
        issue_fields = [i["field"] for i in issues]
        assert "desired_delivery_date" in issue_fields

    def test_blocking_issues_desired_delivery_date_before_available(self):
        """Should block when desired_delivery_date is before available_date."""
        registry = get_registry()

        today = datetime.now()
        available = (today + timedelta(days=7)).strftime("%Y-%m-%d")
        desired = (today + timedelta(days=3)).strftime("%Y-%m-%d")  # Before available

        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "vehicle_type": "SUV",
            "vehicle_condition": "OPERABLE",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
            "available_date": available,
            "desired_delivery_date": desired,  # Before available_date
            "trailer_type": "OPEN",
        }

        issues = registry.get_blocking_issues(data, warehouse_selected=True)
        issue_fields = [i["field"] for i in issues]
        issue_messages = [i["issue"] for i in issues]
        assert "desired_delivery_date" in issue_fields
        assert any("after available" in msg.lower() for msg in issue_messages)

    def test_blocking_issues_desired_delivery_date_too_far_future(self):
        """Should block when desired_delivery_date is more than 30 days ahead."""
        registry = get_registry()

        today = datetime.now()
        available = today.strftime("%Y-%m-%d")
        desired = (today + timedelta(days=60)).strftime("%Y-%m-%d")  # 60 days ahead

        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "vehicle_type": "SUV",
            "vehicle_condition": "OPERABLE",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
            "available_date": available,
            "desired_delivery_date": desired,  # 60 days ahead
            "trailer_type": "OPEN",
        }

        issues = registry.get_blocking_issues(data, warehouse_selected=True)
        issue_fields = [i["field"] for i in issues]
        assert "desired_delivery_date" in issue_fields

    def test_to_json_schema(self):
        """Should export as JSON schema."""
        registry = get_registry()
        schema = registry.to_json_schema()

        assert "version" in schema
        assert "sections" in schema
        assert "required_fields" in schema

        assert "vehicle" in schema["sections"]
        assert "pickup" in schema["sections"]
        assert "delivery" in schema["sections"]


class TestBuildCDPayload:
    """Tests for CD payload building."""

    def test_build_minimal_payload(self):
        """Should build payload with minimal data."""
        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "pickup_address": "5701 Whiteside Rd",
            "pickup_city": "Sandston",
            "pickup_state": "VA",
            "pickup_zip": "23150",
            "delivery_address": "123 Warehouse St",
            "delivery_city": "Dallas",
            "delivery_state": "TX",
            "delivery_zip": "75001",
        }

        payload, warnings = build_cd_payload(data)

        assert "externalId" in payload
        assert "trailerType" in payload
        assert "stops" in payload
        assert len(payload["stops"]) == 2
        assert "vehicles" in payload
        assert len(payload["vehicles"]) == 1

        # Verify partnerReferenceId is generated for retry safety
        assert "partnerReferenceId" in payload

        # Verify vehicle
        vehicle = payload["vehicles"][0]
        assert vehicle["vin"] == "KM8JCCD18RU178398"
        assert vehicle["year"] == 2024
        assert vehicle["make"] == "Hyundai"

        # Verify stops
        pickup = payload["stops"][0]
        assert pickup["stopNumber"] == 1
        assert pickup["address"]["city"] == "Sandston"

        delivery = payload["stops"][1]
        assert delivery["stopNumber"] == 2
        assert delivery["address"]["city"] == "Dallas"

    def test_build_payload_with_pricing(self):
        """Should include pricing when provided."""
        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
            "price_total": 450.00,
            "price_cod_amount": 450.00,
            "price_cod_method": "CASH",
        }

        payload, warnings = build_cd_payload(data)

        assert "price" in payload
        assert payload["price"]["total"] == 450.00
        assert "cod" in payload["price"]
        assert payload["price"]["cod"]["amount"] == 450.00

    def test_build_payload_with_notes(self):
        """Should include notes when provided."""
        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
            "notes": "Call before delivery",
            "transport_special_instructions": "Gate code: 1234",
        }

        payload, warnings = build_cd_payload(data)

        assert payload.get("notes") == "Call before delivery"
        assert payload.get("transportationReleaseNotes") == "Gate code: 1234"

    def test_vehicle_operability(self):
        """Should handle vehicle operability."""
        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "vehicle_condition": "INOPERABLE",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
        }

        payload, warnings = build_cd_payload(data)

        assert payload["hasInOpVehicle"] is True
        assert payload["vehicles"][0]["isOperable"] is False

    def test_external_id_truncation(self):
        """Should truncate external_id to 50 characters (CD API limit) and return warning."""
        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
            "external_id": "A" * 100,  # 100 chars, should be truncated
        }

        payload, warnings = build_cd_payload(data)

        assert len(payload["externalId"]) == 50
        assert payload["externalId"] == "A" * 50
        # Verify truncation warning is returned (not silent)
        assert any("truncated" in w.lower() for w in warnings)

    def test_partner_reference_id_with_run_id(self):
        """Should generate partnerReferenceId when run_id is provided (for retry-safe POST)."""
        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
        }

        payload, warnings = build_cd_payload(data, run_id=12345)

        # partnerReferenceId should be generated based on run_id
        assert "partnerReferenceId" in payload
        assert "CD-RUN-12345" == payload["partnerReferenceId"]
        # Must be <= 50 characters per CD API
        assert len(payload["partnerReferenceId"]) <= 50

    def test_partner_reference_id_fallback_to_vin(self):
        """Should generate partnerReferenceId from VIN when no run_id."""
        data = {
            "vehicle_vin": "KM8JCCD18RU178398",
            "vehicle_year": 2024,
            "vehicle_make": "Hyundai",
            "vehicle_model": "Tucson",
            "pickup_address": "123 Main St",
            "pickup_city": "Austin",
            "pickup_state": "TX",
            "pickup_zip": "78701",
            "delivery_address": "456 Oak St",
            "delivery_city": "Houston",
            "delivery_state": "TX",
            "delivery_zip": "77001",
        }

        payload, warnings = build_cd_payload(data)  # No run_id

        # partnerReferenceId should be generated from VIN
        assert "partnerReferenceId" in payload
        assert payload["partnerReferenceId"].startswith("CD-KM8JCCD18RU178398")
        # Must be <= 50 characters per CD API
        assert len(payload["partnerReferenceId"]) <= 50


class TestFieldDefinitions:
    """Tests for field definitions completeness."""

    def test_all_required_cd_fields_present(self):
        """All required CD fields should be defined."""
        required_keys = [
            "vehicle_vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "vehicle_type",
            "vehicle_condition",
            "pickup_address",
            "pickup_city",
            "pickup_state",
            "pickup_zip",
            "delivery_address",
            "delivery_city",
            "delivery_state",
            "delivery_zip",
            "available_date",
            "trailer_type",
        ]

        field_keys = [f.key for f in LISTING_FIELDS]

        for key in required_keys:
            assert key in field_keys, f"Missing required field: {key}"

    def test_fields_have_labels(self):
        """All fields should have labels."""
        for field in LISTING_FIELDS:
            assert field.label, f"Field {field.key} missing label"

    def test_fields_have_sections(self):
        """All fields should have sections."""
        for field in LISTING_FIELDS:
            assert field.section, f"Field {field.key} missing section"
            assert isinstance(field.section, FieldSection)

    def test_select_fields_have_options(self):
        """Select fields should have options."""
        for field in LISTING_FIELDS:
            if field.field_type == FieldType.SELECT:
                assert field.options, f"Select field {field.key} missing options"
                assert len(field.options) > 0

    def test_fields_sorted_by_display_order(self):
        """Fields within sections should be sorted by display_order."""
        registry = get_registry()

        for section in registry.get_sections():
            fields = registry.get_fields_by_section(section)
            orders = [f.display_order for f in fields]
            assert orders == sorted(orders), f"Section {section} not sorted by display_order"
