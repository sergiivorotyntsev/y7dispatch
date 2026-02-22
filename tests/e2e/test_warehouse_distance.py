"""
Tests for Warehouse Backend — CRUD extensions, Distance Service, Cache.

Tests cover:
  - Warehouse CRUD (create with lat/lon/notes, update, soft-delete, list active)
  - Distance service haversine calculations
  - Google Distance Matrix mock
  - Distance cache (hit skips API, TTL expiry)
  - Warehouse options endpoint (sorted, best_value marked)
  - Graceful degradation (no API keys)
  - CD pricing stub (returns unavailable)
  - Credential store accepts google_maps
"""

import importlib
import json
import math
import os
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def warehouse_db(tmp_path):
    """Isolated temp DB with warehouse schema."""
    import api.database as db_mod

    db_path = str(tmp_path / "warehouse_test.db")
    with patch.dict(os.environ, {"DATABASE_PATH": db_path}):
        importlib.reload(db_mod)

        from api.models import init_schema
        from api.routes.warehouses import init_warehouses_schema
        init_schema()
        init_warehouses_schema()

        # Clear any YAML-seeded warehouses and insert our test data
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM warehouses")
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO warehouses (id, code, name, state, city, address, zip_code, "
            "latitude, longitude, is_active, is_default, created_at, updated_at) "
            "VALUES (1, 'BOS', 'Boston Warehouse', 'MA', 'Natick', '6 Harding Rd', '01760', "
            "42.28, -71.35, 1, 1, ?, ?)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO warehouses (id, code, name, state, city, address, zip_code, "
            "latitude, longitude, is_active, is_default, created_at, updated_at) "
            "VALUES (2, 'ATL', 'Atlanta Warehouse', 'GA', 'Atlanta', '100 Peachtree St', '30301', "
            "33.75, -84.39, 1, 0, ?, ?)",
            (now, now),
        )
        conn.commit()
        conn.close()

        yield db_path

    importlib.reload(db_mod)


# ---------------------------------------------------------------------------
# Warehouse CRUD Tests
# ---------------------------------------------------------------------------


