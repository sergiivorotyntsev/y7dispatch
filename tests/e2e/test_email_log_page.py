"""
Tests for Email Log API endpoints used by the Email Log page.
"""

import json

import pytest


class TestEmailLogEndpoints:
    """Test email log API endpoints."""

    def test_get_email_log_returns_200(self, client):
        """GET /api/email-log should return 200 with items and total."""
        resp = client.get("/api/email-log/")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_get_email_log_with_status_filter(self, client):
        """GET /api/email-log/?status=processed should filter by status."""
        resp = client.get("/api/email-log/?status=processed")
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["status"] == "processed"

    def test_get_email_log_with_sender_filter(self, client):
        """GET /api/email-log/?sender=test should filter by sender substring."""
        resp = client.get("/api/email-log/?sender=nonexistent_sender_xyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_get_email_log_pagination(self, client):
        """GET /api/email-log/?limit=5&offset=0 should respect pagination."""
        resp = client.get("/api/email-log/?limit=5&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 5

    def test_stats_returns_counts(self, client):
        """GET /api/email-log/stats should return status counts."""
        resp = client.get("/api/email-log/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "processed" in data
        assert "skipped" in data
        assert "failed" in data
        assert "ready" in data
        assert isinstance(data["total"], int)

    def test_process_nonexistent_returns_404(self, client):
        """POST /api/email-log/999999/process should return 404."""
        resp = client.post("/api/email-log/999999/process")
        assert resp.status_code == 404

    def test_skip_nonexistent_returns_404(self, client):
        """POST /api/email-log/999999/skip should return 404."""
        resp = client.post("/api/email-log/999999/skip")
        assert resp.status_code == 404

    def test_reprocess_nonexistent_returns_404(self, client):
        """POST /api/email-log/999999/reprocess should return 404."""
        resp = client.post("/api/email-log/999999/reprocess")
        assert resp.status_code == 404

    def test_email_log_item_has_expected_fields(self, client):
        """Email log items should have expected fields."""
        resp = client.get("/api/email-log/?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        if data["items"]:
            item = data["items"][0]
            # Core fields that should exist
            assert "id" in item
            assert "status" in item
            assert "sender" in item


class TestDocumentsLoadId:
    """Test load_id in Documents API enriched response."""

    def test_documents_response_has_load_id_field(self, client):
        """Document list response should include load_id field."""
        resp = client.get("/api/documents/?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        if data["items"]:
            item = data["items"][0]
            # load_id field should exist (may be null if not yet generated)
            assert "load_id" in item
