"""
Tests for Day 13.2: Server-side IMAP sender filtering, email_log table, thread dedup.
"""

import json
import uuid
from unittest.mock import MagicMock

import pytest


# =============================================================================
# IMAP SEARCH Criteria Tests
# =============================================================================


class TestIMAPSearchCriteria:
    """Test _build_search_criteria() generates correct IMAP SEARCH strings.

    Uses SINCE today (not UNSEEN) so read emails are also visible.
    """

    def _build(self, senders):
        from api.workers.email_worker import EmailWorker
        return EmailWorker._build_search_criteria(senders)

    def _today(self):
        from datetime import datetime
        return datetime.now().strftime("%d-%b-%Y")

    def test_no_senders_returns_since_today(self):
        result = self._build([])
        assert result == f"(SINCE {self._today()})"

    def test_one_sender_returns_from_filter(self):
        result = self._build(["autausapl@gmail.com"])
        assert result == f'(SINCE {self._today()} FROM "autausapl@gmail.com")'

    def test_two_senders_returns_or_chain(self):
        result = self._build(["a@x.com", "b@x.com"])
        assert result == f'(SINCE {self._today()} (OR FROM "a@x.com" FROM "b@x.com"))'

    def test_three_senders_returns_nested_or(self):
        result = self._build(["a@x.com", "b@x.com", "c@x.com"])
        assert result == f'(SINCE {self._today()} (OR FROM "a@x.com" (OR FROM "b@x.com" FROM "c@x.com")))'

    def test_four_senders_nested(self):
        result = self._build(["a@x.com", "b@x.com", "c@x.com", "d@x.com"])
        assert result == f'(SINCE {self._today()} (OR FROM "a@x.com" (OR FROM "b@x.com" (OR FROM "c@x.com" FROM "d@x.com"))))'

    def test_domain_only_falls_back_to_since(self):
        """Domain-only filters can't be expressed in IMAP FROM."""
        result = self._build(["@domain.com"])
        assert result == f"(SINCE {self._today()})"

    def test_mixed_domain_and_email(self):
        """Domain entries are excluded; only email addresses go to IMAP."""
        result = self._build(["user@x.com", "@domain.com"])
        assert result == f'(SINCE {self._today()} FROM "user@x.com")'

    def test_mixed_two_emails_one_domain(self):
        result = self._build(["a@x.com", "@domain.com", "b@x.com"])
        assert result == f'(SINCE {self._today()} (OR FROM "a@x.com" FROM "b@x.com"))'


# =============================================================================
# PDF Detection Tests
# =============================================================================


class TestPDFDetection:
    """Test that _parse_message detects PDFs correctly."""

    def _make_raw_email(self, attachments):
        """Build a raw email with given attachments.

        attachments: list of (filename, content_type, payload)
        """
        import email.mime.base
        import email.mime.multipart
        import email.mime.text

        msg = email.mime.multipart.MIMEMultipart()
        msg["From"] = "test@example.com"
        msg["Subject"] = "Test with attachments"
        msg["Message-ID"] = "<detect-test@example.com>"
        msg["Date"] = "Wed, 18 Feb 2026 12:00:00 -0500"
        msg.attach(email.mime.text.MIMEText("Body text"))

        for filename, content_type, payload in attachments:
            maintype, subtype = content_type.split("/", 1)
            part = email.mime.base.MIMEBase(maintype, subtype)
            part.set_payload(payload)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)

        return msg.as_bytes()

    def test_standard_pdf_content_type(self):
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        raw = self._make_raw_email([("invoice.pdf", "application/pdf", b"%PDF-1.4")])
        msg = worker._parse_message("1", raw)
        assert msg.has_pdf is True
        assert msg.pdf_filenames == ["invoice.pdf"]

    def test_octet_stream_with_pdf_extension(self):
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        raw = self._make_raw_email([("report.pdf", "application/octet-stream", b"%PDF-1.4")])
        msg = worker._parse_message("1", raw)
        assert msg.has_pdf is True
        assert msg.pdf_filenames == ["report.pdf"]

    def test_no_attachments_returns_empty(self):
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        raw = self._make_raw_email([])
        msg = worker._parse_message("1", raw)
        assert msg.has_pdf is False
        assert msg.pdf_filenames == []

    def test_non_pdf_attachment_ignored(self):
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        raw = self._make_raw_email([("photo.jpg", "image/jpeg", b"\xff\xd8")])
        msg = worker._parse_message("1", raw)
        assert msg.has_pdf is False

    def test_multiple_pdfs_detected(self):
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        raw = self._make_raw_email([
            ("invoice.pdf", "application/pdf", b"%PDF"),
            ("release.pdf", "application/octet-stream", b"%PDF"),
        ])
        msg = worker._parse_message("1", raw)
        assert msg.has_pdf is True
        assert len(msg.pdf_filenames) == 2


