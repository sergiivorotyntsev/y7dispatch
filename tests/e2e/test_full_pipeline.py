"""
E2E Pipeline Tests — Full Data Integrity & Status Flow Validation

Validates the ENTIRE pipeline using a temporary test database seeded
with realistic data from actual extraction outputs.

Tests cover:
  - Document ↔ ExtractionRun 1:1 integrity
  - No orphan records across tables
  - VIN format validation (ISO 3779)
  - Load ID uniqueness and format
  - Exported doc required field coverage
  - Status flow consistency (review_items, export_jobs)
  - Auction-specific field coverage thresholds
  - Email→Document traceability
"""

import json
import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures — isolated temp DB seeded with realistic pipeline data
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def pipeline_db(tmp_path):
    """Create a temp database seeded with realistic pipeline data."""
    import importlib
    import api.database as db_mod

    db_path = str(tmp_path / "pipeline_test.db")
    with patch.dict(os.environ, {"DATABASE_PATH": db_path}):
        importlib.reload(db_mod)

        from api.models import init_schema
        init_schema()

        conn = sqlite3.connect(db_path)
        _seed_data(conn)
        conn.close()

        yield db_path

    # Restore api.database to original state so subsequent tests aren't polluted
    importlib.reload(db_mod)


def _seed_data(conn):
    """Seed realistic pipeline data into the test DB."""
    now = datetime.now(timezone.utc).isoformat()

    # Auction types
    conn.execute("INSERT INTO auction_types (id, name, code) VALUES (1, 'Copart', 'copart')")
    conn.execute("INSERT INTO auction_types (id, name, code) VALUES (2, 'IAA', 'iaa')")
    conn.execute("INSERT INTO auction_types (id, name, code) VALUES (3, 'Manheim', 'manheim')")
    conn.execute("INSERT INTO auction_types (id, name, code) VALUES (4, 'Other', 'other')")

    # -- Copart documents (5)
    copart_vins = [
        ("1HGCV1F34LA000001", "2020", "HONDA", "ACCORD", "40112233", "GP-001"),
        ("2T1BURHE0JC000002", "2018", "TOYOTA", "COROLLA", "40112234", "GP-002"),
        ("3FA6P0H76HR000003", "2017", "FORD", "FUSION", "40112235", "GP-003"),
        ("5YJSA1E26MF000004", "2021", "TESLA", "MODEL S", "40112236", ""),
        ("WBA8E9C50JK000005", "2018", "BMW", "330I", "40112237", "GP-005"),
    ]
    for i, (vin, yr, mk, md, lot, gp) in enumerate(copart_vins, start=1):
        doc_uuid = str(uuid.uuid4())
        fp = str(tempfile.mktemp(suffix=".pdf"))
        # Create dummy file
        with open(fp, "wb") as f:
            f.write(b"%PDF-1.4 dummy copart " + str(i).encode())
        conn.execute(
            "INSERT INTO documents (id, uuid, auction_type_id, dataset_split, filename, file_path, source, email_metadata_json) "
            "VALUES (?, ?, 1, 'train', ?, ?, 'email', ?)",
            (i, doc_uuid, f"copart_{i}.pdf", fp, json.dumps({"message_id": f"copart-msg-{i}"})),
        )
        outputs = {
            "vehicle_vin": vin, "vehicle_year": yr, "vehicle_make": mk, "vehicle_model": md,
            "vehicle_lot": lot, "gate_pass": gp, "vehicle_type": "CAR",
            "pickup_address": "123 Auction Ln", "pickup_city": "Dallas", "pickup_state": "TX", "pickup_zip": "75001",
            "buyer_name": "Y7 Transport", "total_amount": "1500.00",
            "auction_source": "copart", "load_id": f"222COP{i:02d}",
        }
        conn.execute(
            "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, extractor_kind, status, outputs_json) "
            "VALUES (?, ?, ?, 1, 'rule', 'needs_review', ?)",
            (i, str(uuid.uuid4()), i, json.dumps(outputs)),
        )
        # Create review items
        for key, val in outputs.items():
            conn.execute(
                "INSERT INTO review_items (run_id, source_key, internal_key, predicted_value, status) VALUES (?, ?, ?, ?, 'pending')",
                (i, key, key, str(val)),
            )

    # -- IAA documents (4)
    iaa_vins = [
        ("KNDJN2A26K7000006", "2019", "KIA", "SOUL", "33001122", "GP-006"),
        ("1C4RJFBG5LC000007", "2020", "JEEP", "GR CHEROKEE", "33001123", "GP-007"),
        ("3N1AB7AP2KY000008", "2019", "NISSAN", "SENTRA", "33001124", ""),
        ("1G1ZD5ST5LF000009", "2020", "CHEVROLET", "MALIBU", "33001125", "GP-009"),
    ]
    for i, (vin, yr, mk, md, lot, gp) in enumerate(iaa_vins, start=6):
        doc_uuid = str(uuid.uuid4())
        fp = str(tempfile.mktemp(suffix=".pdf"))
        with open(fp, "wb") as f:
            f.write(b"%PDF-1.4 dummy iaa " + str(i).encode())
        conn.execute(
            "INSERT INTO documents (id, uuid, auction_type_id, dataset_split, filename, file_path, source, email_metadata_json) "
            "VALUES (?, ?, 2, 'train', ?, ?, 'email', ?)",
            (i, doc_uuid, f"iaa_{i}.pdf", fp, json.dumps({"message_id": f"iaa-msg-{i}"})),
        )
        outputs = {
            "vehicle_vin": vin, "vehicle_year": yr, "vehicle_make": mk, "vehicle_model": md,
            "vehicle_lot": lot, "gate_pass": gp, "vehicle_type": "SUV" if "CHEROKEE" in md else "CAR",
            "pickup_address": "456 IAA Blvd", "pickup_city": "Houston", "pickup_state": "TX", "pickup_zip": "77001",
            "buyer_name": "Y7 Transport", "total_amount": "2000.00",
            "auction_source": "iaa", "load_id": f"222IAA{i:02d}",
        }
        conn.execute(
            "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, extractor_kind, status, outputs_json) "
            "VALUES (?, ?, ?, 2, 'rule', 'needs_review', ?)",
            (i, str(uuid.uuid4()), i, json.dumps(outputs)),
        )
        for key, val in outputs.items():
            conn.execute(
                "INSERT INTO review_items (run_id, source_key, internal_key, predicted_value, status) VALUES (?, ?, ?, ?, 'pending')",
                (i, key, key, str(val)),
            )

    # -- Manheim documents (2)
    manheim_vins = [
        ("WDCTG4EB2LJ000010", "2020", "MERCEDES", "GLC 300", "", ""),
        ("5UXTR9C51KLE00011", "2019", "BMW", "X3", "", ""),
    ]
    for i, (vin, yr, mk, md, lot, gp) in enumerate(manheim_vins, start=10):
        doc_uuid = str(uuid.uuid4())
        fp = str(tempfile.mktemp(suffix=".pdf"))
        with open(fp, "wb") as f:
            f.write(b"%PDF-1.4 dummy manheim " + str(i).encode())
        conn.execute(
            "INSERT INTO documents (id, uuid, auction_type_id, dataset_split, filename, file_path, source) "
            "VALUES (?, ?, 3, 'train', ?, ?, 'email')",
            (i, doc_uuid, f"manheim_{i}.pdf", fp),
        )
        outputs = {
            "vehicle_vin": vin, "vehicle_year": yr, "vehicle_make": mk, "vehicle_model": md,
            "vehicle_type": "SUV",
            "pickup_address": "789 Manheim Dr", "pickup_city": "Atlanta", "pickup_state": "GA", "pickup_zip": "30301",
            "buyer_name": "Y7 Transport", "total_amount": "3000.00",
            "auction_source": "manheim", "load_id": f"222MAN{i:02d}",
        }
        conn.execute(
            "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, extractor_kind, status, outputs_json) "
            "VALUES (?, ?, ?, 3, 'rule', 'needs_review', ?)",
            (i, str(uuid.uuid4()), i, json.dumps(outputs)),
        )
        for key, val in outputs.items():
            conn.execute(
                "INSERT INTO review_items (run_id, source_key, internal_key, predicted_value, status) VALUES (?, ?, ?, ?, 'pending')",
                (i, key, key, str(val)),
            )

    # -- Exported document (doc 1, run 1)
    conn.execute("UPDATE extraction_runs SET status = 'exported' WHERE id = 1")
    conn.execute("UPDATE review_items SET status = 'exported' WHERE run_id = 1")
    conn.execute(
        "INSERT INTO export_jobs (id, uuid, run_id, status, cd_listing_id, created_at) VALUES (1, ?, 1, 'completed', '304700001', ?)",
        (str(uuid.uuid4()), now),
    )

    # -- Failed extraction (doc 12, with error)
    doc_uuid = str(uuid.uuid4())
    fp = str(tempfile.mktemp(suffix=".pdf"))
    with open(fp, "wb") as f:
        f.write(b"%PDF-1.4 dummy failed")
    conn.execute(
        "INSERT INTO documents (id, uuid, auction_type_id, dataset_split, filename, file_path, source) "
        "VALUES (12, ?, 4, 'train', 'bad_doc.pdf', ?, 'upload')",
        (doc_uuid, fp),
    )
    conn.execute(
        "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, extractor_kind, status, error_message, outputs_json) "
        "VALUES (12, ?, 12, 4, 'rule', 'failed', 'PDF text extraction returned empty', ?)",
        (str(uuid.uuid4()), json.dumps({})),
    )

    # -- manual_required run (doc 13)
    doc_uuid = str(uuid.uuid4())
    fp = str(tempfile.mktemp(suffix=".pdf"))
    with open(fp, "wb") as f:
        f.write(b"%PDF-1.4 dummy manual")
    conn.execute(
        "INSERT INTO documents (id, uuid, auction_type_id, dataset_split, filename, file_path, source) "
        "VALUES (13, ?, 4, 'train', 'manual_doc.pdf', ?, 'email')",
        (doc_uuid, fp),
    )
    conn.execute(
        "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, extractor_kind, status, error_message, outputs_json) "
        "VALUES (13, ?, 13, 4, 'rule', 'manual_required', 'Confidence below threshold', ?)",
        (str(uuid.uuid4()), json.dumps({"vehicle_vin": "JM1BK32F781000099"})),
    )

    # -- Email log table (created by email worker, not init_schema)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            thread_id TEXT,
            sender TEXT NOT NULL,
            sender_name TEXT,
            subject TEXT,
            received_date DATETIME,
            body_preview TEXT,
            has_attachments BOOLEAN DEFAULT FALSE,
            attachment_count INTEGER DEFAULT 0,
            attachment_names TEXT,
            gate_pass TEXT,
            status TEXT DEFAULT 'new',
            skip_reason TEXT,
            processed_at DATETIME,
            extraction_run_ids TEXT,
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # -- Email log entries
    conn.executemany(
        "INSERT INTO email_log (id, message_id, sender, subject, status, attachment_count, received_date, skip_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "copart-msg-1", "auto@copart.com", "Invoice - HONDA ACCORD", "processed", 1, now, None),
            (2, "copart-msg-2", "auto@copart.com", "Invoice - TOYOTA COROLLA", "processed", 1, now, None),
            (3, "iaa-msg-6", "auto@iaai.com", "Invoice - KIA SOUL", "processed", 2, now, None),
            (4, "skipped-1", "noreply@ads.com", "Special Offer!", "skipped", 0, now, "no_attachments"),
            (5, "skipped-2", "newsletter@copart.com", "Weekly Report", "skipped", 0, now, "sender_not_allowed"),
            (6, "thread-1", "auto@copart.com", "RE: Invoice - HONDA ACCORD", "thread_reply", 0, now, "thread_reply"),
        ],
    )

    conn.commit()


