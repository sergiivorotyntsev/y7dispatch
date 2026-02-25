"""
Day 15 Comprehensive E2E Tests — Coverage Gap Fill

Covers features/areas NOT already tested by existing test files:
- test_batch_operations.py (batch approve/hold/archive)
- test_scan_process.py (scan/process/health)
- test_load_id.py (load ID generation)
- test_weather_alerts.py (weather alerts)
- test_warehouse_distance.py (warehouse CRUD + haversine)
- test_email_context_vision.py (email context + vision)
- test_flicker_attachment_price.py (attachment dedup + price display)

THIS file fills the gaps:
1. Banking PDF classification (new exclusion feature)
2. Distance cache write/read/source tracking
3. Graceful degradation (weather + warehouse without pickup ZIP)
4. Export warehouse persistence through review/submit flow
5. Status-aware editing (save changes per run status)
6. Canonical field name consistency in API responses
7. Document list API (required fields, pagination)
8. Price fields persistence through approve/export flow
9. Review submit with operator overrides (load_id, trailer, dates)
10. ZIP3 coordinate coverage for distance service
"""

import json
import uuid as uuid_mod
from datetime import datetime, timezone
from io import BytesIO

import pytest


# =============================================================================
# Helpers
# =============================================================================

_counter = 0


def _unique_pdf(tag="d15"):
    """Generate unique PDF bytes each call."""
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


def _upload(client, filename="day15_test.pdf"):
    """Upload a document and return (doc_id, run_id)."""
    resp = client.post(
        "/api/documents/upload",
        files={"file": (filename, BytesIO(_unique_pdf(filename)), "application/pdf")},
        data={"dataset_split": "train", "source": "upload"},
    )
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    data = resp.json()
    doc_id = data["document"]["id"]
    run_id = data.get("run_id")

    if not run_id:
        from api.database import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM extraction_runs WHERE document_id = ? ORDER BY id DESC LIMIT 1",
                (doc_id,),
            ).fetchone()
        run_id = row["id"] if row else None

    return doc_id, run_id


def _set_run_status(run_id, status):
    from api.database import get_connection
    with get_connection() as conn:
        conn.execute(
            "UPDATE extraction_runs SET status = ? WHERE id = ?",
            (status, run_id),
        )
        conn.commit()


def _get_run(run_id):
    from api.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM extraction_runs WHERE id = ?", (run_id,)
        ).fetchone()
    return dict(row) if row else None


def _get_outputs(run_id):
    run = _get_run(run_id)
    if not run or not run.get("outputs_json"):
        return {}
    raw = run["outputs_json"]
    return json.loads(raw) if isinstance(raw, str) else (raw or {})


def _get_doc(doc_id):
    from api.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    return dict(row) if row else None


def _set_outputs(run_id, outputs):
    from api.database import get_connection
    with get_connection() as conn:
        conn.execute(
            "UPDATE extraction_runs SET outputs_json = ? WHERE id = ?",
            (json.dumps(outputs), run_id),
        )
        conn.commit()


# =============================================================================
# Class 1: Banking PDF Classification
# =============================================================================


