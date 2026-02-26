"""
E2E Tests — DAY 10: Review Page Restructure + Load ID + Manheim Logic

Tests for:
- Load ID generation algorithm and sequencing
- Manheim release date field parsing in extraction prompt
- Load-specific terms template variable substitution
- Default payment/listing field values
"""

import os
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def temp_database(tmp_path):
    """Use a temporary database for all tests."""
    db_path = str(tmp_path / "test.db")
    with patch.dict(os.environ, {"DATABASE_PATH": db_path}):
        # Re-import to pick up new path
        import importlib
        import api.database as db_mod
        importlib.reload(db_mod)

        # Re-init listings schema against temp DB
        from api.routes.listings import init_load_ids_schema
        init_load_ids_schema()

        yield db_path


@pytest.fixture
def client(temp_database):
    """TestClient that uses the temp database."""
    import importlib
    import api.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


# ===========================================================================
# Test Load ID Generation
# ===========================================================================

class TestLoadIdGeneration:
    """Load ID format: M(no leading zero) + DD + first3Make(upper) + first2Model(upper)"""

    def test_basic_format(self, client):
        """216TOYPR for Toyota Prius on Feb 16."""
        now = datetime.now()
        resp = client.get("/api/listings/generate-load-id?make=Toyota&model=Prius")
        assert resp.status_code == 200
        data = resp.json()

        month = str(now.month)
        day = now.strftime("%d")
        expected = f"{month}{day}TOYPR"
        assert data["load_id"] == expected
        assert data["make"] == "Toyota"
        assert data["model"] == "Prius"
        assert data["sequence"] == 1

    def test_no_leading_zero_month(self, client):
        """Month should not have leading zero (e.g., '2' not '02')."""
        resp = client.get("/api/listings/generate-load-id?make=Honda&model=Civic")
        assert resp.status_code == 200
        load_id = resp.json()["load_id"]
        # First character(s) before day should be month without leading zero
        now = datetime.now()
        assert load_id.startswith(str(now.month))

    def test_uppercase_make_model(self, client):
        """Make and model parts should be uppercase."""
        resp = client.get("/api/listings/generate-load-id?make=toyota&model=prius")
        assert resp.status_code == 200
        load_id = resp.json()["load_id"]
        # Extract the make/model portion (after month+day)
        now = datetime.now()
        prefix_len = len(str(now.month)) + 2  # month (no leading 0) + 2-digit day
        suffix = load_id[prefix_len:]
        assert suffix == "TOYPR"

    def test_short_model_name(self, client):
        """Short model names (< 2 chars) should use what's available."""
        resp = client.get("/api/listings/generate-load-id?make=BMW&model=X5")
        assert resp.status_code == 200
        data = resp.json()
        now = datetime.now()
        expected = f"{now.month}{now.strftime('%d')}BMWX5"
        assert data["load_id"] == expected

    def test_make_truncated_to_3(self, client):
        """Make longer than 3 chars is truncated."""
        resp = client.get("/api/listings/generate-load-id?make=Mercedes&model=Sprinter")
        assert resp.status_code == 200
        load_id = resp.json()["load_id"]
        now = datetime.now()
        expected = f"{now.month}{now.strftime('%d')}MERSP"
        assert load_id == expected

    def test_model_truncated_to_2(self, client):
        """Model longer than 2 chars is truncated."""
        resp = client.get("/api/listings/generate-load-id?make=Ford&model=Mustang")
        assert resp.status_code == 200
        load_id = resp.json()["load_id"]
        now = datetime.now()
        expected = f"{now.month}{now.strftime('%d')}FORMU"
        assert load_id == expected

    def test_missing_make_returns_422(self, client):
        """Missing required 'make' parameter returns validation error."""
        resp = client.get("/api/listings/generate-load-id?model=Prius")
        assert resp.status_code == 422

    def test_missing_model_returns_422(self, client):
        """Missing required 'model' parameter returns validation error."""
        resp = client.get("/api/listings/generate-load-id?make=Toyota")
        assert resp.status_code == 422


