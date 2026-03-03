"""
Tests for Weather Alerts — NWS route alerts, waypoints, cache.

Tests cover:
  - Waypoint interpolation (count, same-point, endpoint inclusion)
  - Route state estimation from bounding boxes
  - Alert deduplication by NWS alert ID
  - Transport-relevant alert filtering
  - Severity categorization mapping
  - Cache hit skips NWS API calls
  - Cache expiry triggers fresh fetch
  - API endpoints (route-alerts, route-alerts-for-run)
  - Best-value warehouse fallback when no warehouse_id given
  - Invalid ZIP graceful error
"""

import importlib
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def weather_db(tmp_path):
    """Isolated temp DB with warehouse + weather schema."""
    import api.database as db_mod

    db_path = str(tmp_path / "weather_test.db")
    with patch.dict(os.environ, {"DATABASE_PATH": db_path}):
        importlib.reload(db_mod)

        from api.models import init_schema
        from api.routes.warehouses import init_warehouses_schema
        from services.weather_service import init_weather_schema

        init_schema()
        init_warehouses_schema()
        init_weather_schema()

        # Clear YAML-seeded warehouses and insert our test data
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM warehouses")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO warehouses (id, code, name, state, city, zip_code, "
            "latitude, longitude, is_active, is_default, created_at, updated_at) "
            "VALUES (1, 'BOS', 'Boston Warehouse', 'MA', 'Natick', '01760', "
            "42.28, -71.35, 1, 1, ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO warehouses (id, code, name, state, city, zip_code, "
            "latitude, longitude, is_active, is_default, created_at, updated_at) "
            "VALUES (2, 'ATL', 'Atlanta Warehouse', 'GA', 'Atlanta', '30301', "
            "33.75, -84.39, 1, 0, ?, ?)",
            (now, now),
        )
        conn.commit()
        conn.close()

        yield db_path

        importlib.reload(db_mod)


@pytest.fixture
def mock_nws_response():
    """Build a mock NWS GeoJSON response with configurable alerts."""
    def _build(alerts=None):
        if alerts is None:
            alerts = []
        features = []
        for i, a in enumerate(alerts):
            features.append({
                "type": "Feature",
                "properties": {
                    "id": a.get("id", f"urn:oid:2.49.0.1.840.0.{i}"),
                    "event": a.get("event", "Winter Storm Warning"),
                    "severity": a.get("severity", "Severe"),
                    "urgency": a.get("urgency", "Expected"),
                    "headline": a.get("headline", "Winter Storm Warning for test area"),
                    "description": a.get("description", "Heavy snow expected."),
                    "areaDesc": a.get("areaDesc", "Test County, WY"),
                    "onset": a.get("onset", "2026-02-22T18:00:00-07:00"),
                    "expires": a.get("expires", "2026-02-24T12:00:00-07:00"),
                },
            })
        return {"type": "FeatureCollection", "features": features}
    return _build


# ===========================================================================
# WeatherService unit tests
# ===========================================================================

class TestInterpolateWaypoints:
    def test_count(self):
        from services.weather_service import WeatherService
        svc = WeatherService()
        points = svc._interpolate_waypoints(40.0, -74.0, 42.0, -72.0, n=5)
        assert len(points) == 5

    def test_endpoints_included(self):
        from services.weather_service import WeatherService
        svc = WeatherService()
        points = svc._interpolate_waypoints(40.0, -74.0, 42.0, -72.0, n=5)
        # First point = origin
        assert points[0] == (40.0, -74.0)
        # Last point = destination
        assert points[-1] == (42.0, -72.0)

    def test_same_point(self):
        from services.weather_service import WeatherService
        svc = WeatherService()
        points = svc._interpolate_waypoints(40.0, -74.0, 40.0, -74.0, n=3)
        assert len(points) == 3
        for p in points:
            assert p == (40.0, -74.0)

    def test_minimum_two(self):
        from services.weather_service import WeatherService
        svc = WeatherService()
        points = svc._interpolate_waypoints(40.0, -74.0, 42.0, -72.0, n=1)
        assert len(points) >= 2

    def test_midpoint_correct(self):
        from services.weather_service import WeatherService
        svc = WeatherService()
        points = svc._interpolate_waypoints(40.0, -80.0, 42.0, -70.0, n=3)
        mid = points[1]
        assert abs(mid[0] - 41.0) < 0.01
        assert abs(mid[1] - (-75.0)) < 0.01


