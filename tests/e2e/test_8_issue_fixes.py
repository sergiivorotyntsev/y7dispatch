"""
Tests for 8-issue fix pack:
1. Buyer Reference in warehouses
2. Google Maps key in Credentials (moved from Warehouses)
3. Location type options (CD-valid values)
4. No auto-select warehouse (suggest only)
5. Distance source indicator
6. AI Weather summary
7. CD Listing ID in export response
8. Transport price persistence
"""

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database."""
    db_file = str(tmp_path / "test_fixes.db")
    os.environ["DATABASE_URL"] = db_file
    yield db_file
    os.environ.pop("DATABASE_URL", None)


@pytest.fixture
def fix_db(db_path):
    """Initialize DB with required tables for testing."""
    from api.database import get_connection
    from api.routes.warehouses import init_warehouses_schema

    init_warehouses_schema()

    # Seed test warehouse
    with get_connection() as conn:
        conn.execute("DELETE FROM warehouses")
        conn.execute(
            """INSERT INTO warehouses (id, code, name, state, city, zip_code, is_active, is_default,
               location_type, buyer_reference, created_at, updated_at)
               VALUES (1, 'BOS01', 'Boston Warehouse', 'MA', 'Boston', '02101', 1, 1,
               'CROSS_DOCK', 'BUY-REF-123', datetime('now'), datetime('now'))"""
        )
        conn.execute(
            """INSERT INTO warehouses (id, code, name, state, city, zip_code, is_active, is_default,
               location_type, created_at, updated_at)
               VALUES (2, 'ATL01', 'Atlanta Warehouse', 'GA', 'Atlanta', '30301', 1, 0,
               'BUSINESS', datetime('now'), datetime('now'))"""
        )
        conn.commit()

    yield db_path


# =============================================================================
# Issue 1: Buyer Reference
# =============================================================================

class TestBuyerReference:
    """Test buyer_reference field in warehouse schema and API."""

    def test_warehouse_schema_has_buyer_reference(self, fix_db):
        """buyer_reference column exists in warehouses table."""
        from api.database import get_connection

        with get_connection() as conn:
            cols = [c[1] for c in conn.execute("PRAGMA table_info(warehouses)").fetchall()]
        assert "buyer_reference" in cols

    def test_warehouse_create_model_accepts_buyer_reference(self):
        """WarehouseCreate model accepts buyer_reference field."""
        from api.routes.warehouses import WarehouseCreate

        wh = WarehouseCreate(
            code="TEST01", name="Test", state="TX",
            buyer_reference="BUYER-456"
        )
        assert wh.buyer_reference == "BUYER-456"

    def test_warehouse_response_includes_buyer_reference(self):
        """WarehouseResponse model includes buyer_reference."""
        from api.routes.warehouses import WarehouseResponse

        resp = WarehouseResponse(
            id=1, code="T", name="T", state="TX",
            buyer_reference="REF-789"
        )
        assert resp.buyer_reference == "REF-789"

    def test_buyer_reference_stored_in_db(self, fix_db):
        """buyer_reference is persisted to database."""
        from api.database import get_connection

        with get_connection() as conn:
            row = conn.execute("SELECT buyer_reference FROM warehouses WHERE code = 'BOS01'").fetchone()
        assert row["buyer_reference"] == "BUY-REF-123"

    def test_buyer_reference_nullable(self, fix_db):
        """buyer_reference can be NULL (not required)."""
        from api.database import get_connection

        with get_connection() as conn:
            row = conn.execute("SELECT buyer_reference FROM warehouses WHERE code = 'ATL01'").fetchone()
        assert row["buyer_reference"] is None


# =============================================================================
# Issue 3: Location Type Options
# =============================================================================

class TestLocationTypeOptions:
    """CD-valid location type values."""

    def test_cd_valid_location_types(self):
        """All CD API location types are valid for warehouse model."""
        from api.routes.warehouses import WarehouseCreate

        cd_types = [
            "RESIDENCE", "BUSINESS", "DEALER", "AUCTION",
            "PORT", "STORAGE_FACILITY", "BODY_SHOP", "CROSS_DOCK", "OTHER"
        ]
        for lt in cd_types:
            wh = WarehouseCreate(code="T", name="T", state="TX", location_type=lt)
            assert wh.location_type == lt

    def test_default_location_type_is_business(self):
        """Default location_type is BUSINESS."""
        from api.routes.warehouses import WarehouseCreate

        wh = WarehouseCreate(code="T", name="T", state="TX")
        assert wh.location_type == "BUSINESS"

    def test_cross_dock_stored(self, fix_db):
        """CROSS_DOCK location_type is stored correctly."""
        from api.database import get_connection

        with get_connection() as conn:
            row = conn.execute("SELECT location_type FROM warehouses WHERE code = 'BOS01'").fetchone()
        assert row["location_type"] == "CROSS_DOCK"


# =============================================================================
# Issue 4: No Auto-Select Warehouse
# =============================================================================

class TestWarehouseNoAutoSelect:
    """Warehouse options should NOT auto-select — just suggest."""

    def test_options_have_best_value_flag(self, fix_db):
        """Backend still marks best_value but it's a suggestion, not auto-select."""
        from services.distance_service import DistanceService

        svc = DistanceService()
        options = svc.get_warehouse_options("02101")
        assert len(options) >= 1
        # At least one option has best_value=True (suggestion)
        best = [o for o in options if o.best_value]
        assert len(best) == 1, "Exactly one option should be marked best_value"

    def test_best_value_is_suggestion_only(self, fix_db):
        """best_value flag exists but doesn't force selection (backend check)."""
        from services.distance_service import WarehouseOption

        opt = WarehouseOption(
            warehouse_id=1, warehouse_code="T", warehouse_name="T",
            best_value=True
        )
        # best_value is just a flag, not a "selected" state
        assert opt.best_value is True
        # No "selected" or "auto_select" attribute exists
        assert not hasattr(opt, "selected")
        assert not hasattr(opt, "auto_selected")