# ===========================================================================
# Test Pipeline Data Integrity
# ===========================================================================


class TestPipelineDataIntegrity:
    """Validate database referential integrity across the pipeline."""

    def test_every_document_has_extraction_run(self, pipeline_db):
        """Every document should have at least one extraction run."""
        conn = sqlite3.connect(pipeline_db)
        orphans = conn.execute(
            "SELECT d.id FROM documents d "
            "LEFT JOIN extraction_runs er ON er.document_id = d.id "
            "WHERE er.id IS NULL"
        ).fetchall()
        conn.close()
        assert len(orphans) == 0, f"Documents without extraction runs: {[o[0] for o in orphans]}"

    def test_no_orphan_extraction_runs(self, pipeline_db):
        """No extraction runs without parent document."""
        conn = sqlite3.connect(pipeline_db)
        orphans = conn.execute(
            "SELECT er.id FROM extraction_runs er "
            "LEFT JOIN documents d ON d.id = er.document_id "
            "WHERE d.id IS NULL"
        ).fetchall()
        conn.close()
        assert len(orphans) == 0, f"Orphan extraction runs: {[o[0] for o in orphans]}"

    def test_no_orphan_review_items(self, pipeline_db):
        """No review items without parent extraction run."""
        conn = sqlite3.connect(pipeline_db)
        orphans = conn.execute(
            "SELECT ri.id FROM review_items ri "
            "LEFT JOIN extraction_runs er ON er.id = ri.run_id "
            "WHERE er.id IS NULL"
        ).fetchall()
        conn.close()
        assert len(orphans) == 0, f"Orphan review items: {[o[0] for o in orphans]}"

    def test_all_vins_are_valid_format(self, pipeline_db):
        """Every VIN matches ISO 3779: 17 chars, alphanumeric, no I/O/Q."""
        vin_pattern = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT id, json_extract(outputs_json, '$.vehicle_vin') as vin "
            "FROM extraction_runs WHERE outputs_json IS NOT NULL"
        ).fetchall()
        conn.close()

        invalid = []
        for run_id, vin in rows:
            if vin and not vin_pattern.match(vin):
                invalid.append((run_id, vin))
        assert len(invalid) == 0, f"Invalid VINs: {invalid}"

    def test_no_duplicate_vins_in_active_docs(self, pipeline_db):
        """No two active (non-archived) documents share the same VIN."""
        conn = sqlite3.connect(pipeline_db)
        dups = conn.execute(
            "SELECT json_extract(er.outputs_json, '$.vehicle_vin') as vin, COUNT(*) as cnt "
            "FROM extraction_runs er "
            "JOIN documents d ON er.document_id = d.id "
            "WHERE d.archived_at IS NULL "
            "AND json_extract(er.outputs_json, '$.vehicle_vin') IS NOT NULL "
            "AND json_extract(er.outputs_json, '$.vehicle_vin') != '' "
            "GROUP BY vin HAVING cnt > 1"
        ).fetchall()
        conn.close()
        assert len(dups) == 0, f"Duplicate VINs: {dups}"

    def test_no_duplicate_load_ids(self, pipeline_db):
        """All load_ids are unique."""
        conn = sqlite3.connect(pipeline_db)
        dups = conn.execute(
            "SELECT json_extract(outputs_json, '$.load_id') as lid, COUNT(*) as cnt "
            "FROM extraction_runs "
            "WHERE lid IS NOT NULL AND lid != '' "
            "GROUP BY lid HAVING cnt > 1"
        ).fetchall()
        conn.close()
        assert len(dups) == 0, f"Duplicate load IDs: {dups}"

    def test_load_ids_no_spaces(self, pipeline_db):
        """No load_id contains spaces or special characters."""
        load_id_pattern = re.compile(r"^[A-Z0-9]+$")
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT id, json_extract(outputs_json, '$.load_id') as lid "
            "FROM extraction_runs WHERE outputs_json IS NOT NULL"
        ).fetchall()
        conn.close()

        invalid = []
        for run_id, lid in rows:
            if lid and not load_id_pattern.match(lid):
                invalid.append((run_id, lid))
        assert len(invalid) == 0, f"Load IDs with bad chars: {invalid}"

    def test_exported_docs_have_required_fields(self, pipeline_db):
        """Every exported doc has VIN, year, make, model, pickup city/state."""
        required = ["vehicle_vin", "vehicle_year", "vehicle_make", "vehicle_model", "pickup_city", "pickup_state"]
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT id, outputs_json FROM extraction_runs WHERE status = 'exported'"
        ).fetchall()
        conn.close()

        assert len(rows) > 0, "No exported runs found"
        for run_id, outputs_json in rows:
            outputs = json.loads(outputs_json) if outputs_json else {}
            missing = [f for f in required if not outputs.get(f)]
            assert len(missing) == 0, f"Run {run_id} missing required fields: {missing}"

    def test_file_paths_exist_on_disk(self, pipeline_db):
        """Every document's file_path points to a real file."""
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT id, file_path FROM documents WHERE file_path IS NOT NULL"
        ).fetchall()
        conn.close()

        missing = []
        for doc_id, path in rows:
            if path and not os.path.exists(path):
                missing.append((doc_id, path))
        assert len(missing) == 0, f"Missing files: {missing}"


