"""Tests for the training and learning system."""

from unittest.mock import MagicMock, patch

import pytest

from extractors.address_parser import extract_lines_after_label
from extractors.base import LearnedRule
from extractors.copart import CopartExtractor
from extractors.iaa import IAAExtractor
from extractors.manheim import ManheimExtractor


class TestExtractLinesAfterLabel:
    """Tests for the extract_lines_after_label function."""

    def test_basic_extraction(self):
        """Test basic label-value extraction."""
        text = """
PHYSICAL ADDRESS OF LOT:
46 ZUK-PIERCE RD
CENTRAL SQUARE, NY 13036
Phone: 555-1234
"""
        lines = extract_lines_after_label(text, r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT")
        assert lines is not None
        assert len(lines) >= 2
        assert "46 ZUK-PIERCE RD" in lines[0]

    def test_with_colon_in_label(self):
        """Test label with colon."""
        text = "SELLER:\nFARMERS INS HOME OFFICE\nSome other text"
        lines = extract_lines_after_label(text, r"SELLER")
        assert lines is not None
        assert len(lines) > 0, f"Expected lines, got: {lines}"
        assert "FARMERS INS HOME OFFICE" in lines[0]

    def test_case_insensitive(self):
        """Test case insensitive matching."""
        text = "Seller:\nACME INSURANCE CO\nMore text"
        lines = extract_lines_after_label(text, r"seller", max_lines=2)
        assert lines is not None
        assert len(lines) > 0, f"Expected lines, got: {lines}"
        assert "ACME INSURANCE CO" in lines[0]

    def test_no_match(self):
        """Test when label is not found."""
        text = "Some text without the label we're looking for"
        lines = extract_lines_after_label(text, r"NONEXISTENT\s*LABEL")
        assert lines is None or len(lines) == 0

    def test_max_lines_limit(self):
        """Test max_lines parameter."""
        text = """
LABEL:
Line 1
Line 2
Line 3
Line 4
Line 5
"""
        lines = extract_lines_after_label(text, r"LABEL", max_lines=3)
        assert lines is not None
        assert len(lines) <= 3


class TestLearnedRule:
    """Tests for the LearnedRule dataclass."""

    def test_matches_label(self):
        """Test label pattern matching."""
        rule = LearnedRule(
            field_key="pickup_address",
            rule_type="label_below",
            label_patterns=[r"PHYSICAL\s*ADDRESS", r"LOT\s*LOCATION"],
            exclude_patterns=["MEMBER", "BUYER"],
            confidence=0.8,
        )

        assert rule.matches_label("PHYSICAL ADDRESS OF LOT")
        assert rule.matches_label("LOT LOCATION:")
        assert not rule.matches_label("SOME OTHER TEXT")

    def test_should_exclude(self):
        """Test exclusion pattern matching."""
        rule = LearnedRule(
            field_key="pickup_address",
            rule_type="label_below",
            label_patterns=[r"ADDRESS"],
            exclude_patterns=["MEMBER", "BUYER", "BILLING"],
            confidence=0.8,
        )

        assert rule.should_exclude("MEMBER: 12345")
        assert rule.should_exclude("BILLING ADDRESS")
        assert not rule.should_exclude("46 ZUK-PIERCE RD")


class TestCopartExtractorWithLearnedRules:
    """Tests for Copart extractor with learned rules integration."""

    COPART_SAMPLE = """
Copart
Sales Receipt/Bill of Sale
SOLD THROUGH COPART

MEMBER:
12345678
BROADWAY MOTORING INC

SELLER:
FARMERS INS HOME OFFICE

VEHICLE: 2020 HYUNDAI TUCSON BLACK 45678
VIN: 5NMZU3LB5LH123456
Mileage: 45678

PHYSICAL ADDRESS OF LOT:
46 ZUK-PIERCE RD
CENTRAL SQUARE, NY 13036

LOT# 789456
Sale Date: 01/15/2024
"""

    def test_extract_buyer_name(self):
        """Test buyer name extraction from below MEMBER line."""
        extractor = CopartExtractor()
        # Mock learned rules to not interfere
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        buyer_name = extractor._extract_buyer_name(self.COPART_SAMPLE)
        assert buyer_name == "BROADWAY MOTORING INC"

    def test_extract_seller_name(self):
        """Test seller name extraction."""
        extractor = CopartExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        seller_name = extractor._extract_seller_name(self.COPART_SAMPLE)
        assert "FARMERS" in seller_name or seller_name == "FARMERS INS HOME OFFICE"

    def test_with_learned_rule(self):
        """Test extraction with learned rule override."""
        extractor = CopartExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {
            "seller_name": LearnedRule(
                field_key="seller_name",
                rule_type="label_below",
                label_patterns=[r"SELLER"],
                exclude_patterns=["SOLD", "THROUGH"],
                confidence=0.9,
            )
        }

        seller_name = extractor._extract_seller_name(self.COPART_SAMPLE)
        assert seller_name == "FARMERS INS HOME OFFICE"


class TestIAAExtractorWithLearnedRules:
    """Tests for IAA extractor with learned rules integration."""

    IAA_SAMPLE = """
Insurance Auto Auctions, Inc.
BUYER RECEIPT

Buyer Name:
ABC AUTO SALES INC

Buyer #: 98765

Seller:
STATE FARM INSURANCE

Pick-Up Location:
123 AUCTION BLVD
TAMPA, FL 33601
Phone: (813) 555-1234

StockNo: 123-456789
VIN: 1HGBH41JXMN109186
2020 HONDA ACCORD SILVER
Mileage: 50000

Total Due: $5,500.00
"""

    def test_extract_buyer_name(self):
        """Test buyer name extraction."""
        extractor = IAAExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        buyer_name = extractor._extract_buyer_name(self.IAA_SAMPLE)
        assert "ABC AUTO SALES" in buyer_name

    def test_extract_seller_name(self):
        """Test seller name extraction."""
        extractor = IAAExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        seller_name = extractor._extract_seller_name(self.IAA_SAMPLE)
        assert "STATE FARM" in seller_name

    def test_extract_pickup_location(self):
        """Test pickup location extraction."""
        extractor = IAAExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        address = extractor._extract_pickup_location(self.IAA_SAMPLE)
        assert address is not None
        assert "123 AUCTION BLVD" in address.street or "TAMPA" in address.city

    def test_extract_stock_number_default(self):
        """Test stock number extraction with default patterns."""
        extractor = IAAExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        stock = extractor._extract_stock_number(self.IAA_SAMPLE)
        assert stock == "123-456789"

    def test_extract_stock_number_with_learned_rule(self):
        """Test stock number extraction with learned rules from training."""
        extractor = IAAExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {
            "vehicle_lot": LearnedRule(
                field_key="vehicle_lot",
                rule_type="label_below",
                label_patterns=[r"Stock\\s*No", r"StockNo"],
                exclude_patterns=[],
                confidence=0.9,
            )
        }

        stock = extractor._extract_stock_number(self.IAA_SAMPLE)
        assert stock == "123-456789"

    def test_extract_stock_number_alternate_format(self):
        """Test stock number extraction with different format."""
        alternate_text = """
Stock Number: 98765432
VIN: 1HGBH41JXMN109186
"""
        extractor = IAAExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        stock = extractor._extract_stock_number(alternate_text)
        assert stock == "98765432"

    def test_vehicle_lot_in_default_labels(self):
        """Test that vehicle_lot is defined in DEFAULT_LABELS."""
        extractor = IAAExtractor()
        assert "vehicle_lot" in extractor.DEFAULT_LABELS
        assert len(extractor.DEFAULT_LABELS["vehicle_lot"]) >= 1


class TestManheimExtractorWithLearnedRules:
    """Tests for Manheim extractor with learned rules integration."""

    MANHEIM_SAMPLE = """
Manheim Auto Auction
Cox Automotive
BILL OF SALE

Buyer:
XYZ MOTORS LLC

Account #: 54321

Seller:
ENTERPRISE RENT-A-CAR

Pickup Location Address:
456 DEALER WAY
ATLANTA, GA 30339
Phone: (404) 555-9876

YMMT: 2021 TOYOTA CAMRY
VIN: 4T1B11HK5MU123456
Color: White
Mileage: 35000

Release ID: MAN789456
Final Sale Price: $22,500.00
"""

    def test_extract_buyer_name(self):
        """Test buyer name extraction."""
        extractor = ManheimExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        buyer_name = extractor._extract_buyer_name(self.MANHEIM_SAMPLE)
        assert "XYZ MOTORS" in buyer_name

    def test_extract_seller_name(self):
        """Test seller name extraction."""
        extractor = ManheimExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        seller_name = extractor._extract_seller_name(self.MANHEIM_SAMPLE)
        assert "ENTERPRISE" in seller_name

    def test_extract_pickup_location(self):
        """Test pickup location extraction."""
        extractor = ManheimExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        address = extractor._extract_pickup_location(self.MANHEIM_SAMPLE)
        assert address is not None


@pytest.mark.skipif(True, reason="Requires sqlmodel which may not be installed in test env")
class TestTrainingModels:
    """Tests for training data models."""

    def test_extraction_rule_json_methods(self):
        """Test ExtractionRule JSON serialization/deserialization."""
        pytest.importorskip("sqlmodel")
        from models.training import ExtractionRule

        rule = ExtractionRule(
            auction_type_id=1,
            field_key="pickup_address",
            rule_type="label_below",
        )

        # Test setting patterns
        patterns = [r"PHYSICAL\s*ADDRESS", r"LOT\s*LOCATION"]
        rule.set_label_patterns(patterns)
        assert rule.get_label_patterns() == patterns

        # Test exclude patterns
        excludes = ["MEMBER", "BUYER"]
        rule.set_exclude_patterns(excludes)
        assert rule.get_exclude_patterns() == excludes

    def test_field_correction_create(self):
        """Test FieldCorrectionCreate model."""
        pytest.importorskip("sqlmodel")
        from models.training import FieldCorrectionCreate

        correction = FieldCorrectionCreate(
            field_key="pickup_address",
            predicted_value="Wrong address",
            corrected_value="Correct address",
            was_correct=False,
        )

        assert correction.field_key == "pickup_address"
        assert correction.was_correct is False


@pytest.mark.skipif(True, reason="Requires sqlmodel which may not be installed in test env")
class TestCorrectionRulesServiceMocked:
    """Tests for CorrectionRulesService with mocked database."""

    def test_save_corrections(self):
        """Test saving corrections creates training records."""
        pytest.importorskip("sqlmodel")
        from models.training import FieldCorrectionCreate
        from services.correction_rules_service import CorrectionRulesService

        mock_session = MagicMock()

        # Mock the extraction run
        mock_run = MagicMock()
        mock_run.id = 1
        mock_run.auction_type_id = 1
        mock_run.extracted_text = "Sample text"
        mock_session.get.return_value = mock_run

        service = CorrectionRulesService(mock_session)

        corrections = [
            FieldCorrectionCreate(
                field_key="pickup_address",
                predicted_value="Wrong",
                corrected_value="Correct",
                was_correct=False,
            )
        ]

        # Call save_corrections
        with patch.object(service, "_learn_from_corrections"):
            saved, errors = service.save_corrections(1, corrections)

        # Verify session was used
        assert mock_session.add.called
        assert mock_session.commit.called


class TestAddressParsingEdgeCases:
    """Test edge cases in address parsing."""

    def test_parse_address_from_lines_empty(self):
        """Test with empty lines."""
        extractor = CopartExtractor()
        result = extractor._parse_address_from_lines([])
        assert result is None

    def test_parse_address_from_lines_with_excludes(self):
        """Test filtering excluded patterns."""
        extractor = CopartExtractor()
        lines = [
            "MEMBER: 12345",  # Should be excluded
            "46 ZUK-PIERCE RD",
            "CENTRAL SQUARE, NY 13036",
        ]
        result = extractor._parse_address_from_lines(lines, ["MEMBER"])
        assert result is not None
        assert "MEMBER" not in result.street

    def test_multiline_address_extraction(self):
        """Test extraction of multi-line addresses."""
        text = "PHYSICAL ADDRESS OF LOT:\n46 ZUK-PIERCE RD\nCENTRAL SQUARE, NY 13036"
        lines = extract_lines_after_label(text, r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT")
        assert len(lines) >= 2, f"Expected at least 2 lines, got: {lines}"

        extractor = CopartExtractor()
        address = extractor._parse_address_from_lines(lines)
        assert address is not None
        assert address.street == "46 ZUK-PIERCE RD"


class TestDefaultLabelsConfig:
    """Test default label configurations for each extractor."""

    def test_copart_default_labels(self):
        """Test Copart has required default labels."""
        extractor = CopartExtractor()
        assert "pickup_address" in extractor.DEFAULT_LABELS
        assert "buyer_name" in extractor.DEFAULT_LABELS
        assert "seller_name" in extractor.DEFAULT_LABELS

    def test_iaa_default_labels(self):
        """Test IAA has required default labels."""
        extractor = IAAExtractor()
        assert "pickup_address" in extractor.DEFAULT_LABELS
        assert "buyer_name" in extractor.DEFAULT_LABELS
        assert "seller_name" in extractor.DEFAULT_LABELS

    def test_manheim_default_labels(self):
        """Test Manheim has required default labels."""
        extractor = ManheimExtractor()
        assert "pickup_address" in extractor.DEFAULT_LABELS
        assert "buyer_name" in extractor.DEFAULT_LABELS
        assert "seller_name" in extractor.DEFAULT_LABELS


class TestLearnedRulesLoading:
    """Test learned rules loading functionality."""

    def test_load_learned_rules_caching(self):
        """Test that rules are cached after first load."""
        extractor = CopartExtractor()

        # Simulate loaded rules
        extractor._rules_loaded = True
        extractor._learned_rules = {
            "test": LearnedRule(
                field_key="test",
                rule_type="label_below",
                label_patterns=[],
                exclude_patterns=[],
                confidence=0.5,
            )
        }

        # Call load again
        rules = extractor.load_learned_rules()

        # Should return cached rules
        assert "test" in rules

    def test_get_learned_rule_missing(self):
        """Test getting a non-existent rule."""
        extractor = CopartExtractor()
        extractor._rules_loaded = True
        extractor._learned_rules = {}

        rule = extractor.get_learned_rule("nonexistent_field")
        assert rule is None

    def test_get_learned_rule_exists(self):
        """Test getting an existing rule."""
        extractor = CopartExtractor()
        extractor._rules_loaded = True
        test_rule = LearnedRule(
            field_key="pickup_address",
            rule_type="label_below",
            label_patterns=[r"PHYSICAL\s*ADDRESS"],
            exclude_patterns=[],
            confidence=0.8,
        )
        extractor._learned_rules = {"pickup_address": test_rule}

        rule = extractor.get_learned_rule("pickup_address")
        assert rule is not None
        assert rule.field_key == "pickup_address"
        assert rule.confidence == 0.8


class TestZoneFieldWithLabelPatterns:
    """Tests for ZoneField with label_patterns functionality."""

    def test_zone_field_with_label_patterns(self):
        """Test ZoneField stores label_patterns correctly."""
        from extractors.zone_extractor import ZoneField, FieldType

        field = ZoneField(
            key="vehicle_lot",
            field_type=FieldType.TEXT,
            label_patterns=[r"Stock\s*No", r"StockNo", r"Stock\s*#"],
            extract_strategy="after_label",
        )

        assert field.key == "vehicle_lot"
        assert len(field.label_patterns) == 3
        assert field.extract_strategy == "after_label"

    def test_zone_field_default_values(self):
        """Test ZoneField default values for new fields."""
        from extractors.zone_extractor import ZoneField, FieldType

        field = ZoneField(key="test_field")

        assert field.label_patterns == []
        assert field.extract_strategy == "after_label"
        assert field.field_type == FieldType.TEXT

    def test_zone_field_serialization(self):
        """Test ZoneField serialization with label_patterns."""
        from extractors.zone_extractor import DocumentZone, ZoneField, FieldType

        zone = DocumentZone(
            name="test_zone",
            x0=0, y0=0, x1=100, y1=100,
            fields=[
                ZoneField(
                    key="stock_number",
                    field_type=FieldType.TEXT,
                    label_patterns=[r"Stock\s*No"],
                    extract_strategy="after_label",
                )
            ]
        )

        data = zone.to_dict()
        assert "label_patterns" in data["fields"][0]
        assert data["fields"][0]["label_patterns"] == [r"Stock\s*No"]
        assert data["fields"][0]["extract_strategy"] == "after_label"

    def test_zone_field_deserialization(self):
        """Test ZoneField deserialization with label_patterns."""
        from extractors.zone_extractor import DocumentZone

        data = {
            "name": "test_zone",
            "x0": 0, "y0": 0, "x1": 100, "y1": 100,
            "fields": [
                {
                    "key": "stock_number",
                    "field_type": "text",
                    "label_patterns": [r"Stock\s*No", r"StockNo"],
                    "extract_strategy": "after_label",
                }
            ]
        }

        zone = DocumentZone.from_dict(data)
        field = zone.fields[0]
        assert field.label_patterns == [r"Stock\s*No", r"StockNo"]
        assert field.extract_strategy == "after_label"

    def test_parse_field_with_label_patterns(self):
        """Test field extraction using label_patterns array."""
        from extractors.zone_extractor import ZoneExtractor, ZoneField, FieldType

        extractor = ZoneExtractor()

        # Text with stock number following "StockNo:" label
        text = """
Some header text
StockNo: 123-456789
VIN: 1HGBH41JXMN109186
More text
"""

        field_def = ZoneField(
            key="stock_number",
            field_type=FieldType.TEXT,
            label_patterns=[r"Stock\s*No", r"StockNo"],
            extract_strategy="after_label",
        )

        value = extractor.parse_field_from_text(text, field_def)
        assert value is not None
        assert "123-456789" in value


class TestUnmatchedFieldsDetection:
    """Tests for unmatched fields detection in training."""

    def test_find_context_returns_none_for_missing_value(self):
        """Test that _find_context returns None when value not in text."""
        from services.correction_rules_service import CorrectionRulesService
        from unittest.mock import MagicMock

        session = MagicMock()
        service = CorrectionRulesService(session)

        text = "Some document text here"
        value = "VALUE_NOT_IN_TEXT"

        context = service._find_context(text, value)
        assert context is None

    def test_find_context_returns_context_when_found(self):
        """Test that _find_context returns context when value found."""
        from services.correction_rules_service import CorrectionRulesService
        from unittest.mock import MagicMock

        session = MagicMock()
        service = CorrectionRulesService(session)

        text = "Some prefix text THE VALUE IS HERE more text after"
        value = "THE VALUE IS HERE"

        context = service._find_context(text, value)
        assert context is not None
        assert value in context

    def test_learning_summary_includes_unmatched_fields(self):
        """Test that learning_summary includes unmatched_fields."""
        # This is an integration test placeholder
        # The actual integration would require database setup
        pass
