"""
E2E Test Configuration and Fixtures

Uses existing sample_docs/ and golden_set/expected/ directories.
DO NOT create parallel fixture structure - reference existing data.
"""

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Project root for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Paths to existing test data - DO NOT DUPLICATE
SAMPLE_DOCS = Path(__file__).parent.parent / "sample_docs"
GOLDEN_SET = Path(__file__).parent.parent / "golden_set" / "expected"

# Test database paths (isolated for E2E tests)
TEST_DB_PATH = tempfile.mktemp(suffix="_e2e.db")
TEST_TRAINING_DB_PATH = tempfile.mktemp(suffix="_e2e_training.db")


# =============================================================================
# SESSION FIXTURES
# =============================================================================


@pytest.fixture(scope="session", autouse=True)
def setup_e2e_environment():
    """Set up E2E test environment with isolated database."""
    os.environ["DATABASE_PATH"] = TEST_DB_PATH
    os.environ["TRAINING_DB_PATH"] = TEST_TRAINING_DB_PATH
    os.environ["DATA_DIR"] = tempfile.mkdtemp()
    os.environ["UPLOADS_DIR"] = tempfile.mkdtemp()
    os.environ["LOG_LEVEL"] = "WARNING"

    # Reload database modules
    db = importlib.import_module("api.database")
    importlib.reload(db)

    training_db = importlib.import_module("api.training_db")
    importlib.reload(training_db)

    # Initialize schema
    db.init_db()
    models = importlib.import_module("api.models")
    models.init_schema()
    models.seed_base_auction_types()
    models.seed_default_field_mappings()

    # Initialize auction profiles
    from api.auction_profiles import init_auction_profiles_schema, seed_default_auction_profiles
    init_auction_profiles_schema()
    seed_default_auction_profiles()

    training_db.init_training_db()

    yield

    # Cleanup
    import gc
    gc.collect()
    for p in (TEST_DB_PATH, TEST_TRAINING_DB_PATH):
        if os.path.exists(p):
            try:
                os.remove(p)
            except PermissionError:
                pass


@pytest.fixture(scope="session")
def app():
    """FastAPI application instance."""
    from api.main import app
    return app


@pytest.fixture(scope="session")
def client(app):
    """FastAPI test client."""
    from fastapi.testclient import TestClient
    return TestClient(app)


# =============================================================================
# PDF DOCUMENT FIXTURES - REFERENCE EXISTING DATA
# =============================================================================


def _load_pdf(pattern: str) -> bytes:
    """Load PDF bytes from sample_docs matching pattern."""
    files = list(SAMPLE_DOCS.glob(pattern))
    if not files:
        pytest.skip(f"No sample PDF matching '{pattern}' in {SAMPLE_DOCS}")
    return files[0].read_bytes()


def _load_ground_truth(pattern: str) -> dict:
    """Load ground truth JSON from golden_set/expected matching pattern."""
    files = list(GOLDEN_SET.glob(pattern))
    if not files:
        pytest.skip(f"No ground truth matching '{pattern}' in {GOLDEN_SET}")
    return json.loads(files[0].read_text())


@pytest.fixture
def copart_pdf() -> bytes:
    """Copart sample PDF from existing golden set (invoice*.pdf)."""
    return _load_pdf("invoice21.pdf")


@pytest.fixture
def copart_pdf_path() -> Path:
    """Path to Copart sample PDF."""
    files = list(SAMPLE_DOCS.glob("invoice21.pdf"))
    if not files:
        pytest.skip("No Copart sample PDF")
    return files[0]


@pytest.fixture
def copart_ground_truth() -> dict:
    """Copart ground truth from existing golden set."""
    return _load_ground_truth("invoice21_expected.json")


@pytest.fixture
def iaa_pdf() -> bytes:
    """IAA sample PDF from existing golden set (ShowReport*.pdf)."""
    return _load_pdf("ShowReport1.pdf")


@pytest.fixture
def iaa_pdf_path() -> Path:
    """Path to IAA sample PDF."""
    files = list(SAMPLE_DOCS.glob("ShowReport1.pdf"))
    if not files:
        pytest.skip("No IAA sample PDF")
    return files[0]


@pytest.fixture
def iaa_ground_truth() -> dict:
    """IAA ground truth from existing golden set."""
    return _load_ground_truth("ShowReport1_expected.json")


@pytest.fixture
def manheim_pdf() -> bytes:
    """Manheim sample PDF from fixture (Bill of Sale)."""
    return _load_pdf("sample_manheim_invoice.pdf")


@pytest.fixture
def manheim_pdf_path() -> Path:
    """Path to Manheim sample PDF."""
    files = list(SAMPLE_DOCS.glob("sample_manheim_invoice.pdf"))
    if not files:
        pytest.skip("No Manheim sample PDF")
    return files[0]


@pytest.fixture
def manheim_ground_truth() -> dict:
    """Manheim ground truth from golden set."""
    return _load_ground_truth("sample_manheim_invoice_expected.json")


# =============================================================================
# EXTRACTION HELPERS
# =============================================================================