class TestRouteStates:
    def test_includes_origin_dest(self):
        from services.weather_service import WeatherService
        svc = WeatherService()
        states = svc._get_route_states([(40.0, -74.0)], origin_state="NJ", dest_state="MA")
        assert "NJ" in states
        assert "MA" in states

    def test_intermediate_states(self):
        from services.weather_service import WeatherService
        svc = WeatherService()
        # LA to NYC — should cross multiple states
        waypoints = svc._interpolate_waypoints(34.0, -118.2, 40.7, -74.0, n=5)
        states = svc._get_route_states(waypoints, origin_state="CA", dest_state="NY")
        assert "CA" in states
        assert "NY" in states
        assert len(states) >= 3  # At least origin, dest, and some intermediate

    def test_empty_waypoints_uses_known_states(self):
        from services.weather_service import WeatherService
        svc = WeatherService()
        states = svc._get_route_states([], origin_state="TX", dest_state="FL")
        assert states == ["FL", "TX"]


class TestDeduplicateAlerts:
    def test_removes_duplicates(self):
        from services.weather_service import WeatherService, RouteAlert
        svc = WeatherService()
        alerts = [
            RouteAlert(alert_id="alert-1", event="Winter Storm Warning", severity="warning"),
            RouteAlert(alert_id="alert-1", event="Winter Storm Warning", severity="warning"),
            RouteAlert(alert_id="alert-2", event="Flood Warning", severity="warning"),
        ]
        result = svc._deduplicate_alerts(alerts)
        assert len(result) == 2

    def test_preserves_unique(self):
        from services.weather_service import WeatherService, RouteAlert
        svc = WeatherService()
        alerts = [
            RouteAlert(alert_id="a1", event="Ice Storm Warning"),
            RouteAlert(alert_id="a2", event="Blizzard Warning"),
            RouteAlert(alert_id="a3", event="Tornado Warning"),
        ]
        result = svc._deduplicate_alerts(alerts)
        assert len(result) == 3

    def test_empty_input(self):
        from services.weather_service import WeatherService
        svc = WeatherService()
        assert svc._deduplicate_alerts([]) == []


class TestAlertFiltering:
    def test_transport_relevant_accepted(self, mock_nws_response):
        from services.weather_service import WeatherService
        svc = WeatherService()
        response = mock_nws_response([
            {"event": "Winter Storm Warning", "severity": "Severe"},
            {"event": "Tornado Warning", "severity": "Extreme"},
            {"event": "Dense Fog Advisory", "severity": "Moderate"},
        ])
        alerts = []
        for f in response["features"]:
            a = svc._parse_alert(f)
            if a:
                alerts.append(a)
        assert len(alerts) == 3

    def test_non_transport_filtered(self, mock_nws_response):
        from services.weather_service import WeatherService
        svc = WeatherService()
        response = mock_nws_response([
            {"event": "Heat Advisory", "severity": "Minor"},
            {"event": "Air Quality Alert", "severity": "Moderate"},
            {"event": "Tsunami Warning", "severity": "Extreme"},
        ])
        alerts = []
        for f in response["features"]:
            a = svc._parse_alert(f)
            if a:
                alerts.append(a)
        assert len(alerts) == 0

    def test_mixed_filtering(self, mock_nws_response):
        from services.weather_service import WeatherService
        svc = WeatherService()
        response = mock_nws_response([
            {"event": "Blizzard Warning", "severity": "Extreme"},
            {"event": "Heat Advisory", "severity": "Minor"},
            {"event": "Flood Warning", "severity": "Severe"},
        ])
        alerts = []
        for f in response["features"]:
            a = svc._parse_alert(f)
            if a:
                alerts.append(a)
        assert len(alerts) == 2
        events = {a.event for a in alerts}
        assert "Blizzard Warning" in events
        assert "Flood Warning" in events


class TestSeverityCategorization:
    def test_severity_mapping(self):
        from services.weather_service import SEVERITY_MAP
        assert SEVERITY_MAP["Extreme"] == "critical"
        assert SEVERITY_MAP["Severe"] == "warning"
        assert SEVERITY_MAP["Moderate"] == "advisory"
        assert SEVERITY_MAP["Minor"] == "info"
        assert SEVERITY_MAP["Unknown"] == "info"

    def test_parsed_severity(self, mock_nws_response):
        from services.weather_service import WeatherService
        svc = WeatherService()
        response = mock_nws_response([
            {"event": "Tornado Warning", "severity": "Extreme"},
        ])
        alert = svc._parse_alert(response["features"][0])
        assert alert.severity == "critical"
        assert alert.nws_severity == "Extreme"


