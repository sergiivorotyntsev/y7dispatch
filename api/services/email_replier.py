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

# Words that indicate a company name, not a person name
_CORPORATE_WORDS = {
    "llc", "inc", "corp", "corporation", "ltd", "agency", "import", "export",
    "auto", "autos", "motors", "motor", "transport", "transportation",
    "logistics", "international", "group", "co", "services", "service",
    "trading", "enterprises", "global", "dealers", "dealer", "sales",
    "shipping", "freight", "express", "solutions", "partners", "usa",
    "company", "automotive",
}


def _looks_like_person_name(name: str) -> bool:
    """Check if a string looks like a person's name (not a company)."""
    if not name or not name.strip():
        return False
    words = name.strip().split()
    if len(words) > 3:
        return False
    lower_words = {w.lower().rstrip(".,") for w in words}
    if lower_words & _CORPORATE_WORDS:
        return False
    # At least one word should start with uppercase and be alpha
    return any(w[0].isupper() and w.isalpha() for w in words)


class ReplyBodyBuilder:
    """Formats HTML body for confirmation email replies.

    Loads template from email_templates table (template_key='reply_confirmation').
    Falls back to hardcoded default if DB template is unavailable.

    Available placeholders:
        {{greeting}}               - "Hello {name}," or "Hello,"
        {{load_id}}                - Our internal Load ID (e.g. 226PORMA1)
        {{warehouse_name}}         - warehouse name
        {{warehouse_address}}      - street address
        {{warehouse_city}}         - city
        {{warehouse_state}}        - state
        {{warehouse_zip}}          - ZIP code
        {{warehouse_phone}}        - phone number
        {{warehouse_full_address}} - "address, city, state zip"
        {{warehouse_phone_line}}   - phone HTML div (empty if no phone)
        {{vin}}                    - Vehicle VIN number(s), comma-separated
        {{pickup_name}}            - Pickup/auction location name
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
    def _build_variables(load_id: str, warehouse: dict, sender_name: str = None,
                         vin: str = None, pickup_name: str = None) -> dict:
        """Build the variable dict for template substitution."""
        # Smart greeting: use first name if sender_name looks like a person,
        # otherwise plain "Hello," (don't try to extract from email — unreliable)
        display_name = None
        if sender_name and _looks_like_person_name(sender_name):
            display_name = sender_name.split()[0]  # first name only
        greeting = f"Hello {display_name}," if display_name else "Hello,"

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
            "load_id": load_id,
            "vin": vin or "",
            "pickup_name": pickup_name or "",
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
    def build(cls, load_id: str, warehouse: dict, sender_name: str = None,
              vin: str = None, pickup_name: str = None) -> str:
        """Build HTML reply body with Load ID and warehouse address.

        Loads template from DB; falls back to hardcoded default.
        """
        variables = cls._build_variables(load_id, warehouse, sender_name, vin=vin,
                                         pickup_name=pickup_name)

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

    def preview_confirmation(self, run_id: int) -> dict:
        """Build preview of confirmation email with real data, without sending.

        Returns:
            dict with preview_html, recipient metadata, or error
        """
        try:
            return self._preview_confirmation_impl(run_id)
        except Exception as e:
            logger.error("EmailReplier.preview_confirmation(%d) failed: %s", run_id, e)
            return {"success": False, "error": str(e)}

    def _gather_reply_data(self, run_id: int) -> dict:
        """Gather all data needed to build a confirmation reply.

        Returns dict with keys: load_id, cd_listing_id, warehouse, vin, email_log,
        sender, sender_name, subject, graph_message_id.
        On failure returns dict with success=False and error message.
        """
        # Get CD listing — external_id is our internal Load ID (e.g. 226PORMA1),
        # cd_listing_id is CD's internal ID (e.g. 304787159)
        with get_connection() as conn:
            listing = conn.execute(
                "SELECT cd_listing_id, external_id FROM cd_listings WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if not listing:
            return {"success": False, "error": "No CD listing found for this run"}

        load_id = listing["external_id"] or listing["cd_listing_id"]
        cd_listing_id = listing["cd_listing_id"]

        # Get warehouse data, VIN, and pickup name
        warehouse, vin, pickup_name = self._get_warehouse_and_vin_for_run(run_id)
        if not warehouse:
            return {"success": False, "error": "No warehouse found for this run"}

        logger.info("Reply data for run_id=%s: load_id=%s, vin=%s", run_id, load_id, vin)

        # Find email_log entry for this run
        email_log = self._find_email_log_for_run(run_id)
        if not email_log:
            return {"success": False, "error": "No email_log entry found for this run"}

        return {
            "success": True,
            "load_id": load_id,
            "cd_listing_id": cd_listing_id,
            "warehouse": warehouse,
            "vin": vin,
            "pickup_name": pickup_name,
            "email_log": email_log,
            "sender": email_log["sender"],
            "sender_name": email_log["sender_name"],
            "subject": email_log.get("subject", ""),
            "graph_message_id": email_log["graph_message_id"],
        }

    def _preview_confirmation_impl(self, run_id: int) -> dict:
        data = self._gather_reply_data(run_id)
        if not data.get("success"):
            return data

        html_body = self.body_builder.build(
            data["load_id"], data["warehouse"], data["sender_name"],
            vin=data["vin"], pickup_name=data.get("pickup_name"),
        )

        return {
            "success": True,
            "preview_html": html_body,
            "recipient_email": data["sender"],
            "recipient_name": data["sender_name"] or "",
            "subject": data["subject"],
            "load_id": data["load_id"],
            "cd_listing_id": data["cd_listing_id"],
            "vin": data["vin"],
            "warehouse_name": data["warehouse"].get("name", ""),
            "has_graph_id": bool(data["graph_message_id"]),
        }

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

        # 2. Gather all reply data
        data = self._gather_reply_data(run_id)
        if not data.get("success"):
            return data

        load_id = data["load_id"]
        cd_listing_id = data["cd_listing_id"]
        graph_message_id = data["graph_message_id"]

        # Resolve Graph message ID if missing (pre-migration emails)
        if not graph_message_id:
            rfc822_id = data["email_log"].get("message_id")
            if rfc822_id and self.graph:
                graph_message_id = self._resolve_and_cache_graph_id(
                    rfc822_id, data["email_log"]["id"],
                )
            if not graph_message_id:
                return {
                    "success": False,
                    "error": "Original email not found in mailbox",
                }

        sender = data["sender"]
        sender_name = data["sender_name"]

        # 3. Create pending reply record (store cd_listing_id for DB reference)
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO email_replies
                   (email_log_id, run_id, cd_listing_id, status, attempts, created_at)
                   VALUES (?, ?, ?, 'pending', 0, ?)""",
                (data["email_log"]["id"], run_id, cd_listing_id, now),
            )
            conn.commit()
            reply_id = cursor.lastrowid

        # 4. Build HTML body (uses load_id, our internal ID, for display)
        html_body = self.body_builder.build(
            load_id, data["warehouse"], sender_name,
            vin=data["vin"], pickup_name=data.get("pickup_name"),
        )

        # 5. Send via Graph API
        result = self.graph.reply_to_message(graph_message_id, html_body)

        # 6. Update reply record
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
                "Confirmation reply sent for run %d (load %s) to %s",
                run_id, load_id, sender,
            )
            return {
                "success": True,
                "load_id": load_id,
                "cd_listing_id": cd_listing_id,
                "replied_to": sender,
            }
        else:
            return {"success": False, "error": result.get("error", "Reply failed")}

    def _get_warehouse_and_vin_for_run(self, run_id: int) -> tuple[Optional[dict], str, str]:
        """Get warehouse data, VIN, and pickup name for a run via extraction_runs.outputs_json.

        Returns:
            (warehouse_dict or None, vin_string, pickup_name_string)
        """
        with get_connection() as conn:
            run = conn.execute(
                "SELECT outputs_json FROM extraction_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if not run or not run["outputs_json"]:
            return None, "", ""

        outputs = run["outputs_json"]
        if isinstance(outputs, str):
            outputs = json.loads(outputs)

        # Extract VIN — field is "vehicle_vin" in outputs_json
        vin_raw = outputs.get("vehicle_vin") or outputs.get("vin") or ""
        if isinstance(vin_raw, list):
            vin = ", ".join(str(v) for v in vin_raw if v)
        else:
            vin = str(vin_raw) if vin_raw else ""

        pickup_name = outputs.get("pickup_name") or ""

        warehouse_id = outputs.get("warehouse_id")
        if not warehouse_id:
            return None, vin, pickup_name

        with get_connection() as conn:
            wh = conn.execute(
                "SELECT * FROM warehouses WHERE id = ?", (warehouse_id,)
            ).fetchone()
        return (dict(wh) if wh else None), vin, pickup_name

    def _find_email_log_for_run(self, run_id: int) -> Optional[dict]:
        """Find email_log entry that contains this run_id in extraction_run_ids.

        If direct lookup fails, falls back to searching via sibling runs
        (same document_id) to handle re-run scenarios where email_log only
        contains the original run_id.
        """
        # 1. Direct lookup
        result = self._search_email_log_by_run_id(run_id)
        if result:
            return result

        # 2. Fallback: find sibling run_ids via document_id
        with get_connection() as conn:
            run_row = conn.execute(
                "SELECT document_id FROM extraction_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if not run_row:
                return None

            sibling_rows = conn.execute(
                "SELECT id FROM extraction_runs WHERE document_id = ? AND id != ? ORDER BY id",
                (run_row["document_id"], run_id),
            ).fetchall()

        for sib in sibling_rows:
            result = self._search_email_log_by_run_id(sib["id"])
            if result:
                logger.info(
                    "Found email_log for run %d via sibling run %d (same doc %d)",
                    run_id, sib["id"], run_row["document_id"],
                )
                return result

        return None

    def _search_email_log_by_run_id(self, run_id: int) -> Optional[dict]:
        """Search email_log for a specific run_id via junction table."""
        with get_connection() as conn:
            row = conn.execute(
                """SELECT el.id, el.message_id, el.sender, el.sender_name, el.subject,
                          el.graph_message_id, el.extraction_run_ids
                   FROM email_log el
                   INNER JOIN email_run_links erl ON erl.email_log_id = el.id
                   WHERE erl.run_id = ?
                   LIMIT 1""",
                (run_id,),
            ).fetchone()

        return dict(row) if row else None

    def _resolve_and_cache_graph_id(self, rfc822_message_id: str, email_log_id: int) -> Optional[str]:
        """Resolve Graph message ID from RFC822 Message-ID via Graph API.

        Caches the result in email_log.graph_message_id for future use.
        Returns Graph message ID or None if not found.
        """
        try:
            graph_id = self.graph.resolve_graph_message_id(rfc822_message_id)
        except Exception as e:
            logger.warning("Failed to resolve graph_message_id for %s: %s", rfc822_message_id, e)
            return None

        if graph_id:
            logger.info("Resolved graph_message_id for email_log %d: %s", email_log_id, graph_id[:30])
            with get_connection() as conn:
                conn.execute(
                    "UPDATE email_log SET graph_message_id = ? WHERE id = ?",
                    (graph_id, email_log_id),
                )
                conn.commit()
        return graph_id
