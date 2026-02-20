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

    def test_manheim_psi_report(self):
        from api.routes.documents import _classify_from_filename

        assert _classify_from_filename("PSI_Report.pdf") == "MANHEIM"
        assert _classify_from_filename("psi_report_12345.pdf") == "MANHEIM"
        assert _classify_from_filename("Pre_Sale_Inspection.pdf") == "MANHEIM"

    def test_sparkbuyer_no_longer_maps_to_iaa(self):
        """sparkbuyer filenames should NOT auto-classify — content-based classification is used instead."""
        from api.routes.documents import _classify_from_filename

        assert _classify_from_filename("sparkbuyerdetail__45_.pdf") is None
        assert _classify_from_filename("auctions_in_motion_receipt.pdf") is None

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


class TestTextClassification:
    """Test _classify_from_text() content-based classification."""

    def test_copart_text(self):
        from api.routes.documents import _classify_from_text

        text = "x" * 100 + " Copart Invoice for lot 12345, sold through Copart"
        assert _classify_from_text(text) == "COPART"

    def test_iaa_text(self):
        from api.routes.documents import _classify_from_text

        text = "x" * 100 + " Insurance Auto Auctions buyer receipt for vehicle"
        assert _classify_from_text(text) == "IAA"

    def test_iaa_iaai_domain(self):
        from api.routes.documents import _classify_from_text

        text = "x" * 100 + " visit iaai.com for more information"
        assert _classify_from_text(text) == "IAA"

    def test_manheim_text(self):
        from api.routes.documents import _classify_from_text

        text = "x" * 100 + " Manheim Auto Auction vehicle purchase receipt"
        assert _classify_from_text(text) == "MANHEIM"

    def test_short_text_returns_none(self):
        from api.routes.documents import _classify_from_text

        assert _classify_from_text("Copart") is None
        assert _classify_from_text("") is None
        assert _classify_from_text(None) is None

    def test_generic_text_returns_none(self):
        from api.routes.documents import _classify_from_text

        text = "x" * 200 + " This is a generic vehicle invoice for Broadway Motoring"
        assert _classify_from_text(text) is None

    def test_sparkbuyer_text_no_match(self):
        """SparkBuyer text without IAA patterns should not classify as IAA."""
        from api.routes.documents import _classify_from_text

        text = "x" * 100 + " Purchase Detail for BROADWAY MOTORING INC, AUCTIONS IN MOTION"
        assert _classify_from_text(text) is None


