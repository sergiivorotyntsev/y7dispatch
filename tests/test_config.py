"""Tests for configuration module."""

import os
from unittest.mock import patch

import pytest

from core.config import (
    AppConfig,
    CentralDispatchConfig,
    ClickUpConfig,
    ConfigurationError,
    EmailConfig,
    _mask_secret,
    load_config_from_env,
)


class TestMaskSecret:
    """Tests for secret masking utility."""

    def test_mask_normal_secret(self):
        """Test masking of normal length secret."""
        result = _mask_secret("abcdefghij")
        assert result == "abcd******"

    def test_mask_short_secret(self):
        """Test masking of short secret."""
        result = _mask_secret("abc")
        assert result == "***"

    def test_mask_empty_secret(self):
        """Test masking of empty secret."""
        result = _mask_secret("")
        assert result == "<empty>"

    def test_mask_custom_visible_chars(self):
        """Test masking with custom visible chars."""
        result = _mask_secret("abcdefghij", visible_chars=2)
        assert result == "ab********"


class TestEmailConfig:
    """Tests for EmailConfig validation."""

    def test_valid_imap_config(self):
        """Test validation of valid IMAP config."""
        config = EmailConfig(
            provider="imap",
            imap_server="imap.gmail.com",
            address="test@example.com",
            password="secret123",
        )
        errors = config.validate()
        assert len(errors) == 0

    def test_invalid_imap_missing_server(self):
        """Test validation fails without server."""
        config = EmailConfig(
            provider="imap",
            address="test@example.com",
            password="secret123",
        )
        errors = config.validate()
        assert any("IMAP_SERVER" in e for e in errors)

    def test_invalid_imap_missing_address(self):
        """Test validation fails without address."""
        config = EmailConfig(
            provider="imap",
            imap_server="imap.gmail.com",
            password="secret123",
        )
        errors = config.validate()
        assert any("ADDRESS" in e for e in errors)

    def test_valid_graph_config(self):
        """Test validation of valid Graph config."""
        config = EmailConfig(
            provider="graph",
            address="test@example.com",
            tenant_id="tenant123",
            client_id="client123",
            client_secret="secret123",
        )
        errors = config.validate()
        assert len(errors) == 0

    def test_invalid_graph_missing_tenant(self):
        """Test validation fails without tenant ID."""
        config = EmailConfig(
            provider="graph",
            address="test@example.com",
            client_id="client123",
            client_secret="secret123",
        )
        errors = config.validate()
        assert any("TENANT_ID" in e for e in errors)


class TestClickUpConfig:
    """Tests for ClickUpConfig validation."""

    def test_valid_config(self):
        """Test validation of valid ClickUp config."""
        config = ClickUpConfig(
            token="pk_12345",
            list_id="901234567",
        )
        errors = config.validate()
        assert len(errors) == 0

    def test_invalid_missing_token(self):
        """Test validation fails without token."""
        config = ClickUpConfig(list_id="901234567")
        errors = config.validate()
        assert any("TOKEN" in e for e in errors)

    def test_invalid_missing_list_id(self):
        """Test validation fails without list ID."""
        config = ClickUpConfig(token="pk_12345")
        errors = config.validate()
        assert any("LIST_ID" in e for e in errors)


class TestCentralDispatchConfig:
    """Tests for CentralDispatchConfig validation."""

    def test_disabled_config_valid(self):
        """Test that disabled CD config is always valid."""
        config = CentralDispatchConfig(enabled=False)
        errors = config.validate()
        assert len(errors) == 0

    def test_enabled_config_valid(self):
        """Test validation of valid enabled CD config."""
        config = CentralDispatchConfig(
            enabled=True,
            client_id="client123",
            client_secret="secret123",
        )
        errors = config.validate()
        assert len(errors) == 0

    def test_enabled_missing_credentials(self):
        """Test validation fails when enabled without credentials."""
        config = CentralDispatchConfig(enabled=True)
        errors = config.validate()
        assert any("CLIENT_ID" in e for e in errors)
        assert any("CLIENT_SECRET" in e for e in errors)


class TestAppConfig:
    """Tests for AppConfig validation."""

    def test_validate_full_config(self):
        """Test full configuration validation."""
        config = AppConfig(
            email=EmailConfig(
                provider="imap",
                imap_server="imap.gmail.com",
                address="test@example.com",
                password="secret",
            ),
            clickup=ClickUpConfig(
                token="pk_token",
                list_id="123456",
            ),
        )
        # Should not raise
        config.validate()

    def test_validate_raises_on_error(self):
        """Test that validate raises ConfigurationError on errors."""
        config = AppConfig()  # Empty config
        with pytest.raises(ConfigurationError):
            config.validate()

    def test_validate_skip_email(self):
        """Test validation can skip email check."""
        config = AppConfig(
            clickup=ClickUpConfig(
                token="pk_token",
                list_id="123456",
            ),
        )
        # Should not raise when email not required
        config.validate(require_email=False)

    def test_validate_skip_clickup(self):
        """Test validation can skip ClickUp check."""
        config = AppConfig(
            email=EmailConfig(
                provider="imap",
                imap_server="imap.gmail.com",
                address="test@example.com",
                password="secret",
            ),
        )
        # Should not raise when ClickUp not required
        config.validate(require_clickup=False)


class TestLoadConfigFromEnv:
    """Tests for loading config from environment."""

    def test_load_basic_config(self):
        """Test loading basic configuration from env."""
        env_vars = {
            "EMAIL_PROVIDER": "imap",
            "EMAIL_IMAP_SERVER": "imap.test.com",
            "EMAIL_ADDRESS": "test@test.com",
            "EMAIL_PASSWORD": "password123",
            "CLICKUP_TOKEN": "pk_test",
            "CLICKUP_LIST_ID": "123456",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = load_config_from_env()

            assert config.email.provider == "imap"
            assert config.email.imap_server == "imap.test.com"
            assert config.email.address == "test@test.com"
            assert config.clickup.token == "pk_test"
            assert config.clickup.list_id == "123456"

    def test_load_defaults(self):
        """Test that defaults are applied correctly."""
        with patch.dict(os.environ, {}, clear=True):
            config = load_config_from_env()

            assert config.email.provider == "imap"
            assert config.email.imap_port == 993
            assert config.email.folder == "INBOX"
            assert config.email.check_interval == 60
            assert config.central_dispatch.enabled is False
            assert config.dry_run is False
            assert config.log_level == "INFO"

    def test_load_boolean_values(self):
        """Test boolean value parsing."""
        env_vars = {
            "CD_ENABLED": "true",
            "DRY_RUN": "1",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = load_config_from_env()

            assert config.central_dispatch.enabled is True
            assert config.dry_run is True

    def test_load_integer_values(self):
        """Test integer value parsing."""
        env_vars = {
            "EMAIL_IMAP_PORT": "587",
            "EMAIL_CHECK_INTERVAL": "120",
            "CD_MARKETPLACE_ID": "20000",
        }

        with patch.dict(os.environ, env_vars, clear=False):
            config = load_config_from_env()

            assert config.email.imap_port == 587
            assert config.email.check_interval == 120
            assert config.central_dispatch.marketplace_id == 20000
