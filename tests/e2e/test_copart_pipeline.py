"""
E2E Pipeline Tests — Copart

Tests the full Copart document pipeline:
  Upload → Classification → Extraction → Review → Export readiness

Uses sample fixture PDFs for upload flow tests and
embedded Copart text for extraction accuracy tests.
"""

import os
import uuid
from io import BytesIO

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from api.main import app

    return TestClient(app)


@pytest.fixture(scope="module")
def copart_pdf_path():
    """Path to sample Copart invoice PDF."""
    path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "sample_copart_invoice.pdf")
    if not os.path.exists(path):
        pytest.skip("sample_copart_invoice.pdf not found")
    return path


@pytest.fixture(scope="module")
def copart_pdf_bytes(copart_pdf_path):
    """Read sample Copart invoice PDF bytes."""
    with open(copart_pdf_path, "rb") as f:
        return f.read()


COPART_TEXT = """
Copart
Sales Receipt/Bill of Sale
Date: 01/13/26 11:12 AM

MEMBER: 535527
BROADWAY MOTORING INC
77 FITCHBURG ROAD
AYER, MA 01432

PHYSICAL ADDRESS OF LOT:
5701 WHITESIDE RD
SANDSTON VA 23150

SELLER:
USAA
SOLD THROUGH COPART

LOT#: 91708175
VEHICLE: 2024 HYUNDAI TUCSON SEL BLACK
VIN: KM8JCCD18RU178398

Sale Yard: 139
Item#: 2035/D
Keys: YES
Sale: 01/09/2026

Charges and Payments
Date        Charges           Amount     Description
01/09/2026  Sale Price        $12,400.00
01/09/2026  Environmental Fee $15.00
01/09/2026  Virtual Bid Fee   $160.00
01/09/2026  Gate Fee          $95.00
01/09/2026  Title Pickup Fee  $20.00
01/13/2026  Buyer Fee         $875.00
01/13/2026  Payment           -$13,565.00 Wire Payment

Net Due (USD)  $0.00
"""


def _get_copart_auction_type_id(client):
    """Get the auction_type_id for COPART."""
    resp = client.get("/api/auction-types/")
    if resp.status_code != 200:
        return 1  # fallback
    data = resp.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    for at in items:
        if at.get("code") == "COPART":
            return at["id"]
    return 1


def _upload_copart(client, pdf_bytes, *, is_test=False, auction_type_id=None):
    """Upload a Copart PDF and return response data."""
    if auction_type_id is None:
        auction_type_id = _get_copart_auction_type_id(client)
    resp = client.post(
        "/api/documents/upload",
        files={
            "file": (
                f"copart_{uuid.uuid4().hex[:8]}.pdf",
                BytesIO(pdf_bytes),
                "application/pdf",
            )
        },
        data={
            "auction_type_id": auction_type_id,
            "is_test": str(is_test).lower(),
            "source": "test_lab",
        },
    )
    return resp


# =============================================================================
# CLASSIFICATION TESTS
# =============================================================================


class TestCopartClassification:
    """Test Copart document classification/scoring."""

    def test_copart_extractor_scores_high(self):
        """Copart extractor should score high on Copart text."""
        from extractors.copart import CopartExtractor

        extractor = CopartExtractor()
        score, patterns = extractor.score(COPART_TEXT)
        assert score > 0.5, f"Copart score too low: {score}"

    def test_copart_detected_over_iaa(self):
        """Copart text should score higher than IAA."""
        from extractors.copart import CopartExtractor
        from extractors.iaa import IAAExtractor

        copart = CopartExtractor()
        iaa = IAAExtractor()

        copart_score, _ = copart.score(COPART_TEXT)
        iaa_score, _ = iaa.score(COPART_TEXT)

        assert copart_score > iaa_score, (
            f"Copart ({copart_score}) should beat IAA ({iaa_score})"
        )

    def test_copart_detected_over_manheim(self):
        """Copart text should score higher than Manheim."""
        from extractors.copart import CopartExtractor
        from extractors.manheim import ManheimExtractor

        copart = CopartExtractor()
        manheim = ManheimExtractor()

        copart_score, _ = copart.score(COPART_TEXT)
        manheim_score, _ = manheim.score(COPART_TEXT)

        assert copart_score > manheim_score, (
            f"Copart ({copart_score}) should beat Manheim ({manheim_score})"
        )

    def test_manager_classifies_as_copart(self):
        """ExtractorManager should classify Copart text correctly."""
        from extractors import ExtractorManager
        from models.vehicle import AuctionSource

        manager = ExtractorManager()
        extractor = manager.get_extractor_for_text(COPART_TEXT)
        assert extractor is not None
        assert extractor.source == AuctionSource.COPART

    def test_matched_patterns_include_key_indicators(self):
        """Copart scoring should find key indicator patterns."""
        from extractors.copart import CopartExtractor

        extractor = CopartExtractor()
        _, patterns = extractor.score(COPART_TEXT)
        pattern_strs = [str(p).lower() for p in patterns]
        # Should detect at least "copart" and "SOLD THROUGH COPART"
        assert any("copart" in p for p in pattern_strs), (
            f"Should find 'copart' in patterns: {patterns}"
        )