class TestLoadIdSequence:
    """Duplicate Load ID handling: second same vehicle gets suffix '2'."""

    def test_second_same_vehicle_gets_suffix_2(self, client):
        """Second Toyota Prius on same day appends '2'."""
        resp1 = client.get("/api/listings/generate-load-id?make=Toyota&model=Prius")
        resp2 = client.get("/api/listings/generate-load-id?make=Toyota&model=Prius")

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        data1 = resp1.json()
        data2 = resp2.json()

        assert data1["sequence"] == 1
        assert data2["sequence"] == 2
        assert data2["load_id"] == data1["load_id"] + "2"

    def test_third_same_vehicle_gets_suffix_3(self, client):
        """Third same vehicle gets suffix '3'."""
        client.get("/api/listings/generate-load-id?make=Audi&model=Q5")
        client.get("/api/listings/generate-load-id?make=Audi&model=Q5")
        resp3 = client.get("/api/listings/generate-load-id?make=Audi&model=Q5")

        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["sequence"] == 3

        now = datetime.now()
        expected = f"{now.month}{now.strftime('%d')}AUDQ53"
        assert data3["load_id"] == expected

    def test_different_vehicles_no_conflict(self, client):
        """Different make/model combinations don't interfere."""
        resp1 = client.get("/api/listings/generate-load-id?make=Honda&model=Accord")
        resp2 = client.get("/api/listings/generate-load-id?make=Ford&model=Focus")

        data1 = resp1.json()
        data2 = resp2.json()

        assert data1["sequence"] == 1
        assert data2["sequence"] == 1
        assert data1["load_id"] != data2["load_id"]

    def test_same_make_different_model_no_conflict(self, client):
        """Same make but different model gets separate sequence."""
        resp1 = client.get("/api/listings/generate-load-id?make=Toyota&model=Camry")
        resp2 = client.get("/api/listings/generate-load-id?make=Toyota&model=Corolla")

        data1 = resp1.json()
        data2 = resp2.json()

        # TOYCA vs TOYCO — different base IDs
        assert data1["sequence"] == 1
        assert data2["sequence"] == 1
        assert data1["load_id"] != data2["load_id"]


# ===========================================================================
# Test Manheim Release Date Parsing (Extraction Prompt)
# ===========================================================================

class TestManheimReleaseDateParsing:
    """Verify EXTRACTION_PROMPT includes Manheim release date fields."""

    def test_prompt_includes_manheim_release_date_field(self):
        """EXTRACTION_PROMPT should list manheim_release_date as a field to extract."""
        from services.haiku_extractor import EXTRACTION_PROMPT
        assert "manheim_release_date" in EXTRACTION_PROMPT

    def test_prompt_includes_manheim_offsite_field(self):
        """EXTRACTION_PROMPT should list manheim_offsite as a field to extract."""
        from services.haiku_extractor import EXTRACTION_PROMPT
        assert "manheim_offsite" in EXTRACTION_PROMPT

    def test_prompt_includes_offsite_address_fields(self):
        """EXTRACTION_PROMPT should include offsite pickup address fields."""
        from services.haiku_extractor import EXTRACTION_PROMPT
        assert "offsite_pickup_address" in EXTRACTION_PROMPT
        assert "offsite_pickup_city" in EXTRACTION_PROMPT
        assert "offsite_pickup_state" in EXTRACTION_PROMPT
        assert "offsite_pickup_zip" in EXTRACTION_PROMPT

    def test_prompt_includes_available_now_guidance(self):
        """Prompt should describe AVAILABLE_NOW state."""
        from services.haiku_extractor import EXTRACTION_PROMPT
        assert "AVAILABLE_NOW" in EXTRACTION_PROMPT

    def test_prompt_includes_no_release_document_guidance(self):
        """Prompt should describe NO_RELEASE_DOCUMENT state."""
        from services.haiku_extractor import EXTRACTION_PROMPT
        assert "NO_RELEASE_DOCUMENT" in EXTRACTION_PROMPT

    def test_prompt_includes_onsite_vehicle_release_keyword(self):
        """Prompt should reference ONSITE VEHICLE RELEASE section."""
        from services.haiku_extractor import EXTRACTION_PROMPT
        assert "ONSITE VEHICLE RELEASE" in EXTRACTION_PROMPT

    def test_prompt_includes_inoperable_field(self):
        """EXTRACTION_PROMPT should list vehicle_is_inoperable."""
        from services.haiku_extractor import EXTRACTION_PROMPT
        assert "vehicle_is_inoperable" in EXTRACTION_PROMPT

    def test_prompt_includes_inoperable_keywords(self):
        """Prompt should list inoperable detection keywords."""
        from services.haiku_extractor import EXTRACTION_PROMPT
        assert "INOP" in EXTRACTION_PROMPT
        assert "NON-RUNNING" in EXTRACTION_PROMPT
        assert "RUN AND DRIVE" in EXTRACTION_PROMPT

    def test_manheim_example_has_release_date(self):
        """Manheim example in EXTRACTION_PROMPT should show a release date."""
        from services.haiku_extractor import EXTRACTION_PROMPT
        # The Manheim example should include a concrete date
        assert '"manheim_release_date":"2026-02-03"' in EXTRACTION_PROMPT

    def test_system_prompt_includes_manheim_rules(self):
        """SYSTEM_PROMPT should mention Manheim release date handling."""
        from services.haiku_extractor import HaikuExtractor
        assert "manheim" in HaikuExtractor.SYSTEM_PROMPT.lower() or \
               "Manheim" in HaikuExtractor.SYSTEM_PROMPT