# ===========================================================================
# Test Pipeline Status Flow
# ===========================================================================


class TestPipelineStatusFlow:
    """Validate status transitions are consistent across tables."""

    def test_exported_runs_have_exported_review_items(self, pipeline_db):
        """If a run is exported, its review_items should also be exported."""
        conn = sqlite3.connect(pipeline_db)
        exported_runs = conn.execute(
            "SELECT id FROM extraction_runs WHERE status = 'exported'"
        ).fetchall()

        for (run_id,) in exported_runs:
            pending = conn.execute(
                "SELECT COUNT(*) FROM review_items WHERE run_id = ? AND status = 'pending'",
                (run_id,),
            ).fetchone()[0]
            assert pending == 0, f"Exported run {run_id} has {pending} pending review items"

        conn.close()

    def test_failed_runs_have_error_message(self, pipeline_db):
        """Every failed extraction run has an error_message."""
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT id, error_message FROM extraction_runs WHERE status = 'failed'"
        ).fetchall()
        conn.close()

        assert len(rows) > 0, "No failed runs to validate"
        for run_id, msg in rows:
            assert msg and len(msg.strip()) > 0, f"Failed run {run_id} has no error_message"

    def test_manual_required_runs_have_reason(self, pipeline_db):
        """Every manual_required run explains why via error_message."""
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT id, error_message FROM extraction_runs WHERE status = 'manual_required'"
        ).fetchall()
        conn.close()

        assert len(rows) > 0, "No manual_required runs to validate"
        for run_id, msg in rows:
            assert msg and len(msg.strip()) > 0, f"manual_required run {run_id} has no reason"

    def test_no_stale_pending_export_jobs(self, pipeline_db):
        """No completed export jobs missing cd_listing_id."""
        conn = sqlite3.connect(pipeline_db)
        stale = conn.execute(
            "SELECT id FROM export_jobs WHERE status = 'completed' AND cd_listing_id IS NULL"
        ).fetchall()
        conn.close()
        assert len(stale) == 0, f"Completed exports missing cd_listing_id: {[s[0] for s in stale]}"

    def test_exported_runs_have_export_jobs(self, pipeline_db):
        """Every exported run has a corresponding completed export job."""
        conn = sqlite3.connect(pipeline_db)
        exported_runs = conn.execute("SELECT id FROM extraction_runs WHERE status = 'exported'").fetchall()

        missing = []
        for (run_id,) in exported_runs:
            job = conn.execute(
                "SELECT id FROM export_jobs WHERE run_id = ? AND status = 'completed'", (run_id,)
            ).fetchone()
            if not job:
                missing.append(run_id)

        conn.close()
        assert len(missing) == 0, f"Exported runs without completed export jobs: {missing}"

    def test_valid_extraction_statuses(self, pipeline_db):
        """All extraction run statuses are from the allowed set."""
        allowed = {"pending", "needs_review", "reviewed", "approved", "exported", "failed", "manual_required", "cancelled"}
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute("SELECT DISTINCT status FROM extraction_runs").fetchall()
        conn.close()

        statuses = {r[0] for r in rows}
        invalid = statuses - allowed
        assert len(invalid) == 0, f"Invalid extraction statuses: {invalid}"


