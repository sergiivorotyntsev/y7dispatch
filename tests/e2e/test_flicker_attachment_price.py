"""
E2E Tests — Documents flicker fix, attachment handling, price display.

Tests:
- Attachment endpoint serves correct media type for images vs PDFs
- Price field persists through approval (final_price → price_total in API response)
- Image attachments tracked in EmailMessage dataclass
- Price 0 not treated as falsy (explicit None checks)
- Email context returns view_url + type for all attachments
"""

import json
import mimetypes
import os
import sqlite3
import uuid as uuid_mod
from pathlib import Path
from unittest.mock import patch

import pytest


# ===========================================================================
# Test Price Display After Approval
# ===========================================================================

class TestPriceDisplay:
    """Verify price_total includes final_price from approval flow."""

    def test_final_price_returned_as_price_total(self, client):
        """After setting final_price in outputs_json, documents API should return it as price_total."""
        from api.database import get_connection

        # Create a document + extraction run with only final_price
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO documents (id, uuid, auction_type_id, filename, file_path, dataset_split) VALUES (9901, '99010000-0000-0000-0000-000000009901', 1, 'price_test.pdf', '/tmp/price_test.pdf', 'train')"
            )
            outputs = json.dumps({
                "vehicle_vin": "TEST1234567890VIN",
                "vehicle_make": "Honda",
                "vehicle_model": "Civic",
                "final_price": 850.0,
            })
            conn.execute(
                "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json) VALUES (9901, '99010000-0000-0000-0000-0000000r9901', 1, 9901, 'approved', ?)",
                (outputs,),
            )
            conn.commit()

        resp = client.get("/api/documents?limit=500")
        assert resp.status_code == 200
        docs = resp.json().get("items", [])
        doc = next((d for d in docs if d.get("id") == 9901), None)
        assert doc is not None, f"Document 9901 not found. Got {len(docs)} docs, IDs: {[d['id'] for d in docs[:10]]}"
        assert doc.get("price_total") == 850.0

    def test_price_total_takes_precedence_over_final_price(self, client):
        """If both price_total and final_price exist, price_total wins."""
        from api.database import get_connection

        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO documents (id, uuid, auction_type_id, filename, file_path, dataset_split) VALUES (9902, '99020000-0000-0000-0000-000000009902', 1, 'price_both.pdf', '/tmp/price_both.pdf', 'train')"
            )
            outputs = json.dumps({
                "vehicle_vin": "TEST9876543210VIN",
                "vehicle_make": "Ford",
                "vehicle_model": "Focus",
                "price_total": 1200.0,
                "final_price": 850.0,
            })
            conn.execute(
                "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json) VALUES (9902, '99020000-0000-0000-0000-0000000r9902', 1, 9902, 'approved', ?)",
                (outputs,),
            )
            conn.commit()

        resp = client.get("/api/documents?limit=500")
        docs = resp.json().get("items", [])
        doc = next((d for d in docs if d.get("id") == 9902), None)
        assert doc is not None
        assert doc.get("price_total") == 1200.0

    def test_total_amount_fallback(self, client):
        """If only total_amount exists, it should be returned as price_total."""
        from api.database import get_connection

        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO documents (id, uuid, auction_type_id, filename, file_path, dataset_split) VALUES (9903, '99030000-0000-0000-0000-000000009903', 1, 'amount_test.pdf', '/tmp/amount_test.pdf', 'train')"
            )
            outputs = json.dumps({
                "vehicle_vin": "AMOUNTTEST1234567",
                "vehicle_make": "Chevy",
                "vehicle_model": "Malibu",
                "total_amount": 600.0,
            })
            conn.execute(
                "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json) VALUES (9903, '99030000-0000-0000-0000-0000000r9903', 1, 9903, 'approved', ?)",
                (outputs,),
            )
            conn.commit()

        resp = client.get("/api/documents?limit=500")
        docs = resp.json().get("items", [])
        doc = next((d for d in docs if d.get("id") == 9903), None)
        assert doc is not None
        assert doc.get("price_total") == 600.0

    def test_no_price_returns_null(self, client):
        """If no price field at all, price_total should be null."""
        from api.database import get_connection

        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO documents (id, uuid, auction_type_id, filename, file_path, dataset_split) VALUES (9904, '99040000-0000-0000-0000-000000009904', 1, 'no_price.pdf', '/tmp/no_price.pdf', 'train')"
            )
            outputs = json.dumps({
                "vehicle_vin": "NOPRICE123456789",
                "vehicle_make": "Kia",
                "vehicle_model": "Soul",
            })
            conn.execute(
                "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json) VALUES (9904, '99040000-0000-0000-0000-0000000r9904', 1, 9904, 'completed', ?)",
                (outputs,),
            )
            conn.commit()

        resp = client.get("/api/documents?limit=500")
        docs = resp.json().get("items", [])
        doc = next((d for d in docs if d.get("id") == 9904), None)
        assert doc is not None
        assert doc.get("price_total") is None


