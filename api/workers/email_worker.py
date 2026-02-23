"""
Email Polling Worker

Background worker that polls email inbox for PDF attachments
and processes them through the extraction pipeline.

Features:
- IMAP/OAuth2 support (Microsoft/Gmail)
- Rule-based filtering
- Activity logging
- Configurable polling interval
"""

import asyncio
import email
import imaplib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path
from typing import Any, Optional

from api.database import get_connection


@dataclass
class EmailMessage:
    """Parsed email message."""

    message_id: str
    uid: str
    subject: str
    sender: str
    date: str
    has_pdf: bool
    pdf_filenames: list[str]
    raw_message: email.message.Message
    image_filenames: list[str] = field(default_factory=list)


@dataclass
class ProcessingResult:
    """Result of processing an email."""

    message_id: str
    status: str  # processed, skipped, failed
    rule_matched: Optional[str]
    document_id: Optional[int]
    run_id: Optional[int]
    error: Optional[str]


class EmailWorker:
    """
    Email polling worker.

    Polls configured IMAP inbox, applies rules, and processes PDFs.
    """

    def __init__(self, config: dict[str, Any] = None):
        """Initialize worker with config."""
        self.config = config or {}
        self.imap = None
        self.running = False
        self.poll_interval = self.config.get("poll_interval", 300)  # 5 minutes default
        self.max_emails_per_poll = self.config.get("max_emails_per_poll", 20)
        # READ-ONLY mailbox — no processed folder, no flags, no moves
        self.upload_path = Path(self.config.get("upload_path", "uploads/email"))
        self.upload_path.mkdir(parents=True, exist_ok=True)
        self.attachments_path = Path(self.config.get("attachments_path", "data/attachments"))
        self.attachments_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Enhancement 1: Gate Pass PIN extraction
    # ------------------------------------------------------------------

    def _extract_gate_pass(self, body_text: str) -> str | None:
        """Extract Gate Pass PIN from email body text.

        Handles variants: "Gate Pass PIN:", "Gate Pass Pin:", "gate pass pin",
        "PIN:", "pin:", "Gate pass is ABC", "Gate Pass Code: X",
        "Gate Pass #X", "Gate Pass Number: X", etc.
        """
        patterns = [
            # "Gate Pass Pin: D164", "Gate Pass Code: ABC", "Gate Pass #D164", "Gate Pass Number: XY1"
            (r'gate\s*pass\s*(?:pin|code|#|number)\s*[:\-]?\s*([A-Z0-9]{2,10})', 1),
            # "Gate Pass: D164"
            (r'gate\s*pass\s*[:\-]\s*([A-Z0-9]{2,10})', 1),
            # "Gate Pass is D164"
            (r'gate\s*pass\s*(?:is)\s+([A-Z0-9]{2,10})', 1),
            # "PIN: D164"
            (r'\bpin\s*[:\-]\s*([A-Z0-9]{2,10})', 1),
        ]
        for pattern, group in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                result = match.group(group).strip()
                # Reject common false positives
                if result.lower() not in ('pin', 'pass', 'gate', 'the', 'is', 'see'):
                    return result
        return None

    def _get_email_body_text(self, msg: email.message.Message) -> str:
        """Extract plain text body from email message.

        Prefers text/plain parts. Falls back to text/html with tags stripped
        so gate pass PINs in HTML-only emails are still extracted.
        """
        plain = ""
        html = ""
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
                if ct == "text/plain":
                    plain += decoded
                elif ct == "text/html" and not html:
                    html = decoded
        else:
            ct = msg.get_content_type()
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
                if ct == "text/plain":
                    plain = decoded
                elif ct == "text/html":
                    html = decoded

        if plain:
            return plain

        # Fallback: strip HTML tags to get searchable text
        if html:
            return re.sub(r'<[^>]+>', ' ', html)

        return ""

    # ------------------------------------------------------------------
    # Enhancement 2: Attachment classification
    # ------------------------------------------------------------------

    def _classify_attachment(self, filename: str) -> str:
        """
        Classify PDF by filename.

        Returns:
          "invoice"          — auction invoice/bill of sale (extract via HaikuExtractor)
          "listing_page"     — auction listing with photos (save as attachment)
          "condition_report" — vehicle condition report
          "vehicle_release"  — Manheim release doc
          "unknown"          — can't determine from filename alone

        Priority order:
          1. Exact invoice names ("invoice.pdf", etc.)
          2. Invoice keywords ("invoice", "bill", "receipt")
          3. Listing page indicators (auction slug with vehicle + location)
          4. Condition / inspection report
          5. Vehicle release
          6. Unknown (fallback)
        """
        fn_lower = filename.lower().strip()

        # 1. Exact or near-exact invoice names (highest priority)
        #    - "invoice.pdf" = Copart Sales Receipt/Bill of Sale
        #    - "ShowReport.pdf" = IAA main document (VIN, address, fees)
        if fn_lower in ('invoice.pdf', 'bill_of_sale.pdf', 'receipt.pdf',
                        'sales_receipt.pdf'):
            return 'invoice'
        if fn_lower.startswith('showreport'):
            return 'invoice'

        # 2. Filename contains invoice keywords
        if any(w in fn_lower for w in ['invoice', 'bill_of_sale', 'receipt',
                                       'sales_receipt', 'showreport',
                                       'show_report']):
            return 'invoice'

        # 3. Listing page indicators — auction document with vehicle info + photos
        #    Pattern: "{Year} {Make} {Model} _ {status} _ {date} _ {location} _ {Auction}.pdf"
        #    These are NOT invoices — they have photos and vehicle listing data.
        listing_indicators = ['run and drive', 'run_and_drive',
                              'for auction', 'for_auction',
                              'enhanced vehicle', 'enhanced_vehicle']
        auction_suffix = (fn_lower.endswith('copart.pdf')
                          or fn_lower.endswith('iaa.pdf')
                          or fn_lower.endswith('manheim.pdf'))
        if any(ind in fn_lower for ind in listing_indicators) or auction_suffix:
            return 'listing_page'

        # 4. Condition / inspection report (NOT showreport — that's IAA main doc)
        if any(w in fn_lower for w in ['condition', 'inspection',
                                       'show report']):
            return 'condition_report'

        # 5. Vehicle release (Manheim)
        if any(w in fn_lower for w in ['release', 'vehicle release', 'onsite']):
            return 'vehicle_release'

        return 'unknown'

    @staticmethod
    def _count_pdf_pages(pdf_bytes: bytes) -> int:
        """Count pages in a PDF from raw bytes without external libraries.

        Uses the PDF internal structure: counts /Type /Page objects
        minus /Type /Pages (parent node) to get leaf page count.
        """
        if not pdf_bytes:
            return 1
        try:
            count = pdf_bytes.count(b'/Type /Page')
            # /Type /Pages is the parent node, not a leaf page
            count -= pdf_bytes.count(b'/Type /Pages')
            return max(count, 1)
        except Exception:
            return 1

    def _get_attachment_bytes(self, msg: 'EmailMessage', filename: str) -> bytes | None:
        """Get raw bytes for a specific attachment by filename."""
        for part in msg.raw_message.walk():
            part_filename = part.get_filename()
            if part_filename:
                part_filename = self._decode_header_value(part_filename)
            if part_filename == filename:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload
        return None

    def _pick_best_invoice(
        self, msg: 'EmailMessage', invoice_filenames: list[str],
    ) -> tuple[list[str], list[str]]:
        """When multiple PDFs are classified as 'invoice', pick the real Buyer Receipt.

        IAA Buyer Receipts are 1-page, ~145-170 KB PDFs with structured data.
        Listing pages masquerading as ShowReport are 3-page, ~200-250 KB PDFs.

        Returns: (best_invoices, demoted_to_listing)
        """
        import logging
        logger = logging.getLogger(__name__)

        if len(invoice_filenames) <= 1:
            return invoice_filenames, []

        # Get page counts and sizes for each candidate
        candidates = []
        for fn in invoice_filenames:
            pdf_bytes = self._get_attachment_bytes(msg, fn)
            page_count = self._count_pdf_pages(pdf_bytes) if pdf_bytes else 1
            size = len(pdf_bytes) if pdf_bytes else 0
            candidates.append({"filename": fn, "pages": page_count, "size": size})
            logger.info("[EmailWorker] Invoice candidate: '%s' (%d pages, %d bytes)", fn, page_count, size)

        # 1-page PDFs are almost certainly Buyer Receipts
        one_pagers = [c for c in candidates if c["pages"] == 1]
        multi_pagers = [c for c in candidates if c["pages"] > 1]

        if one_pagers:
            # Pick smallest 1-pager as the invoice
            best = min(one_pagers, key=lambda x: x["size"])
            demoted = [c for c in candidates if c["filename"] != best["filename"]]
            for d in demoted:
                logger.info(
                    "[EmailWorker] Demoted '%s' (%d pages, %d bytes) to listing_page — not a Buyer Receipt",
                    d["filename"], d["pages"], d["size"],
                )
            return [best["filename"]], [d["filename"] for d in demoted]

        # No 1-pagers: pick smallest multi-pager
        candidates.sort(key=lambda x: x["size"])
        best = candidates[0]
        demoted = candidates[1:]
        for d in demoted:
            logger.info(
                "[EmailWorker] Demoted '%s' (%d pages) to listing_page — picking smaller candidate",
                d["filename"], d["pages"],
            )
        return [best["filename"]], [d["filename"] for d in demoted]

    def _classify_and_rank_attachments(
        self, msg: 'EmailMessage',
    ) -> dict[str, list[str]]:
        """
        Classify all PDF attachments and pick which to extract.

        Returns dict with keys: invoice, listing_page, condition_report, vehicle_release.

        Logic:
        1. Classify each PDF by filename
        2. Listing pages are saved as attachments (not extracted)
        3. If no explicit invoice found but unknowns exist:
           - Single unknown → it's the invoice
           - Multiple unknowns → SMALLEST by file size (text-based PDFs
             are smaller than photo-heavy listing pages)
        4. If multiple invoices, pick the 1-page Buyer Receipt over multi-page listings
        5. If single invoice is 3+ pages and a listing page is 1 page, swap them
        """
        import logging
        logger = logging.getLogger(__name__)

        classified = {
            "invoice": [],
            "listing_page": [],
            "condition_report": [],
            "vehicle_release": [],
        }

        unknowns = []
        for pdf_filename in msg.pdf_filenames:
            att_type = self._classify_attachment(pdf_filename)
            if att_type == "unknown":
                unknowns.append(pdf_filename)
            else:
                classified[att_type].append(pdf_filename)

        # Resolve unknowns
        if unknowns and not classified["invoice"]:
            if len(unknowns) == 1:
                # Only one PDF and it's unknown → must be the invoice
                classified["invoice"].append(unknowns[0])
                unknowns = []
            else:
                # Multiple unknowns, no explicit invoice → pick SMALLEST as invoice
                # Invoices are text-based PDFs (~100-200 KB), listing pages with photos
                # are larger (~300-600 KB)
                sizes = {}
                for part in msg.raw_message.walk():
                    part_filename = part.get_filename()
                    if part_filename:
                        part_filename = self._decode_header_value(part_filename)
                    if part_filename in unknowns:
                        payload = part.get_payload(decode=True)
                        sizes[part_filename] = len(payload) if payload else 0

                if sizes:
                    smallest = min(sizes, key=sizes.get)
                    classified["invoice"].append(smallest)
                    unknowns.remove(smallest)

        # Remaining unknowns → save as listing pages (don't extract)
        classified["listing_page"].extend(unknowns)

        # KEY RULE: If still no invoice, promote best candidate.
        # IAA emails have no separate "invoice.pdf" — the listing page
        # IS the document to extract (contains VIN, address, etc.).
        # Never leave an email with PDFs and 0 extraction runs.
        if not classified["invoice"]:
            if classified["listing_page"]:
                promoted = classified["listing_page"].pop(0)
                classified["invoice"].append(promoted)
                logger.info("[EmailWorker] No invoice.pdf — promoted listing page '%s' to invoice", promoted)
            elif classified["condition_report"]:
                promoted = classified["condition_report"].pop(0)
                classified["invoice"].append(promoted)
                logger.info("[EmailWorker] No invoice.pdf — promoted condition report '%s' to invoice (last resort)", promoted)

        # CONTENT-AWARE DISAMBIGUATION: When multiple PDFs are classified as
        # invoice (e.g., two ShowReport variants), pick the 1-page Buyer Receipt
        # over 3-page listing pages masquerading as ShowReport.
        if len(classified["invoice"]) > 1:
            best, demoted = self._pick_best_invoice(msg, classified["invoice"])
            classified["invoice"] = best
            classified["listing_page"].extend(demoted)

        # SWAP CHECK: If the single invoice is a multi-page listing and a
        # "listing_page" is actually a 1-page receipt, swap them.
        if len(classified["invoice"]) == 1 and classified["listing_page"]:
            inv_fn = classified["invoice"][0]
            inv_bytes = self._get_attachment_bytes(msg, inv_fn)
            inv_pages = self._count_pdf_pages(inv_bytes) if inv_bytes else 1

            if inv_pages >= 3:
                for lp_fn in classified["listing_page"]:
                    lp_bytes = self._get_attachment_bytes(msg, lp_fn)
                    lp_pages = self._count_pdf_pages(lp_bytes) if lp_bytes else 3
                    if lp_pages == 1:
                        logger.info(
                            "[EmailWorker] Swapping: '%s' (%dp) → listing, '%s' (%dp) → invoice",
                            inv_fn, inv_pages, lp_fn, lp_pages,
                        )
                        classified["invoice"] = [lp_fn]
                        classified["listing_page"].remove(lp_fn)
                        classified["listing_page"].append(inv_fn)
                        break

        # Log classification
        total = sum(len(v) for v in classified.values())
        logger.info(
            "[EmailWorker] Classified %d PDFs: %d invoice, %d listing, %d condition, %d release",
            total, len(classified["invoice"]),
            len(classified["listing_page"]),
            len(classified["condition_report"]),
            len(classified["vehicle_release"]),
        )
        for cat, files in classified.items():
            for f in files:
                logger.info("[EmailWorker]   %s → %s", f, cat)

        return classified

    def _extract_vin_from_subject(self, subject: str) -> str | None:
        """Extract VIN from email subject line.

        VIN is always 17 alphanumeric chars (no I/O/Q per ISO 3779).
        Common format: "VIN Request a car pickup from the auction for COMPANY"
        """
        if not subject:
            return None
        match = re.search(r'\b([A-HJ-NPR-Z0-9]{17})\b', subject.upper())
        return match.group(1) if match else None

    def _save_vin_to_run(self, run_id: int, vin: str):
        """Save VIN extracted from email subject to extraction_run outputs_json."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT outputs_json FROM extraction_runs WHERE id = ?", (run_id,)
            ).fetchone()

            outputs = {}
            if row and row["outputs_json"]:
                try:
                    outputs = json.loads(row["outputs_json"])
                except Exception:
                    outputs = {}

            # Don't overwrite VIN already extracted from PDF
            if outputs.get("vehicle_vin") or outputs.get("vin"):
                return

            # Save to both canonical names for compatibility with review items + CD export
            outputs["vehicle_vin"] = vin
            outputs["vin"] = vin
            outputs["vin_source"] = "email_subject"

            conn.execute(
                "UPDATE extraction_runs SET outputs_json = ? WHERE id = ?",
                (json.dumps(outputs), run_id),
            )
            conn.commit()

    def _detect_inoperable_from_filename(self, filename: str) -> bool | None:
        """Detect inoperable status from condition report filename."""
        fn_lower = filename.lower()
        if any(w in fn_lower for w in ['run_and_drive', 'runs_and_drives', 'run and drive']):
            return False  # operable
        if any(w in fn_lower for w in ['inop', 'non_run', 'non run', 'does_not_run']):
            return True  # inoperable
        return None  # unknown

    # ------------------------------------------------------------------
    # Enhancement 3: Attachment storage
    # ------------------------------------------------------------------

    def _save_vehicle_release(self, msg: EmailMessage, filename: str, run_id: int,
                              att_type: str = "vehicle_release") -> dict | None:
        """Save attachment PDF to data/attachments/{run_id}/ and record in DB."""
        for part in msg.raw_message.walk():
            part_filename = part.get_filename()
            if part_filename:
                part_filename = self._decode_header_value(part_filename)

            if part_filename == filename:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue

                # Save to data/attachments/{run_id}/
                run_dir = self.attachments_path / str(run_id)
                run_dir.mkdir(parents=True, exist_ok=True)

                safe_filename = re.sub(r"[^\w.-]", "_", filename)
                file_path = run_dir / safe_filename
                file_path.write_bytes(payload)

                attachment_info = {
                    "filename": safe_filename,
                    "original_filename": filename,
                    "type": att_type,
                    "path": str(file_path),
                    "url": f"/api/documents/{run_id}/attachments/{safe_filename}",
                }

                # Store reference in extraction_runs.attachments_json
                self._update_run_attachments(run_id, attachment_info)

                return attachment_info
        return None

    def _update_run_attachments(self, run_id: int, attachment_info: dict):
        """Add attachment info to extraction_runs.attachments_json (with dedup)."""
        with get_connection() as conn:
            # Ensure column exists
            try:
                conn.execute("ALTER TABLE extraction_runs ADD COLUMN attachments_json TEXT DEFAULT '[]'")
                conn.commit()
            except Exception:
                pass  # Column already exists

            row = conn.execute(
                "SELECT attachments_json FROM extraction_runs WHERE id = ?", (run_id,)
            ).fetchone()

            existing = []
            if row and row["attachments_json"]:
                try:
                    existing = json.loads(row["attachments_json"])
                except Exception:
                    existing = []

            # Dedup: skip if attachment with same normalized filename already exists
            new_name = (attachment_info.get("filename") or "").lower().replace(" ", "_")
            already_exists = any(
                (a.get("filename") or "").lower().replace(" ", "_") == new_name
                for a in existing
            )
            if already_exists:
                return

            existing.append(attachment_info)

            conn.execute(
                "UPDATE extraction_runs SET attachments_json = ? WHERE id = ?",
                (json.dumps(existing), run_id),
            )
            conn.commit()

    def _save_gate_pass_to_run(self, run_id: int, gate_pass: str):
        """Save gate pass PIN to extraction_run outputs_json (idempotent)."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT outputs_json FROM extraction_runs WHERE id = ?", (run_id,)
            ).fetchone()

            outputs = {}
            if row and row["outputs_json"]:
                try:
                    outputs = json.loads(row["outputs_json"])
                except Exception:
                    outputs = {}

            if outputs.get("gate_pass") == gate_pass:
                return  # Already set

            outputs["gate_pass"] = gate_pass

            conn.execute(
                "UPDATE extraction_runs SET outputs_json = ? WHERE id = ?",
                (json.dumps(outputs), run_id),
            )
            conn.commit()

    def _save_inoperable_to_run(self, run_id: int, is_inoperable: bool):
        """Save inoperable hint to extraction_run outputs_json."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT outputs_json FROM extraction_runs WHERE id = ?", (run_id,)
            ).fetchone()

            outputs = {}
            if row and row["outputs_json"]:
                try:
                    outputs = json.loads(row["outputs_json"])
                except Exception:
                    outputs = {}

            outputs["vehicle_is_inoperable"] = is_inoperable

            conn.execute(
                "UPDATE extraction_runs SET outputs_json = ? WHERE id = ?",
                (json.dumps(outputs), run_id),
            )
            conn.commit()

    def _load_config(self) -> dict[str, Any]:
        """Load email config from credential store (same source as test_connection).

        Checks email_oauth first, then email_imap. Merges in allowed_senders
        and rules from settings.json (non-secret config lives there).
        """
        import logging

        from services.credential_store import get_credential_raw

        logger = logging.getLogger(__name__)

        # Try OAuth2 credential first
        raw = get_credential_raw("email_oauth")
        if raw and raw.get("enabled"):
            config = dict(raw["config"])
            config["auth_type"] = "oauth2"
            logger.info("[EmailWorker] Loaded OAuth2 config for %s", config.get("email_address", "?"))
        else:
            # Fall back to IMAP password credential
            raw = get_credential_raw("email_imap")
            if raw and raw.get("enabled"):
                config = dict(raw["config"])
                config["auth_type"] = "password"
                logger.info("[EmailWorker] Loaded IMAP config for %s", config.get("email_address", "?"))
            else:
                logger.warning("[EmailWorker] No email credentials found in credential store")
                return {}

        # Merge non-secret settings (allowed_senders, rules) from settings.json
        try:
            from api.routes.settings import load_settings

            settings = load_settings()
            email_settings = settings.get("email", {})
            # Only merge non-secret keys that aren't already in credential config
            for key in ("allowed_senders", "poll_interval", "max_emails_per_poll"):
                if key in email_settings and key not in config:
                    config[key] = email_settings[key]
        except Exception:
            pass

        return config

    def _load_rules(self) -> list[dict[str, Any]]:
        """Load email processing rules."""
        from api.routes.settings import load_settings

        settings = load_settings()
        rules = settings.get("email_rules", [])
        # Sort by priority
        return sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)

    def _load_allowed_senders(self) -> list[str]:
        """Load allowed senders list from email config."""
        config = self._load_config()
        return [s.strip().lower() for s in config.get("allowed_senders", []) if s.strip()]

    def _is_sender_allowed(self, sender: str, allowed: list[str]) -> bool:
        """Check if sender matches allowed senders list. Empty list = allow all."""
        if not allowed:
            return True
        sender_lower = sender.lower()
        for entry in allowed:
            if entry.startswith("@"):
                # Domain match
                if entry in sender_lower:
                    return True
            else:
                # Email address match
                if entry in sender_lower:
                    return True
        return False

    @staticmethod
    def _build_search_criteria(allowed_senders: list[str], since_days: int = 0) -> str:
        """Build IMAP SEARCH criteria with server-side sender filtering.

        Uses SINCE date (not UNSEEN) so read emails are also visible in the
        Email Log. Dedup via email_log.message_id UNIQUE prevents reprocessing.

        Args:
            since_days: Look back N days (0 = today only, 7 = past week).
        """
        from datetime import datetime, timedelta
        since_date = (datetime.now() - timedelta(days=since_days)).strftime("%d-%b-%Y")

        if not allowed_senders:
            return f"(SINCE {since_date})"

        # Filter out domain-only entries (@domain.com) — IMAP FROM doesn't support domain-only
        email_senders = [s for s in allowed_senders if not s.startswith("@")]

        # If only domain filters, can't do server-side — fall back to SINCE
        if not email_senders:
            return f"(SINCE {since_date})"

        # Build nested OR for 2+ senders
        # IMAP OR takes exactly 2 arguments: OR <search1> <search2>
        def _nest_or(items: list[str]) -> str:
            if len(items) == 1:
                return f'FROM "{items[0]}"'
            if len(items) == 2:
                return f'(OR FROM "{items[0]}" FROM "{items[1]}")'
            return f'(OR FROM "{items[0]}" {_nest_or(items[1:])})'

        if len(email_senders) == 1:
            return f'(SINCE {since_date} FROM "{email_senders[0]}")'

        or_clause = _nest_or(email_senders)
        return f"(SINCE {since_date} {or_clause})"

    # ------------------------------------------------------------------
    # Email Log table management
    # ------------------------------------------------------------------

    def _init_email_log_table(self):
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

    def _insert_email_log(self, msg: 'EmailMessage', body_preview: str = "",
                          gate_pass: str = None) -> int | None:
        """Insert email into email_log. Returns row id, or None if duplicate."""
        self._init_email_log_table()

        # Extract sender name and email
        sender_name = ""
        sender_email = msg.sender
        import re as _re
        name_match = _re.match(r'^"?([^"<]+)"?\s*<(.+?)>', msg.sender)
        if name_match:
            sender_name = name_match.group(1).strip()
            sender_email = name_match.group(2).strip()

        try:
            with get_connection() as conn:
                cursor = conn.execute("""
                    INSERT INTO email_log
                    (message_id, thread_id, sender, sender_name, subject, received_date,
                     body_preview, has_attachments, attachment_count, attachment_names,
                     gate_pass, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    msg.message_id,
                    msg.raw_message.get("In-Reply-To", ""),
                    sender_email,
                    sender_name,
                    msg.subject,
                    msg.date,
                    body_preview[:2000] if body_preview else "",
                    msg.has_pdf,
                    len(msg.pdf_filenames),
                    json.dumps(msg.pdf_filenames) if msg.pdf_filenames else "[]",
                    gate_pass,
                    "new",
                ))
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            # UNIQUE constraint on message_id → duplicate
            if "UNIQUE" in str(e).upper():
                return None
            raise

    def _update_email_log(self, message_id: str, **kwargs):
        """Update email_log entry by message_id."""
        allowed = {"status", "skip_reason", "processed_at", "extraction_run_ids",
                    "error_message", "gate_pass"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [message_id]

        with get_connection() as conn:
            conn.execute(f"UPDATE email_log SET {set_clause} WHERE message_id = ?", values)
            conn.commit()

    def _is_thread_reply_without_pdf(self, msg: 'EmailMessage') -> bool:
        """Check if email is a thread reply with no PDF attachments."""
        in_reply_to = msg.raw_message.get("In-Reply-To", "")
        references = msg.raw_message.get("References", "")
        is_reply = bool(in_reply_to or references)
        return is_reply and not msg.has_pdf

    def _acquire_oauth2_token(self, config: dict) -> str | None:
        """Acquire access token via Microsoft client_credentials grant.

        Same logic as _test_email_oauth() in credentials.py.
        """
        import logging

        import httpx

        logger = logging.getLogger(__name__)

        tenant_id = config.get("tenant_id", "")
        client_id = config.get("client_id", "")
        client_secret = config.get("client_secret", "")

        if not all([tenant_id, client_id, client_secret]):
            logger.error("[EmailWorker] OAuth2 token: missing tenant_id/client_id/client_secret")
            return None

        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://outlook.office365.com/.default",
            "grant_type": "client_credentials",
        }

        try:
            logger.info("[EmailWorker] POST %s", token_url)
            resp = httpx.post(token_url, data=data, timeout=15.0)
            if resp.status_code == 200:
                token = resp.json()["access_token"]
                expires_in = resp.json().get("expires_in", "?")
                logger.info("[EmailWorker] Token acquired, expires in %ss", expires_in)
                return token
            else:
                error = resp.json().get("error_description", resp.text[:300])
                logger.error("[EmailWorker] Token request failed (%d): %s", resp.status_code, error)
                self._log_activity("SYSTEM", "oauth2_token", "failed", error=f"Token request failed: {error}")
                return None
        except Exception as e:
            logger.error("[EmailWorker] Token request error: %s", e)
            self._log_activity("SYSTEM", "oauth2_token", "failed", error=str(e))
            return None

    def _connect(self) -> bool:
        """Connect to IMAP server. Supports password auth and OAuth2 client_credentials.

        Uses the same credential store as test_connection() in credentials.py.
        """
        import logging
        import ssl

        logger = logging.getLogger(__name__)

        config = self._load_config()

        if not config:
            self._log_activity("SYSTEM", "connect", "failed", error="No email credentials configured")
            return False

        auth_type = config.get("auth_type", "password")
        email_addr = config.get("email_address")

        if not email_addr:
            self._log_activity("SYSTEM", "connect", "failed", error="No email_address in credentials")
            return False

        logger.info("[EmailWorker] Connecting as %s via %s", email_addr, auth_type)

        try:
            if auth_type == "oauth2":
                # Microsoft OAuth2: acquire token via client_credentials, connect XOAUTH2
                # (identical to _test_email_oauth in credentials.py)
                tenant_id = config.get("tenant_id", "")
                client_id = config.get("client_id", "")
                client_secret = config.get("client_secret", "")

                if not all([tenant_id, client_id, client_secret]):
                    missing = []
                    if not tenant_id: missing.append("tenant_id")
                    if not client_id: missing.append("client_id")
                    if not client_secret: missing.append("client_secret")
                    error_msg = f"Missing OAuth2 fields: {', '.join(missing)}"
                    logger.error("[EmailWorker] %s", error_msg)
                    self._log_activity("SYSTEM", "connect", "failed", error=error_msg)
                    return False

                access_token = self._acquire_oauth2_token(config)
                if not access_token:
                    self._log_activity(
                        "SYSTEM", "connect", "failed", error="Failed to acquire OAuth2 token"
                    )
                    return False

                server = "outlook.office365.com"
                port = 993

                ctx = ssl.create_default_context()
                self.imap = imaplib.IMAP4_SSL(server, port, ssl_context=ctx)
                auth_string = f"user={email_addr}\x01auth=Bearer {access_token}\x01\x01"
                self.imap.authenticate("XOAUTH2", lambda x: auth_string.encode())
                logger.info("[EmailWorker] OAuth2 IMAP connected to %s", server)
            else:
                # Standard IMAP password auth
                server = config.get("imap_server")
                port = int(config.get("imap_port", 993))
                password = config.get("password")

                if not all([server, password]):
                    self._log_activity("SYSTEM", "connect", "failed", error="IMAP server/password not configured")
                    return False

                ctx = ssl.create_default_context()
                self.imap = imaplib.IMAP4_SSL(server, port, ssl_context=ctx)
                self.imap.login(email_addr, password)
                logger.info("[EmailWorker] IMAP connected to %s:%d", server, port)

            return True

        except Exception as e:
            logger.error("[EmailWorker] Connect failed: %s", e)
            self._log_activity("SYSTEM", "connect", "failed", error=str(e))
            return False

    def _disconnect(self):
        """Disconnect from IMAP server."""
        if self.imap:
            try:
                self.imap.logout()
            except Exception:
                pass
            self.imap = None

    def _decode_header_value(self, value: str) -> str:
        """Decode email header value."""
        if not value:
            return ""

        decoded_parts = decode_header(value)
        result = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                try:
                    result.append(part.decode(encoding or "utf-8", errors="replace"))
                except Exception:
                    result.append(part.decode("utf-8", errors="replace"))
            else:
                result.append(part)
        return "".join(result)

    def _parse_message(self, uid: str, raw: bytes) -> EmailMessage:
        """Parse raw email into EmailMessage."""
        msg = email.message_from_bytes(raw)

        message_id = msg.get("Message-ID", f"<{uid}@local>")
        subject = self._decode_header_value(msg.get("Subject", ""))
        sender = self._decode_header_value(msg.get("From", ""))
        date = msg.get("Date", "")

        # Find PDF and image attachments (generous detection)
        pdf_filenames = []
        image_filenames = []
        image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".webp"}
        for part in msg.walk():
            content_type = part.get_content_type()
            filename = part.get_filename()
            disposition = str(part.get("Content-Disposition") or "")

            if filename:
                filename = self._decode_header_value(filename)

            is_pdf = (
                content_type == "application/pdf"
                or (filename and filename.lower().endswith(".pdf"))
                or (content_type == "application/octet-stream"
                    and filename and filename.lower().endswith(".pdf"))
            )

            is_image = (
                content_type.startswith("image/")
                or (filename and any(filename.lower().endswith(ext) for ext in image_extensions))
            ) and "attachment" in disposition.lower()

            if is_pdf and filename:
                pdf_filenames.append(filename)
            elif is_image and filename:
                image_filenames.append(filename)

        return EmailMessage(
            message_id=message_id,
            uid=uid,
            subject=subject,
            sender=sender,
            date=date,
            has_pdf=len(pdf_filenames) > 0,
            pdf_filenames=pdf_filenames,
            image_filenames=image_filenames,
            raw_message=msg,
        )

    def _match_rule(self, msg: EmailMessage, rules: list[dict]) -> Optional[dict]:
        """Match email against rules. Returns first matching rule."""
        for rule in rules:
            if not rule.get("enabled", True):
                continue

            condition_type = rule.get("condition_type")
            condition_value = rule.get("condition_value", "")

            matched = False

            if condition_type == "subject_contains":
                matched = condition_value.lower() in msg.subject.lower()

            elif condition_type == "from_contains":
                matched = condition_value.lower() in msg.sender.lower()

            elif condition_type == "attachment_type":
                if condition_value.lower() == "pdf":
                    matched = msg.has_pdf

            elif condition_type == "subject_regex":
                try:
                    matched = bool(re.search(condition_value, msg.subject, re.IGNORECASE))
                except Exception:
                    pass

            elif condition_type == "from_domain":
                # Extract domain from sender
                domain_match = re.search(r"@([\w.-]+)", msg.sender)
                if domain_match:
                    matched = domain_match.group(1).lower() == condition_value.lower()

            if matched:
                return rule

        return None

    def _save_attachment(self, msg: EmailMessage, filename: str) -> Optional[Path]:
        """Save PDF attachment to disk."""
        for part in msg.raw_message.walk():
            content_type = part.get_content_type()
            part_filename = part.get_filename()

            if part_filename:
                part_filename = self._decode_header_value(part_filename)

            if part_filename == filename:
                # Generate unique filename
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                safe_filename = re.sub(r"[^\w.-]", "_", filename)
                unique_filename = f"{timestamp}_{uuid.uuid4().hex[:8]}_{safe_filename}"

                file_path = self.upload_path / unique_filename

                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        file_path.write_bytes(payload)
                        return file_path
                except Exception:
                    pass

        return None

    def _detect_auction_type(self, text: str) -> Optional[int]:
        """Detect auction type from text content."""
        text_upper = text.upper()

        with get_connection() as conn:
            auction_types = conn.execute(
                "SELECT id, code, extractor_config FROM auction_types WHERE is_active = TRUE"
            ).fetchall()

        for at in auction_types:
            config = at["extractor_config"]
            if config:
                try:
                    cfg = json.loads(config) if isinstance(config, str) else config
                    patterns = cfg.get("patterns", [])
                    for pattern in patterns:
                        if pattern.upper() in text_upper:
                            return at["id"]
                except Exception:
                    pass

        # Default to "OTHER" type
        with get_connection() as conn:
            other = conn.execute("SELECT id FROM auction_types WHERE code = 'OTHER'").fetchone()
            return other["id"] if other else 1

    def _process_pdf(
        self, file_path: Path, auction_type_id: int,
        email_metadata: dict = None,
    ) -> tuple[Optional[int], Optional[int]]:
        """
        Process PDF file: create document and run extraction.
        Returns (document_id, run_id).
        """
        import hashlib

        import pdfplumber

        from api.models import DocumentRepository, ExtractionRunRepository
        from api.routes.extractions import run_extraction

        # Calculate hash
        file_bytes = file_path.read_bytes()
        sha256 = hashlib.sha256(file_bytes).hexdigest()

        # Check for duplicate
        existing = DocumentRepository.get_by_sha256(sha256)
        if existing:
            return existing.id, None  # Already processed

        # Extract text
        raw_text = ""
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        raw_text += text + "\n"
        except Exception:
            pass

        # Create document with source=email and email metadata
        doc_id = DocumentRepository.create(
            auction_type_id=auction_type_id,
            dataset_split="train",
            filename=file_path.name,
            file_path=str(file_path),
            file_size=len(file_bytes),
            sha256=sha256,
            raw_text=raw_text,
            uploaded_by="email_worker",
            source="email",
            email_metadata_json=json.dumps(email_metadata) if email_metadata else None,
        )

        # Check if scanned (low text content)
        if len(raw_text.strip()) < 100:
            # Mark as manual_required
            run_id = ExtractionRunRepository.create(
                document_id=doc_id,
                auction_type_id=auction_type_id,
                extractor_kind="rule",
            )
            ExtractionRunRepository.update(
                run_id,
                status="manual_required",
                errors_json=[{"error": "Scanned PDF - OCR required"}],
            )
            return doc_id, run_id

        # Create and run extraction
        run_id = ExtractionRunRepository.create(
            document_id=doc_id,
            auction_type_id=auction_type_id,
            extractor_kind="rule",
        )

        run_extraction(run_id, doc_id, auction_type_id)

        return doc_id, run_id

    def _log_activity(
        self,
        message_id: str,
        subject: str,
        status: str,
        sender: str = None,
        rule_matched: str = None,
        run_id: int = None,
        error: str = None,
    ):
        """Log email activity."""
        entry_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        with get_connection() as conn:
            # Create table if needed
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

            conn.execute(
                """
                INSERT INTO email_activity_log
                (id, timestamp, message_id, subject, sender, status, rule_matched, run_id, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    entry_id,
                    timestamp,
                    message_id,
                    subject,
                    sender,
                    status,
                    rule_matched,
                    run_id,
                    error,
                ),
            )
            conn.commit()

    # NOTE: _move_to_processed was REMOVED (Day 13A).
    # READ-ONLY mailbox access — no flags, no moves, no deletes.
    # All tracking is internal via email_log table (message_id UNIQUE dedup).

    def poll_once(self, since_days: int = 7) -> list[ProcessingResult]:
        """
        Poll inbox once and process emails.

        Uses server-side IMAP SEARCH filtering for allowed senders,
        logs every email to email_log table, and handles thread dedup.
        Already-processed emails are skipped via message_id dedup in email_log.

        Args:
            since_days: Look back N days (default 7 = past week).
        """
        import logging
        from datetime import datetime

        logger = logging.getLogger(__name__)
        results = []

        if not self._connect():
            return results

        try:
            rules = self._load_rules()
            allowed_senders = self._load_allowed_senders()

            # Select inbox
            self.imap.select("INBOX")

            # Server-side sender filtering via IMAP SEARCH
            criteria = self._build_search_criteria(allowed_senders, since_days=since_days)
            logger.info("[EmailWorker] IMAP SEARCH: %s", criteria)
            status, messages = self.imap.search(None, criteria)
            if status != "OK":
                return results

            msg_ids = messages[0].split() if messages[0] else []
            # Most recent first — IMAP returns oldest first (ascending),
            # reverse so we process newest emails within the per-poll limit
            msg_ids.reverse()
            uids = msg_ids[: self.max_emails_per_poll]
            logger.info("[EmailWorker] Found %d emails matching criteria (processing %d newest)", len(msg_ids), len(uids))

            for uid in uids:
                uid_str = uid.decode() if isinstance(uid, bytes) else uid

                try:
                    # Fetch email
                    status, data = self.imap.fetch(uid, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = data[0][1]
                    msg = self._parse_message(uid_str, raw_email)

                    # Extract body text + gate pass early (needed for email_log)
                    body_text = self._get_email_body_text(msg.raw_message)
                    gate_pass = self._extract_gate_pass(body_text)

                    # Insert into email_log (dedup by message_id)
                    log_id = self._insert_email_log(msg, body_preview=body_text, gate_pass=gate_pass)
                    if log_id is None:
                        # Duplicate message_id — already processed
                        logger.info("[EmailWorker] Duplicate message_id: %s", msg.message_id)
                        self._log_activity(
                            msg.message_id, msg.subject, "skipped",
                            sender=msg.sender, error="Duplicate (already in email_log)",
                        )
                        results.append(ProcessingResult(
                            message_id=msg.message_id, status="skipped",
                            rule_matched=None, document_id=None, run_id=None,
                            error="Duplicate",
                        ))
                        continue

                    # Secondary sender filter for domain-only entries (@domain.com)
                    # that can't be filtered server-side
                    if not self._is_sender_allowed(msg.sender, allowed_senders):
                        self._update_email_log(msg.message_id, status="skipped",
                                               skip_reason="Sender not in allowed list")
                        self._log_activity(
                            msg.message_id, msg.subject, "skipped",
                            sender=msg.sender, error="Sender not in allowed list",
                        )
                        results.append(ProcessingResult(
                            message_id=msg.message_id, status="skipped",
                            rule_matched=None, document_id=None, run_id=None,
                            error="Sender not in allowed list",
                        ))
                        continue

                    # Thread dedup: reply without new PDFs → skip
                    if self._is_thread_reply_without_pdf(msg):
                        self._update_email_log(msg.message_id, status="skipped",
                                               skip_reason="Thread reply without PDF")
                        self._log_activity(
                            msg.message_id, msg.subject, "skipped",
                            sender=msg.sender, error="Thread reply without PDF",
                        )
                        results.append(ProcessingResult(
                            message_id=msg.message_id, status="skipped",
                            rule_matched=None, document_id=None, run_id=None,
                            error="Thread reply without PDF",
                        ))
                        continue

                    # Match rules — if rules exist, use them; if empty, auto-process PDFs
                    rule = self._match_rule(msg, rules)
                    rule_name = None
                    action = "process"  # default
                    auction_type_id_from_rule = None

                    if rules:
                        # Rules exist — require a match
                        if not rule:
                            skip_reason = "No matching rule"
                            if not msg.has_pdf:
                                skip_reason = "No PDF attachments"
                            self._update_email_log(msg.message_id, status="skipped",
                                                   skip_reason=skip_reason)
                            self._log_activity(
                                msg.message_id, msg.subject, "skipped",
                                sender=msg.sender, error=skip_reason,
                            )
                            results.append(ProcessingResult(
                                message_id=msg.message_id, status="skipped",
                                rule_matched=None, document_id=None, run_id=None,
                                error=skip_reason,
                            ))
                            continue

                        action = rule.get("action", "process")
                        rule_name = rule.get("name")
                        auction_type_id_from_rule = rule.get("auction_type_id")

                        if action == "ignore":
                            self._update_email_log(msg.message_id, status="skipped",
                                                   skip_reason=f"Rule '{rule_name}': ignore")
                            self._log_activity(
                                msg.message_id, msg.subject, "skipped",
                                sender=msg.sender, rule_matched=rule_name,
                                error="Rule action: ignore",
                            )
                            results.append(ProcessingResult(
                                message_id=msg.message_id, status="skipped",
                                rule_matched=rule_name, document_id=None,
                                run_id=None, error="Rule action: ignore",
                            ))
                            # READ-ONLY mailbox — email stays in Inbox
                            continue
                    else:
                        # No rules configured — auto-process any email with PDF
                        # from allowed senders (sender already filtered above)
                        rule_name = "auto (no rules)"
                        logger.info("[EmailWorker] No rules configured, auto-processing: %s",
                                    msg.subject)

                    if not msg.has_pdf:
                        self._update_email_log(msg.message_id, status="skipped",
                                               skip_reason="No PDF attachments")
                        self._log_activity(
                            msg.message_id, msg.subject, "skipped",
                            sender=msg.sender, rule_matched=rule_name,
                            error="No PDF attachments",
                        )
                        results.append(ProcessingResult(
                            message_id=msg.message_id, status="skipped",
                            rule_matched=rule_name, document_id=None,
                            run_id=None, error="No PDF attachments",
                        ))
                        continue

                    if action == "process" and msg.has_pdf:
                        # Mark as processing
                        self._update_email_log(msg.message_id, status="processing")

                        email_metadata = {
                            "sender": msg.sender,
                            "subject": msg.subject,
                            "message_id": msg.message_id,
                            "date": msg.date,
                        }

                        # Classify ALL attachments, pick invoice(s) for extraction
                        classified = self._classify_and_rank_attachments(msg)
                        auction_type_id = auction_type_id_from_rule
                        last_doc_id = None
                        last_run_id = None
                        run_ids = []

                        # 1. Process INVOICE PDFs through extraction
                        for pdf_filename in classified["invoice"]:
                            file_path = self._save_attachment(msg, pdf_filename)
                            if file_path:
                                if not auction_type_id:
                                    try:
                                        with open(file_path, "rb") as f:
                                            import pdfplumber
                                            with pdfplumber.open(f) as pdf:
                                                text = ""
                                                for page in pdf.pages[:3]:
                                                    t = page.extract_text()
                                                    if t:
                                                        text += t
                                        auction_type_id = self._detect_auction_type(text)
                                    except Exception:
                                        auction_type_id = 1

                                doc_id, run_id = self._process_pdf(
                                    file_path, auction_type_id,
                                    email_metadata=email_metadata,
                                )
                                last_doc_id = doc_id
                                last_run_id = run_id
                                if run_id:
                                    run_ids.append(run_id)

                                if gate_pass and run_id:
                                    self._save_gate_pass_to_run(run_id, gate_pass)

                        # 2. Save LISTING PAGES as attachments (photos + vehicle info)
                        for pdf_filename in classified["listing_page"]:
                            if last_run_id:
                                self._save_vehicle_release(msg, pdf_filename, last_run_id,
                                                           att_type="listing_page")
                            else:
                                self._save_attachment(msg, pdf_filename)
                            # Listing page filenames can indicate operable status
                            is_inoperable = self._detect_inoperable_from_filename(pdf_filename)
                            if is_inoperable is not None and last_run_id:
                                self._save_inoperable_to_run(last_run_id, is_inoperable)

                        # 3. Save CONDITION REPORTS as attachments + extract inoperable hint
                        for pdf_filename in classified["condition_report"]:
                            if last_run_id:
                                self._save_vehicle_release(msg, pdf_filename, last_run_id,
                                                           att_type="condition_report")
                            else:
                                self._save_attachment(msg, pdf_filename)
                            is_inoperable = self._detect_inoperable_from_filename(pdf_filename)
                            if is_inoperable is not None and last_run_id:
                                self._save_inoperable_to_run(last_run_id, is_inoperable)

                        # 4. Save VEHICLE RELEASE PDFs as attachments
                        for pdf_filename in classified["vehicle_release"]:
                            if last_run_id:
                                self._save_vehicle_release(msg, pdf_filename, last_run_id)
                            else:
                                self._save_attachment(msg, pdf_filename)

                        # 5. Save IMAGE attachments (PNG, JPG, etc.)
                        for img_filename in msg.image_filenames:
                            if last_run_id:
                                self._save_vehicle_release(
                                    msg, img_filename, last_run_id, att_type="image"
                                )

                        # Guarantee gate_pass in ALL linked runs
                        if gate_pass and run_ids:
                            for rid in run_ids:
                                self._save_gate_pass_to_run(rid, gate_pass)

                        # VIN fallback: extract from email subject for scanned PDFs
                        if run_ids:
                            subject_vin = self._extract_vin_from_subject(msg.subject)
                            if subject_vin:
                                for rid in run_ids:
                                    self._save_vin_to_run(rid, subject_vin)

                        # Update email_log with results
                        self._update_email_log(
                            msg.message_id,
                            status="processed",
                            processed_at=datetime.now(timezone.utc).isoformat() + "Z",
                            extraction_run_ids=json.dumps(run_ids) if run_ids else None,
                            gate_pass=gate_pass,
                        )

                        self._log_activity(
                            msg.message_id, msg.subject, "processed",
                            sender=msg.sender, rule_matched=rule_name,
                            run_id=last_run_id,
                        )
                        results.append(ProcessingResult(
                            message_id=msg.message_id, status="processed",
                            rule_matched=rule_name, document_id=last_doc_id,
                            run_id=last_run_id, error=None,
                        ))

                        # READ-ONLY mailbox — email stays in Inbox

                except Exception as e:
                    logger.error("[EmailWorker] Error processing uid=%s: %s", uid_str, e)
                    # Try to update email_log with error
                    try:
                        self._update_email_log(
                            uid_str, status="failed",
                            error_message=str(e)[:500],
                        )
                    except Exception:
                        pass
                    self._log_activity(uid_str, "", "failed", error=str(e))
                    results.append(ProcessingResult(
                        message_id=uid_str, status="failed",
                        rule_matched=None, document_id=None,
                        run_id=None, error=str(e),
                    ))

        finally:
            self._disconnect()

        return results

    @staticmethod
    def _build_search_criteria_range(
        allowed_senders: list[str],
        since_date_str: str,
        until_date_str: str | None = None,
    ) -> str:
        """Build IMAP SEARCH criteria with date range and sender filtering.

        Args:
            since_date_str: IMAP-format date e.g. "04-Feb-2026"
            until_date_str: Optional IMAP-format BEFORE date (exclusive upper bound)
        """
        date_clause = f"SINCE {since_date_str}"
        if until_date_str:
            date_clause += f" BEFORE {until_date_str}"

        if not allowed_senders:
            return f"({date_clause})"

        email_senders = [s for s in allowed_senders if not s.startswith("@")]
        if not email_senders:
            return f"({date_clause})"

        def _nest_or(items: list[str]) -> str:
            if len(items) == 1:
                return f'FROM "{items[0]}"'
            if len(items) == 2:
                return f'(OR FROM "{items[0]}" FROM "{items[1]}")'
            return f'(OR FROM "{items[0]}" {_nest_or(items[1:])})'

        if len(email_senders) == 1:
            return f'({date_clause} FROM "{email_senders[0]}")'
        or_clause = _nest_or(email_senders)
        return f"({date_clause} {or_clause})"

    def scan_emails(self, since_date: str, until_date: str | None = None) -> dict:
        """Scan inbox for emails in date range WITHOUT processing.

        Connects to IMAP, lists emails, cross-references with email_log
        and extraction_runs for duplicate/already-processed detection.

        Args:
            since_date: ISO date string (YYYY-MM-DD)
            until_date: Optional ISO date string for upper bound (exclusive)

        Returns:
            dict with emails list and summary counts
        """
        import logging

        logger = logging.getLogger(__name__)
        self._init_email_log_table()

        if not self._connect():
            return {"emails": [], "total": 0, "already_processed": 0, "new": 0,
                    "error": "Could not connect to email server"}

        try:
            allowed_senders = self._load_allowed_senders()
            self.imap.select("INBOX", readonly=True)

            # Convert ISO dates to IMAP format (DD-Mon-YYYY)
            since_dt = datetime.strptime(since_date, "%Y-%m-%d")
            since_imap = since_dt.strftime("%d-%b-%Y")
            until_imap = None
            if until_date:
                # BEFORE is exclusive in IMAP, add 1 day
                until_dt = datetime.strptime(until_date, "%Y-%m-%d")
                from datetime import timedelta
                until_imap = (until_dt + timedelta(days=1)).strftime("%d-%b-%Y")

            criteria = self._build_search_criteria_range(
                allowed_senders, since_imap, until_imap
            )
            logger.info("[EmailWorker] SCAN IMAP SEARCH: %s", criteria)
            status, messages = self.imap.search(None, criteria)
            if status != "OK":
                return {"emails": [], "total": 0, "already_processed": 0, "new": 0,
                        "error": "IMAP search failed"}

            msg_ids = messages[0].split() if messages[0] else []
            msg_ids.reverse()  # newest first
            # Scan up to 100 emails (display only, not processing)
            uids = msg_ids[:100]
            logger.info("[EmailWorker] Scan found %d emails (showing %d)", len(msg_ids), len(uids))

            # Gather known message_ids and VINs from DB
            with get_connection() as conn:
                known_rows = conn.execute(
                    "SELECT message_id, status, extraction_run_ids FROM email_log"
                ).fetchall()
                known_map = {}
                for row in known_rows:
                    known_map[row["message_id"]] = {
                        "status": row["status"],
                        "run_ids": row["extraction_run_ids"],
                    }

                # Build VIN set from all extraction runs
                vin_runs = conn.execute(
                    "SELECT id, status, outputs_json FROM extraction_runs WHERE outputs_json IS NOT NULL"
                ).fetchall()
                vin_to_run = {}
                for vr in vin_runs:
                    try:
                        outputs = json.loads(vr["outputs_json"])
                        vin = outputs.get("vehicle_vin", "")
                        if vin and len(vin) == 17:
                            vin_to_run[vin] = {"run_id": vr["id"], "status": vr["status"]}
                    except Exception:
                        pass

            emails = []
            for uid in uids:
                uid_str = uid.decode() if isinstance(uid, bytes) else uid
                try:
                    status, data = self.imap.fetch(uid, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = data[0][1]
                    msg = self._parse_message(uid_str, raw_email)

                    # Check if already processed
                    known = known_map.get(msg.message_id)
                    already_processed = known is not None and known["status"] == "processed"
                    existing_run_id = None
                    existing_status = None
                    if known and known["run_ids"]:
                        try:
                            run_ids = json.loads(known["run_ids"])
                            if run_ids:
                                existing_run_id = run_ids[0]
                                with get_connection() as conn:
                                    rrow = conn.execute(
                                        "SELECT status FROM extraction_runs WHERE id = ?",
                                        (existing_run_id,),
                                    ).fetchone()
                                    if rrow:
                                        existing_status = rrow["status"]
                        except Exception:
                            pass

                    # Extract VIN from subject
                    vin_in_subject = self._extract_vin_from_subject(msg.subject)

                    # Check for VIN duplicates
                    vin_duplicate = False
                    if vin_in_subject and vin_in_subject in vin_to_run:
                        vin_duplicate = True

                    # Parse date
                    email_date = msg.date
                    try:
                        from email.utils import parsedate_to_datetime
                        dt = parsedate_to_datetime(msg.date)
                        email_date = dt.astimezone(timezone.utc).isoformat()
                    except Exception:
                        pass

                    emails.append({
                        "message_id": msg.message_id,
                        "subject": msg.subject,
                        "sender": msg.sender,
                        "date": email_date,
                        "attachment_count": len(msg.pdf_filenames),
                        "attachment_names": msg.pdf_filenames,
                        "already_processed": already_processed,
                        "existing_run_id": existing_run_id,
                        "existing_status": existing_status,
                        "vin_in_subject": vin_in_subject,
                        "vin_duplicate": vin_duplicate,
                    })
                except Exception as e:
                    logger.warning("[EmailWorker] Scan error for uid=%s: %s", uid_str, e)
                    continue

            already_count = sum(1 for e in emails if e["already_processed"])
            return {
                "emails": emails,
                "total": len(emails),
                "already_processed": already_count,
                "new": len(emails) - already_count,
            }

        finally:
            self._disconnect()

    def process_selected(self, message_ids: list[str]) -> dict:
        """Process only selected emails by message_id.

        Downloads from IMAP, runs through existing processing pipeline.
        Only processes emails whose message_id matches.

        Args:
            message_ids: List of email Message-ID strings to process.

        Returns:
            dict with processed/failed counts and per-item results.
        """
        import logging

        logger = logging.getLogger(__name__)

        if not message_ids:
            return {"processed": 0, "failed": 0, "results": []}

        if not self._connect():
            return {"processed": 0, "failed": 0, "results": [],
                    "error": "Could not connect to email server"}

        try:
            rules = self._load_rules()
            allowed_senders = self._load_allowed_senders()
            self.imap.select("INBOX")

            # Search broadly to find the matching emails
            # Use a 60-day lookback to cover reasonable range
            from datetime import timedelta
            since_date = (datetime.now() - timedelta(days=60)).strftime("%d-%b-%Y")
            criteria = f"(SINCE {since_date})"
            status, messages = self.imap.search(None, criteria)
            if status != "OK":
                return {"processed": 0, "failed": 0, "results": [],
                        "error": "IMAP search failed"}

            all_uids = messages[0].split() if messages[0] else []
            all_uids.reverse()

            target_ids = set(message_ids)
            results = []

            for uid in all_uids:
                if not target_ids:
                    break  # All targets found

                uid_str = uid.decode() if isinstance(uid, bytes) else uid
                try:
                    status, data = self.imap.fetch(uid, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = data[0][1]
                    msg = self._parse_message(uid_str, raw_email)

                    if msg.message_id not in target_ids:
                        continue

                    target_ids.discard(msg.message_id)

                    # Extract body text + gate pass
                    body_text = self._get_email_body_text(msg.raw_message)
                    gate_pass = self._extract_gate_pass(body_text)

                    # Insert into email_log (or get existing)
                    log_id = self._insert_email_log(msg, body_preview=body_text, gate_pass=gate_pass)
                    if log_id is None:
                        # Already in email_log — update status to reprocess
                        self._update_email_log(msg.message_id, status="processing")

                    if not msg.has_pdf:
                        self._update_email_log(msg.message_id, status="failed",
                                               error_message="No PDF attachments")
                        results.append({
                            "message_id": msg.message_id,
                            "status": "failed",
                            "error": "No PDF attachment",
                            "run_id": None,
                            "vin": None,
                        })
                        continue

                    # Process: mark as processing
                    self._update_email_log(msg.message_id, status="processing")

                    email_metadata = {
                        "sender": msg.sender,
                        "subject": msg.subject,
                        "message_id": msg.message_id,
                        "date": msg.date,
                    }

                    classified = self._classify_and_rank_attachments(msg)

                    # Determine auction type from rule or auto-detect
                    rule = self._match_rule(msg, rules)
                    auction_type_id = rule.get("auction_type_id") if rule else None

                    last_doc_id = None
                    last_run_id = None
                    run_ids = []

                    for pdf_filename in classified["invoice"]:
                        file_path = self._save_attachment(msg, pdf_filename)
                        if file_path:
                            if not auction_type_id:
                                try:
                                    with open(file_path, "rb") as f:
                                        import pdfplumber
                                        with pdfplumber.open(f) as pdf:
                                            text = ""
                                            for page in pdf.pages[:3]:
                                                t = page.extract_text()
                                                if t:
                                                    text += t
                                    auction_type_id = self._detect_auction_type(text)
                                except Exception:
                                    auction_type_id = 1

                            doc_id, run_id = self._process_pdf(
                                file_path, auction_type_id,
                                email_metadata=email_metadata,
                            )
                            last_doc_id = doc_id
                            last_run_id = run_id
                            if run_id:
                                run_ids.append(run_id)

                            if gate_pass and run_id:
                                self._save_gate_pass_to_run(run_id, gate_pass)

                    # Save secondary attachments
                    for pdf_filename in classified.get("listing_page", []):
                        if last_run_id:
                            self._save_vehicle_release(msg, pdf_filename, last_run_id,
                                                       att_type="listing_page")
                    for pdf_filename in classified.get("condition_report", []):
                        if last_run_id:
                            self._save_vehicle_release(msg, pdf_filename, last_run_id,
                                                       att_type="condition_report")
                    for pdf_filename in classified.get("vehicle_release", []):
                        if last_run_id:
                            self._save_vehicle_release(msg, pdf_filename, last_run_id)

                    # Save IMAGE attachments (PNG, JPG, etc.)
                    for img_filename in msg.image_filenames:
                        if last_run_id:
                            self._save_vehicle_release(
                                msg, img_filename, last_run_id, att_type="image"
                            )

                    if gate_pass and run_ids:
                        for rid in run_ids:
                            self._save_gate_pass_to_run(rid, gate_pass)

                    # VIN from subject fallback
                    subject_vin = self._extract_vin_from_subject(msg.subject)
                    if subject_vin and run_ids:
                        for rid in run_ids:
                            self._save_vin_to_run(rid, subject_vin)

                    # Extract VIN from outputs for result
                    result_vin = subject_vin
                    if last_run_id and not result_vin:
                        try:
                            with get_connection() as conn:
                                rrow = conn.execute(
                                    "SELECT outputs_json FROM extraction_runs WHERE id = ?",
                                    (last_run_id,),
                                ).fetchone()
                                if rrow and rrow["outputs_json"]:
                                    result_vin = json.loads(rrow["outputs_json"]).get("vehicle_vin")
                        except Exception:
                            pass

                    # Update email_log
                    self._update_email_log(
                        msg.message_id,
                        status="processed",
                        processed_at=datetime.now(timezone.utc).isoformat() + "Z",
                        extraction_run_ids=json.dumps(run_ids) if run_ids else None,
                        gate_pass=gate_pass,
                    )

                    results.append({
                        "message_id": msg.message_id,
                        "status": "success",
                        "run_id": last_run_id,
                        "vin": result_vin,
                    })

                except Exception as e:
                    logger.error("[EmailWorker] process_selected error uid=%s: %s", uid_str, e)
                    results.append({
                        "message_id": uid_str,
                        "status": "failed",
                        "error": str(e),
                        "run_id": None,
                        "vin": None,
                    })

            # Any message_ids not found in mailbox
            for mid in target_ids:
                results.append({
                    "message_id": mid,
                    "status": "failed",
                    "error": "Message not found in mailbox",
                    "run_id": None,
                    "vin": None,
                })

            processed = sum(1 for r in results if r["status"] == "success")
            failed = sum(1 for r in results if r["status"] == "failed")
            return {
                "processed": processed,
                "failed": failed,
                "results": results,
            }

        finally:
            self._disconnect()

    async def run(self):
        """Run worker loop."""
        self.running = True

        while self.running:
            try:
                self.poll_once()
            except Exception as e:
                self._log_activity("SYSTEM", "poll_error", "failed", error=str(e))

            await asyncio.sleep(self.poll_interval)

    def stop(self):
        """Stop worker loop."""
        self.running = False
        self._disconnect()


# Singleton worker instance
_worker_instance: Optional[EmailWorker] = None
_worker_task: Optional[asyncio.Task] = None


def get_worker() -> EmailWorker:
    """Get or create worker instance."""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = EmailWorker()
    return _worker_instance


async def start_worker():
    """Start the email worker in background."""
    global _worker_task
    worker = get_worker()

    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(worker.run())


async def stop_worker():
    """Stop the email worker."""
    global _worker_instance, _worker_task

    if _worker_instance:
        _worker_instance.stop()

    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass


# =============================================================================
# RECOVERY OPERATIONS (standalone — outside EmailWorker class)
#
# These functions use IMAP COPY/STORE/EXPUNGE intentionally to undo
# damage from the old _move_to_processed() code. Normal polling
# (EmailWorker.poll_once) remains READ-ONLY on the mailbox.
# =============================================================================


def recover_processed_emails() -> dict:
    """One-time recovery: move emails from Processed folder back to Inbox.

    Returns dict with 'recovered' count and any errors.
    """
    import logging
    import ssl

    logger = logging.getLogger(__name__)

    worker = get_worker()
    config = worker._load_config()
    if not config:
        return {"error": "No email credentials configured", "recovered": 0}

    auth_type = config.get("auth_type", "password")
    email_addr = config.get("email_address")

    try:
        if auth_type == "oauth2":
            access_token = worker._acquire_oauth2_token(config)
            if not access_token:
                return {"error": "Failed to acquire OAuth2 token", "recovered": 0}

            ctx = ssl.create_default_context()
            imap = imaplib.IMAP4_SSL("outlook.office365.com", 993, ssl_context=ctx)
            auth_string = f"user={email_addr}\x01auth=Bearer {access_token}\x01\x01"
            imap.authenticate("XOAUTH2", lambda x: auth_string.encode())
        else:
            ctx = ssl.create_default_context()
            server = config.get("imap_server", "outlook.office365.com")
            port = int(config.get("imap_port", 993))
            imap = imaplib.IMAP4_SSL(server, port, ssl_context=ctx)
            imap.login(email_addr, config.get("password", ""))

        logger.info("[Recovery] Connected to IMAP as %s", email_addr)

        # Check if Processed folder exists
        try:
            status, _ = imap.select("Processed")
        except Exception:
            imap.logout()
            return {"recovered": 0, "message": "No Processed folder found"}

        if status != "OK":
            imap.logout()
            return {"recovered": 0, "message": "Cannot select Processed folder"}

        status, msgs = imap.search(None, "ALL")
        if not msgs[0]:
            imap.logout()
            return {"recovered": 0, "message": "Processed folder is empty"}

        uids = msgs[0].split()
        recovered = 0

        for uid in uids:
            try:
                imap.copy(uid, "INBOX")
                imap.store(uid, "+FLAGS", "\\Deleted")
                recovered += 1
                logger.info("[Recovery] Moved UID %s from Processed → Inbox", uid.decode())
            except Exception as e:
                logger.error("[Recovery] Failed UID %s: %s", uid.decode(), e)

        imap.expunge()
        imap.logout()

        logger.info("[Recovery] Recovered %d emails from Processed folder", recovered)
        return {"recovered": recovered}

    except Exception as e:
        logger.error("[Recovery] Error: %s", e)
        return {"error": str(e), "recovered": 0}


def reset_email_data() -> dict:
    """Delete all email-sourced data from DB.

    Clears: email_log, email-sourced documents, extraction_runs, review_items.
    Preserves manually uploaded documents.

    Returns dict with counts of deleted rows.
    """
    deleted = {"email_log": 0, "documents": 0, "extraction_runs": 0, "review_items": 0}

    with get_connection() as conn:
        # Find email-sourced document IDs
        docs = conn.execute(
            "SELECT id FROM documents WHERE source = 'email'"
        ).fetchall()
        doc_ids = [d["id"] for d in docs]

        if doc_ids:
            ph = ",".join("?" * len(doc_ids))
            # Find linked extraction_runs
            runs = conn.execute(
                f"SELECT id FROM extraction_runs WHERE document_id IN ({ph})",
                doc_ids,
            ).fetchall()
            run_ids = [r["id"] for r in runs]

            if run_ids:
                rph = ",".join("?" * len(run_ids))
                # Delete review_items first (FK dependency)
                c = conn.execute(
                    f"DELETE FROM review_items WHERE run_id IN ({rph})",
                    run_ids,
                )
                deleted["review_items"] = c.rowcount

                # Delete extraction_runs
                c = conn.execute(
                    f"DELETE FROM extraction_runs WHERE id IN ({rph})",
                    run_ids,
                )
                deleted["extraction_runs"] = c.rowcount

            # Delete documents
            c = conn.execute(
                f"DELETE FROM documents WHERE id IN ({ph})",
                doc_ids,
            )
            deleted["documents"] = c.rowcount

        # Delete all email_log entries
        c = conn.execute("DELETE FROM email_log")
        deleted["email_log"] = c.rowcount

        conn.commit()

    return deleted
