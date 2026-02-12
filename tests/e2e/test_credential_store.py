"""
E2E Tests for Credential Store — encrypted credential management.

Covers:
- DB table creation and CRUD operations
- Fernet encryption/decryption round-trip
- Secret masking in API responses
- Credential wiring into services (HaikuExtractor)
- REST API endpoints via TestClient

All tests use SQLite in-memory or temp DB. No real API calls.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from api.main import app

    return TestClient(app)


# =============================================================================
# 1. CREDENTIAL STORE UNIT TESTS
# =============================================================================


class TestCredentialStoreCRUD:
    """Test credential_store save/get/delete/list operations."""

    def test_save_and_get_credential(self):
        """Save a credential and retrieve it (masked)."""
        from services.credential_store import (
            delete_credential,
            get_credential,
            save_credential,
        )

        save_credential("anthropic", {"api_key": "sk-ant-test123456"}, enabled=True)
        cred = get_credential("anthropic")

        assert cred is not None
        assert cred["service"] == "anthropic"
        assert cred["enabled"] is True
        # Secret should be masked
        assert "sk-a" in cred["config"]["api_key"]
        assert "●" in cred["config"]["api_key"] or "****" in cred["config"]["api_key"]

        # Cleanup
        delete_credential("anthropic")

    def test_get_credential_raw(self):
        """Raw get should return decrypted secrets."""
        from services.credential_store import (
            delete_credential,
            get_credential_raw,
            save_credential,
        )

        save_credential("anthropic", {"api_key": "sk-ant-rawtest789"}, enabled=True)
        raw = get_credential_raw("anthropic")

        assert raw is not None
        assert raw["config"]["api_key"] == "sk-ant-rawtest789"

        delete_credential("anthropic")

    def test_delete_credential(self):
        """Delete should remove the credential."""
        from services.credential_store import (
            delete_credential,
            get_credential,
            save_credential,
        )

        save_credential("anthropic", {"api_key": "delete-me"})
        assert get_credential("anthropic") is not None

        deleted = delete_credential("anthropic")
        assert deleted is True
        assert get_credential("anthropic") is None

        # Deleting again should return False
        deleted2 = delete_credential("anthropic")
        assert deleted2 is False

    def test_list_credentials(self):
        """List should return all stored credentials with masked secrets."""
        from services.credential_store import (
            delete_credential,
            list_credentials,
            save_credential,
        )

        save_credential("anthropic", {"api_key": "sk-ant-list1"}, enabled=True)
        save_credential("cd_api", {"username": "user1", "password": "pass12345678"}, enabled=False)

        creds = list_credentials()
        services = [c["service"] for c in creds]

        assert "anthropic" in services
        assert "cd_api" in services

        cd_cred = next(c for c in creds if c["service"] == "cd_api")
        # Password should be masked
        assert "●" in cd_cred["config"]["password"] or "****" in cd_cred["config"]["password"]

        # Cleanup
        delete_credential("anthropic")
        delete_credential("cd_api")

    def test_update_test_status(self):
        """update_test_status should set last_tested_at and status."""
        from services.credential_store import (
            delete_credential,
            get_credential,
            save_credential,
            update_test_status,
        )

        save_credential("anthropic", {"api_key": "test-status"})
        update_test_status("anthropic", "ok")

        cred = get_credential("anthropic")
        assert cred["last_test_status"] == "ok"
        assert cred["last_tested_at"] is not None

        delete_credential("anthropic")

    def test_invalid_service_rejected(self):
        """Saving to an invalid service should raise ValueError."""
        from services.credential_store import save_credential

        with pytest.raises(ValueError, match="Invalid service"):
            save_credential("invalid_svc", {"key": "val"})

    def test_get_credential_for_service(self):
        """get_credential_for_service returns config dict when enabled."""
        from services.credential_store import (
            delete_credential,
            get_credential_for_service,
            save_credential,
        )

        # Not found
        assert get_credential_for_service("anthropic") is None

        # Saved but disabled
        save_credential("anthropic", {"api_key": "test-key"}, enabled=False)
        assert get_credential_for_service("anthropic") is None

        # Enabled
        save_credential("anthropic", {"api_key": "test-key"}, enabled=True)
        config = get_credential_for_service("anthropic")
        assert config is not None
        assert config["api_key"] == "test-key"

        delete_credential("anthropic")

    def test_save_overwrites_existing(self):
        """Saving to same service should update, not duplicate."""
        from services.credential_store import (
            delete_credential,
            get_credential_raw,
            list_credentials,
            save_credential,
        )

        save_credential("anthropic", {"api_key": "version1"})
        save_credential("anthropic", {"api_key": "version2"})

        raw = get_credential_raw("anthropic")
        assert raw["config"]["api_key"] == "version2"

        # Should only have one entry for anthropic
        creds = list_credentials()
        anthropic_count = sum(1 for c in creds if c["service"] == "anthropic")
        assert anthropic_count == 1

        delete_credential("anthropic")


# =============================================================================
# 2. REST API TESTS
# =============================================================================


class TestCredentialAPI:
    """Test credential API endpoints via TestClient."""

    def test_credential_api_save(self, client):
        """PUT /api/credentials/{service} should save credential."""
        resp = client.put(
            "/api/credentials/anthropic",
            json={"config": {"api_key": "sk-ant-apitest123"}, "enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Cleanup
        client.delete("/api/credentials/anthropic")

    def test_credential_api_list(self, client):
        """GET /api/credentials/ should return masked list."""
        # Save one first
        client.put(
            "/api/credentials/anthropic",
            json={"config": {"api_key": "sk-ant-listtest1234"}, "enabled": True},
        )

        resp = client.get("/api/credentials/")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

        # Find anthropic
        anthro = next((c for c in data if c["service"] == "anthropic"), None)
        assert anthro is not None
        # Key should be masked
        assert anthro["config"]["api_key"] != "sk-ant-listtest1234"

        client.delete("/api/credentials/anthropic")

    def test_credential_api_get_single(self, client):
        """GET /api/credentials/{service} should return masked credential."""
        client.put(
            "/api/credentials/cd_api",
            json={"config": {"username": "cduser", "password": "cdpass12345"}, "enabled": False},
        )

        resp = client.get("/api/credentials/cd_api")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "cd_api"
        assert data["config"]["username"] == "cduser"
        # Password masked
        assert data["config"]["password"] != "cdpass12345"

        client.delete("/api/credentials/cd_api")

    def test_credential_api_delete(self, client):
        """DELETE /api/credentials/{service} should remove credential."""
        client.put(
            "/api/credentials/anthropic",
            json={"config": {"api_key": "delete-me"}, "enabled": True},
        )

        resp = client.delete("/api/credentials/anthropic")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Should 404 now
        resp2 = client.get("/api/credentials/anthropic")
        assert resp2.status_code == 404

    def test_masked_secrets_in_response(self, client):
        """API should never return raw secrets."""
        client.put(
            "/api/credentials/anthropic",
            json={"config": {"api_key": "sk-ant-supersecret12345678"}, "enabled": True},
        )

        # Single get
        resp = client.get("/api/credentials/anthropic")
        assert "supersecret" not in resp.text

        # List
        resp = client.get("/api/credentials/")
        assert "supersecret" not in resp.text

        client.delete("/api/credentials/anthropic")

    def test_invalid_service_rejected(self, client):
        """PUT to invalid service should return 400."""
        resp = client.put(
            "/api/credentials/invalid_svc",
            json={"config": {"key": "val"}, "enabled": True},
        )
        assert resp.status_code == 400

    def test_credential_update_preserves_masked(self, client):
        """Re-saving with masked values should preserve original secrets."""
        # Save original
        client.put(
            "/api/credentials/anthropic",
            json={"config": {"api_key": "sk-ant-original123456"}, "enabled": True},
        )

        # Get masked value
        resp = client.get("/api/credentials/anthropic")
        masked_key = resp.json()["config"]["api_key"]

        # Re-save with masked value (simulating UI re-submit)
        client.put(
            "/api/credentials/anthropic",
            json={"config": {"api_key": masked_key}, "enabled": True},
        )

        # Raw should still have original
        from services.credential_store import get_credential_raw

        raw = get_credential_raw("anthropic")
        assert raw["config"]["api_key"] == "sk-ant-original123456"

        client.delete("/api/credentials/anthropic")


# =============================================================================
# 3. SERVICE WIRING TESTS
# =============================================================================


class TestServiceWiring:
    """Test that services read from credential_store."""

    def test_anthropic_credential_wiring(self):
        """HaikuExtractor should read api_key from credential_store."""
        from services.credential_store import delete_credential, save_credential

        # Save credential
        save_credential("anthropic", {"api_key": "sk-ant-fromdb"}, enabled=True)

        try:
            # Clear env var to force DB lookup
            with patch.dict(os.environ, {}, clear=True):
                from services.haiku_extractor import HaikuExtractor

                extractor = HaikuExtractor(api_key=None)
                assert extractor.api_key == "sk-ant-fromdb"
        finally:
            delete_credential("anthropic")

    def test_anthropic_env_fallback(self):
        """HaikuExtractor should fall back to env var when credential_store empty."""
        from services.credential_store import delete_credential

        # Ensure no credential stored
        delete_credential("anthropic")

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-fromenv"}):
            from services.haiku_extractor import HaikuExtractor

            extractor = HaikuExtractor(api_key=None)
            assert extractor.api_key == "sk-ant-fromenv"