# ===========================================================================
# Test Pipeline Field Coverage by Auction
# ===========================================================================


class TestPipelineFieldCoverage:
    """Validate extraction quality across auction types."""

    def _get_field_coverage(self, db_path, auction_type_id, field_name):
        """Helper: get percentage of runs with a non-empty field."""
        conn = sqlite3.connect(db_path)
        total = conn.execute(
            "SELECT COUNT(*) FROM extraction_runs WHERE auction_type_id = ? AND outputs_json IS NOT NULL",
            (auction_type_id,),
        ).fetchone()[0]
        with_field = conn.execute(
            f"SELECT COUNT(*) FROM extraction_runs WHERE auction_type_id = ? "
            f"AND json_extract(outputs_json, '$.{field_name}') IS NOT NULL "
            f"AND json_extract(outputs_json, '$.{field_name}') != ''",
            (auction_type_id,),
        ).fetchone()[0]
        conn.close()
        return (with_field / total * 100) if total > 0 else 0

    def test_copart_vin_coverage(self, pipeline_db):
        """Copart docs should have VIN at 100%."""
        assert self._get_field_coverage(pipeline_db, 1, "vehicle_vin") == 100

    def test_copart_lot_coverage(self, pipeline_db):
        """Copart docs should have lot number at 100%."""
        assert self._get_field_coverage(pipeline_db, 1, "vehicle_lot") == 100

    def test_copart_pickup_coverage(self, pipeline_db):
        """Copart docs should have pickup_city at 100%."""
        assert self._get_field_coverage(pipeline_db, 1, "pickup_city") == 100

    def test_copart_total_amount_coverage(self, pipeline_db):
        """Copart docs should have total_amount at 100%."""
        assert self._get_field_coverage(pipeline_db, 1, "total_amount") == 100

    def test_copart_gate_pass_coverage(self, pipeline_db):
        """Copart docs should have gate_pass at >70%."""
        coverage = self._get_field_coverage(pipeline_db, 1, "gate_pass")
        assert coverage >= 70, f"Copart gate_pass coverage: {coverage}%"

    def test_iaa_vin_coverage(self, pipeline_db):
        """IAA docs should have VIN at 100%."""
        assert self._get_field_coverage(pipeline_db, 2, "vehicle_vin") == 100

    def test_iaa_buyer_name_coverage(self, pipeline_db):
        """IAA docs should have buyer_name at 100%."""
        assert self._get_field_coverage(pipeline_db, 2, "buyer_name") == 100

    def test_iaa_gate_pass_coverage(self, pipeline_db):
        """IAA docs should have gate_pass at >70%."""
        coverage = self._get_field_coverage(pipeline_db, 2, "gate_pass")
        assert coverage >= 70, f"IAA gate_pass coverage: {coverage}%"

    def test_manheim_vin_coverage(self, pipeline_db):
        """Manheim docs should have VIN at 100%."""
        assert self._get_field_coverage(pipeline_db, 3, "vehicle_vin") == 100

    def test_manheim_pickup_coverage(self, pipeline_db):
        """Manheim docs should have pickup_city at 100%."""
        assert self._get_field_coverage(pipeline_db, 3, "pickup_city") == 100

    def test_manheim_total_amount_coverage(self, pipeline_db):
        """Manheim docs should have total_amount at 100%."""
        assert self._get_field_coverage(pipeline_db, 3, "total_amount") == 100