# ===========================================================================
# Test Load-Specific Terms Template
# ===========================================================================

class TestLoadSpecificTermsTemplate:
    """Template auto-fill: TEXT 857-895-8777 (ZELLE ...), Pick-up - {pickup}, Delivery - {warehouse}."""

    def test_template_includes_phone_number(self):
        """Template should include the contact phone number."""
        template = "TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY). Pick-up location - {pickup_name}, Delivery - {warehouse_name}"
        assert "857-895-8777" in template

    def test_template_variable_substitution(self):
        """Variables should be substitutable."""
        template = "TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY). Pick-up location - {pickup_name}, Delivery - {warehouse_name}"
        result = template.format(
            pickup_name="Copart Riverview",
            warehouse_name="Boston Warehouse"
        )
        assert "Copart Riverview" in result
        assert "Boston Warehouse" in result
        assert "857-895-8777" in result

    def test_template_handles_auction_name(self):
        """Template with auction name substitution."""
        template = "TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY). Pick-up location - {pickup_name}, Delivery - {warehouse_name}"
        result = template.format(
            pickup_name="Manheim Portland",
            warehouse_name="Y7 West"
        )
        assert "Manheim Portland" in result
        assert "Y7 West" in result


# ===========================================================================
# Test Default Payment Fields
# ===========================================================================

class TestDefaultPaymentFields:
    """Verify listing_fields.py defines correct defaults for payment/listing fields."""

    def test_cod_default_zero(self):
        """COD amount should default to '0'."""
        from api.listing_fields import LISTING_FIELDS
        cod_field = next(f for f in LISTING_FIELDS if f.key == "cod_amount")
        assert cod_field.default_value == "0"

    def test_trailer_type_field_exists(self):
        """Trailer type field should exist in field registry."""
        from api.listing_fields import LISTING_FIELDS
        field = next((f for f in LISTING_FIELDS if f.key == "trailer_type"), None)
        assert field is not None

    def test_balance_payment_method_default(self):
        """Balance payment method should default to CERTIFIED_FUNDS."""
        from api.listing_fields import LISTING_FIELDS
        field = next(f for f in LISTING_FIELDS if f.key == "balance_payment_method")
        assert field.default_value == "CERTIFIED_FUNDS"

    def test_balance_payment_time_default(self):
        """Balance payment time should default to TWO_BUSINESS_DAYS (CD API V2 format)."""
        from api.listing_fields import LISTING_FIELDS
        field = next(f for f in LISTING_FIELDS if f.key == "balance_payment_time")
        assert field.default_value == "TWO_BUSINESS_DAYS"

    def test_balance_terms_begin_on_default(self):
        """Balance terms begin on should default to RECEIVING_SIGNED_BOL."""
        from api.listing_fields import LISTING_FIELDS
        field = next(f for f in LISTING_FIELDS if f.key == "balance_terms_begin_on")
        assert field.default_value == "RECEIVING_SIGNED_BOL"

    def test_requires_inspection_default_true(self):
        """Requires inspection should default to 'true'."""
        from api.listing_fields import LISTING_FIELDS
        field = next(f for f in LISTING_FIELDS if f.key == "requires_inspection")
        assert field.default_value == "true"

    def test_cod_payment_method_default(self):
        """COD payment method should default to CASH_CERTIFIED_FUNDS."""
        from api.listing_fields import LISTING_FIELDS
        field = next(f for f in LISTING_FIELDS if f.key == "cod_payment_method")
        assert field.default_value == "CASH_CERTIFIED_FUNDS"

    def test_cod_payment_location_default(self):
        """COD payment location should default to DELIVERY."""
        from api.listing_fields import LISTING_FIELDS
        field = next(f for f in LISTING_FIELDS if f.key == "cod_payment_location")
        assert field.default_value == "DELIVERY"

    def test_vehicle_is_inoperable_default_false(self):
        """Vehicle inoperable should default to 'false'."""
        from api.listing_fields import LISTING_FIELDS
        field = next(f for f in LISTING_FIELDS if f.key == "vehicle_is_inoperable")
        assert field.default_value == "false"

    def test_manheim_release_date_field_exists(self):
        """Manheim release date field should be in the registry."""
        from api.listing_fields import LISTING_FIELDS
        field = next((f for f in LISTING_FIELDS if f.key == "manheim_release_date"), None)
        assert field is not None

    def test_load_id_not_editable(self):
        """Load ID should not be editable in review UI."""
        from api.listing_fields import LISTING_FIELDS
        field = next(f for f in LISTING_FIELDS if f.key == "load_id")
        assert field.editable_in_review is False


