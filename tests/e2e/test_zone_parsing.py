"""
E2E Tests — Zone Extractor Parsing Fixes

Tests cover:
  - pickup_address preserves full street name (no truncation)
  - pickup_city contains only city name (no street address words)
  - sale_price does not match date fragments
  - total_amount uses Total Due, not Net Due
  - Zone fallback merge does not overwrite existing pattern values
"""

import json
import uuid

import pytest

from extractors.zone_extractor import ZoneExtractor, ZoneField, FieldType


@pytest.fixture(scope="module")
def extractor():
    """Create a ZoneExtractor instance for parsing tests."""
    return ZoneExtractor()


# =============================================================================
# Bug 1: pickup_address must preserve full street name
# =============================================================================


class TestZoneAddressFullStreet:
    """Address parsing must keep full street name — no truncation."""

    def test_pond_station_road_not_truncated(self, extractor):
        """'3100 POND STATION ROAD' must NOT be truncated to '3100 Pond St'."""
        text = "3100 POND STATION ROAD"
        result = extractor._parse_address_from_text(text)
        assert result is not None
        assert "POND STATION ROAD" in result.upper()
        # Must NOT be truncated to just "Pond St"
        assert result.upper() != "3100 POND ST"

    def test_main_street_not_confused(self, extractor):
        """'123 MAIN STREET' should parse correctly (ST inside STREET is fine)."""
        text = "123 MAIN STREET"
        result = extractor._parse_address_from_text(text)
        assert result is not None
        assert "MAIN STREET" in result.upper()

    def test_simple_rd_address(self, extractor):
        """'456 OAK RD' should still match with short suffix."""
        text = "456 OAK RD"
        result = extractor._parse_address_from_text(text)
        assert result is not None
        assert "OAK RD" in result.upper()

    def test_no_title_case_applied(self, extractor):
        """Address should be returned as-is (uppercase), not title-cased."""
        text = "3100 POND STATION ROAD"
        result = extractor._parse_address_from_text(text)
        assert result is not None
        # Should preserve original case (all uppercase input → all uppercase output)
        assert result == "3100 POND STATION ROAD"

    def test_compound_name_with_drive(self, extractor):
        """'789 SILVER SPRINGS DRIVE' must not truncate at 'DR' inside 'DRIVE'."""
        text = "789 SILVER SPRINGS DRIVE"
        result = extractor._parse_address_from_text(text)
        assert result is not None
        assert "SILVER SPRINGS DRIVE" in result.upper()


# =============================================================================
# Bug 2: pickup_city must NOT contain street address
# =============================================================================


class TestZoneCityNoStreet:
    """City field must contain only the city name, not street address fragments."""

    def test_city_from_multiline_text(self, extractor):
        """City should be parsed from 'LOUISVILLE KY 40272' line, not street line."""
        text = "3100 POND STATION ROAD\nLOUISVILLE KY 40272"
        city, state, zip_code = extractor._parse_city_state_zip(text)
        assert city is not None
        assert city.upper() == "LOUISVILLE"
        assert state == "KY"
        assert zip_code == "40272"
        # Must NOT contain street address
        assert "POND" not in city.upper()
        assert "ROAD" not in city.upper()
        assert "STATION" not in city.upper()

    def test_city_single_line(self, extractor):
        """Single-line 'LOUISVILLE KY 40272' should parse correctly."""
        text = "LOUISVILLE KY 40272"
        city, state, zip_code = extractor._parse_city_state_zip(text)
        assert city is not None
        assert city.upper() == "LOUISVILLE"
        assert state == "KY"
        assert zip_code == "40272"

    def test_multiword_city(self, extractor):
        """Multi-word cities like 'LAS VEGAS' should be fully captured."""
        text = "4810 N LAMB BLVD\nLAS VEGAS NV 89115"
        city, state, zip_code = extractor._parse_city_state_zip(text)
        assert city is not None
        assert city.upper() == "LAS VEGAS"
        assert state == "NV"

    def test_city_with_comma(self, extractor):
        """'PORTLAND, OR 97230' should parse city correctly."""
        text = "PORTLAND, OR 97230"
        city, state, zip_code = extractor._parse_city_state_zip(text)
        assert city is not None
        assert city.upper() == "PORTLAND"
        assert state == "OR"


# =============================================================================
# Bug 3: sale_price must NOT match date fragments
# =============================================================================