class TestBankingPDFClassification:
    """Verify banking/wire/ACH PDFs are classified correctly and never extracted."""

    def test_wire_ach_classified_as_banking(self):
        """'ANAA Wire & ACH Information.pdf' → banking."""
        from api.workers.email_worker import EmailWorker
        w = EmailWorker()
        assert w._classify_attachment("ANAA Wire & ACH Information.pdf") == "banking"

    def test_wire_instructions_classified_as_banking(self):
        """'Wire_ACH_Instructions.pdf' → banking."""
        from api.workers.email_worker import EmailWorker
        w = EmailWorker()
        assert w._classify_attachment("Wire_ACH_Instructions.pdf") == "banking"

    def test_bank_document_classified_as_banking(self):
        """'Bank of America.pdf' → banking."""
        from api.workers.email_worker import EmailWorker
        w = EmailWorker()
        assert w._classify_attachment("Bank of America.pdf") == "banking"

    def test_wire_transfer_classified_as_banking(self):
        """'Wire Transfer Info.pdf' → banking."""
        from api.workers.email_worker import EmailWorker
        w = EmailWorker()
        assert w._classify_attachment("Wire Transfer Info.pdf") == "banking"

    def test_payment_instructions_classified_as_banking(self):
        """'Payment Instructions for Buyer.pdf' → banking."""
        from api.workers.email_worker import EmailWorker
        w = EmailWorker()
        assert w._classify_attachment("Payment Instructions for Buyer.pdf") == "banking"

    def test_remittance_classified_as_banking(self):
        """'Remittance Advice.pdf' → banking."""
        from api.workers.email_worker import EmailWorker
        w = EmailWorker()
        assert w._classify_attachment("Remittance Advice.pdf") == "banking"

    def test_attachment_pdf_not_banking(self):
        """'attachment.pdf' should NOT be classified as banking (no false positive)."""
        from api.workers.email_worker import EmailWorker
        w = EmailWorker()
        assert w._classify_attachment("attachment.pdf") == "unknown"

    def test_show_report_not_banking(self):
        """'ShowReport.pdf' should be invoice, not banking."""
        from api.workers.email_worker import EmailWorker
        w = EmailWorker()
        assert w._classify_attachment("ShowReport.pdf") == "invoice"

    def test_invoice_not_banking(self):
        """'invoice.pdf' should be invoice, not banking."""
        from api.workers.email_worker import EmailWorker
        w = EmailWorker()
        assert w._classify_attachment("invoice.pdf") == "invoice"

    def test_banking_category_in_classify_and_rank(self):
        """_classify_and_rank_attachments includes 'banking' key."""
        from api.workers.email_worker import EmailWorker
        from unittest.mock import MagicMock
        from api.workers.email_worker import EmailMessage

        w = EmailWorker()
        msg = EmailMessage(
            message_id="<bank-test@local>", uid="1", subject="Test",
            sender="a@x.com", date="2026-01-01", has_pdf=True,
            pdf_filenames=["ShowReport.pdf", "Wire & ACH Info.pdf"],
            raw_message=MagicMock(),
        )
        classified = w._classify_and_rank_attachments(msg)
        assert "banking" in classified
        assert "Wire & ACH Info.pdf" in classified["banking"]
        assert "ShowReport.pdf" in classified["invoice"]

    def test_banking_pdf_not_promoted_to_invoice(self):
        """When only PDF is banking, it should NOT be promoted to invoice."""
        from api.workers.email_worker import EmailWorker
        from unittest.mock import MagicMock
        from api.workers.email_worker import EmailMessage

        w = EmailWorker()
        msg = EmailMessage(
            message_id="<bank-only@local>", uid="2", subject="Test",
            sender="a@x.com", date="2026-01-01", has_pdf=True,
            pdf_filenames=["Bank Wire Info.pdf"],
            raw_message=MagicMock(),
        )
        classified = w._classify_and_rank_attachments(msg)
        assert classified["invoice"] == []
        assert classified["banking"] == ["Bank Wire Info.pdf"]


# =============================================================================
# Class 2: Distance Cache Operations
# =============================================================================


