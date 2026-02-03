"""Tests for PDF extractors."""

from extractors import ExtractorManager
from extractors.base import BaseExtractor
from extractors.copart import CopartExtractor
from extractors.iaa import IAAExtractor
from extractors.manheim import ManheimExtractor
from models.vehicle import AuctionSource, VehicleType


class TestBaseExtractor:
    """Tests for BaseExtractor utility methods."""

    def test_extract_vin_valid(self):
        """Test VIN extraction with valid 17-char VIN."""
        text = "Vehicle VIN: 1HGBH41JXMN109186 is ready"
        vin = BaseExtractor.extract_vin(text)
        assert vin == "1HGBH41JXMN109186"

    def test_extract_vin_no_match(self):
        """Test VIN extraction with no valid VIN."""
        text = "No VIN here, just some text"
        vin = BaseExtractor.extract_vin(text)
        assert vin is None

    def test_extract_vin_excludes_invalid(self):
        """Test that VINs with I, O, Q are not matched."""
        # VINs cannot contain I, O, or Q
        text = "Invalid VIN: 1HGBH41JOMN109186"  # Contains O
        vin = BaseExtractor.extract_vin(text)
        assert vin is None

    def test_extract_phone(self):
        """Test phone number extraction."""
        test_cases = [
            ("Call us at (555) 123-4567", "(555) 123-4567"),
            ("Phone: 555-123-4567", "555-123-4567"),
            ("Contact: 555.123.4567", "555.123.4567"),
        ]
        for text, _expected in test_cases:
            result = BaseExtractor.extract_phone(text)
            assert result is not None, f"Failed to extract from: {text}"

    def test_extract_zip(self):
        """Test ZIP code extraction."""
        text = "Address: 123 Main St, City, ST 12345-6789"
        zip_code = BaseExtractor.extract_zip(text)
        assert zip_code == "12345-6789"

        text2 = "ZIP: 90210"
        zip_code2 = BaseExtractor.extract_zip(text2)
        assert zip_code2 == "90210"

    def test_detect_vehicle_type_suv(self):
        """Test SUV detection."""
        suv_cases = [
            ("VOLVO", "XC90"),
            ("JEEP", "CHEROKEE"),
            ("FORD", "EXPLORER"),
            ("HYUNDAI", "TUCSON"),
        ]
        for make, model in suv_cases:
            result = BaseExtractor.detect_vehicle_type(make, model)
            assert result == VehicleType.SUV, f"Failed for {make} {model}"

    def test_detect_vehicle_type_car(self):
        """Test car detection."""
        car_cases = [
            ("ALFA ROMEO", "GIULIA"),
            ("MERCEDES", "E 300"),
            ("TOYOTA", "CAMRY"),
        ]
        for make, model in car_cases:
            result = BaseExtractor.detect_vehicle_type(make, model)
            assert result == VehicleType.CAR, f"Failed for {make} {model}"

    def test_detect_vehicle_type_truck(self):
        """Test truck detection."""
        truck_cases = [
            ("FORD", "F-150"),
            ("CHEVROLET", "SILVERADO"),
            ("RAM", "1500 TRUCK"),
        ]
        for make, model in truck_cases:
            result = BaseExtractor.detect_vehicle_type(make, model)
            assert result == VehicleType.TRUCK, f"Failed for {make} {model}"

    def test_extract_year(self):
        """Test year extraction."""
        text = "2023 Toyota Camry"
        year = BaseExtractor.extract_year(text)
        assert year == 2023

        text2 = "Model year: 1999"
        year2 = BaseExtractor.extract_year(text2)
        assert year2 == 1999

    def test_extract_mileage(self):
        """Test mileage extraction."""
        test_cases = [
            ("Mileage: 45,678", 45678),
            ("Mileage: 123456", 123456),
            ("45,678 Miles", 45678),
        ]
        for text, expected in test_cases:
            result = BaseExtractor.extract_mileage(text)
            assert result == expected, f"Failed for: {text}"

    def test_extract_amount(self):
        """Test amount extraction."""
        test_cases = [
            ("Total: $1,234.56", 1234.56),
            ("Price $999", 999.0),
            ("Amount Due: $45,678.90", 45678.90),
        ]
        for text, expected in test_cases:
            result = BaseExtractor.extract_amount(text)
            assert result == expected, f"Failed for: {text}"


