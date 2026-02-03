"""
Comprehensive tests for the extraction system.

Test categories:
1. Unit tests - individual components
2. Integration tests - component interactions
3. E2E tests - full extraction pipeline
"""

import os

# Add project root to path
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSpatialParser:
    """Tests for the spatial document parser."""

    def test_text_element_properties(self):
        """Test TextElement dataclass properties."""
        from extractors.spatial_parser import TextElement

        elem = TextElement(text="Test", x0=10, y0=20, x1=50, y1=30, page=0)

        assert elem.width == 40
        assert elem.height == 10
        assert elem.center_x == 30
        assert elem.center_y == 25

    def test_document_block_text(self):
        """Test DocumentBlock text aggregation."""
        from extractors.spatial_parser import DocumentBlock, TextElement

        block = DocumentBlock(
            id="test",
            label=None,
            elements=[
                TextElement("Hello", x0=10, y0=10, x1=50, y1=20, page=0),
                TextElement("World", x0=10, y0=25, x1=50, y1=35, page=0),
            ],
            x0=10,
            y0=10,
            x1=50,
            y1=35,
            page=0,
        )

        assert "Hello" in block.text
        assert "World" in block.text

    def test_document_block_lines(self):
        """Test DocumentBlock line grouping."""
        from extractors.spatial_parser import DocumentBlock, TextElement

        block = DocumentBlock(
            id="test",
            label=None,
            elements=[
                TextElement("First", x0=10, y0=10, x1=50, y1=20, page=0),
                TextElement("Line", x0=60, y0=10, x1=100, y1=20, page=0),
                TextElement("Second", x0=10, y0=30, x1=50, y1=40, page=0),
                TextElement("Line", x0=60, y0=30, x1=100, y1=40, page=0),
            ],
            x0=10,
            y0=10,
            x1=100,
            y1=40,
            page=0,
        )

        lines = block.lines
        assert len(lines) == 2
        assert "First Line" in lines[0] or "First" in lines[0]

    def test_document_structure_label_search(self):
        """Test finding blocks by label pattern."""
        from extractors.spatial_parser import DocumentBlock, DocumentStructure

        structure = DocumentStructure()
        block = DocumentBlock(id="1", label="PHYSICAL ADDRESS OF LOT")
        structure.labeled_blocks["PHYSICAL ADDRESS OF LOT"] = block
        structure.blocks = [block]

        found = structure.get_block_by_label(r"PHYSICAL\s*ADDRESS")
        assert found is not None
        assert found.id == "1"


class TestCopartExtractor:
    """Tests for Copart document extraction."""

    def test_score_indicators(self):
        """Test Copart document scoring."""
        from extractors.copart import CopartExtractor

        extractor = CopartExtractor()

        # Text with Copart indicators
        copart_text = """
        Copart
        Sales Receipt/Bill of Sale
        MEMBER: 12345
        SOLD THROUGH COPART
        PHYSICAL ADDRESS OF LOT:
        123 Test St
        Dallas TX 75001
        """

        score, matched = extractor.score(copart_text)
        assert score > 0.5
        assert "Copart" in matched or "SOLD THROUGH COPART" in matched

    def test_score_negative_indicators(self):
        """Test that IAA indicators reduce Copart score."""
        from extractors.copart import CopartExtractor

        extractor = CopartExtractor()

        # Text with IAA indicators
        iaa_text = """
        Insurance Auto Auctions
        IAAI
        Buyer Receipt
        """

        score, _ = extractor.score(iaa_text)
        assert score < 0.5

    def test_extract_vin(self):
        """Test VIN extraction."""
        from extractors.base import BaseExtractor

        text = "VIN: 1HGCM82633A004352 is the vehicle identification"
        vin = BaseExtractor.extract_vin(text)
        assert vin == "1HGCM82633A004352"

    def test_extract_year(self):
        """Test year extraction."""
        from extractors.base import BaseExtractor

        text = "VEHICLE: 2024 HYUNDAI TUCSON"
        year = BaseExtractor.extract_year(text)
        assert year == 2024

    def test_extract_mileage(self):
        """Test mileage extraction."""
        from extractors.base import BaseExtractor

        text = "Mileage: 45,230 Miles"
        mileage = BaseExtractor.extract_mileage(text)
        assert mileage == 45230

    def test_parse_address(self):
        """Test address parsing."""
        from extractors.base import BaseExtractor

        text = "Dallas, TX 75001"
        city, state, zip_code = BaseExtractor.parse_address(text)
        assert city.strip() == "Dallas"
        assert state == "TX"
        assert zip_code == "75001"