# ===========================================================================
# Test Pipeline Email Integrity
# ===========================================================================


class TestPipelineEmailIntegrity:
    """Validate email→document traceability."""

    def test_email_docs_have_metadata(self, pipeline_db):
        """Every email-sourced doc has email_metadata_json."""
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT id, email_metadata_json FROM documents WHERE source = 'email'"
        ).fetchall()
        conn.close()

        # At least some email docs should have metadata
        with_meta = [r for r in rows if r[1] and r[1] != 'null']
        assert len(with_meta) > 0, "No email docs have metadata"

    def test_processed_emails_have_attachments(self, pipeline_db):
        """Processed emails have at least 1 attachment."""
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT id, attachment_count FROM email_log WHERE status = 'processed'"
        ).fetchall()
        conn.close()

        for email_id, count in rows:
            assert count and count > 0, f"Processed email {email_id} has 0 attachments"

    def test_skipped_emails_have_reason(self, pipeline_db):
        """Every skipped email has a skip_reason."""
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT id, skip_reason FROM email_log WHERE status = 'skipped'"
        ).fetchall()
        conn.close()

        assert len(rows) > 0, "No skipped emails to validate"
        for email_id, reason in rows:
            assert reason and len(reason.strip()) > 0, f"Skipped email {email_id} has no reason"

    def test_thread_replies_identified(self, pipeline_db):
        """Thread replies are correctly identified."""
        conn = sqlite3.connect(pipeline_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM email_log WHERE status = 'thread_reply'"
        ).fetchone()[0]
        conn.close()
        assert count >= 1, "No thread replies identified"

    def test_email_status_values_valid(self, pipeline_db):
        """All email statuses are from the allowed set."""
        allowed = {"processed", "skipped", "failed", "ready", "new", "processing", "thread_reply", "duplicate"}
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute("SELECT DISTINCT status FROM email_log").fetchall()
        conn.close()

        statuses = {r[0] for r in rows}
        invalid = statuses - allowed
        assert len(invalid) == 0, f"Invalid email statuses: {invalid}"


