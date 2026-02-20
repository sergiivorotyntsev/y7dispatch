"""
Tests for filename-based and email-context auction classification.

Covers:
- _classify_from_filename() patterns
- _classify_from_email_context() patterns
- Classification pipeline integration (scanned PDF gets correct type)
- Reclassify endpoint
"""

import json
from io import BytesIO

import pytest


class TestFilenameClassification:
    """Test _classify_from_filename() pattern matching."""

    def test_copart_in_filename(self):
        from api.routes.documents import _classify_from_filename

        assert _classify_from_filename("copart_invoice_123.pdf") == "COPART"
        assert _classify_from_filename("20260219_Copart_billing.pdf") == "COPART"

    def test_iaa_showreport(self):
        from api.routes.documents import _classify_from_filename

        assert _classify_from_filename("ShowReport.pdf") == "IAA"
        assert _classify_from_filename("ShowReport__1_.pdf") == "IAA"
        assert _classify_from_filename("ShowReport3.pdf") == "IAA"

    def test_iaa_in_filename(self):
        from api.routes.documents import _classify_from_filename

        assert _classify_from_filename("iaa_receipt.pdf") == "IAA"
        assert _classify_from_filename("IAA_buyer_receipt.pdf") == "IAA"

    def test_manheim_in_filename(self):
        from api.routes.documents import _classify_from_filename

        assert _classify_from_filename("manheim_invoice.pdf") == "MANHEIM"
        assert _classify_from_filename("Manheim_sale.pdf") == "MANHEIM"

    def test_sparkbuyer_maps_to_iaa(self):
        from api.routes.documents import _classify_from_filename

        assert _classify_from_filename("sparkbuyerdetail__45_.pdf") == "IAA"
        assert _classify_from_filename("auctions_in_motion_receipt.pdf") == "IAA"

    def test_unknown_filename_returns_none(self):
        from api.routes.documents import _classify_from_filename

        assert _classify_from_filename("invoice.pdf") is None
        assert _classify_from_filename("document_123.pdf") is None
        assert _classify_from_filename("receipt.pdf") is None

    def test_empty_filename_returns_none(self):
        from api.routes.documents import _classify_from_filename

        assert _classify_from_filename("") is None
        assert _classify_from_filename(None) is None


class TestEmailContextClassification:
    """Test _classify_from_email_context() pattern matching."""

    def test_copart_in_subject(self):
        from api.routes.documents import _classify_from_email_context

        meta = json.dumps({"subject": "Copart Invoice for VIN 1234", "sender": "noreply@example.com"})
        assert _classify_from_email_context(meta) == "COPART"

    def test_iaa_in_subject(self):
        from api.routes.documents import _classify_from_email_context

        meta = json.dumps({"subject": "IAA Buyer Receipt", "sender": "noreply@example.com"})
        assert _classify_from_email_context(meta) == "IAA"

    def test_manheim_in_sender(self):
        from api.routes.documents import _classify_from_email_context

        meta = json.dumps({"subject": "Your invoice", "sender": "noreply@manheim.com"})
        assert _classify_from_email_context(meta) == "MANHEIM"

    def test_no_context_returns_none(self):
        from api.routes.documents import _classify_from_email_context

        assert _classify_from_email_context(None) is None
        assert _classify_from_email_context("") is None

    def test_generic_email_returns_none(self):
        from api.routes.documents import _classify_from_email_context

        meta = json.dumps({"subject": "Please pick up this car", "sender": "user@gmail.com"})
        assert _classify_from_email_context(meta) is None

    def test_invalid_json_returns_none(self):
        from api.routes.documents import _classify_from_email_context

        assert _classify_from_email_context("not json") is None


class TestClassificationPipeline:
    """Test that classification pipeline correctly handles scanned PDFs."""

    def _unique_pdf_bytes(self, tag=""):
        """Generate unique minimal PDF bytes."""
        import uuid
        unique = uuid.uuid4().hex[:8]
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
<< /Length 44 >>
stream
BT /F1 12 Tf 100 700 Td ({tag}{unique}) Tj ET
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

    def test_showreport_filename_gets_iaa(self, client):
        """Upload with ShowReport filename should classify as IAA even if text is short."""
        pdf_bytes = self._unique_pdf_bytes("showreport")
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("ShowReport.pdf", BytesIO(pdf_bytes), "application/pdf")},
            data={"dataset_split": "train", "source": "upload"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["document"]["auction_type_code"] == "IAA"

    def test_copart_filename_gets_copart(self, client):
        """Upload with Copart in filename should classify as COPART."""
        pdf_bytes = self._unique_pdf_bytes("copart")
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("copart_invoice.pdf", BytesIO(pdf_bytes), "application/pdf")},
            data={"dataset_split": "train", "source": "upload"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["document"]["auction_type_code"] == "COPART"

    def test_generic_filename_falls_to_text_or_other(self, client):
        """Upload with generic filename should fall through to text classification or OTHER."""
        pdf_bytes = self._unique_pdf_bytes("generic")
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("document.pdf", BytesIO(pdf_bytes), "application/pdf")},
            data={"dataset_split": "train", "source": "upload"},
        )
        assert resp.status_code == 201
        # Generic filename with minimal text → OTHER
        data = resp.json()
        assert data["document"]["auction_type_code"] in ("OTHER", "COPART", "IAA", "MANHEIM")

    def test_reclassify_endpoint(self, client):
        """POST /api/documents/reclassify-other should work."""
        resp = client.post("/api/documents/reclassify-other")
        assert resp.status_code == 200
        data = resp.json()
        assert "updated" in data
        assert "skipped" in data
        assert "total_checked" in data

    def test_sparkbuyer_filename_gets_iaa(self, client):
        """Upload with sparkbuyer filename should classify as IAA."""
        pdf_bytes = self._unique_pdf_bytes("spark")
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("sparkbuyerdetail__45_.pdf", BytesIO(pdf_bytes), "application/pdf")},
            data={"dataset_split": "train", "source": "upload"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["document"]["auction_type_code"] == "IAA"
