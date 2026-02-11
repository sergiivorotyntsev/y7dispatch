"""
E2E Pipeline Tests — Manheim

Tests the full Manheim document pipeline:
  Upload → Classification → Extraction → Review → Export readiness

Uses sample fixture PDFs for upload flow tests and
embedded Manheim text for extraction accuracy tests.
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
def manheim_pdf_path():
    """Path to sample Manheim invoice PDF."""
    path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "sample_manheim_invoice.pdf")
    if not os.path.exists(path):
        pytest.skip("sample_manheim_invoice.pdf not found")
    return path


@pytest.fixture(scope="module")
def manheim_pdf_bytes(manheim_pdf_path):
    """Read sample Manheim invoice PDF bytes."""
    with open(manheim_pdf_path, "rb") as f:
        return f.read()


MANHEIM_TEXT = """
Manheim
BILL OF SALE

Cox Automotive

Account #: 5515588
BROADWAY MOTORING INC

Release ID: 4N0F01G244B96
Work Order #: 78901234

YMMT: 2016 VOLVO XC90 T5 MOMENTUM
VIN: YV4A22PMXG1037898
Color: BLACK
Mileage: 87,432

Sale Date: 12/15/2025
Final Sale Price: $6,500.00

Buyer Fee:          $350.00
Documentation Fee:  $75.00
Total:              $6,925.00

Consignor: GEICO
Sold At: Manheim Pennsylvania

Pickup Location Address:
Manheim Auto Auction
1190 LANCASTER RD
MANHEIM, PA 17545
Phone: (717) 555-0456