# ===========================================================================
# Test Attachment Media Type Serving
# ===========================================================================

class TestAttachmentMediaType:
    """Attachment download endpoint serves correct media type."""

    def test_pdf_media_type(self):
        """PDF files should be served with application/pdf media type."""
        media_type, _ = mimetypes.guess_type("test_file.pdf")
        assert media_type == "application/pdf"

    def test_png_media_type(self):
        """PNG files should be detected as image/png."""
        media_type, _ = mimetypes.guess_type("photo.png")
        assert media_type == "image/png"

    def test_jpg_media_type(self):
        """JPG files should be detected as image/jpeg."""
        media_type, _ = mimetypes.guess_type("photo.jpg")
        assert media_type == "image/jpeg"

    def test_unknown_extension(self):
        """Unknown extensions get None from mimetypes (our code falls back to octet-stream)."""
        media_type, _ = mimetypes.guess_type("file.xyz123")
        assert media_type is None

    def test_attachment_download_serves_png_with_correct_type(self, client):
        """Actual download endpoint serves PNG with image/png content type."""
        from api.database import get_connection

        att_dir = Path("data/attachments/9990")
        att_dir.mkdir(parents=True, exist_ok=True)

        # Minimal valid PNG (1x1 pixel)
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
            b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
            b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        (att_dir / "test_image.png").write_bytes(png_bytes)

        try:
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json, attachments_json) VALUES (9990, '99900000-0000-0000-0000-0000000r9990', 1, 9901, 'completed', '{}', ?)",
                    (json.dumps([{
                        "filename": "test_image.png",
                        "original_filename": "Test Image.png",
                        "type": "image",
                        "url": "/api/documents/9990/attachments/test_image.png",
                    }]),),
                )
                conn.commit()

            resp = client.get("/api/documents/9990/attachments/test_image.png")
            assert resp.status_code == 200
            assert "image/png" in resp.headers.get("content-type", "")
        finally:
            (att_dir / "test_image.png").unlink(missing_ok=True)
            try:
                att_dir.rmdir()
            except OSError:
                pass

    def test_attachment_list_includes_images(self, client):
        """List attachments endpoint returns image type attachments."""
        from api.database import get_connection

        with get_connection() as conn:
            attachments = [
                {"filename": "invoice.pdf", "original_filename": "Invoice.pdf", "type": "listing_page", "url": "/api/documents/9990/attachments/invoice.pdf"},
                {"filename": "photo.png", "original_filename": "Photo.png", "type": "image", "url": "/api/documents/9990/attachments/photo.png"},
            ]
            conn.execute(
                "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json, attachments_json) VALUES (9990, '99900000-0000-0000-0000-0000000r9990', 1, 9901, 'completed', '{}', ?)",
                (json.dumps(attachments),),
            )
            conn.commit()

        resp = client.get("/api/documents/9990/attachments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["attachments"]) == 2
        types = [a["type"] for a in data["attachments"]]
        assert "image" in types
        assert "listing_page" in types


# ===========================================================================
# Test EmailMessage Image Filename Collection
# ===========================================================================

class TestEmailImageFilenames:
    """Verify EmailMessage dataclass collects image filenames from emails."""

    def test_email_message_has_image_filenames_field(self):
        """EmailMessage should have image_filenames attribute."""
        from api.workers.email_worker import EmailMessage
        import dataclasses
        fields = {f.name for f in dataclasses.fields(EmailMessage)}
        assert "image_filenames" in fields

    def _build_email_with_attachments(self, message_id, parts):
        """Build raw email bytes with given parts.

        Each part: (content_type_main, content_type_sub, filename, disposition)
        """
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart()
        msg["Message-ID"] = message_id
        msg["Subject"] = "Test email"
        msg["From"] = "test@example.com"
        msg["Date"] = "Sat, 22 Feb 2026 10:00:00 -0500"

        for main_type, sub_type, filename, disposition in parts:
            part = MIMEBase(main_type, sub_type)
            part.set_payload(b'\x00' * 10)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", disposition, filename=filename)
            msg.attach(part)

        return msg.as_bytes()

    def test_png_attachment_collected(self):
        """PNG attachment with Content-Disposition: attachment should be collected."""
        from api.workers.email_worker import EmailWorker

        raw = self._build_email_with_attachments(
            "<png@test.com>",
            [("image", "png", "photo.png", "attachment")],
        )
        worker = EmailWorker()
        parsed = worker._parse_message("123", raw)
        assert "photo.png" in parsed.image_filenames
        assert len(parsed.pdf_filenames) == 0

    def test_jpg_attachment_collected(self):
        """JPG attachment should be collected."""
        from api.workers.email_worker import EmailWorker

        raw = self._build_email_with_attachments(
            "<jpg@test.com>",
            [("image", "jpeg", "vehicle.jpg", "attachment")],
        )
        worker = EmailWorker()
        parsed = worker._parse_message("456", raw)
        assert "vehicle.jpg" in parsed.image_filenames

    def test_mixed_pdf_and_image(self):
        """Mixed PDF+image emails separate into correct lists."""
        from api.workers.email_worker import EmailWorker

        raw = self._build_email_with_attachments(
            "<mixed@test.com>",
            [
                ("application", "pdf", "invoice.pdf", "attachment"),
                ("image", "png", "scan.png", "attachment"),
            ],
        )
        worker = EmailWorker()
        parsed = worker._parse_message("789", raw)
        assert "invoice.pdf" in parsed.pdf_filenames
        assert "scan.png" in parsed.image_filenames
        assert len(parsed.pdf_filenames) == 1
        assert len(parsed.image_filenames) == 1

    def test_inline_images_not_collected(self):
        """Inline images (Content-Disposition: inline) should be ignored."""
        from api.workers.email_worker import EmailWorker

        raw = self._build_email_with_attachments(
            "<inline@test.com>",
            [("image", "png", "logo.png", "inline")],
        )
        worker = EmailWorker()
        parsed = worker._parse_message("000", raw)
        assert len(parsed.image_filenames) == 0


# ===========================================================================
# Test Price Zero Not Treated as Falsy
# ===========================================================================

class TestPriceZeroNotFalsy:
    """Verify price_total=0 is returned as 0.0, not replaced by fallback."""

    def test_price_total_zero_not_overridden_by_final_price(self, client):
        """price_total=0 should be returned as 0.0, not fall through to final_price."""
        from api.database import get_connection

        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO documents (id, uuid, auction_type_id, filename, file_path, dataset_split) "
                "VALUES (9910, '99100000-0000-0000-0000-000000009910', 1, 'zero_price.pdf', '/tmp/zero_price.pdf', 'train')"
            )
            outputs = json.dumps({
                "vehicle_vin": "ZEROPRICE12345678",
                "vehicle_make": "BMW",
                "vehicle_model": "X3",
                "price_total": 0,
                "final_price": 999.0,
            })
            conn.execute(
                "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json) "
                "VALUES (9910, '99100000-0000-0000-0000-0000000r9910', 1, 9910, 'approved', ?)",
                (outputs,),
            )
            conn.commit()

        resp = client.get("/api/documents?limit=500")
        docs = resp.json().get("items", [])
        doc = next((d for d in docs if d.get("id") == 9910), None)
        assert doc is not None, "Document 9910 not found"
        assert doc.get("price_total") == 0.0, f"Expected 0.0 but got {doc.get('price_total')}"

    def test_final_price_zero_not_overridden_by_total_amount(self, client):
        """final_price=0 (no price_total) should be returned as 0.0, not fall through to total_amount."""
        from api.database import get_connection

        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO documents (id, uuid, auction_type_id, filename, file_path, dataset_split) "
                "VALUES (9911, '99110000-0000-0000-0000-000000009911', 1, 'zero_final.pdf', '/tmp/zero_final.pdf', 'train')"
            )
            outputs = json.dumps({
                "vehicle_vin": "ZEROFINAL12345678",
                "vehicle_make": "Audi",
                "vehicle_model": "A4",
                "final_price": 0,
                "total_amount": 500.0,
            })
            conn.execute(
                "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json) "
                "VALUES (9911, '99110000-0000-0000-0000-0000000r9911', 1, 9911, 'approved', ?)",
                (outputs,),
            )
            conn.commit()

        resp = client.get("/api/documents?limit=500")
        docs = resp.json().get("items", [])
        doc = next((d for d in docs if d.get("id") == 9911), None)
        assert doc is not None
        assert doc.get("price_total") == 0.0, f"Expected 0.0 but got {doc.get('price_total')}"


