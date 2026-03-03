"""
Tests for pickup address extraction fixes:
- layout=True for Copart PDFs (preserves column structure)
- Standard extract_text for IAA PDFs
- _haiku_original_pickup saved before post-processing
- Validation: corrected_by_directory vs verified status
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ─── Test: layout=True for Copart ────────────────────────────────────────────


class TestLayoutTrueCopart:
    """Verify Copart PDFs use layout-preserving text extraction."""

    def test_copart_uses_layout_true(self):
        """extract_text_from_pdf is called with use_layout=True when auction_type=COPART."""
        from services.haiku_extractor import HaikuExtractor

        extractor = HaikuExtractor(api_key="test-key")

        # Mock pdfplumber and the API call
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "COPART test text with enough content to pass minimum length check for extraction processing"
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        with patch("pdfplumber.open", return_value=mock_pdf):
            text, page_count, orig_len = extractor.extract_text_from_pdf(
                "dummy.pdf", use_layout=True
            )

        # Verify layout=True was passed
        mock_page.extract_text.assert_called_once_with(layout=True)
        assert "COPART test text" in text

    def test_extract_passes_layout_for_copart(self):
        """extract() with auction_type='COPART' uses layout=True internally."""
        from services.haiku_extractor import HaikuExtractor

        extractor = HaikuExtractor(api_key="test-key")

        # Track the use_layout parameter
        original_method = extractor.extract_text_from_pdf
        calls = []

        def tracking_extract(pdf_path, use_layout=False):
            calls.append(use_layout)
            return ("enough text for extraction" * 5, 1, 100)

        extractor.extract_text_from_pdf = tracking_extract

        # Mock the API call to avoid actual Anthropic calls
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"auction_type": "COPART", "vehicle_vin": "TEST"}')]
        mock_response.usage = MagicMock(
            input_tokens=100, output_tokens=50,
            cache_read_input_tokens=0, cache_creation_input_tokens=0
        )

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        extractor._client = mock_client
        extractor.extract("dummy.pdf", auction_type="COPART")

        assert len(calls) == 1
        assert calls[0] is True, "COPART should use layout=True"


class TestLayoutStandardIAA:
    """Verify IAA PDFs use standard text extraction (no layout)."""

    def test_iaa_uses_standard_extraction(self):
        """extract() with auction_type='IAA' does NOT use layout=True."""
        from services.haiku_extractor import HaikuExtractor

        extractor = HaikuExtractor(api_key="test-key")

        calls = []

        def tracking_extract(pdf_path, use_layout=False):
            calls.append(use_layout)
            return ("enough text for extraction" * 5, 1, 100)

        extractor.extract_text_from_pdf = tracking_extract

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"auction_type": "IAA", "vehicle_vin": "TEST"}')]
        mock_response.usage = MagicMock(
            input_tokens=100, output_tokens=50,
            cache_read_input_tokens=0, cache_creation_input_tokens=0
        )

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        extractor._client = mock_client
        extractor.extract("dummy.pdf", auction_type="IAA")

        assert len(calls) == 1
        assert calls[0] is False, "IAA should NOT use layout=True"

    def test_no_auction_type_uses_standard(self):
        """extract() with no auction_type uses standard extraction."""
        from services.haiku_extractor import HaikuExtractor

        extractor = HaikuExtractor(api_key="test-key")

        calls = []

        def tracking_extract(pdf_path, use_layout=False):
            calls.append(use_layout)
            return ("enough text for extraction" * 5, 1, 100)

        extractor.extract_text_from_pdf = tracking_extract

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"auction_type": "UNKNOWN", "vehicle_vin": "TEST"}')]
        mock_response.usage = MagicMock(
            input_tokens=100, output_tokens=50,
            cache_read_input_tokens=0, cache_creation_input_tokens=0
        )

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        extractor._client = mock_client
        extractor.extract("dummy.pdf")

        assert len(calls) == 1
        assert calls[0] is False, "No auction_type should use standard extraction"


# ─── Test: _haiku_original_pickup saved ──────────────────────────────────────


class TestOriginalPickupSaved:
    """Verify _haiku_original_pickup is saved before Copart post-processing."""

    def test_original_pickup_saved_before_copart_postprocess(self):
        """When Haiku extracts Copart data, original pickup values are saved
        BEFORE directory post-processing replaces them."""
        from services.haiku_extractor import HaikuExtractor, normalize_haiku_result

        extractor = HaikuExtractor(api_key="test-key")

        # Simulate Haiku extracting wrong pickup (buyer address instead of lot)
        haiku_response = json.dumps({
            "auction_type": "COPART",
            "vehicle_vin": "1C4RJFAG2GC489125",
            "vehicle_year": 2016,
            "vehicle_make": "JEEP",
            "vehicle_model": "GRAND CHEROKEE",
            "pickup_name": "COPART - AYER",
            "pickup_address": "77 FITCHBURG ROAD",
            "pickup_city": "AYER",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        })

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=haiku_response)]
        mock_response.usage = MagicMock(
            input_tokens=100, output_tokens=50,
            cache_read_input_tokens=0, cache_creation_input_tokens=0
        )

        calls = []

        def tracking_extract(pdf_path, use_layout=False):
            calls.append(use_layout)
            return ("enough text" * 10, 1, 100)

        extractor.extract_text_from_pdf = tracking_extract

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        extractor._client = mock_client
        result = extractor.extract("dummy.pdf", auction_type="COPART")

        # _haiku_original_pickup should be in the result fields
        assert "_haiku_original_pickup" in result.fields
        original = result.fields["_haiku_original_pickup"].value

        # Original should have Haiku's ORIGINAL values (before directory correction)
        assert original["pickup_address"] == "77 FITCHBURG ROAD"
        assert original["pickup_city"] == "AYER"
        assert original["pickup_state"] == "MA"
        assert original["pickup_zip"] == "01432"

        # Post-processed values should be from Copart North Boston directory
        outputs, _ = normalize_haiku_result(result)
        assert outputs["pickup_city"] == "AYER"  # Ayer is correct city for 01432
        assert outputs["pickup_zip"] == "01432"
        # pickup_name should be resolved via directory
        assert "Copart" in outputs.get("pickup_name", "")

        # _haiku_original_pickup should flow into outputs
        assert "_haiku_original_pickup" in outputs
        assert outputs["_haiku_original_pickup"]["pickup_address"] == "77 FITCHBURG ROAD"

    def test_original_pickup_saved_for_iaa(self):
        """_haiku_original_pickup is saved for IAA too (no post-processing changes it)."""
        from services.haiku_extractor import HaikuExtractor, normalize_haiku_result

        extractor = HaikuExtractor(api_key="test-key")

        haiku_response = json.dumps({
            "auction_type": "IAA",
            "vehicle_vin": "WA1CCAFP4GA133227",
            "pickup_name": "East Bay",
            "pickup_address": "2780 Willow Pass Road",
            "pickup_city": "Bay Point",
            "pickup_state": "CA",
            "pickup_zip": "94565",
        })

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=haiku_response)]
        mock_response.usage = MagicMock(
            input_tokens=100, output_tokens=50,
            cache_read_input_tokens=0, cache_creation_input_tokens=0
        )

        def stub_extract(pdf_path, use_layout=False):
            return ("enough text" * 10, 1, 100)

        extractor.extract_text_from_pdf = stub_extract

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        extractor._client = mock_client
        result = extractor.extract("dummy.pdf", auction_type="IAA")

        assert "_haiku_original_pickup" in result.fields
        original = result.fields["_haiku_original_pickup"].value
        assert original["pickup_city"] == "Bay Point"
        assert original["pickup_state"] == "CA"


# ─── Test: Validation status logic ───────────────────────────────────────────


class TestValidationCorrectedByDirectory:
    """Verify validation correctly detects when directory replaced Haiku's values."""

    def test_corrected_by_directory_when_original_differs(self):
        """When original pickup differs from directory, status = corrected_by_directory."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()

        # Post-processed values (from directory — Copart North Boston)
        pickup_fields = {
            "pickup_name": "Copart North Boston",
            "pickup_address": "77 Fitchburg Rd",
            "pickup_city": "Ayer",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        }

        # Original Haiku extraction was DIFFERENT (Le Roy, NY)
        original_pickup = {
            "pickup_name": "COPART - LEROY",
            "pickup_address": "4 WEST AVE",
            "pickup_city": "LEROY",
            "pickup_state": "NY",
            "pickup_zip": "14482",
        }

        result = validator.validate("COPART", pickup_fields, original_pickup=original_pickup)

        # All fields should be corrected_by_directory (original != directory)
        for key in ["pickup_name", "pickup_address", "pickup_city", "pickup_state"]:
            assert result["fields"][key]["status"] == "corrected_by_directory", \
                f"{key} should be corrected_by_directory, got {result['fields'][key]['status']}"
            assert "original" in result["fields"][key], \
                f"{key} should have 'original' field"

        # ZIP should also be corrected (14482 != 01432)
        assert result["fields"]["pickup_zip"]["status"] == "corrected_by_directory"
        assert result["fields"]["pickup_zip"]["original"] == "14482"

        # Directory match should still be True (post-processed values match)
        assert result["directory_match"] is True

    def test_verified_when_original_matches_directory(self):
        """When original pickup matches directory, status = verified (not corrected)."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()

        # Post-processed values match Copart North Boston
        pickup_fields = {
            "pickup_name": "Copart North Boston",
            "pickup_address": "77 Fitchburg Rd",
            "pickup_city": "Ayer",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        }

        # Original Haiku extraction was THE SAME (correct extraction)
        original_pickup = {
            "pickup_name": "Copart North Boston",
            "pickup_address": "77 FITCHBURG RD",
            "pickup_city": "AYER",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        }

        result = validator.validate("COPART", pickup_fields, original_pickup=original_pickup)

        # All fields should be verified (original matches directory)
        for key in ["pickup_name", "pickup_address", "pickup_city", "pickup_state", "pickup_zip"]:
            assert result["fields"][key]["status"] == "verified", \
                f"{key} should be verified, got {result['fields'][key]['status']}"

    def test_verified_when_no_original_available(self):
        """When no original_pickup provided, falls back to standard verified."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()

        pickup_fields = {
            "pickup_name": "Copart North Boston",
            "pickup_address": "77 Fitchburg Rd",
            "pickup_city": "Ayer",
            "pickup_state": "MA",
            "pickup_zip": "01432",
        }

        result = validator.validate("COPART", pickup_fields, original_pickup=None)

        # Should be plain "verified" without original comparison
        for key in ["pickup_name", "pickup_address", "pickup_city", "pickup_state", "pickup_zip"]:
            assert result["fields"][key]["status"] == "verified", \
                f"{key} should be verified, got {result['fields'][key]['status']}"

    def test_unverified_when_zip_not_in_directory(self):
        """When ZIP is not in any directory, status = unverified."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()

        pickup_fields = {
            "pickup_name": "Some Unknown Location",
            "pickup_address": "123 Main St",
            "pickup_city": "Nowhereville",
            "pickup_state": "TX",
            "pickup_zip": "99999",
        }

        result = validator.validate("COPART", pickup_fields)

        for key in ["pickup_name", "pickup_address", "pickup_city", "pickup_state", "pickup_zip"]:
            assert result["fields"][key]["status"] == "unverified"
        assert result["directory_match"] is False