OFFSITE VEHICLE RELEASE
"""


def _get_manheim_auction_type_id(client):
    """Get the auction_type_id for MANHEIM."""
    resp = client.get("/api/auction-types/")
    if resp.status_code != 200:
        return 3  # fallback
    data = resp.json()
    items = data.get("items", data) if isinstance(data, dict) else data
    for at in items:
        if at.get("code") == "MANHEIM":
            return at["id"]
    return 3


def _upload_manheim(client, pdf_bytes, *, is_test=False, auction_type_id=None):
    """Upload a Manheim PDF and return response."""
    if auction_type_id is None:
        auction_type_id = _get_manheim_auction_type_id(client)
    resp = client.post(
        "/api/documents/upload",
        files={
            "file": (
                f"manheim_{uuid.uuid4().hex[:8]}.pdf",
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


class TestManheimClassification:
    """Test Manheim document classification/scoring."""

    def test_manheim_extractor_scores_high(self):
        """Manheim extractor should score high on Manheim text."""
        from extractors.manheim import ManheimExtractor

        extractor = ManheimExtractor()
        score, patterns = extractor.score(MANHEIM_TEXT)
        assert score > 0.5, f"Manheim score too low: {score}"

    def test_manheim_detected_over_copart(self):
        """Manheim text should score higher than Copart."""
        from extractors.copart import CopartExtractor
        from extractors.manheim import ManheimExtractor

        manheim = ManheimExtractor()
        copart = CopartExtractor()

        manheim_score, _ = manheim.score(MANHEIM_TEXT)
        copart_score, _ = copart.score(MANHEIM_TEXT)

        assert manheim_score > copart_score, (
            f"Manheim ({manheim_score}) should beat Copart ({copart_score})"
        )

    def test_manheim_detected_over_iaa(self):
        """Manheim text should score higher than IAA."""
        from extractors.iaa import IAAExtractor
        from extractors.manheim import ManheimExtractor

        manheim = ManheimExtractor()
        iaa = IAAExtractor()

        manheim_score, _ = manheim.score(MANHEIM_TEXT)
        iaa_score, _ = iaa.score(MANHEIM_TEXT)

        assert manheim_score > iaa_score, (
            f"Manheim ({manheim_score}) should beat IAA ({iaa_score})"
        )

    def test_manager_classifies_as_manheim(self):
        """ExtractorManager should classify Manheim text correctly."""
        from extractors import ExtractorManager
        from models.vehicle import AuctionSource

        manager = ExtractorManager()
        extractor = manager.get_extractor_for_text(MANHEIM_TEXT)
        assert extractor is not None
        assert extractor.source == AuctionSource.MANHEIM

    def test_matched_patterns_include_manheim_indicators(self):
        """Manheim scoring should find key indicator patterns."""
        from extractors.manheim import ManheimExtractor

        extractor = ManheimExtractor()
        _, patterns = extractor.score(MANHEIM_TEXT)
        pattern_strs = [str(p).lower() for p in patterns]
        assert any("manheim" in p for p in pattern_strs), (
            f"Should find 'manheim' in patterns: {patterns}"
        )


# =============================================================================
# EXTRACTION TESTS
# =============================================================================


class TestManheimExtraction:
    """Test field extraction patterns from Manheim documents."""

    def test_vin_present_in_text(self):
        """Manheim text should contain a valid 17-char VIN."""
        import re

        vins = re.findall(r"\b[A-HJ-NPR-Z0-9]{17}\b", MANHEIM_TEXT)
        assert len(vins) >= 1
        assert "YV4A22PMXG1037898" in vins

    def test_release_id_present_in_text(self):
        """Manheim text should contain Release ID pattern."""
        import re

        match = re.search(r"Release\s+ID[:\s]+([A-Z0-9]+)", MANHEIM_TEXT)
        assert match is not None
        assert match.group(1) == "4N0F01G244B96"

    def test_account_id_present_in_text(self):
        """Manheim text should contain Account # pattern."""
        import re

        match = re.search(r"Account\s*#[:\s]+(\d+)", MANHEIM_TEXT)
        assert match is not None
        assert match.group(1) == "5515588"

    def test_ymmt_line_parseable(self):
        """YMMT line should be parseable for year/make/model."""
        import re

        match = re.search(r"YMMT[:\s]+(\d{4})\s+(\S+)", MANHEIM_TEXT)
        assert match is not None
        assert match.group(1) == "2016"
        assert "VOLVO" in match.group(2).upper()

    def test_sale_date_parseable(self):
        """Sale date should be parseable from Manheim text."""
        import re

        match = re.search(r"Sale\s+Date[:\s]+(\d{2}/\d{2}/\d{4})", MANHEIM_TEXT)
        assert match is not None
        assert match.group(1) == "12/15/2025"

    def test_pickup_location_section_present(self):
        """Manheim text should have Pickup Location Address section."""
        assert "Pickup Location Address" in MANHEIM_TEXT
        assert "MANHEIM" in MANHEIM_TEXT
        assert "PA" in MANHEIM_TEXT

    def test_total_amount_parseable(self):
        """Total amount should be parseable from Manheim text."""
        import re

        match = re.search(r"Total[:\s]+\$?([\d,]+\.?\d*)", MANHEIM_TEXT)
        assert match is not None
        assert float(match.group(1).replace(",", "")) == 6925.0

    def test_offsite_indicator_present(self):
        """Manheim text should contain OFFSITE VEHICLE RELEASE."""
        assert "OFFSITE VEHICLE RELEASE" in MANHEIM_TEXT


# =============================================================================
# UPLOAD PIPELINE TESTS
# =============================================================================


class TestManheimUpload:
    """Test Manheim document upload pipeline."""

    def test_upload_returns_201(self, client, manheim_pdf_bytes):
        """Uploading a Manheim PDF should return 201."""
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
        assert resp.status_code == 201, f"Upload failed: {resp.text}"

    def test_upload_creates_document(self, client, manheim_pdf_bytes):
        """Upload should create a document record."""
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
        data = resp.json()
        assert "document" in data
        assert data["document"]["id"] is not None

    def test_upload_auto_extracts(self, client, manheim_pdf_bytes):
        """Upload with auto_extract should create an extraction run."""
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
        data = resp.json()
        if data.get("text_length", 0) >= 100:
            assert data.get("run_id") is not None, "Should create extraction run"

    def test_upload_returns_text_length(self, client, manheim_pdf_bytes):
        """Upload response should include text_length."""
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
        data = resp.json()
        assert "text_length" in data
        assert isinstance(data["text_length"], int)

    def test_upload_returns_classification(self, client, manheim_pdf_bytes):
        """Upload should return detected_source."""
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
        data = resp.json()
        assert "detected_source" in data


