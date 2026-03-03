"""
Tests for Copart directory advisory model.

Document = primary source. Directory = advisory reference.
Extraction never overwrites pickup address fields from directory.
Instead, it compares and stores _directory_match_status + _directory_suggestion.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.haiku_extractor import ExtractedField, FieldSource, HaikuExtractor, normalize_haiku_result


def _make_extractor_with_response(haiku_json: dict):
    """Helper: create HaikuExtractor with mocked API returning haiku_json."""
    extractor = HaikuExtractor(api_key="test-key")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(haiku_json))]
    mock_response.usage = MagicMock(
        input_tokens=100, output_tokens=50,
        cache_read_input_tokens=0, cache_creation_input_tokens=0
    )

    def stub_extract(pdf_path, use_layout=False):
        return ("enough text for extraction" * 5, 1, 100)

    extractor.extract_text_from_pdf = stub_extract
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    extractor._client = mock_client
    return extractor


class TestDocumentIsPrimarySource:
    """Document values must NEVER be overwritten by directory."""

    def test_document_is_primary_source(self):
        """Extracted address fields are preserved even when directory has different values."""
        # Haiku extracts "123 MAIN ST" but directory has "77 Fitchburg Rd"
        extractor = _make_extractor_with_response({
            "auction_type": "COPART",
            "vehicle_vin": "1C4RJFAG2GC489125",
            "pickup_name": "COPART - AYER",
            "pickup_address": "123 MAIN ST",
            "pickup_city": "AYER",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        })

        result = extractor.extract("dummy.pdf", auction_type="COPART")
        outputs, _ = normalize_haiku_result(result)

        # Document address must NOT be replaced by directory
        assert outputs["pickup_address"] == "123 MAIN ST"
        assert outputs["pickup_city"] == "AYER"
        assert outputs["pickup_state"] == "MA"
        assert outputs["pickup_zip"] == "01432"


class TestDirectoryConfirmed:
    """When all document fields match directory, status = confirmed."""

    def test_directory_confirmed(self):
        """All fields match directory -> status='confirmed', verified=True."""
        extractor = _make_extractor_with_response({
            "auction_type": "COPART",
            "vehicle_vin": "1C4RJFAG2GC489125",
            "pickup_name": "COPART - AYER",
            "pickup_address": "77 FITCHBURG RD",
            "pickup_city": "AYER",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        })

        result = extractor.extract("dummy.pdf", auction_type="COPART")
        outputs, _ = normalize_haiku_result(result)

        assert outputs["_directory_match_status"] == "confirmed"
        assert outputs["pickup_verified"] is True
        # Suggestion should still be saved for UI display
        assert "_directory_suggestion" in outputs
        assert outputs["_directory_suggestion"]["name"] == "Copart North Boston"


class TestDirectoryMismatch:
    """When document differs from directory, status = mismatch with suggestion."""

    def test_directory_mismatch_shows_suggestion(self):
        """Different address -> status='mismatch', suggestion saved, verified=False."""
        extractor = _make_extractor_with_response({
            "auction_type": "COPART",
            "vehicle_vin": "1C4RJFAG2GC489125",
            "pickup_name": "COPART - AYER",
            "pickup_address": "999 WRONG ST",
            "pickup_city": "AYER",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        })

        result = extractor.extract("dummy.pdf", auction_type="COPART")
        outputs, _ = normalize_haiku_result(result)

        assert outputs["_directory_match_status"] == "mismatch"
        assert outputs["pickup_verified"] is False
        # Suggestion should contain directory data
        suggestion = outputs["_directory_suggestion"]
        assert suggestion["address"] == "77 Fitchburg Rd"
        assert suggestion["city"] == "Ayer"
        assert suggestion["name"] == "Copart North Boston"


class TestDirectoryNotFound:
    """When city/zip not in directory, status = not_found."""

    def test_directory_not_found(self):
        """Unknown location -> status='not_found', verified=False."""
        extractor = _make_extractor_with_response({
            "auction_type": "COPART",
            "vehicle_vin": "1C4RJFAG2GC489125",
            "pickup_name": "COPART - NOWHERE",
            "pickup_address": "1 NOWHERE ST",
            "pickup_city": "NOWHERE",
            "pickup_state": "XX",
            "pickup_zip": "00000",
        })

        result = extractor.extract("dummy.pdf", auction_type="COPART")
        outputs, _ = normalize_haiku_result(result)

        assert outputs["_directory_match_status"] == "not_found"
        assert outputs["pickup_verified"] is False


class TestPickupNameFromDirectory:
    """Pickup name should still come from directory (PDFs lack canonical names)."""

    def test_pickup_name_from_directory(self):
        """Even on mismatch, pickup_name is set from directory match."""
        extractor = _make_extractor_with_response({
            "auction_type": "COPART",
            "vehicle_vin": "1C4RJFAG2GC489125",
            "pickup_name": "COPART - AYER",
            "pickup_address": "WRONG ADDRESS",
            "pickup_city": "AYER",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        })

        result = extractor.extract("dummy.pdf", auction_type="COPART")
        outputs, _ = normalize_haiku_result(result)

        # Name resolved from directory
        assert outputs["pickup_name"] == "Copart North Boston"
        # But address is still from document (not overwritten)
        assert outputs["pickup_address"] == "WRONG ADDRESS"


class TestTwoCopartSameCity:
    """Two Copart locations in same city — ZIP fallback disambiguates when city doesn't match."""

    def test_two_copart_same_city(self):
        """City+state match takes priority; ZIP fallback resolves when city is wrong."""
        # City match: "LEXINGTON" + "KY" -> Copart Lexington (first city match wins)
        ext1 = _make_extractor_with_response({
            "auction_type": "COPART",
            "vehicle_vin": "TEST1",
            "pickup_city": "LEXINGTON",
            "pickup_state": "KY",
            "pickup_zip": "40511",
        })
        result1 = ext1.extract("dummy.pdf", auction_type="COPART")
        out1, _ = normalize_haiku_result(result1)
        assert out1["pickup_name"] == "Copart Lexington"

        # ZIP fallback: wrong city, but ZIP 40509 -> Copart Lexington East
        ext2 = _make_extractor_with_response({
            "auction_type": "COPART",
            "vehicle_vin": "TEST2",
            "pickup_city": "WRONG_CITY",
            "pickup_state": "KY",
            "pickup_zip": "40509",
        })
        result2 = ext2.extract("dummy.pdf", auction_type="COPART")
        out2, _ = normalize_haiku_result(result2)
        assert out2["pickup_name"] == "Copart Lexington East"


