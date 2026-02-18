"""
Tests for CD API OAuth2 Client Credentials Flow.

Covers:
- OAuth2 token acquisition via client_credentials grant
- Token caching (reuse unexpired tokens)
- Token auto-refresh when expired
- CDClient integration with OAuth2
- Credential config structure
- Settings model with OAuth2 fields
- Test connection endpoints using OAuth2
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Test: OAuth2 Token Acquisition
# =============================================================================


class TestOAuth2TokenAcquisition:
    """Test OAuth2 client_credentials flow in CDClient."""

    def test_acquire_token_sends_correct_request(self):
        """Token request POSTs client_id + client_secret with grant_type=client_credentials."""
        from api.cd_client import CDClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test-bearer-token-123",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        with patch("api.cd_client.requests.post", return_value=mock_response) as mock_post:
            client = CDClient(
                client_id="test-client-id",
                client_secret="test-client-secret",
                token_url="https://id.centraldispatch.com/connect/token",
            )
            token = client._acquire_token()

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert call_kwargs[1]["data"]["grant_type"] == "client_credentials"
            assert call_kwargs[1]["data"]["client_id"] == "test-client-id"
            assert call_kwargs[1]["data"]["client_secret"] == "test-client-secret"
            assert token == "test-bearer-token-123"

    def test_acquire_token_with_scopes(self):
        """Token request includes scope parameter when provided."""
        from api.cd_client import CDClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "scoped-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        with patch("api.cd_client.requests.post", return_value=mock_response) as mock_post:
            client = CDClient(
                client_id="cid",
                client_secret="csec",
                token_url="https://id.centraldispatch.com/connect/token",
                scopes="marketplace dispatchdocument_api",
            )
            client._acquire_token()

            call_data = mock_post.call_args[1]["data"]
            assert call_data["scope"] == "marketplace dispatchdocument_api"

    def test_acquire_token_failure_raises(self):
        """Token acquisition failure raises an error."""
        from api.cd_client import CDClient

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "invalid_client"

        with patch("api.cd_client.requests.post", return_value=mock_response):
            client = CDClient(
                client_id="bad-id",
                client_secret="bad-secret",
                token_url="https://id.centraldispatch.com/connect/token",
            )
            with pytest.raises(Exception, match="OAuth2 token acquisition failed"):
                client._acquire_token()


# =============================================================================
# Test: Token Caching
# =============================================================================


class TestTokenCaching:
    """Test that tokens are cached and reused until expiry."""

    def test_token_reused_when_not_expired(self):
        """Second call to get_token reuses cached token without HTTP call."""
        from api.cd_client import CDClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "cached-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        with patch("api.cd_client.requests.post", return_value=mock_response) as mock_post:
            client = CDClient(
                client_id="cid",
                client_secret="csec",
                token_url="https://id.centraldispatch.com/connect/token",
            )
            token1 = client._get_bearer_token()
            token2 = client._get_bearer_token()

            assert token1 == token2 == "cached-token"
            # Only one HTTP call — token was reused
            assert mock_post.call_count == 1

    def test_token_refreshed_when_expired(self):
        """Expired token triggers re-acquisition."""
        from api.cd_client import CDClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        with patch("api.cd_client.requests.post", return_value=mock_response) as mock_post:
            client = CDClient(
                client_id="cid",
                client_secret="csec",
                token_url="https://id.centraldispatch.com/connect/token",
            )
            # First acquisition
            client._get_bearer_token()

            # Simulate expired token (set expiry to the past)
            client._token_expires_at = time.time() - 10

            # Should trigger new acquisition
            client._get_bearer_token()
            assert mock_post.call_count == 2

    def test_token_refreshed_with_safety_margin(self):
        """Token acquired with safety margin: expires_at = now + expires_in - 60."""
        from api.cd_client import CDClient, TOKEN_REFRESH_MARGIN

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "refreshed",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        with patch("api.cd_client.requests.post", return_value=mock_response):
            client = CDClient(
                client_id="cid",
                client_secret="csec",
                token_url="https://id.centraldispatch.com/connect/token",
            )
            before = time.time()
            client._acquire_token()
            after = time.time()

            # Expiry should be set with safety margin (3600 - 60 = 3540s)
            expected_min = before + 3600 - TOKEN_REFRESH_MARGIN
            expected_max = after + 3600 - TOKEN_REFRESH_MARGIN
            assert expected_min <= client._token_expires_at <= expected_max


# =============================================================================
# Test: CDClient Headers with OAuth2
# =============================================================================


class TestCDClientOAuth2Headers:
    """Test that CDClient uses OAuth2 Bearer token in headers."""

    def test_headers_contain_bearer_token(self):
        """Authorization header uses Bearer token from OAuth2."""
        from api.cd_client import CDClient

        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "oauth-bearer-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        with patch("api.cd_client.requests.post", return_value=token_response):
            client = CDClient(
                client_id="cid",
                client_secret="csec",
                token_url="https://id.centraldispatch.com/connect/token",
            )
            headers = client._get_headers()
            assert headers["Authorization"] == "Bearer oauth-bearer-token"

    def test_create_listing_uses_oauth_token(self):
        """create_listing uses OAuth2 Bearer token, not static API key."""
        from api.cd_client import CDClient

        # Mock token acquisition
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "listing-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        # Mock listing creation
        listing_response = MagicMock()
        listing_response.status_code = 201
        listing_response.json.return_value = {"id": "L123", "etag": "abc"}
        listing_response.headers = {"ETag": "abc"}

        with patch("api.cd_client.requests.post") as mock_post:
            # First call = token, second call = listing
            mock_post.side_effect = [token_response, listing_response]

            client = CDClient(
                client_id="cid",
                client_secret="csec",
                token_url="https://id.centraldispatch.com/connect/token",
                base_url="https://api.centraldispatch.com/v2",
            )
            result = client.create_listing({"partnerReferenceId": "test"})

            assert result.success
            # Second call (listing) should have Bearer token
            listing_call = mock_post.call_args_list[1]
            assert "Bearer listing-token" in listing_call[1]["headers"]["Authorization"]


# =============================================================================
# Test: CDSettings Model
# =============================================================================


class TestCDSettingsOAuth2:
    """Test CDSettings model includes OAuth2 fields."""

    def test_settings_model_has_oauth_fields(self):
        """CDSettings model has client_id, client_secret, marketplace_id, scopes."""
        from api.routes.settings import CDSettings

        settings = CDSettings(
            client_id="my-client-id",
            client_secret="my-secret",
            marketplace_id="12345",
            scopes="marketplace",
            environment="test",
            shipper_username="testshipper",
        )
        assert settings.client_id == "my-client-id"
        assert settings.client_secret == "my-secret"
        assert settings.marketplace_id == "12345"
        assert settings.scopes == "marketplace"
        assert settings.environment == "test"
        assert settings.shipper_username == "testshipper"

    def test_settings_model_no_username_password(self):
        """CDSettings model does NOT have username/password fields."""
        from api.routes.settings import CDSettings

        settings = CDSettings()
        assert not hasattr(settings, "username")
        assert not hasattr(settings, "password")


# =============================================================================
# Test: Credential Test Endpoint
# =============================================================================


class TestCDCredentialTest:
    """Test _test_cd_api uses OAuth2 flow."""

    @pytest.mark.asyncio
    async def test_cd_api_test_uses_oauth2(self):
        """_test_cd_api acquires OAuth2 token and tests API call."""
        from api.routes.credentials import _test_cd_api

        config = {
            "client_id": "test-cid",
            "client_secret": "test-csec",
            "marketplace_id": "10000",
            "environment": "test",
            "scopes": "marketplace",
        }

        # Mock httpx for both token and API call
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {
            "access_token": "test-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        mock_api_resp = MagicMock()
        mock_api_resp.status_code = 200
        mock_api_resp.json.return_value = {"status": "ok"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_api_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        import httpx as httpx_mod
        with patch.object(httpx_mod, "AsyncClient", return_value=mock_client):
            result = await _test_cd_api(config)

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_cd_api_test_missing_client_id(self):
        """_test_cd_api fails when client_id is missing."""
        from api.routes.credentials import _test_cd_api

        config = {"client_secret": "sec", "marketplace_id": "10000"}
        result = await _test_cd_api(config)
        assert result["status"] == "failed"
        assert "client_id" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_cd_api_test_missing_client_secret(self):
        """_test_cd_api fails when client_secret is missing."""
        from api.routes.credentials import _test_cd_api

        config = {"client_id": "cid", "marketplace_id": "10000"}
        result = await _test_cd_api(config)
        assert result["status"] == "failed"
        assert "client_secret" in result["message"].lower()


# =============================================================================
# Test: Integration Test Connection
# =============================================================================


class TestCDIntegrationTest:
    """Test CD integration test connection uses OAuth2."""

    @pytest.mark.asyncio
    async def test_connection_uses_oauth2_token(self):
        """test_cd_connection uses OAuth2 Bearer token, not Basic Auth."""
        import httpx as httpx_mod

        # Mock settings to return OAuth2 config
        mock_settings = {
            "cd": {
                "client_id": "int-cid",
                "client_secret": "int-csec",
                "marketplace_id": "10000",
                "environment": "test",
                "scopes": "marketplace",
            }
        }

        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {
            "access_token": "int-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        mock_api_resp = MagicMock()
        mock_api_resp.status_code = 200
        mock_api_resp.json.return_value = {"username": "testuser"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_api_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("api.routes.settings.load_settings", return_value=mock_settings), \
             patch.object(httpx_mod, "AsyncClient", return_value=mock_client):
            from api.routes.integrations.cd import test_cd_connection

            result = await test_cd_connection()

        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_connection_fails_without_client_id(self):
        """test_cd_connection fails when client_id not configured."""
        mock_settings = {"cd": {"client_secret": "sec"}}

        with patch("api.routes.settings.load_settings", return_value=mock_settings):
            from api.routes.integrations.cd import test_cd_connection

            result = await test_cd_connection()

        assert result.status == "error"


# =============================================================================
# Test: Environment URL Resolution
# =============================================================================


class TestEnvironmentURLs:
    """Test that all environments use the same URLs (test vs prod differs by marketplace_id only)."""

    def test_test_environment_urls(self):
        """'test' environment uses the single CD API + token URL."""
        from api.cd_client import get_cd_urls

        urls = get_cd_urls("test")
        assert urls["api_base_url"] == "https://marketplace-api.centraldispatch.com"
        assert urls["token_url"] == "https://id.centraldispatch.com/connect/token"

    def test_production_environment_urls(self):
        """'production' environment uses the same URLs as test."""
        from api.cd_client import get_cd_urls

        urls = get_cd_urls("production")
        assert urls["api_base_url"] == "https://marketplace-api.centraldispatch.com"
        assert urls["token_url"] == "https://id.centraldispatch.com/connect/token"

    def test_default_environment_is_same(self):
        """Default/empty environment uses the same URLs."""
        from api.cd_client import get_cd_urls

        urls = get_cd_urls("")
        assert urls["api_base_url"] == "https://marketplace-api.centraldispatch.com"
        assert urls["token_url"] == "https://id.centraldispatch.com/connect/token"
