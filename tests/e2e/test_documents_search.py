"""
E2E Tests — Documents search + stats endpoint

Tests cover:
  - Search by load_id
  - Search by email subject
  - Search combined with auction_type filter
  - /api/documents/stats endpoint
  - Filter by status (ready_to_export virtual filter)
"""

import json
import uuid

import pytest

from api.database import get_connection


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _ensure_auction_type(code="COPART", name="Copart"):
    """Get or create an auction type, return its id."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM auction_types WHERE code = ?", (code,)
        ).fetchone()
        if row:
            return row["id"]
        conn.execute(
            "INSERT INTO auction_types (name, code, is_base, is_active) VALUES (?, ?, 1, 1)",
            (name, code),
        )
        conn.commit()
        return conn.execute(
            "SELECT id FROM auction_types WHERE code = ?", (code,)
        ).fetchone()["id"]


def _create_doc_with_run(auction_type_id, outputs, status="needs_review", source="email"):
    """Create a document + extraction run, return (doc_id, run_id)."""
    doc_uuid = uuid.uuid4().hex
    run_uuid = uuid.uuid4().hex
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO documents
               (uuid, filename, file_path, auction_type_id, dataset_split, is_test, source)
               VALUES (?, ?, ?, ?, 'train', 0, ?)""",
            (doc_uuid, f"test_{doc_uuid[:8]}.pdf", f"/tmp/{doc_uuid}.pdf", auction_type_id, source),
        )
        doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            """INSERT INTO extraction_runs
               (uuid, document_id, auction_type_id, extractor_kind, status, outputs_json)
               VALUES (?, ?, ?, 'rule', ?, ?)""",
            (run_uuid, doc_id, auction_type_id, status, json.dumps(outputs)),
        )
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
    return doc_id, run_id


def _ensure_tables():
    """Create email_log and email_replies tables if they don't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE,
                sender TEXT,
                sender_name TEXT,
                subject TEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                graph_message_id TEXT,
                extraction_run_ids TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def _create_email_log(subject, sender, run_ids):
    """Create an email_log entry linked to given run_ids."""
    _ensure_tables()
    msg_id = f"<{uuid.uuid4().hex}@test.com>"
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO email_log
               (message_id, sender, sender_name, subject, extraction_run_ids, status)
               VALUES (?, ?, ?, ?, ?, 'processed')""",
            (msg_id, sender, "Test Sender", subject, json.dumps(run_ids)),
        )
        conn.commit()


# ═══════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════

class TestDocumentsSearch:
    """Test document search across new fields."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Create test data for search tests."""
        self.at_copart = _ensure_auction_type("COPART", "Copart")
        self.at_iaa = _ensure_auction_type("IAA", "IAA")

        # Document with a unique load_id
        outputs_1 = {
            "vehicle_vin": "WBAJB0C51JB084264",
            "vehicle_make": "BMW",
            "vehicle_model": "530I",
            "load_id": "226BMWFI1",
            "vehicle_lot": "LOT9999",
        }
        self.doc1_id, self.run1_id = _create_doc_with_run(
            self.at_copart, outputs_1, status="needs_review"
        )

        # Document with IAA type and different load_id
        outputs_2 = {
            "vehicle_vin": "JF1ZNBF18P8758268",
            "vehicle_make": "SUBARU",
            "vehicle_model": "BRZ",
            "load_id": "226SUBBA1",
            "vehicle_lot": "LOT8888",
        }
        self.doc2_id, self.run2_id = _create_doc_with_run(
            self.at_iaa, outputs_2, status="reviewed"
        )

        # Email log linked to run1 with a descriptive subject
        _create_email_log(
            subject="Fwd: Copart Purchase - BMW 530I VIN WBAJB0C51JB084264",
            sender="broker@test.com",
            run_ids=[self.run1_id],
        )

    def test_search_by_load_id(self, client):
        """Searching for load_id '226BMWFI1' should find the document."""
        resp = client.get("/api/documents/", params={
            "search": "226BMWFI1",
            "dataset_split": "train",
        })
        assert resp.status_code == 200
        data = resp.json()
        found_ids = [it["id"] for it in data["items"]]
        assert self.doc1_id in found_ids

    def test_search_by_load_id_partial(self, client):
        """Partial load_id search should still match."""
        resp = client.get("/api/documents/", params={
            "search": "226BMW",
            "dataset_split": "train",
        })
        assert resp.status_code == 200
        data = resp.json()
        found_ids = [it["id"] for it in data["items"]]
        assert self.doc1_id in found_ids

    def test_search_by_email_subject(self, client):
        """Searching for text in email subject should find linked document."""
        resp = client.get("/api/documents/", params={
            "search": "Copart Purchase",
            "dataset_split": "train",
        })
        assert resp.status_code == 200
        data = resp.json()
        found_ids = [it["id"] for it in data["items"]]
        assert self.doc1_id in found_ids

    def test_search_combined_with_auction_type(self, client):
        """Search + auction_type_id should both apply (AND)."""
        # Search for 'SUBARU' in IAA type — should find doc2
        resp = client.get("/api/documents/", params={
            "search": "SUBARU",
            "auction_type_id": self.at_iaa,
            "dataset_split": "train",
        })
        assert resp.status_code == 200
        data = resp.json()
        found_ids = [it["id"] for it in data["items"]]
        assert self.doc2_id in found_ids

        # Search for 'SUBARU' in COPART type — should NOT find doc2
        resp2 = client.get("/api/documents/", params={
            "search": "SUBARU",
            "auction_type_id": self.at_copart,
            "dataset_split": "train",
        })
        assert resp2.status_code == 200
        data2 = resp2.json()
        found_ids2 = [it["id"] for it in data2["items"]]
        assert self.doc2_id not in found_ids2

    def test_search_combined_with_status(self, client):
        """Search + status should both apply (AND)."""
        # 'BMW' exists in doc1 (needs_review) — filter by needs_review should find it
        resp = client.get("/api/documents/", params={
            "search": "BMW",
            "status": "needs_review",
            "dataset_split": "train",
        })
        assert resp.status_code == 200
        found_ids = [it["id"] for it in resp.json()["items"]]
        assert self.doc1_id in found_ids

        # 'BMW' with status=exported should NOT find doc1
        resp2 = client.get("/api/documents/", params={
            "search": "BMW",
            "status": "exported",
            "dataset_split": "train",
        })
        assert resp2.status_code == 200
        found_ids2 = [it["id"] for it in resp2.json()["items"]]
        assert self.doc1_id not in found_ids2


