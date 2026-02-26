"""
Tests for EmailReplier service and ReplyBodyBuilder.

Covers:
- HTML body generation (with/without sender name, warehouse address)
- send_confirmation success flow
- Idempotency (no duplicate sends)
- Error cases: no CD listing, no graph_message_id, Graph API errors
"""

import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_db(tmp_path):
    """Create a test SQLite database with all required tables."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # extraction_runs
    conn.execute("""
        CREATE TABLE extraction_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            status TEXT DEFAULT 'pending',
            outputs_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # cd_listings
    conn.execute("""
        CREATE TABLE cd_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL UNIQUE,
            cd_listing_id TEXT NOT NULL,
            etag TEXT,
            external_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES extraction_runs(id)
        )
    """)

    # warehouses
    conn.execute("""
        CREATE TABLE warehouses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            state TEXT NOT NULL,
            city TEXT,
            address TEXT,
            zip_code TEXT,
            phone TEXT,
            contact_name TEXT,
            contact_phone TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # email_log
    conn.execute("""
        CREATE TABLE email_log (
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
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            graph_message_id TEXT
        )
    """)

    # email_replies
    conn.execute("""
        CREATE TABLE email_replies (
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

    conn.commit()
    return conn


@pytest.fixture
def populated_db(test_db):
    """Populate test DB with typical data for a successful export scenario."""
    conn = test_db

    # Create warehouse
    conn.execute("""
        INSERT INTO warehouses (id, code, name, state, city, address, zip_code, phone, contact_name, contact_phone)
        VALUES (1, 'BRD1', 'Broadway Warehouse', 'NJ', 'Newark', '123 Broadway Ave', '07101', '555-123-4567', 'John Smith', '555-987-6543')
    """)

    # Create extraction run with warehouse_id in outputs (vehicle_vin is the real field name)
    conn.execute("""
        INSERT INTO extraction_runs (id, status, outputs_json)
        VALUES (42, 'exported', ?)
    """, (json.dumps({"warehouse_id": 1, "vehicle_vin": "1HGCM82633A123456"}),))

    # Create CD listing (external_id = our internal Load ID, cd_listing_id = CD's internal ID)
    conn.execute("""
        INSERT INTO cd_listings (run_id, cd_listing_id, external_id)
        VALUES (42, '304787159', '226HONAC1')
    """)

    # Create email_log entry
    conn.execute("""
        INSERT INTO email_log (id, message_id, sender, sender_name, subject, extraction_run_ids, graph_message_id, status)
        VALUES (10, '<test@example.com>', 'seller@auction.com', 'Jane Doe', 'Invoice #12345',
                ?, 'AAMkAGI1AAAoZCfHAAA=', 'processed')
    """, (json.dumps([42]),))

    conn.commit()
    return conn


def _patch_get_connection(monkeypatch, conn):
    """Monkey-patch get_connection to return our test connection."""
    from contextlib import contextmanager

    @contextmanager
    def mock_get_connection():
        yield conn

    monkeypatch.setattr("api.services.email_replier.get_connection", mock_get_connection)


# ---------------------------------------------------------------------------
# ReplyBodyBuilder Tests
# ---------------------------------------------------------------------------


class TestReplyBodyBuilder:
    def test_reply_body_has_listing_id(self):
        from api.services.email_replier import ReplyBodyBuilder

        html = ReplyBodyBuilder.build(
            load_id="226HONAC1",
            warehouse={"name": "Test WH", "address": "123 Main St", "city": "Newark",
                        "state": "NJ", "zip_code": "07101", "phone": "555-0000"},
            sender_name="John",
        )
        assert "226HONAC1" in html

    def test_reply_body_has_warehouse_address(self):
        from api.services.email_replier import ReplyBodyBuilder

        warehouse = {
            "name": "Broadway Warehouse",
            "address": "123 Broadway Ave",
            "city": "Newark",
            "state": "NJ",
            "zip_code": "07101",
            "phone": "555-123-4567",
        }
        html = ReplyBodyBuilder.build("CD-TEST", warehouse, "Jane")
        assert "Broadway Warehouse" in html
        assert "123 Broadway Ave" in html
        assert "Newark" in html
        assert "NJ" in html
        assert "07101" in html

    def test_reply_body_no_sender_name(self):
        from api.services.email_replier import ReplyBodyBuilder

        html = ReplyBodyBuilder.build(
            load_id="TEST-LOAD1",
            warehouse={"name": "WH", "address": "1 St", "city": "C", "state": "NJ", "zip_code": "07101"},
            sender_name=None,
        )
        assert "Hello," in html
        assert "Hello None" not in html

    def test_reply_body_with_sender_name(self):
        from api.services.email_replier import ReplyBodyBuilder

        html = ReplyBodyBuilder.build(
            load_id="TEST-LOAD1",
            warehouse={"name": "WH", "address": "1 St", "city": "C", "state": "NJ", "zip_code": "07101"},
            sender_name="John",
        )
        assert "Hello John," in html

    def test_reply_body_no_phone(self):
        from api.services.email_replier import ReplyBodyBuilder

        html = ReplyBodyBuilder.build(
            load_id="TEST-LOAD1",
            warehouse={"name": "WH", "address": "1 St", "city": "C", "state": "NJ", "zip_code": "07101"},
        )
        assert "Phone:" not in html

    def test_reply_body_has_status_text(self):
        from api.services.email_replier import ReplyBodyBuilder

        html = ReplyBodyBuilder.build("CD-TEST", {"name": "WH"})
        assert "Searching for carriers" in html

    def test_reply_body_has_signature(self):
        from api.services.email_replier import ReplyBodyBuilder

        html = ReplyBodyBuilder.build("CD-TEST", {"name": "WH"})
        assert "Y7 Agency" in html
        assert "Broadway Motoring" not in html

    def test_reply_body_has_vin(self):
        from api.services.email_replier import ReplyBodyBuilder

        html = ReplyBodyBuilder.build(
            "CD-TEST", {"name": "WH"}, vin="4T1BF1FK5EU123456",
        )
        assert "4T1BF1FK5EU123456" in html

    def test_reply_body_vin_empty_when_not_provided(self):
        from api.services.email_replier import ReplyBodyBuilder

        html = ReplyBodyBuilder.build("CD-TEST", {"name": "WH"})
        # VIN placeholder replaced with empty string
        assert "{{vin}}" not in html


# ---------------------------------------------------------------------------
# EmailReplier Tests
# ---------------------------------------------------------------------------


class TestSendConfirmationSuccess:
    def test_send_confirmation_success(self, populated_db, monkeypatch):
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        mock_graph = MagicMock()
        mock_graph.reply_to_message.return_value = {"success": True}

        replier = EmailReplier(mock_graph)
        result = replier.send_confirmation(42)

        assert result["success"] is True
        assert result["load_id"] == "226HONAC1"
        assert result["cd_listing_id"] == "304787159"
        assert result["replied_to"] == "seller@auction.com"

        # Verify reply record in DB (cd_listing_id column stores CD's internal ID)
        row = populated_db.execute(
            "SELECT status, cd_listing_id FROM email_replies WHERE run_id = 42"
        ).fetchone()
        assert row["status"] == "sent"
        assert row["cd_listing_id"] == "304787159"

        # Verify Graph API was called with correct args
        mock_graph.reply_to_message.assert_called_once()
        call_args = mock_graph.reply_to_message.call_args
        assert call_args[0][0] == "AAMkAGI1AAAoZCfHAAA="
        assert "226HONAC1" in call_args[0][1]  # HTML body contains our Load ID
        assert "1HGCM82633A123456" in call_args[0][1]  # HTML body contains VIN


class TestSendConfirmationIdempotent:
    def test_send_confirmation_idempotent(self, populated_db, monkeypatch):
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        mock_graph = MagicMock()
        mock_graph.reply_to_message.return_value = {"success": True}

        replier = EmailReplier(mock_graph)

        # First call — sends
        result1 = replier.send_confirmation(42)
        assert result1["success"] is True
        assert "already_sent" not in result1

        # Second call — idempotent
        result2 = replier.send_confirmation(42)
        assert result2["success"] is True
        assert result2.get("already_sent") is True

        # Graph API called only once
        assert mock_graph.reply_to_message.call_count == 1

        # Only one reply record
        count = populated_db.execute(
            "SELECT COUNT(*) as cnt FROM email_replies WHERE run_id = 42"
        ).fetchone()["cnt"]
        assert count == 1


class TestSendConfirmationNoCdListing:
    def test_send_confirmation_no_cd_listing(self, populated_db, monkeypatch):
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        # Delete CD listing
        populated_db.execute("DELETE FROM cd_listings WHERE run_id = 42")
        populated_db.commit()

        mock_graph = MagicMock()
        replier = EmailReplier(mock_graph)
        result = replier.send_confirmation(42)

        assert result["success"] is False
        assert "No CD listing" in result["error"]
        mock_graph.reply_to_message.assert_not_called()


class TestSendConfirmationNoGraphId:
    def test_send_confirmation_no_graph_id(self, populated_db, monkeypatch):
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        # Clear graph_message_id (simulating pre-migration email)
        populated_db.execute("UPDATE email_log SET graph_message_id = NULL WHERE id = 10")
        populated_db.commit()

        mock_graph = MagicMock()
        mock_graph.resolve_graph_message_id.return_value = None  # resolve fails
        replier = EmailReplier(mock_graph)
        result = replier.send_confirmation(42)

        assert result["success"] is False
        assert "not found in mailbox" in result["error"]
        mock_graph.reply_to_message.assert_not_called()


class TestSendConfirmationGraphApiError:
    def test_send_confirmation_graph_api_error(self, populated_db, monkeypatch):
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        mock_graph = MagicMock()
        mock_graph.reply_to_message.return_value = {
            "success": False,
            "error": "HTTP 403: Insufficient privileges",
        }

        replier = EmailReplier(mock_graph)
        result = replier.send_confirmation(42)

        assert result["success"] is False
        assert "403" in result["error"]

        # Verify failed status in DB
        row = populated_db.execute(
            "SELECT status, error_message FROM email_replies WHERE run_id = 42"
        ).fetchone()
        assert row["status"] == "failed"
        assert "403" in row["error_message"]


class TestSendConfirmationNoWarehouse:
    def test_send_confirmation_no_warehouse(self, populated_db, monkeypatch):
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        # Remove warehouse_id from outputs
        populated_db.execute(
            "UPDATE extraction_runs SET outputs_json = ? WHERE id = 42",
            (json.dumps({"vehicle_vin": "1HGCM82633A123456"}),),
        )
        populated_db.commit()

        mock_graph = MagicMock()
        replier = EmailReplier(mock_graph)
        result = replier.send_confirmation(42)

        assert result["success"] is False
        assert "No warehouse" in result["error"]


class TestSendConfirmationNoEmailLog:
    def test_send_confirmation_no_email_log(self, populated_db, monkeypatch):
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        # Remove email_log entry
        populated_db.execute("DELETE FROM email_log")
        populated_db.commit()

        mock_graph = MagicMock()
        replier = EmailReplier(mock_graph)
        result = replier.send_confirmation(42)

        assert result["success"] is False
        assert "email_log" in result["error"].lower()


# ---------------------------------------------------------------------------
# Preview Confirmation Tests
# ---------------------------------------------------------------------------


class TestPreviewConfirmation:
    def test_preview_confirmation_success(self, populated_db, monkeypatch):
        """Preview returns rendered HTML + recipient metadata."""
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        replier = EmailReplier(graph_reader=None)
        result = replier.preview_confirmation(42)

        assert result["success"] is True
        assert "226HONAC1" in result["preview_html"]
        assert "1HGCM82633A123456" in result["preview_html"]
        assert result["recipient_email"] == "seller@auction.com"
        assert result["recipient_name"] == "Jane Doe"
        assert result["subject"] == "Invoice #12345"
        assert result["load_id"] == "226HONAC1"
        assert result["vin"] == "1HGCM82633A123456"
        assert result["warehouse_name"] == "Broadway Warehouse"
        assert result["has_graph_id"] is True

    def test_preview_confirmation_no_cd_listing(self, populated_db, monkeypatch):
        """Run without CD export returns error."""
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        populated_db.execute("DELETE FROM cd_listings WHERE run_id = 42")
        populated_db.commit()

        replier = EmailReplier(graph_reader=None)
        result = replier.preview_confirmation(42)

        assert result["success"] is False
        assert "No CD listing" in result["error"]

    def test_preview_confirmation_no_graph_id(self, populated_db, monkeypatch):
        """Preview works even without graph_message_id (only needed for sending)."""
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        populated_db.execute("UPDATE email_log SET graph_message_id = NULL WHERE id = 10")
        populated_db.commit()

        replier = EmailReplier(graph_reader=None)
        result = replier.preview_confirmation(42)

        assert result["success"] is True
        assert "226HONAC1" in result["preview_html"]
        assert result["has_graph_id"] is False

    def test_gather_reply_data_reused(self, populated_db, monkeypatch):
        """send_confirmation and preview_confirmation produce the same HTML."""
        _patch_get_connection(monkeypatch, populated_db)
        from api.services.email_replier import EmailReplier

        # Get preview HTML
        replier_preview = EmailReplier(graph_reader=None)
        preview_result = replier_preview.preview_confirmation(42)
        assert preview_result["success"] is True

        # Get send HTML (capture from Graph API call)
        mock_graph = MagicMock()
        mock_graph.reply_to_message.return_value = {"success": True}
        replier_send = EmailReplier(mock_graph)
        replier_send.send_confirmation(42)

        call_args = mock_graph.reply_to_message.call_args
        send_html = call_args[0][1]

        assert preview_result["preview_html"] == send_html


# ---------------------------------------------------------------------------
# Template System Tests
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    def test_render_simple_placeholders(self):
        from api.services.email_replier import ReplyBodyBuilder

        template = "<p>{{greeting}}</p><p>Load: {{load_id}}</p>"
        result = ReplyBodyBuilder.render_template(template, {
            "greeting": "Hello John,",
            "load_id": "226TOYPR1",
        })
        assert result == "<p>Hello John,</p><p>Load: 226TOYPR1</p>"

    def test_render_all_warehouse_variables(self):
        from api.services.email_replier import ReplyBodyBuilder

        template = "{{warehouse_name}} at {{warehouse_full_address}} {{warehouse_phone_line}}"
        variables = ReplyBodyBuilder._build_variables(
            "CD-X", {"name": "WH1", "address": "1 St", "city": "NYC", "state": "NY", "zip_code": "10001", "phone": "555-0000"},
            sender_name="Jane",
        )
        result = ReplyBodyBuilder.render_template(template, variables)
        assert "WH1" in result
        assert "1 St, NYC, NY 10001" in result
        assert "555-0000" in result

    def test_render_missing_placeholder_preserved(self):
        from api.services.email_replier import ReplyBodyBuilder

        template = "<p>{{greeting}}</p><p>{{unknown_var}}</p>"
        result = ReplyBodyBuilder.render_template(template, {"greeting": "Hi,"})
        assert "Hi," in result
        assert "{{unknown_var}}" in result  # Unmatched placeholders stay


class TestBuildVariables:
    def test_build_variables_with_sender_name(self):
        from api.services.email_replier import ReplyBodyBuilder

        variables = ReplyBodyBuilder._build_variables(
            "CD-123", {"name": "WH", "address": "1 St", "city": "C", "state": "NJ", "zip_code": "07101"},
            sender_name="Alice",
        )
        assert variables["greeting"] == "Hello Alice,"
        assert variables["sender_name"] == "Alice"
        assert variables["load_id"] == "CD-123"
        assert variables["warehouse_name"] == "WH"
        assert variables["warehouse_full_address"] == "1 St, C, NJ 07101"

    def test_build_variables_no_sender_name(self):
        from api.services.email_replier import ReplyBodyBuilder

        variables = ReplyBodyBuilder._build_variables("CD-X", {"name": "WH"}, sender_name=None)
        assert variables["greeting"] == "Hello,"
        assert variables["sender_name"] == ""

    def test_build_variables_phone_line_present(self):
        from api.services.email_replier import ReplyBodyBuilder

        variables = ReplyBodyBuilder._build_variables("CD-X", {"name": "WH", "phone": "555-1234"})
        assert "555-1234" in variables["warehouse_phone_line"]
        assert "Phone:" in variables["warehouse_phone_line"]

    def test_build_variables_phone_line_empty(self):
        from api.services.email_replier import ReplyBodyBuilder

        variables = ReplyBodyBuilder._build_variables("CD-X", {"name": "WH"})
        assert variables["warehouse_phone_line"] == ""

    def test_build_variables_vin(self):
        from api.services.email_replier import ReplyBodyBuilder

        variables = ReplyBodyBuilder._build_variables(
            "CD-X", {"name": "WH"}, vin="4T1BF1FK5EU123456",
        )
        assert variables["vin"] == "4T1BF1FK5EU123456"

    def test_build_variables_vin_empty(self):
        from api.services.email_replier import ReplyBodyBuilder

        variables = ReplyBodyBuilder._build_variables("CD-X", {"name": "WH"})
        assert variables["vin"] == ""

    def test_build_variables_company_name_fallback(self):
        """Company sender_name → plain Hello (no email extraction)."""
        from api.services.email_replier import ReplyBodyBuilder

        variables = ReplyBodyBuilder._build_variables(
            "CD-X", {"name": "WH"}, sender_name="Import USA",
        )
        assert variables["greeting"] == "Hello,"

    def test_build_variables_person_name_first_name_only(self):
        """Person sender_name uses first name only in greeting."""
        from api.services.email_replier import ReplyBodyBuilder

        variables = ReplyBodyBuilder._build_variables(
            "CD-X", {"name": "WH"}, sender_name="Jane Doe",
        )
        assert variables["greeting"] == "Hello Jane,"


class TestTemplateFromDB:
    def _create_email_templates_table(self, conn):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_key TEXT UNIQUE NOT NULL,
                subject_template TEXT,
                body_html TEXT NOT NULL,
                description TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_by TEXT,
                version INTEGER DEFAULT 1
            )
        """)
        conn.commit()

    def test_build_from_db_template(self, test_db, monkeypatch):
        """Template loaded from DB, variables substituted correctly."""
        _patch_get_connection(monkeypatch, test_db)
        self._create_email_templates_table(test_db)

        test_db.execute(
            "INSERT INTO email_templates (template_key, body_html) VALUES (?, ?)",
            ("reply_confirmation", "<p>{{greeting}}</p><p>CUSTOM Load: {{load_id}}</p><p>WH: {{warehouse_name}}</p>"),
        )
        test_db.commit()

        from api.services.email_replier import ReplyBodyBuilder

        html = ReplyBodyBuilder.build("226CUSTOM", {"name": "Broadway WH"}, sender_name="Bob")
        assert "CUSTOM Load: 226CUSTOM" in html
        assert "Hello Bob," in html
        assert "Broadway WH" in html

    def test_build_fallback_no_template(self, test_db, monkeypatch):
        """No email_templates table in DB → uses hardcoded fallback."""
        _patch_get_connection(monkeypatch, test_db)

        from api.services.email_replier import ReplyBodyBuilder

        # No email_templates table → _load_template() returns None → fallback
        html = ReplyBodyBuilder.build("CD-FALL", {"name": "WH"}, sender_name="Eve")
        assert "CD-FALL" in html
        assert "Hello Eve," in html
        assert "Y7 Agency" in html  # Fallback includes signature

    def test_build_fallback_empty_template(self, test_db, monkeypatch):
        """body_html is empty string in DB → treated as falsy, uses fallback."""
        _patch_get_connection(monkeypatch, test_db)
        self._create_email_templates_table(test_db)

        test_db.execute(
            "INSERT INTO email_templates (template_key, body_html) VALUES (?, ?)",
            ("reply_confirmation", ""),
        )
        test_db.commit()

        from api.services.email_replier import ReplyBodyBuilder

        html = ReplyBodyBuilder.build("CD-EMPTY", {"name": "WH"}, sender_name="Alice")
        assert "CD-EMPTY" in html
        assert "Hello Alice," in html
        assert "Y7 Agency" in html  # Fallback includes signature


def _patch_get_connection_all(monkeypatch, conn):
    """Patch get_connection in both email_replier and email_log modules."""
    from contextlib import contextmanager

    @contextmanager
    def mock_get_connection():
        yield conn

    monkeypatch.setattr("api.services.email_replier.get_connection", mock_get_connection)
    monkeypatch.setattr("api.routes.email_log.get_connection", mock_get_connection)


class TestSeedDefaultTemplates:
    _TEMPLATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS email_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_key TEXT UNIQUE NOT NULL,
            subject_template TEXT,
            body_html TEXT NOT NULL,
            description TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_by TEXT,
            version INTEGER DEFAULT 1
        )
    """

    def test_seed_creates_template(self, test_db, monkeypatch):
        _patch_get_connection_all(monkeypatch, test_db)

        test_db.execute(self._TEMPLATE_TABLE_SQL)
        test_db.commit()

        from api.routes.email_log import seed_default_templates
        seed_default_templates()

        row = test_db.execute(
            "SELECT template_key, body_html, description, version FROM email_templates WHERE template_key = 'reply_confirmation'"
        ).fetchone()
        assert row is not None
        assert "{{load_id}}" in row["body_html"]
        assert "{{greeting}}" in row["body_html"]
        assert "{{vin}}" in row["body_html"]
        assert "Confirmation email" in row["description"]
        assert row["version"] == 2
        # v2 template uses table-based layout
        assert "<table" in row["body_html"]
        assert "We will notify" not in row["body_html"]

    def test_seed_migrates_v1_to_v2(self, test_db, monkeypatch):
        """Seed upgrades v1 template to v2 redesigned HTML."""
        _patch_get_connection_all(monkeypatch, test_db)

        test_db.execute(self._TEMPLATE_TABLE_SQL)
        # Insert v1 template (old style)
        test_db.execute(
            "INSERT INTO email_templates (template_key, body_html, description, version) VALUES (?, ?, ?, 1)",
            ("reply_confirmation",
             "<p>{{greeting}}</p><p>{{load_id}}</p><p>Y7 Agency</p>",
             "Confirmation email"),
        )
        test_db.commit()

        from api.routes.email_log import seed_default_templates
        seed_default_templates()

        row = test_db.execute(
            "SELECT body_html, version FROM email_templates WHERE template_key = 'reply_confirmation'"
        ).fetchone()
        assert row["version"] == 2
        assert "<table" in row["body_html"]  # v2 uses table layout
        assert "{{load_id}}" in row["body_html"]
        assert "{{vin}}" in row["body_html"]
        assert "We will notify" not in row["body_html"]

    def test_seed_preserves_user_edited_v2(self, test_db, monkeypatch):
        """Seed does NOT overwrite template already at version 2."""
        _patch_get_connection_all(monkeypatch, test_db)

        test_db.execute(self._TEMPLATE_TABLE_SQL)
        custom_html = "<p>{{greeting}}</p><p>Custom user template {{load_id}}</p>"
        test_db.execute(
            "INSERT INTO email_templates (template_key, body_html, description, version) VALUES (?, ?, ?, 2)",
            ("reply_confirmation", custom_html, "Confirmation email"),
        )
        test_db.commit()

        from api.routes.email_log import seed_default_templates
        seed_default_templates()

        row = test_db.execute(
            "SELECT body_html, version FROM email_templates WHERE template_key = 'reply_confirmation'"
        ).fetchone()
        assert row["body_html"] == custom_html  # NOT overwritten
        assert row["version"] == 2

    def test_seed_is_idempotent(self, test_db, monkeypatch):
        _patch_get_connection_all(monkeypatch, test_db)

        test_db.execute(self._TEMPLATE_TABLE_SQL)
        test_db.commit()

        from api.routes.email_log import seed_default_templates
        seed_default_templates()
        seed_default_templates()  # Second call — should not duplicate

        count = test_db.execute(
            "SELECT COUNT(*) as cnt FROM email_templates WHERE template_key = 'reply_confirmation'"
        ).fetchone()["cnt"]
        assert count == 1


# ---------------------------------------------------------------------------
# Template API Endpoint Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def template_db(tmp_path, monkeypatch):
    """Test DB with email_templates table seeded with default template."""
    db_path = tmp_path / "tmpl_test.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("""
        CREATE TABLE email_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_key TEXT UNIQUE NOT NULL,
            subject_template TEXT,
            body_html TEXT NOT NULL,
            description TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_by TEXT,
            version INTEGER DEFAULT 1
        )
    """)
    from api.routes.email_log import _DEFAULT_REPLY_CONFIRMATION_HTML
    conn.execute(
        "INSERT INTO email_templates (template_key, body_html, description) VALUES (?, ?, ?)",
        ("reply_confirmation", _DEFAULT_REPLY_CONFIRMATION_HTML, "Confirmation email"),
    )
    conn.commit()

    from contextlib import contextmanager

    @contextmanager
    def mock_conn():
        yield conn

    monkeypatch.setattr("api.routes.email_templates.get_connection", mock_conn)
    monkeypatch.setattr("api.services.email_replier.get_connection", mock_conn)
    return conn


class TestTemplateGetEndpoint:
    def test_get_template(self, template_db):
        from fastapi.testclient import TestClient
        from api.routes.email_templates import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/email-templates/reply_confirmation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["template_key"] == "reply_confirmation"
        assert "{{load_id}}" in data["body_html"]
        assert data["description"] == "Confirmation email"
        assert isinstance(data["available_variables"], list)
        assert any(v["key"] == "load_id" for v in data["available_variables"])
        assert any(v["key"] == "greeting" for v in data["available_variables"])
        assert any(v["key"] == "vin" for v in data["available_variables"])


class TestTemplatePutEndpoint:
    def _make_client(self):
        from fastapi.testclient import TestClient
        from api.routes.email_templates import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_update_template(self, template_db):
        client = self._make_client()
        new_html = "<p>{{greeting}}</p><p>Load: {{load_id}}</p>"
        resp = client.put("/api/email-templates/reply_confirmation", json={"body_html": new_html})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify in DB
        row = template_db.execute(
            "SELECT body_html FROM email_templates WHERE template_key = 'reply_confirmation'"
        ).fetchone()
        assert row["body_html"] == new_html

    def test_update_template_validation(self, template_db):
        """PUT without {{load_id}} → 400; empty → 400; too long → 400."""
        client = self._make_client()

        # Empty body
        resp = client.put("/api/email-templates/reply_confirmation", json={"body_html": ""})
        assert resp.status_code == 400

        # Missing required placeholder
        resp = client.put("/api/email-templates/reply_confirmation", json={"body_html": "<p>No load id</p>"})
        assert resp.status_code == 400
        assert "load_id" in resp.json()["detail"]

        # Too long
        huge = "{{load_id}}" + "x" * 50001
        resp = client.put("/api/email-templates/reply_confirmation", json={"body_html": huge})
        assert resp.status_code == 400
        assert "too long" in resp.json()["detail"]


class TestTemplatePreviewEndpoint:
    def test_preview_template(self, template_db):
        from fastapi.testclient import TestClient
        from api.routes.email_templates import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        template = "<p>{{greeting}}</p><p>Load: {{load_id}}</p><p>VIN: {{vin}}</p><p>WH: {{warehouse_name}}</p>"
        resp = client.post("/api/email-templates/reply_confirmation/preview", json={"body_html": template})
        assert resp.status_code == 200
        html = resp.json()["preview_html"]
        assert "Hello John," in html
        assert "226TOYPR1" in html
        assert "4T1BF1FK5EU123456" in html
        assert "NJ Warehouse" in html


class TestTemplateResetEndpoint:
    def test_reset_template(self, template_db):
        from fastapi.testclient import TestClient
        from api.routes.email_templates import router
        from api.routes.email_log import _DEFAULT_REPLY_CONFIRMATION_HTML
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # First modify the template
        client.put("/api/email-templates/reply_confirmation", json={
            "body_html": "<p>Custom {{load_id}}</p>"
        })

        # Then reset
        resp = client.post("/api/email-templates/reply_confirmation/reset")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify it's back to default
        row = template_db.execute(
            "SELECT body_html FROM email_templates WHERE template_key = 'reply_confirmation'"
        ).fetchone()
        assert row["body_html"] == _DEFAULT_REPLY_CONFIRMATION_HTML


# ---------------------------------------------------------------------------
# Graph Message ID Resolution Tests
# ---------------------------------------------------------------------------


class TestResolveGraphMessageId:
    def test_resolve_graph_message_id_success(self):
        """GraphEmailReader.resolve_graph_message_id returns Graph ID from API."""
        from unittest.mock import patch, MagicMock
        from ingest.email_reader import GraphEmailReader, EmailConfig

        config = MagicMock(spec=EmailConfig)
        config.address = "test@example.com"
        reader = GraphEmailReader(config)
        reader._access_token = "fake-token"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": [{"id": "AAMkAGI1RESOLVED"}]
        }

        with patch("requests.get", return_value=mock_response) as mock_get:
            result = reader.resolve_graph_message_id("<test-msg@example.com>")

        assert result == "AAMkAGI1RESOLVED"
        # Graph API expects angle brackets in internetMessageId filter
        call_params = mock_get.call_args[1]["params"]
        assert "<test-msg@example.com>" in call_params["$filter"]

    def test_resolve_adds_angle_brackets_if_missing(self):
        """resolve_graph_message_id adds angle brackets when not present."""
        from unittest.mock import patch, MagicMock
        from ingest.email_reader import GraphEmailReader, EmailConfig

        config = MagicMock(spec=EmailConfig)
        config.address = "test@example.com"
        reader = GraphEmailReader(config)
        reader._access_token = "fake-token"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": [{"id": "AAMkRESOLVED"}]
        }

        # Pass without angle brackets
        with patch("requests.get", return_value=mock_response) as mock_get:
            result = reader.resolve_graph_message_id("test-msg@example.com")

        assert result == "AAMkRESOLVED"
        call_params = mock_get.call_args[1]["params"]
        assert "<test-msg@example.com>" in call_params["$filter"]

    def test_resolve_graph_message_id_not_found(self):
        """resolve_graph_message_id returns None when email not in mailbox."""
        from unittest.mock import patch, MagicMock
        from ingest.email_reader import GraphEmailReader, EmailConfig

        config = MagicMock(spec=EmailConfig)
        config.address = "test@example.com"
        reader = GraphEmailReader(config)
        reader._access_token = "fake-token"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"value": []}

        with patch("requests.get", return_value=mock_response):
            result = reader.resolve_graph_message_id("<gone@example.com>")

        assert result is None


class TestSendWithGraphResolve:
    def test_send_confirmation_resolves_null_graph_id(self, populated_db, monkeypatch):
        """send_confirmation resolves graph_message_id when NULL in email_log."""
        _patch_get_connection(monkeypatch, populated_db)

        # Set graph_message_id to NULL (pre-migration email)
        populated_db.execute("UPDATE email_log SET graph_message_id = NULL WHERE id = 10")
        populated_db.commit()

        from api.services.email_replier import EmailReplier

        mock_graph = MagicMock()
        mock_graph.resolve_graph_message_id.return_value = "AAMkRESOLVED123"
        mock_graph.reply_to_message.return_value = {"success": True}

        replier = EmailReplier(mock_graph)
        result = replier.send_confirmation(42)

        assert result["success"] is True
        assert result["load_id"] == "226HONAC1"

        # Verify resolve was called with RFC822 message_id
        mock_graph.resolve_graph_message_id.assert_called_once_with("<test@example.com>")

        # Verify reply was called with resolved Graph ID
        mock_graph.reply_to_message.assert_called_once()
        assert mock_graph.reply_to_message.call_args[0][0] == "AAMkRESOLVED123"

        # Verify graph_message_id was cached in email_log
        row = populated_db.execute(
            "SELECT graph_message_id FROM email_log WHERE id = 10"
        ).fetchone()
        assert row["graph_message_id"] == "AAMkRESOLVED123"

    def test_send_confirmation_resolve_fails(self, populated_db, monkeypatch):
        """send_confirmation fails gracefully when Graph resolve returns None."""
        _patch_get_connection(monkeypatch, populated_db)

        populated_db.execute("UPDATE email_log SET graph_message_id = NULL WHERE id = 10")
        populated_db.commit()

        from api.services.email_replier import EmailReplier

        mock_graph = MagicMock()
        mock_graph.resolve_graph_message_id.return_value = None

        replier = EmailReplier(mock_graph)
        result = replier.send_confirmation(42)

        assert result["success"] is False
        assert "not found in mailbox" in result["error"]
        mock_graph.reply_to_message.assert_not_called()

    def test_preview_works_without_graph_id(self, populated_db, monkeypatch):
        """preview_confirmation works even when graph_message_id is NULL."""
        _patch_get_connection(monkeypatch, populated_db)

        populated_db.execute("UPDATE email_log SET graph_message_id = NULL WHERE id = 10")
        populated_db.commit()

        from api.services.email_replier import EmailReplier

        replier = EmailReplier(graph_reader=None)
        result = replier.preview_confirmation(42)

        assert result["success"] is True
        assert "226HONAC1" in result["preview_html"]
        assert result["has_graph_id"] is False