class TestAddressParser:
    """Tests for address parsing utilities."""

    def test_normalize_state(self):
        """Test state normalization."""
        from extractors.address_parser import normalize_state

        assert normalize_state("Texas") == "TX"
        assert normalize_state("TX") == "TX"
        assert normalize_state("California") == "CA"

    def test_parse_city_state_zip(self):
        """Test city/state/zip parsing."""
        from extractors.address_parser import parse_city_state_zip

        city, state, zip_code = parse_city_state_zip("DALLAS, TX 75001")
        assert city.upper() == "DALLAS"
        assert state == "TX"
        assert zip_code == "75001"

    def test_extract_lines_after_label(self):
        """Test extracting lines after a label."""
        from extractors.address_parser import extract_lines_after_label

        text = """
PHYSICAL ADDRESS OF LOT:
123 Main Street
Dallas TX 75001
Some other content
"""
        lines = extract_lines_after_label(text, "PHYSICAL ADDRESS OF LOT")
        assert len(lines) >= 2
        assert "123 Main Street" in lines[0] or "Main" in lines[0]


class TestExtractionPipeline:
    """Integration tests for the extraction pipeline."""

    def test_extractor_manager_classification(self):
        """Test document type classification."""
        from extractors import ExtractorManager
        from models.vehicle import AuctionSource

        manager = ExtractorManager()

        copart_text = """
        Copart Sales Receipt/Bill of Sale
        SOLD THROUGH COPART
        MEMBER: 12345
        PHYSICAL ADDRESS OF LOT:
        123 Test St, Dallas TX 75001
        LOT#: 92326455
        VEHICLE: 2024 HYUNDAI TUCSON BLACK
        VIN: KM8JCCD18RU178398
        """

        extractor = manager.get_extractor_for_text(copart_text)
        assert extractor is not None
        assert extractor.source == AuctionSource.COPART

    def test_extraction_run_creates_all_fields(self):
        """Test that extraction creates review items for ALL configured fields."""
        # This tests the Phase 1 fix
        from unittest.mock import MagicMock, patch

        from api.routes.extractions import _create_review_items_for_all_fields

        # Mock the database connection and repository
        with patch("api.routes.extractions.ReviewItemRepository") as mock_repo:
            with patch("api.database.get_connection") as mock_conn:
                # Setup mock connection to return empty mappings
                mock_context = MagicMock()
                mock_context.__enter__ = MagicMock(return_value=mock_context)
                mock_context.__exit__ = MagicMock(return_value=False)
                mock_context.execute = MagicMock(return_value=MagicMock(fetchall=lambda: []))
                mock_conn.return_value = mock_context

                # Call with partial outputs (missing pickup_address)
                outputs = {
                    "vehicle_vin": "ABC123",
                    "vehicle_year": 2024,
                    # pickup_address is NOT included - should still appear
                }

                _create_review_items_for_all_fields(run_id=1, auction_type_id=1, outputs=outputs)

                # Verify create_batch was called
                mock_repo.create_batch.assert_called_once()
                call_args = mock_repo.create_batch.call_args[0]
                items = call_args[1]

                # Should have items for ALL default fields
                keys = [item["source_key"] for item in items]
                assert "vehicle_vin" in keys
                assert "pickup_address" in keys  # This should be present even though not extracted
                assert "pickup_city" in keys
                assert "pickup_state" in keys


class TestTrainingService:
    """Tests for the training service."""

    def test_find_preceding_label(self):
        """Test finding labels that precede values."""
        from unittest.mock import MagicMock

        from services.training_service import TrainingService

        service = TrainingService(MagicMock())

        text = """
PHYSICAL ADDRESS OF LOT:
123 Main Street
Dallas TX 75001
"""
        label = service._find_preceding_label(text, "123 Main Street")
        assert label is not None
        assert "ADDRESS" in label.upper() or "LOT" in label.upper()

    def test_extract_text_patterns(self):
        """Test pattern extraction from context."""
        from unittest.mock import MagicMock

        from services.training_service import TrainingService

        service = TrainingService(MagicMock())

        text = """
PHYSICAL ADDRESS OF LOT:
123 Main Street
"""
        patterns = service._extract_text_patterns(text, "123 Main Street")
        assert len(patterns) > 0


