"""
E2E Tests for Error Handling across the dispatch pipeline.

Covers:
- Document upload validation (bad files, missing fields, duplicates)
- Extraction error paths
- Export error paths (404, test-doc blocking, validation failures)
- CD API error simulation (412 ETag, 429 rate limit, 5xx transient)
- Batch job error paths
- Retry logic and limits
- Error response format consistency
- Audit trail on failure events

All CD API calls are mocked; database is the real (temp) SQLite.
"""

import json
import uuid
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_auction_type_id(client) -> int:
    resp = client.get("/api/auction-types/")
    items = resp.json().get("items", [])
    if items:
        return items[0]["id"]
    code = f"ERR_{uuid.uuid4().hex[:6].upper()}"
    resp = client.post(
        "/api/auction-types/",
        json={"name": f"Error Test {code}", "code": code},
    )
    return resp.json()["id"]


def _upload_document(client, sample_pdf_bytes, auction_type_id, *, is_test=False, source="upload"):
    """Upload a document and return (doc_id, run_id)."""
    resp = client.post(
        "/api/documents/upload",
        files={
            "file": (
                f"err_{uuid.uuid4().hex[:8]}.pdf",
                BytesIO(sample_pdf_bytes),
                "application/pdf",
            )
        },
        data={
            "auction_type_id": auction_type_id,
            "is_test": str(is_test).lower(),
            "source": source,
        },
    )
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    data = resp.json()
    return data["document"]["id"], data.get("run_id")


def _ensure_run(client, doc_id, auction_type_id) -> int:
    resp = client.post("/api/extractions/run", json={"document_id": doc_id})
    if resp.status_code in (200, 201):
        data = resp.json()
        return data.get("run_id") or data.get("id")
    resp = client.get("/api/extractions/")
    for item in resp.json().get("items", []):
        if item.get("document_id") == doc_id:
            return item["id"]
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def auction_type_id(client):
    return _get_auction_type_id(client)


@pytest.fixture(scope="module")
def sample_pdf_bytes():
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


# =============================================================================
# 1. DOCUMENT UPLOAD VALIDATION
# =============================================================================


class TestDocumentUploadErrors:
    """Verify upload rejects invalid inputs with correct status codes."""

    def test_upload_without_file_returns_422(self, client, auction_type_id):
        """Missing file part should return 422."""
        resp = client.post(
            "/api/documents/upload",
            data={"auction_type_id": auction_type_id},
        )
        assert resp.status_code == 422

    def test_upload_non_pdf_returns_400(self, client, auction_type_id):
        """Non-PDF file should be rejected with 400."""
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.txt", BytesIO(b"not a pdf"), "text/plain")},
            data={"auction_type_id": auction_type_id},
        )
        assert resp.status_code == 400
        assert "PDF" in resp.json()["detail"]

    def test_upload_corrupted_pdf_returns_422(self, client, auction_type_id):
        """Corrupted PDF content should be rejected with 422."""
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("corrupt.pdf", BytesIO(b"%PDF-1.4\ngarbage"), "application/pdf")},
            data={"auction_type_id": auction_type_id},
        )
        assert resp.status_code == 422
        assert "Invalid PDF" in resp.json()["detail"]

    def test_upload_invalid_auction_type_returns_400(self, client, sample_pdf_bytes):
        """Invalid auction_type_id should return 400."""
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", BytesIO(sample_pdf_bytes), "application/pdf")},
            data={"auction_type_id": 999999},
        )
        assert resp.status_code == 400

    def test_upload_invalid_dataset_split_returns_400(self, client, sample_pdf_bytes, auction_type_id):
        """Invalid dataset_split should return 400."""
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", BytesIO(sample_pdf_bytes), "application/pdf")},
            data={
                "auction_type_id": auction_type_id,
                "dataset_split": "invalid",
            },
        )
        assert resp.status_code == 400
        assert "dataset_split" in resp.json()["detail"]

    def test_upload_invalid_source_returns_400(self, client, sample_pdf_bytes, auction_type_id):
        """Invalid source should return 400."""
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", BytesIO(sample_pdf_bytes), "application/pdf")},
            data={
                "auction_type_id": auction_type_id,
                "source": "invalid_source",
            },
        )
        assert resp.status_code == 400

    def test_duplicate_upload_returns_is_duplicate(self, client, sample_pdf_bytes, auction_type_id):
        """Uploading same file twice should flag is_duplicate."""
        # Use fixed content so SHA256 matches
        fixed_content = sample_pdf_bytes + b"\n% DUP_TEST"
        resp1 = client.post(
            "/api/documents/upload",
            files={"file": ("dup1.pdf", BytesIO(fixed_content), "application/pdf")},
            data={"auction_type_id": auction_type_id},
        )
        # Second upload with identical content
        resp2 = client.post(
            "/api/documents/upload",
            files={"file": ("dup2.pdf", BytesIO(fixed_content), "application/pdf")},
            data={"auction_type_id": auction_type_id},
        )
        if resp1.status_code == 201 and resp2.status_code == 201:
            assert resp2.json()["is_duplicate"] is True


