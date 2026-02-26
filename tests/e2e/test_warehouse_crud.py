"""
Warehouse CRUD Tests — Settings → Warehouses

Tests:
- No seed data on fresh init (warehouses table empty)
- Create warehouse via API
- List warehouses returns created items
- Update warehouse
- Delete warehouse (hard delete)
- Duplicate code rejection
"""

import importlib
import json
import os

import pytest


@pytest.fixture(autouse=True)
def isolated_warehouse_db(tmp_path):
    """Isolated DB for warehouse CRUD tests using DATABASE_PATH."""
    db_path = str(tmp_path / "test_wh_crud.db")
    old_path = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = db_path

    import api.database
    importlib.reload(api.database)

    # Initialize warehouse schema (no seed data after fix)
    import api.routes.warehouses
    importlib.reload(api.routes.warehouses)
    api.routes.warehouses.init_warehouses_schema()

    yield db_path

    if old_path:
        os.environ["DATABASE_PATH"] = old_path
    else:
        os.environ.pop("DATABASE_PATH", None)
    importlib.reload(api.database)


@pytest.fixture
def client(isolated_warehouse_db):
    """FastAPI TestClient with isolated DB."""
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


class TestNoSeedData:
    """Fresh init must not auto-populate warehouses."""

    def test_empty_on_init(self):
        """Warehouses table should be empty after init (no seed data)."""
        from api.database import get_connection
        with get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM warehouses").fetchone()[0]
        assert count == 0, f"Expected 0 warehouses on fresh init, got {count}"


class TestWarehouseCreate:
    """POST /api/warehouses/ creates a warehouse."""

    def test_create_returns_201(self, client):
        """Create warehouse returns 201 with full response."""
        resp = client.post("/api/warehouses/", content=json.dumps({
            "code": "FL01",
            "name": "Florida Warehouse",
            "state": "FL",
            "city": "Miami",
            "address": "100 Main St",
            "zip_code": "33101",
        }))
        assert resp.status_code == 201
        data = resp.json()
        assert data["code"] == "FL01"
        assert data["name"] == "Florida Warehouse"
        assert data["state"] == "FL"
        assert data["city"] == "Miami"
        assert data["is_active"] is True

    def test_create_persists_to_db(self, client):
        """Created warehouse appears in list."""
        client.post("/api/warehouses/", content=json.dumps({
            "code": "GA01",
            "name": "Georgia Hub",
            "state": "GA",
        }))
        resp = client.get("/api/warehouses/")
        items = resp.json()["items"]
        codes = [i["code"] for i in items]
        assert "GA01" in codes

    def test_create_duplicate_code_rejected(self, client):
        """Duplicate warehouse code returns 400."""
        client.post("/api/warehouses/", content=json.dumps({
            "code": "DUP1",
            "name": "First",
            "state": "TX",
        }))
        resp2 = client.post("/api/warehouses/", content=json.dumps({
            "code": "DUP1",
            "name": "Second",
            "state": "TX",
        }))
        assert resp2.status_code == 400
        assert "already exists" in resp2.json()["detail"]

    def test_create_missing_required_fields(self, client):
        """Missing required field (state) returns 422."""
        resp = client.post("/api/warehouses/", content=json.dumps({
            "code": "XX",
            "name": "No State",
        }))
        assert resp.status_code == 422


class TestWarehouseUpdate:
    """PUT /api/warehouses/{id} updates a warehouse."""

    def test_update_name(self, client):
        """Update warehouse name."""
        resp = client.post("/api/warehouses/", content=json.dumps({
            "code": "UPD1",
            "name": "Original",
            "state": "NJ",
        }))
        wh_id = resp.json()["id"]

        resp2 = client.put(f"/api/warehouses/{wh_id}", content=json.dumps({
            "name": "Updated Name",
        }))
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "Updated Name"
        assert resp2.json()["code"] == "UPD1"  # Code unchanged


class TestWarehouseDelete:
    """DELETE /api/warehouses/{id} removes a warehouse."""

    def test_hard_delete(self, client):
        """Hard delete removes warehouse from DB."""
        resp = client.post("/api/warehouses/", content=json.dumps({
            "code": "DEL1",
            "name": "To Delete",
            "state": "CA",
        }))
        wh_id = resp.json()["id"]

        resp2 = client.delete(f"/api/warehouses/{wh_id}?hard=true")
        assert resp2.status_code == 200

        # Verify gone from list
        resp3 = client.get("/api/warehouses/")
        codes = [i["code"] for i in resp3.json()["items"]]
        assert "DEL1" not in codes


class TestWarehouseList:
    """GET /api/warehouses/ lists warehouses."""

    def test_list_returns_items_and_total(self, client):
        """List response has items array and total count."""
        client.post("/api/warehouses/", content=json.dumps({
            "code": "L1", "name": "One", "state": "FL",
        }))
        client.post("/api/warehouses/", content=json.dumps({
            "code": "L2", "name": "Two", "state": "GA",
        }))
        resp = client.get("/api/warehouses/")
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