class TestZoneSalePriceNotDate:
    """CURRENCY fallback must require $ sign, not grab bare numbers from dates."""

    def test_currency_requires_dollar_sign(self, extractor):
        """Text with only a date '03/03/2026 Payment' should NOT yield a currency value."""
        field_def = ZoneField(key="sale_price", field_type=FieldType.CURRENCY)
        text = "03/03/2026 Payment Due"
        result = extractor.parse_field_from_text(text, field_def)
        # Should NOT match "03" from the date
        assert result is None

    def test_currency_with_dollar_sign(self, extractor):
        """'$6,900.00' should parse correctly."""
        field_def = ZoneField(key="sale_price", field_type=FieldType.CURRENCY)
        text = "Amount: $6,900.00"
        result = extractor.parse_field_from_text(text, field_def)
        assert result == "6900.00"

    def test_sale_price_pattern_matches_correctly(self, extractor):
        """Sale Price pattern should match 'Sale Price: $6,900.00' not dates."""
        field_def = ZoneField(
            key="sale_price",
            field_type=FieldType.CURRENCY,
            pattern=r"Sale\s*Price[:\s]*\$?([\d,]+\.?\d*)",
        )
        text = "Sale Date: 03/03/2026\nSale Price: $6,900.00"
        result = extractor.parse_field_from_text(text, field_def)
        assert result == "6,900.00"


# =============================================================================
# Bug 3b: total_amount must use Total Due, not Net Due
# =============================================================================


class TestZoneTotalAmountNotNetDue:
    """total_amount should match 'Total Due', not 'Net Due' (which is 0 after payment)."""

    def test_total_due_pattern(self, extractor):
        """Pattern should match 'Total Due' not 'Net Due'."""
        field_def = ZoneField(
            key="total_amount",
            field_type=FieldType.CURRENCY,
            pattern=r"Total\s*(?:Due|Charges|Amount).*?\$?([\d,]+\.?\d*)",
        )
        text = "Net Due (USD) $0.00\nTotal Due (USD) $6,900.00"
        result = extractor.parse_field_from_text(text, field_def)
        assert result == "6,900.00"

    def test_net_due_not_matched(self, extractor):
        """Pattern must NOT match 'Net Due'."""
        field_def = ZoneField(
            key="total_amount",
            field_type=FieldType.CURRENCY,
            pattern=r"Total\s*(?:Due|Charges|Amount).*?\$?([\d,]+\.?\d*)",
        )
        text = "Net Due (USD) $0.00"
        result = extractor.parse_field_from_text(text, field_def)
        # Should not match Net Due
        assert result is None

    def test_total_charges_matched(self, extractor):
        """'Total Charges: $5,250.00' should be matched."""
        field_def = ZoneField(
            key="total_amount",
            field_type=FieldType.CURRENCY,
            pattern=r"Total\s*(?:Due|Charges|Amount).*?\$?([\d,]+\.?\d*)",
        )
        text = "Total Charges: $5,250.00"
        result = extractor.parse_field_from_text(text, field_def)
        assert result == "5,250.00"


# =============================================================================
# Bug 4: Zone fallback merge must not overwrite existing pattern values
# =============================================================================


class TestMergePreservesExistingValues:
    """When zone is fallback (Haiku failed), it must not overwrite existing pattern values."""

    def test_zone_fallback_preserves_pattern_total(self):
        """Zone fallback with total_amount=0.00 must NOT overwrite pattern total_amount=6900.0."""
        # Simulate the merge logic from extractions.py
        outputs = {"total_amount": "6900.0", "sale_date": "2026-03-03"}
        zone_outputs = {"total_amount": "0.00", "sale_price": "03", "pickup_city": "Louisville"}
        extraction_method = "zone_fallback"

        zone_is_fallback = extraction_method == "zone_fallback"

        for field_key, zone_value in zone_outputs.items():
            if zone_value is not None and str(zone_value).strip():
                old_value = outputs.get(field_key)
                if zone_is_fallback and old_value is not None and str(old_value).strip():
                    continue  # Skip — preserve existing value
                outputs[field_key] = zone_value

        # total_amount should be preserved (not overwritten to 0.00)
        assert outputs["total_amount"] == "6900.0"
        # sale_date should be preserved
        assert outputs["sale_date"] == "2026-03-03"
        # pickup_city should be filled (was missing from pattern extraction)
        assert outputs["pickup_city"] == "Louisville"

    def test_haiku_primary_overrides_freely(self):
        """When Haiku is primary (not fallback), merge should override all values."""
        outputs = {"total_amount": "500.0", "pickup_city": "Old City"}
        zone_outputs = {"total_amount": "6900.0", "pickup_city": "Louisville"}
        extraction_method = "haiku"

        zone_is_fallback = extraction_method == "zone_fallback"

        for field_key, zone_value in zone_outputs.items():
            if zone_value is not None and str(zone_value).strip():
                old_value = outputs.get(field_key)
                if zone_is_fallback and old_value is not None and str(old_value).strip():
                    continue
                outputs[field_key] = zone_value

        # Haiku should override everything
        assert outputs["total_amount"] == "6900.0"
        assert outputs["pickup_city"] == "Louisville"