class TestIAAExtractor:
    """Tests for IAA extractor."""

    # Realistic IAA document text with multiple indicators
    IAA_SAMPLE = """
    Insurance Auto Auctions, Inc.
    BUYER RECEIPT
    IAAI Branch Location
    Pick-Up Location: Tampa, FL
    StockNo: 123456789
    VIN: 1HGBH41JXMN109186
    Thank you for your business.
    """

    def test_can_extract_positive(self):
        """Test that IAA documents are recognized."""
        extractor = IAAExtractor()

        # Using realistic IAA document text
        assert extractor.can_extract(self.IAA_SAMPLE), "Should recognize IAA sample"

        # Additional test with just key indicators
        key_text = (
            "Insurance Auto Auctions Buyer Receipt IAAI StockNo: 123 Pick-Up Location: FL"
            + " " * 50
        )
        assert extractor.can_extract(key_text), "Should recognize key IAA indicators"

    def test_can_extract_negative(self):
        """Test that non-IAA documents are rejected."""
        extractor = IAAExtractor()

        negative_sample = """
        Copart Sales Receipt/Bill of Sale
        MEMBER: 12345
        PHYSICAL ADDRESS OF LOT
        LOT# 789456
        VIN: 1HGBH41JXMN109186
        """
        assert not extractor.can_extract(negative_sample), "Should not recognize Copart doc"

        manheim_sample = """
        Manheim Auto Auction
        Cox Automotive BILL OF SALE
        VEHICLE RELEASE
        Release ID: MAN12345
        """
        assert not extractor.can_extract(manheim_sample), "Should not recognize Manheim doc"

    def test_source_property(self):
        """Test source property returns IAA."""
        extractor = IAAExtractor()
        assert extractor.source == AuctionSource.IAA


class TestManheimExtractor:
    """Tests for Manheim extractor."""

    # Realistic Manheim document text with multiple indicators
    MANHEIM_SAMPLE = """
    Manheim Auto Auction
    Cox Automotive
    BILL OF SALE
    VEHICLE RELEASE
    Release ID: MAN12345
    Visit Manheim.com for details
    YMMT: 2023 TOYOTA CAMRY
    """

    def test_can_extract_positive(self):
        """Test that Manheim documents are recognized."""
        extractor = ManheimExtractor()

        # Using realistic Manheim document text
        assert extractor.can_extract(self.MANHEIM_SAMPLE), "Should recognize Manheim sample"

        # Offsite release test
        offsite_text = """
        Manheim OFFSITE VEHICLE RELEASE
        Cox Automotive
        Release ID: OFF789
        VEHICLE RELEASE documentation
        """
        assert extractor.can_extract(offsite_text), "Should recognize offsite release"

    def test_can_extract_negative(self):
        """Test that non-Manheim documents are rejected."""
        extractor = ManheimExtractor()

        iaa_sample = """
        Insurance Auto Auctions, Inc.
        BUYER RECEIPT
        IAAI Branch Location
        Pick-Up Location: Tampa, FL
        StockNo: 123456789
        """
        assert not extractor.can_extract(iaa_sample), "Should not recognize IAA doc"

        copart_sample = """
        Copart Sales Receipt/Bill of Sale
        SOLD THROUGH COPART
        MEMBER: 12345
        PHYSICAL ADDRESS OF LOT
        """
        assert not extractor.can_extract(copart_sample), "Should not recognize Copart doc"

    def test_source_property(self):
        """Test source property returns MANHEIM."""
        extractor = ManheimExtractor()
        assert extractor.source == AuctionSource.MANHEIM