class TestCacheHit:
    def test_cache_hit_skips_nws(self):
        from services.weather_service import WeatherService, init_weather_schema, RouteAlertsResult, RouteAlert
        import json as json_mod
        from api.database import get_connection

        init_weather_schema()

        # Pre-populate cache (including summary_json so cache is valid)
        alert_data = [{"alert_id": "cached-1", "severity": "warning", "nws_severity": "Severe",
                       "event": "Winter Storm Warning", "headline": "Cached alert",
                       "description": "From cache", "area": "WY", "onset": "", "expires": "",
                       "urgency": "Expected", "waypoint_lat": None, "waypoint_lon": None, "source": "state"}]
        summary_data = {"ai_summary": "Cached: Winter Storm Warning along route.",
                        "risk_level": "medium", "optimal_pickup_suggestion": None,
                        "recommended_pickup_date": None, "recommendation_reason": None, "scenarios": []}
        now_utc = datetime.now(timezone.utc)
        expires = (now_utc + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO weather_cache (cache_key, alerts_json, route_states, summary_json, checked_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("route:75201:1", json_mod.dumps(alert_data), json_mod.dumps(["TX", "MA"]),
                 json_mod.dumps(summary_data),
                 now_utc.strftime("%Y-%m-%d %H:%M:%S"), expires),
            )
            conn.commit()

        # Mock the HTTP client to prove it's NOT called
        mock_client = MagicMock()
        svc = WeatherService(http_client=mock_client)

        result = svc.get_route_alerts(
            32.8, -96.8, 42.3, -71.4,
            origin_state="TX", dest_state="MA",
            cache_key="route:75201:1",
        )

        assert result.cached is True
        assert len(result.alerts) == 1
        assert result.alerts[0].event == "Winter Storm Warning"
        mock_client.get.assert_not_called()

    def test_cache_expiry_triggers_fetch(self):
        from services.weather_service import WeatherService, init_weather_schema
        import json as json_mod
        from api.database import get_connection

        init_weather_schema()

        # Expired cache entry
        expired = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO weather_cache (cache_key, alerts_json, route_states, checked_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("route:75201:2", "[]", "[]",
                 expired, expired),
            )
            conn.commit()

        # Mock HTTP client that returns empty results
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": []}

        mock_client = MagicMock()
        mock_client.get.return_value = mock_response

        svc = WeatherService(http_client=mock_client)
        result = svc.get_route_alerts(
            32.8, -96.8, 33.75, -84.39,
            origin_state="TX", dest_state="GA",
            cache_key="route:75201:2",
        )

        assert result.cached is False
        # Should have made NWS API calls (waypoints + states)
        assert mock_client.get.call_count > 0


# ===========================================================================
# API endpoint tests
# ===========================================================================

class TestWeatherAPI:
    def _get_client(self):
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_route_alerts_endpoint(self):
        """GET /api/weather/route-alerts returns valid response."""
        client = self._get_client()

        # Mock NWS calls
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": []}

        with patch("services.weather_service.WeatherService._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            resp = client.get("/api/weather/route-alerts?origin_zip=75201&warehouse_id=1")

        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert "route_states" in data
        assert "waypoints_checked" in data
        assert "cached" in data
        assert isinstance(data["alerts"], list)
        assert isinstance(data["route_states"], list)

    def test_route_alerts_invalid_zip(self):
        """Invalid ZIP returns 400."""
        client = self._get_client()
        resp = client.get("/api/weather/route-alerts?origin_zip=ZZZZZ&warehouse_id=1")
        assert resp.status_code == 400

    def test_route_alerts_missing_warehouse(self):
        """Non-existent warehouse returns 404."""
        client = self._get_client()
        resp = client.get("/api/weather/route-alerts?origin_zip=75201&warehouse_id=999")
        assert resp.status_code == 404

    def test_route_alerts_for_run(self):
        """GET /api/weather/route-alerts-for-run/{run_id} works with extraction run."""
        client = self._get_client()

        # Seed an extraction run (with parent document and auction_type for FK)
        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        outputs = json.dumps({"pickup_zip": "75201", "pickup_state": "TX", "pickup_city": "Dallas"})
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO auction_types (id, name, code, is_base) "
                "VALUES (1, 'Copart', 'COPART', 1)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO documents (id, uuid, auction_type_id, filename, file_path, dataset_split) "
                "VALUES (1, 'weather-doc-1', 1, 'test.pdf', '/tmp/test.pdf', 'train')"
            )
            conn.execute(
                "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, status, outputs_json, created_at) "
                "VALUES (1, 'test-uuid-1', 1, 1, 'needs_review', ?, ?)",
                (outputs, now),
            )
            conn.commit()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": []}

        with patch("services.weather_service.WeatherService._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            resp = client.get("/api/weather/route-alerts-for-run/1?warehouse_id=1")

        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert "TX" in data["route_states"]
        assert "MA" in data["route_states"]

    def test_route_alerts_for_run_no_warehouse_uses_default(self):
        """When no warehouse_id given, uses default warehouse."""
        client = self._get_client()

        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        outputs = json.dumps({"pickup_zip": "30301", "pickup_state": "GA"})
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO auction_types (id, name, code, is_base) "
                "VALUES (1, 'Copart', 'COPART', 1)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO documents (id, uuid, auction_type_id, filename, file_path, dataset_split) "
                "VALUES (2, 'weather-doc-2', 1, 'test2.pdf', '/tmp/test2.pdf', 'train')"
            )
            conn.execute(
                "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, status, outputs_json, created_at) "
                "VALUES (2, 'test-uuid-2', 2, 1, 'needs_review', ?, ?)",
                (outputs, now),
            )
            conn.commit()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": []}

        with patch("services.weather_service.WeatherService._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            # No warehouse_id — should use default (BOS, id=1)
            resp = client.get("/api/weather/route-alerts-for-run/2")

        assert resp.status_code == 200
        data = resp.json()
        assert "MA" in data["route_states"]  # Default warehouse is in MA

    def test_route_alerts_for_run_not_found(self):
        """Non-existent run returns 404."""
        client = self._get_client()
        resp = client.get("/api/weather/route-alerts-for-run/999")
        assert resp.status_code == 404

    def test_route_alerts_for_run_no_pickup_zip(self):
        """Run without pickup ZIP returns 400."""
        client = self._get_client()

        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        outputs = json.dumps({"pickup_city": "Dallas"})  # No pickup_zip
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO auction_types (id, name, code, is_base) "
                "VALUES (1, 'Copart', 'COPART', 1)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO documents (id, uuid, auction_type_id, filename, file_path, dataset_split) "
                "VALUES (3, 'weather-doc-3', 1, 'test3.pdf', '/tmp/test3.pdf', 'train')"
            )
            conn.execute(
                "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, status, outputs_json, created_at) "
                "VALUES (3, 'test-uuid-3', 3, 1, 'needs_review', ?, ?)",
                (outputs, now),
            )
            conn.commit()

        resp = client.get("/api/weather/route-alerts-for-run/3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alerts"] == []
        assert "not available" in (data.get("ai_summary") or "").lower()

    def test_response_shape(self):
        """Verify full response shape matches RouteAlertsResponse schema."""
        client = self._get_client()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "features": [{
                "type": "Feature",
                "properties": {
                    "id": "test-alert-1",
                    "event": "Winter Storm Warning",
                    "severity": "Severe",
                    "urgency": "Expected",
                    "headline": "Winter Storm Warning",
                    "description": "Heavy snow expected.",
                    "areaDesc": "Test County, MA",
                    "onset": "2026-02-22T18:00:00-05:00",
                    "expires": "2026-02-24T12:00:00-05:00",
                },
            }],
        }

        with patch("services.weather_service.WeatherService._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_get_client.return_value = mock_client

            resp = client.get("/api/weather/route-alerts?origin_zip=75201&warehouse_id=1")

        assert resp.status_code == 200
        data = resp.json()

        # Verify all expected top-level keys
        assert set(data.keys()) == {
            "alerts", "route_states", "clear_states", "alert_states",
            "waypoints_checked", "cached", "checked_at",
            "ai_summary", "risk_level", "optimal_pickup_suggestion",
            "recommended_pickup_date", "recommendation_reason", "scenarios",
            "transit", "warehouse_used",
        }

        # If alerts present, verify alert shape
        if data["alerts"]:
            alert = data["alerts"][0]
            expected_keys = {
                "alert_id", "severity", "nws_severity", "event", "headline",
                "description", "area", "onset", "expires", "urgency",
                "waypoint_lat", "waypoint_lon", "source",
            }
            assert set(alert.keys()) == expected_keys
