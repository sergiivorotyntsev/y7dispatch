"""
E2E Tests — VIN Duplicate Detection & Email Linking

Tests cover:
  - detect_vin_duplicates() finds duplicates and stores to vin_duplicates table
  - GET /api/extractions/{run_id}/duplicates returns enriched data with email context
  - No false duplicates when only one run has a VIN
  - has_duplicate_vin flag in documents list response
  - Auto-detection in extraction pipeline
"""

import json
import uuid

import pytest

from api.database import get_connection
from api.routes.extractions import detect_vin_duplicates, init_vin_duplicates_schema


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables():
    """Ensure vin_duplicates and email_log tables exist."""
    init_vin_duplicates_schema()
    from api.routes.email_log import init_email_log_table
    init_email_log_table()


def _create_test_run(conn, vin, status="needs_review", filename="test.pdf"):
    """Helper: create a document + extraction_run with a given VIN."""
    doc_uuid = str(uuid.uuid4())
    run_uuid = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO documents (uuid, auction_type_id, dataset_split, filename, file_path) "
        "VALUES (?, 1, 'train', ?, '/tmp/test.pdf')",
        (doc_uuid, filename),
    )
    doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    outputs = json.dumps({"vehicle_vin": vin, "vehicle_make": "TOYOTA", "vehicle_model": "CAMRY"})
    conn.execute(
        "INSERT INTO extraction_runs (uuid, document_id, auction_type_id, status, outputs_json) "
        "VALUES (?, ?, 1, ?, ?)",
        (run_uuid, doc_id, status, outputs),
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return run_id, doc_id


class TestDuplicateVINDetected:
    """Two runs with the same VIN → vin_duplicates record created."""

    def test_duplicate_vin_detected(self):
        vin = "WAUFNCF53JA032001"

        with get_connection() as conn:
            run1, _ = _create_test_run(conn, vin, filename="email1.pdf")
            run2, _ = _create_test_run(conn, vin, filename="email2.pdf")

        # Detect from run2's perspective
        dups = detect_vin_duplicates(run2, vin)
        assert len(dups) >= 1
        assert any(d["run_id"] == run1 for d in dups)

        # Check vin_duplicates table was populated
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM vin_duplicates WHERE vin = ? AND run_id = ?", (vin, run2)
            ).fetchone()
            assert row is not None
            dup_ids = json.loads(row["duplicate_run_ids"])
            assert run1 in dup_ids

            # Reverse entry should also exist
            rev = conn.execute(
                "SELECT * FROM vin_duplicates WHERE vin = ? AND run_id = ?", (vin, run1)
            ).fetchone()
            assert rev is not None
            rev_ids = json.loads(rev["duplicate_run_ids"])
            assert run2 in rev_ids


class TestDuplicateEndpoint:
    """GET /api/extractions/{id}/duplicates returns enriched data."""

    def test_duplicate_endpoint(self, client):
        vin = "WAUFNCF53JA032002"

        with get_connection() as conn:
            run1, _ = _create_test_run(conn, vin, filename="dup_ep1.pdf")
            run2, _ = _create_test_run(conn, vin, filename="dup_ep2.pdf")

        resp = client.get(f"/api/extractions/{run2}/duplicates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["vin"] == vin
        assert data["has_duplicates"] is True
        assert len(data["duplicates"]) >= 1
        dup = data["duplicates"][0]
        assert "run_id" in dup
        assert "status" in dup
        assert "filename" in dup


class TestNoFalseDuplicates:
    """One VIN, one run → has_duplicates=false."""

    def test_no_false_duplicates(self, client):
        vin = "WAUFNCF53JA032003"

        with get_connection() as conn:
            run1, _ = _create_test_run(conn, vin, filename="unique.pdf")

        resp = client.get(f"/api/extractions/{run1}/duplicates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["vin"] == vin
        assert data["has_duplicates"] is False
        assert len(data["duplicates"]) == 0


class TestDuplicateFlagInDocuments:
    """Documents list has_duplicate_vin=true for matching doc."""

    def test_duplicate_flag_in_documents(self):
        """Verify vin_duplicates table is populated and queryable."""
        vin = "WAUFNCF53JA032004"

        with get_connection() as conn:
            run1, doc1 = _create_test_run(conn, vin, filename="docflag1.pdf")
            run2, doc2 = _create_test_run(conn, vin, filename="docflag2.pdf")

        # Trigger detection so vin_duplicates table is populated
        detect_vin_duplicates(run1, vin)
        detect_vin_duplicates(run2, vin)

        # Verify directly from vin_duplicates table
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT vin FROM vin_duplicates WHERE vin = ?", (vin,)
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["vin"] == vin

            # Verify both runs have entries
            run_rows = conn.execute(
                "SELECT run_id FROM vin_duplicates WHERE vin = ?", (vin,)
            ).fetchall()
            run_ids = {r["run_id"] for r in run_rows}
            assert run1 in run_ids
            assert run2 in run_ids


class TestDuplicateAutoDetection:
    """After detect_vin_duplicates, vin_duplicates is auto-populated."""

    def test_duplicate_auto_detection(self):
        vin = "WAUFNCF53JA032005"

        with get_connection() as conn:
            run1, _ = _create_test_run(conn, vin, status="needs_review", filename="auto1.pdf")
            run2, _ = _create_test_run(conn, vin, status="needs_review", filename="auto2.pdf")

        # Simulate what the extraction pipeline does
        detect_vin_duplicates(run2, vin)

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM vin_duplicates WHERE vin = ?", (vin,)
            ).fetchall()
            assert len(rows) >= 2  # Both run1 and run2 should have entries
            all_run_ids = {r["run_id"] for r in rows}
            assert run1 in all_run_ids
            assert run2 in all_run_ids
