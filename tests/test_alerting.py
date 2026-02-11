"""
Alerting Service Tests

Tests send_alert with mock Slack webhook, logging fallback,
and pre-built alert helpers.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from services.alerting import (
    Severity,
    alert_accuracy_drop,
    alert_batch_item_failed,
    alert_daily_cost,
    alert_export_failure,
    send_alert,
)


# =============================================================================
# CORE send_alert TESTS
# =============================================================================


class TestSendAlert:
    """Test core send_alert function."""

    def test_returns_true_without_slack(self):
        """send_alert should succeed even without SLACK_WEBHOOK_URL."""
        with patch.dict("os.environ", {}, clear=False):
            # Ensure SLACK_WEBHOOK_URL is not set
            import os
            os.environ.pop("SLACK_WEBHOOK_URL", None)

            result = send_alert("Test alert", Severity.HIGH)
            assert result is True

    def test_logs_high_severity_as_error(self, caplog):
        """HIGH severity should log at ERROR level."""
        import os
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        with caplog.at_level(logging.ERROR, logger="services.alerting"):
            send_alert("Critical failure", Severity.HIGH)
        assert "Critical failure" in caplog.text

    def test_logs_medium_severity_as_warning(self, caplog):
        """MEDIUM severity should log at WARNING level."""
        import os
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        with caplog.at_level(logging.WARNING, logger="services.alerting"):
            send_alert("Cost threshold", Severity.MEDIUM)
        assert "Cost threshold" in caplog.text

    def test_logs_low_severity_as_info(self, caplog):
        """LOW severity should log at INFO level."""
        import os
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        with caplog.at_level(logging.INFO, logger="services.alerting"):
            send_alert("Informational", Severity.LOW)
        assert "Informational" in caplog.text

    def test_context_included_in_log(self, caplog):
        """Context dict should appear in log output."""
        import os
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        with caplog.at_level(logging.ERROR, logger="services.alerting"):
            send_alert("Test", Severity.HIGH, context={"run_id": 42, "vin": "ABC123"})
        assert "run_id" in caplog.text
        assert "42" in caplog.text

    def test_no_crash_on_none_context(self):
        """send_alert with context=None should not crash."""
        import os
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        result = send_alert("Test", Severity.LOW, context=None)
        assert result is True

    def test_no_crash_on_empty_context(self):
        """send_alert with empty context should not crash."""
        import os
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        result = send_alert("Test", Severity.LOW, context={})
        assert result is True


# =============================================================================
# SLACK WEBHOOK TESTS
# =============================================================================


class TestSlackWebhook:
    """Test Slack webhook integration."""

    @patch("services.alerting._send_slack")
    def test_sends_to_slack_when_configured(self, mock_send_slack):
        """Should call _send_slack when SLACK_WEBHOOK_URL is set."""
        mock_send_slack.return_value = True

        with patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"}):
            result = send_alert("Test message", Severity.HIGH)

        assert result is True
        mock_send_slack.assert_called_once()
        args = mock_send_slack.call_args
        assert args[0][0] == "https://hooks.slack.com/test"
        assert args[0][1] == "Test message"
        assert args[0][2] == Severity.HIGH

    @patch("services.alerting._send_slack")
    def test_slack_failure_returns_false(self, mock_send_slack):
        """Slack webhook failure should return False."""
        mock_send_slack.return_value = False

        with patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/test"}):
            result = send_alert("Test", Severity.HIGH)

        assert result is False

    def test_send_slack_with_mock_httpx(self):
        """_send_slack should POST to webhook URL."""
        from services.alerting import _send_slack

        with patch("httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.post.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            result = _send_slack(
                "https://hooks.slack.com/test",
                "Test message",
                Severity.HIGH,
                context={"run_id": 42},
            )

        assert result is True
        mock_client.post.assert_called_once()
        payload = mock_client.post.call_args[1]["json"]
        assert "HIGH" in payload["text"]
        assert "Test message" in payload["text"]
        assert "run_id" in payload["text"]

    def test_send_slack_exception_returns_false(self):
        """_send_slack with connection error should return False."""
        from services.alerting import _send_slack

        with patch("httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post.side_effect = Exception("Connection refused")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            result = _send_slack("https://hooks.slack.com/test", "Test", Severity.HIGH)

        assert result is False

    def test_send_slack_500_returns_false(self):
        """_send_slack with HTTP 500 should return False."""
        from services.alerting import _send_slack

        with patch("httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_client.post.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            result = _send_slack("https://hooks.slack.com/test", "Test", Severity.HIGH)

        assert result is False


# =============================================================================
# HELPER FUNCTION TESTS
# =============================================================================


class TestAlertHelpers:
    """Test pre-built alert helper functions."""

    def test_alert_export_failure(self, caplog):
        """alert_export_failure should send HIGH severity alert."""
        import os
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        with caplog.at_level(logging.ERROR, logger="services.alerting"):
            result = alert_export_failure(run_id=42, error="CD API 500", vin="YV4A22PMX")
            assert result is True
        assert "export failed" in caplog.text.lower()
        assert "42" in caplog.text

    def test_alert_batch_item_failed(self, caplog):
        """alert_batch_item_failed should send HIGH severity alert."""
        import os
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        with caplog.at_level(logging.ERROR, logger="services.alerting"):
            result = alert_batch_item_failed(job_id="abc123", run_id=7, error="Timeout")
            assert result is True
        assert "batch item failed" in caplog.text.lower()

    def test_alert_accuracy_drop(self, caplog):
        """alert_accuracy_drop should send HIGH severity alert."""
        import os
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        with caplog.at_level(logging.ERROR, logger="services.alerting"):
            result = alert_accuracy_drop(run_id=10, confidence=0.65, threshold=0.90)
            assert result is True
        assert "confidence" in caplog.text.lower()
        assert "0.65" in caplog.text

    def test_alert_daily_cost(self, caplog):
        """alert_daily_cost should send MEDIUM severity alert."""
        import os
        os.environ.pop("SLACK_WEBHOOK_URL", None)

        with caplog.at_level(logging.WARNING, logger="services.alerting"):
            result = alert_daily_cost(cost=7.50, limit=5.0)
            assert result is True
        assert "cost" in caplog.text.lower()
        assert "7.50" in caplog.text


# =============================================================================
# INTEGRATION WITH BATCH/EXPORT
# =============================================================================


class TestAlertTriggerIntegration:
    """Test that alert triggers are wired into existing services."""

    def test_batch_queue_has_alert_import(self):
        """batch_queue._process_job should reference alerting on failure."""
        import inspect
        from api.batch_queue import BatchQueue

        source = inspect.getsource(BatchQueue._process_job)
        assert "alert_batch_item_failed" in source

    def test_batch_jobs_has_alert_import(self):
        """batch_jobs._process_single_run should reference alerting on failure."""
        import inspect
        from api.batch_jobs import BatchJobProcessor

        source = inspect.getsource(BatchJobProcessor._process_single_run)
        assert "alert_export_failure" in source

    def test_exports_has_alert_import(self):
        """send_to_cd_with_retry should reference alerting on failure."""
        import inspect
        from api.routes.exports import send_to_cd_with_retry

        source = inspect.getsource(send_to_cd_with_retry)
        assert "alert_export_failure" in source

    def test_zone_extractor_has_alert_import(self):
        """zone_extractor.extract should reference alerting on low confidence."""
        import inspect
        from extractors.zone_extractor import ZoneExtractor

        source = inspect.getsource(ZoneExtractor.extract)
        assert "alert_accuracy_drop" in source


# =============================================================================
# SEVERITY ENUM TESTS
# =============================================================================


class TestSeverityEnum:
    """Test Severity enum values."""

    def test_high_value(self):
        assert Severity.HIGH.value == "high"

    def test_medium_value(self):
        assert Severity.MEDIUM.value == "medium"

    def test_low_value(self):
        assert Severity.LOW.value == "low"

    def test_all_severities(self):
        assert len(Severity) == 3
