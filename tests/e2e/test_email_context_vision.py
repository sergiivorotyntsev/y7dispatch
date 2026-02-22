"""
E2E Tests for Email Context, Vision Extract, and Attachment Serving.

Tests cover:
  - GET /api/extractions/{run_id}/email-context
  - POST /api/extractions/{run_id}/vision-extract
  - Attachment serving via existing endpoints
"""

import importlib
import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures — isolated temp DB with email-linked documents
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def email_test_db(tmp_path):
    """Create a temp database seeded with email-linked documents."""
    import api.database as db_mod

    db_path = str(tmp_path / "email_test.db")
    with patch.dict(os.environ, {"DATABASE_PATH": db_path}):
        importlib.reload(db_mod)

        from api.models import init_schema
        init_schema()

        conn = sqlite3.connect(db_path)
        _seed_email_data(conn, tmp_path)
        conn.close()

        yield db_path

    # Restore module state
    importlib.reload(db_mod)


def _seed_email_data(conn, tmp_path):
    """Seed realistic email-linked documents + manual_required runs."""
    now = datetime.now(timezone.utc).isoformat()

    # Auction types
    conn.execute("INSERT INTO auction_types (id, name, code) VALUES (1, 'Copart', 'copart')")
    conn.execute("INSERT INTO auction_types (id, name, code) VALUES (2, 'IAA', 'iaa')")

    # Create a minimal PDF on disk
    pdf_path = str(tmp_path / "scanned_invoice.pdf")
    with open(pdf_path, "wb") as f:
        f.write(b"%PDF-1.4 scanned doc")

    upload_pdf_path = str(tmp_path / "uploaded_doc.pdf")
    with open(upload_pdf_path, "wb") as f:
        f.write(b"%PDF-1.4 uploaded doc")

    # Document 1: email-sourced, manual_required
    conn.execute(
        "INSERT INTO documents (id, uuid, auction_type_id, dataset_split, filename, file_path, source, email_metadata_json) "
        "VALUES (1, ?, 1, 'train', 'scanned_invoice.pdf', ?, 'email', ?)",
        (
            str(uuid.uuid4()),
            pdf_path,
            json.dumps({
                "sender": "Import USA <autausapl@gmail.com>",
                "subject": "2C4RC1EG0HR680901 Request a car pickup",
                "message_id": "<test-msg-001>",
                "date": "2026-02-12T10:30:00Z",
            }),
        ),
    )

    # Extraction run 1: manual_required (scanned PDF)
    conn.execute(
        "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, status, outputs_json, created_at) "
        "VALUES (1, ?, 1, 1, 'manual_required', ?, ?)",
        (str(uuid.uuid4()), json.dumps({"vehicle_vin": "2C4RC1EG0HR680901"}), now),
    )

    # Document 2: email-sourced, successful extraction
    conn.execute(
        "INSERT INTO documents (id, uuid, auction_type_id, dataset_split, filename, file_path, source, email_metadata_json) "
        "VALUES (2, ?, 1, 'train', 'copart_invoice.pdf', ?, 'email', ?)",
        (
            str(uuid.uuid4()),
            pdf_path,
            json.dumps({
                "sender": "billing@copart.com",
                "subject": "Invoice for lot 40112233",
                "message_id": "<test-msg-002>",
                "date": "2026-02-15T14:00:00Z",
            }),
        ),
    )

    # Extraction run 2: completed
    conn.execute(
        "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, status, outputs_json, created_at) "
        "VALUES (2, ?, 2, 1, 'completed', ?, ?)",
        (str(uuid.uuid4()), json.dumps({"vehicle_vin": "1HGCV1F34LA000001"}), now),
    )

    # Document 3: upload-sourced (no email)
    conn.execute(
        "INSERT INTO documents (id, uuid, auction_type_id, dataset_split, filename, file_path, source) "
        "VALUES (3, ?, 2, 'train', 'uploaded_doc.pdf', ?, 'upload')",
        (str(uuid.uuid4()), upload_pdf_path),
    )

    # Extraction run 3: completed (upload)
    conn.execute(
        "INSERT INTO extraction_runs (id, uuid, document_id, auction_type_id, status, outputs_json, created_at) "
        "VALUES (3, ?, 3, 2, 'completed', ?, ?)",
        (str(uuid.uuid4()), json.dumps({"vehicle_vin": "5YJSA1E26MF000004"}), now),
    )

    # email_log entries
    conn.execute("""CREATE TABLE IF NOT EXISTS email_log (
        id INTEGER PRIMARY KEY,
        message_id TEXT,
        thread_id TEXT,
        sender TEXT,
        sender_name TEXT,
        subject TEXT,
        received_date DATETIME,
        body_preview TEXT,
        has_attachments BOOLEAN,
        attachment_count INTEGER,
        attachment_names TEXT,
        gate_pass TEXT,
        status TEXT,
        skip_reason TEXT,
        processed_at DATETIME,
        extraction_run_ids TEXT,
        error_message TEXT,
        created_at DATETIME
    )""")

    conn.execute(
        "INSERT INTO email_log (id, message_id, sender, subject, body_preview, "
        "has_attachments, attachment_count, attachment_names, status, extraction_run_ids, created_at, received_date) "
        "VALUES (1, '<test-msg-001>', 'autausapl@gmail.com', "
        "'2C4RC1EG0HR680901 Request a car pickup', "
        "'Good morning,\\n\\nPlease arrange to pick up 1 car from the auction.\\nPlease see the attachment.\\n\\nThank you', "
        "1, 1, ?, 'processed', '[1]', ?, ?)",
        (
            json.dumps(["scanned_invoice.pdf"]),
            now,
            "2026-02-12T10:30:00",
        ),
    )

    conn.execute(
        "INSERT INTO email_log (id, message_id, sender, subject, body_preview, "
        "has_attachments, attachment_count, attachment_names, status, extraction_run_ids, created_at, received_date) "
        "VALUES (2, '<test-msg-002>', 'billing@copart.com', "
        "'Invoice for lot 40112233', "
        "'Your Copart invoice is attached.\\nLot: 40112233\\nTotal: $1,250.00', "
        "1, 1, ?, 'processed', '[2]', ?, ?)",
        (
            json.dumps(["copart_invoice.pdf"]),
            now,
            "2026-02-15T14:00:00",
        ),
    )

    conn.commit()


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------


