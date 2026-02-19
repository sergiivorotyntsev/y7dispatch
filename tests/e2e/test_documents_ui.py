"""
Tests for Documents UI backend: search, enriched response, pending status.

Day 13 Part B features:
- Document list enriched with VIN, vehicle, pickup from extraction runs
- Server-side search across VIN, make, model, lot, gate_pass, filename
- PENDING status with set-pending/clear-pending endpoints
"""

import json
import uuid as uuid_mod
from io import BytesIO

import pytest


_upload_counter = 0


# =============================================================================
# Helpers
# =============================================================================


def _unique_pdf_bytes(tag=""):
    """Generate unique PDF bytes each call (different SHA256)."""
    global _upload_counter
    _upload_counter += 1
    unique_str = f"Test-{tag}-{_upload_counter}-{uuid_mod.uuid4().hex[:8]}"
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
<< /Length {len(unique_str) + 44} >>
stream
BT /F1 12 Tf 100 700 Td ({unique_str}) Tj ET
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


def _upload_doc(client, filename="test.pdf", auction_type_id=None, pdf_bytes=None):
    """Upload a document and return the response JSON."""
    if pdf_bytes is None:
        pdf_bytes = _unique_pdf_bytes(filename)

    data = {"dataset_split": "train", "source": "upload"}
    if auction_type_id:
        data["auction_type_id"] = str(auction_type_id)

    resp = client.post(
        "/api/documents/upload",
        files={"file": (filename, BytesIO(pdf_bytes), "application/pdf")},
        data=data,
    )
    return resp


def _set_extraction_outputs(doc_id, outputs: dict):
    """Update the latest extraction run's outputs_json for a document."""
    from api.database import get_connection

    with get_connection() as conn:
        # Update the existing run created by auto_extract
        conn.execute(
            """UPDATE extraction_runs
               SET outputs_json = ?, status = 'needs_review'
               WHERE document_id = ?
               AND id = (SELECT MAX(id) FROM extraction_runs WHERE document_id = ?)""",
            (json.dumps(outputs), doc_id, doc_id),
        )
        conn.commit()


# =============================================================================
# TestDocumentsSearch
# =============================================================================


class TestDocumentsSearch:
    """Test server-side search in documents list."""

    def test_search_returns_200(self, client):
        """Search endpoint returns 200 even with no results."""
        resp = client.get("/api/documents/?search=NONEXISTENT_VIN_XYZ")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_search_by_vin(self, client):
        """Search should find documents by VIN."""
        upload_resp = _upload_doc(client, "search_vin_test.pdf")
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["document"]["id"]

        _set_extraction_outputs(doc_id, {
            "vehicle_vin": "1HGBH41JXMN109186",
            "vehicle_make": "Honda",
        })

        resp = client.get("/api/documents/?search=1HGBH41JXMN109186")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        found_ids = [item["id"] for item in data["items"]]
        assert doc_id in found_ids

    def test_search_by_make(self, client):
        """Search should find documents by vehicle make."""
        upload_resp = _upload_doc(client, "search_make_test.pdf")
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["document"]["id"]

        _set_extraction_outputs(doc_id, {
            "vehicle_vin": "WBAPH5C55BA123456",
            "vehicle_make": "BMW",
            "vehicle_model": "535i",
        })

        resp = client.get("/api/documents/?search=BMW")
        assert resp.status_code == 200
        data = resp.json()
        found_ids = [item["id"] for item in data["items"]]
        assert doc_id in found_ids

    def test_search_by_filename(self, client):
        """Search should find documents by filename."""
        unique_name = "UniqueSearchFileName12345.pdf"
        upload_resp = _upload_doc(client, unique_name)
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["document"]["id"]

        resp = client.get("/api/documents/?search=UniqueSearchFileName12345")
        assert resp.status_code == 200
        data = resp.json()
        found_ids = [item["id"] for item in data["items"]]
        assert doc_id in found_ids

    def test_search_empty_string_returns_all(self, client):
        """Empty search string should return normal document list."""
        resp = client.get("/api/documents/?search=")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data

    def test_enriched_response_has_vin(self, client):
        """Document list response should include enriched VIN field."""
        upload_resp = _upload_doc(client, "enrich_test.pdf")
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["document"]["id"]

        _set_extraction_outputs(doc_id, {
            "vehicle_vin": "JN1TBNT30Z0000001",
            "vehicle_year": "2025",
            "vehicle_make": "Nissan",
            "vehicle_model": "Altima",
            "pickup_city": "Dallas",
            "pickup_state": "TX",
        })

        resp = client.get("/api/documents/")
        assert resp.status_code == 200
        data = resp.json()

        # Find our doc in the list
        our_doc = next((d for d in data["items"] if d["id"] == doc_id), None)
        assert our_doc is not None
        assert our_doc["vin"] == "JN1TBNT30Z0000001"
        assert our_doc["vehicle_year"] == "2025"
        assert our_doc["vehicle_make"] == "Nissan"
        assert our_doc["vehicle_model"] == "Altima"
        assert our_doc["pickup_city"] == "Dallas"
        assert our_doc["pickup_state"] == "TX"
        assert our_doc["extraction_status"] == "needs_review"
        assert our_doc["extraction_run_id"] is not None


