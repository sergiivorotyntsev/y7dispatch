"""
Email Log API — Browse, filter, and manage ingested emails.

Provides paginated access to the email_log table with filtering,
manual process/skip actions, and aggregate stats.
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from api.database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email-log", tags=["Email Log"])


# =============================================================================
# INIT
# =============================================================================


def init_email_log_table():
    """Create email_log table if it doesn't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE,
                thread_id TEXT,
                sender TEXT NOT NULL,
                sender_name TEXT,
                subject TEXT,
                received_date DATETIME,
                body_preview TEXT,
                has_attachments BOOLEAN DEFAULT FALSE,
                attachment_count INTEGER DEFAULT 0,
                attachment_names TEXT,
                gate_pass TEXT,
                status TEXT DEFAULT 'new',
                skip_reason TEXT,
                processed_at DATETIME,
                extraction_run_ids TEXT,
                error_message TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_log_status ON email_log(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_log_sender ON email_log(sender)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_log_date ON email_log(received_date)")
        conn.commit()


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/")
async def get_email_log(
    status: Optional[str] = Query(None, description="Filter by status"),
    sender: Optional[str] = Query(None, description="Filter by sender (substring)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Get paginated email log with optional filters."""
    init_email_log_table()

    sql = "SELECT * FROM email_log WHERE 1=1"
    count_sql = "SELECT COUNT(*) as total FROM email_log WHERE 1=1"
    params: list = []
    count_params: list = []

    if status:
        sql += " AND status = ?"
        count_sql += " AND status = ?"
        params.append(status)
        count_params.append(status)

    if sender:
        sql += " AND (sender LIKE ? OR sender_name LIKE ?)"
        count_sql += " AND (sender LIKE ? OR sender_name LIKE ?)"
        like = f"%{sender}%"
        params.extend([like, like])
        count_params.extend([like, like])

    # Get total count
    with get_connection() as conn:
        total = conn.execute(count_sql, count_params).fetchone()["total"]

    # Get page
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        # Parse JSON fields
        if item.get("attachment_names"):
            try:
                item["attachment_names"] = json.loads(item["attachment_names"])
            except Exception:
                item["attachment_names"] = []
        if item.get("extraction_run_ids"):
            try:
                item["extraction_run_ids"] = json.loads(item["extraction_run_ids"])
            except Exception:
                item["extraction_run_ids"] = []
        items.append(item)

    return {"items": items, "total": total}


@router.post("/{email_id}/process")
async def process_email(email_id: int) -> dict[str, Any]:
    """Manually trigger processing of an email log entry."""
    init_email_log_table()

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM email_log WHERE id = ?", (email_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Email log entry {email_id} not found")

    if row["status"] == "processed":
        raise HTTPException(status_code=400, detail="Email already processed")

    # Update status to ready for next poll_once to pick up
    now = datetime.utcnow().isoformat() + "Z"
    with get_connection() as conn:
        conn.execute(
            "UPDATE email_log SET status = 'ready', processed_at = ? WHERE id = ?",
            (now, email_id),
        )
        conn.commit()

    return {"success": True, "status": "ready", "id": email_id}


@router.post("/{email_id}/skip")
async def skip_email(email_id: int) -> dict[str, Any]:
    """Manually skip an email log entry."""
    init_email_log_table()

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM email_log WHERE id = ?", (email_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Email log entry {email_id} not found")

    with get_connection() as conn:
        conn.execute(
            "UPDATE email_log SET status = 'skipped', skip_reason = 'Manual skip' WHERE id = ?",
            (email_id,),
        )
        conn.commit()

    return {"success": True, "status": "skipped", "id": email_id}


@router.get("/stats")
async def get_email_stats() -> dict[str, Any]:
    """Get aggregate email log statistics."""
    init_email_log_table()

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM email_log GROUP BY status"
        ).fetchall()

    stats = {r["status"]: r["count"] for r in rows}
    total = sum(stats.values())

    return {
        "total": total,
        "processed": stats.get("processed", 0),
        "skipped": stats.get("skipped", 0),
        "failed": stats.get("failed", 0),
        "ready": stats.get("ready", 0),
        "new": stats.get("new", 0),
        "processing": stats.get("processing", 0),
        "duplicate": stats.get("duplicate", 0),
        "thread_reply": stats.get("thread_reply", 0),
    }