class TestValidationReflectsMatchStatus:
    """Validator uses pre-computed directory_match_status when provided."""

    def test_validation_reflects_match_status(self):
        """Validator with directory_match_status='mismatch' produces per-field comparisons."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()

        pickup_fields = {
            "pickup_name": "Copart North Boston",
            "pickup_address": "999 WRONG ST",
            "pickup_city": "Ayer",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        }

        directory_suggestion = {
            "name": "Copart North Boston",
            "address": "77 Fitchburg Rd",
            "city": "Ayer",
            "state": "MA",
            "zip": "01432",
        }

        result = validator.validate(
            "COPART", pickup_fields,
            directory_match_status="mismatch",
            directory_suggestion=directory_suggestion)

        assert result["directory_match"] is True
        # Address should be mismatch (999 WRONG ST vs 77 Fitchburg Rd)
        assert result["fields"]["pickup_address"]["status"] == "mismatch"
        # City should be verified (both Ayer)
        assert result["fields"]["pickup_city"]["status"] == "verified"
        # State should be verified (both MA)
        assert result["fields"]["pickup_state"]["status"] == "verified"


class TestValidatorFallbackWithoutStatus:
    """Without directory_match_status, validator falls back to _lookup_by_zip."""

    def test_validator_fallback_without_status(self):
        """No status -> falls back to ZIP-based lookup (legacy path)."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()

        # Values matching Copart North Boston
        pickup_fields = {
            "pickup_name": "Copart North Boston",
            "pickup_address": "77 Fitchburg Rd",
            "pickup_city": "Ayer",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        }

        # No directory_match_status -> should use _lookup_by_zip
        result = validator.validate("COPART", pickup_fields)

        assert result["directory_match"] is True
        assert result["fields"]["pickup_city"]["status"] == "verified"
        assert result["fields"]["pickup_state"]["status"] == "verified"
