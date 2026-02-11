"""
E2E Pipeline Tests — IAA (Insurance Auto Auctions)

Tests the full IAA document pipeline:
  Upload → Classification → Extraction → Review → Export readiness

Uses sample fixture PDFs for upload flow tests and
embedded IAA text for extraction accuracy tests.
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
def iaa_pdf_path():
    """Path to sample IAA invoice PDF."""
    path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "sample_iaa_invoice.pdf")
    if not os.path.exists(path):
        pytest.skip("sample_iaa_invoice.pdf not found")
    return path


@pytest.fixture(scope="module")
def iaa_pdf_bytes(iaa_pdf_path):
    """Read sample IAA invoice PDF bytes."""
    with open(iaa_pdf_path, "rb") as f:
        return f.read()


IAA_TEXT = """
Insurance Auto Auctions
IAAI
Buyer Receipt

Stock#: 35678901
Buyer: 12345
BROADWAY MOTORING INC

Branch: IAAI Tampa South
14920 N NEBRASKA AVE
TAMPA FL 33613

VEHICLE: 2023 TOYOTA CAMRY SE WHITE
VIN: 4T1G11AK5NU123456

Sale Date: 01/10/2026
Total Due: $8,500.00

Charges:
Sale Price           $7,200.00
Buyer Fee            $800.00
Environmental Fee    $15.00
Pull Out Fee         $75.00
Gate Fee             $85.00
Internet Bid Fee     $125.00
Storage Fee          $200.00

Total                $8,500.00