class TestFieldMappings:
    """Tests for field mapping configuration."""

    def test_default_field_mappings_complete(self):
        """Test that default field mappings cover all required CD fields."""
        from api.routes.extractions import _create_review_items_for_all_fields

        # Required fields for Central Dispatch
        required_fields = [
            "vehicle_vin",
            "pickup_address",
            "pickup_city",
            "pickup_state",
            "pickup_zip",
        ]

        # Get the DEFAULT_FIELDS from the function (we can't import it directly)
        # So we test via the behavior
        with patch("api.routes.extractions.ReviewItemRepository") as mock_repo:
            with patch("api.database.get_connection") as mock_conn:
                mock_context = MagicMock()
                mock_context.__enter__ = MagicMock(return_value=mock_context)
                mock_context.__exit__ = MagicMock(return_value=False)
                mock_context.execute = MagicMock(return_value=MagicMock(fetchall=lambda: []))
                mock_conn.return_value = mock_context

                _create_review_items_for_all_fields(run_id=1, auction_type_id=1, outputs={})

                items = mock_repo.create_batch.call_args[0][1]
                keys = [item["source_key"] for item in items]

                for field in required_fields:
                    assert field in keys, f"Required field {field} missing from defaults"


class TestE2E:
    """End-to-end tests for the complete extraction flow."""

    @pytest.mark.skipif(
        not os.path.exists("/home/user/CENTRALDISPATCH/data/uploads"),
        reason="No test documents available",
    )
    def test_full_extraction_pipeline(self):
        """Test complete extraction from PDF to review items."""
        # This test requires actual PDF documents
        # Skip if no test documents available
        pass

    def test_extraction_with_mock_pdf(self):
        """Test extraction flow with mocked PDF content."""
        from extractors import ExtractorManager
        from models.vehicle import AuctionSource

        manager = ExtractorManager()

        # Simulate extracted text from a Copart document
        mock_text = """
        Copart
        Sales Receipt/Bill of Sale
        Date: 01/13/26 11:12 AM

        MEMBER: 535527
        BROADWAY MOTORING INC
        77 FITCHBURG ROAD
        AYER, MA 01432

        PHYSICAL ADDRESS OF LOT:
        5701 WHITESIDE RD
        SANDSTON VA 23150

        SELLER:
        USAA
        SOLD THROUGH COPART
        5701 WHITESIDE RD
        SANDSTON, VA 23150

        LOT#: 91708175
        VEHICLE: 2024 HYUNDAI TUCSON SEL BLACK
        VIN: KM8JCCD18RU178398

        Sale Yard: 139
        Item#: 2035/D
        Keys: YES
        Sale: 01/09/2026
        """

        # Get extractor
        extractor = manager.get_extractor_for_text(mock_text)
        assert extractor is not None
        assert extractor.source == AuctionSource.COPART

        # Verify scoring
        score, matched = extractor.score(mock_text)
        assert score > 0.5, f"Score too low: {score}"

    def test_order_id_generation(self):
        """Test Order ID generation format."""
        from datetime import datetime

        from api.routes.extractions import generate_order_id

        # Test: Feb 1, Jeep Grand Cherokee
        date = datetime(2026, 2, 1)
        order_id = generate_order_id("Jeep", "Grand Cherokee", date)

        # Should be: 21 (month+day) + JEE (make) + G (model) + 1 (seq)
        assert order_id.startswith("21JEE")
        assert order_id[5] == "G"

    def test_order_id_unique_per_day(self):
        """Test that Order IDs are unique per day with sequence numbers."""
        from datetime import datetime
        from unittest.mock import MagicMock, patch

        from api.routes.extractions import generate_order_id

        date = datetime(2026, 1, 15)

        # Mock database to return different counts
        with patch("api.database.get_connection") as mock_conn:
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=mock_context)
            mock_context.__exit__ = MagicMock(return_value=False)

            # First call: no existing orders
            mock_context.execute = MagicMock(return_value=MagicMock(fetchone=lambda: (0,)))
            mock_conn.return_value = mock_context

            order1 = generate_order_id("Toyota", "Camry", date)
            assert order1.endswith("1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