# =============================================================================
# Auto-Process Flow Tests (no rules configured)
# =============================================================================


class TestAutoProcessFlow:
    """Test that emails are auto-processed when no rules are configured."""

    def test_match_rule_returns_none_when_no_rules(self):
        from api.workers.email_worker import EmailMessage, EmailWorker
        worker = EmailWorker()
        msg = EmailMessage(
            message_id="<test@local>", uid="1", subject="Test",
            sender="a@x.com", date="2026-01-01", has_pdf=True,
            pdf_filenames=["doc.pdf"], raw_message=MagicMock(),
        )
        result = worker._match_rule(msg, [])
        assert result is None

    def test_match_rule_returns_rule_when_matched(self):
        from api.workers.email_worker import EmailMessage, EmailWorker
        worker = EmailWorker()
        msg = EmailMessage(
            message_id="<test@local>", uid="1", subject="Invoice from auction",
            sender="a@x.com", date="2026-01-01", has_pdf=True,
            pdf_filenames=["doc.pdf"], raw_message=MagicMock(),
        )
        rules = [{"name": "Auction", "enabled": True,
                   "condition_type": "subject_contains", "condition_value": "invoice",
                   "action": "process"}]
        result = worker._match_rule(msg, rules)
        assert result is not None
        assert result["name"] == "Auction"


# =============================================================================
# Thread Dedup Tests
# =============================================================================


class TestThreadDedup:
    """Test _is_thread_reply_without_pdf()."""

    def _make_msg(self, has_pdf, in_reply_to="", references=""):
        from api.workers.email_worker import EmailMessage
        raw = MagicMock()
        raw.get = MagicMock(side_effect=lambda h, d="": {
            "In-Reply-To": in_reply_to,
            "References": references,
        }.get(h, d))
        return EmailMessage(
            message_id="<test@local>",
            uid="1",
            subject="Test",
            sender="a@x.com",
            date="2026-01-01",
            has_pdf=has_pdf,
            pdf_filenames=["doc.pdf"] if has_pdf else [],
            raw_message=raw,
        )

    def test_reply_without_pdf_is_thread_reply(self):
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        msg = self._make_msg(has_pdf=False, in_reply_to="<orig@x.com>")
        assert worker._is_thread_reply_without_pdf(msg) is True

    def test_reply_with_pdf_is_processed(self):
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        msg = self._make_msg(has_pdf=True, in_reply_to="<orig@x.com>")
        assert worker._is_thread_reply_without_pdf(msg) is False

    def test_no_reply_header_is_processed(self):
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        msg = self._make_msg(has_pdf=False, in_reply_to="", references="")
        assert worker._is_thread_reply_without_pdf(msg) is False

    def test_references_only_is_thread_reply(self):
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        msg = self._make_msg(has_pdf=False, in_reply_to="", references="<ref1@x.com>")
        assert worker._is_thread_reply_without_pdf(msg) is True


# =============================================================================
# Email Log API Tests
# =============================================================================