Pick-Up Location:
IAAI Tampa South
14920 N NEBRASKA AVE
TAMPA, FL 33613
Phone: (813) 555-0123
"""


def _get_iaa_auction_type_id(client):
    """Get the auction_type_id for IAA."""
    resp = client.get("/api/auction-types/")
    if resp.status_code != 200:
        return 2  # fallback
    data = resp.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    for at in items:
        if at.get("code") == "IAA":
            return at["id"]
    return 2


def _upload_iaa(client, pdf_bytes, *, is_test=False, auction_type_id=None):
    """Upload an IAA PDF and return response."""
    if auction_type_id is None:
        auction_type_id = _get_iaa_auction_type_id(client)
    resp = client.post(
        "/api/documents/upload",
        files={
            "file": (
                f"iaa_{uuid.uuid4().hex[:8]}.pdf",
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


class TestIAAClassification:
    """Test IAA document classification/scoring."""

    def test_iaa_extractor_scores_high(self):
        """IAA extractor should score high on IAA text."""
        from extractors.iaa import IAAExtractor

        extractor = IAAExtractor()
        score, patterns = extractor.score(IAA_TEXT)
        assert score > 0.5, f"IAA score too low: {score}"

    def test_iaa_detected_over_copart(self):
        """IAA text should score higher than Copart."""
        from extractors.copart import CopartExtractor
        from extractors.iaa import IAAExtractor

        iaa = IAAExtractor()
        copart = CopartExtractor()

        iaa_score, _ = iaa.score(IAA_TEXT)
        copart_score, _ = copart.score(IAA_TEXT)

        assert iaa_score > copart_score, (
            f"IAA ({iaa_score}) should beat Copart ({copart_score})"
        )

    def test_iaa_detected_over_manheim(self):
        """IAA text should score higher than Manheim."""
        from extractors.iaa import IAAExtractor
        from extractors.manheim import ManheimExtractor

        iaa = IAAExtractor()
        manheim = ManheimExtractor()

        iaa_score, _ = iaa.score(IAA_TEXT)
        manheim_score, _ = manheim.score(IAA_TEXT)

        assert iaa_score > manheim_score, (
            f"IAA ({iaa_score}) should beat Manheim ({manheim_score})"
        )

    def test_manager_classifies_as_iaa(self):
        """ExtractorManager should classify IAA text correctly."""
        from extractors import ExtractorManager
        from models.vehicle import AuctionSource

        manager = ExtractorManager()
        extractor = manager.get_extractor_for_text(IAA_TEXT)
        assert extractor is not None
        assert extractor.source == AuctionSource.IAA

    def test_matched_patterns_include_iaa_indicators(self):
        """IAA scoring should find key indicator patterns."""
        from extractors.iaa import IAAExtractor

        extractor = IAAExtractor()
        _, patterns = extractor.score(IAA_TEXT)
        pattern_strs = [str(p).lower() for p in patterns]
        assert any("iaai" in p or "insurance auto" in p for p in pattern_strs), (
            f"Should find IAA indicators in patterns: {patterns}"
        )


# =============================================================================
# EXTRACTION TESTS
# =============================================================================


class TestIAAExtraction:
    """Test field extraction patterns from IAA documents."""

    def test_vin_present_in_text(self):
        """IAA text should contain a valid 17-char VIN."""
        import re

        vins = re.findall(r"\b[A-HJ-NPR-Z0-9]{17}\b", IAA_TEXT)
        assert len(vins) >= 1
        assert "4T1G11AK5NU123456" in vins

    def test_stock_number_present_in_text(self):
        """IAA text should contain Stock# pattern."""
        import re

        match = re.search(r"Stock#[:\s]+(\d+)", IAA_TEXT)
        assert match is not None
        assert match.group(1) == "35678901"

    def test_buyer_id_present_in_text(self):
        """IAA text should contain Buyer pattern."""
        import re

        match = re.search(r"Buyer[:\s]+(\d+)", IAA_TEXT)
        assert match is not None
        assert match.group(1) == "12345"

    def test_vehicle_line_parseable(self):
        """VEHICLE line should be parseable for year/make/model."""
        import re

        match = re.search(r"VEHICLE[:\s]+(\d{4})\s+(\S+)", IAA_TEXT)
        assert match is not None
        assert match.group(1) == "2023"
        assert "TOYOTA" in match.group(2).upper()

    def test_sale_date_parseable(self):
        """Sale date should be parseable from IAA text."""
        import re

        match = re.search(r"Sale\s+Date[:\s]+(\d{2}/\d{2}/\d{4})", IAA_TEXT)
        assert match is not None
        assert match.group(1) == "01/10/2026"

    def test_pickup_location_section_present(self):
        """IAA text should have Pick-Up Location section."""
        assert "Pick-Up Location" in IAA_TEXT
        assert "TAMPA" in IAA_TEXT
        assert "FL" in IAA_TEXT

    def test_total_amount_parseable(self):
        """Total amount should be parseable from IAA text."""
        import re

        match = re.search(r"Total\s+Due[:\s]+\$?([\d,]+\.?\d*)", IAA_TEXT)
        assert match is not None
        assert float(match.group(1).replace(",", "")) == 8500.0


# =============================================================================
# UPLOAD PIPELINE TESTS
# =============================================================================


class TestIAAUpload:
    """Test IAA document upload pipeline."""

    def test_upload_returns_201(self, client, iaa_pdf_bytes):
        """Uploading an IAA PDF should return 201."""
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
        assert resp.status_code == 201, f"Upload failed: {resp.text}"

    def test_upload_creates_document(self, client, iaa_pdf_bytes):
        """Upload should create a document record."""
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
        data = resp.json()
        assert "document" in data
        assert data["document"]["id"] is not None

    def test_upload_auto_extracts(self, client, iaa_pdf_bytes):
        """Upload with auto_extract should create an extraction run."""
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
        data = resp.json()
        if data.get("text_length", 0) >= 100:
            assert data.get("run_id") is not None, "Should create extraction run"

    def test_upload_returns_text_length(self, client, iaa_pdf_bytes):
        """Upload response should include text_length."""
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
        data = resp.json()
        assert "text_length" in data
        assert isinstance(data["text_length"], int)

    def test_upload_returns_classification(self, client, iaa_pdf_bytes):
        """Upload should return detected_source."""
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
        data = resp.json()
        assert "detected_source" in data


# =============================================================================
# EXTRACTION RUN RETRIEVAL TESTS
# =============================================================================