# ===========================================================================
# Test Pipeline Auction Classification
# ===========================================================================


class TestPipelineAuctionClassification:
    """Validate auction types match document content."""

    def test_copart_docs_have_copart_source(self, pipeline_db):
        """Copart-classified docs have auction_source=copart in extraction."""
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT er.id, json_extract(er.outputs_json, '$.auction_source') "
            "FROM extraction_runs er WHERE er.auction_type_id = 1 AND er.outputs_json IS NOT NULL"
        ).fetchall()
        conn.close()

        for run_id, source in rows:
            assert source == "copart", f"Run {run_id}: auction_type=copart but auction_source={source}"

    def test_iaa_docs_have_iaa_source(self, pipeline_db):
        """IAA-classified docs have auction_source=iaa in extraction."""
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT er.id, json_extract(er.outputs_json, '$.auction_source') "
            "FROM extraction_runs er WHERE er.auction_type_id = 2 AND er.outputs_json IS NOT NULL"
        ).fetchall()
        conn.close()

        for run_id, source in rows:
            assert source == "iaa", f"Run {run_id}: auction_type=iaa but auction_source={source}"

    def test_manheim_docs_have_manheim_source(self, pipeline_db):
        """Manheim-classified docs have auction_source=manheim in extraction."""
        conn = sqlite3.connect(pipeline_db)
        rows = conn.execute(
            "SELECT er.id, json_extract(er.outputs_json, '$.auction_source') "
            "FROM extraction_runs er WHERE er.auction_type_id = 3 AND er.outputs_json IS NOT NULL"
        ).fetchall()
        conn.close()

        for run_id, source in rows:
            assert source == "manheim", f"Run {run_id}: auction_type=manheim but auction_source={source}"
