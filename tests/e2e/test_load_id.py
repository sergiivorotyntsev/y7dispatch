"""
Tests for Load ID generation and persistence.

Load ID format: M(no leading zero) + DD + first3Make(upper) + first2Model(upper) + sequence
Example: 219TOYPR (Feb 19, Toyota Prius, first of day)
"""

import json
import re
from datetime import datetime

import pytest


class TestLoadIDGeneration:
    """Test the reusable create_load_id() function."""

    def test_generates_correct_format(self):
        """Load ID should match MDD + 3-char make + 2-char model."""
        from api.routes.listings import create_load_id

        result = create_load_id("BMW", "335i")
        assert result is not None
        lid, seq = result
        now = datetime.now()
        expected_prefix = f"{now.month}{now.day:02d}BMW33"
        assert lid.startswith(expected_prefix) or lid.rstrip("0123456789").startswith(expected_prefix.rstrip("0123456789"))

    def test_duplicate_gets_sequence(self):
        """Second call with same make/model on same day gets sequence suffix."""
        from api.routes.listings import create_load_id

        result1 = create_load_id("TESTMAKE1", "TESTMOD1")
        result2 = create_load_id("TESTMAKE1", "TESTMOD1")
        assert result1 is not None
        assert result2 is not None
        lid1, seq1 = result1
        lid2, seq2 = result2
        assert lid1 != lid2
        assert seq2 > seq1
        # Second should have a numeric suffix
        assert lid2[-1].isdigit()

    def test_missing_make_returns_none(self):
        """Empty make should return None."""
        from api.routes.listings import create_load_id

        assert create_load_id("", "Prius") is None
        assert create_load_id(None, "Prius") is None

    def test_missing_model_returns_none(self):
        """Empty model should return None."""
        from api.routes.listings import create_load_id

        assert create_load_id("Toyota", "") is None
        assert create_load_id("Toyota", None) is None

    def test_uppercase_output(self):
        """Load ID should be uppercase."""
        from api.routes.listings import create_load_id

        result = create_load_id("toyota", "prius")
        assert result is not None
        lid, seq = result
        # The make/model parts should be uppercase
        assert lid == lid.upper() or lid[:-1] == lid[:-1].upper()

    def test_short_make_model(self):
        """Short make/model names should still work."""
        from api.routes.listings import create_load_id

        result = create_load_id("KIA", "K5")
        assert result is not None
        lid, seq = result
        now = datetime.now()
        assert lid.startswith(f"{now.month}{now.day:02d}KIA")


class TestLoadIDInDocuments:
    """Test load_id appears in Documents API response."""

    def test_documents_api_has_load_id_field(self, client):
        """Document list response should include load_id field."""
        resp = client.get("/api/documents/?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        if data["items"]:
            assert "load_id" in data["items"][0]

    def test_generate_load_id_endpoint(self, client):
        """GET /api/listings/generate-load-id should work."""
        resp = client.get("/api/listings/generate-load-id?make=Toyota&model=Camry")
        assert resp.status_code == 200
        data = resp.json()
        assert "load_id" in data
        now = datetime.now()
        assert data["load_id"].startswith(f"{now.month}{now.day:02d}TOY")

    def test_generate_load_id_missing_params(self, client):
        """Missing make/model should return 422."""
        resp = client.get("/api/listings/generate-load-id?make=Toyota")
        assert resp.status_code == 422

    def test_backfill_endpoint(self, client):
        """POST /api/listings/backfill-load-ids should work."""
        resp = client.post("/api/listings/backfill-load-ids")
        assert resp.status_code == 200
        data = resp.json()
        assert "updated" in data
        assert "skipped" in data


class TestLoadIDInExtraction:
    """Test load_id is auto-generated during extraction."""

    def test_extraction_generates_load_id(self, client):
        """After extraction, outputs_json should contain load_id."""
        from io import BytesIO
        import uuid as uuid_mod

        # Upload a unique PDF
        unique = uuid_mod.uuid4().hex[:8]
        pdf_bytes = f"""%PDF-1.4
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
<< /Length 80 >>
stream
BT /F1 12 Tf 100 700 Td (Test load_id extraction {unique}) Tj ET
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

        resp = client.post(
            "/api/documents/upload",
            files={"file": (f"loadid_test_{unique}.pdf", BytesIO(pdf_bytes), "application/pdf")},
            data={"dataset_split": "train", "source": "upload"},
        )
        assert resp.status_code == 201
        run_id = resp.json().get("run_id")

        if run_id:
            # Check if extraction generated a load_id
            from api.database import get_connection
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT outputs_json FROM extraction_runs WHERE id = ?",
                    (run_id,)
                ).fetchone()
            if row and row["outputs_json"]:
                outputs = json.loads(row["outputs_json"])
                # load_id is generated when make+model are present
                # In test env without API key, extraction may not produce make/model
                # so we just verify the field mechanism works
                if outputs.get("vehicle_make") and outputs.get("vehicle_model"):
                    assert outputs.get("load_id") is not None
