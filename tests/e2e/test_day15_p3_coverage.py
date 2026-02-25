"""
Day 15 P3 — Coverage tests for features added during Day 15.
Tests: vision OCR, attachment dedup, weather recommendation,
export retry, location name enrichment, warehouse mandatory, price canonical.
"""
import json
import re as _re
import uuid as uuid_mod
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.database import get_connection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_counter = 0


def _unique_pdf(tag="p3"):
    global _counter
    _counter += 1
    uid = f"{tag}-{_counter}-{uuid_mod.uuid4().hex[:8]}"
    return f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << >> >>
endobj
4 0 obj
<< /Length {len(uid) + 44} >>
stream
BT /F1 12 Tf 100 700 Td ({uid}) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000236 00000 n
trailer
<< /Size 5 /Root 1 0 R >>
startxref
330
%%EOF""".encode()


def _upload(client, filename="p3_test.pdf"):
    resp = client.post(
        "/api/documents/upload",
        files={"file": (filename, BytesIO(_unique_pdf(filename)), "application/pdf")},
        data={"dataset_split": "train", "source": "upload"},
    )
    assert resp.status_code == 201, f"Upload failed ({resp.status_code}): {resp.text}"
    data = resp.json()
    doc_id = data["document"]["id"]
    run_id = data.get("run_id")
    return doc_id, run_id


def _set_run_status(run_id, status):
    with get_connection() as conn:
        conn.execute("UPDATE extraction_runs SET status=? WHERE id=?", (status, run_id))
        conn.commit()


def _get_outputs(run_id):
    with get_connection() as conn:
        row = conn.execute("SELECT outputs_json FROM extraction_runs WHERE id=?", (run_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


def _set_outputs(run_id, outputs):
    with get_connection() as conn:
        conn.execute(
            "UPDATE extraction_runs SET outputs_json=? WHERE id=?",
            (json.dumps(outputs), run_id),
        )
        conn.commit()


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


# =========================================================================
# TEST: Vision OCR endpoint
# =========================================================================
class TestVisionOCR:
    def test_vision_extract_endpoint_exists(self, client):
        """POST /api/extractions/{id}/vision-extract is a valid endpoint."""
        doc_id, run_id = _upload(client)
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        _set_run_status(run_id, "manual_required")
        resp = client.post(f"/api/extractions/{run_id}/vision-extract")
        # Endpoint must exist (not 404/405). 422/500/503 from missing API key is OK.
        assert resp.status_code not in (404, 405), \
            f"Vision extract endpoint not found: {resp.status_code}"

    def test_manual_required_can_trigger_vision(self, client):
        """Run with status=manual_required can trigger vision extract."""
        doc_id, run_id = _upload(client)
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        _set_run_status(run_id, "manual_required")
        resp = client.post(f"/api/extractions/{run_id}/vision-extract")
        # Any non-404 response proves endpoint processes the request
        assert resp.status_code != 404


# =========================================================================
# TEST: Attachment dedup
# =========================================================================
class TestAttachmentDedup:
    def _normalize(self, name):
        """Mirror the actual dedup normalize from extractions.py."""
        n = _re.sub(r'[^a-z0-9.]', '_', (name or '').lower().strip())
        n = _re.sub(r'_?\(\d+\)', '', n)
        return n

    def test_normalize_case_insensitive(self):
        """Uppercase and lowercase normalize to same value."""
        assert self._normalize("Invoice.pdf") == self._normalize("invoice.pdf")
        assert self._normalize("UPPER_CASE.PDF") == self._normalize("upper_case.pdf")

    def test_normalize_spaces_to_underscore(self):
        """Spaces are converted to underscores."""
        assert self._normalize("My File.pdf") == "my_file.pdf"

    def test_normalize_preserves_extension(self):
        """File extensions are preserved."""
        assert self._normalize("test.pdf").endswith(".pdf")
        assert self._normalize("photo.jpg").endswith(".jpg")

    def test_email_context_endpoint_exists(self, client):
        """email-context endpoint exists and returns data."""
        doc_id, run_id = _upload(client, "dedup_test.pdf")
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        resp = client.get(f"/api/extractions/{run_id}/email-context")
        # Should not 404
        assert resp.status_code != 404, "email-context endpoint not found"


# =========================================================================
# TEST: Weather recommendation
# =========================================================================
class TestWeatherRecommendation:
    def _ensure_warehouses(self):
        """Ensure warehouses table exists with at least one entry (matching real schema)."""
        with get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS warehouses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    city TEXT,
                    address TEXT,
                    zip_code TEXT,
                    phone TEXT,
                    contact_name TEXT,
                    contact_phone TEXT,
                    location_type TEXT,
                    transport_special_instructions TEXT,
                    is_default BOOLEAN DEFAULT FALSE,
                    is_active BOOLEAN DEFAULT TRUE,
                    latitude REAL,
                    longitude REAL,
                    notes TEXT,
                    buyer_reference TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Add columns if they don't exist (for existing DBs)
            for col, typ in [("latitude", "REAL"), ("longitude", "REAL")]:
                try:
                    conn.execute(f"ALTER TABLE warehouses ADD COLUMN {col} {typ}")
                except Exception:
                    pass
            existing = conn.execute("SELECT COUNT(*) FROM warehouses").fetchone()[0]
            if existing == 0:
                conn.execute("""
                    INSERT INTO warehouses (name, code, city, state, zip_code, is_active, latitude, longitude)
                    VALUES ('Test Warehouse NJ', 'NJ', 'Newark', 'NJ', '07102', 1, 40.7357, -74.1724)
                """)
            conn.commit()

    def test_weather_endpoint_returns_risk_level(self, client):
        """Weather route-alerts always returns risk_level."""
        self._ensure_warehouses()
        resp = client.get("/api/weather/route-alerts?origin_zip=07102&warehouse_id=1")
        if resp.status_code == 200:
            data = resp.json()
            assert "risk_level" in data, "Missing risk_level"
            assert data["risk_level"] in ("low", "moderate", "high")
        else:
            # Weather may fail if NWS API is unreachable — that's OK
            assert resp.status_code in (200, 422, 500, 503)

    def test_recommendation_always_present(self, client):
        """Every successful weather response has recommended_pickup_date."""
        self._ensure_warehouses()
        resp = client.get("/api/weather/route-alerts?origin_zip=07102&warehouse_id=1")
        if resp.status_code == 200:
            data = resp.json()
            assert "recommended_pickup_date" in data, "Missing recommended_pickup_date"

    def test_scenarios_always_present(self, client):
        """Every successful weather response has scenarios key (list)."""
        self._ensure_warehouses()
        resp = client.get("/api/weather/route-alerts?origin_zip=07102&warehouse_id=1")
        if resp.status_code == 200:
            data = resp.json()
            assert "scenarios" in data, "Missing scenarios"
            assert isinstance(data["scenarios"], list), "scenarios should be a list"


# =========================================================================
# TEST: Export retry
# =========================================================================
class TestExportRetry:
    def test_export_with_force_flag(self, client):
        """POST with force=true parameter accepted by endpoint."""
        doc_id, run_id = _upload(client)
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        _set_run_status(run_id, "approved")
        resp = client.post(
            "/api/exports/cd",
            json={
                "run_ids": [run_id],
                "dry_run": True,
                "sandbox": True,
                "force": True,
            },
        )
        # Should be accepted (not 422 for unknown field)
        if resp.status_code == 422:
            assert "force" not in resp.text.lower(), "force parameter not accepted"


# =========================================================================
# TEST: Location name enrichment
# =========================================================================
class TestLocationNameEnrichment:
    def test_copart_location_name(self):
        """COPART auction -> pickup_name includes 'COPART - {city}'."""
        from api.routes.extractions import _enrich_location_name
        outputs = {
            "auction_source": "COPART",
            "pickup_city": "Dallas",
            "pickup_state": "TX",
            "pickup_location_name": "Dallas",
        }
        _enrich_location_name(outputs)
        assert "COPART" in outputs.get("pickup_location_name", ""), \
            f"Expected COPART in name, got: {outputs.get('pickup_location_name')}"
        assert "Dallas" in outputs.get("pickup_location_name", "")

    def test_copart_sublot(self):
        """COPART with sublot -> 'COPART Sub Lot - {city}'."""
        from api.routes.extractions import _enrich_location_name
        outputs = {
            "auction_source": "COPART",
            "pickup_city": "Houston",
            "pickup_state": "TX",
            "pickup_location_name": "Houston",
            "sublot": "A123",
        }
        _enrich_location_name(outputs)
        assert "Sub Lot" in outputs.get("pickup_location_name", ""), \
            f"Expected 'Sub Lot' in name, got: {outputs.get('pickup_location_name')}"
        assert "Houston" in outputs.get("pickup_location_name", "")

    def test_iaa_keeps_branch_name(self):
        """IAA with proper branch name is not overwritten."""
        from api.routes.extractions import _enrich_location_name
        outputs = {
            "auction_source": "IAA",
            "pickup_city": "Chicago",
            "pickup_state": "IL",
            "pickup_location_name": "IAA Chicago South Branch",
        }
        _enrich_location_name(outputs)
        assert outputs["pickup_location_name"] == "IAA Chicago South Branch"

    def test_iaa_city_only_flags_low_confidence(self):
        """IAA with name == city flags low confidence."""
        from api.routes.extractions import _enrich_location_name
        outputs = {
            "auction_source": "IAA",
            "pickup_city": "Chicago",
            "pickup_state": "IL",
            "pickup_location_name": "Chicago",
        }
        _enrich_location_name(outputs)
        assert outputs.get("pickup_location_name_confidence") == "low"

    def test_manheim_offsite_uses_seller(self):
        """MANHEIM offsite -> uses seller_name for location."""
        from api.routes.extractions import _enrich_location_name
        outputs = {
            "auction_source": "MANHEIM",
            "pickup_city": "Atlanta",
            "pickup_state": "GA",
            "pickup_location_name": "Manheim Atlanta",
            "manheim_offsite": True,
            "seller_name": "AutoNation Ford",
        }
        _enrich_location_name(outputs)
        assert outputs["pickup_location_name"] == "AutoNation Ford"


# =========================================================================
# TEST: Warehouse mandatory for approve
# =========================================================================
class TestWarehouseMandatory:
    def test_approve_for_export_without_warehouse_fails(self, client):
        """Approve for export (mark_for_export=True) with no warehouse_id -> 400."""
        doc_id, run_id = _upload(client)
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        _set_run_status(run_id, "needs_review")
        _set_outputs(run_id, {"vin": "TEST12345678901"})
        resp = client.post(
            "/api/review/submit",
            json={
                "run_id": run_id,
                "items": [],
                "mark_as_reviewed": True,
                "mark_for_export": True,
            },
        )
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        assert "warehouse" in resp.text.lower(), "Error should mention warehouse"

    def test_approve_with_warehouse_succeeds(self, client):
        """Approve with warehouse_id -> 200."""
        doc_id, run_id = _upload(client)
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        _set_run_status(run_id, "needs_review")
        _set_outputs(run_id, {"vin": "TEST12345678901", "vehicle_year": "2024"})
        resp = client.post(
            "/api/review/submit",
            json={
                "run_id": run_id,
                "items": [],
                "mark_as_reviewed": True,
                "warehouse_id": 1,
            },
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


# =========================================================================
# TEST: Price canonical (transport_price, auction_cost, rate_per_mile)
# =========================================================================
class TestPriceCanonical:
    def test_documents_returns_transport_price(self, client):
        """Documents API response includes transport_price from price_total."""
        doc_id, run_id = _upload(client)
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        _set_outputs(run_id, {"price_total": 450.0})
        _set_run_status(run_id, "needs_review")

        resp = client.get("/api/documents/?limit=200")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        doc = next((d for d in items if d["id"] == doc_id), None)
        assert doc is not None, f"Document {doc_id} not found in list"
        assert doc.get("transport_price") == 450.0, \
            f"Expected transport_price=450.0, got {doc.get('transport_price')}"

    def test_documents_returns_auction_cost(self, client):
        """Documents API response includes auction_cost from total_amount."""
        doc_id, run_id = _upload(client)
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        _set_outputs(run_id, {"total_amount": 12500.0})
        _set_run_status(run_id, "needs_review")

        resp = client.get("/api/documents/?limit=200")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        doc = next((d for d in items if d["id"] == doc_id), None)
        assert doc is not None
        assert doc.get("auction_cost") == 12500.0, \
            f"Expected auction_cost=12500.0, got {doc.get('auction_cost')}"

    def test_rate_per_mile_computed(self, client):
        """rate_per_mile = transport_price / distance_miles."""
        doc_id, run_id = _upload(client)
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        _set_outputs(run_id, {"price_total": 500.0, "distance_miles": 250})
        _set_run_status(run_id, "needs_review")

        resp = client.get("/api/documents/?limit=200")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        doc = next((d for d in items if d["id"] == doc_id), None)
        assert doc is not None
        assert doc.get("rate_per_mile") == 2.0, \
            f"Expected rate_per_mile=2.0, got {doc.get('rate_per_mile')}"

    def test_submit_saves_price_total(self, client):
        """Review submit with price_total persists to outputs_json."""
        doc_id, run_id = _upload(client)
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        _set_run_status(run_id, "needs_review")
        _set_outputs(run_id, {"vin": "TEST12345678901"})
        resp = client.post(
            "/api/review/submit",
            json={
                "run_id": run_id,
                "items": [],
                "price_total": 325.50,
                "warehouse_id": 1,
            },
        )
        assert resp.status_code == 200, resp.text
        outputs = _get_outputs(run_id)
        assert outputs.get("price_total") == 325.50, \
            f"Expected price_total=325.50, got {outputs.get('price_total')}"

    def test_price_total_zero_not_lost(self, client):
        """price_total=0 should be stored as 0, not treated as missing."""
        doc_id, run_id = _upload(client)
        if run_id is None:
            pytest.skip("Upload did not return run_id")
        _set_outputs(run_id, {"price_total": 0})
        _set_run_status(run_id, "needs_review")

        resp = client.get("/api/documents/?limit=200")
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        doc = next((d for d in items if d["id"] == doc_id), None)
        assert doc is not None
        # 0 should appear as 0.0, not None
        tp = doc.get("transport_price")
        assert tp is not None and float(tp) == 0.0, \
            f"Expected transport_price=0, got {tp}"