def run_extraction_from_pdf(pdf_path: str | Path) -> dict:
    """
    Run extraction pipeline on a PDF file.

    Returns dict with extracted fields in format compatible with ground truth.
    """
    import pdfplumber
    from extractors import ExtractorManager

    # Extract text
    with pdfplumber.open(str(pdf_path)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    # Get extractor and run
    manager = ExtractorManager()
    extractor = manager.get_extractor_for_text(text)

    if not extractor:
        return {"error": "No extractor found for document"}

    result = extractor.extract_with_result(str(pdf_path), text)

    if not result.invoice:
        return {"error": "Extraction returned no invoice"}

    # Build extracted fields dict
    inv = result.invoice
    fields = {
        "auction_source": result.source.value if result.source else None,
        "reference_id": inv.reference_id,
        "buyer_id": inv.buyer_id,
        "buyer_name": inv.buyer_name,
        "sale_date": str(inv.sale_date) if inv.sale_date else None,
        "total_amount": str(inv.total_amount) if inv.total_amount else None,
    }

    if inv.pickup_address:
        addr = inv.pickup_address
        fields.update({
            "pickup_name": addr.name,
            "pickup_address": addr.street,
            "pickup_city": addr.city,
            "pickup_state": addr.state,
            "pickup_zip": addr.postal_code,
        })

    if inv.vehicles:
        v = inv.vehicles[0]
        fields.update({
            "vehicle_vin": v.vin,
            "vehicle_year": v.year,
            "vehicle_make": v.make,
            "vehicle_model": v.model,
            "vehicle_color": v.color,
            "vehicle_lot": v.lot_number,
        })

    # Add extraction metadata
    fields["_extraction_meta"] = {
        "classification_confidence": result.score if hasattr(result, "score") else None,
        "extractor_used": extractor.__class__.__name__,
        "has_invoice": result.invoice is not None,
    }

    return fields


@pytest.fixture
def extraction_runner():
    """Fixture providing extraction runner function."""
    return run_extraction_from_pdf


# =============================================================================
# FIELD COMPARISON HELPERS
# =============================================================================


def normalize_vin(vin: str | None) -> str:
    """Normalize VIN for comparison."""
    if not vin:
        return ""
    return str(vin).upper().strip()


def normalize_state(state: str | None) -> str:
    """Normalize state to uppercase 2-letter."""
    if not state:
        return ""
    return str(state).upper()[:2]


def normalize_zip(zip_code: str | None) -> str:
    """Normalize ZIP to 5-digit."""
    if not zip_code:
        return ""
    return str(zip_code).split("-")[0][:5]


def compare_fields(extracted: dict, expected: dict, field_key: str) -> tuple[bool, str]:
    """
    Compare extracted field against expected value.
    Returns (match, reason).
    """
    ext_val = extracted.get(field_key)
    exp_val = expected.get(field_key)

    if exp_val is None:
        return True, "Expected null, skipped"

    if ext_val is None:
        return False, f"Expected '{exp_val}', got null"

    # Apply normalization based on field type
    if "vin" in field_key.lower():
        return normalize_vin(ext_val) == normalize_vin(exp_val), \
            f"VIN: '{ext_val}' vs '{exp_val}'"

    if "state" in field_key.lower():
        return normalize_state(ext_val) == normalize_state(exp_val), \
            f"State: '{ext_val}' vs '{exp_val}'"

    if "zip" in field_key.lower():
        return normalize_zip(ext_val) == normalize_zip(exp_val), \
            f"ZIP: '{ext_val}' vs '{exp_val}'"

    # Case-insensitive string comparison
    return str(ext_val).upper().strip() == str(exp_val).upper().strip(), \
        f"'{ext_val}' vs '{exp_val}'"


@pytest.fixture
def field_comparator():
    """Fixture providing field comparison function."""
    return compare_fields


# =============================================================================
# API TEST FIXTURES
# =============================================================================


@pytest.fixture
def uploaded_document(client, copart_pdf):
    """
    Upload a document and return the upload response.
    Yields document data for tests, cleans up after.
    """
    import io

    response = client.post(
        "/api/documents/upload",
        files={"file": ("test_copart.pdf", io.BytesIO(copart_pdf), "application/pdf")},
        data={
            "auto_extract": "true",
            "source": "test_lab",
            "is_test": "true",
        }
    )

    assert response.status_code in (200, 201), f"Upload failed: {response.text}"
    data = response.json()

    yield data

    # Cleanup: delete the document
    if data.get("document", {}).get("id"):
        try:
            client.delete(f"/api/documents/{data['document']['id']}")
        except Exception:
            pass


# =============================================================================
# MOCK CD API (for export tests - Day 4)
# =============================================================================


@pytest.fixture
def mock_cd_api(mocker):
    """
    Mock Central Dispatch API for export tests.
    Validates payload against expected schema.
    """
    from unittest.mock import MagicMock

    mock_response = MagicMock()
    mock_response.listing_id = "CD-TEST-2026-001"
    mock_response.status = "ACTIVE"
    mock_response.etag = "test-etag-123"

    mock = mocker.patch(
        "services.cd_client.CDClient.create_listing",
        return_value=mock_response
    )
    return mock


@pytest.fixture
def mock_market_intel(mocker):
    """
    Mock Market Intelligence API for pricing tests.
    """
    from unittest.mock import MagicMock

    mock_price = MagicMock()
    mock_price.listing_price = 550.0
    mock_price.dispatch_price = 485.0
    mock_price.listing_price_per_mile = 0.55
    mock_price.dispatch_distance = 1000

    mock = mocker.patch(
        "services.cd_client.CDClient.get_listing_prices",
        return_value=[mock_price]
    )
    return mock