class TestEmailLogAPI:
    """Test email log API endpoints using the shared e2e test client."""

    def _unique_id(self):
        return uuid.uuid4().hex[:8]

    def _seed_email_log(self, count=3, tag=None):
        """Insert test email_log rows directly. Returns list of message_ids."""
        from api.database import get_connection
        from api.routes.email_log import init_email_log_table
        init_email_log_table()

        tag = tag or self._unique_id()
        msg_ids = []
        with get_connection() as conn:
            for i in range(count):
                status = "processed" if i == 0 else ("skipped" if i == 1 else "failed")
                msg_id = f"<msg{i}_{tag}@test.com>"
                msg_ids.append(msg_id)
                conn.execute("""
                    INSERT INTO email_log
                    (message_id, sender, sender_name, subject, status, skip_reason,
                     has_attachments, attachment_count, attachment_names)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    msg_id,
                    f"sender{i}_{tag}@test.com",
                    f"Sender {i}",
                    f"Test Subject {i} {tag}",
                    status,
                    "No matching rule" if status == "skipped" else None,
                    True if i == 0 else False,
                    1 if i == 0 else 0,
                    '["invoice.pdf"]' if i == 0 else "[]",
                ))
            conn.commit()
        return msg_ids

    def test_get_email_log_returns_paginated(self, client):
        tag = self._unique_id()
        self._seed_email_log(5, tag)
        resp = client.get(f"/api/email-log/?sender={tag}&limit=3&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] == 5
        assert len(data["items"]) == 3

    def test_get_email_log_filter_by_status(self, client):
        tag = self._unique_id()
        self._seed_email_log(3, tag)
        # Filter by sender to isolate our test data, then check status
        resp = client.get(f"/api/email-log/?sender={tag}&status=processed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert all(item["status"] == "processed" for item in data["items"])

    def test_get_email_log_filter_by_sender(self, client):
        tag = self._unique_id()
        self._seed_email_log(3, tag)
        resp = client.get(f"/api/email-log/?sender=sender0_{tag}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_skip_email_updates_status(self, client):
        tag = self._unique_id()
        self._seed_email_log(1, tag)
        resp = client.get(f"/api/email-log/?sender={tag}")
        email_id = resp.json()["items"][0]["id"]

        resp = client.post(f"/api/email-log/{email_id}/skip")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["status"] == "skipped"

    def test_process_email_updates_status(self, client):
        from api.database import get_connection
        from api.routes.email_log import init_email_log_table
        init_email_log_table()

        tag = self._unique_id()
        with get_connection() as conn:
            conn.execute("""
                INSERT INTO email_log (message_id, sender, subject, status)
                VALUES (?, ?, ?, ?)
            """, (f"<new_{tag}@test.com>", f"test_{tag}@x.com", "Test", "new"))
            conn.commit()

        resp = client.get(f"/api/email-log/?sender={tag}&status=new")
        email_id = resp.json()["items"][0]["id"]

        resp = client.post(f"/api/email-log/{email_id}/process")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["status"] == "ready"

    def test_process_already_processed_returns_400(self, client):
        tag = self._unique_id()
        self._seed_email_log(1, tag)  # First entry is "processed"
        resp = client.get(f"/api/email-log/?sender={tag}&status=processed")
        email_id = resp.json()["items"][0]["id"]

        resp = client.post(f"/api/email-log/{email_id}/process")
        assert resp.status_code == 400

    def test_stats_returns_counts(self, client):
        """Stats endpoint returns valid structure with counts."""
        resp = client.get("/api/email-log/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "processed" in data
        assert "skipped" in data
        assert "failed" in data

    def test_duplicate_message_id_skipped(self, client):
        """Inserting duplicate message_id returns None from _insert_email_log."""
        from api.workers.email_worker import EmailWorker

        worker = EmailWorker()
        worker._init_email_log_table()

        tag = self._unique_id()
        msg = MagicMock()
        msg.message_id = f"<dup_{tag}@test.com>"
        msg.sender = "test@x.com"
        msg.subject = "Test"
        msg.date = "2026-01-01"
        msg.has_pdf = False
        msg.pdf_filenames = []
        msg.raw_message = MagicMock()
        msg.raw_message.get = MagicMock(return_value="")

        result1 = worker._insert_email_log(msg, body_preview="Hello")
        assert result1 is not None

        result2 = worker._insert_email_log(msg, body_preview="Hello")
        assert result2 is None

    def test_nonexistent_email_returns_404(self, client):
        resp = client.post("/api/email-log/9999/process")
        assert resp.status_code == 404

        resp = client.post("/api/email-log/9999/skip")
        assert resp.status_code == 404


# =============================================================================
# PDF Classification Tests (Day 13A)
# =============================================================================


class TestPDFClassification:
    """Test _classify_attachment() recognizes real-world filenames."""

    def _classify(self, filename):
        from api.workers.email_worker import EmailWorker
        return EmailWorker()._classify_attachment(filename)

    # Invoice patterns
    def test_invoice_by_filename(self):
        assert self._classify("Copart_Invoice_123.pdf") == "invoice"

    def test_invoice_bill_of_sale(self):
        assert self._classify("Bill_of_Sale_Feb2026.pdf") == "invoice"

    def test_invoice_buyer_receipt(self):
        assert self._classify("Buyer_Receipt.pdf") == "invoice"

    def test_for_auction_iaa(self):
        """IAA auction listing page should be classified as invoice."""
        assert self._classify("2024 HYUNDAI KONA LIMITED for Auction - IAA.pdf") == "invoice"

    def test_copart_listing(self):
        """Copart condition page with 'Copart' in name."""
        assert self._classify(
            "2023 FORD ESCAPE ST-LINE ELITE _ Run and Drive _ Feb 17, 2026 _ IL - CHICAGO _ Copart.pdf"
        ) == "invoice"

    # Condition report patterns
    def test_showreport_is_condition(self):
        """IAA's ShowReport is a condition report, NOT an invoice."""
        assert self._classify("ShowReport.pdf") == "condition_report"

    def test_showreport_numbered_is_condition(self):
        assert self._classify("ShowReport (1).pdf") == "condition_report"

    def test_showreport3_is_condition(self):
        assert self._classify("ShowReport3.pdf") == "condition_report"

    def test_condition_explicit(self):
        assert self._classify("Vehicle_Condition_Report.pdf") == "condition_report"

    def test_inspection_is_condition(self):
        assert self._classify("Inspection_Report.pdf") == "condition_report"

    def test_enhanced_vehicle_is_condition(self):
        assert self._classify("Enhanced Vehicles report.pdf") == "condition_report"

    # Vehicle release patterns
    def test_vehicle_release(self):
        assert self._classify("Vehicle_Release.pdf") == "vehicle_release"

    def test_release_document(self):
        assert self._classify("release_document.pdf") == "vehicle_release"

    # Unknown / fallback
    def test_generic_filename_unknown(self):
        assert self._classify("document.pdf") == "unknown"

    def test_attachment_unknown(self):
        assert self._classify("attachment.pdf") == "unknown"

    # Single PDF = invoice (via _classify_and_rank_attachments)
    def test_single_unknown_pdf_becomes_invoice(self):
        """When only one PDF and it's unknown, rank it as invoice."""
        from api.workers.email_worker import EmailMessage, EmailWorker

        worker = EmailWorker()
        msg = EmailMessage(
            message_id="<test@local>", uid="1", subject="Test",
            sender="a@x.com", date="2026-01-01", has_pdf=True,
            pdf_filenames=["document.pdf"], raw_message=MagicMock(),
        )
        classified = worker._classify_and_rank_attachments(msg)
        assert classified["invoice"] == ["document.pdf"]
        assert classified["condition_report"] == []

    # Two PDFs: invoice + condition (real-world IAA pattern)
    def test_iaa_invoice_and_showreport(self):
        """Real IAA email: 'for Auction - IAA.pdf' = invoice, 'ShowReport.pdf' = condition."""
        from api.workers.email_worker import EmailMessage, EmailWorker

        worker = EmailWorker()
        msg = EmailMessage(
            message_id="<test@local>", uid="1", subject="Test",
            sender="a@x.com", date="2026-01-01", has_pdf=True,
            pdf_filenames=[
                "2024 HYUNDAI KONA LIMITED for Auction - IAA.pdf",
                "ShowReport (1).pdf",
            ],
            raw_message=MagicMock(),
        )
        classified = worker._classify_and_rank_attachments(msg)
        assert classified["invoice"] == ["2024 HYUNDAI KONA LIMITED for Auction - IAA.pdf"]
        assert classified["condition_report"] == ["ShowReport (1).pdf"]

    def test_copart_invoice_and_condition(self):
        """Real Copart email pattern."""
        from api.workers.email_worker import EmailMessage, EmailWorker

        worker = EmailWorker()
        msg = EmailMessage(
            message_id="<test@local>", uid="1", subject="Test",
            sender="a@x.com", date="2026-01-01", has_pdf=True,
            pdf_filenames=[
                "invoice.pdf",
                "2023 FORD ESCAPE ST LINE SELECT _ Run and Drive _ Feb 17, 2026 _ OK - OKLAHOMA CITY _ Copart.pdf",
            ],
            raw_message=MagicMock(),
        )
        classified = worker._classify_and_rank_attachments(msg)
        assert "invoice.pdf" in classified["invoice"]
        assert classified["condition_report"] == []


# =============================================================================
# Email Safety Tests (Day 13A)
# =============================================================================


class TestEmailSafety:
    """Verify that the worker does NOT modify the mailbox."""

    def test_no_move_to_processed_method(self):
        """_move_to_processed should not exist as a callable method."""
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        assert not callable(getattr(worker, "_move_to_processed", None))

    def test_no_processed_folder_attribute(self):
        """Worker should not have a processed_folder attribute."""
        from api.workers.email_worker import EmailWorker
        worker = EmailWorker()
        assert not hasattr(worker, "processed_folder")

    def test_no_imap_store_in_source(self):
        """Source code should not contain imap.store() with FLAGS."""
        import inspect
        from api.workers import email_worker
        source = inspect.getsource(email_worker)
        # Check for dangerous IMAP operations
        assert "imap.store" not in source
        assert "imap.copy" not in source
        assert "imap.expunge" not in source
        assert "\\\\Deleted" not in source
        assert "\\\\Seen" not in source
