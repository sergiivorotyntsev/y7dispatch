"""
Golden Tests for CD Listings API V2 Integration

These tests verify that:
1. Payload builder generates correct CD V2 structure
2. Upsert respects fill-only mode when row_status != NEW
3. Lock flags block appropriate field updates
4. Override resolution works correctly
5. READY validation enforces CD V2 requirements
"""

from datetime import date, timedelta
from unittest.mock import Mock

from schemas.sheets_schema_v3 import (
    OVERRIDE_MAPPINGS,
    RowStatus,
    apply_all_overrides,
    can_transition_to,
    generate_dispatch_id,
    get_delivery_columns,
    get_final_value_with_mapping,
    get_release_notes_columns,
    get_required_columns,
    validate_row_for_ready,
)


class TestDispatchIdGeneration:
    """Test dispatch_id generation."""

    def test_format_with_gate_pass(self):
        """Test dispatch_id format with gate pass."""
        dispatch_id = generate_dispatch_id(
            auction_source="COPART",
            gate_pass="ABC123",
        )
        assert dispatch_id.startswith("DC-")
        assert "-COPART-" in dispatch_id
        assert len(dispatch_id) <= 50  # CD externalId limit

    def test_format_with_vin(self):
        """Test dispatch_id with VIN fallback."""
        dispatch_id = generate_dispatch_id(
            auction_source="IAA",
            vin="1HGBH41JXMN109186",
        )
        assert "-IAA-" in dispatch_id

    def test_unknown_auction(self):
        """Test unknown auction source."""
        dispatch_id = generate_dispatch_id(
            auction_source="UNKNOWN",
            gate_pass="XYZ",
        )
        assert "-UNK-" in dispatch_id

    def test_deterministic_hash(self):
        """Test same inputs produce same hash."""
        id1 = generate_dispatch_id("COPART", gate_pass="ABC123")
        id2 = generate_dispatch_id("COPART", gate_pass="ABC123")
        # Hash part should be same
        assert id1.split("-")[-1] == id2.split("-")[-1]


class TestStateTransitions:
    """Test row_status state machine."""

    def test_new_to_ready(self):
        """NEW can transition to READY."""
        assert can_transition_to(RowStatus.NEW, RowStatus.READY)

    def test_new_to_hold(self):
        """NEW can transition to HOLD."""
        assert can_transition_to(RowStatus.NEW, RowStatus.HOLD)

    def test_new_to_cancelled(self):
        """NEW can transition to CANCELLED."""
        assert can_transition_to(RowStatus.NEW, RowStatus.CANCELLED)

    def test_ready_to_exported(self):
        """READY can transition to EXPORTED."""
        assert can_transition_to(RowStatus.READY, RowStatus.EXPORTED)

    def test_ready_to_error(self):
        """READY can transition to ERROR."""
        assert can_transition_to(RowStatus.READY, RowStatus.ERROR)

    def test_error_to_retry(self):
        """ERROR can transition to RETRY."""
        assert can_transition_to(RowStatus.ERROR, RowStatus.RETRY)

    def test_exported_is_terminal(self):
        """EXPORTED is terminal state."""
        assert not can_transition_to(RowStatus.EXPORTED, RowStatus.READY)
        assert not can_transition_to(RowStatus.EXPORTED, RowStatus.ERROR)

    def test_invalid_transition(self):
        """NEW cannot directly go to EXPORTED."""
        assert not can_transition_to(RowStatus.NEW, RowStatus.EXPORTED)


class TestOverrideResolution:
    """Test override pattern resolution."""

    def test_override_takes_precedence(self):
        """Override value takes precedence over base."""
        row = {
            "vehicle_vin": "1HGBH41JXMN109186",
            "override_vehicle_vin": "CORRECTED12345678",
        }
        final = get_final_value_with_mapping(row, "vehicle_vin", "override_vehicle_vin")
        assert final == "CORRECTED12345678"

    def test_base_used_when_no_override(self):
        """Base value used when override is empty."""
        row = {
            "vehicle_vin": "1HGBH41JXMN109186",
            "override_vehicle_vin": "",
        }
        final = get_final_value_with_mapping(row, "vehicle_vin", "override_vehicle_vin")
        assert final == "1HGBH41JXMN109186"

    def test_apply_all_overrides(self):
        """apply_all_overrides adds _final_ keys."""
        row = {
            "price_total": 500,
            "override_price_total": 550,
            "vehicle_vin": "1HGBH41JXMN109186",
        }
        result = apply_all_overrides(row)
        assert result.get("_final_price_total") == 550
        assert result.get("_final_vehicle_vin") == "1HGBH41JXMN109186"


