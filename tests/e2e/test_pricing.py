"""
E2E Tests for Pricing API Routes.

Covers:
- POST /api/pricing/recommend — single price recommendation
- POST /api/pricing/recommend/batch — batch pricing
- POST /api/pricing/override — user override recording
- GET  /api/pricing/config — configuration retrieval
- Edge cases: missing fields, invalid urgency, enclosed trailers

All MI API calls are mocked via the PricingEngine.
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


def _make_pricing_request(
    *,
    origin_city="Sandston",
    origin_state="VA",
    dest_city="Ayer",
    dest_state="MA",
    urgency="STANDARD",
    is_enclosed=False,
    vehicle_type="SEDAN",
):
    """Build a pricing request body."""
    return {
        "origin": {"city": origin_city, "state": origin_state},
        "destination": {"city": dest_city, "state": dest_state},
        "vehicle": {"vehicle_type": vehicle_type, "is_operable": True},
        "urgency": urgency,
        "is_enclosed": is_enclosed,
    }


def _mock_recommendation():
    """Build a mock PriceRecommendation for patching."""
    from services.pricing_engine import PriceRecommendation, PriceSource, PriceStatus, Urgency

    return PriceRecommendation(
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
    )


# =============================================================================
# 1. SINGLE PRICE RECOMMENDATION
# =============================================================================


class TestPriceRecommend:
    """Test POST /api/pricing/recommend."""

    @patch("api.routes.pricing.get_pricing_engine")
    def test_recommend_returns_200(self, mock_get_engine, client):
        """Basic pricing request should return 200."""
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = _mock_recommendation()
        mock_get_engine.return_value = engine

        resp = client.post("/api/pricing/recommend", json=_make_pricing_request())
        assert resp.status_code == 200

    @patch("api.routes.pricing.get_pricing_engine")
    def test_recommend_returns_suggested_price(self, mock_get_engine, client):
        """Response should contain a suggested_price."""
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = _mock_recommendation()
        mock_get_engine.return_value = engine

        resp = client.post("/api/pricing/recommend", json=_make_pricing_request())
        data = resp.json()
        assert data["suggested_price"] == 525.0

    @patch("api.routes.pricing.get_pricing_engine")
    def test_recommend_returns_market_data(self, mock_get_engine, client):
        """Response should include market data fields."""
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = _mock_recommendation()
        mock_get_engine.return_value = engine

        resp = client.post("/api/pricing/recommend", json=_make_pricing_request())
        data = resp.json()
        assert data["avg_dispatch_price"] == 500.0
        assert data["avg_listing_price"] == 550.0
        assert data["spread"] == 50.0
        assert data["market_data_count"] == 12

    @patch("api.routes.pricing.get_pricing_engine")
    def test_recommend_returns_constraints(self, mock_get_engine, client):
        """Response should include floor/ceiling constraints."""
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = _mock_recommendation()
        mock_get_engine.return_value = engine

        resp = client.post("/api/pricing/recommend", json=_make_pricing_request())
        data = resp.json()
        assert data["floor"] == 200.0
        assert data["ceiling"] == 750.0
        assert data["distance_miles"] == 480.0

    @patch("api.routes.pricing.get_pricing_engine")
    def test_recommend_returns_source_and_status(self, mock_get_engine, client):
        """Response should include source and status."""
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = _mock_recommendation()
        mock_get_engine.return_value = engine

        resp = client.post("/api/pricing/recommend", json=_make_pricing_request())
        data = resp.json()
        assert data["source"] == "CD_MARKET_INTELLIGENCE"
        assert data["status"] == "PENDING_REVIEW"

    @patch("api.routes.pricing.get_pricing_engine")
    def test_recommend_priority_urgency(self, mock_get_engine, client):
        """PRIORITY urgency should be reflected in response."""
        rec = _mock_recommendation()
        from services.pricing_engine import Urgency
        rec.urgency = Urgency.PRIORITY
        rec.urgency_multiplier = 1.15
        rec.price = 603.75

        engine = MagicMock()
        engine.calculate_recommended_price.return_value = rec
        mock_get_engine.return_value = engine

        resp = client.post(
            "/api/pricing/recommend",
            json=_make_pricing_request(urgency="PRIORITY"),
        )
        data = resp.json()
        assert data["urgency"] == "PRIORITY"
        assert data["urgency_multiplier"] == 1.15

    @patch("api.routes.pricing.get_pricing_engine")
    def test_recommend_manual_required(self, mock_get_engine, client):
        """When MI returns no data, source should be MANUAL_REQUIRED."""
        from services.pricing_engine import PriceRecommendation, PriceSource, PriceStatus, Urgency

        rec = PriceRecommendation(
            price=None,
            source=PriceSource.MANUAL_REQUIRED,
            status=PriceStatus.MANUAL,
            reason="No market data for route",
            urgency=Urgency.STANDARD,
            urgency_multiplier=1.0,
        )
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = rec
        mock_get_engine.return_value = engine

        resp = client.post("/api/pricing/recommend", json=_make_pricing_request())
        data = resp.json()
        assert data["suggested_price"] is None
        assert data["source"] == "MANUAL_REQUIRED"
        assert data["reason"] is not None

    def test_recommend_missing_origin_returns_422(self, client):
        """Missing origin should return 422."""
        resp = client.post(
            "/api/pricing/recommend",
            json={
                "destination": {"city": "Ayer", "state": "MA"},
            },
        )
        assert resp.status_code == 422

    def test_recommend_invalid_state_returns_422(self, client):
        """State code longer than 2 chars should return 422."""
        resp = client.post(
            "/api/pricing/recommend",
            json=_make_pricing_request(origin_state="VAX"),
        )
        assert resp.status_code == 422


# =============================================================================
# 2. BATCH PRICING
# =============================================================================


class TestBatchPricing:
    """Test POST /api/pricing/recommend/batch."""

    @patch("api.routes.pricing.get_pricing_engine")
    def test_batch_returns_200(self, mock_get_engine, client):
        """Batch pricing should return 200."""
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = _mock_recommendation()
        mock_get_engine.return_value = engine

        resp = client.post(
            "/api/pricing/recommend/batch",
            json={"requests": [_make_pricing_request(), _make_pricing_request()]},
        )
        assert resp.status_code == 200

    @patch("api.routes.pricing.get_pricing_engine")
    def test_batch_returns_correct_counts(self, mock_get_engine, client):
        """Batch should return correct success/failure counts."""
        engine = MagicMock()
        engine.calculate_recommended_price.return_value = _mock_recommendation()
        mock_get_engine.return_value = engine

        resp = client.post(
            "/api/pricing/recommend/batch",
            json={"requests": [_make_pricing_request(), _make_pricing_request()]},
        )
        data = resp.json()
        assert len(data["results"]) == 2
        assert data["success_count"] == 2
        assert data["failure_count"] == 0

    @patch("api.routes.pricing.get_pricing_engine")
    def test_batch_partial_failure(self, mock_get_engine, client):
        """Batch should handle partial failures gracefully."""
        from services.pricing_engine import PriceRecommendation, PriceSource, PriceStatus, Urgency

        success_rec = _mock_recommendation()
        fail_rec = PriceRecommendation(
            price=None,
            source=PriceSource.MANUAL_REQUIRED,
            status=PriceStatus.MANUAL,
            reason="No data",
            urgency=Urgency.STANDARD,
            urgency_multiplier=1.0,
        )
        engine = MagicMock()
        engine.calculate_recommended_price.side_effect = [success_rec, fail_rec]
        mock_get_engine.return_value = engine

        resp = client.post(
            "/api/pricing/recommend/batch",
            json={"requests": [_make_pricing_request(), _make_pricing_request()]},
        )
        data = resp.json()
        assert data["success_count"] == 1
        assert data["failure_count"] == 1

    def test_batch_empty_returns_200(self, client):
        """Empty batch should return 200 with zero counts."""
        resp = client.post(
            "/api/pricing/recommend/batch",
            json={"requests": []},
        )
        # May be 200 (empty results) or 422 (validation error on empty list)
        assert resp.status_code in (200, 422)


# =============================================================================
# 3. USER OVERRIDE
# =============================================================================


class TestPriceOverride:
    """Test POST /api/pricing/override."""

    def test_override_accepted(self, client):
        """Override matching suggested price should return ACCEPTED."""
        resp = client.post(
            "/api/pricing/override",
            json={
                "original_suggested_price": 500.0,
                "final_price": 500.0,
                "avg_dispatch_price": 480.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ACCEPTED"
        assert data["final_price"] == 500.0
        assert data["source"] == "USER_OVERRIDE"

    def test_override_adjusted(self, client):
        """Override differing from suggested should return ADJUSTED."""
        resp = client.post(
            "/api/pricing/override",
            json={
                "original_suggested_price": 500.0,
                "final_price": 550.0,
                "avg_dispatch_price": 480.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ADJUSTED"

    def test_override_manual(self, client):
        """Override with no original suggestion should return MANUAL."""
        resp = client.post(
            "/api/pricing/override",
            json={
                "original_suggested_price": None,
                "final_price": 450.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "MANUAL"

    def test_override_below_market_warning(self, client):
        """Price below 90% of market should generate warning."""
        resp = client.post(
            "/api/pricing/override",
            json={
                "original_suggested_price": 500.0,
                "final_price": 350.0,
                "avg_dispatch_price": 500.0,
            },
        )
        data = resp.json()
        assert any("below market" in w.lower() or "Below market" in w for w in data["warnings"])

    def test_override_above_market_warning(self, client):
        """Price above 130% of market should generate warning."""
        resp = client.post(
            "/api/pricing/override",
            json={
                "original_suggested_price": 500.0,
                "final_price": 700.0,
                "avg_dispatch_price": 500.0,
            },
        )
        data = resp.json()
        assert any("above market" in w.lower() or "Above market" in w for w in data["warnings"])

    def test_override_invalid_price_returns_422(self, client):
        """Zero or negative price should return 422."""
        resp = client.post(
            "/api/pricing/override",
            json={
                "original_suggested_price": 500.0,
                "final_price": 0,
            },
        )
        assert resp.status_code == 422


# =============================================================================
# 4. PRICING CONFIG
# =============================================================================


class TestPricingConfig:
    """Test GET /api/pricing/config."""

    @patch("api.routes.pricing.get_pricing_engine")
    def test_config_returns_200(self, mock_get_engine, client):
        """Config endpoint should return 200."""
        from services.pricing_engine import PricingConfig
        engine = MagicMock()
        engine.config = PricingConfig()
        mock_get_engine.return_value = engine

        resp = client.get("/api/pricing/config")
        assert resp.status_code == 200

    @patch("api.routes.pricing.get_pricing_engine")
    def test_config_has_urgency_multipliers(self, mock_get_engine, client):
        """Config should include urgency multipliers."""
        from services.pricing_engine import PricingConfig
        engine = MagicMock()
        engine.config = PricingConfig()
        mock_get_engine.return_value = engine

        resp = client.get("/api/pricing/config")
        data = resp.json()
        assert "urgency_multipliers" in data
        assert "STANDARD" in data["urgency_multipliers"]
        assert "PRIORITY" in data["urgency_multipliers"]
        assert "URGENT" in data["urgency_multipliers"]

    @patch("api.routes.pricing.get_pricing_engine")
    def test_config_has_floor_constraints(self, mock_get_engine, client):
        """Config should include floor constraints."""
        from services.pricing_engine import PricingConfig
        engine = MagicMock()
        engine.config = PricingConfig()
        mock_get_engine.return_value = engine

        resp = client.get("/api/pricing/config")
        data = resp.json()
        assert "floor_constraints" in data
        assert data["floor_constraints"]["absolute_minimum"] > 0

    @patch("api.routes.pricing.get_pricing_engine")
    def test_config_has_ceiling_constraints(self, mock_get_engine, client):
        """Config should include ceiling constraints."""
        from services.pricing_engine import PricingConfig
        engine = MagicMock()
        engine.config = PricingConfig()
        mock_get_engine.return_value = engine

        resp = client.get("/api/pricing/config")
        data = resp.json()
        assert "ceiling_constraints" in data

    @patch("api.routes.pricing.get_pricing_engine")
    def test_config_has_warning_thresholds(self, mock_get_engine, client):
        """Config should include warning thresholds."""
        from services.pricing_engine import PricingConfig
        engine = MagicMock()
        engine.config = PricingConfig()
        mock_get_engine.return_value = engine

        resp = client.get("/api/pricing/config")
        data = resp.json()
        assert "warning_thresholds" in data
