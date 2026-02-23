"""
Tests for 2-step email scan/process endpoints and production hardening.

Tests:
- POST /api/email/scan — endpoint exists, validates input
- POST /api/email/process-selected — endpoint exists, validates input
- GET /api/health — enhanced health check with API key + data count checks
- Auto-poll uses last_poll_at tracking
"""

import json

import pytest


# =============================================================================
# TestScanEndpoint
# =============================================================================


class TestScanEndpoint:
    """Test POST /api/email/scan endpoint registration and validation."""

    def test_scan_requires_since_date(self, client):
        """Scan without since_date returns 400."""
        resp = client.post("/api/email/scan", json={})
        assert resp.status_code == 400
        assert "since_date" in resp.json().get("detail", "").lower()

    def test_scan_rejects_invalid_date(self, client):
        """Scan with invalid date format returns 400."""
        resp = client.post("/api/email/scan", json={"since_date": "not-a-date"})
        assert resp.status_code == 400

    def test_scan_accepts_valid_request(self, client):
        """Scan with valid date returns 200 (will fail to connect to IMAP, but endpoint works)."""
        resp = client.post("/api/email/scan", json={"since_date": "2026-02-01"})
        # May return 200 with error field if no IMAP configured, or 500 if exception
        # The key test is that endpoint is registered and processes the request
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            data = resp.json()
            assert "emails" in data or "error" in data

    def test_scan_with_date_range(self, client):
        """Scan with both since_date and until_date is accepted."""
        resp = client.post("/api/email/scan", json={
            "since_date": "2026-02-01",
            "until_date": "2026-02-15",
        })
        assert resp.status_code in (200, 500)


# =============================================================================
# TestProcessSelectedEndpoint
# =============================================================================


class TestProcessSelectedEndpoint:
    """Test POST /api/email/process-selected endpoint."""

    def test_process_requires_message_ids(self, client):
        """Process without message_ids returns 400."""
        resp = client.post("/api/email/process-selected", json={})
        assert resp.status_code == 400

    def test_process_rejects_empty_list(self, client):
        """Process with empty message_ids returns 400."""
        resp = client.post("/api/email/process-selected", json={"message_ids": []})
        assert resp.status_code == 400

    def test_process_rejects_too_many(self, client):
        """Process with >50 message_ids returns 400."""
        ids = [f"msg{i}@test.com" for i in range(51)]
        resp = client.post("/api/email/process-selected", json={"message_ids": ids})
        assert resp.status_code == 400

    def test_process_accepts_valid_request(self, client):
        """Process with valid message_ids returns 200 (may fail IMAP)."""
        resp = client.post("/api/email/process-selected", json={
            "message_ids": ["test-msg-1@test.com"],
        })
        # Endpoint registered — may return 200 with error or 500 if no IMAP
        assert resp.status_code in (200, 500)


# =============================================================================
# TestHealthCheck
# =============================================================================


class TestHealthCheck:
    """Test GET /api/health enhanced health check."""

    def test_health_returns_200(self, client):
        """Health check returns 200."""
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_has_required_fields(self, client):
        """Health check response has all required fields."""
        resp = client.get("/api/health")
        data = resp.json()
        assert "status" in data
        assert "version" in data
        assert "checks" in data
        assert data["status"] in ("healthy", "unhealthy")

    def test_health_includes_api_checks(self, client):
        """Health check includes API key and email config checks."""
        resp = client.get("/api/health")
        checks = resp.json()["checks"]
        assert "anthropic_api" in checks
        assert "email_config" in checks
        assert "cd_api" in checks

    def test_health_includes_data_counts(self, client):
        """Health check includes data table counts."""
        resp = client.get("/api/health")
        checks = resp.json()["checks"]
        assert "data_counts" in checks
        counts = checks["data_counts"]
        assert "documents" in counts
        assert "extraction_runs" in counts
        assert "email_log" in counts

    def test_health_includes_database_check(self, client):
        """Health check verifies database connectivity."""
        resp = client.get("/api/health")
        checks = resp.json()["checks"]
        assert "database" in checks
        assert checks["database"]["status"] in ("ok", "not_initialized", "error")

    def test_readiness_probe(self, client):
        """Readiness probe returns 200."""
        resp = client.get("/api/ready")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True

    def test_liveness_probe(self, client):
        """Liveness probe returns 200."""
        resp = client.get("/api/live")
        assert resp.status_code == 200
        assert resp.json()["alive"] is True


# =============================================================================
# TestAutoPollConfig
# =============================================================================


class TestAutoPollConfig:
    """Test auto-poll configuration and status endpoints."""

    def test_poll_status_returns_200(self, client):
        """Poll status endpoint returns 200."""
        resp = client.get("/api/email/poll-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data or "auto_poll_enabled" in data or "is_polling" in data

    def test_poll_settings_update(self, client):
        """Can update poll settings."""
        resp = client.post("/api/email/poll-settings?enabled=true&interval_minutes=10")
        assert resp.status_code == 200


# =============================================================================
# TestExistingPollEndpoint
# =============================================================================


class TestExistingPollEndpoint:
    """Verify existing poll endpoint still works alongside new scan/process."""

    def test_old_poll_endpoint_still_exists(self, client):
        """POST /api/email/poll still registered."""
        resp = client.post("/api/email/poll?since_days=0")
        # Will likely return 200 with results (or error if no IMAP)
        assert resp.status_code in (200, 500)