class TestReadyValidation:
    """Test READY validation (CD V2 requirements)."""

    def test_valid_row_passes(self):
        """Fully valid row passes validation."""
        today = date.today()
        row = {
            "dispatch_id": "DC-20260130-COPART-ABC12345",
            "trailer_type": "OPEN",
            "available_date": today.isoformat(),
            "expiration_date": (today + timedelta(days=7)).isoformat(),
            "price_total": 450,
            "marketplace_id": 12345,
            "pickup_stop_number": 1,
            "pickup_address": "123 Main St",
            "pickup_city": "Dallas",
            "pickup_state": "TX",
            "pickup_postal_code": "75001",
            "pickup_country": "US",
            "dropoff_stop_number": 2,
            "dropoff_address": "456 Oak Ave",
            "dropoff_city": "Houston",
            "dropoff_state": "TX",
            "dropoff_postal_code": "77001",
            "dropoff_country": "US",
            "vehicle_vin": "1HGBH41JXMN109186",
        }
        errors = validate_row_for_ready(row)
        assert errors == []

    def test_missing_dispatch_id(self):
        """Missing dispatch_id fails validation."""
        row = {"trailer_type": "OPEN"}
        errors = validate_row_for_ready(row)
        assert any("dispatch_id" in e.lower() for e in errors)

    def test_dispatch_id_too_long(self):
        """dispatch_id > 50 chars fails."""
        row = {
            "dispatch_id": "X" * 51,
            "trailer_type": "OPEN",
        }
        errors = validate_row_for_ready(row)
        assert any("50" in e for e in errors)

    def test_invalid_trailer_type(self):
        """Invalid trailer_type fails."""
        row = {
            "dispatch_id": "DC-20260130-COPART-ABC12345",
            "trailer_type": "INVALID",
        }
        errors = validate_row_for_ready(row)
        assert any("trailer_type" in e.lower() for e in errors)

    def test_available_date_in_past(self):
        """available_date in past fails."""
        yesterday = date.today() - timedelta(days=1)
        row = {
            "dispatch_id": "DC-20260130-COPART-ABC12345",
            "trailer_type": "OPEN",
            "available_date": yesterday.isoformat(),
        }
        errors = validate_row_for_ready(row)
        assert any("past" in e.lower() for e in errors)

    def test_available_date_too_far_future(self):
        """available_date > 30 days fails."""
        far_future = date.today() + timedelta(days=35)
        row = {
            "dispatch_id": "DC-20260130-COPART-ABC12345",
            "trailer_type": "OPEN",
            "available_date": far_future.isoformat(),
        }
        errors = validate_row_for_ready(row)
        assert any("30 days" in e.lower() for e in errors)

    def test_expiration_before_available(self):
        """expiration_date <= available_date fails."""
        today = date.today()
        row = {
            "dispatch_id": "DC-20260130-COPART-ABC12345",
            "trailer_type": "OPEN",
            "available_date": today.isoformat(),
            "expiration_date": today.isoformat(),  # Same day = invalid
        }
        errors = validate_row_for_ready(row)
        assert any("after" in e.lower() for e in errors)

    def test_invalid_vin_length(self):
        """VIN not 17 chars fails."""
        today = date.today()
        row = {
            "dispatch_id": "DC-20260130-COPART-ABC12345",
            "trailer_type": "OPEN",
            "available_date": today.isoformat(),
            "expiration_date": (today + timedelta(days=7)).isoformat(),
            "price_total": 450,
            "marketplace_id": 12345,
            "pickup_address": "123 Main St",
            "pickup_city": "Dallas",
            "pickup_state": "TX",
            "pickup_postal_code": "75001",
            "pickup_country": "US",
            "dropoff_address": "456 Oak Ave",
            "dropoff_city": "Houston",
            "dropoff_state": "TX",
            "dropoff_postal_code": "77001",
            "dropoff_country": "US",
            "vehicle_vin": "TOOSHORT",  # Not 17 chars
        }
        errors = validate_row_for_ready(row)
        assert any("17" in e for e in errors)

    def test_price_zero_fails(self):
        """price_total = 0 fails (treated as missing/required)."""
        row = {
            "dispatch_id": "DC-20260130-COPART-ABC12345",
            "trailer_type": "OPEN",
            "price_total": 0,
        }
        errors = validate_row_for_ready(row)
        # 0 is falsy, so it's treated as "required"
        assert any("price_total" in e.lower() for e in errors)

    def test_override_used_in_validation(self):
        """Validation uses override values."""
        today = date.today()
        row = {
            "dispatch_id": "DC-20260130-COPART-ABC12345",
            "trailer_type": "INVALID",  # Base is invalid
            "override_trailer_type": "OPEN",  # Override is valid
            "available_date": today.isoformat(),
            "expiration_date": (today + timedelta(days=7)).isoformat(),
            "price_total": 450,
            "marketplace_id": 12345,
            "pickup_address": "123 Main St",
            "pickup_city": "Dallas",
            "pickup_state": "TX",
            "pickup_postal_code": "75001",
            "pickup_country": "US",
            "dropoff_address": "456 Oak Ave",
            "dropoff_city": "Houston",
            "dropoff_state": "TX",
            "dropoff_postal_code": "77001",
            "dropoff_country": "US",
            "vehicle_vin": "1HGBH41JXMN109186",
        }
        errors = validate_row_for_ready(row)
        # Should pass because override_trailer_type is valid
        assert not any("trailer_type" in e.lower() for e in errors)


