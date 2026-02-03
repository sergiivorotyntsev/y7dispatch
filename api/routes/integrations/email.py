"""
Email Integration

Endpoints for testing and managing email ingestion.
"""

import time
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.database import get_connection
from api.routes.integrations.utils import (
    TestConnectionResponse,
    log_integration_action,
    mask_secret,
)

router = APIRouter(prefix="/email", tags=["Email"])


# =============================================================================
# MODELS
# =============================================================================


class EmailRule(BaseModel):
    """Email processing rule."""

    name: str
    enabled: bool = True
    priority: int = 0
    condition_type: (
        str  # subject_contains, from_contains, attachment_type, from_domain, subject_regex
    )
    condition_value: str
    action: str = "process"  # process, ignore
    auction_type_id: Optional[int] = None


class EmailRulesUpdate(BaseModel):
    """Request to update email rules."""

    rules: list[EmailRule]


class EmailActivity(BaseModel):
    """Email activity log entry."""

    id: str
    timestamp: str
    message_id: str
    subject: Optional[str] = None
    sender: Optional[str] = None
    status: str
    rule_matched: Optional[str] = None
    run_id: Optional[int] = None
    error: Optional[str] = None


# =============================================================================
# TEST CONNECTION
# =============================================================================


@router.post("/test", response_model=TestConnectionResponse)
async def test_email_connection():
    """
    Test email IMAP connection.

    Verifies IMAP server connection and authentication.
    """
    import imaplib

    from api.routes.settings import load_settings

    start_time = time.time()
    settings = load_settings()
    email_config = settings.get("email", {})

    server = email_config.get("imap_server")
    port = email_config.get("imap_port", 993)
    email_addr = email_config.get("email_address")
    password = email_config.get("password")

    if not all([server, email_addr, password]):
        log_integration_action("email", "test", "failed", error="Email not configured")
        return TestConnectionResponse(
            status="error",
            message="Email not configured. Set IMAP server, email, and password in settings.",
        )

    try:
        imap = imaplib.IMAP4_SSL(server, port)
        imap.login(email_addr, password)
        imap.select("INBOX")
        status, messages = imap.search(None, "ALL")
        total_messages = len(messages[0].split()) if messages[0] else 0
        status, unseen = imap.search(None, "UNSEEN")
        unseen_count = len(unseen[0].split()) if unseen[0] else 0
        imap.logout()

        duration_ms = int((time.time() - start_time) * 1000)

        log_integration_action(
            "email",
            "test",
            "success",
            details={
                "server": server,
                "total_messages": total_messages,
                "unread": unseen_count,
            },
            duration_ms=duration_ms,
        )

        return TestConnectionResponse(
            status="ok",
            message=f"Connected to {server}",
            details={
                "server": server,
                "port": port,
                "email": mask_secret(email_addr) if email_addr else None,
                "total_messages": total_messages,
                "unread_messages": unseen_count,
            },
            duration_ms=duration_ms,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        error_str = str(e)

        if "authentication" in error_str.lower() or "login" in error_str.lower():
            message = "Authentication failed. Check email and password."
        elif "connection" in error_str.lower():
            message = f"Could not connect to {server}:{port}"
        else:
            message = f"Connection failed: {error_str}"

        log_integration_action(
            "email", "test", "failed", error=error_str[:200], duration_ms=duration_ms
        )

        return TestConnectionResponse(
            status="error",
            message=message,
            duration_ms=duration_ms,
        )


# =============================================================================
# RULES MANAGEMENT
# =============================================================================


@router.get("/rules", response_model=list[EmailRule])
async def get_email_rules():
    """Get configured email processing rules."""
    from api.routes.settings import load_settings

    settings = load_settings()
    rules = settings.get("email_rules", [])
    return [EmailRule(**r) for r in rules]


@router.put("/rules")
async def update_email_rules(request: EmailRulesUpdate):
    """Update email processing rules."""
    from api.routes.settings import load_settings, save_settings

    settings = load_settings()
    settings["email_rules"] = [r.model_dump() for r in request.rules]
    save_settings(settings)

    log_integration_action(
        "email", "update_rules", "success", details={"rule_count": len(request.rules)}
    )

    return {"status": "ok", "count": len(request.rules)}


# =============================================================================
# ACTIVITY LOG
# =============================================================================


def init_email_activity_table():
    """Initialize email activity log table."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_activity_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                message_id TEXT NOT NULL,
                subject TEXT,
                sender TEXT,
                status TEXT NOT NULL,
                rule_matched TEXT,
                run_id INTEGER,
                error TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_email_activity_timestamp
            ON email_activity_log(timestamp DESC)
        """)
        conn.commit()


@router.get("/activity", response_model=list[EmailActivity])
async def get_email_activity(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None),
):
    """Get email ingestion activity log."""
    init_email_activity_table()

    sql = "SELECT * FROM email_activity_log WHERE 1=1"
    params = []

    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    try:
        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            EmailActivity(
                id=row["id"],
                timestamp=row["timestamp"],
                message_id=row["message_id"],
                subject=row["subject"],
                sender=row["sender"],
                status=row["status"],
                rule_matched=row["rule_matched"],
                run_id=row["run_id"],
                error=row["error"],
            )
            for row in rows
        ]
    except Exception:
        return []