# =============================================================================
# TestPendingStatus
# =============================================================================


class TestPendingStatus:
    """Test PENDING status: set-pending and clear-pending endpoints."""

    def test_set_pending_returns_success(self, client):
        """Setting pending status should return success."""
        upload_resp = _upload_doc(client, "pending_test.pdf", )
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["document"]["id"]

        resp = client.post(
            f"/api/documents/{doc_id}/set-pending",
            json={"reason": "Awaiting gate pass"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["pending_reason"] == "Awaiting gate pass"

    def test_set_pending_persists_in_list(self, client):
        """Pending reason should appear in document list response."""
        upload_resp = _upload_doc(client, "pending_list_test.pdf", )
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["document"]["id"]

        client.post(
            f"/api/documents/{doc_id}/set-pending",
            json={"reason": "Vehicle not released"},
        )

        resp = client.get("/api/documents/")
        data = resp.json()
        our_doc = next((d for d in data["items"] if d["id"] == doc_id), None)
        assert our_doc is not None
        assert our_doc["pending_reason"] == "Vehicle not released"

    def test_clear_pending(self, client):
        """Clearing pending should remove the reason."""
        upload_resp = _upload_doc(client, "clear_pending_test.pdf", )
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["document"]["id"]

        # Set pending
        client.post(
            f"/api/documents/{doc_id}/set-pending",
            json={"reason": "Awaiting title"},
        )

        # Clear pending
        resp = client.post(f"/api/documents/{doc_id}/clear-pending")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["pending_reason"] is None

        # Verify in list
        list_resp = client.get("/api/documents/")
        list_data = list_resp.json()
        our_doc = next((d for d in list_data["items"] if d["id"] == doc_id), None)
        assert our_doc is not None
        assert our_doc["pending_reason"] is None

    def test_set_pending_nonexistent_doc(self, client):
        """Setting pending on nonexistent document should return 404."""
        resp = client.post(
            "/api/documents/999999/set-pending",
            json={"reason": "test"},
        )
        assert resp.status_code == 404

    def test_clear_pending_nonexistent_doc(self, client):
        """Clearing pending on nonexistent document should return 404."""
        resp = client.post("/api/documents/999999/clear-pending")
        assert resp.status_code == 404

    def test_set_pending_updates_reason(self, client):
        """Setting pending again should update the reason."""
        upload_resp = _upload_doc(client, "update_pending_test.pdf", )
        assert upload_resp.status_code == 201
        doc_id = upload_resp.json()["document"]["id"]

        # Set first reason
        client.post(
            f"/api/documents/{doc_id}/set-pending",
            json={"reason": "Awaiting gate pass"},
        )

        # Update reason
        client.post(
            f"/api/documents/{doc_id}/set-pending",
            json={"reason": "Vehicle release delayed"},
        )

        resp = client.get("/api/documents/")
        data = resp.json()
        our_doc = next((d for d in data["items"] if d["id"] == doc_id), None)
        assert our_doc is not None
        assert our_doc["pending_reason"] == "Vehicle release delayed"