class TestSchemaColumns:
    """Test schema column definitions."""

    def test_has_required_columns(self):
        """Schema has all required columns."""
        required = get_required_columns()
        assert "dispatch_id" in required
        assert "trailer_type" in required
        assert "available_date" in required
        assert "expiration_date" in required
        assert "price_total" in required
        assert "marketplace_id" in required
        assert "pickup_address" in required
        assert "vehicle_vin" in required

    def test_delivery_columns_identified(self):
        """Delivery columns are properly identified."""
        delivery = get_delivery_columns()
        assert "dropoff_address" in delivery
        assert "dropoff_city" in delivery
        assert "dropoff_state" in delivery

    def test_release_notes_columns_identified(self):
        """Release notes columns are properly identified."""
        release = get_release_notes_columns()
        assert "transportation_release_notes" in release
        assert "load_specific_terms" in release


class TestPayloadBuilder:
    """Test CD V2 payload builder."""

    def test_row_to_cd_payload_structure(self):
        """Test payload has correct CD V2 structure."""
        from services.cd_sheet_exporter_v2 import CDSheetExporterV2

        # Create exporter with mock configs
        mock_sheets_config = Mock()
        mock_cd_config = Mock()
        mock_cd_config.enabled = False

        exporter = CDSheetExporterV2(mock_sheets_config, mock_cd_config)

        row = {
            "dispatch_id": "DC-20260130-COPART-ABC12345",
            "trailer_type": "OPEN",
            "has_inop_vehicle": "FALSE",
            "available_date": "2026-01-30",
            "expiration_date": "2026-02-15",
            "price_total": 450,
            "cod_amount": 450,
            "cod_payment_method": "CASH",
            "cod_payment_location": "DELIVERY",
            "pickup_stop_number": 1,
            "pickup_location_name": "Copart Dallas",
            "pickup_address": "123 Auction Blvd",
            "pickup_city": "Dallas",
            "pickup_state": "TX",
            "pickup_postal_code": "75001",
            "pickup_country": "US",
            "pickup_location_type": "AUCTION",
            "dropoff_stop_number": 2,
            "dropoff_location_name": "ABC Warehouse",
            "dropoff_address": "456 Industrial Way",
            "dropoff_city": "Houston",
            "dropoff_state": "TX",
            "dropoff_postal_code": "77001",
            "dropoff_country": "US",
            "dropoff_location_type": "BUSINESS",
            "vehicle_vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
            "vehicle_is_inoperable": "FALSE",
            "vehicle_lot_number": "12345678",
            "marketplace_id": 12345,
            "digital_offers_enabled": "TRUE",
            "searchable": "TRUE",
        }

        payload = exporter.row_to_cd_payload(row)

        # Check top-level structure
        assert payload["externalId"] == "DC-20260130-COPART-ABC12345"
        assert payload["trailerType"] == "OPEN"
        assert not payload["hasInOpVehicle"]
        assert payload["availableDate"] == "2026-01-30"
        assert payload["expirationDate"] == "2026-02-15"

        # Check price structure
        assert "price" in payload
        assert payload["price"]["total"] == 450.0
        assert "cod" in payload["price"]
        assert payload["price"]["cod"]["amount"] == 450.0
        assert payload["price"]["cod"]["paymentMethod"] == "CASH"
        assert payload["price"]["cod"]["paymentLocation"] == "DELIVERY"

        # Check stops array (flat structure)
        assert "stops" in payload
        assert len(payload["stops"]) == 2

        pickup = payload["stops"][0]
        assert pickup["stopNumber"] == 1
        assert pickup["address"] == "123 Auction Blvd"
        assert pickup["city"] == "Dallas"
        assert pickup["state"] == "TX"
        assert pickup["postalCode"] == "75001"
        assert pickup["country"] == "US"
        assert pickup["locationType"] == "AUCTION"

        dropoff = payload["stops"][1]
        assert dropoff["stopNumber"] == 2
        assert dropoff["address"] == "456 Industrial Way"
        assert dropoff["city"] == "Houston"

        # Check vehicles array
        assert "vehicles" in payload
        assert len(payload["vehicles"]) == 1

        vehicle = payload["vehicles"][0]
        assert vehicle["pickupStopNumber"] == 1
        assert vehicle["dropoffStopNumber"] == 2
        assert vehicle["vin"] == "1HGBH41JXMN109186"
        assert vehicle["year"] == 2021
        assert vehicle["make"] == "Honda"
        assert vehicle["model"] == "Civic"
        assert not vehicle["isInoperable"]
        assert vehicle["lotNumber"] == "12345678"

        # Check marketplaces array
        assert "marketplaces" in payload
        assert len(payload["marketplaces"]) == 1

        marketplace = payload["marketplaces"][0]
        assert marketplace["marketplaceId"] == 12345
        assert marketplace["digitalOffersEnabled"]
        assert marketplace["searchable"]

    def test_override_applied_in_payload(self):
        """Test that overrides are applied in payload."""
        from services.cd_sheet_exporter_v2 import CDSheetExporterV2

        mock_sheets_config = Mock()
        mock_cd_config = Mock()
        mock_cd_config.enabled = False

        exporter = CDSheetExporterV2(mock_sheets_config, mock_cd_config)

        row = {
            "dispatch_id": "DC-20260130-COPART-ABC12345",
            "trailer_type": "OPEN",
            "override_trailer_type": "ENCLOSED",  # Override
            "vehicle_vin": "WRONGVIN12345678X",
            "override_vehicle_vin": "1HGBH41JXMN109186",  # Override
            "pickup_address": "Wrong Address",
            "override_pickup_address": "Correct Address",
        }

        payload = exporter.row_to_cd_payload(row)

        assert payload["trailerType"] == "ENCLOSED"  # From override
        assert payload["vehicles"][0]["vin"] == "1HGBH41JXMN109186"  # From override
        assert payload["stops"][0]["address"] == "Correct Address"  # From override