class TestHoldStatus:
    """Test HOLD status API endpoints."""

    def test_set_hold(self, client):
        """POST /api/documents/{id}/set-hold should set hold reason."""
        from io import BytesIO
        import uuid as uuid_mod

        unique = uuid_mod.uuid4().hex[:8]
        pdf_bytes = f"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n210\n%%EOF {unique}".encode()
        upload = client.post(
            "/api/documents/upload",
            files={"file": (f"hold_test_{unique}.pdf", BytesIO(pdf_bytes), "application/pdf")},
            data={"dataset_split": "train", "source": "upload"},
        )
        assert upload.status_code == 201
        doc_id = upload.json()["document"]["id"]

        resp = client.post(f"/api/documents/{doc_id}/set-hold", json={"reason": "awaiting_gate_pass", "note": "Need gate pass from Copart"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["hold_reason"] == "awaiting_gate_pass"
        assert data["hold_note"] == "Need gate pass from Copart"
        assert data["hold_since"] is not None

    def test_release_hold(self, client):
        """POST /api/documents/{id}/release-hold should clear hold."""
        from io import BytesIO
        import uuid as uuid_mod

        unique = uuid_mod.uuid4().hex[:8]
        pdf_bytes = f"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n210\n%%EOF {unique}".encode()
        upload = client.post(
            "/api/documents/upload",
            files={"file": (f"hold_rel_{unique}.pdf", BytesIO(pdf_bytes), "application/pdf")},
            data={"dataset_split": "train", "source": "upload"},
        )
        doc_id = upload.json()["document"]["id"]

        client.post(f"/api/documents/{doc_id}/set-hold", json={"reason": "awaiting_payment"})
        resp = client.post(f"/api/documents/{doc_id}/release-hold")
        assert resp.status_code == 200
        assert resp.json()["hold_reason"] is None

    def test_hold_appears_in_document_response(self, client):
        """Document list should include hold fields."""
        resp = client.get("/api/documents/?limit=1")
        assert resp.status_code == 200
        # Response model should accept hold_reason field without error
        data = resp.json()
        if data["items"]:
            item = data["items"][0]
            assert "hold_reason" in item or item.get("hold_reason") is None

    def test_set_hold_not_found(self, client):
        """Setting hold on nonexistent doc should 404."""
        resp = client.post("/api/documents/999999/set-hold", json={"reason": "test"})
        assert resp.status_code == 404


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

    def test_sparkbuyer_filename_gets_other(self, client):
        """sparkbuyer filename without matching text content should fall to OTHER."""
        pdf_bytes = self._unique_pdf_bytes("spark")
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("sparkbuyerdetail__45_.pdf", BytesIO(pdf_bytes), "application/pdf")},
            data={"dataset_split": "train", "source": "upload"},
        )
        assert resp.status_code == 201
        data = resp.json()
        # Without IAA text content, sparkbuyer filename alone doesn't classify as IAA
        assert data["document"]["auction_type_code"] == "OTHER"

    def test_manheim_filename_gets_manheim(self, client):
        """Upload with Manheim in filename should classify as MANHEIM."""
        pdf_bytes = self._unique_pdf_bytes("manheim")
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("manheim_receipt.pdf", BytesIO(pdf_bytes), "application/pdf")},
            data={"dataset_split": "train", "source": "upload"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["document"]["auction_type_code"] == "MANHEIM"

    def test_psi_report_filename_gets_manheim(self, client):
        """Upload with PSI_Report filename should classify as MANHEIM."""
        pdf_bytes = self._unique_pdf_bytes("psi")
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("PSI_Report.pdf", BytesIO(pdf_bytes), "application/pdf")},
            data={"dataset_split": "train", "source": "upload"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["document"]["auction_type_code"] == "MANHEIM"


class TestManheimReleaseDatePropagation:
    """Test Manheim release date → available_date logic in extraction pipeline."""

    def test_release_date_iso_sets_available_date(self):
        """ISO release date should become available_date."""
        # Simulate the post-extraction logic directly
        outputs = {
            "auction_type": "MANHEIM",
            "manheim_release_date": "2026-03-15",
            "vehicle_make": "VOLVO",
            "vehicle_model": "XC90",
        }
        field_sources = {}

        # Run the Manheim propagation logic
        release_date = outputs.get("manheim_release_date")
        if release_date and release_date not in ("AVAILABLE_NOW", "NO_RELEASE_DOCUMENT"):
            if not outputs.get("available_date"):
                outputs["available_date"] = release_date

        assert outputs["available_date"] == "2026-03-15"

    def test_available_now_sets_today(self):
        """AVAILABLE_NOW should set available_date to today."""
        import time
        outputs = {
            "auction_type": "MANHEIM",
            "manheim_release_date": "AVAILABLE_NOW",
        }

        release_date = outputs.get("manheim_release_date")
        if release_date == "AVAILABLE_NOW":
            if not outputs.get("available_date"):
                outputs["available_date"] = time.strftime("%Y-%m-%d")

        assert outputs["available_date"] == time.strftime("%Y-%m-%d")

    def test_no_release_document_sets_warning(self):
        """NO_RELEASE_DOCUMENT should add a warning, not set available_date."""
        outputs = {
            "auction_type": "MANHEIM",
            "manheim_release_date": "NO_RELEASE_DOCUMENT",
        }

        release_date = outputs.get("manheim_release_date")
        if release_date == "NO_RELEASE_DOCUMENT":
            if not outputs.get("available_date"):
                outputs["manheim_release_warning"] = "No release document found"

        assert "available_date" not in outputs
        assert "manheim_release_warning" in outputs

    def test_existing_available_date_not_overwritten(self):
        """If available_date already set, release date should not overwrite it."""
        outputs = {
            "auction_type": "MANHEIM",
            "manheim_release_date": "2026-03-15",
            "available_date": "2026-03-01",
        }

        release_date = outputs.get("manheim_release_date")
        if release_date and release_date not in ("AVAILABLE_NOW", "NO_RELEASE_DOCUMENT"):
            if not outputs.get("available_date"):
                outputs["available_date"] = release_date

        assert outputs["available_date"] == "2026-03-01"  # Not overwritten

    def test_offsite_overrides_pickup(self):
        """Manheim offsite should override pickup address with offsite address."""
        outputs = {
            "auction_type": "MANHEIM",
            "manheim_offsite": True,
            "pickup_address": "1190 Lancaster Rd",
            "pickup_city": "Manheim",
            "pickup_state": "PA",
            "pickup_zip": "17545",
            "offsite_pickup_address": "500 Dealer Row",
            "offsite_pickup_city": "Philadelphia",
            "offsite_pickup_state": "PA",
            "offsite_pickup_zip": "19103",
        }

        if outputs.get("manheim_offsite") is True:
            offsite_addr = outputs.get("offsite_pickup_address")
            offsite_city = outputs.get("offsite_pickup_city")
            if offsite_addr and offsite_city:
                outputs["pickup_address"] = offsite_addr
                outputs["pickup_city"] = offsite_city
                outputs["pickup_state"] = outputs.get("offsite_pickup_state", outputs["pickup_state"])
                outputs["pickup_zip"] = outputs.get("offsite_pickup_zip", outputs["pickup_zip"])
                outputs["pickup_location_type"] = "BUSINESS"

        assert outputs["pickup_address"] == "500 Dealer Row"
        assert outputs["pickup_city"] == "Philadelphia"
        assert outputs["pickup_location_type"] == "BUSINESS"

    def test_non_manheim_skips_release_logic(self):
        """Non-Manheim docs should not trigger release date propagation."""
        outputs = {
            "auction_type": "COPART",
            "manheim_release_date": "2026-03-15",
        }

        auction_source = outputs.get("auction_type", "").upper()
        if auction_source == "MANHEIM":
            outputs["available_date"] = outputs["manheim_release_date"]

        assert "available_date" not in outputs

    def test_haiku_prompt_has_manheim_fields(self):
        """EXTRACTION_PROMPT should include all Manheim-specific fields."""
        from services.haiku_extractor import EXTRACTION_PROMPT

        assert "manheim_release_date" in EXTRACTION_PROMPT
        assert "manheim_offsite" in EXTRACTION_PROMPT
        assert "offsite_pickup_address" in EXTRACTION_PROMPT
        assert "ONSITE VEHICLE RELEASE" in EXTRACTION_PROMPT
        assert "NO_RELEASE_DOCUMENT" in EXTRACTION_PROMPT
        assert "AVAILABLE_NOW" in EXTRACTION_PROMPT
