"""
E2E Tests for Alerting Service Integration.

Covers:
- Alert helper functions fire correctly
- Severity levels map to correct log levels
- Slack webhook integration (mocked)
- Alert triggers wired in pipeline code
- Graceful behavior when SLACK_WEBHOOK_URL is unset

All external calls (Slack) are mocked. Tests verify the alerting
service integrates correctly with the rest of the pipeline.
"""

import logging
import os
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_slack_env(monkeypatch):
    """Ensure SLACK_WEBHOOK_URL is unset by default."""
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)


# =============================================================================
# 1. SEND_ALERT — CORE FUNCTION
# =============================================================================


class TestSendAlertCore:
    """Test send_alert function behavior."""

    def test_returns_true_without_slack(self):
        """send_alert should return True even without Slack."""
        result = send_alert("Test message", Severity.LOW)
        assert result is True

    def test_logs_high_as_error(self, caplog):
        """HIGH severity should log at ERROR level."""
        with caplog.at_level(logging.ERROR, logger="services.alerting"):
            send_alert("Critical failure", Severity.HIGH)
        assert any("Critical failure" in r.message for r in caplog.records)

    def test_logs_medium_as_warning(self, caplog):
        """MEDIUM severity should log at WARNING level."""
        with caplog.at_level(logging.WARNING, logger="services.alerting"):
            send_alert("Cost threshold", Severity.MEDIUM)
        assert any("Cost threshold" in r.message for r in caplog.records)

    def test_logs_low_as_info(self, caplog):
        """LOW severity should log at INFO level."""
        with caplog.at_level(logging.INFO, logger="services.alerting"):
            send_alert("Informational", Severity.LOW)
        assert any("Informational" in r.message for r in caplog.records)

    def test_context_included_in_log(self, caplog):
        """Alert context should appear in log output."""
        with caplog.at_level(logging.ERROR, logger="services.alerting"):
            send_alert("Failure", Severity.HIGH, context={"run_id": 42})
        assert any("run_id" in r.message for r in caplog.records)

    def test_never_crashes_on_bad_context(self):
        """send_alert should not crash even with unusual context."""
        result = send_alert(
            "Edge case",
            Severity.LOW,
            context={"nested": {"a": [1, 2, 3]}, "none_val": None},
        )
        assert result is True


# =============================================================================
# 2. SLACK WEBHOOK INTEGRATION
# =============================================================================


class TestSlackWebhook:
    """Test Slack webhook sending (mocked)."""

    @patch("services.alerting._send_slack")
    def test_slack_called_when_url_set(self, mock_slack, monkeypatch):
        """_send_slack should be called when SLACK_WEBHOOK_URL is set."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_slack.return_value = True

        send_alert("Slack test", Severity.HIGH)
        mock_slack.assert_called_once()

    @patch("services.alerting._send_slack")
    def test_slack_not_called_without_url(self, mock_slack):
        """_send_slack should NOT be called when SLACK_WEBHOOK_URL is unset."""
        send_alert("No slack", Severity.HIGH)
        mock_slack.assert_not_called()

    @patch("services.alerting._send_slack")
    def test_slack_failure_returns_false(self, mock_slack, monkeypatch):
        """If _send_slack returns False, send_alert should still succeed."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_slack.return_value = False

        result = send_alert("Crash test", Severity.HIGH)
        # send_alert returns the result of _send_slack when webhook is set
        assert result is False
        mock_slack.assert_called_once()

    @patch("services.alerting._send_slack")
    def test_slack_receives_severity(self, mock_slack, monkeypatch):
        """_send_slack should receive the severity parameter."""
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
        mock_slack.return_value = True

        send_alert("Test", Severity.MEDIUM)
        args = mock_slack.call_args
        assert args[0][2] == Severity.MEDIUM  # 3rd positional arg


# =============================================================================
# 3. ALERT HELPER FUNCTIONS
# =============================================================================


class TestAlertHelpers:
    """Test pre-built alert helper functions."""

    def test_alert_export_failure(self, caplog):
        """alert_export_failure should log with run_id and error."""
        with caplog.at_level(logging.ERROR, logger="services.alerting"):
            result = alert_export_failure(run_id=101, error="CD 502", vin="ABC123")
        assert result is True
        assert any("101" in r.message for r in caplog.records)

    def test_alert_batch_item_failed(self, caplog):
        """alert_batch_item_failed should log with job_id and run_id."""
        with caplog.at_level(logging.ERROR, logger="services.alerting"):
            result = alert_batch_item_failed(job_id=5, run_id=200, error="Timeout")
        assert result is True
        assert any("200" in r.message for r in caplog.records)

    def test_alert_accuracy_drop(self, caplog):
        """alert_accuracy_drop should log with confidence value."""
        with caplog.at_level(logging.ERROR, logger="services.alerting"):
            result = alert_accuracy_drop(run_id=300, confidence=0.72, threshold=0.90)
        assert result is True
        assert any("0.72" in r.message for r in caplog.records)

    def test_alert_daily_cost(self, caplog):
        """alert_daily_cost should log with cost and limit."""
        with caplog.at_level(logging.WARNING, logger="services.alerting"):
            result = alert_daily_cost(cost=7.50, limit=5.0)
        assert result is True
        assert any("7.50" in r.message for r in caplog.records)


# =============================================================================
# 4. ALERT TRIGGERS WIRED IN PIPELINE
# =============================================================================


class TestAlertTriggersWired:
    """Verify alert calls are present in pipeline source code."""

    def test_batch_queue_has_alert_trigger(self):
        """api/batch_queue.py should call alert_batch_item_failed."""
        import inspect
        import api.batch_queue as mod
        source = inspect.getsource(mod)
        assert "alert_batch_item_failed" in source

    def test_exports_has_alert_trigger(self):
        """api/routes/exports.py should call alert_export_failure."""
        import inspect
        import api.routes.exports as mod
        source = inspect.getsource(mod)
        assert "alert_export_failure" in source

    def test_zone_extractor_has_alert_trigger(self):
        """extractors/zone_extractor.py should call alert_accuracy_drop."""
        import inspect
        import extractors.zone_extractor as mod
        source = inspect.getsource(mod)
        assert "alert_accuracy_drop" in source

    def test_batch_jobs_has_alert_trigger(self):
        """api/batch_jobs.py should call alert_export_failure."""
        import inspect
        import api.batch_jobs as mod
        source = inspect.getsource(mod)
        assert "alert_export_failure" in source


# =============================================================================
# 5. SEVERITY ENUM
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
