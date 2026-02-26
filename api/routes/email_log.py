"""
Email Log API — Browse, filter, and manage ingested emails.

Provides paginated access to the email_log table with filtering,
manual process/skip actions, and aggregate stats.
"""

import json
import logging
from datetime import datetime, timezone
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
        # Migration: add graph_message_id for Graph API reply support
        try:
            conn.execute("ALTER TABLE email_log ADD COLUMN graph_message_id TEXT")
        except Exception:
            pass  # Column already exists
        conn.commit()


def init_email_replies_table():
    """Create email_replies table for tracking confirmation email replies."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_log_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                cd_listing_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TEXT,
                sent_at TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (email_log_id) REFERENCES email_log(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_replies_run_id ON email_replies(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_replies_status ON email_replies(status)")
        conn.commit()


def init_email_templates_table():
    """Create email_templates table for customizable email reply templates."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_key TEXT UNIQUE NOT NULL,
                subject_template TEXT,
                body_html TEXT NOT NULL,
                description TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_by TEXT
            )
        """)
        # Migration: add version column for template upgrades
        try:
            conn.execute("ALTER TABLE email_templates ADD COLUMN version INTEGER DEFAULT 1")
        except Exception:
            pass  # Column already exists
        conn.commit()


_DEFAULT_REPLY_CONFIRMATION_HTML = """\
<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#333;line-height:1.6;max-width:520px;">
  <p>{{greeting}}</p>
  <p>We have received your transport request and created a listing.</p>
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:480px;margin:16px 0;">
    <tr>
      <td style="background-color:#f0faf0;border:1px solid #4caf50;border-radius:8px;padding:16px 20px;text-align:center;">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px;">Load ID</div>
        <div style="font-size:22px;font-weight:bold;color:#2e7d32;">{{load_id}}</div>
        <div style="font-size:13px;color:#555;margin-top:6px;">VIN: {{vin}}</div>
      </td>
    </tr>
  </table>
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:480px;margin:16px 0;">
    <tr>
      <td style="background-color:#f5f8fc;border:1px solid #bbdefb;border-left:4px solid #1976d2;border-radius:4px;padding:12px 16px;">
        <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px;">Delivery Warehouse</div>
        <div style="font-weight:bold;color:#333;">{{warehouse_name}}</div>
        <div style="color:#555;">{{warehouse_full_address}}</div>
      </td>
    </tr>
  </table>
  <p><strong>Status:</strong> Listed &mdash; Searching for carriers</p>
  <p style="margin-top:24px;color:#555;">Best regards,<br/><strong>Y7 Agency</strong></p>
</div>"""


def seed_default_templates():
    """Insert default email templates if they don't exist (INSERT OR IGNORE).

    Also migrates existing templates via version column:
    - version 1 → 2: redesigned HTML (table-based layout, max-width, no notify text)
    - Legacy fixes: {{cd_listing_id}} → {{load_id}}, signature cleanup
    """
    with get_connection() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO email_templates
               (template_key, body_html, description, version)
               VALUES (?, ?, ?, 2)""",
            (
                "reply_confirmation",
                _DEFAULT_REPLY_CONFIRMATION_HTML,
                "Confirmation email sent to sender after CD listing is created",
            ),
        )
        # Migrate v1 → v2: full template redesign (only if not user-edited)
        conn.execute(
            """UPDATE email_templates
               SET body_html = ?, version = 2,
                   updated_at = datetime('now'), updated_by = 'migration_v2'
               WHERE template_key = 'reply_confirmation'
                 AND (version IS NULL OR version < 2)""",
            (_DEFAULT_REPLY_CONFIRMATION_HTML,),
        )
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

    # Enrich with linked document IDs for download links
    all_run_ids = []
    for item in items:
        all_run_ids.extend(item.get("extraction_run_ids") or [])
    run_to_doc = {}
    if all_run_ids:
        with get_connection() as conn:
            ph = ",".join("?" * len(all_run_ids))
            doc_rows = conn.execute(
                f"SELECT er.id as run_id, er.document_id, er.status as run_status, d.filename "
                f"FROM extraction_runs er JOIN documents d ON er.document_id = d.id "
                f"WHERE er.id IN ({ph})",
                all_run_ids,
            ).fetchall()
            for dr in doc_rows:
                run_to_doc[dr["run_id"]] = {
                    "run_id": dr["run_id"],
                    "document_id": dr["document_id"],
                    "run_status": dr["run_status"],
                    "filename": dr["filename"],
                }
    for item in items:
        item["linked_documents"] = [
            run_to_doc[rid] for rid in (item.get("extraction_run_ids") or []) if rid in run_to_doc
        ]

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
    now = datetime.now(timezone.utc).isoformat() + "Z"
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


@router.post("/{email_id}/reprocess")
async def reprocess_email_from_source(email_id: int) -> dict[str, Any]:
    """
    Re-process an email: delete its linked data, reset log entry,
    and re-poll to re-fetch and re-classify with current logic.
    """
    init_email_log_table()

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM email_log WHERE id = ?", (email_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Email log entry {email_id} not found")

    message_id = row["message_id"]

    # Delete linked documents/runs
    with get_connection() as conn:
        run_ids_json = row["extraction_run_ids"]
        if run_ids_json:
            try:
                run_ids = json.loads(run_ids_json)
                if run_ids:
                    ph = ",".join("?" * len(run_ids))
                    # Get doc IDs before deleting runs
                    docs = conn.execute(
                        f"SELECT document_id FROM extraction_runs WHERE id IN ({ph})",
                        run_ids,
                    ).fetchall()
                    doc_ids = [d["document_id"] for d in docs if d["document_id"]]

                    conn.execute(
                        f"DELETE FROM review_items WHERE run_id IN ({ph})",
                        run_ids,
                    )
                    conn.execute(
                        f"DELETE FROM extraction_runs WHERE id IN ({ph})",
                        run_ids,
                    )

                    if doc_ids:
                        dph = ",".join("?" * len(doc_ids))
                        conn.execute(
                            f"DELETE FROM documents WHERE id IN ({dph})",
                            doc_ids,
                        )
            except (json.JSONDecodeError, TypeError):
                pass

        # Delete email_log entry so dedup allows re-ingestion
        conn.execute("DELETE FROM email_log WHERE id = ?", (email_id,))
        conn.commit()

    # Re-poll with 30-day lookback to find the original email
    from api.workers.email_worker import get_worker

    worker = get_worker()
    results = worker.poll_once(since_days=30)

    # Find result for this specific message
    reprocessed = None
    for r in results:
        if r.message_id == message_id:
            reprocessed = {
                "message_id": r.message_id,
                "status": r.status,
                "run_id": r.run_id,
                "document_id": r.document_id,
                "error": r.error,
            }
            break

    return {
        "success": True,
        "reprocessed": reprocessed,
        "total_poll_results": len(results),
    }


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
