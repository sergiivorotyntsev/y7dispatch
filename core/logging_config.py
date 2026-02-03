"""Structured logging configuration with correlation fields."""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Optional

# Context variables for log correlation
current_run_id: ContextVar[str] = ContextVar("run_id", default="")
current_message_id: ContextVar[str] = ContextVar("message_id", default="")
current_thread_root_id: ContextVar[str] = ContextVar("thread_root_id", default="")
current_attachment_name: ContextVar[str] = ContextVar("attachment_name", default="")
current_attachment_hash: ContextVar[str] = ContextVar("attachment_hash", default="")


def generate_run_id() -> str:
    """Generate a unique run ID for log correlation."""
    return f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def set_context(
    run_id: Optional[str] = None,
    message_id: Optional[str] = None,
    thread_root_id: Optional[str] = None,
    attachment_name: Optional[str] = None,
    attachment_hash: Optional[str] = None,
) -> None:
    """Set logging context variables."""
    if run_id is not None:
        current_run_id.set(run_id)
    if message_id is not None:
        current_message_id.set(message_id)
    if thread_root_id is not None:
        current_thread_root_id.set(thread_root_id)
    if attachment_name is not None:
        current_attachment_name.set(attachment_name)
    if attachment_hash is not None:
        current_attachment_hash.set(attachment_hash)


def clear_context() -> None:
    """Clear all logging context variables."""
    current_run_id.set("")
    current_message_id.set("")
    current_thread_root_id.set("")
    current_attachment_name.set("")
    current_attachment_hash.set("")


class JSONFormatter(logging.Formatter):
    """JSON log formatter with correlation fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add correlation fields if present
        if run_id := current_run_id.get():
            log_data["run_id"] = run_id
        if message_id := current_message_id.get():
            log_data["message_id"] = message_id
        if thread_root_id := current_thread_root_id.get():
            log_data["thread_root_id"] = thread_root_id
        if attachment_name := current_attachment_name.get():
            log_data["attachment_name"] = attachment_name
        if attachment_hash := current_attachment_hash.get():
            log_data["attachment_hash"] = attachment_hash

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields from record
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        return json.dumps(log_data, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable text formatter with correlation fields."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # Build context string
        ctx_parts = []
        if run_id := current_run_id.get():
            ctx_parts.append(f"run={run_id[:16]}")
        if message_id := current_message_id.get():
            ctx_parts.append(f"msg={message_id[:20]}")
        if attachment_name := current_attachment_name.get():
            ctx_parts.append(f"file={attachment_name}")

        ctx_str = f" [{', '.join(ctx_parts)}]" if ctx_parts else ""

        msg = f"{timestamp} {record.levelname:8s} {record.name}{ctx_str}: {record.getMessage()}"

        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)

        return msg


def setup_logging(
    level: str = "INFO",
    format_type: str = "text",
    logger_name: Optional[str] = None,
) -> logging.Logger:
    """
    Configure logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_type: "json" for structured logs, "text" for human-readable
        logger_name: Specific logger name, or None for root logger

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    logger.handlers.clear()

    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Set formatter
    if format_type.lower() == "json":
        formatter = JSONFormatter()
    else:
        formatter = TextFormatter()

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Don't propagate to root logger
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)


class LogContext:
    """Context manager for setting and clearing log context."""

    def __init__(
        self,
        run_id: Optional[str] = None,
        message_id: Optional[str] = None,
        thread_root_id: Optional[str] = None,
        attachment_name: Optional[str] = None,
        attachment_hash: Optional[str] = None,
    ):
        self.run_id = run_id
        self.message_id = message_id
        self.thread_root_id = thread_root_id
        self.attachment_name = attachment_name
        self.attachment_hash = attachment_hash
        self._tokens = {}

    def __enter__(self):
        if self.run_id:
            self._tokens["run_id"] = current_run_id.set(self.run_id)
        if self.message_id:
            self._tokens["message_id"] = current_message_id.set(self.message_id)
        if self.thread_root_id:
            self._tokens["thread_root_id"] = current_thread_root_id.set(self.thread_root_id)
        if self.attachment_name:
            self._tokens["attachment_name"] = current_attachment_name.set(self.attachment_name)
        if self.attachment_hash:
            self._tokens["attachment_hash"] = current_attachment_hash.set(self.attachment_hash)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for name, token in self._tokens.items():
            globals()[f"current_{name}"].reset(token)
        return False
