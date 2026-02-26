"""
Email Replier Service

Sends confirmation email replies after successful CD export.
Uses Microsoft Graph API to reply in the original email thread.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from api.database import get_connection

logger = logging.getLogger(__name__)


class ReplyBodyBuilder:
    """Formats HTML body for confirmation email replies.

    Loads template from email_templates table (template_key='reply_confirmation').
    Falls back to hardcoded default if DB template is unavailable.

    Available placeholders:
        {{greeting}}               - "Hello {name}," or "Hello,"
        {{cd_listing_id}}          - Load ID from Central Dispatch
        {{warehouse_name}}         - warehouse name
        {{warehouse_address}}      - street address
        {{warehouse_city}}         - city
        {{warehouse_state}}        - state
        {{warehouse_zip}}          - ZIP code
        {{warehouse_phone}}        - phone number
        {{warehouse_full_address}} - "address, city, state zip"
        {{warehouse_phone_line}}   - phone HTML div (empty if no phone)
    """

    @staticmethod
    def _load_template() -> Optional[str]:
        """Load reply_confirmation template from DB. Returns None on failure."""
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT body_html FROM email_templates WHERE template_key = 'reply_confirmation'"
                ).fetchone()
            return row["body_html"] if row else None
        except Exception:
            return None

    @staticmethod
    def _build_variables(cd_listing_id: str, warehouse: dict, sender_name: str = None) -> dict:
        """Build the variable dict for template substitution."""
        greeting = f"Hello {sender_name}," if sender_name else "Hello,"

        wh_name = warehouse.get("name", "")
        wh_address = warehouse.get("address", "")
        wh_city = warehouse.get("city", "")
        wh_state = warehouse.get("state", "")
        wh_zip = warehouse.get("zip_code", "")
        wh_phone = warehouse.get("phone", "")

        full_address = ", ".join(filter(None, [wh_address, wh_city]))
        if wh_state:
            full_address = f"{full_address}, {wh_state}"
        if wh_zip:
            full_address = f"{full_address} {wh_zip}"

        phone_line = (
            f'<div style="margin-top:4px;">Phone: {wh_phone}</div>' if wh_phone else ""
        )

        return {
            "greeting": greeting,
            "sender_name": sender_name or "",
            "cd_listing_id": cd_listing_id,
            "warehouse_name": wh_name,
            "warehouse_address": wh_address,
            "warehouse_city": wh_city,
            "warehouse_state": wh_state,
            "warehouse_zip": wh_zip,
            "warehouse_phone": wh_phone,
            "warehouse_full_address": full_address,
            "warehouse_phone_line": phone_line,
        }

    @staticmethod
    def render_template(template_html: str, variables: dict) -> str:
        """Replace {{placeholder}} tokens with variable values."""
        result = template_html
        for key, value in variables.items():
            result = result.replace("{{" + key + "}}", value or "")
        return result

    @classmethod
    def build(cls, cd_listing_id: str, warehouse: dict, sender_name: str = None) -> str:
        """Build HTML reply body with Load ID and warehouse address.

        Loads template from DB; falls back to hardcoded default.
        """
        variables = cls._build_variables(cd_listing_id, warehouse, sender_name)

        template = cls._load_template()
        if template:
            logger.info("Reply template loaded from DB (reply_confirmation)")
            return cls.render_template(template, variables)

        # Fallback: hardcoded default (same as seed template)
        logger.warning("Reply template not found in DB — using fallback")
        from api.routes.email_log import _DEFAULT_REPLY_CONFIRMATION_HTML

        return cls.render_template(_DEFAULT_REPLY_CONFIRMATION_HTML, variables)


class EmailReplier:
    """Orchestrates sending confirmation reply emails after CD export."""

    def __init__(self, graph_reader):
        """
        Args:
            graph_reader: GraphEmailReader instance (already connected or will auto-connect)
        """
        self.graph = graph_reader
        self.body_builder = ReplyBodyBuilder()

    def send_confirmation(self, run_id: int) -> dict:
        """Send confirmation email reply for a given extraction run.

        Returns:
            dict with success, cd_listing_id, replied_to, and optional error/already_sent
        """
        try:
            return self._send_confirmation_impl(run_id)
        except Exception as e:
            logger.error("EmailReplier.send_confirmation(%d) failed: %s", run_id, e)
            return {"success": False, "error": str(e)}

    def _send_confirmation_impl(self, run_id: int) -> dict:
        now = datetime.now(timezone.utc).isoformat() + "Z"

        # 1. Idempotency check — already sent?
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id, status FROM email_replies WHERE run_id = ? AND status = 'sent'",
                (run_id,),
            ).fetchone()
            if existing:
                return {"success": True, "already_sent": True}

        # 2. Get CD listing
        with get_connection() as conn:
            listing = conn.execute(
                "SELECT cd_listing_id, external_id FROM cd_listings WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if not listing:
            return {"success": False, "error": "No CD listing found for this run"}

        cd_listing_id = listing["cd_listing_id"]

        # 3. Get warehouse data
        warehouse = self._get_warehouse_for_run(run_id)
        if not warehouse:
            return {"success": False, "error": "No warehouse found for this run"}

        # 4. Find email_log entry for this run
        email_log = self._find_email_log_for_run(run_id)
        if not email_log:
            return {"success": False, "error": "No email_log entry found for this run"}

        graph_message_id = email_log["graph_message_id"]
        if not graph_message_id:
            return {
                "success": False,
                "error": "Graph message ID not available (old email before migration)",
            }

        sender = email_log["sender"]
        sender_name = email_log["sender_name"]

        # 5. Create pending reply record
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO email_replies
                   (email_log_id, run_id, cd_listing_id, status, attempts, created_at)
                   VALUES (?, ?, ?, 'pending', 0, ?)""",
                (email_log["id"], run_id, cd_listing_id, now),
            )
            conn.commit()
            reply_id = cursor.lastrowid

        # 6. Build HTML body
        html_body = self.body_builder.build(cd_listing_id, warehouse, sender_name)

        # 7. Send via Graph API
        result = self.graph.reply_to_message(graph_message_id, html_body)

        # 8. Update reply record
        with get_connection() as conn:
            if result.get("success"):
                conn.execute(
                    """UPDATE email_replies
                       SET status = 'sent', sent_at = ?, attempts = 1, last_attempt_at = ?
                       WHERE id = ?""",
                    (now, now, reply_id),
                )
            else:
                conn.execute(
                    """UPDATE email_replies
                       SET status = 'failed', error_message = ?, attempts = 1, last_attempt_at = ?
                       WHERE id = ?""",
                    (result.get("error", "Unknown error"), now, reply_id),
                )
            conn.commit()

        if result.get("success"):
            logger.info(
                "Confirmation reply sent for run %d (listing %s) to %s",
                run_id, cd_listing_id, sender,
            )
            return {
                "success": True,
                "cd_listing_id": cd_listing_id,
                "replied_to": sender,
            }
        else:
            return {"success": False, "error": result.get("error", "Reply failed")}

    def _get_warehouse_for_run(self, run_id: int) -> Optional[dict]:
        """Get warehouse data for a run via extraction_runs.outputs_json."""
        with get_connection() as conn:
            run = conn.execute(
                "SELECT outputs_json FROM extraction_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if not run or not run["outputs_json"]:
            return None

        outputs = run["outputs_json"]
        if isinstance(outputs, str):
            outputs = json.loads(outputs)

        warehouse_id = outputs.get("warehouse_id")
        if not warehouse_id:
            return None

        with get_connection() as conn:
            wh = conn.execute(
                "SELECT * FROM warehouses WHERE id = ?", (warehouse_id,)
            ).fetchone()
        return dict(wh) if wh else None

    def _find_email_log_for_run(self, run_id: int) -> Optional[dict]:
        """Find email_log entry that contains this run_id in extraction_run_ids."""
        run_id_str = str(run_id)
        with get_connection() as conn:
            # extraction_run_ids is JSON array stored as TEXT, e.g. "[42, 43]"
            rows = conn.execute(
                """SELECT id, sender, sender_name, subject, graph_message_id,
                          extraction_run_ids
                   FROM email_log
                   WHERE extraction_run_ids IS NOT NULL
                   AND extraction_run_ids LIKE ?""",
                (f"%{run_id_str}%",),
            ).fetchall()

        # Verify run_id is actually in the JSON array (not just substring match)
        for row in rows:
            try:
                run_ids = json.loads(row["extraction_run_ids"] or "[]")
                if run_id in run_ids:
                    return dict(row)
            except (json.JSONDecodeError, TypeError):
                continue

        return None