class TestEmailContext:
    """Test GET /api/extractions/{run_id}/email-context."""

    def test_get_email_context_for_email_sourced_run(self):
        """Email-sourced run returns full email context."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/extractions/1/email-context")
        assert resp.status_code == 200
        data = resp.json()

        assert data["source"] == "email"
        assert "autausapl@gmail.com" in (data["sender"] or "")
        assert "2C4RC1EG0HR680901" in (data["subject"] or "")

    def test_email_context_includes_body(self):
        """Email context includes body text from email_log."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/extractions/1/email-context")
        data = resp.json()

        assert data["body"] is not None
        assert "pick up" in data["body"].lower()

    def test_email_context_includes_attachments(self):
        """Email context includes attachment list."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/extractions/1/email-context")
        data = resp.json()

        assert len(data["attachments"]) >= 1
        att = data["attachments"][0]
        assert "filename" in att
        assert "scanned_invoice.pdf" in att["filename"]

    def test_email_context_for_upload_source(self):
        """Upload-sourced document returns source=upload, no email data."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/extractions/3/email-context")
        assert resp.status_code == 200
        data = resp.json()

        assert data["source"] == "upload"
        assert data["sender"] is None
        assert data["body"] is None

    def test_email_context_404_for_nonexistent_run(self):
        """Non-existent run returns 404."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/extractions/9999/email-context")
        assert resp.status_code == 404

    def test_email_context_second_run(self):
        """Second email-sourced run also returns email context."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/extractions/2/email-context")
        assert resp.status_code == 200
        data = resp.json()

        assert data["source"] == "email"
        assert "copart" in (data["sender"] or "").lower() or "billing" in (data["sender"] or "").lower()