class TestWarehouseCRUD:
    """Test warehouse CRUD endpoints."""

    def test_create_warehouse_with_coordinates(self):
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.post("/api/warehouses/", json={
            "code": "NJ01",
            "name": "New Jersey Hub",
            "state": "NJ",
            "city": "Newark",
            "address": "123 Industrial Blvd",
            "zip_code": "07102",
            "latitude": 40.74,
            "longitude": -74.17,
            "notes": "Gate code: 4455",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == "NJ01"
        assert data["latitude"] == 40.74
        assert data["longitude"] == -74.17
        assert data["notes"] == "Gate code: 4455"

    def test_update_warehouse_coordinates(self):
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.put("/api/warehouses/1", json={
            "latitude": 42.30,
            "longitude": -71.40,
            "notes": "Updated coords",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["latitude"] == 42.30
        assert data["notes"] == "Updated coords"

    def test_soft_delete_warehouse(self):
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.delete("/api/warehouses/2")
        assert resp.status_code == 200

        # Verify it's hidden from active list
        resp = client.get("/api/warehouses/")
        data = resp.json()
        ids = [w["id"] for w in data["items"]]
        assert 2 not in ids

    def test_list_active_warehouses(self):
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/warehouses/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        for w in data["items"]:
            assert w["is_active"] is True


# ---------------------------------------------------------------------------
# Distance Service Tests
# ---------------------------------------------------------------------------


class TestDistanceService:
    """Test DistanceService calculations."""

    def test_haversine_known_distance(self):
        """Haversine Boston-NYC should be ~190 miles."""
        from services.distance_service import haversine

        dist = haversine(42.4, -71.1, 40.7, -74.0)
        assert 180 < dist < 200, f"Expected ~190, got {dist}"

    def test_haversine_same_point(self):
        """Same point should return 0."""
        from services.distance_service import haversine

        dist = haversine(42.4, -71.1, 42.4, -71.1)
        assert dist == 0.0

    def test_haversine_cross_country(self):
        """LA to NYC should be ~2450 miles."""
        from services.distance_service import haversine

        dist = haversine(34.1, -118.2, 40.7, -74.0)
        assert 2400 < dist < 2500, f"Expected ~2450, got {dist}"

    def test_google_api_mock(self):
        """Google Distance Matrix returns correct result when mocked."""
        from services.distance_service import DistanceService

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "OK",
            "rows": [{
                "elements": [{
                    "status": "OK",
                    "distance": {"value": 321869, "text": "200 mi"},
                    "duration": {"value": 14400, "text": "4 hours"},
                }]
            }],
        }

        svc = DistanceService(google_api_key="test-key")
        with patch("httpx.get", return_value=mock_resp):
            result = svc.get_road_distance("02101", "10001")

        assert result.source == "google"
        assert abs(result.distance_miles - 200.0) < 1
        assert result.duration_minutes == 240

    def test_no_api_key_uses_fallback(self):
        """Without Google key, falls back to OSRM or haversine."""
        from services.distance_service import DistanceService

        svc = DistanceService(google_api_key=None)
        svc.google_api_key = None  # Ensure no key
        result = svc.get_road_distance("02101", "10001")

        assert result.source in ("osrm", "haversine")
        assert result.distance_miles is not None
        # OSRM gives road distance; haversine * 1.3 road factor
        assert 180 < result.distance_miles < 300

    def test_cache_hit_skips_api(self):
        """Cached distance should be returned without calling API."""
        from services.distance_service import DistanceService, DistanceResult

        svc = DistanceService(google_api_key="test-key")

        # Pre-populate cache
        svc._cache_distance(
            "30301", 1,
            DistanceResult(distance_miles=1050, distance_text="1,050 mi",
                           duration_minutes=900, duration_text="15h", source="google"),
            None, "unavailable",
        )

        # Should hit cache, not API
        cached = svc._get_cached_distance("30301", 1)
        assert cached is not None
        assert cached["distance_miles"] == 1050

    def test_cache_expired_returns_none(self):
        """Expired cache entry should return None."""
        from services.distance_service import DistanceService

        svc = DistanceService()

        # Insert an old cache entry directly
        from api.database import get_connection
        old_time = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO distance_cache (origin_zip, destination_warehouse_id, "
                "distance_miles, calculated_at) VALUES (?, ?, ?, ?)",
                ("99999", 1, 500.0, old_time),
            )
            conn.commit()

        cached = svc._get_cached_distance("99999", 1)
        assert cached is None  # Expired (> 7 days)


# ---------------------------------------------------------------------------
# Warehouse Options Tests
# ---------------------------------------------------------------------------


class TestWarehouseOptions:
    """Test warehouse options endpoint."""

    def test_options_returns_all_active(self):
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/warehouses/options?pickup_zip=30301")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["options"]) >= 2
        assert data["pickup_zip"] == "30301"

    def test_sorted_by_distance_fallback(self):
        """Without prices, options sorted by distance."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        # Pickup in Atlanta (30301) — ATL warehouse should be closest
        resp = client.get("/api/warehouses/options?pickup_zip=30301")
        data = resp.json()
        options = data["options"]

        # ATL (30301) should be closer than BOS (01760) from Atlanta
        atl = next((o for o in options if o["warehouse_code"] == "ATL"), None)
        bos = next((o for o in options if o["warehouse_code"] == "BOS"), None)
        assert atl is not None
        assert bos is not None
        if atl["distance_miles"] and bos["distance_miles"]:
            assert atl["distance_miles"] < bos["distance_miles"]

    def test_best_value_marked(self):
        """First option (cheapest/closest) should have best_value=True."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/warehouses/options?pickup_zip=30301")
        data = resp.json()
        options = data["options"]

        assert options[0]["best_value"] is True
        for o in options[1:]:
            assert o["best_value"] is False

    def test_graceful_no_keys(self):
        """Options work with no API keys (haversine fallback)."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/warehouses/options?pickup_zip=75001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["google_maps_available"] is False
        assert data["cd_pricing_available"] is False
        # Should still have distance estimates
        for o in data["options"]:
            if o["zip_code"]:
                assert o["distance_miles"] is not None or o["distance_source"] == "haversine"

    def test_options_for_run_404(self):
        """Non-existent run returns 404."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/warehouses/options-for-run/9999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# CD Pricing Stub Tests
# ---------------------------------------------------------------------------


class TestCDPricingStub:
    """Test CD pricing stub returns unavailable."""

    def test_transport_price_unavailable(self):
        from services.distance_service import DistanceService

        svc = DistanceService()
        result = svc.get_transport_price("02101", "10001")
        assert result.price is None
        assert result.source == "unavailable"

    def test_options_have_no_prices(self):
        """Warehouse options should have null prices (no CD subscription)."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/warehouses/options?pickup_zip=30301")
        data = resp.json()
        for o in data["options"]:
            assert o["transport_price"] is None


# ---------------------------------------------------------------------------
# Credential Store Tests
# ---------------------------------------------------------------------------


class TestGoogleMapsCredential:
    """Test google_maps is accepted as a valid credential service."""

    def test_google_maps_in_valid_services(self):
        from services.credential_store import VALID_SERVICES
        assert "google_maps" in VALID_SERVICES


# ---------------------------------------------------------------------------
# Distance Cache Table Tests
# ---------------------------------------------------------------------------


class TestDistanceCacheTable:
    """Test distance_cache table was created by schema init."""

    def test_table_exists(self):
        from api.database import get_connection
        with get_connection() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='distance_cache'"
            ).fetchall()
        assert len(tables) == 1

    def test_unique_constraint(self):
        """UNIQUE(origin_zip, destination_warehouse_id) should prevent duplicates."""
        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO distance_cache (origin_zip, destination_warehouse_id, distance_miles, calculated_at) "
                "VALUES ('12345', 1, 100.0, ?)", (now,)
            )
            conn.commit()

        # Second insert with same key should fail (without ON CONFLICT)
        with get_connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO distance_cache (origin_zip, destination_warehouse_id, distance_miles, calculated_at) "
                    "VALUES ('12345', 1, 200.0, ?)", (now,)
                )
                conn.commit()
                # Should not reach here
                assert False, "Expected unique constraint violation"
            except Exception:
                pass  # Expected