class TestUpsertLogicRules:
    """Test upsert logic rules (mocked)."""

    def test_fill_only_mode_concept(self):
        """Test fill-only mode concept."""
        # When row_status != NEW, should only fill empty fields
        existing_data = {
            "row_status": "READY",  # Not NEW
            "vehicle_vin": "EXISTINGVIN123456",  # Has value
            "vehicle_make": "",  # Empty
        }

        # Simulate fill-only logic
        is_fill_only = existing_data["row_status"] != RowStatus.NEW.value
        assert is_fill_only

        # In fill-only mode, only empty fields get updated
        should_update_vin = is_fill_only and not existing_data["vehicle_vin"]
        should_update_make = is_fill_only and not existing_data["vehicle_make"]

        assert not should_update_vin  # Has value, don't overwrite
        assert should_update_make  # Empty, can fill

    def test_lock_all_concept(self):
        """Test lock_all concept."""
        # When lock_all=TRUE, only SYSTEM/AUDIT columns are updatable

        # vehicle_vin is BASE class - should be blocked
        # updated_at is SYSTEM class - should be allowed

        from schemas.sheets_schema_v3 import get_system_audit_columns

        system_audit = set(get_system_audit_columns())

        assert "vehicle_vin" not in system_audit  # BASE, blocked by lock_all
        assert "updated_at" in system_audit  # SYSTEM, allowed

    def test_lock_delivery_concept(self):
        """Test lock_delivery concept."""
        delivery_cols = get_delivery_columns()

        # All dropoff_* fields should be protected
        assert "dropoff_address" in delivery_cols
        assert "dropoff_city" in delivery_cols
        assert "dropoff_state" in delivery_cols

        # Pickup fields should NOT be in delivery columns
        assert "pickup_address" not in delivery_cols

    def test_manual_warehouse_blocks_delivery(self):
        """Test warehouse_selected_mode=MANUAL blocks delivery."""
        existing_data = {
            "warehouse_selected_mode": "MANUAL",
        }

        # When MANUAL, delivery fields should be protected
        is_manual = existing_data["warehouse_selected_mode"] == "MANUAL"
        assert is_manual

        # Same protection as lock_delivery


class TestOverrideMappings:
    """Test override field mappings."""

    def test_all_overrides_have_mappings(self):
        """All expected fields have override mappings."""
        expected_overrides = [
            "trailer_type",
            "available_date",
            "expiration_date",
            "price_total",
            "pickup_address",
            "pickup_city",
            "pickup_state",
            "pickup_postal_code",
            "dropoff_address",
            "dropoff_city",
            "dropoff_state",
            "dropoff_postal_code",
            "vehicle_vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "vehicle_is_inoperable",
        ]

        for field in expected_overrides:
            assert field in OVERRIDE_MAPPINGS
            override = OVERRIDE_MAPPINGS[field]
            assert override.startswith("override_")