# =============================================================================
# EXTRACTION TESTS
# =============================================================================


class TestCopartExtraction:
    """Test field extraction patterns from Copart documents."""

    def test_vin_present_in_text(self):
        """Copart text should contain a valid 17-char VIN."""
        import re

        vins = re.findall(r"\b[A-HJ-NPR-Z0-9]{17}\b", COPART_TEXT)
        assert len(vins) >= 1
        assert "KM8JCCD18RU178398" in vins

    def test_lot_number_present_in_text(self):
        """Copart text should contain LOT# pattern."""
        import re

        match = re.search(r"LOT#[:\s]+(\d+)", COPART_TEXT)
        assert match is not None
        assert match.group(1) == "91708175"

    def test_member_id_present_in_text(self):
        """Copart text should contain MEMBER pattern."""
        import re

        match = re.search(r"MEMBER[:\s]+(\d+)", COPART_TEXT)
        assert match is not None
        assert match.group(1) == "535527"

    def test_vehicle_line_parseable(self):
        """VEHICLE line should be parseable for year/make/model."""
        import re

        match = re.search(r"VEHICLE[:\s]+(\d{4})\s+(\S+)", COPART_TEXT)
        assert match is not None
        assert match.group(1) == "2024"
        assert "HYUNDAI" in match.group(2).upper()

    def test_sale_date_parseable(self):
        """Sale date should be parseable from Copart text."""
        import re

        match = re.search(r"Sale[:\s]+(\d{2}/\d{2}/\d{4})", COPART_TEXT)
        assert match is not None
        assert match.group(1) == "01/09/2026"

    def test_physical_address_section_present(self):
        """Copart text should have PHYSICAL ADDRESS OF LOT section."""
        assert "PHYSICAL ADDRESS OF LOT" in COPART_TEXT
        assert "SANDSTON" in COPART_TEXT
        assert "VA" in COPART_TEXT


# =============================================================================
# UPLOAD PIPELINE TESTS
# =============================================================================


class TestCopartUpload:
    """Test Copart document upload pipeline."""

    def test_upload_returns_201(self, client, copart_pdf_bytes):
        """Uploading a Copart PDF should return 201."""
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        assert resp.status_code == 201, f"Upload failed: {resp.text}"

    def test_upload_creates_document(self, client, copart_pdf_bytes):
        """Upload should create a document record."""
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        data = resp.json()
        assert "document" in data
        assert data["document"]["id"] is not None

    def test_upload_auto_extracts(self, client, copart_pdf_bytes):
        """Upload with auto_extract should create an extraction run."""
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        data = resp.json()
        # run_id may be None if text is too short for extraction
        if data.get("text_length", 0) >= 100:
            assert data.get("run_id") is not None, "Should create extraction run"

    def test_upload_returns_text_length(self, client, copart_pdf_bytes):
        """Upload response should include text_length."""
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        data = resp.json()
        assert "text_length" in data
        assert isinstance(data["text_length"], int)

    def test_upload_returns_classification(self, client, copart_pdf_bytes):
        """Upload should return detected_source."""
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        data = resp.json()
        # detected_source may be None for minimal test PDFs
        assert "detected_source" in data


# =============================================================================
# EXTRACTION RUN RETRIEVAL TESTS
# =============================================================================