# ===========================================================================
# Test Load ID Recalculation
# ===========================================================================

class TestLoadIdRecalculation:
    """POST /api/listings/recalculate-load-id/{run_id} endpoint."""

    @pytest.fixture(autouse=True)
    def _ensure_extraction_runs_table(self, temp_database):
        """Ensure extraction_runs table exists for all tests in this class."""
        conn = sqlite3.connect(temp_database)
        conn.execute("CREATE TABLE IF NOT EXISTS extraction_runs (id INTEGER PRIMARY KEY, document_id INTEGER, status TEXT DEFAULT 'completed', outputs_json TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.commit()
        conn.close()

    def _insert_run(self, db_path, run_id, make, model, load_id=None):
        """Helper: insert a fake extraction_run with outputs_json."""
        import json
        outputs = {"vehicle_make": make, "vehicle_model": model}
        if load_id:
            outputs["load_id"] = load_id
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO extraction_runs (id, document_id, status, outputs_json) VALUES (?, 1, 'completed', ?)",
            (run_id, json.dumps(outputs)),
        )
        conn.commit()
        conn.close()

    def test_recalculate_generates_new_load_id(self, client, temp_database):
        """Recalculate should generate a fresh load_id and update the run."""
        import json
        self._insert_run(temp_database, 999, "Toyota", "Camry")
        resp = client.post("/api/listings/recalculate-load-id/999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == 999
        assert data["make"] == "Toyota"
        assert data["model"] == "Camry"
        now = datetime.now()
        expected_prefix = f"{now.month}{now.strftime('%d')}TOYCA"
        assert data["new_load_id"].startswith(expected_prefix)

    def test_recalculate_removes_old_load_id(self, client, temp_database):
        """Old load_id should be removed from load_ids table after recalculate."""
        # First generate a load_id
        resp1 = client.get("/api/listings/generate-load-id?make=Ford&model=Focus")
        old_id = resp1.json()["load_id"]

        # Insert run with that load_id
        self._insert_run(temp_database, 888, "Ford", "Focus", load_id=old_id)

        # Recalculate
        resp2 = client.post("/api/listings/recalculate-load-id/888")
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["old_load_id"] == old_id
        # New load_id should be generated (sequence resets since old was deleted)
        assert data["new_load_id"] is not None

    def test_recalculate_nonexistent_run_returns_404(self, client):
        """Recalculate for non-existent run returns 404."""
        resp = client.post("/api/listings/recalculate-load-id/99999")
        assert resp.status_code == 404

    def test_recalculate_run_without_make_model_returns_400(self, client, temp_database):
        """Run missing make/model returns 400."""
        import json
        conn = sqlite3.connect(temp_database)
        conn.execute("CREATE TABLE IF NOT EXISTS extraction_runs (id INTEGER PRIMARY KEY, document_id INTEGER, status TEXT DEFAULT 'completed', outputs_json TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute(
            "INSERT INTO extraction_runs (id, document_id, status, outputs_json) VALUES (777, 1, 'completed', ?)",
            (json.dumps({"some_field": "value"}),),
        )
        conn.commit()
        conn.close()
        resp = client.post("/api/listings/recalculate-load-id/777")
        assert resp.status_code == 400
        assert "vehicle_make" in resp.json()["detail"]

    def test_recalculate_updates_outputs_json(self, client, temp_database):
        """After recalculate, outputs_json in DB should have the new load_id."""
        import json
        self._insert_run(temp_database, 666, "Jeep", "Grand Cherokee", load_id="OLD123")
        resp = client.post("/api/listings/recalculate-load-id/666")
        assert resp.status_code == 200
        new_id = resp.json()["new_load_id"]

        # Verify in DB
        conn = sqlite3.connect(temp_database)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT outputs_json FROM extraction_runs WHERE id = 666").fetchone()
        conn.close()
        outputs = json.loads(row["outputs_json"])
        assert outputs["load_id"] == new_id
