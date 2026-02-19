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
from dataclasses import dataclass
from datetime import datetime
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
        self.processed_folder = self.config.get("processed_folder", "Processed")
        self.upload_path = Path(self.config.get("upload_path", "uploads/email"))
        self.upload_path.mkdir(parents=True, exist_ok=True)
        self.attachments_path = Path(self.config.get("attachments_path", "data/attachments"))
        self.attachments_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Enhancement 1: Gate Pass PIN extraction
    # ------------------------------------------------------------------

    def _extract_gate_pass(self, body_text: str) -> str | None:
        """Extract Gate Pass PIN from email body text."""
        patterns = [
            r'[Gg]ate\s*[Pp]ass\s*(?:PIN|pin|Pin)?\s*[:\-]?\s*(\w{4,10})',
            r'[Pp][Ii][Nn]\s*[:\-]?\s*(\w{4,10})',
            r'[Gg]ate\s*[Pp]ass\s*(?:is|:)\s*(\w{4,10})',
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text)
            if match:
                return match.group(1).strip()
        return None

    def _get_email_body_text(self, msg: email.message.Message) -> str:
        """Extract plain text body from email message."""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body += payload.decode(charset, errors="replace")
        else:
            if msg.get_content_type() == "text/plain":
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
        return body

    # ------------------------------------------------------------------
    # Enhancement 2: Attachment classification
    # ------------------------------------------------------------------

    def _classify_attachment(self, filename: str) -> str:
        """
        Classify PDF by filename:
        - "invoice" — auction invoice/bill of sale (run through HaikuExtractor)
        - "vehicle_release" — Manheim release doc (save for carrier, link to run)
        - "condition_report" — vehicle condition (extract inoperable status)
        - "other" — unknown (treated as invoice)
        """
        fn_lower = filename.lower()
        if any(w in fn_lower for w in ['release', 'vehicle release', 'onsite']):
            return 'vehicle_release'
        if any(w in fn_lower for w in ['condition', 'inspection']):
            return 'condition_report'
        if any(w in fn_lower for w in ['invoice', 'bill', 'receipt', 'sale', 'buyer']):
            return 'invoice'
        return 'invoice'  # default: treat unknown PDFs as invoices

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

    def _save_vehicle_release(self, msg: EmailMessage, filename: str, run_id: int) -> dict | None:
        """Save vehicle release PDF to data/attachments/{run_id}/ and record in DB."""
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
                    "type": "vehicle_release",
                    "path": str(file_path),
                    "url": f"/api/documents/{run_id}/attachments/{safe_filename}",
                }

                # Store reference in extraction_runs.attachments_json
                self._update_run_attachments(run_id, attachment_info)

                return attachment_info
        return None

    def _update_run_attachments(self, run_id: int, attachment_info: dict):
        """Add attachment info to extraction_runs.attachments_json."""
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

            existing.append(attachment_info)

            conn.execute(
                "UPDATE extraction_runs SET attachments_json = ? WHERE id = ?",
                (json.dumps(existing), run_id),
            )
            conn.commit()

    def _save_gate_pass_to_run(self, run_id: int, gate_pass: str):
        """Save gate pass PIN to extraction_run outputs_json."""
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
        """Load email config from settings."""
        from api.routes.settings import load_settings

        settings = load_settings()
        return settings.get("email", {})

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

    def _connect(self) -> bool:
        """Connect to IMAP server."""
        config = self._load_config()

        server = config.get("imap_server")
        port = config.get("imap_port", 993)
        email_addr = config.get("email_address")
        password = config.get("password")

        if not all([server, email_addr, password]):
            self._log_activity("SYSTEM", "connect", "failed", error="Email not configured")
            return False

        try:
            # Handle OAuth2 for Microsoft/Gmail
            auth_type = config.get("auth_type", "password")

            if auth_type == "oauth2":
                # Microsoft/Gmail OAuth2
                access_token = config.get("access_token")
                if not access_token:
                    self._log_activity(
                        "SYSTEM", "connect", "failed", error="OAuth2 access token not configured"
                    )
                    return False

                self.imap = imaplib.IMAP4_SSL(server, port)
                # OAuth2 authentication
                auth_string = f"user={email_addr}\x01auth=Bearer {access_token}\x01\x01"
                self.imap.authenticate("XOAUTH2", lambda x: auth_string)
            else:
                # Standard password auth
                self.imap = imaplib.IMAP4_SSL(server, port)
                self.imap.login(email_addr, password)

            return True

        except Exception as e:
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

        # Find PDF attachments
        pdf_filenames = []
        for part in msg.walk():
            content_type = part.get_content_type()
            filename = part.get_filename()

            if filename:
                filename = self._decode_header_value(filename)

            if content_type == "application/pdf" or (
                filename and filename.lower().endswith(".pdf")
            ):
                if filename:
                    pdf_filenames.append(filename)

        return EmailMessage(
            message_id=message_id,
            uid=uid,
            subject=subject,
            sender=sender,
            date=date,
            has_pdf=len(pdf_filenames) > 0,
            pdf_filenames=pdf_filenames,
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

            if part_filename == filename or (content_type == "application/pdf" and part_filename):
                # Generate unique filename
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
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
        self, file_path: Path, auction_type_id: int
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

        # Create document with source=email
        doc_id = DocumentRepository.create(
            auction_type_id=auction_type_id,
            dataset_split="train",
            filename=file_path.name,
            file_path=str(file_path),
            file_size=len(file_bytes),
            sha256=sha256,
            raw_text=raw_text,
            uploaded_by="email_worker",
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
        timestamp = datetime.utcnow().isoformat() + "Z"

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

    def _move_to_processed(self, uid: str):
        """Move email to processed folder."""
        try:
            # Create folder if not exists
            self.imap.create(self.processed_folder)
        except Exception:
            pass  # Folder may already exist

        try:
            # Copy and delete
            self.imap.copy(uid, self.processed_folder)
            self.imap.store(uid, "+FLAGS", "\\Deleted")
            self.imap.expunge()
        except Exception:
            pass

    def poll_once(self) -> list[ProcessingResult]:
        """
        Poll inbox once and process emails.
        Returns list of processing results.
        """
        results = []

        if not self._connect():
            return results

        try:
            rules = self._load_rules()
            allowed_senders = self._load_allowed_senders()

            # Select inbox
            self.imap.select("INBOX")

            # Search for unread emails
            status, messages = self.imap.search(None, "UNSEEN")
            if status != "OK":
                return results

            uids = messages[0].split()[: self.max_emails_per_poll]

            for uid in uids:
                uid_str = uid.decode() if isinstance(uid, bytes) else uid

                try:
                    # Fetch email
                    status, data = self.imap.fetch(uid, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = data[0][1]
                    msg = self._parse_message(uid_str, raw_email)

                    # Check sender filter
                    if not self._is_sender_allowed(msg.sender, allowed_senders):
                        self._log_activity(
                            msg.message_id,
                            msg.subject,
                            "skipped",
                            sender=msg.sender,
                            error="Sender not in allowed list",
                        )
                        results.append(
                            ProcessingResult(
                                message_id=msg.message_id,
                                status="skipped",
                                rule_matched=None,
                                document_id=None,
                                run_id=None,
                                error="Sender not in allowed list",
                            )
                        )
                        continue

                    # Match rules
                    rule = self._match_rule(msg, rules)

                    if not rule:
                        # No rule matched - skip
                        self._log_activity(
                            msg.message_id,
                            msg.subject,
                            "skipped",
                            sender=msg.sender,
                            error="No matching rule",
                        )
                        results.append(
                            ProcessingResult(
                                message_id=msg.message_id,
                                status="skipped",
                                rule_matched=None,
                                document_id=None,
                                run_id=None,
                                error="No matching rule",
                            )
                        )
                        continue

                    action = rule.get("action", "process")

                    if action == "ignore":
                        self._log_activity(
                            msg.message_id,
                            msg.subject,
                            "skipped",
                            sender=msg.sender,
                            rule_matched=rule.get("name"),
                            error="Rule action: ignore",
                        )
                        results.append(
                            ProcessingResult(
                                message_id=msg.message_id,
                                status="skipped",
                                rule_matched=rule.get("name"),
                                document_id=None,
                                run_id=None,
                                error="Rule action: ignore",
                            )
                        )
                        self._move_to_processed(uid)
                        continue

                    if action == "process" and msg.has_pdf:
                        # Extract gate pass from email body
                        body_text = self._get_email_body_text(msg.raw_message)
                        gate_pass = self._extract_gate_pass(body_text)

                        # Process PDF attachments with classification
                        auction_type_id = rule.get("auction_type_id")
                        last_doc_id = None
                        last_run_id = None

                        for pdf_filename in msg.pdf_filenames:
                            attachment_type = self._classify_attachment(pdf_filename)

                            if attachment_type == "invoice" or attachment_type == "other":
                                # Standard flow: save + extract
                                file_path = self._save_attachment(msg, pdf_filename)

                                if file_path:
                                    # Auto-detect auction type if not specified
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
                                            auction_type_id = 1  # Default

                                    doc_id, run_id = self._process_pdf(file_path, auction_type_id)
                                    last_doc_id = doc_id
                                    last_run_id = run_id

                                    # Save gate pass to this run if found
                                    if gate_pass and run_id:
                                        self._save_gate_pass_to_run(run_id, gate_pass)

                            elif attachment_type == "vehicle_release":
                                # Save release PDF for carrier download
                                if last_run_id:
                                    self._save_vehicle_release(msg, pdf_filename, last_run_id)
                                else:
                                    # Process invoice first, then attach release
                                    # Save to temp and link after invoice processing
                                    file_path = self._save_attachment(msg, pdf_filename)

                            elif attachment_type == "condition_report":
                                # Extract inoperable hint from filename
                                is_inoperable = self._detect_inoperable_from_filename(pdf_filename)
                                if is_inoperable is not None and last_run_id:
                                    self._save_inoperable_to_run(last_run_id, is_inoperable)
                                # Also save as regular attachment
                                file_path = self._save_attachment(msg, pdf_filename)

                        # Log and record result for the email
                        self._log_activity(
                            msg.message_id,
                            msg.subject,
                            "processed",
                            sender=msg.sender,
                            rule_matched=rule.get("name"),
                            run_id=last_run_id,
                        )
                        results.append(
                            ProcessingResult(
                                message_id=msg.message_id,
                                status="processed",
                                rule_matched=rule.get("name"),
                                document_id=last_doc_id,
                                run_id=last_run_id,
                                error=None,
                            )
                        )

                        self._move_to_processed(uid)
                    else:
                        # No PDF or unsupported action
                        self._log_activity(
                            msg.message_id,
                            msg.subject,
                            "skipped",
                            sender=msg.sender,
                            rule_matched=rule.get("name"),
                            error=(
                                "No PDF attachment"
                                if not msg.has_pdf
                                else f"Unsupported action: {action}"
                            ),
                        )
                        results.append(
                            ProcessingResult(
                                message_id=msg.message_id,
                                status="skipped",
                                rule_matched=rule.get("name"),
                                document_id=None,
                                run_id=None,
                                error="No PDF attachment",
                            )
                        )

                except Exception as e:
                    self._log_activity(uid_str, "", "failed", error=str(e))
                    results.append(
                        ProcessingResult(
                            message_id=uid_str,
                            status="failed",
                            rule_matched=None,
                            document_id=None,
                            run_id=None,
                            error=str(e),
                        )
                    )

        finally:
            self._disconnect()

        return results

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