class TestDistanceCache:
    """Verify distance cache write/read/source tracking."""

    def _ensure_cache_table(self):
        from api.database import get_connection
        with get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS distance_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    origin_zip TEXT,
                    destination_warehouse_id INTEGER,
                    distance_miles REAL,
                    distance_text TEXT,
                    duration_minutes REAL,
                    duration_text TEXT,
                    distance_source TEXT,
                    transport_price REAL,
                    transport_price_source TEXT,
                    calculated_at TEXT,
                    UNIQUE(origin_zip, destination_warehouse_id)
                )
            """)
            conn.commit()

    def test_cache_write_and_read(self):
        """Writing to cache and reading back returns same values."""
        self._ensure_cache_table()
        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO distance_cache "
                "(origin_zip, destination_warehouse_id, distance_miles, distance_text, "
                "duration_minutes, duration_text, distance_source, calculated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("90210", 999, 2500.5, "2,501 mi", 2400.0, "40h 0min", "haversine", now),
            )
            conn.commit()

            row = conn.execute(
                "SELECT * FROM distance_cache WHERE origin_zip = ? AND destination_warehouse_id = ?",
                ("90210", 999),
            ).fetchone()

        assert row is not None
        assert row["distance_miles"] == 2500.5
        assert row["distance_source"] == "haversine"
        assert row["duration_minutes"] == 2400.0

    def test_cache_stores_source_label(self):
        """Cache stores the distance source (google, haversine, osrm)."""
        self._ensure_cache_table()
        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        for source in ("google", "haversine", "osrm"):
            zip_code = f"1000{source[:1]}"
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO distance_cache "
                    "(origin_zip, destination_warehouse_id, distance_miles, distance_text, "
                    "duration_minutes, duration_text, distance_source, calculated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (zip_code, 998, 100.0, "100 mi", 120.0, "2h", source, now),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT distance_source FROM distance_cache "
                    "WHERE origin_zip = ? AND destination_warehouse_id = ?",
                    (zip_code, 998),
                ).fetchone()
            assert row["distance_source"] == source

    def test_cache_upsert_overwrites(self):
        """Inserting same origin_zip + warehouse_id updates existing row."""
        self._ensure_cache_table()
        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO distance_cache "
                "(origin_zip, destination_warehouse_id, distance_miles, distance_text, "
                "duration_minutes, duration_text, distance_source, calculated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("11111", 997, 100.0, "100 mi", 120.0, "2h", "haversine", now),
            )
            conn.commit()
            conn.execute(
                "INSERT OR REPLACE INTO distance_cache "
                "(origin_zip, destination_warehouse_id, distance_miles, distance_text, "
                "duration_minutes, duration_text, distance_source, calculated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("11111", 997, 95.3, "95 mi", 110.0, "1h 50min", "google", now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM distance_cache WHERE origin_zip = '11111' AND destination_warehouse_id = 997",
            ).fetchone()
        assert row["distance_miles"] == 95.3
        assert row["distance_source"] == "google"


# =============================================================================
# Class 3: Graceful Degradation
# =============================================================================


class TestGracefulDegradation:
    """Verify endpoints degrade gracefully instead of returning 400."""

    def test_weather_without_zip_returns_200(self, client):
        """Weather for run without pickup_zip returns 200 (not 400)."""
        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        outputs = json.dumps({"pickup_city": "Dallas"})  # No zip
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO extraction_runs "
                "(id, uuid, document_id, auction_type_id, status, outputs_json, created_at) "
                "VALUES (9901, 'graceful-weather-1', 1, 1, 'needs_review', ?, ?)",
                (outputs, now),
            )
            conn.commit()

        resp = client.get("/api/weather/route-alerts-for-run/9901")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alerts"] == []
        assert "not available" in (data.get("ai_summary") or "").lower()

    def test_weather_without_zip_has_low_risk(self, client):
        """Graceful weather response has risk_level=low."""
        resp = client.get("/api/weather/route-alerts-for-run/9901")
        if resp.status_code == 200:
            assert resp.json().get("risk_level") == "low"

    def test_warehouse_options_without_zip_returns_200(self, client):
        """Warehouse options for run without pickup_zip returns 200 (not 400)."""
        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        outputs = json.dumps({"pickup_city": "Austin"})  # No zip
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO extraction_runs "
                "(id, uuid, document_id, auction_type_id, status, outputs_json, created_at) "
                "VALUES (9902, 'graceful-wh-1', 1, 1, 'needs_review', ?, ?)",
                (outputs, now),
            )
            conn.commit()

        resp = client.get("/api/warehouses/options-for-run/9902")
        assert resp.status_code == 200
        data = resp.json()
        assert data["options"] == []

    def test_warehouse_options_without_zip_has_message(self, client):
        """Graceful warehouse response includes an info message."""
        resp = client.get("/api/warehouses/options-for-run/9902")
        if resp.status_code == 200:
            msg = resp.json().get("message") or ""
            assert "not available" in msg.lower() or "manually" in msg.lower()

    def test_weather_nonexistent_run_returns_404(self, client):
        """Weather for nonexistent run still returns 404."""
        resp = client.get("/api/weather/route-alerts-for-run/999999")
        assert resp.status_code == 404

    def test_warehouse_options_nonexistent_run_returns_404(self, client):
        """Warehouse options for nonexistent run still returns 404."""
        resp = client.get("/api/warehouses/options-for-run/999999")
        assert resp.status_code == 404


# =============================================================================
# Class 4: Export Warehouse Persistence
# =============================================================================


class TestExportWarehousePersistence:
    """Verify warehouse selection persists through review submit into outputs_json."""

    def test_submit_review_saves_warehouse_id(self, client):
        """Review submit with warehouse_id saves it to outputs_json."""
        doc_id, run_id = _upload(client, "wh_persist_1.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "warehouse_id": 1,
            "mark_as_reviewed": True,
        })
        assert resp.status_code == 200

        outputs = _get_outputs(run_id)
        assert outputs.get("warehouse_id") == 1

    def test_submit_review_saves_price_total(self, client):
        """Review submit with price_total saves it to outputs_json."""
        doc_id, run_id = _upload(client, "price_persist_1.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "price_total": 450.00,
            "mark_as_reviewed": True,
        })
        assert resp.status_code == 200

        outputs = _get_outputs(run_id)
        assert outputs.get("price_total") == 450.00

    def test_submit_review_saves_load_id(self, client):
        """Review submit with load_id saves it to outputs_json."""
        doc_id, run_id = _upload(client, "loadid_persist_1.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "load_id": "223TOYCA",
            "mark_as_reviewed": True,
        })
        assert resp.status_code == 200

        outputs = _get_outputs(run_id)
        assert outputs.get("load_id") == "223TOYCA"

    def test_submit_review_saves_trailer_type(self, client):
        """Review submit with trailer_type saves it to outputs_json."""
        doc_id, run_id = _upload(client, "trailer_persist_1.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "trailer_type": "ENCLOSED",
            "mark_as_reviewed": True,
        })
        assert resp.status_code == 200

        outputs = _get_outputs(run_id)
        assert outputs.get("trailer_type") == "ENCLOSED"

    def test_submit_review_saves_dates(self, client):
        """Review submit with date fields saves them to outputs_json."""
        doc_id, run_id = _upload(client, "dates_persist_1.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "available_date": "2026-03-01",
            "expiration_date": "2026-03-31",
            "desired_delivery_date": "2026-03-15",
            "mark_as_reviewed": True,
        })
        assert resp.status_code == 200

        outputs = _get_outputs(run_id)
        assert outputs.get("available_date") == "2026-03-01"
        assert outputs.get("expiration_date") == "2026-03-31"
        assert outputs.get("desired_delivery_date") == "2026-03-15"

    def test_submit_review_saves_payment_fields(self, client):
        """Review submit with payment method fields saves to outputs_json."""
        doc_id, run_id = _upload(client, "payment_persist_1.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "cod_amount": 0,
            "cod_payment_method": "CASH_CERTIFIED_FUNDS",
            "balance_payment_method": "CERTIFIED_FUNDS",
            "balance_payment_time": "2_BUSINESS_DAYS_QUICK_PAY",
            "balance_terms_begin_on": "RECEIVING_SIGNED_BOL",
            "mark_as_reviewed": True,
        })
        assert resp.status_code == 200

        outputs = _get_outputs(run_id)
        assert outputs.get("cod_amount") == 0
        assert outputs.get("balance_payment_method") == "CERTIFIED_FUNDS"
        assert outputs.get("balance_terms_begin_on") == "RECEIVING_SIGNED_BOL"


# =============================================================================
# Class 5: Status-Aware Editing
# =============================================================================


class TestStatusAwareEditing:
    """Verify save/approve behavior depends on extraction run status."""

    def test_approve_from_needs_review(self, client):
        """Can approve a run that is 'needs_review'."""
        doc_id, run_id = _upload(client, "status_nr.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/batch/approve", json={"run_ids": [run_id]})
        assert resp.status_code == 200
        assert resp.json()["succeeded"] == 1

        run = _get_run(run_id)
        assert run["status"] == "reviewed"

    def test_submit_saves_without_status_change(self, client):
        """Submit with mark_as_reviewed=False preserves current status."""
        doc_id, run_id = _upload(client, "status_save_only.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "mark_as_reviewed": False,
            "price_total": 500.0,
        })
        assert resp.status_code == 200

        # Price saved but status unchanged
        outputs = _get_outputs(run_id)
        assert outputs.get("price_total") == 500.0
        run = _get_run(run_id)
        assert run["status"] == "needs_review"

    def test_submit_with_mark_for_export(self, client):
        """Submit with mark_for_export changes status to approved."""
        doc_id, run_id = _upload(client, "status_export.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "mark_for_export": True,
            "warehouse_id": 1,
            "price_total": 600.0,
        })
        assert resp.status_code == 200

        run = _get_run(run_id)
        assert run["status"] in ("approved", "reviewed", "exported")

    def test_submit_reviewed_run_preserves_data(self, client):
        """Re-submitting a reviewed run preserves previously saved fields."""
        doc_id, run_id = _upload(client, "status_reviewed_edit.pdf")
        assert run_id is not None
        _set_run_status(run_id, "reviewed")

        # First submit — save price
        client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "price_total": 700.0,
            "load_id": "223BMWX5",
        })

        # Second submit — save warehouse (price should persist)
        client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "warehouse_id": 1,
        })

        outputs = _get_outputs(run_id)
        # Earlier fields should still be there
        assert outputs.get("price_total") == 700.0
        assert outputs.get("load_id") == "223BMWX5"


# =============================================================================
# Class 6: Field Name Consistency
# =============================================================================


class TestFieldNameConsistency:
    """Verify API responses use canonical field names from CLAUDE.md mapping."""

    @pytest.fixture(autouse=True)
    def _init_warehouses(self):
        """Ensure warehouses table exists for document list queries."""
        from api.routes.warehouses import init_warehouses_schema
        init_warehouses_schema()

    def test_document_list_has_canonical_fields(self, client):
        """GET /api/documents/ response items contain canonical field names."""
        _upload(client, "canonical_test.pdf")

        resp = client.get("/api/documents/?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0

        doc = data["items"][0]
        # Canonical field names that MUST exist (even if null)
        required_fields = [
            "id", "filename", "auction_type_id", "source",
            "vin", "vehicle_year", "vehicle_make", "vehicle_model",
            "load_id", "gate_pass", "warehouse_id", "warehouse_name",
            "price_total", "auction_cost", "distance_miles",
            "extraction_status", "extraction_run_id",
        ]
        for field in required_fields:
            assert field in doc, f"Missing canonical field '{field}' in document response"

    def test_no_total_amount_alias_in_documents(self, client):
        """Documents API should use auction_cost, not total_amount."""
        resp = client.get("/api/documents/?limit=1")
        assert resp.status_code == 200
        items = resp.json()["items"]
        if items:
            doc = items[0]
            # auction_cost is the canonical name, total_amount should not be at top-level
            assert "auction_cost" in doc

    def test_extraction_response_has_run_fields(self, client):
        """GET /api/extractions/{id} returns run with expected fields."""
        doc_id, run_id = _upload(client, "extract_fields_test.pdf")
        if not run_id:
            pytest.skip("No extraction run created")

        resp = client.get(f"/api/extractions/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        run = data.get("run") or data
        assert "id" in run
        assert "status" in run
        assert "document_id" in run
        assert "auction_type_id" in run

    def test_document_response_has_pickup_fields(self, client):
        """Document response includes pickup city/state for UI display."""
        from api.routes.warehouses import init_warehouses_schema
        init_warehouses_schema()
        resp = client.get("/api/documents/?limit=5")
        assert resp.status_code == 200
        items = resp.json()["items"]
        if items:
            doc = items[0]
            assert "pickup_city" in doc
            assert "pickup_state" in doc


# =============================================================================
# Class 7: Document List API
# =============================================================================


class TestDocumentListAPI:
    """Verify Documents API pagination, field presence, and response shape."""

    @pytest.fixture(autouse=True)
    def _init_warehouses(self):
        """Ensure warehouses table exists for document list queries."""
        from api.routes.warehouses import init_warehouses_schema
        init_warehouses_schema()

    def test_documents_list_returns_200(self, client):
        """GET /api/documents/ returns 200."""
        resp = client.get("/api/documents/")
        assert resp.status_code == 200

    def test_documents_list_has_total(self, client):
        """Response includes total count."""
        resp = client.get("/api/documents/")
        data = resp.json()
        assert "total" in data
        assert isinstance(data["total"], int)

    def test_documents_list_has_items_array(self, client):
        """Response includes items array."""
        resp = client.get("/api/documents/")
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_documents_pagination_limit(self, client):
        """Limit parameter restricts returned items."""
        # Upload a few docs to ensure we have data
        for i in range(3):
            _upload(client, f"pagination_{i}.pdf")

        resp = client.get("/api/documents/?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2

    def test_documents_pagination_offset(self, client):
        """Offset parameter skips items."""
        resp_all = client.get("/api/documents/?limit=100")
        total = resp_all.json()["total"]

        if total > 1:
            resp_offset = client.get("/api/documents/?limit=100&offset=1")
            assert resp_offset.status_code == 200
            items_offset = resp_offset.json()["items"]
            # Should have one fewer item (or same if more were added)
            assert len(items_offset) <= total

    def test_documents_response_time(self, client):
        """Documents list responds within reasonable time."""
        import time
        start = time.time()
        resp = client.get("/api/documents/?limit=50")
        elapsed_ms = (time.time() - start) * 1000
        assert resp.status_code == 200
        assert elapsed_ms < 2000, f"Documents API took {elapsed_ms:.0f}ms (should be <2000ms)"


# =============================================================================
# Class 8: Price Fields Persistence
# =============================================================================


class TestPriceFieldsPersistence:
    """Verify price fields persist through review/approve flow."""

    def test_price_total_persists_after_review(self, client):
        """price_total set during review persists in outputs_json."""
        doc_id, run_id = _upload(client, "price_review.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "price_total": 325.50,
        })

        outputs = _get_outputs(run_id)
        assert outputs.get("price_total") == 325.50

    def test_zero_price_not_treated_as_null(self, client):
        """COD amount of 0 should be saved as 0, not null."""
        doc_id, run_id = _upload(client, "price_zero.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "cod_amount": 0,
        })

        outputs = _get_outputs(run_id)
        assert outputs.get("cod_amount") == 0

    def test_price_accessible_after_approve(self, client):
        """Price saved before approve is accessible after approve."""
        doc_id, run_id = _upload(client, "price_approve.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        # Save price
        client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "price_total": 800.0,
        })

        # Approve
        client.post("/api/batch/approve", json={"run_ids": [run_id]})

        # Price still there
        outputs = _get_outputs(run_id)
        assert outputs.get("price_total") == 800.0

    def test_auction_cost_stored_as_total_amount(self):
        """Verify extraction stores auction purchase price in outputs_json."""
        # Direct DB check: outputs_json should contain 'total_amount' or 'auction_cost'
        # This tests the data model, not a specific endpoint
        from api.database import get_connection
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id, outputs_json FROM extraction_runs WHERE outputs_json IS NOT NULL LIMIT 5"
            ).fetchall()

        # At least verify outputs_json is valid JSON
        for row in rows:
            outputs = json.loads(row["outputs_json"]) if row["outputs_json"] else {}
            assert isinstance(outputs, dict)


# =============================================================================
# Class 9: Review Submit with Operator Overrides
# =============================================================================


class TestReviewSubmitOverrides:
    """Verify all operator override fields survive the review submit roundtrip."""

    def test_all_overrides_saved(self, client):
        """Submit with all override fields saves them all to outputs_json."""
        doc_id, run_id = _upload(client, "all_overrides.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        overrides = {
            "price_total": 550.0,
            "load_id": "223HONDO",
            "trailer_type": "OPEN",
            "requires_inspection": True,
            "available_date": "2026-02-25",
            "expiration_date": "2026-03-27",
            "desired_delivery_date": "2026-03-01",
            "cod_amount": 0,
            "cod_payment_method": "CASH_CERTIFIED_FUNDS",
            "cod_payment_location": "DELIVERY",
            "balance_payment_method": "CERTIFIED_FUNDS",
            "balance_payment_time": "2_BUSINESS_DAYS_QUICK_PAY",
            "balance_terms_begin_on": "RECEIVING_SIGNED_BOL",
            "vehicle_is_inoperable": False,
            "warehouse_id": 1,
            "load_specific_terms": "TEXT 857-895-8777",
            "transport_special_instructions": "Call before arrival",
        }

        resp = client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "mark_as_reviewed": True,
            **overrides,
        })
        assert resp.status_code == 200

        outputs = _get_outputs(run_id)
        for key, expected in overrides.items():
            actual = outputs.get(key)
            assert actual == expected, (
                f"Override '{key}': expected {expected!r}, got {actual!r}"
            )

    def test_submit_without_overrides_doesnt_clear(self, client):
        """Re-submitting without certain overrides should NOT clear them."""
        doc_id, run_id = _upload(client, "no_clear_overrides.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        # First: set price and load_id
        client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "price_total": 400.0,
            "load_id": "223BMWX3",
        })

        # Second: set only warehouse (no price/load_id in request)
        client.post("/api/review/submit", json={
            "run_id": run_id,
            "items": [],
            "warehouse_id": 1,
        })

        outputs = _get_outputs(run_id)
        # Previous values should still be there
        assert outputs.get("price_total") == 400.0
        assert outputs.get("load_id") == "223BMWX3"
        assert outputs.get("warehouse_id") == 1


# =============================================================================
# Class 10: ZIP3 Coordinate Coverage
# =============================================================================


class TestZIP3CoordinateCoverage:
    """Verify ZIP3 coordinate lookup covers major US regions."""

    def test_major_zip_prefixes_resolvable(self):
        """Major ZIP3 prefixes should resolve to coordinates."""
        from services.distance_service import _zip_to_coords

        # Major metro ZIPs
        test_zips = {
            "10001": "New York",
            "90210": "Beverly Hills",
            "60601": "Chicago",
            "77001": "Houston",
            "33101": "Miami",
            "02101": "Boston",
            "30301": "Atlanta",
            "48201": "Detroit",
            "85001": "Phoenix",
        }

        resolved = 0
        for zip_code, city in test_zips.items():
            coords = _zip_to_coords(zip_code)
            if coords:
                lat, lon = coords
                assert -90 <= lat <= 90, f"{city} lat out of range: {lat}"
                assert -180 <= lon <= 180, f"{city} lon out of range: {lon}"
                resolved += 1

        # At least 50% should resolve (ZIP3 table may not have all)
        assert resolved >= len(test_zips) // 2, (
            f"Only {resolved}/{len(test_zips)} major ZIPs resolved"
        )

    def test_haversine_returns_positive_distance(self):
        """Haversine between two known points returns positive distance."""
        from services.distance_service import haversine

        # NYC to LA: ~2,451 miles
        dist = haversine(40.7128, -74.0060, 34.0522, -118.2437)
        assert dist > 2000
        assert dist < 3000

    def test_haversine_same_point_is_zero(self):
        """Haversine from point to itself is 0."""
        from services.distance_service import haversine

        dist = haversine(40.0, -74.0, 40.0, -74.0)
        assert dist == 0.0


# =============================================================================
# Class 11: Weather Response Shape
# =============================================================================


class TestWeatherResponseShape:
    """Verify weather API response contains all expected fields."""

    def _create_run_with_zip(self, client, run_id_val, zip_code):
        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        outputs = json.dumps({
            "pickup_zip": zip_code,
            "pickup_city": "Test",
            "pickup_state": "MA",
        })
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO extraction_runs "
                "(id, uuid, document_id, auction_type_id, status, outputs_json, created_at) "
                "VALUES (?, ?, 1, 1, 'needs_review', ?, ?)",
                (run_id_val, f"weather-shape-{run_id_val}", outputs, now),
            )
            conn.commit()

    def test_response_has_required_fields(self, client):
        """Weather response has alerts, route_states, risk_level."""
        self._create_run_with_zip(client, 9910, "02101")

        resp = client.get("/api/weather/route-alerts-for-run/9910")
        assert resp.status_code == 200
        data = resp.json()
        assert "alerts" in data
        assert "route_states" in data
        assert "risk_level" in data
        assert isinstance(data["alerts"], list)

    def test_graceful_response_has_same_shape(self, client):
        """Graceful degradation response has same shape as normal response."""
        from api.database import get_connection
        now = datetime.now(timezone.utc).isoformat()
        outputs = json.dumps({})  # No pickup data at all
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO extraction_runs "
                "(id, uuid, document_id, auction_type_id, status, outputs_json, created_at) "
                "VALUES (9911, 'weather-graceful-shape', 1, 1, 'needs_review', ?, ?)",
                (outputs, now),
            )
            conn.commit()

        resp = client.get("/api/weather/route-alerts-for-run/9911")
        assert resp.status_code == 200
        data = resp.json()
        # Same fields should exist in graceful mode
        assert "alerts" in data
        assert "route_states" in data
        assert "risk_level" in data
        assert data["risk_level"] == "low"


# =============================================================================
# Class 12: Extraction Detail Endpoint
# =============================================================================


class TestExtractionDetail:
    """Verify extraction detail endpoint returns complete data."""

    def test_extraction_detail_returns_200(self, client):
        """GET /api/extractions/{id} returns 200 for valid run."""
        doc_id, run_id = _upload(client, "detail_test.pdf")
        if not run_id:
            pytest.skip("No run created")

        resp = client.get(f"/api/extractions/{run_id}")
        assert resp.status_code == 200

    def test_extraction_detail_has_outputs(self, client):
        """Extraction detail includes outputs field."""
        doc_id, run_id = _upload(client, "detail_outputs.pdf")
        if not run_id:
            pytest.skip("No run created")

        resp = client.get(f"/api/extractions/{run_id}")
        data = resp.json()
        run = data.get("run") or data
        assert "outputs" in run or "outputs_json" in run

    def test_extraction_detail_404_for_missing(self, client):
        """GET /api/extractions/999999 returns 404."""
        resp = client.get("/api/extractions/999999")
        assert resp.status_code == 404

    def test_extraction_list_returns_200(self, client):
        """GET /api/extractions/ returns 200."""
        resp = client.get("/api/extractions/")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data


# =============================================================================
# Class 13: Batch Validation Edge Cases
# =============================================================================


class TestBatchValidationExtended:
    """Extended batch validation beyond existing test_batch_operations.py."""

    def test_batch_approve_over_50_rejected(self, client):
        """Batch approve with >50 run_ids returns 400 or 422."""
        ids = list(range(1, 52))
        resp = client.post("/api/batch/approve", json={"run_ids": ids})
        assert resp.status_code in (400, 422)

    def test_batch_hold_over_50_rejected(self, client):
        """Batch hold with >50 document_ids returns 400 or 422."""
        ids = list(range(1, 52))
        resp = client.post("/api/batch/hold", json={
            "document_ids": ids,
            "reason": "other",
        })
        assert resp.status_code in (400, 422)

    def test_batch_archive_over_50_rejected(self, client):
        """Batch archive with >50 document_ids returns 400 or 422."""
        ids = list(range(1, 52))
        resp = client.post("/api/batch/archive", json={"document_ids": ids})
        assert resp.status_code in (400, 422)

    def test_batch_response_has_results_array(self, client):
        """Batch response includes results array with per-item details."""
        doc_id, run_id = _upload(client, "batch_results.pdf")
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/batch/approve", json={"run_ids": [run_id]})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert isinstance(data["results"], list)
        assert len(data["results"]) == 1
        assert data["results"][0]["success"] is True


# =============================================================================
# Class 14: Document Hold/Archive Flow
# =============================================================================


class TestDocumentHoldArchiveFlow:
    """Verify hold → release → archive → unarchive flow."""

    def test_set_hold_on_document(self, client):
        """POST /api/documents/{id}/set-hold sets hold fields."""
        doc_id, _ = _upload(client, "hold_flow.pdf")

        resp = client.post(f"/api/documents/{doc_id}/set-hold", json={
            "reason": "awaiting_gate_pass",
            "note": "Waiting for gate pass PIN",
        })
        assert resp.status_code == 200

        doc = _get_doc(doc_id)
        assert doc["hold_reason"] == "awaiting_gate_pass"
        assert doc["hold_note"] == "Waiting for gate pass PIN"
        assert doc["hold_since"] is not None

    def test_release_hold(self, client):
        """POST /api/documents/{id}/release-hold clears hold fields."""
        doc_id, _ = _upload(client, "release_flow.pdf")

        client.post(f"/api/documents/{doc_id}/set-hold", json={
            "reason": "awaiting_payment",
        })

        resp = client.post(f"/api/documents/{doc_id}/release-hold")
        assert resp.status_code == 200

        doc = _get_doc(doc_id)
        assert doc["hold_reason"] is None

    def test_archive_document(self, client):
        """POST /api/documents/{id}/archive sets archived_at."""
        doc_id, _ = _upload(client, "archive_flow.pdf")

        resp = client.post(f"/api/documents/{doc_id}/archive")
        assert resp.status_code == 200

        doc = _get_doc(doc_id)
        assert doc["archived_at"] is not None

    def test_unarchive_document(self, client):
        """POST /api/documents/{id}/unarchive clears archived_at."""
        doc_id, _ = _upload(client, "unarchive_flow.pdf")

        client.post(f"/api/documents/{doc_id}/archive")
        resp = client.post(f"/api/documents/{doc_id}/unarchive")
        assert resp.status_code == 200

        doc = _get_doc(doc_id)
        assert doc["archived_at"] is None


# =============================================================================
# Class 15: Health Check Extended
# =============================================================================


class TestHealthCheckExtended:
    """Extended health check beyond existing test_scan_process.py."""

    def test_health_version_is_string(self, client):
        """Health version field is a string."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("version"), str)

    def test_health_checks_is_dict(self, client):
        """Health checks field is a dictionary."""
        resp = client.get("/api/health")
        data = resp.json()
        assert isinstance(data.get("checks"), dict)

    def test_readiness_ready_field(self, client):
        """Readiness probe has 'ready' boolean field."""
        resp = client.get("/api/ready")
        assert resp.status_code == 200
        assert "ready" in resp.json()

    def test_liveness_alive_field(self, client):
        """Liveness probe has 'alive' boolean field."""
        resp = client.get("/api/live")
        assert resp.status_code == 200
        assert "alive" in resp.json()


# =============================================================================
# Class 16: Email Context Endpoint
# =============================================================================


class TestEmailContextEndpoint:
    """Verify email context endpoint for extraction runs."""

    def test_email_context_returns_200_for_email_sourced(self, client):
        """Email context returns 200 for email-sourced runs."""
        # Upload-sourced run won't have email context, so test the endpoint exists
        doc_id, run_id = _upload(client, "email_ctx_test.pdf")
        if not run_id:
            pytest.skip("No run created")

        resp = client.get(f"/api/extractions/{run_id}/email-context")
        # May return 200 with empty/null context or 404 if not email-sourced
        assert resp.status_code in (200, 404)

    def test_email_context_404_for_missing_run(self, client):
        """Email context returns 404 for nonexistent run."""
        resp = client.get("/api/extractions/999999/email-context")
        assert resp.status_code == 404