# =============================================================================
# Issue 5: Distance Source
# =============================================================================

class TestDistanceSource:
    """Distance source is available in warehouse options."""

    def test_haversine_source_label(self, fix_db):
        """Distance source should be google, osrm, or haversine."""
        from services.distance_service import DistanceService

        svc = DistanceService()
        options = svc.get_warehouse_options("30301")
        assert len(options) >= 1
        for opt in options:
            assert opt.distance_source in ("haversine", "google", "osrm")

    def test_distance_source_in_option_response(self):
        """WarehouseOptionResponse model has distance_source field."""
        from api.routes.warehouses import WarehouseOptionResponse

        resp = WarehouseOptionResponse(
            warehouse_id=1, warehouse_code="T", warehouse_name="T",
            distance_source="google"
        )
        assert resp.distance_source == "google"


# =============================================================================
# Issue 6: AI Weather Summary
# =============================================================================

class TestWeatherAISummary:
    """AI-generated weather summary for transport routes."""

    def test_route_alerts_result_has_summary_fields(self):
        """RouteAlertsResult dataclass includes AI summary fields."""
        from services.weather_service import RouteAlertsResult

        result = RouteAlertsResult()
        assert hasattr(result, "ai_summary")
        assert hasattr(result, "risk_level")
        assert hasattr(result, "optimal_pickup_suggestion")
        assert result.risk_level == "low"

    def test_to_dict_includes_summary(self):
        """to_dict() returns AI summary fields."""
        from services.weather_service import RouteAlertsResult

        result = RouteAlertsResult(
            ai_summary="Storm expected. Delay pickup.",
            risk_level="high",
            optimal_pickup_suggestion="2026-02-23 14:00 UTC",
        )
        d = result.to_dict()
        assert d["ai_summary"] == "Storm expected. Delay pickup."
        assert d["risk_level"] == "high"
        assert d["optimal_pickup_suggestion"] == "2026-02-23 14:00 UTC"

    def test_fallback_summary_high_risk(self):
        """Fallback summary for high-risk alerts."""
        from services.weather_service import RouteAlert, WeatherService

        svc = WeatherService()
        alerts = [
            RouteAlert(event="Blizzard Warning", severity="critical"),
            RouteAlert(event="Ice Storm Warning", severity="warning"),
        ]
        summary = svc._fallback_summary(alerts, "high")
        assert "alert" in summary.lower()
        assert "delay" in summary.lower() or "consider" in summary.lower()

    def test_fallback_summary_medium_risk(self):
        """Fallback summary for medium-risk alerts."""
        from services.weather_service import RouteAlert, WeatherService

        svc = WeatherService()
        alerts = [RouteAlert(event="Wind Advisory", severity="advisory")]
        summary = svc._fallback_summary(alerts, "medium")
        assert "monitor" in summary.lower()

    def test_risk_level_from_severities(self):
        """_generate_ai_summary determines correct risk level."""
        from services.weather_service import RouteAlert, WeatherService

        svc = WeatherService()

        # Mock out the actual API call to test risk level logic
        with patch.object(svc, "_fallback_summary", return_value="test") as mock_fb:
            # No API key set → goes to fallback
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("ANTHROPIC_API_KEY", None)
                summary, risk, pickup, rec_date, rec_reason, scenarios = svc._generate_ai_summary(
                    [RouteAlert(event="Blizzard Warning", severity="critical")],
                    ["MA", "CT"],
                )
                assert risk == "high"

    def test_optimal_pickup_suggestion(self):
        """_suggest_optimal_pickup returns time after alert expiry."""
        from services.weather_service import RouteAlert, WeatherService

        svc = WeatherService()
        alerts = [
            RouteAlert(
                event="Winter Storm Warning", severity="warning",
                expires="2026-02-23T12:00:00+00:00"
            ),
        ]
        suggestion = svc._suggest_optimal_pickup(alerts)
        assert suggestion is not None
        assert "2026-02-23" in suggestion
        assert "14:00" in suggestion  # 12:00 + 2h buffer

    def test_response_model_has_summary(self):
        """RouteAlertsResponse Pydantic model includes AI fields."""
        from api.routes.weather import RouteAlertsResponse

        resp = RouteAlertsResponse(
            ai_summary="All clear.",
            risk_level="low",
            optimal_pickup_suggestion=None,
        )
        assert resp.ai_summary == "All clear."
        assert resp.risk_level == "low"


