"""
Alerting Service — Internal notifications via Slack webhook with logging fallback.

Severity levels:
  HIGH   — Immediate Slack notification (DLQ items, export failures)
  MEDIUM — Hourly digest (daily cost threshold breached)
  LOW    — Daily digest (informational)

If SLACK_WEBHOOK_URL is not set, alerts are logged but never crash.
"""

import json
import logging
import os
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "dispatch@y7agency.com")


class Severity(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Emoji mapping for Slack messages
_SEVERITY_EMOJI = {
    Severity.HIGH: ":red_circle:",
    Severity.MEDIUM: ":large_orange_circle:",
    Severity.LOW: ":large_blue_circle:",
}


def send_alert(
    message: str,
    severity: Severity,
    context: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Send an alert notification.

    Uses Slack webhook if SLACK_WEBHOOK_URL is configured.
    Falls back to logging if Slack is not available.

    Args:
        message: Alert message text
        severity: Alert severity level
        context: Optional dict with additional context (run_id, vin, error, etc.)

    Returns:
        True if alert was sent/logged successfully, False on error.
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL") or SLACK_WEBHOOK_URL

    # Build structured log entry
    log_entry = {
        "alert": message,
        "severity": severity.value,
    }
    if context:
        log_entry["context"] = context

    # Always log the alert regardless of Slack availability
    log_method = {
        Severity.HIGH: logger.error,
        Severity.MEDIUM: logger.warning,
        Severity.LOW: logger.info,
    }.get(severity, logger.info)

    log_method(f"ALERT [{severity.value.upper()}]: {message}" +
               (f" | context={context}" if context else ""))

    if not webhook_url:
        logger.debug("SLACK_WEBHOOK_URL not set — alert logged only")
        return True

    # Send to Slack
    return _send_slack(webhook_url, message, severity, context)


def _send_slack(
    webhook_url: str,
    message: str,
    severity: Severity,
    context: Optional[dict[str, Any]] = None,
) -> bool:
    """Send alert to Slack via webhook. Returns True on success."""
    import httpx

    emoji = _SEVERITY_EMOJI.get(severity, ":information_source:")
    text = f"{emoji} *[{severity.value.upper()}]* {message}"

    if context:
        context_lines = []
        for key, value in context.items():
            context_lines.append(f"  *{key}*: {value}")
        text += "\n" + "\n".join(context_lines)

    payload = {"text": text}

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(webhook_url, json=payload)
            if response.status_code == 200:
                logger.debug(f"Slack alert sent: {severity.value}")
                return True
            else:
                logger.warning(
                    f"Slack webhook returned {response.status_code}: {response.text[:200]}"
                )
                return False
    except Exception as e:
        logger.warning(f"Slack webhook failed: {e}")
        return False


# =============================================================================
# Pre-built alert helpers for common scenarios
# =============================================================================


def alert_export_failure(run_id: int, error: str, vin: str = None) -> bool:
    """Alert when CD export fails."""
    return send_alert(
        f"CD export failed for run {run_id}",
        Severity.HIGH,
        context={"run_id": run_id, "error": error, "vin": vin or "unknown"},
    )


def alert_batch_item_failed(job_id: Any, run_id: int, error: str) -> bool:
    """Alert when a batch job item fails (DLQ equivalent)."""
    return send_alert(
        f"Batch item failed — job {job_id}, run {run_id}",
        Severity.HIGH,
        context={"job_id": str(job_id), "run_id": run_id, "error": error},
    )


def alert_accuracy_drop(run_id: int, confidence: float, threshold: float = 0.90) -> bool:
    """Alert when extraction confidence drops below threshold."""
    return send_alert(
        f"Extraction confidence {confidence:.2f} below threshold {threshold:.2f} for run {run_id}",
        Severity.HIGH,
        context={"run_id": run_id, "confidence": confidence, "threshold": threshold},
    )


def alert_daily_cost(cost: float, limit: float = 5.0) -> bool:
    """Alert when daily API cost exceeds limit."""
    return send_alert(
        f"Daily API cost ${cost:.2f} exceeds ${limit:.2f} limit",
        Severity.MEDIUM,
        context={"cost": cost, "limit": limit},
    )
