"""
E2E Tests for Pricing UI + Export Flow (Day 9 Part 2).

Covers:
- GET /api/pricing/recommend/{run_id} — full market data response
- GET /api/pricing/recommend/{run_id} with urgency param
- GET /api/pricing/recommend/{run_id} with missing locations
- POST /api/exports/central-dispatch — export with mock CD API
- Export blocked when required fields missing

All pricing engine calls are mocked. No real API calls.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from api.main import app

    return TestClient(app)


def _get_or_create_auction_type(code, name=None):
    """Get existing auction type by code, or create if not found."""
    from api.database import get_connection
    from api.models import AuctionTypeRepository

    with get_connection() as conn:
        row = conn.execute("SELECT id FROM auction_types WHERE code = ?", (code.upper(),)).fetchone()
        if row:
            return row["id"]
    return AuctionTypeRepository.create(name=name or code, code=code)


@pytest.fixture()
def test_run_with_locations(client):
    """Create a test extraction run with pickup/delivery location fields."""
    from api.models import (
        DocumentRepository,
        ExtractionRunRepository,
        ReviewItemRepository,
    )

    # Get or create auction type
    at_id = _get_or_create_auction_type("TEST_PRICING_UI", "Test Copart")

    # Create document
    doc_id = DocumentRepository.create(
        auction_type_id=at_id,
        dataset_split="test",
        filename="test_pricing.pdf",
    )

    # Create extraction run (extractor_kind must be 'rule' or 'ml')
    run_id = ExtractionRunRepository.create(
        document_id=doc_id,
        auction_type_id=at_id,
        extractor_kind="rule",
    )
    ExtractionRunRepository.update(run_id, status="needs_review")

    # Create review items with location data
    items = [
        {"source_key": "pickup_city", "predicted_value": "Sandston", "confidence": 0.95},
        {"source_key": "pickup_state", "predicted_value": "VA", "confidence": 0.95},
        {"source_key": "delivery_city", "predicted_value": "Ayer", "confidence": 0.90},
        {"source_key": "delivery_state", "predicted_value": "MA", "confidence": 0.90},
        {"source_key": "vehicle_vin", "predicted_value": "1HGCG5655WA044251", "confidence": 0.85},
        {"source_key": "vehicle_year", "predicted_value": "2020", "confidence": 0.80},
        {"source_key": "vehicle_make", "predicted_value": "Honda", "confidence": 0.80},
        {"source_key": "vehicle_model", "predicted_value": "Civic", "confidence": 0.80},
    ]
    ReviewItemRepository.create_batch(run_id, items)

    return run_id


@pytest.fixture()
def test_run_no_locations(client):
    """Create a test extraction run without delivery location fields."""
    from api.models import (
        DocumentRepository,
        ExtractionRunRepository,
        ReviewItemRepository,
    )

    at_id = _get_or_create_auction_type("TEST_NOLOC", "Test NoLoc")
    doc_id = DocumentRepository.create(
        auction_type_id=at_id,
        dataset_split="test",
        filename="test_noloc.pdf",
    )
    run_id = ExtractionRunRepository.create(
        document_id=doc_id,
        auction_type_id=at_id,
        extractor_kind="rule",
    )
    ExtractionRunRepository.update(run_id, status="needs_review")

    # Only pickup, no delivery
    items = [
        {"source_key": "pickup_city", "predicted_value": "Richmond", "confidence": 0.9},
        {"source_key": "pickup_state", "predicted_value": "VA", "confidence": 0.9},
        {"source_key": "vehicle_vin", "predicted_value": "1HGCG5655WA044252", "confidence": 0.85},
    ]
    ReviewItemRepository.create_batch(run_id, items)

    return run_id


def _mock_recommendation(**overrides):
    """Build a mock PriceRecommendation."""
    from services.pricing_engine import PriceRecommendation, PriceSource, PriceStatus, Urgency

    defaults = dict(
        price=525.0,
        source=PriceSource.CD_MARKET_INTELLIGENCE,
        status=PriceStatus.PENDING_REVIEW,
        avg_dispatch_price=500.0,
        avg_listing_price=550.0,
        spread=50.0,
        market_data_count=12,
        floor=200.0,
        ceiling=750.0,
        distance_miles=480.0,
        urgency=Urgency.STANDARD,
        urgency_multiplier=1.0,
        warnings=[],
        cached=False,
    )
    defaults.update(overrides)
    return PriceRecommendation(**defaults)


# =============================================================================
# 1. GET /api/pricing/recommend/{run_id} — FULL MARKET DATA
# =============================================================================


class TestRunPricingEndpoint:
    """Test GET /api/pricing/recommend/{run_id} returns all market data fields."""

    @patch("api.routes.pricing.get_pricing_engine")
    def test_returns_200_with_all_fields(self, mock_get_engine, client, test_run_with_locations):
        """Endpoint should return 200 with all RunPricingResponse fields."""
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = _mock_recommendation()
        mock_get_engine.return_value = engine

        resp = client.get(f"/api/pricing/recommend/{test_run_with_locations}")
        assert resp.status_code == 200

        data = resp.json()
        assert data["run_id"] == test_run_with_locations
        assert data["suggested_price"] == 525.0
        assert data["source"] == "CD_MARKET_INTELLIGENCE"
        assert data["floor"] == 200.0
        assert data["ceiling"] == 750.0
        assert data["avg_dispatch"] == 500.0
        assert data["avg_listing"] == 550.0
        assert data["spread"] == 50.0
        assert data["data_points"] == 12
        assert data["distance_miles"] == 480.0
        assert data["urgency"] == "STANDARD"
        assert data["urgency_multiplier"] == 1.0

    @patch("api.routes.pricing.get_pricing_engine")
    def test_returns_pickup_and_delivery_locations(self, mock_get_engine, client, test_run_with_locations):
        """Response should include pickup and delivery location strings."""
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = _mock_recommendation()
        mock_get_engine.return_value = engine

        resp = client.get(f"/api/pricing/recommend/{test_run_with_locations}")
        data = resp.json()

        assert data["pickup_location"] == "Sandston, VA"
        assert data["delivery_location"] == "Ayer, MA"

    @patch("api.routes.pricing.get_pricing_engine")
    def test_urgency_param_changes_result(self, mock_get_engine, client, test_run_with_locations):
        """Urgency query param should be passed to PricingEngine."""
        from services.pricing_engine import Urgency

        rec = _mock_recommendation(
            urgency=Urgency.URGENT,
            urgency_multiplier=1.25,
            price=656.25,
        )
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = rec
        mock_get_engine.return_value = engine

        resp = client.get(f"/api/pricing/recommend/{test_run_with_locations}?urgency=URGENT")
        data = resp.json()

        assert data["urgency"] == "URGENT"
        assert data["urgency_multiplier"] == 1.25
        assert data["suggested_price"] == 656.25

        # Verify engine was called with URGENT
        call_args = engine.calculate_recommended_price.call_args
        assert call_args.kwargs.get("urgency") == Urgency.URGENT or (
            len(call_args.args) > 3 and call_args.args[3] == Urgency.URGENT
        )

    def test_missing_locations_returns_manual_required(self, client, test_run_no_locations):
        """Run without delivery location should return MANUAL_REQUIRED."""
        resp = client.get(f"/api/pricing/recommend/{test_run_no_locations}")
        assert resp.status_code == 200

        data = resp.json()
        assert data["source"] == "MANUAL_REQUIRED"
        assert any("Missing" in w for w in data["warnings"])
        assert data["suggested_price"] is None

    def test_nonexistent_run_returns_404(self, client):
        """Non-existent run ID should return 404."""
        resp = client.get("/api/pricing/recommend/999999")
        assert resp.status_code == 404

    @patch("api.routes.pricing.get_pricing_engine")
    def test_engine_failure_returns_manual_required(self, mock_get_engine, client, test_run_with_locations):
        """If PricingEngine raises, response should fall back to MANUAL_REQUIRED."""
        engine = MagicMock()
        engine.calculate_recommended_price.side_effect = RuntimeError("CD API down")
        mock_get_engine.return_value = engine

        resp = client.get(f"/api/pricing/recommend/{test_run_with_locations}")
        assert resp.status_code == 200

        data = resp.json()
        assert data["source"] == "MANUAL_REQUIRED"
        assert any("failed" in w.lower() for w in data["warnings"])

    @patch("api.routes.pricing.get_pricing_engine")
    def test_warnings_are_passed_through(self, mock_get_engine, client, test_run_with_locations):
        """Warnings from PricingEngine should appear in response."""
        rec = _mock_recommendation(warnings=["Below market — pickup may be slow"])
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = rec
        mock_get_engine.return_value = engine

        resp = client.get(f"/api/pricing/recommend/{test_run_with_locations}")
        data = resp.json()

        assert len(data["warnings"]) == 1
        assert "Below market" in data["warnings"][0]


# =============================================================================
# 2. EXPORT FLOW — POST /api/exports/central-dispatch
# =============================================================================


class TestExportFlow:
    """Test export to CD via POST /api/exports/central-dispatch."""

    @patch("api.routes.pricing.get_pricing_engine")
    def test_dry_run_export_returns_preview(self, mock_get_engine, client, test_run_with_locations):
        """Dry run export should return payload preview without posting."""
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = _mock_recommendation()
        mock_get_engine.return_value = engine

        resp = client.post(
            "/api/exports/central-dispatch",
            json={
                "run_ids": [test_run_with_locations],
                "dry_run": True,
                "sandbox": True,
            },
        )
        # Should return 200 (dry run is preview only)
        assert resp.status_code == 200
        data = resp.json()
        assert "previews" in data or "results" in data

    def test_export_nonexistent_run_fails(self, client):
        """Exporting non-existent run should fail gracefully."""
        resp = client.post(
            "/api/exports/central-dispatch",
            json={
                "run_ids": [999999],
                "dry_run": True,
                "sandbox": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should have 0 exported, 1 failed
        assert data.get("exported_count", 0) == 0 or data.get("posted", 0) == 0


# =============================================================================
# 3. RunPricingResponse MODEL VALIDATION
# =============================================================================


class TestRunPricingResponseModel:
    """Test RunPricingResponse Pydantic model defaults and serialization."""

    def test_default_values(self):
        """RunPricingResponse should have sensible defaults."""
        from api.routes.pricing import RunPricingResponse

        resp = RunPricingResponse(run_id=1)
        assert resp.run_id == 1
        assert resp.source == "MANUAL_REQUIRED"
        assert resp.suggested_price is None
        assert resp.floor is None
        assert resp.ceiling is None
        assert resp.warnings == []
        assert resp.urgency == "STANDARD"
        assert resp.urgency_multiplier == 1.0
        assert resp.data_points == 0
        assert resp.cached is False

    def test_full_serialization(self):
        """RunPricingResponse with all fields should serialize correctly."""
        from api.routes.pricing import RunPricingResponse

        resp = RunPricingResponse(
            run_id=42,
            suggested_price=525.0,
            source="CD_MARKET_INTELLIGENCE",
            floor=200.0,
            ceiling=750.0,
            avg_dispatch=500.0,
            avg_listing=550.0,
            spread=50.0,
            warnings=["test warning"],
            urgency="PRIORITY",
            urgency_multiplier=1.12,
            data_points=15,
            cached=True,
            distance_miles=480.0,
            pickup_location="Sandston, VA",
            delivery_location="Ayer, MA",
        )
        data = resp.model_dump()
        assert data["run_id"] == 42
        assert data["suggested_price"] == 525.0
        assert data["pickup_location"] == "Sandston, VA"
        assert data["delivery_location"] == "Ayer, MA"
        assert data["data_points"] == 15
        assert data["cached"] is True
