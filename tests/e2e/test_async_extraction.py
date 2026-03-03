"""
E2E Tests — Async Extraction with Background Processing

Tests cover:
  - POST /api/extractions/run?sync=false returns immediately (not blocked)
  - Background extraction updates processing_step in DB
  - GET /api/extractions/status/{run_id} returns correct processing status
"""

import json
import uuid

import pytest

from api.database import get_connection
from api.models import ExtractionRunRepository


def _create_test_doc_and_run(conn, status="processing", processing_step=None, processing_message=None):
    """Helper: create a document + extraction_run for status testing."""
    doc_uuid = str(uuid.uuid4())
    run_uuid = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO documents (uuid, auction_type_id, dataset_split, filename, file_path) "
        "VALUES (?, 1, 'train', 'test_async.pdf', '/tmp/test_async.pdf')",
        (doc_uuid,),
    )
    doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    cols = "uuid, document_id, auction_type_id, status"
    vals = [run_uuid, doc_id, 1, status]
    placeholders = "?, ?, ?, ?"

    if processing_step is not None:
        cols += ", processing_step"
        vals.append(processing_step)
        placeholders += ", ?"
    if processing_message is not None:
        cols += ", processing_message"
        vals.append(processing_message)
        placeholders += ", ?"

    conn.execute(
        f"INSERT INTO extraction_runs ({cols}) VALUES ({placeholders})",
        vals,
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return run_id, doc_id


class TestAsyncReturnsImmediately:
    """POST /api/extractions/run?sync=false should return quickly with status=pending/processing."""

    def test_async_returns_processing_status(self, client):
        """Async endpoint returns run with pending/processing status without waiting for extraction."""
        # Create a document with auction type
        with get_connection() as conn:
            doc_uuid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO documents (uuid, auction_type_id, dataset_split, filename, file_path) "
                "VALUES (?, 1, 'train', 'async_test.pdf', '/tmp/async_test.pdf')",
                (doc_uuid,),
            )
            doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()

        import time
        start = time.time()
        resp = client.post(
            "/api/extractions/run?sync=false",
            json={"document_id": doc_id},
        )
        elapsed = time.time() - start

        # Should return quickly (not blocked by extraction)
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] is not None
        assert data["status"] in ("pending", "processing")
        # Should return in under 5 seconds (extraction itself takes 10-60s)
        assert elapsed < 5, f"Async endpoint took {elapsed:.1f}s — should be <5s"


class TestStatusEndpoint:
    """GET /api/extractions/status/{run_id} returns processing status."""

    def test_status_returns_processing_info(self, client):
        """Status endpoint returns processing_step and processing_message."""
        with get_connection() as conn:
            run_id, _ = _create_test_doc_and_run(
                conn,
                status="processing",
                processing_step="calling_haiku",
                processing_message="Running AI extraction...",
            )

        resp = client.get(f"/api/extractions/status/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == run_id
        assert data["status"] == "processing"
        assert data["processing_step"] == "calling_haiku"
        assert data["processing_message"] == "Running AI extraction..."

    def test_status_404_for_missing_run(self, client):
        """Status endpoint returns 404 for non-existent run."""
        resp = client.get("/api/extractions/status/999999")
        assert resp.status_code == 404

    def test_status_completed_run(self, client):
        """Status endpoint works for completed runs too."""
        with get_connection() as conn:
            run_id, _ = _create_test_doc_and_run(
                conn,
                status="needs_review",
                processing_step="completing",
                processing_message="Saving results...",
            )

        resp = client.get(f"/api/extractions/status/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "needs_review"
        assert data["processing_step"] == "completing"