# ===========================================================================
# Test Email Context Attachment View URLs
# ===========================================================================

class TestEmailContextAttachmentUrls:
    """Verify email-context endpoint returns view_url and type for all attachments."""

    @pytest.fixture(autouse=True)
    def setup_email_data(self, client):
        """Set up email-sourced document with multiple attachments."""
        from api.database import get_connection

        with get_connection() as conn:
            # Create email_log table if needed
            conn.execute("""
                CREATE TABLE IF NOT EXISTS email_log (
                    id INTEGER PRIMARY KEY,
                    message_id TEXT,
                    sender TEXT,
                    subject TEXT,
                    body_preview TEXT,
                    attachment_names TEXT,
                    received_date TEXT,
                    extraction_run_ids TEXT,
                    status TEXT DEFAULT 'processed'
                )
            """)
            # Create document (email-sourced)
            conn.execute(
                "INSERT OR REPLACE INTO documents (id, uuid, auction_type_id, filename, file_path, dataset_split, source, email_metadata_json) "
                "VALUES (9920, '99200000-0000-0000-0000-000000009920', 1, 'invoice.pdf', '/tmp/invoice.pdf', 'train', 'email', ?)",
                (json.dumps({"sender": "test@auction.com", "subject": "Invoice", "date": "2026-02-22T10:00:00"}),)
            )
            # Create extraction run with attachments_json
            run_attachments = json.dumps([
                {"filename": "invoice.pdf", "original_filename": "Invoice.pdf", "type": "listing_page", "url": "/api/documents/9920/attachments/invoice.pdf"},
                {"filename": "photo.png", "original_filename": "Photo.png", "type": "image", "url": "/api/documents/9920/attachments/photo.png"},
            ])
            conn.execute(
                "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json, attachments_json) "
                "VALUES (9920, '99200000-0000-0000-0000-0000000r9920', 1, 9920, 'completed', '{}', ?)",
                (run_attachments,),
            )
            # Create email_log entry referencing this run
            conn.execute(
                "INSERT OR REPLACE INTO email_log (id, message_id, sender, subject, body_preview, attachment_names, received_date, extraction_run_ids) "
                "VALUES (9920, '<test9920@auction.com>', 'test@auction.com', 'Invoice for vehicle', 'Here is your invoice.', ?, '2026-02-22T10:00:00', ?)",
                (json.dumps(["invoice.pdf", "photo.png"]), json.dumps([9920])),
            )
            conn.commit()

    def test_email_context_returns_view_url_for_all_attachments(self, client):
        """Non-main attachments should get view_url from run attachments."""
        resp = client.get("/api/extractions/9920/email-context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "email"
        atts = data.get("attachments", [])
        assert len(atts) >= 2, f"Expected 2+ attachments, got {len(atts)}: {atts}"

        # All attachments should have a view_url (not null)
        for att in atts:
            assert att.get("view_url") is not None, f"Attachment {att['filename']} has no view_url"

    def test_email_context_returns_type_for_attachments(self, client):
        """Each attachment should have a type field (pdf, image, etc.)."""
        resp = client.get("/api/extractions/9920/email-context")
        data = resp.json()
        atts = data.get("attachments", [])

        types = {att["filename"]: att.get("type") for att in atts}
        # photo.png should be 'image', invoice.pdf should be 'listing_page' (from run) or 'pdf'
        assert types.get("photo.png") == "image", f"Expected 'image' for photo.png, got {types.get('photo.png')}"
        assert types.get("invoice.pdf") in ("pdf", "listing_page"), f"Expected pdf/listing_page for invoice.pdf, got {types.get('invoice.pdf')}"

    def test_main_document_has_document_file_url(self, client):
        """Main document attachment should link to /api/documents/{id}/file."""
        resp = client.get("/api/extractions/9920/email-context")
        data = resp.json()
        atts = data.get("attachments", [])

        main_att = next((a for a in atts if a.get("is_main_document")), None)
        assert main_att is not None, "No main document attachment found"
        assert "/api/documents/" in main_att["view_url"]
        assert main_att["view_url"].endswith("/file")


# ===========================================================================
# Test Attachment Serving — Inline (no Content-Disposition: attachment)
# ===========================================================================

class TestAttachmentInlineServing:
    """Verify attachments are served inline (not forced download)."""

    def test_pdf_served_without_attachment_disposition(self, client):
        """PDF should not have Content-Disposition: attachment (allows iframe display)."""
        from api.database import get_connection

        att_dir = Path("data/attachments/9950")
        att_dir.mkdir(parents=True, exist_ok=True)
        # Minimal PDF
        pdf_bytes = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
        (att_dir / "test_doc.pdf").write_bytes(pdf_bytes)

        try:
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json, attachments_json) "
                    "VALUES (9950, '99500000-0000-0000-0000-0000000r9950', 1, 9901, 'completed', '{}', ?)",
                    (json.dumps([{"filename": "test_doc.pdf", "original_filename": "Test Doc.pdf", "type": "listing_page", "url": "/api/documents/9950/attachments/test_doc.pdf"}]),),
                )
                conn.commit()

            resp = client.get("/api/documents/9950/attachments/test_doc.pdf")
            assert resp.status_code == 200
            assert "application/pdf" in resp.headers.get("content-type", "")
            # Should NOT have Content-Disposition: attachment
            cd = resp.headers.get("content-disposition", "")
            assert "attachment" not in cd.lower(), f"Content-Disposition forces download: {cd}"
        finally:
            (att_dir / "test_doc.pdf").unlink(missing_ok=True)
            try:
                att_dir.rmdir()
            except OSError:
                pass

    def test_png_served_without_attachment_disposition(self, client):
        """PNG should be served inline for img tag display."""
        att_dir = Path("data/attachments/9951")
        att_dir.mkdir(parents=True, exist_ok=True)
        # Minimal PNG
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
            b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
            b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        (att_dir / "photo.png").write_bytes(png_bytes)

        try:
            from api.database import get_connection
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO extraction_runs (id, uuid, auction_type_id, document_id, status, outputs_json, attachments_json) "
                    "VALUES (9951, '99510000-0000-0000-0000-0000000r9951', 1, 9901, 'completed', '{}', ?)",
                    (json.dumps([{"filename": "photo.png", "original_filename": "Photo.png", "type": "image", "url": "/api/documents/9951/attachments/photo.png"}]),),
                )
                conn.commit()

            resp = client.get("/api/documents/9951/attachments/photo.png")
            assert resp.status_code == 200
            assert "image/png" in resp.headers.get("content-type", "")
            cd = resp.headers.get("content-disposition", "")
            assert "attachment" not in cd.lower(), f"Content-Disposition forces download: {cd}"
        finally:
            (att_dir / "photo.png").unlink(missing_ok=True)
            try:
                att_dir.rmdir()
            except OSError:
                pass
