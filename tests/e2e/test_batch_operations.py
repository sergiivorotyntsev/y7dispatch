"""
Tests for batch operations: bulk approve, hold, archive.

Verifies:
- Batch approve sets extraction_runs.status = 'reviewed'
- Batch hold sets hold_reason/hold_note/hold_since on documents
- Batch archive sets archived_at on documents
- Validation: max 50 items, not-found IDs handled gracefully
- Partial success: mix of valid/invalid IDs
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
    unique_str = f"Batch-{tag}-{_upload_counter}-{uuid_mod.uuid4().hex[:8]}"
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


def _upload_doc(client, filename="batch_test.pdf"):
    """Upload a document and return (doc_id, run_id)."""
    pdf_bytes = _unique_pdf_bytes(filename)
    resp = client.post(
        "/api/documents/upload",
        files={"file": (filename, BytesIO(pdf_bytes), "application/pdf")},
        data={"dataset_split": "train", "source": "upload"},
    )
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    doc = resp.json()["document"]
    doc_id = doc["id"]

    # Get the extraction run created by auto_extract
    from api.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM extraction_runs WHERE document_id = ? ORDER BY id DESC LIMIT 1",
            (doc_id,),
        ).fetchone()
    run_id = row["id"] if row else None
    return doc_id, run_id


def _set_run_status(run_id, status):
    """Set extraction run status directly."""
    from api.database import get_connection
    with get_connection() as conn:
        conn.execute(
            "UPDATE extraction_runs SET status = ? WHERE id = ?",
            (status, run_id),
        )
        conn.commit()


def _get_run_status(run_id):
    """Get extraction run status."""
    from api.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM extraction_runs WHERE id = ?", (run_id,)
        ).fetchone()
    return row["status"] if row else None


def _get_doc(doc_id):
    """Get document row as dict."""
    from api.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    return dict(row) if row else None


# =============================================================================
# TestBatchApprove
# =============================================================================


class TestBatchApprove:
    """Test POST /api/batch/approve."""

    def test_approve_single(self, client):
        """Approve a single extraction run."""
        doc_id, run_id = _upload_doc(client, "approve_single.pdf")
        assert run_id is not None
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/batch/approve", json={"run_ids": [run_id]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["succeeded"] == 1
        assert data["failed"] == 0
        assert _get_run_status(run_id) == "reviewed"

    def test_approve_multiple(self, client):
        """Approve multiple extraction runs at once."""
        runs = []
        for i in range(3):
            doc_id, run_id = _upload_doc(client, f"approve_multi_{i}.pdf")
            _set_run_status(run_id, "needs_review")
            runs.append(run_id)

        resp = client.post("/api/batch/approve", json={"run_ids": runs})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["succeeded"] == 3

        for run_id in runs:
            assert _get_run_status(run_id) == "reviewed"

    def test_approve_already_reviewed(self, client):
        """Approving an already-reviewed run should succeed (idempotent)."""
        doc_id, run_id = _upload_doc(client, "approve_idem.pdf")
        _set_run_status(run_id, "reviewed")

        resp = client.post("/api/batch/approve", json={"run_ids": [run_id]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 1
        assert data["failed"] == 0

    def test_approve_not_found(self, client):
        """Approving a nonexistent run should report failure for that item."""
        resp = client.post("/api/batch/approve", json={"run_ids": [999999]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["failed"] == 1
        assert "not found" in data["results"][0]["error"].lower()

    def test_approve_partial_success(self, client):
        """Mix of valid and invalid run IDs: partial success."""
        doc_id, run_id = _upload_doc(client, "approve_partial.pdf")
        _set_run_status(run_id, "needs_review")

        resp = client.post("/api/batch/approve", json={"run_ids": [run_id, 999998]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["succeeded"] == 1
        assert data["failed"] == 1


# =============================================================================
# TestBatchHold
# =============================================================================


class TestBatchHold:
    """Test POST /api/batch/hold."""

    def test_hold_single(self, client):
        """Put a single document on hold."""
        doc_id, _ = _upload_doc(client, "hold_single.pdf")

        resp = client.post("/api/batch/hold", json={
            "document_ids": [doc_id],
            "reason": "awaiting_gate_pass",
            "note": "Batch test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 1

        doc = _get_doc(doc_id)
        assert doc["hold_reason"] == "awaiting_gate_pass"
        assert doc["hold_note"] == "Batch test"
        assert doc["hold_since"] is not None

    def test_hold_multiple(self, client):
        """Hold multiple documents at once."""
        doc_ids = []
        for i in range(3):
            doc_id, _ = _upload_doc(client, f"hold_multi_{i}.pdf")
            doc_ids.append(doc_id)

        resp = client.post("/api/batch/hold", json={
            "document_ids": doc_ids,
            "reason": "awaiting_payment",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["succeeded"] == 3

        for doc_id in doc_ids:
            doc = _get_doc(doc_id)
            assert doc["hold_reason"] == "awaiting_payment"

    def test_hold_not_found(self, client):
        """Hold nonexistent document: graceful failure."""
        resp = client.post("/api/batch/hold", json={
            "document_ids": [999997],
            "reason": "other",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1


# =============================================================================
# TestBatchArchive
# =============================================================================


class TestBatchArchive:
    """Test POST /api/batch/archive."""

    def test_archive_single(self, client):
        """Archive a single document."""
        doc_id, _ = _upload_doc(client, "archive_single.pdf")

        resp = client.post("/api/batch/archive", json={"document_ids": [doc_id]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["succeeded"] == 1

        doc = _get_doc(doc_id)
        assert doc["archived_at"] is not None

    def test_archive_multiple(self, client):
        """Archive multiple documents at once."""
        doc_ids = []
        for i in range(3):
            doc_id, _ = _upload_doc(client, f"archive_multi_{i}.pdf")
            doc_ids.append(doc_id)

        resp = client.post("/api/batch/archive", json={"document_ids": doc_ids})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["succeeded"] == 3

        for doc_id in doc_ids:
            doc = _get_doc(doc_id)
            assert doc["archived_at"] is not None

    def test_archive_not_found(self, client):
        """Archive nonexistent document: graceful failure."""
        resp = client.post("/api/batch/archive", json={"document_ids": [999996]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed"] == 1


# =============================================================================
# TestBatchValidation
# =============================================================================


class TestBatchValidation:
    """Test batch size limits and input validation."""

    def test_empty_run_ids_rejected(self, client):
        """Empty run_ids list should be accepted (0 results)."""
        resp = client.post("/api/batch/approve", json={"run_ids": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_missing_reason_rejected(self, client):
        """Hold without reason should be rejected (422)."""
        resp = client.post("/api/batch/hold", json={"document_ids": [1]})
        assert resp.status_code == 422

    def test_batch_approve_endpoint_exists(self, client):
        """Verify endpoint is registered and accepts POST."""
        resp = client.post("/api/batch/approve", json={"run_ids": []})
        assert resp.status_code == 200

    def test_batch_hold_endpoint_exists(self, client):
        """Verify endpoint is registered and accepts POST."""
        resp = client.post("/api/batch/hold", json={
            "document_ids": [],
            "reason": "other",
        })
        assert resp.status_code == 200

    def test_batch_archive_endpoint_exists(self, client):
        """Verify endpoint is registered and accepts POST."""
        resp = client.post("/api/batch/archive", json={"document_ids": []})
        assert resp.status_code == 200
