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
    """Test _build_search_criteria() generates correct IMAP SEARCH strings."""

    def _build(self, senders):
        from api.workers.email_worker import EmailWorker
        return EmailWorker._build_search_criteria(senders)

    def test_no_senders_returns_unseen(self):
        assert self._build([]) == "UNSEEN"

    def test_none_senders_returns_unseen(self):
        assert self._build([]) == "UNSEEN"

    def test_one_sender_returns_from_filter(self):
        result = self._build(["autausapl@gmail.com"])
        assert result == '(UNSEEN FROM "autausapl@gmail.com")'

    def test_two_senders_returns_or_chain(self):
        result = self._build(["a@x.com", "b@x.com"])
        assert result == '(UNSEEN (OR FROM "a@x.com" FROM "b@x.com"))'

    def test_three_senders_returns_nested_or(self):
        result = self._build(["a@x.com", "b@x.com", "c@x.com"])
        assert result == '(UNSEEN (OR FROM "a@x.com" (OR FROM "b@x.com" FROM "c@x.com")))'

    def test_four_senders_nested(self):
        result = self._build(["a@x.com", "b@x.com", "c@x.com", "d@x.com"])
        assert result == '(UNSEEN (OR FROM "a@x.com" (OR FROM "b@x.com" (OR FROM "c@x.com" FROM "d@x.com"))))'

    def test_domain_only_falls_back_to_unseen(self):
        """Domain-only filters can't be expressed in IMAP FROM."""
        result = self._build(["@domain.com"])
        assert result == "UNSEEN"

    def test_mixed_domain_and_email(self):
        """Domain entries are excluded; only email addresses go to IMAP."""
        result = self._build(["user@x.com", "@domain.com"])
        assert result == '(UNSEEN FROM "user@x.com")'

    def test_mixed_two_emails_one_domain(self):
        result = self._build(["a@x.com", "@domain.com", "b@x.com"])
        assert result == '(UNSEEN (OR FROM "a@x.com" FROM "b@x.com"))'


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
