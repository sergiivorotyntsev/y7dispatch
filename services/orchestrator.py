"""
Main orchestrator for email-to-ClickUp pipeline.

Flow:
1. Fetch unseen emails from inbox
2. For each email:
   a. Extract Gate Pass from body
   b. Extract data from PDF attachments
   c. Check idempotency (skip if already processed)
   d. Create ClickUp task
   e. Mark email as seen
   f. Record in idempotency store
"""

import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from core.config import AppConfig, get_config
from core.logging_config import LogContext, generate_run_id, get_logger
from extractors import extract_from_pdf
from extractors.gate_pass import GatePassExtractor
from ingest.email_reader import Attachment, EmailMessage, create_email_reader
from models.vehicle import AuctionInvoice
from services.clickup import ClickUpClient, ClickUpTask
from services.idempotency import IdempotencyStore

logger = get_logger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a single attachment."""

    success: bool
    message: str
    attachment_name: str
    attachment_hash: str
    extracted_data: Optional[AuctionInvoice] = None
    clickup_task_id: Optional[str] = None
    clickup_task_url: Optional[str] = None
    error: Optional[str] = None
    skipped_duplicate: bool = False


@dataclass
class EmailProcessingResult:
    """Result of processing a single email."""

    message_id: str
    subject: str
    gate_pass: Optional[str]
    attachment_results: list[ProcessingResult]
    error: Optional[str] = None


class Orchestrator:
    """Main orchestrator for email processing pipeline."""

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or get_config()
        self._clickup_client: Optional[ClickUpClient] = None
        self._idempotency_store: Optional[IdempotencyStore] = None

    @property
    def clickup_client(self) -> ClickUpClient:
        """Lazy-load ClickUp client."""
        if self._clickup_client is None:
            self._clickup_client = ClickUpClient(
                token=self.config.clickup.token,
                list_id=self.config.clickup.list_id,
            )
        return self._clickup_client

    @property
    def idempotency_store(self) -> IdempotencyStore:
        """Lazy-load idempotency store."""
        if self._idempotency_store is None:
            self._idempotency_store = IdempotencyStore(
                db_path=self.config.storage.idempotency_db_path
            )
        return self._idempotency_store

    def process_email(self, email_msg: EmailMessage) -> EmailProcessingResult:
        """Process a single email message."""
        logger.info(f"Processing email: {email_msg.subject}")

        result = EmailProcessingResult(
            message_id=email_msg.message_id,
            subject=email_msg.subject,
            gate_pass=None,
            attachment_results=[],
        )

        # Extract Gate Pass from email body
        body_text = email_msg.body_text or self._html_to_text(email_msg.body_html)
        gate_pass = GatePassExtractor.extract_primary(body_text)
        result.gate_pass = gate_pass

        if gate_pass:
            logger.info(f"Extracted Gate Pass: {gate_pass}")
        else:
            logger.warning("No Gate Pass found in email body")

        # Get PDF attachments
        pdf_attachments = email_msg.pdf_attachments
        if not pdf_attachments:
            logger.warning("No PDF attachments found in email")
            return result

        logger.info(f"Found {len(pdf_attachments)} PDF attachment(s)")

        # Process each PDF attachment
        for attachment in pdf_attachments:
            with LogContext(
                attachment_name=attachment.filename,
                attachment_hash=attachment.hash[:16],
            ):
                att_result = self._process_attachment(
                    email_msg=email_msg,
                    attachment=attachment,
                    gate_pass=gate_pass,
                )
                result.attachment_results.append(att_result)

        return result

    def _process_attachment(
        self,
        email_msg: EmailMessage,
        attachment: Attachment,
        gate_pass: Optional[str],
    ) -> ProcessingResult:
        """Process a single PDF attachment."""
        logger.info(f"Processing attachment: {attachment.filename}")

        result = ProcessingResult(
            success=False,
            message="",
            attachment_name=attachment.filename,
            attachment_hash=attachment.hash,
        )

        # Check idempotency
        is_processed, existing_task_id = self.idempotency_store.is_attachment_processed_in_thread(
            thread_root_id=email_msg.thread_root_id,
            attachment_hash=attachment.hash,
        )

        if is_processed:
            logger.info(f"Attachment already processed, task ID: {existing_task_id}")
            result.success = True
            result.message = "Skipped - already processed"
            result.clickup_task_id = existing_task_id
            result.skipped_duplicate = True
            return result

        # Save PDF to temp file for processing
        temp_dir = self.config.storage.temp_dir
        os.makedirs(temp_dir, exist_ok=True)

        temp_path = os.path.join(temp_dir, f"temp_{attachment.hash[:16]}.pdf")
        try:
            with open(temp_path, "wb") as f:
                f.write(attachment.content)

            # Extract data from PDF
            invoice = extract_from_pdf(temp_path)
            result.extracted_data = invoice

            if invoice:
                logger.info(
                    f"Extracted invoice: source={invoice.source.value}, "
                    f"vehicles={len(invoice.vehicles)}"
                )
            else:
                logger.warning("Failed to extract data from PDF")

        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # Create ClickUp task
        if not self.config.dry_run:
            task_result = self._create_clickup_task(
                email_msg=email_msg,
                attachment=attachment,
                invoice=invoice,
                gate_pass=gate_pass,
            )

            if task_result.get("success"):
                result.success = True
                result.message = "Task created successfully"
                result.clickup_task_id = task_result.get("task_id")
                result.clickup_task_url = task_result.get("url")

                # Record in idempotency store
                self.idempotency_store.mark_processed(
                    thread_root_id=email_msg.thread_root_id,
                    message_id=email_msg.message_id,
                    attachment_hash=attachment.hash,
                    source_type=invoice.source.value if invoice else "UNKNOWN",
                    result_type="clickup_task",
                    result_id=result.clickup_task_id or "",
                )
            else:
                result.success = False
                result.error = task_result.get("error", "Unknown error")
                result.message = f"Failed to create task: {result.error}"
        else:
            # Dry run mode
            result.success = True
            result.message = "Dry run - task would be created"
            logger.info("DRY RUN: Would create ClickUp task")

        return result

    def _create_clickup_task(
        self,
        email_msg: EmailMessage,
        attachment: Attachment,
        invoice: Optional[AuctionInvoice],
        gate_pass: Optional[str],
    ) -> dict[str, Any]:
        """Create a ClickUp task for the extracted data."""
        try:
            # Build task name
            if invoice and invoice.vehicles:
                vehicle = invoice.vehicles[0]
                vehicle_desc = f"{vehicle.year} {vehicle.make} {vehicle.model}"
                lot_number = vehicle.lot_number or invoice.lot_number or "N/A"
                source = invoice.source.value
                task_name = f"[{source}] {vehicle_desc} | LOT {lot_number}"
            else:
                task_name = f"[PARSE_FAILED] {attachment.filename}"
                source = "UNKNOWN"
                lot_number = "N/A"
                vehicle_desc = "Unknown Vehicle"

            # Build description
            desc_parts = [
                f"**Source:** {source}",
                f"**Gate Pass:** {gate_pass or 'NOT FOUND'}",
                "",
            ]

            if invoice and invoice.vehicles:
                vehicle = invoice.vehicles[0]
                desc_parts.extend(
                    [
                        f"**VIN:** {vehicle.vin}",
                        f"**Lot #:** {lot_number}",
                        f"**Vehicle:** {vehicle_desc}",
                    ]
                )

                if vehicle.color:
                    desc_parts.append(f"**Color:** {vehicle.color}")
                if vehicle.mileage:
                    desc_parts.append(f"**Mileage:** {vehicle.mileage:,}")

                desc_parts.append("")

                if invoice.pickup_address:
                    addr = invoice.pickup_address
                    addr_str = ", ".join(
                        filter(
                            None,
                            [
                                addr.name,
                                addr.street,
                                f"{addr.city}, {addr.state} {addr.postal_code}",
                            ],
                        )
                    )
                    desc_parts.append("**Pickup Address:**")
                    desc_parts.append(addr_str)
            else:
                desc_parts.extend(
                    [
                        "**PARSE FAILED** - Manual review required",
                        f"**Attachment:** {attachment.filename}",
                    ]
                )

            # Add email metadata
            desc_parts.extend(
                [
                    "",
                    "---",
                    "**Email Info:**",
                    f"- From: {email_msg.sender}",
                    f"- Subject: {email_msg.subject}",
                    f"- Date: {email_msg.date}",
                    f"- Message-ID: {email_msg.message_id}",
                ]
            )

            description = "\n".join(desc_parts)

            # Create task
            task = ClickUpTask(
                name=task_name,
                description=description,
                priority=3 if invoice else 2,  # Higher priority for parse failures
                tags=[source.lower()] if invoice else ["parse_failed"],
            )

            result = self.clickup_client.create_task(task)
            logger.info(f"Created ClickUp task: {result.get('task_id')}")
            return result

        except Exception as e:
            logger.error(f"Failed to create ClickUp task: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Simple HTML to text conversion."""
        import re

        if not html:
            return ""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        return text.strip()

    def run_once(self) -> list[EmailProcessingResult]:
        """Run a single pass: fetch and process all unseen emails."""
        run_id = generate_run_id()
        results = []

        with LogContext(run_id=run_id):
            logger.info("Starting email processing run")

            email_reader = create_email_reader(self.config.email)

            with email_reader:
                for email_msg in email_reader.fetch_unseen():
                    with LogContext(
                        message_id=email_msg.message_id,
                        thread_root_id=email_msg.thread_root_id,
                    ):
                        try:
                            result = self.process_email(email_msg)
                            results.append(result)

                            # Mark as seen only if at least one attachment was processed successfully
                            # or if there were no PDF attachments (nothing to do)
                            should_mark_seen = not email_msg.pdf_attachments or any(
                                r.success for r in result.attachment_results
                            )

                            if should_mark_seen and email_msg.uid:
                                email_reader.mark_seen(email_msg.uid)
                                logger.info("Marked email as seen")

                        except Exception as e:
                            logger.error(f"Error processing email: {e}", exc_info=True)
                            results.append(
                                EmailProcessingResult(
                                    message_id=email_msg.message_id,
                                    subject=email_msg.subject,
                                    gate_pass=None,
                                    attachment_results=[],
                                    error=str(e),
                                )
                            )

            logger.info(f"Run complete. Processed {len(results)} emails")

        return results

    def run_daemon(self, interval: Optional[int] = None) -> None:
        """Run continuously, checking for new emails at regular intervals."""
        interval = interval or self.config.email.check_interval
        logger.info(f"Starting daemon mode with {interval}s interval")

        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                logger.info("Received interrupt, shutting down")
                break
            except Exception as e:
                logger.error(f"Error in daemon loop: {e}", exc_info=True)

            logger.debug(f"Sleeping for {interval} seconds")
            time.sleep(interval)


def run_once(config: Optional[AppConfig] = None) -> list[EmailProcessingResult]:
    """Convenience function to run a single processing pass."""
    orchestrator = Orchestrator(config)
    return orchestrator.run_once()


def run_daemon(config: Optional[AppConfig] = None, interval: Optional[int] = None) -> None:
    """Convenience function to run in daemon mode."""
    orchestrator = Orchestrator(config)
    orchestrator.run_daemon(interval)