class TestCopartExtractor:
    """Tests for Copart extractor."""

    # Realistic Copart document text with multiple indicators
    COPART_SAMPLE = """
    Copart
    Sales Receipt/Bill of Sale
    SOLD THROUGH COPART
    MEMBER: 12345678
    PHYSICAL ADDRESS OF LOT
    LOT# 45678901
    Visit copart.com
    VIN: 1HGBH41JXMN109186
    """

    def test_can_extract_positive(self):
        """Test that Copart documents are recognized."""
        extractor = CopartExtractor()

        # Using realistic Copart document text
        assert extractor.can_extract(self.COPART_SAMPLE), "Should recognize Copart sample"

        # Minimal but sufficient indicators
        key_text = """
        Copart Sales Receipt/Bill of Sale
        SOLD THROUGH COPART
        MEMBER: 12345
        LOT# 789
        """
        assert extractor.can_extract(key_text), "Should recognize key Copart indicators"

    def test_can_extract_negative(self):
        """Test that non-Copart documents are rejected."""
        extractor = CopartExtractor()

        iaa_sample = """
        Insurance Auto Auctions, Inc.
        BUYER RECEIPT
        IAAI Branch Location
        Pick-Up Location: Tampa, FL
        StockNo: 123456789
        """
        assert not extractor.can_extract(iaa_sample), "Should not recognize IAA doc"

        manheim_sample = """
        Manheim Auto Auction
        Cox Automotive
        BILL OF SALE
        VEHICLE RELEASE
        Release ID: MAN12345
        """
        assert not extractor.can_extract(manheim_sample), "Should not recognize Manheim doc"

    def test_source_property(self):
        """Test source property returns COPART."""
        extractor = CopartExtractor()
        assert extractor.source == AuctionSource.COPART


class TestExtractorManager:
    """Tests for ExtractorManager."""

    IAA_SAMPLE = """
    Insurance Auto Auctions, Inc.
    BUYER RECEIPT
    IAAI Branch Location
    Pick-Up Location: Tampa, FL
    StockNo: 123456789
    VIN: 1HGBH41JXMN109186
    """

    MANHEIM_SAMPLE = """
    Manheim Auto Auction
    Cox Automotive
    BILL OF SALE
    VEHICLE RELEASE
    Release ID: MAN12345
    Visit Manheim.com
    """

    COPART_SAMPLE = """
    Copart
    Sales Receipt/Bill of Sale
    SOLD THROUGH COPART
    MEMBER: 12345678
    PHYSICAL ADDRESS OF LOT
    LOT# 45678901
    """

    def test_manager_has_all_extractors(self):
        """Test that manager includes all three extractors."""
        manager = ExtractorManager()

        sources = [e.source for e in manager.extractors]
        assert AuctionSource.IAA in sources
        assert AuctionSource.MANHEIM in sources
        assert AuctionSource.COPART in sources

    def test_get_extractor_for_text_iaa(self):
        """Test extractor selection for IAA text."""
        manager = ExtractorManager()

        extractor = manager.get_extractor_for_text(self.IAA_SAMPLE)
        assert extractor is not None
        assert extractor.source == AuctionSource.IAA

    def test_get_extractor_for_text_manheim(self):
        """Test extractor selection for Manheim text."""
        manager = ExtractorManager()

        extractor = manager.get_extractor_for_text(self.MANHEIM_SAMPLE)
        assert extractor is not None
        assert extractor.source == AuctionSource.MANHEIM

    def test_get_extractor_for_text_copart(self):
        """Test extractor selection for Copart text."""
        manager = ExtractorManager()

        extractor = manager.get_extractor_for_text(self.COPART_SAMPLE)
        assert extractor is not None
        assert extractor.source == AuctionSource.COPART

    def test_get_extractor_for_unknown_text(self):
        """Test extractor selection for unrecognized text."""
        manager = ExtractorManager()

        text = """
        Some random document that doesn't match any auction.
        This is just placeholder text for testing purposes.
        No specific indicators here.
        """
        extractor = manager.get_extractor_for_text(text)
        assert extractor is None