class TestDocumentsStats:
    """Test the /api/documents/stats endpoint."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        at_id = _ensure_auction_type("COPART", "Copart")
        # Create docs with different statuses
        _create_doc_with_run(at_id, {"vehicle_vin": "V1"}, status="needs_review")
        _create_doc_with_run(at_id, {"vehicle_vin": "V2"}, status="reviewed")
        _create_doc_with_run(at_id, {"vehicle_vin": "V3"}, status="approved")
        _create_doc_with_run(at_id, {"vehicle_vin": "V4"}, status="exported")
        _create_doc_with_run(at_id, {"vehicle_vin": "V5"}, status="exported")
        _create_doc_with_run(at_id, {"vehicle_vin": "V6"}, status="failed")

    def test_stats_endpoint(self, client):
        """Stats should return correct counts from entire DB."""
        resp = client.get("/api/documents/stats")
        assert resp.status_code == 200
        data = resp.json()
        # We can't assert exact numbers because other tests also insert data,
        # but we can verify the structure and that counts are >= our inserts
        assert "total_emails" in data
        assert "transport_requests" in data
        assert data["needs_review"] >= 1
        assert data["ready_to_export"] >= 2  # reviewed + approved
        assert data["exported"] >= 2
        assert data["failed"] >= 1

    def test_stats_keys_present(self, client):
        """All expected keys should be present in response."""
        resp = client.get("/api/documents/stats")
        data = resp.json()
        for key in ("total_emails", "transport_requests", "needs_review",
                     "ready_to_export", "exported", "failed"):
            assert key in data, f"Missing key: {key}"


class TestDocumentsStatusFilter:
    """Test the ready_to_export virtual status filter."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        _ensure_tables()
        at_id = _ensure_auction_type("COPART", "Copart")
        outputs_rev = {"vehicle_vin": "VREV1", "vehicle_make": "HONDA"}
        outputs_app = {"vehicle_vin": "VAPP1", "vehicle_make": "TOYOTA"}
        outputs_exp = {"vehicle_vin": "VEXP1", "vehicle_make": "FORD"}

        self.rev_doc, self.rev_run = _create_doc_with_run(at_id, outputs_rev, status="reviewed")
        self.app_doc, self.app_run = _create_doc_with_run(at_id, outputs_app, status="approved")
        self.exp_doc, self.exp_run = _create_doc_with_run(at_id, outputs_exp, status="exported")

    def test_filter_ready_to_export(self, client):
        """status=ready_to_export should return reviewed + approved docs."""
        resp = client.get("/api/documents/", params={
            "status": "ready_to_export",
            "dataset_split": "train",
        })
        assert resp.status_code == 200
        data = resp.json()
        found_ids = [it["id"] for it in data["items"]]
        assert self.rev_doc in found_ids
        assert self.app_doc in found_ids
        assert self.exp_doc not in found_ids

    def test_filter_exported(self, client):
        """status=exported should return exported docs and exclude reviewed/approved."""
        resp = client.get("/api/documents/", params={
            "status": "exported",
            "dataset_split": "train",
        })
        assert resp.status_code == 200
        data = resp.json()
        found_ids = [it["id"] for it in data["items"]]
        assert self.exp_doc in found_ids
        # Reviewed/approved should NOT appear in exported filter
        assert self.rev_doc not in found_ids
        assert self.app_doc not in found_ids