class TestVisionExtract:
    """Test POST /api/extractions/{run_id}/vision-extract."""

    def test_vision_extract_endpoint_exists(self):
        """Vision extract endpoint returns a response (not 404/405)."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        # Will fail with 500 (no real PDF / no API key) but endpoint exists
        resp = client.post("/api/extractions/1/vision-extract")
        assert resp.status_code != 404
        assert resp.status_code != 405

    def test_vision_extract_404_for_nonexistent_run(self):
        """Non-existent run returns 404."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.post("/api/extractions/9999/vision-extract")
        assert resp.status_code == 404

    def test_vision_extract_returns_fields_with_mock(self):
        """Vision extract returns extracted fields (mocked Haiku API)."""
        from fastapi.testclient import TestClient
        from api.main import app
        from services.haiku_extractor import HaikuExtractor

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "auction_type": "COPART",
            "vehicle_vin": "2C4RC1EG0HR680901",
            "vehicle_year": "2017",
            "vehicle_make": "CHRYSLER",
            "vehicle_model": "PACIFICA",
            "pickup_city": "DALLAS",
            "pickup_state": "TX",
        }))]
        mock_response.usage = MagicMock(
            input_tokens=1000,
            output_tokens=200,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )

        mock_anthropic_client = MagicMock()
        mock_anthropic_client.messages.create.return_value = mock_response

        with patch("fitz.open") as mock_fitz:
            # Mock PDF document with one page
            mock_page = MagicMock()
            mock_pix = MagicMock()
            mock_pix.tobytes.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
            mock_page.get_pixmap.return_value = mock_pix

            mock_doc = MagicMock()
            mock_doc.__len__ = lambda self: 1
            mock_doc.__getitem__ = lambda self, idx: mock_page
            mock_fitz.return_value = mock_doc

            # Patch the HaikuExtractor to have a test API key and mock client
            with patch.object(HaikuExtractor, "__init__", lambda self, **kw: None):
                # Pre-set instance attributes that __init__ would normally set
                original_new = HaikuExtractor.__new__

                def patched_new(cls, **kwargs):
                    inst = original_new(cls)
                    inst.api_key = "test-key"
                    inst._client = mock_anthropic_client
                    inst.enable_caching = False
                    return inst

                with patch.object(HaikuExtractor, "__new__", patched_new):
                    http_client = TestClient(app)
                    resp = http_client.post("/api/extractions/1/vision-extract")

        assert resp.status_code == 200
        data = resp.json()
        assert data["extraction_mode"] == "vision"
        assert "vehicle_vin" in data["fields"]
        assert data["fields"]["vehicle_vin"] == "2C4RC1EG0HR680901"

    def test_vision_extract_handles_fitz_unavailable(self):
        """Vision extract returns 500 when PyMuPDF is not installed."""
        from fastapi.testclient import TestClient
        from api.main import app

        with patch.dict("sys.modules", {"fitz": None}):
            client = TestClient(app)
            resp = client.post("/api/extractions/1/vision-extract")
            # Should fail gracefully (500) rather than crash
            assert resp.status_code == 500


class TestAttachmentServing:
    """Test existing attachment listing and serving endpoints."""

    def test_list_attachments_for_run(self):
        """List attachments returns a response for valid run."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/documents/1/attachments")
        assert resp.status_code == 200
        data = resp.json()
        assert "attachments" in data

    def test_404_for_missing_attachment_file(self):
        """Requesting a non-existent attachment file returns 404."""
        from fastapi.testclient import TestClient
        from api.main import app

        client = TestClient(app)
        resp = client.get("/api/documents/1/attachments/nonexistent.pdf")
        assert resp.status_code == 404


class TestManualRequiredFlow:
    """Test the manual_required status flow end-to-end."""

    def test_manual_required_run_has_outputs(self):
        """Manual required run still has outputs_json (e.g., VIN from email subject)."""
        from api.database import get_connection

        with get_connection() as conn:
            row = conn.execute(
                "SELECT outputs_json, status FROM extraction_runs WHERE id = 1"
            ).fetchone()

        assert row["status"] == "manual_required"
        outputs = json.loads(row["outputs_json"])
        assert "vehicle_vin" in outputs

    def test_manual_required_document_is_email_sourced(self):
        """Manual required document was sourced from email."""
        from api.database import get_connection

        with get_connection() as conn:
            row = conn.execute(
                "SELECT d.source FROM documents d "
                "JOIN extraction_runs er ON d.id = er.document_id "
                "WHERE er.id = 1"
            ).fetchone()

        assert row["source"] == "email"

    def test_email_metadata_on_document(self):
        """Document has email_metadata_json with sender and subject."""
        from api.database import get_connection

        with get_connection() as conn:
            row = conn.execute(
                "SELECT email_metadata_json FROM documents WHERE id = 1"
            ).fetchone()

        meta = json.loads(row["email_metadata_json"])
        assert "sender" in meta
        assert "subject" in meta
        assert "2C4RC1EG0HR680901" in meta["subject"]