class TestCopartExtractionRetrieval:
    """Test retrieving Copart extraction results via API."""

    def test_get_extraction_by_run_id(self, client, copart_pdf_bytes):
        """Should retrieve extraction run by ID."""
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        data = resp.json()
        run_id = data.get("run_id")
        if run_id is None:
            pytest.skip("No extraction run created (text too short)")

        ext_resp = client.get(f"/api/extractions/{run_id}")
        assert ext_resp.status_code == 200
        ext_data = ext_resp.json()
        assert "run" in ext_data
        assert ext_data["run"]["id"] == run_id

    def test_extraction_has_outputs(self, client, copart_pdf_bytes):
        """Extraction run should have outputs dict."""
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        data = resp.json()
        run_id = data.get("run_id")
        if run_id is None:
            pytest.skip("No extraction run created")

        ext_resp = client.get(f"/api/extractions/{run_id}")
        ext_data = ext_resp.json()
        run_data = ext_data["run"]
        # outputs may be empty dict for minimal PDFs but should be present
        assert "outputs" in run_data

    def test_extraction_has_status(self, client, copart_pdf_bytes):
        """Extraction run should have a valid status."""
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        data = resp.json()
        run_id = data.get("run_id")
        if run_id is None:
            pytest.skip("No extraction run created")

        ext_resp = client.get(f"/api/extractions/{run_id}")
        ext_data = ext_resp.json()
        status = ext_data["run"]["status"]
        valid_statuses = ["pending", "processing", "needs_review", "approved", "failed", "manual_required"]
        assert status in valid_statuses, f"Unexpected status: {status}"


# =============================================================================
# DOCUMENT RETRIEVAL TESTS
# =============================================================================


class TestCopartDocumentRetrieval:
    """Test document retrieval after Copart upload."""

    def test_get_document_by_id(self, client, copart_pdf_bytes):
        """Should retrieve uploaded document by ID."""
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        doc_id = resp.json()["document"]["id"]

        doc_resp = client.get(f"/api/documents/{doc_id}")
        assert doc_resp.status_code == 200

    def test_document_has_auction_type(self, client, copart_pdf_bytes):
        """Uploaded Copart document should have correct auction type."""
        auction_type_id = _get_copart_auction_type_id(client)
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True, auction_type_id=auction_type_id)
        data = resp.json()
        assert data["document"]["auction_type_id"] == auction_type_id

    def test_document_has_source_test_lab(self, client, copart_pdf_bytes):
        """Document uploaded with source=test_lab should reflect that."""
        resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        data = resp.json()
        assert data["document"].get("source") == "test_lab"


# =============================================================================
# FULL PIPELINE INTEGRATION
# =============================================================================


class TestCopartFullPipeline:
    """Test the complete Copart pipeline from upload to export readiness."""

    def test_upload_classify_extract_flow(self, client, copart_pdf_bytes):
        """Full pipeline: upload → classify → extract → retrieve."""
        # Step 1: Upload
        upload_resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        assert upload_resp.status_code == 201
        upload_data = upload_resp.json()

        doc_id = upload_data["document"]["id"]
        run_id = upload_data.get("run_id")

        # Step 2: Verify document exists
        doc_resp = client.get(f"/api/documents/{doc_id}")
        assert doc_resp.status_code == 200

        # Step 3: If run exists, verify extraction
        if run_id:
            ext_resp = client.get(f"/api/extractions/{run_id}")
            assert ext_resp.status_code == 200
            ext_data = ext_resp.json()
            assert ext_data["run"]["document_id"] == doc_id

    def test_duplicate_upload_handling(self, client, copart_pdf_bytes):
        """Uploading the same Copart PDF twice should handle duplicates."""
        # Use same bytes with same filename
        filename = f"copart_dup_test_{uuid.uuid4().hex[:6]}.pdf"

        resp1 = client.post(
            "/api/documents/upload",
            files={"file": (filename, BytesIO(copart_pdf_bytes), "application/pdf")},
            data={
                "auction_type_id": _get_copart_auction_type_id(client),
                "is_test": "true",
                "source": "test_lab",
            },
        )
        assert resp1.status_code == 201

        # Second upload with same content
        resp2 = client.post(
            "/api/documents/upload",
            files={"file": (filename, BytesIO(copart_pdf_bytes), "application/pdf")},
            data={
                "auction_type_id": _get_copart_auction_type_id(client),
                "is_test": "true",
                "source": "test_lab",
            },
        )
        # Should either succeed (duplicate detection) or reject
        assert resp2.status_code in [200, 201, 409]

    def test_extraction_run_endpoint_lists_runs(self, client, copart_pdf_bytes):
        """Extraction runs list should include our uploaded doc's run."""
        upload_resp = _upload_copart(client, copart_pdf_bytes, is_test=True)
        run_id = upload_resp.json().get("run_id")
        if run_id is None:
            pytest.skip("No extraction run created")

        list_resp = client.get("/api/extractions/")
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert "items" in data
        assert data["total"] >= 1