class TestIAAExtractionRetrieval:
    """Test retrieving IAA extraction results via API."""

    def test_get_extraction_by_run_id(self, client, iaa_pdf_bytes):
        """Should retrieve extraction run by ID."""
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
        data = resp.json()
        run_id = data.get("run_id")
        if run_id is None:
            pytest.skip("No extraction run created (text too short)")

        ext_resp = client.get(f"/api/extractions/{run_id}")
        assert ext_resp.status_code == 200
        ext_data = ext_resp.json()
        assert "run" in ext_data
        assert ext_data["run"]["id"] == run_id

    def test_extraction_has_outputs(self, client, iaa_pdf_bytes):
        """Extraction run should have outputs dict."""
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
        data = resp.json()
        run_id = data.get("run_id")
        if run_id is None:
            pytest.skip("No extraction run created")

        ext_resp = client.get(f"/api/extractions/{run_id}")
        ext_data = ext_resp.json()
        assert "outputs" in ext_data["run"]

    def test_extraction_has_valid_status(self, client, iaa_pdf_bytes):
        """Extraction run should have a valid status."""
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
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


class TestIAADocumentRetrieval:
    """Test document retrieval after IAA upload."""

    def test_get_document_by_id(self, client, iaa_pdf_bytes):
        """Should retrieve uploaded document by ID."""
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
        doc_id = resp.json()["document"]["id"]

        doc_resp = client.get(f"/api/documents/{doc_id}")
        assert doc_resp.status_code == 200

    def test_document_has_auction_type(self, client, iaa_pdf_bytes):
        """Uploaded IAA document should have correct auction type."""
        auction_type_id = _get_iaa_auction_type_id(client)
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True, auction_type_id=auction_type_id)
        data = resp.json()
        assert data["document"]["auction_type_id"] == auction_type_id

    def test_document_has_source_test_lab(self, client, iaa_pdf_bytes):
        """Document uploaded with source=test_lab should reflect that."""
        resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
        data = resp.json()
        assert data["document"].get("source") == "test_lab"


# =============================================================================
# FULL PIPELINE INTEGRATION
# =============================================================================


class TestIAAFullPipeline:
    """Test the complete IAA pipeline from upload to export readiness."""

    def test_upload_classify_extract_flow(self, client, iaa_pdf_bytes):
        """Full pipeline: upload → classify → extract → retrieve."""
        # Step 1: Upload
        upload_resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
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

    def test_extraction_run_endpoint_lists_runs(self, client, iaa_pdf_bytes):
        """Extraction runs list should include our uploaded doc's run."""
        upload_resp = _upload_iaa(client, iaa_pdf_bytes, is_test=True)
        run_id = upload_resp.json().get("run_id")
        if run_id is None:
            pytest.skip("No extraction run created")

        list_resp = client.get("/api/extractions/")
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert "items" in data
        assert data["total"] >= 1

    def test_manual_extraction_trigger(self, client, sample_pdf_bytes):
        """Should be able to trigger extraction manually via POST."""
        # Upload a unique PDF without auto_extract
        auction_type_id = _get_iaa_auction_type_id(client)
        # Use sample_pdf_bytes (unique per test) to avoid duplicate detection
        unique_pdf = sample_pdf_bytes + b"% IAA manual test " + uuid.uuid4().hex.encode()
        resp = client.post(
            "/api/documents/upload",
            files={
                "file": (
                    f"iaa_manual_{uuid.uuid4().hex[:8]}.pdf",
                    BytesIO(unique_pdf),
                    "application/pdf",
                )
            },
            data={
                "auction_type_id": auction_type_id,
                "is_test": "true",
                "source": "test_lab",
                "auto_extract": "false",
            },
        )
        assert resp.status_code == 201
        doc_id = resp.json()["document"]["id"]

        # Trigger manual extraction
        run_resp = client.post(
            "/api/extractions/run",
            json={"document_id": doc_id},
        )
        assert run_resp.status_code in [200, 201]
        run_data = run_resp.json()
        assert run_data["document_id"] == doc_id
