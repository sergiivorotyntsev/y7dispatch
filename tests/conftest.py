"""
Pytest configuration and shared fixtures.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Use a test database
TEST_DB_PATH = tempfile.mktemp(suffix=".db")


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables."""
    os.environ["DATABASE_PATH"] = TEST_DB_PATH
    os.environ["DATA_DIR"] = tempfile.mkdtemp()
    os.environ["UPLOADS_DIR"] = tempfile.mkdtemp()
    os.environ["LOG_LEVEL"] = "WARNING"
    yield
    # Cleanup
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


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
    from api.models import get_connection

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