# ─── Test: Copart Le Roy in directory ────────────────────────────────────────


class TestCopartLeRoyDirectory:
    """Verify Copart Le Roy was added to directory correctly."""

    def test_leroy_exists_in_directory(self):
        """Copart Le Roy should exist in COPART_LOCATIONS."""
        from services.auction_directory import COPART_LOCATIONS

        assert "Copart Le Roy" in COPART_LOCATIONS
        loc = COPART_LOCATIONS["Copart Le Roy"]
        assert loc["address"] == "4 West Ave"
        assert loc["city"] == "LeRoy"
        assert loc["state"] == "NY"
        assert loc["zip"] == "14482"
        assert loc["phone"] == "(585) 768-8160"

    def test_copart_name_from_city_leroy(self):
        """_copart_name_from_city should resolve LEROY to Copart Le Roy."""
        from services.haiku_extractor import _copart_name_from_city, ExtractedField

        fields = {
            "pickup_state": ExtractedField(value="NY"),
            "pickup_zip": ExtractedField(value="14482"),
        }
        result = _copart_name_from_city("LEROY", fields)
        assert result == "Copart Le Roy"

    def test_copart_zip_fallback_14482(self):
        """ZIP 14482 should resolve to Copart Le Roy even with wrong city."""
        from services.haiku_extractor import _copart_name_from_city, ExtractedField

        fields = {
            "pickup_state": ExtractedField(value="NY"),
            "pickup_zip": ExtractedField(value="14482"),
        }
        result = _copart_name_from_city("WRONGCITY", fields)
        assert result == "Copart Le Roy"
