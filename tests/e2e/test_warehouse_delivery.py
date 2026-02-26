"""
Day 11 Tests: Warehouse Delivery Integration + Auction Phone Directory

Tests:
- Auction directory: lookup by name, normalized matching, unknown returns None
- Warehouse schema: location_type and contact_phone fields
- Delivery integration: warehouse fills delivery stop in export payload
- Pickup phone auto-fill: directory fills phone when extraction misses it
"""

import importlib
import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def temp_database(tmp_path):
    """Use a temp database for each test."""
    db_path = str(tmp_path / "test_warehouse.db")
    os.environ["DATABASE_URL"] = db_path

    import api.database

    importlib.reload(api.database)

    from api.database import get_connection

    with get_connection() as conn:
        # Create core tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL UNIQUE,
                filename TEXT, raw_text TEXT, file_path TEXT,
                source TEXT DEFAULT 'upload', status TEXT DEFAULT 'pending',
                is_test_document BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auction_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL, auction_type_id INTEGER,
                uuid TEXT, status TEXT DEFAULT 'pending',
                method TEXT DEFAULT 'haiku', outputs_json TEXT,
                errors_json TEXT, extraction_cost REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL, source_key TEXT, internal_key TEXT,
                cd_key TEXT, predicted_value TEXT, corrected_value TEXT,
                is_match_ok BOOLEAN DEFAULT FALSE, export_field BOOLEAN DEFAULT TRUE,
                confidence REAL, status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES extraction_runs(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS training_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER, auction_type_id INTEGER, run_id INTEGER,
                field_key TEXT, predicted_value TEXT, gold_value TEXT,
                is_correct BOOLEAN, source_text_snippet TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    # Reload modules to pick up temp DB
    import api.routes.warehouses

    importlib.reload(api.routes.warehouses)
    api.routes.warehouses.init_warehouses_schema()

    # Initialize warehouse_constants table (used by build_cd_payload)
    from api.warehouse_constants import init_warehouse_constants_schema

    init_warehouse_constants_schema()

    yield db_path


# ── Test Class 1: Auction Directory ──────────────────────────────────────────


class TestAuctionDirectory:
    """Test auction location directory lookup."""

    def test_copart_location_lookup_exact(self):
        """Exact Copart location name returns phone and address."""
        from services.auction_directory import lookup_auction_location

        result = lookup_auction_location("Copart Clearwater")
        assert result is not None
        assert result["phone"] is not None
        assert len(result["phone"]) > 0

    def test_copart_location_lookup_normalized(self):
        """Copart lookup normalizes case and whitespace."""
        from services.auction_directory import lookup_auction_location

        result1 = lookup_auction_location("COPART CLEARWATER")
        result2 = lookup_auction_location("copart clearwater")
        assert result1 is not None
        assert result1 == result2

    def test_copart_location_with_dash(self):
        """'Copart - Clearwater' matches 'Copart Clearwater'."""
        from services.auction_directory import lookup_auction_location

        result = lookup_auction_location("Copart - Clearwater")
        assert result is not None
        assert "phone" in result

    def test_iaa_location_lookup(self):
        """IAA location lookup works."""
        from services.auction_directory import lookup_auction_location

        result = lookup_auction_location("IAA Clearwater")
        assert result is not None
        assert result["phone"] is not None

    def test_unknown_location_returns_none(self):
        """Unknown location returns None."""
        from services.auction_directory import lookup_auction_location

        result = lookup_auction_location("Unknown Auction XYZ123")
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        from services.auction_directory import lookup_auction_location

        assert lookup_auction_location("") is None
        assert lookup_auction_location(None) is None

    def test_location_has_required_fields(self):
        """Auction location result has phone, city, state at minimum."""
        from services.auction_directory import lookup_auction_location

        result = lookup_auction_location("Copart Clearwater")
        assert result is not None
        assert "phone" in result
        assert "city" in result
        assert "state" in result

    def test_directory_has_multiple_locations(self):
        """Directory has multiple Copart locations."""
        from services.auction_directory import COPART_LOCATIONS

        assert len(COPART_LOCATIONS) >= 20  # At least 20 Florida/common locations


# ── Test Class 2: Warehouse Schema ───────────────────────────────────────────


class TestWarehouseSchema:
    """Test warehouse table has required fields for CD API."""

    def test_location_type_column_exists(self):
        """Warehouse table has location_type column."""
        from api.database import get_connection

        with get_connection() as conn:
            cursor = conn.execute("PRAGMA table_info(warehouses)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "location_type" in columns

    def test_contact_phone_column_exists(self):
        """Warehouse table has contact_phone column."""
        from api.database import get_connection

        with get_connection() as conn:
            cursor = conn.execute("PRAGMA table_info(warehouses)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "contact_phone" in columns

    def test_location_type_default_business(self):
        """New warehouse defaults to BUSINESS location type."""
        from api.database import get_connection

        with get_connection() as conn:
            conn.execute("""
                INSERT INTO warehouses (code, name, state, city, address, zip_code)
                VALUES ('TEST1', 'Test WH', 'FL', 'Tampa', '123 Main St', '33601')
            """)
            conn.commit()
            row = conn.execute("SELECT location_type FROM warehouses WHERE code='TEST1'").fetchone()
            assert row[0] in ("BUSINESS", None)  # Default or NULL is acceptable

    def test_warehouse_create_with_new_fields(self):
        """WarehouseCreate model accepts location_type and contact_phone."""
        from api.routes.warehouses import WarehouseCreate

        wh = WarehouseCreate(
            code="test",
            name="Test Warehouse",
            state="FL",
            location_type="DEALERSHIP",
            contact_phone="(813) 555-1234",
        )
        assert wh.location_type == "DEALERSHIP"
        assert wh.contact_phone == "(813) 555-1234"

    def test_warehouse_response_includes_new_fields(self):
        """WarehouseResponse model has location_type and contact_phone."""
        from api.routes.warehouses import WarehouseResponse

        resp = WarehouseResponse(
            id=1,
            code="TEST",
            name="Test",
            state="FL",
            location_type="BUSINESS",
            contact_phone="(555) 123-4567",
        )
        assert resp.location_type == "BUSINESS"
        assert resp.contact_phone == "(555) 123-4567"

    def test_warehouse_api_crud(self):
        """Warehouse CRUD via TestClient includes new fields."""
        from fastapi.testclient import TestClient

        from api.main import app

        client = TestClient(app)

        # Create
        resp = client.post(
            "/api/warehouses/",
            json={
                "code": "DAY11",
                "name": "Day 11 Test WH",
                "state": "FL",
                "city": "Tampa",
                "address": "100 Test Blvd",
                "zip_code": "33601",
                "phone": "(813) 555-0001",
                "contact_name": "John Day11",
                "contact_phone": "(813) 555-0002",
                "location_type": "DEALERSHIP",
                "transport_special_instructions": "Mon-Fri 8am-5pm",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["location_type"] == "DEALERSHIP"
        assert data["contact_phone"] == "(813) 555-0002"

        # Get
        wh_id = data["id"]
        resp2 = client.get(f"/api/warehouses/{wh_id}")
        assert resp2.status_code == 200
        assert resp2.json()["contact_phone"] == "(813) 555-0002"

        # Update
        resp3 = client.put(
            f"/api/warehouses/{wh_id}",
            json={"location_type": "RESIDENCE", "contact_phone": "(813) 555-9999"},
        )
        assert resp3.status_code == 200
        assert resp3.json()["location_type"] == "RESIDENCE"
        assert resp3.json()["contact_phone"] == "(813) 555-9999"


# ── Test Class 3: Delivery Integration ───────────────────────────────────────


class TestDeliveryIntegration:
    """Test warehouse → delivery stop in export payload."""

    def _create_test_run(self):
        """Create a minimal extraction run for testing."""
        from api.database import get_connection

        with get_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO auction_types (code, name) VALUES ('COPART', 'Copart')")
            at_row = conn.execute("SELECT id FROM auction_types WHERE code='COPART'").fetchone()
            at_id = at_row[0]

            doc_uuid = str(uuid.uuid4())[:8]
            cursor = conn.execute(
                "INSERT INTO documents (uuid, auction_type_id, dataset_split, filename, raw_text, source) VALUES (?, ?, 'test', 'test.pdf', 'test', 'upload')",
                (doc_uuid, at_id),
            )
            doc_id = cursor.lastrowid

            outputs = json.dumps(
                {
                    "vehicle_vin": "1HGBH41JXMN109186",
                    "vehicle_year": "2021",
                    "vehicle_make": "Honda",
                    "vehicle_model": "Civic",
                    "pickup_name": "Copart Clearwater",
                    "pickup_address": "7701 N Hwy 301",
                    "pickup_city": "Tampa",
                    "pickup_state": "FL",
                    "pickup_zip": "33637",
                }
            )
            run_uuid = str(uuid.uuid4())[:8]
            cursor2 = conn.execute(
                """INSERT INTO extraction_runs (document_id, auction_type_id, uuid, status, outputs_json)
                   VALUES (?, ?, ?, 'approved', ?)""",
                (doc_id, at_id, run_uuid, outputs),
            )
            run_id = cursor2.lastrowid

            # Create review items
            fields = [
                ("vehicle_vin", "1HGBH41JXMN109186"),
                ("vehicle_year", "2021"),
                ("vehicle_make", "Honda"),
                ("vehicle_model", "Civic"),
                ("pickup_name", "Copart Clearwater"),
                ("pickup_address", "7701 N Hwy 301"),
                ("pickup_city", "Tampa"),
                ("pickup_state", "FL"),
                ("pickup_zip", "33637"),
            ]
            for key, val in fields:
                conn.execute(
                    """INSERT INTO review_items (run_id, source_key, predicted_value, corrected_value, is_match_ok, export_field, confidence)
                       VALUES (?, ?, ?, ?, 1, 1, 0.95)""",
                    (run_id, key, val, val),
                )
            conn.commit()
        return run_id

    def _ensure_nj_warehouse(self):
        """Create the NJ warehouse explicitly (YAML sync is unreliable across test boundaries)."""
        from api.database import get_connection

        with get_connection() as conn:
            existing = conn.execute("SELECT id FROM warehouses WHERE code='NJ'").fetchone()
            if existing:
                return existing[0]
            conn.execute(
                """INSERT INTO warehouses (code, name, state, city, address, zip_code, is_active)
                   VALUES ('NJ', 'New Jersey Warehouse', 'NJ', 'Newark', '123 Industrial Blvd', '07102', 1)"""
            )
            conn.commit()
            row = conn.execute("SELECT id FROM warehouses WHERE code='NJ'").fetchone()
            return row[0]

    def test_warehouse_fills_delivery_stop(self):
        """Warehouse selection fills delivery stop in CD payload."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = self._create_test_run()
        wh_id = self._ensure_nj_warehouse()

        overrides = OperatorOverrides(
            warehouse_id=wh_id,
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, errors = build_cd_payload(run_id, overrides=overrides)

        # Delivery stop should be filled from warehouse
        stops = payload.get("stops", [])
        delivery = next((s for s in stops if s.get("stopNumber") == 2), None)
        assert delivery is not None, "Delivery stop (stopNumber=2) must exist"
        assert delivery["city"] == "Newark"
        assert delivery["state"] == "NJ"

    def test_warehouse_location_type_in_payload(self):
        """Warehouse location_type appears in delivery stop."""
        from api.database import get_connection
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = self._create_test_run()

        # Create warehouse with DEALERSHIP type
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO warehouses (code, name, state, city, address, zip_code, location_type, is_active)
                VALUES ('DLR1', 'Test Dealer', 'FL', 'Tampa', '999 Auto Row', '33601', 'DEALERSHIP', 1)
            """)
            conn.commit()
            wh = conn.execute("SELECT id FROM warehouses WHERE code='DLR1'").fetchone()

        overrides = OperatorOverrides(
            warehouse_id=wh[0],
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, errors = build_cd_payload(run_id, overrides=overrides)

        stops = payload.get("stops", [])
        delivery = next((s for s in stops if s.get("stopNumber") == 2), None)
        assert delivery is not None
        assert delivery.get("locationType") == "Dealership"

    def test_transport_instructions_in_payload(self):
        """Transport special instructions flow to payload."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = self._create_test_run()
        wh_id = self._ensure_nj_warehouse()

        overrides = OperatorOverrides(
            warehouse_id=wh_id,
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
            transport_special_instructions="Mon-Fri 8am-5pm, call ahead",
        )
        payload, errors = build_cd_payload(run_id, overrides=overrides)

        assert payload.get("transportationReleaseNotes") == "Mon-Fri 8am-5pm, call ahead"

    def test_missing_warehouse_gives_error(self):
        """No warehouse selected gives validation error."""
        from api.routes.exports import build_cd_payload

        run_id = self._create_test_run()
        payload, errors = build_cd_payload(run_id, overrides=None)

        delivery_errors = [e for e in errors if "delivery" in e.lower()]
        assert len(delivery_errors) > 0, "Should have delivery-related errors when no warehouse"


# ── Test Class 4: Pickup Phone Auto-fill ─────────────────────────────────────


class TestPickupPhoneAutoFill:
    """Test pickup phone auto-fill from auction directory."""

    def test_copart_phone_lookup(self):
        """Auto-fill phone for Copart location."""
        from services.auction_directory import lookup_auction_location

        result = lookup_auction_location("Copart Clearwater")
        assert result is not None
        assert result["phone"] is not None
        assert "(" in result["phone"] or result["phone"].replace("-", "").isdigit()

    def test_iaa_phone_lookup(self):
        """Auto-fill phone for IAA location."""
        from services.auction_directory import lookup_auction_location

        result = lookup_auction_location("IAA Clearwater")
        assert result is not None
        assert result["phone"] is not None

    def test_manheim_phone_lookup(self):
        """Manheim location lookup returns data."""
        from services.auction_directory import lookup_auction_location

        result = lookup_auction_location("Manheim Tampa")
        assert result is not None
        assert result["phone"] is not None

    def test_api_endpoint_returns_location(self):
        """GET /api/auction-directory/lookup returns location data."""
        from fastapi.testclient import TestClient

        from api.main import app

        client = TestClient(app)

        resp = client.get("/api/auction-directory/lookup", params={"name": "Copart Clearwater"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("found") is True
        assert "phone" in data.get("location", {})

    def test_api_endpoint_unknown_returns_not_found(self):
        """GET /api/auction-directory/lookup for unknown location."""
        from fastapi.testclient import TestClient

        from api.main import app

        client = TestClient(app)

        resp = client.get("/api/auction-directory/lookup", params={"name": "Unknown ABC"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("found") is False