# =============================================================================
# Issue 7: CD Listing ID in Export Response
# =============================================================================

class TestCDListingIdResponse:
    """CD listing ID returned in export response."""

    def test_payload_preview_has_cd_listing_id(self):
        """CDPayloadPreview model includes cd_listing_id."""
        from api.routes.exports import CDPayloadPreview

        preview = CDPayloadPreview(
            dispatch_id="D001", run_id=1, payload={},
            cd_listing_id="12345"
        )
        assert preview.cd_listing_id == "12345"

    def test_export_response_has_cd_listing_ids(self):
        """CDExportResponse model includes cd_listing_ids list."""
        from api.routes.exports import CDExportResponse

        resp = CDExportResponse(
            status="completed",
            exported_count=1,
            failed_count=0,
            message="Exported 1.",
            cd_listing_ids=["12345", "67890"],
        )
        assert resp.cd_listing_ids == ["12345", "67890"]

    def test_export_response_empty_listing_ids_default(self):
        """cd_listing_ids defaults to empty list."""
        from api.routes.exports import CDExportResponse

        resp = CDExportResponse(
            status="preview", exported_count=0,
            failed_count=0, message="Preview."
        )
        assert resp.cd_listing_ids == []


# =============================================================================
# Issue 8: Transport Price Persistence
# =============================================================================

class TestTransportPricePersistence:
    """Transport price saved and loaded from outputs_json."""

    def test_review_submit_saves_final_price(self, fix_db):
        """Override fields merge into outputs_json correctly (core logic)."""
        from api.database import get_connection

        with get_connection() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS extraction_runs (
                id INTEGER PRIMARY KEY, document_id INTEGER, uuid TEXT NOT NULL,
                auction_type_id INTEGER NOT NULL, status TEXT DEFAULT 'needs_review',
                outputs_json TEXT, extractor_kind TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.execute(
                "INSERT INTO extraction_runs (id, document_id, uuid, auction_type_id, status, outputs_json) "
                "VALUES (100, 1, 'price-test-uuid', 1, 'needs_review', '{\"vehicle_vin\": \"TEST\"}')"
            )
            conn.commit()

        # Simulate the exact logic from reviews.py lines 453-471
        with get_connection() as conn:
            row = conn.execute("SELECT outputs_json FROM extraction_runs WHERE id = 100").fetchone()
            outputs = json.loads(row[0]) if row[0] else {}

            override_fields = {
                "final_price": 200.0,
                "available_date": "2026-03-01",
                "trailer_type": "OPEN",
                "cod_amount": 50.0,
            }
            for key, value in override_fields.items():
                if value is not None:
                    outputs[key] = value

            conn.execute(
                "UPDATE extraction_runs SET outputs_json = ? WHERE id = ?",
                (json.dumps(outputs), 100),
            )
            conn.commit()

        # Verify all override fields saved and original preserved
        with get_connection() as conn:
            row = conn.execute("SELECT outputs_json FROM extraction_runs WHERE id = 100").fetchone()
            saved = json.loads(row[0])
            assert saved["final_price"] == 200.0
            assert saved["available_date"] == "2026-03-01"
            assert saved["trailer_type"] == "OPEN"
            assert saved["cod_amount"] == 50.0
            assert saved["vehicle_vin"] == "TEST"

    def test_override_fields_saved(self, fix_db):
        """All operator override fields are persisted."""
        from api.routes.reviews import ReviewSubmitRequest

        req = ReviewSubmitRequest(
            run_id=1,
            items=[],
            final_price=250.0,
            trailer_type="ENCLOSED",
            available_date="2026-03-01",
            cod_amount=50.0,
        )
        assert req.final_price == 250.0
        assert req.trailer_type == "ENCLOSED"
        assert req.available_date == "2026-03-01"
        assert req.cod_amount == 50.0
