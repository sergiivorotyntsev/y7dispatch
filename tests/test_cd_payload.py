"""
Unit tests for CD Listings API v2 Pydantic models, validators, and helpers.

Covers:
  - CDListingDraft cross-field validators (stops, vehicles, VINs)
  - Sub-model field validators (VIN format, state, ZIP)
  - CDPrice / CDCOD validation
  - Enum values and LUXURY_MAKES
  - cd_client helper functions (reference ID, idempotency key)
  - Payload serialization via to_api_dict()
"""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from api.cd_client import generate_idempotency_key, generate_partner_reference_id
from models.cd_enums import (
    DEFAULT_MARKETPLACE_ID,
    LUXURY_MAKES,
    LocationType,
    PaymentLocation,
    PaymentMethod,
    SLAType,
    TrailerType,
    VehicleType,
)
from models.cd_listing import (
    CDCOD,
    CDListingDraft,
    CDPrice,
    CDStop,
    CDVehicle,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_stop(number, **overrides):
    """Build a valid CDStop dict."""
    defaults = {
        "stopNumber": number,
        "locationType": "AUCTION" if number == 1 else "BUSINESS",
        "address": f"{number}00 Main St",
        "city": "Dallas" if number == 1 else "Houston",
        "state": "TX",
        "postalCode": "75001" if number == 1 else "77001",
        "country": "US",
    }
    defaults.update(overrides)
    return defaults


def _make_vehicle(**overrides):
    """Build a valid CDVehicle dict."""
    defaults = {
        "vin": "1HGBH41JXMN109186",
        "year": 2024,
        "make": "Honda",
        "model": "Civic",
        "vehicleType": "AUTO",
        "pickupStopNumber": 1,
        "dropoffStopNumber": 2,
    }
    defaults.update(overrides)
    return defaults


def _make_price(**overrides):
    """Build a valid CDPrice dict."""
    defaults = {
        "total": 500.0,
        "cod": {
            "amount": 500.0,
            "paymentMethod": "CASH_CERTIFIED_FUNDS",
            "paymentLocation": "DELIVERY",
        },
    }
    defaults.update(overrides)
    return defaults


def _make_draft(**overrides):
    """Build a valid CDListingDraft dict."""
    today = date.today()
    defaults = {
        "externalId": "DC-TEST-001",
        "trailerType": "OPEN",
        "availableDate": today.isoformat(),
        "expirationDate": (today + timedelta(days=14)).isoformat(),
        "price": _make_price(),
        "stops": [_make_stop(1), _make_stop(2)],
        "vehicles": [_make_vehicle()],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# CDListingDraft — happy path
# ---------------------------------------------------------------------------


class TestCDListingDraftValid:
    """Test valid CDListingDraft constructions."""

    def test_minimal_valid(self):
        draft = CDListingDraft(**_make_draft())
        assert draft.externalId == "DC-TEST-001"
        assert len(draft.stops) == 2
        assert len(draft.vehicles) == 1

    def test_to_api_dict_excludes_none(self):
        draft = CDListingDraft(**_make_draft())
        d = draft.to_api_dict()
        assert "shipperOrderId" not in d
        assert "partnerReferenceId" not in d
        assert d["externalId"] == "DC-TEST-001"

    def test_to_api_dict_has_required_keys(self):
        draft = CDListingDraft(**_make_draft())
        d = draft.to_api_dict()
        for key in ("externalId", "trailerType", "availableDate", "price", "stops", "vehicles"):
            assert key in d

    def test_multiple_vehicles(self):
        v1 = _make_vehicle(vin="1HGBH41JXMN109186")
        v2 = _make_vehicle(vin="2T1BURHE5JC123456")
        draft = CDListingDraft(**_make_draft(vehicles=[v1, v2]))
        assert len(draft.vehicles) == 2

    def test_has_inop_vehicle_auto_set(self):
        v = _make_vehicle(isInoperable=True)
        draft = CDListingDraft(**_make_draft(vehicles=[v]))
        assert draft.hasInOpVehicle is True

    def test_has_inop_vehicle_stays_false(self):
        draft = CDListingDraft(**_make_draft())
        assert draft.hasInOpVehicle is False

    def test_with_sla(self):
        sla = {"type": "EXPEDITED", "pickupByDate": date.today().isoformat()}
        draft = CDListingDraft(**_make_draft(sla=sla))
        assert draft.sla.type == SLAType.EXPEDITED

    def test_with_tags(self):
        tags = [{"name": "auctionSource", "value": "COPART"}]
        draft = CDListingDraft(**_make_draft(tags=tags))
        assert len(draft.tags) == 1
        assert draft.tags[0].name == "auctionSource"

    def test_default_marketplace(self):
        draft = CDListingDraft(**_make_draft())
        assert len(draft.marketplaces) == 1
        assert draft.marketplaces[0].marketplaceId == DEFAULT_MARKETPLACE_ID


# ---------------------------------------------------------------------------
# CDListingDraft — validation failures
# ---------------------------------------------------------------------------


class TestCDListingDraftInvalid:
    """Test CDListingDraft rejects invalid data."""

    def test_missing_external_id(self):
        d = _make_draft()
        del d["externalId"]
        with pytest.raises(ValidationError) as exc:
            CDListingDraft(**d)
        assert "externalId" in str(exc.value)

    def test_external_id_too_long(self):
        with pytest.raises(ValidationError):
            CDListingDraft(**_make_draft(externalId="X" * 51))

    def test_only_one_stop(self):
        with pytest.raises(ValidationError) as exc:
            CDListingDraft(**_make_draft(stops=[_make_stop(1)]))
        assert "stop" in str(exc.value).lower()

    def test_three_stops(self):
        with pytest.raises(ValidationError):
            CDListingDraft(
                **_make_draft(stops=[_make_stop(1), _make_stop(2), _make_stop(1, stopNumber=3)])
            )

    def test_duplicate_stop_numbers(self):
        with pytest.raises(ValidationError) as exc:
            CDListingDraft(**_make_draft(stops=[_make_stop(1), _make_stop(1)]))
        assert "stop" in str(exc.value).lower()

    def test_no_vehicles(self):
        with pytest.raises(ValidationError):
            CDListingDraft(**_make_draft(vehicles=[]))

    def test_thirteen_vehicles(self):
        vehicles = [_make_vehicle(vin=f"1HGBH41JXMN10{i:04d}") for i in range(13)]
        with pytest.raises(ValidationError):
            CDListingDraft(**_make_draft(vehicles=vehicles))

    def test_duplicate_vins(self):
        v1 = _make_vehicle(vin="1HGBH41JXMN109186")
        v2 = _make_vehicle(vin="1HGBH41JXMN109186")
        with pytest.raises(ValidationError) as exc:
            CDListingDraft(**_make_draft(vehicles=[v1, v2]))
        assert "vin" in str(exc.value).lower()

    def test_vehicle_invalid_pickup_stop(self):
        v = _make_vehicle(pickupStopNumber=3)
        with pytest.raises(ValidationError):
            CDListingDraft(**_make_draft(vehicles=[v]))

    def test_vehicle_invalid_dropoff_stop(self):
        v = _make_vehicle(dropoffStopNumber=3)
        with pytest.raises(ValidationError):
            CDListingDraft(**_make_draft(vehicles=[v]))


# ---------------------------------------------------------------------------
# Sub-model validators
# ---------------------------------------------------------------------------


class TestCDStopValidator:
    """Test CDStop field validators."""

    def test_valid_state(self):
        stop = CDStop(**_make_stop(1))
        assert stop.state == "TX"

    def test_invalid_state_lowercase(self):
        with pytest.raises(ValidationError):
            CDStop(**_make_stop(1, state="tx"))

    def test_invalid_state_three_chars(self):
        with pytest.raises(ValidationError):
            CDStop(**_make_stop(1, state="TEX"))

    def test_valid_zip5(self):
        stop = CDStop(**_make_stop(1, postalCode="75001"))
        assert stop.postalCode == "75001"

    def test_valid_zip9(self):
        stop = CDStop(**_make_stop(1, postalCode="75001-1234"))
        assert stop.postalCode == "75001-1234"

    def test_invalid_zip(self):
        with pytest.raises(ValidationError):
            CDStop(**_make_stop(1, postalCode="ABC"))


class TestCDVehicleValidator:
    """Test CDVehicle field validators."""

    def test_valid_vin(self):
        v = CDVehicle(**_make_vehicle())
        assert v.vin == "1HGBH41JXMN109186"

    def test_vin_uppercased(self):
        v = CDVehicle(**_make_vehicle(vin="1hgbh41jxmn109186"))
        assert v.vin == "1HGBH41JXMN109186"

    def test_vin_too_short(self):
        with pytest.raises(ValidationError):
            CDVehicle(**_make_vehicle(vin="ABC123"))

    def test_vin_contains_forbidden_chars(self):
        # I, O, Q are forbidden in VIN
        with pytest.raises(ValidationError):
            CDVehicle(**_make_vehicle(vin="1HGBH41IXMN109186"))  # I instead of J

    def test_year_range(self):
        v = CDVehicle(**_make_vehicle(year=2024))
        assert v.year == 2024

    def test_year_too_old(self):
        with pytest.raises(ValidationError):
            CDVehicle(**_make_vehicle(year=1899))

    def test_year_too_new(self):
        with pytest.raises(ValidationError):
            CDVehicle(**_make_vehicle(year=2036))


class TestCDPriceValidator:
    """Test CDPrice validation."""

    def test_valid_price(self):
        price = CDPrice(**_make_price())
        assert price.total == 500.0

    def test_price_zero_fails(self):
        with pytest.raises(ValidationError):
            CDPrice(total=0, cod=None)

    def test_price_negative_fails(self):
        with pytest.raises(ValidationError):
            CDPrice(total=-100, cod=None)

    def test_price_too_high(self):
        with pytest.raises(ValidationError):
            CDPrice(total=100001, cod=None)

    def test_cod_amount_zero_ok(self):
        cod = CDCOD(amount=0)
        assert cod.amount == 0

    def test_cod_negative_fails(self):
        with pytest.raises(ValidationError):
            CDCOD(amount=-1)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TestEnums:
    """Test CD enum values."""

    def test_trailer_types(self):
        assert TrailerType.OPEN.value == "OPEN"
        assert TrailerType.ENCLOSED.value == "ENCLOSED"
        assert TrailerType.DRIVEAWAY.value == "DRIVEAWAY"

    def test_vehicle_types(self):
        assert VehicleType.AUTO.value == "AUTO"
        assert VehicleType.SUV.value == "SUV"
        assert VehicleType.MOTORCYCLE.value == "MOTORCYCLE"

    def test_payment_methods(self):
        assert PaymentMethod.CASH_CERTIFIED_FUNDS.value == "CASH_CERTIFIED_FUNDS"

    def test_payment_locations(self):
        assert PaymentLocation.DELIVERY.value == "DELIVERY"
        assert PaymentLocation.PICKUP.value == "PICKUP"

    def test_location_types(self):
        assert LocationType.AUCTION.value == "Auction"
        assert LocationType.DEALERSHIP.value == "Dealership"
        assert LocationType.RESIDENCE.value == "Residence"

    def test_sla_types(self):
        assert SLAType.STANDARD.value == "STANDARD"
        assert SLAType.EXPEDITED.value == "EXPEDITED"

    def test_luxury_makes_frozenset(self):
        assert isinstance(LUXURY_MAKES, frozenset)
        assert "BMW" in LUXURY_MAKES
        assert "MERCEDES-BENZ" in LUXURY_MAKES
        assert "PORSCHE" in LUXURY_MAKES
        assert "HONDA" not in LUXURY_MAKES

    def test_default_marketplace_id(self):
        assert DEFAULT_MARKETPLACE_ID == 10000


# ---------------------------------------------------------------------------
# cd_client helper functions
# ---------------------------------------------------------------------------


class TestCDClientHelpers:
    """Test helper functions from cd_client module."""

    def test_partner_reference_id_format(self):
        ref = generate_partner_reference_id(42, 100)
        assert ref.startswith("CD-42-100-")
        assert len(ref) <= 50

    def test_partner_reference_id_deterministic(self):
        ref1 = generate_partner_reference_id(1, 2)
        ref2 = generate_partner_reference_id(1, 2)
        assert ref1 == ref2

    def test_partner_reference_id_different_inputs(self):
        ref1 = generate_partner_reference_id(1, 2)
        ref2 = generate_partner_reference_id(1, 3)
        assert ref1 != ref2

    def test_partner_reference_id_max_length(self):
        # Large IDs should still be truncated to 50 chars
        ref = generate_partner_reference_id(999999999, 999999999)
        assert len(ref) <= 50

    def test_idempotency_key_format(self):
        key = generate_idempotency_key("CD-1-2-abc", "create")
        assert len(key) == 32  # sha256 truncated

    def test_idempotency_key_deterministic_within_hour(self):
        key1 = generate_idempotency_key("ref-1", "create")
        key2 = generate_idempotency_key("ref-1", "create")
        assert key1 == key2

    def test_idempotency_key_different_operations(self):
        key1 = generate_idempotency_key("ref-1", "create")
        key2 = generate_idempotency_key("ref-1", "update")
        assert key1 != key2


# ---------------------------------------------------------------------------
# CDListingDraft — serialization round-trip
# ---------------------------------------------------------------------------


class TestSerialization:
    """Test payload serialization produces CD-API-ready dicts."""

    def test_dates_serialized_as_iso(self):
        draft = CDListingDraft(**_make_draft())
        d = draft.to_api_dict()
        assert isinstance(d["availableDate"], str)
        # Should be parseable back to date
        date.fromisoformat(d["availableDate"])

    def test_stops_are_list_of_dicts(self):
        draft = CDListingDraft(**_make_draft())
        d = draft.to_api_dict()
        assert isinstance(d["stops"], list)
        assert isinstance(d["stops"][0], dict)
        assert d["stops"][0]["stopNumber"] == 1
        assert d["stops"][1]["stopNumber"] == 2

    def test_vehicles_are_list_of_dicts(self):
        draft = CDListingDraft(**_make_draft())
        d = draft.to_api_dict()
        assert isinstance(d["vehicles"], list)
        assert d["vehicles"][0]["vin"] == "1HGBH41JXMN109186"

    def test_nested_price_cod(self):
        draft = CDListingDraft(**_make_draft())
        d = draft.to_api_dict()
        assert d["price"]["total"] == 500.0
        assert d["price"]["cod"]["amount"] == 500.0
        assert d["price"]["cod"]["paymentMethod"] == "CASH_CERTIFIED_FUNDS"

    def test_marketplaces_included(self):
        draft = CDListingDraft(**_make_draft())
        d = draft.to_api_dict()
        assert len(d["marketplaces"]) == 1
        assert d["marketplaces"][0]["marketplaceId"] == DEFAULT_MARKETPLACE_ID

    def test_tags_serialized(self):
        tags = [{"name": "source", "value": "COPART"}, {"name": "lot", "value": "12345"}]
        draft = CDListingDraft(**_make_draft(tags=tags))
        d = draft.to_api_dict()
        assert len(d["tags"]) == 2
        assert d["tags"][0]["name"] == "source"