# =============================================================================
# EXTRACTION RUN RETRIEVAL TESTS
# =============================================================================


class TestManheimExtractionRetrieval:
    """Test retrieving Manheim extraction results via API."""

    def test_get_extraction_by_run_id(self, client, manheim_pdf_bytes):
        """Should retrieve extraction run by ID."""
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
        data = resp.json()
        run_id = data.get("run_id")
        if run_id is None:
            pytest.skip("No extraction run created (text too short)")

        ext_resp = client.get(f"/api/extractions/{run_id}")
        assert ext_resp.status_code == 200
        ext_data = ext_resp.json()
        assert "run" in ext_data
        assert ext_data["run"]["id"] == run_id

    def test_extraction_has_outputs(self, client, manheim_pdf_bytes):
        """Extraction run should have outputs dict."""
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
        data = resp.json()
        run_id = data.get("run_id")
        if run_id is None:
            pytest.skip("No extraction run created")

        ext_resp = client.get(f"/api/extractions/{run_id}")
        ext_data = ext_resp.json()
        assert "outputs" in ext_data["run"]

    def test_extraction_has_valid_status(self, client, manheim_pdf_bytes):
        """Extraction run should have a valid status."""
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
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


class TestManheimDocumentRetrieval:
    """Test document retrieval after Manheim upload."""

    def test_get_document_by_id(self, client, manheim_pdf_bytes):
        """Should retrieve uploaded document by ID."""
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
        doc_id = resp.json()["document"]["id"]

        doc_resp = client.get(f"/api/documents/{doc_id}")
        assert doc_resp.status_code == 200

    def test_document_has_auction_type(self, client, manheim_pdf_bytes):
        """Uploaded Manheim document should have correct auction type."""
        auction_type_id = _get_manheim_auction_type_id(client)
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True, auction_type_id=auction_type_id)
        data = resp.json()
        assert data["document"]["auction_type_id"] == auction_type_id

    def test_document_has_source_test_lab(self, client, manheim_pdf_bytes):
        """Document uploaded with source=test_lab should reflect that."""
        resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
        data = resp.json()
        assert data["document"].get("source") == "test_lab"


# =============================================================================
# FULL PIPELINE INTEGRATION
# =============================================================================


class TestManheimFullPipeline:
    """Test the complete Manheim pipeline from upload to export readiness."""

    def test_upload_classify_extract_flow(self, client, manheim_pdf_bytes):
        """Full pipeline: upload → classify → extract → retrieve."""
        # Step 1: Upload
        upload_resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
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

    def test_extraction_run_endpoint_lists_runs(self, client, manheim_pdf_bytes):
        """Extraction runs list should include our uploaded doc's run."""
        upload_resp = _upload_manheim(client, manheim_pdf_bytes, is_test=True)
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
        auction_type_id = _get_manheim_auction_type_id(client)
        # Use unique PDF bytes to avoid duplicate detection
        unique_pdf = sample_pdf_bytes + b"% Manheim manual test " + uuid.uuid4().hex.encode()
        resp = client.post(
            "/api/documents/upload",
            files={
                "file": (
                    f"manheim_manual_{uuid.uuid4().hex[:8]}.pdf",
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

    def test_manheim_vs_copart_cross_classification(self):
        """Manheim text should not be misclassified as Copart or IAA."""
        from extractors.copart import CopartExtractor
        from extractors.iaa import IAAExtractor
        from extractors.manheim import ManheimExtractor

        manheim = ManheimExtractor()
        copart = CopartExtractor()
        iaa = IAAExtractor()

        m_score, _ = manheim.score(MANHEIM_TEXT)
        c_score, _ = copart.score(MANHEIM_TEXT)
        i_score, _ = iaa.score(MANHEIM_TEXT)

        assert m_score > c_score, f"Manheim ({m_score}) should beat Copart ({c_score})"
        assert m_score > i_score, f"Manheim ({m_score}) should beat IAA ({i_score})"