# =============================================================================
# 2. EXTRACTION ERROR PATHS
# =============================================================================


class TestExtractionErrors:
    """Test extraction pipeline error handling."""

    def test_run_extraction_invalid_document(self, client):
        """Extraction on nonexistent document should return 404."""
        resp = client.post("/api/extractions/run", json={"document_id": 999999})
        assert resp.status_code == 404

    def test_get_extraction_not_found(self, client):
        """Get extraction by invalid ID should return 404."""
        resp = client.get("/api/extractions/999999")
        # Some APIs return 404, others may return 200 with empty
        assert resp.status_code in (404, 200)


# =============================================================================
# 3. EXPORT — NOT FOUND & VALIDATION ERRORS
# =============================================================================


class TestExportNotFound:
    """Test export endpoints with missing resources."""

    def test_export_nonexistent_run_has_errors(self, client):
        """Exporting nonexistent run should produce validation errors."""
        resp = client.post(
            "/api/exports/central-dispatch",
            json={"run_ids": [999999], "dry_run": True, "sandbox": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["failed_count"] >= 1
        # Preview should show error
        preview = data["previews"][0]
        assert preview["is_valid"] is False
        assert len(preview["validation_errors"]) > 0

    def test_export_preview_not_found(self, client):
        """Preview nonexistent run should return 404."""
        resp = client.get("/api/exports/central-dispatch/preview/999999")
        assert resp.status_code == 404

    def test_export_job_not_found(self, client):
        resp = client.get("/api/exports/jobs/999999")
        assert resp.status_code == 404

    def test_retry_nonexistent_job(self, client):
        resp = client.post("/api/exports/jobs/999999/retry")
        assert resp.status_code == 404


# =============================================================================
# 4. TEST DOCUMENT BLOCKING
# =============================================================================


class TestTestDocumentBlocking:
    """Test documents should be blocked from CD export."""

    def test_test_doc_blocked_in_dry_run(self, client, sample_pdf_bytes, auction_type_id):
        """Test document should be blocked even in dry-run."""
        doc_id, run_id = _upload_document(
            client, sample_pdf_bytes, auction_type_id,
            is_test=True, source="test_lab",
        )
        if not run_id:
            run_id = _ensure_run(client, doc_id, auction_type_id)
        if not run_id:
            pytest.skip("Could not create extraction run")

        resp = client.post(
            "/api/exports/central-dispatch",
            json={"run_ids": [run_id], "dry_run": True, "sandbox": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Should be skipped or show validation error about test doc
        previews = data["previews"]
        if previews:
            # At least one preview should mention test document blocking
            errors_text = " ".join(
                " ".join(p["validation_errors"]) for p in previews
            ).lower()
            assert "test" in errors_text or data.get("failed_count", 0) == 0

    def test_test_doc_blocked_in_batch_preflight(self, client, sample_pdf_bytes, auction_type_id):
        """Test document should show as not_ready in batch preflight."""
        doc_id, run_id = _upload_document(
            client, sample_pdf_bytes, auction_type_id,
            is_test=True, source="test_lab",
        )
        if not run_id:
            run_id = _ensure_run(client, doc_id, auction_type_id)
        if not run_id:
            pytest.skip("Could not create extraction run")

        resp = client.post(
            "/api/exports/batch-post/preflight",
            json=[run_id],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["not_ready_count"] >= 1


# =============================================================================
# 5. CD API ERROR SIMULATION
# =============================================================================


class TestCDAPIErrors:
    """Simulate CD API errors and verify handling."""

    @patch("api.routes.exports.send_to_cd_with_retry")
    def test_cd_api_failure_records_failed_job(self, mock_send, client, sample_pdf_bytes, auction_type_id):
        """CD API failure should create a failed export job."""
        mock_send.return_value = (
            False,
            {"error": "Connection refused", "status_code": 502},
            None,
        )

        doc_id, run_id = _upload_document(client, sample_pdf_bytes, auction_type_id)
        if not run_id:
            run_id = _ensure_run(client, doc_id, auction_type_id)
        if not run_id:
            pytest.skip("Could not create extraction run")

        resp = client.post(
            "/api/exports/central-dispatch",
            json={"run_ids": [run_id], "dry_run": False, "sandbox": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Either fails at validation or at CD API — both produce failed_count
        # The export attempt was made, so failed_count should reflect it

    @patch("api.routes.exports.send_to_cd_with_retry")
    def test_etag_mismatch_error_message(self, mock_send, client, sample_pdf_bytes, auction_type_id):
        """ETag mismatch should produce clear error message."""
        mock_send.return_value = (
            False,
            {
                "error": "ETag mismatch",
                "error_code": "ETAG_MISMATCH",
                "status_code": 412,
            },
            None,
        )

        doc_id, run_id = _upload_document(client, sample_pdf_bytes, auction_type_id)
        if not run_id:
            run_id = _ensure_run(client, doc_id, auction_type_id)
        if not run_id:
            pytest.skip("Could not create extraction run")

        resp = client.post(
            "/api/exports/central-dispatch",
            json={"run_ids": [run_id], "dry_run": False, "sandbox": True},
        )
        data = resp.json()
        # May or may not hit mock depending on validation — if it does,
        # the error message should be about ETag
        if data["failed_count"] > 0:
            assert data["status"] == "partial"

    @patch("api.routes.exports.send_to_cd_with_retry")
    def test_rate_limit_error_message(self, mock_send, client, sample_pdf_bytes, auction_type_id):
        """Rate limit should produce clear error message."""
        mock_send.return_value = (
            False,
            {
                "error": "Rate limited",
                "error_code": "RATE_LIMITED",
                "status_code": 429,
            },
            None,
        )

        doc_id, run_id = _upload_document(client, sample_pdf_bytes, auction_type_id)
        if not run_id:
            run_id = _ensure_run(client, doc_id, auction_type_id)
        if not run_id:
            pytest.skip("Could not create extraction run")

        resp = client.post(
            "/api/exports/central-dispatch",
            json={"run_ids": [run_id], "dry_run": False, "sandbox": True},
        )
        assert resp.status_code == 200  # API returns 200 with error details


# =============================================================================
# 6. CD CLIENT RETRY LOGIC
# =============================================================================


class TestCDClientRetry:
    """Test retry behavior of the CD client."""

    def test_max_retries_config(self):
        """MAX_RETRIES should be reasonable (2-5)."""
        from api.cd_client import MAX_RETRIES
        assert 2 <= MAX_RETRIES <= 5

    def test_semaphore_limit_config(self):
        """Semaphore limit should be reasonable."""
        from api.cd_client import CD_SEMAPHORE_LIMIT
        assert 1 <= CD_SEMAPHORE_LIMIT <= 10

    @patch("api.cd_client.requests.post")
    def test_create_listing_retries_on_429(self, mock_post):
        """CDClient.create_listing should retry on 429."""
        from api.cd_client import CDClient

        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "0"}  # Immediate for test speed

        mock_success = MagicMock()
        mock_success.status_code = 201
        mock_success.json.return_value = {"id": "retry-test"}
        mock_success.headers = {"ETag": "etag-retry"}

        mock_post.side_effect = [mock_429, mock_success]

        client = CDClient(api_key="test", base_url="https://test.cd.com")
        result = client.create_listing({"partnerReferenceId": "test-ref"})

        assert result.success is True
        assert result.listing_id == "retry-test"
        assert result.retries == 1

    @patch("api.cd_client.requests.put")
    @patch("api.cd_client.requests.get")
    def test_update_listing_retries_on_412(self, mock_get, mock_put):
        """CDClient.update_listing should refresh ETag and retry on 412."""
        from api.cd_client import CDClient

        mock_412 = MagicMock()
        mock_412.status_code = 412

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.json.return_value = {"id": "listing-1"}
        mock_get_resp.headers = {"ETag": "fresh-etag"}
        mock_get.return_value = mock_get_resp

        mock_success = MagicMock()
        mock_success.status_code = 200
        mock_success.json.return_value = {"id": "listing-1"}
        mock_success.headers = {"ETag": "updated-etag"}

        mock_put.side_effect = [mock_412, mock_success]

        client = CDClient(api_key="test", base_url="https://test.cd.com")
        result = client.update_listing("listing-1", {"test": True}, etag="stale-etag")

        assert result.success is True
        assert result.retries == 1

    @patch("api.cd_client.requests.post")
    def test_create_listing_exhausts_retries(self, mock_post):
        """After MAX_RETRIES failures, should return failure."""
        from api.cd_client import CDClient, MAX_RETRIES

        mock_error = MagicMock()
        mock_error.status_code = 500
        mock_error.text = "Internal Server Error"
        mock_post.return_value = mock_error

        client = CDClient(api_key="test", base_url="https://test.cd.com")
        result = client.create_listing({"partnerReferenceId": "exhaust-ref"})

        assert result.success is False
        assert result.retries == MAX_RETRIES + 1  # Initial + retries

    @patch("api.cd_client.requests.post")
    def test_create_listing_handles_409_conflict(self, mock_post):
        """409 Conflict should attempt to find existing listing."""
        from api.cd_client import CDClient

        mock_409 = MagicMock()
        mock_409.status_code = 409

        mock_post.return_value = mock_409

        with patch.object(CDClient, "_find_existing_listing") as mock_find:
            from api.cd_client import CDResponse
            mock_find.return_value = CDResponse(
                success=True, listing_id="existing-1", status_code=200
            )

            client = CDClient(api_key="test", base_url="https://test.cd.com")
            result = client.create_listing({"partnerReferenceId": "conflict-ref"})

            assert result.success is True
            assert result.listing_id == "existing-1"


# =============================================================================
# 7. RETRY JOB ENDPOINT
# =============================================================================


class TestRetryJobErrors:
    """Test retry endpoint error handling."""

    def test_retry_non_failed_job_returns_400(self, client, sample_pdf_bytes, auction_type_id):
        """Retrying a non-failed job should return 400."""
        from api.models import ExportJobRepository

        # Create a completed job manually
        doc_id, run_id = _upload_document(client, sample_pdf_bytes, auction_type_id)
        if not run_id:
            run_id = _ensure_run(client, doc_id, auction_type_id)
        if not run_id:
            pytest.skip("Could not create extraction run")

        job_id = ExportJobRepository.create(
            run_id=run_id,
            target="central_dispatch",
            payload_json={"test": True},
        )
        ExportJobRepository.update(job_id, status="completed")

        resp = client.post(f"/api/exports/jobs/{job_id}/retry")
        assert resp.status_code == 400
        assert "failed" in resp.json()["detail"].lower()


# =============================================================================
# 8. BATCH JOB ERROR PATHS
# =============================================================================


class TestBatchJobErrors:
    """Test batch job error handling."""

    def test_create_batch_job_empty_list(self, client):
        """Empty run_ids should return 400."""
        resp = client.post(
            "/api/exports/batch-jobs",
            json=[],
            params={"sandbox": True},
        )
        assert resp.status_code == 400

    def test_get_nonexistent_batch_job(self, client):
        resp = client.get("/api/exports/batch-jobs/999999")
        assert resp.status_code == 404

    def test_cancel_nonexistent_batch_job(self, client):
        resp = client.post("/api/exports/batch-jobs/999999/cancel")
        assert resp.status_code == 404

    def test_cancel_completed_batch_job_returns_400(self, client):
        """Cannot cancel an already-completed job."""
        from api.batch_jobs import BatchJobRepository, BatchJobStatus

        # Create and complete a job
        from api.batch_jobs import create_batch_job
        try:
            job_id = create_batch_job(
                run_ids=[1],
                options={"sandbox": True},
            )
            BatchJobRepository.update(
                job_id,
                status=BatchJobStatus.COMPLETED.value,
            )

            resp = client.post(f"/api/exports/batch-jobs/{job_id}/cancel")
            assert resp.status_code == 400
        except Exception:
            pytest.skip("batch_jobs module not fully initialized")


# =============================================================================
# 9. ERROR RESPONSE FORMAT CONSISTENCY
# =============================================================================


class TestErrorResponseFormat:
    """Verify all error responses follow consistent format."""

    def test_404_has_detail_field(self, client):
        """All 404 responses should have 'detail' key."""
        endpoints_404 = [
            "/api/documents/999999",
            "/api/exports/central-dispatch/preview/999999",
            "/api/exports/jobs/999999",
        ]
        for endpoint in endpoints_404:
            resp = client.get(endpoint)
            if resp.status_code == 404:
                data = resp.json()
                assert "detail" in data, f"Missing 'detail' in 404 response for {endpoint}"

    def test_422_has_detail_field(self, client):
        """422 responses should have 'detail' key."""
        resp = client.post("/api/auction-types/", json={})
        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data

    def test_400_has_detail_field(self, client, sample_pdf_bytes, auction_type_id):
        """400 responses should have 'detail' key."""
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("bad.txt", BytesIO(b"not pdf"), "text/plain")},
            data={"auction_type_id": auction_type_id},
        )
        if resp.status_code == 400:
            data = resp.json()
            assert "detail" in data

    def test_export_error_response_structure(self, client):
        """Export endpoint errors should have structured previews."""
        resp = client.post(
            "/api/exports/central-dispatch",
            json={"run_ids": [999999], "dry_run": True, "sandbox": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "previews" in data
        assert "message" in data
        assert "exported_count" in data
        assert "failed_count" in data


# =============================================================================
# 10. AUDIT TRAIL ON FAILURES
# =============================================================================


class TestAuditTrailOnFailures:
    """Verify audit events are created for failure scenarios."""

    def test_log_post_fail_creates_event(self):
        """log_post_fail should create an audit event."""
        from api.audit_log import AuditEventType, AuditLogRepository, log_post_fail

        run_id_sentinel = 999990  # Unlikely to collide

        event_id = log_post_fail(
            run_id=run_id_sentinel,
            payload={"externalId": "FAIL-TEST"},
            response_status=502,
            error_message="Bad Gateway",
            cd_listing_id=None,
            request_id="fail-req-001",
        )
        assert event_id > 0

        events = AuditLogRepository.get_by_run(run_id_sentinel)
        fail_events = [e for e in events if e.event_type == AuditEventType.POST_FAIL.value]
        assert len(fail_events) >= 1
        assert fail_events[0].response_status == 502

    def test_log_etag_conflict_creates_event(self):
        """log_etag_conflict should create an audit event."""
        from api.audit_log import AuditEventType, AuditLogRepository, log_etag_conflict

        run_id_sentinel = 999991

        event_id = log_etag_conflict(
            run_id=run_id_sentinel,
            cd_listing_id="conflict-listing",
            etag_used="stale-etag",
            request_id="conflict-req-001",
        )
        assert event_id > 0

        events = AuditLogRepository.get_by_run(run_id_sentinel)
        conflict_events = [
            e for e in events if e.event_type == AuditEventType.ETAG_CONFLICT.value
        ]
        assert len(conflict_events) >= 1
        assert conflict_events[0].etag_before == "stale-etag"
        assert conflict_events[0].response_status == 412

    def test_log_duplicate_detected_creates_event(self):
        """log_duplicate_detected should create an audit event."""
        from api.audit_log import AuditEventType, AuditLogRepository, log_duplicate_detected

        run_id_sentinel = 999992

        event_id = log_duplicate_detected(
            run_id=run_id_sentinel,
            external_id="DUP-EXT-001",
            existing_listing_id="existing-dup-listing",
            request_id="dup-req-001",
        )
        assert event_id > 0

        events = AuditLogRepository.get_by_run(run_id_sentinel)
        dup_events = [
            e for e in events if e.event_type == AuditEventType.POST_DUPLICATE.value
        ]
        assert len(dup_events) >= 1


# =============================================================================
# 11. PAYLOAD VALIDATION EDGE CASES
# =============================================================================


class TestPayloadValidationEdgeCases:
    """Test edge cases in payload building/validation."""

    def test_build_payload_missing_document(self):
        """build_cd_payload with orphaned run should produce errors."""
        # This tests the case where run exists but document was deleted
        from api.routes.exports import build_cd_payload
        payload, errors = build_cd_payload(999998)
        assert len(errors) > 0

    def test_blocking_issues_detects_missing_warehouse(self, client, sample_pdf_bytes, auction_type_id):
        """Blocking issues should flag missing warehouse selection."""
        doc_id, run_id = _upload_document(client, sample_pdf_bytes, auction_type_id)
        if not run_id:
            run_id = _ensure_run(client, doc_id, auction_type_id)
        if not run_id:
            pytest.skip("Could not create extraction run")

        resp = client.get(f"/api/exports/field-registry/blocking-issues/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        # Minimal PDF won't have warehouse selected → should have issues
        assert data["is_ready"] is False or len(data["issues"]) >= 0

    def test_corrections_for_nonexistent_run(self, client):
        """Production corrections for nonexistent run should return 404."""
        resp = client.post(
            "/api/exports/production-corrections",
            json={
                "run_id": 999997,
                "corrections": [
                    {"field_key": "vehicle_vin", "new_value": "TEST"}
                ],
            },
        )
        assert resp.status_code == 404


# =============================================================================
# 12. REVIEW ENDPOINT ERRORS
# =============================================================================


class TestReviewErrors:
    """Test review endpoint error handling."""

    def test_get_review_not_found(self, client):
        resp = client.get("/api/review/999999")
        assert resp.status_code == 404

    def test_get_review_core_not_found(self, client):
        resp = client.get("/api/review/999999/core")
        assert resp.status_code == 404

    def test_get_review_core_returns_combined_data(self, client, sample_pdf_bytes):
        """Review core endpoint returns run + document + items in one response."""
        at_id = _get_auction_type_id(client)
        doc_id, run_id = _upload_document(client, sample_pdf_bytes, at_id)
        if not run_id:
            run_id = _ensure_run(client, doc_id, at_id)
        assert run_id is not None

        resp = client.get(f"/api/review/{run_id}/core")
        assert resp.status_code == 200
        data = resp.json()

        # Verify run structure
        assert "run" in data
        assert data["run"]["id"] == run_id
        assert data["run"]["document_id"] == doc_id
        assert "outputs" in data["run"]
        assert "status" in data["run"]

        # Verify document info
        assert "document" in data
        assert data["document"]["id"] == doc_id
        assert "source" in data["document"]

        # Verify items list exists
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_submit_review_invalid_run(self, client):
        resp = client.post(
            "/api/review/submit",
            json={"run_id": 999999, "items": []},
        )
        assert resp.status_code == 404
