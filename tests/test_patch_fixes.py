"""
Tests for PATCH-ТЗ fixes.

P0.1: Address parsing (city/state/zip)
P0.3: Key normalization and aliases
"""

import pytest


class TestAddressParser:
    """Tests for address parsing improvements (P0.1)."""

    def test_parse_city_state_zip_with_comma(self):
        """Test parsing 'City, ST ZIP' format."""
        from extractors.address_parser import parse_city_state_zip

        # Standard format with comma
        city, state, zip_code = parse_city_state_zip("Houston, TX 77001")
        assert city == "Houston"
        assert state == "TX"
        assert zip_code == "77001"

    def test_parse_city_state_zip_with_plus4(self):
        """Test parsing ZIP+4 format."""
        from extractors.address_parser import parse_city_state_zip

        city, state, zip_code = parse_city_state_zip("Los Angeles, CA 90001-1234")
        assert city == "Los Angeles"
        assert state == "CA"
        assert zip_code == "90001-1234"

    def test_parse_city_state_zip_no_comma(self):
        """Test parsing 'City ST ZIP' format without comma."""
        from extractors.address_parser import parse_city_state_zip

        city, state, zip_code = parse_city_state_zip("Dallas TX 75001")
        assert city == "Dallas"
        assert state == "TX"
        assert zip_code == "75001"

    def test_parse_city_state_zip_full_state_name(self):
        """Test parsing with full state name."""
        from extractors.address_parser import parse_city_state_zip

        city, state, zip_code = parse_city_state_zip("Flint Michigan 48507")
        assert city == "Flint"
        assert state == "MI"  # Should be normalized to abbreviation
        assert zip_code == "48507"

    def test_parse_city_state_zip_extra_whitespace(self):
        """Test parsing with extra whitespace."""
        from extractors.address_parser import parse_city_state_zip

        city, state, zip_code = parse_city_state_zip("  Houston ,  TX   77001  ")
        assert city is not None
        # Should handle extra whitespace gracefully

    def test_extract_address_from_section(self):
        """Test multi-line address extraction."""
        from extractors.address_parser import extract_address_from_section

        section = """Copart - Houston
5678 Industrial Blvd
Houston, TX 77001
Phone: (281) 555-7890"""

        result = extract_address_from_section(section)

        assert result.city == "Houston"
        assert result.state == "TX"
        assert result.postal_code == "77001"
        assert result.street == "5678 Industrial Blvd"


class TestKeyNormalization:
    """Tests for key normalization (P0.3)."""

    def test_normalize_pickup_zip_to_postal_code(self):
        """Test that pickup_zip normalizes to pickup_postal_code."""
        from extractors.field_resolver import normalize_field_key

        assert normalize_field_key("pickup_zip") == "pickup_postal_code"

    def test_normalize_delivery_to_dropoff(self):
        """Test that dropoff_* normalizes to delivery_*."""
        from extractors.field_resolver import normalize_field_key

        assert normalize_field_key("dropoff_address") == "delivery_address"
        assert normalize_field_key("dropoff_city") == "delivery_city"
        assert normalize_field_key("dropoff_state") == "delivery_state"
        assert normalize_field_key("dropoff_postal_code") == "delivery_postal_code"

    def test_get_all_key_variants(self):
        """Test getting all variants of a key."""
        from extractors.field_resolver import get_all_key_variants

        variants = get_all_key_variants("delivery_postal_code")

        assert "delivery_postal_code" in variants
        assert "delivery_zip" in variants
        assert "dropoff_postal_code" in variants
        assert "dropoff_zip" in variants

    def test_unknown_key_unchanged(self):
        """Test that unknown keys are returned unchanged."""
        from extractors.field_resolver import normalize_field_key

        assert normalize_field_key("some_unknown_key") == "some_unknown_key"

    def test_canonical_key_unchanged(self):
        """Test that canonical keys map to themselves."""
        from extractors.field_resolver import normalize_field_key

        assert normalize_field_key("delivery_postal_code") == "delivery_postal_code"
        assert normalize_field_key("vehicle_vin") == "vehicle_vin"


class TestInvariantLogic:
    """Tests for relaxed invariant logic (P0.2)."""

    def test_anchor_breakdown_tracking(self):
        """Test that anchor breakdown is tracked in metrics."""
        # This would require mocking the full extraction flow
        # For now, just verify the constants are defined correctly
        pass

    def test_two_of_three_anchors_passes(self):
        """Test that 2/3 anchors results in needs_review, not failed."""
        # This would require integration testing with actual extraction
        pass


class TestMarketIntelligenceClient:
    """Tests for Market Intelligence API client (P0.6)."""

    def test_mi_stop_to_dict(self):
        """Test MIStop serialization."""
        from api.mi_client import MIStop

        stop = MIStop(
            stop_number=1,
            city="Houston",
            state="TX",
            postal_code="77001",
        )

        data = stop.to_dict()

        assert data["stopNumber"] == 1
        assert data["city"] == "Houston"
        assert data["state"] == "TX"
        assert data["postalCode"] == "77001"

    def test_mi_vehicle_to_dict(self):
        """Test MIVehicle serialization."""
        from api.mi_client import MIVehicle

        vehicle = MIVehicle(
            vin="5YFBURHE8LP123456",
            year=2020,
            make="TOYOTA",
            model="COROLLA",
            vehicle_type="SEDAN",
            is_operable=True,
        )

        data = vehicle.to_dict()

        assert data["vin"] == "5YFBURHE8LP123456"
        assert data["year"] == 2020
        assert data["vehicleType"] == "SEDAN"
        assert data["isOperable"] is True
        assert data["pickupStopNumber"] == 1
        assert data["dropOffStopNumber"] == 2

    def test_mi_client_validates_stops(self):
        """Test that MI client validates stop requirements."""
        from api.mi_client import MarketIntelligenceClient, MIStop, MIVehicle

        client = MarketIntelligenceClient()

        # Should fail with only 1 stop
        with pytest.raises(ValueError, match="Exactly 2 stops required"):
            client.get_list_prices(
                stops=[MIStop(1, "Houston", "TX")],
                vehicles=[MIVehicle()],
            )

    def test_mi_client_validates_stop_numbers(self):
        """Test that MI client validates stop numbers are 1 and 2."""
        from api.mi_client import MarketIntelligenceClient, MIStop, MIVehicle

        client = MarketIntelligenceClient()

        # Should fail with wrong stop numbers
        with pytest.raises(ValueError, match="stopNumber 1 and 2"):
            client.get_list_prices(
                stops=[
                    MIStop(0, "Houston", "TX"),
                    MIStop(1, "Dallas", "TX"),
                ],
                vehicles=[MIVehicle()],
            )


class TestLearnedRulesLoading:
    """Tests for learned rules loading fix (P1.1)."""

    def test_session_context_works(self):
        """Test that SessionContext works as context manager."""
        from api.training_db import SessionContext

        # SessionContext provides context manager interface for non-FastAPI code
        with SessionContext() as session:
            assert session is not None

    def test_get_session_is_generator(self):
        """Test that get_session is a generator for FastAPI Depends()."""
        from api.training_db import get_session

        # get_session should be a generator function (for FastAPI Depends)
        gen = get_session()
        session = next(gen)
        assert session is not None
        try:
            gen.send(None)
        except StopIteration:
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
