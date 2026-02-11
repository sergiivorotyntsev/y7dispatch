"""
Pytest configuration and shared fixtures.
"""

import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Use test databases (temp files, cleaned up after session)
TEST_DB_PATH = tempfile.mktemp(suffix=".db")
TEST_TRAINING_DB_PATH = tempfile.mktemp(suffix="_training.db")


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables and initialize database schema."""
    os.environ["DATABASE_PATH"] = TEST_DB_PATH
    os.environ["TRAINING_DB_PATH"] = TEST_TRAINING_DB_PATH
    os.environ["DATA_DIR"] = tempfile.mkdtemp()
    os.environ["UPLOADS_DIR"] = tempfile.mkdtemp()
    os.environ["LOG_LEVEL"] = "WARNING"

    # Reload database modules to pick up the env-var overrides
    # (both modules compute their paths at import time)
    db = importlib.import_module("api.database")
    importlib.reload(db)

    training_db = importlib.import_module("api.training_db")
    importlib.reload(training_db)

    # Initialize main database schema
    db.init_db()  # Creates runs, logs, config_snapshots tables
    models = importlib.import_module("api.models")
    models.init_schema()  # Creates auction_types, documents, extraction_runs, etc.
    models.seed_base_auction_types()
    models.seed_default_field_mappings()

    # Initialize training database schema
    training_db.init_training_db()  # Creates TrainingExample, ExtractionRule, etc.

    # Regression assertion: verify all critical tables exist
    import sqlite3

    for db_path, expected_tables in [
        (TEST_DB_PATH, ["auction_types", "documents", "extraction_runs", "training_examples"]),
        (TEST_TRAINING_DB_PATH, ["training_examples", "extraction_rules", "field_corrections"]),
    ]:
        conn = sqlite3.connect(db_path)
        actual = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        for table in expected_tables:
            assert table in actual, (
                f"Table '{table}' missing from {db_path}. Existing tables: {sorted(actual)}"
            )

    yield
    # Cleanup — tolerate Windows file locks on SQLite DBs
    for p in (TEST_DB_PATH, TEST_TRAINING_DB_PATH):
        try:
            if os.path.exists(p):
                os.remove(p)
        except PermissionError:
            pass  # Windows: SQLAlchemy may still hold a file lock


@pytest.fixture(scope="session")
def app():
    """Create FastAPI test application."""
    from api.main import app

    return app


@pytest.fixture(scope="session")
def client(app):
    """Create test client."""
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def sample_pdf_bytes():
    """Generate minimal valid PDF bytes for testing."""
    # Minimal PDF structure
    return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT
/F1 12 Tf
100 700 Td
(Test) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000206 00000 n
trailer
<< /Size 5 /Root 1 0 R >>
startxref
300
%%EOF"""


@pytest.fixture
def db_connection():
    """Get database connection for test assertions."""
    from api.database import get_connection

    with get_connection() as conn:
        yield conn


@pytest.fixture
def clean_db(db_connection):
    """Clean database tables before test."""
    tables = [
        "documents",
        "extraction_runs",
        "extracted_vehicles",
        "review_corrections",
        "training_examples",
        "export_history",
        "email_activity",
        "email_rules",
    ]
    for table in tables:
        try:
            db_connection.execute(f"DELETE FROM {table}")
        except Exception:
            pass  # Table might not exist
    db_connection.commit()
    yield


@pytest.fixture
def sample_copart_text():
    """Sample Copart document text for testing."""
    return """
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


@pytest.fixture
def sample_iaa_text():
    """Sample IAA document text for testing."""
    return """
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
"""


@pytest.fixture
def mock_db_connection():
    """Mock database connection for testing."""
    from unittest.mock import MagicMock

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute = MagicMock(
        return_value=MagicMock(fetchall=lambda: [], fetchone=lambda: None)
    )

    return mock_conn
