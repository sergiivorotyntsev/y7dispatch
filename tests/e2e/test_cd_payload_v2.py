"""
Day 12 Tests: CD API V2 Payload Builder — Marketplaces, Tags, Terms, Payment Validation

Tests:
- Payload contains marketplaces[] array with public marketplace
- Payload contains tags[] array with automation metadata
- loadSpecificTerms populated from default template when no override
- Payment method enum validation (warn on invalid)
- Full V2 payload structure verification
- Sheets export column alignment
"""

import importlib
import json
import os
import uuid
from datetime import datetime

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def temp_database(tmp_path):
    """Use a temp database for each test."""
    db_path = str(tmp_path / "test_cd_payload_v2.db")
    os.environ["DATABASE_URL"] = db_path

    import api.database

    importlib.reload(api.database)

    from api.database import get_connection

    with get_connection() as conn:
        # Create core tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL UNIQUE,
                auction_type_id INTEGER NOT NULL,
                dataset_split TEXT NOT NULL,
                filename TEXT, raw_text TEXT, file_path TEXT,
                source TEXT DEFAULT 'upload', status TEXT DEFAULT 'pending',
                is_test_document BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auction_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL, auction_type_id INTEGER,
                uuid TEXT NOT NULL UNIQUE,
                status TEXT DEFAULT 'pending',
                method TEXT DEFAULT 'haiku', outputs_json TEXT,
                errors_json TEXT, extraction_cost REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL, source_key TEXT, internal_key TEXT,
                cd_key TEXT, predicted_value TEXT, corrected_value TEXT,
                is_match_ok BOOLEAN DEFAULT FALSE, export_field BOOLEAN DEFAULT TRUE,
                confidence REAL, status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES extraction_runs(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS training_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER, auction_type_id INTEGER, run_id INTEGER,
                field_key TEXT, predicted_value TEXT, gold_value TEXT,
                is_correct BOOLEAN, source_text_snippet TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

    # Initialize warehouses and warehouse_constants
    import api.routes.warehouses

    importlib.reload(api.routes.warehouses)
    api.routes.warehouses.init_warehouses_schema()

    from api.warehouse_constants import init_warehouse_constants_schema

    init_warehouse_constants_schema()

    yield db_path


def _create_test_run(auction_code="COPART"):
    """Create a minimal extraction run with standard fields for testing."""
    from api.database import get_connection

    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO auction_types (code, name) VALUES (?, ?)",
            (auction_code, auction_code.title()),
        )
        at_row = conn.execute(
            "SELECT id FROM auction_types WHERE code=?", (auction_code,)
        ).fetchone()
        at_id = at_row[0]

        doc_uuid = str(uuid.uuid4())[:8]
        cursor = conn.execute(
            "INSERT INTO documents (uuid, auction_type_id, dataset_split, filename, raw_text, source) VALUES (?, ?, 'test', 'test.pdf', 'test', 'upload')",
            (doc_uuid, at_id),
        )
        doc_id = cursor.lastrowid

        outputs = json.dumps(
            {
                "vehicle_vin": "1HGBH41JXMN109186",
                "vehicle_year": "2021",
                "vehicle_make": "Honda",
                "vehicle_model": "Civic",
                "vehicle_color": "White",
                "vehicle_lot": "12345678",
                "pickup_name": "Copart Clearwater",
                "pickup_address": "7701 N Hwy 301",
                "pickup_city": "Tampa",
                "pickup_state": "FL",
                "pickup_zip": "33637",
                "pickup_phone": "(813) 555-1234",
                "pickup_location_type": "AUCTION",
                "buyer_id": "535527",
            }
        )
        run_uuid = str(uuid.uuid4())[:8]
        cursor2 = conn.execute(
            """INSERT INTO extraction_runs (document_id, auction_type_id, uuid, status, outputs_json)
               VALUES (?, ?, ?, 'approved', ?)""",
            (doc_id, at_id, run_uuid, outputs),
        )
        run_id = cursor2.lastrowid

        # Create review items
        fields = [
            ("vehicle_vin", "1HGBH41JXMN109186"),
            ("vehicle_year", "2021"),
            ("vehicle_make", "Honda"),
            ("vehicle_model", "Civic"),
            ("vehicle_color", "White"),
            ("vehicle_lot", "12345678"),
            ("pickup_name", "Copart Clearwater"),
            ("pickup_address", "7701 N Hwy 301"),
            ("pickup_city", "Tampa"),
            ("pickup_state", "FL"),
            ("pickup_zip", "33637"),
            ("pickup_phone", "(813) 555-1234"),
            ("pickup_location_type", "AUCTION"),
            ("buyer_id", "535527"),
        ]
        for key, val in fields:
            conn.execute(
                """INSERT INTO review_items (run_id, source_key, predicted_value, corrected_value, is_match_ok, export_field, confidence)
                   VALUES (?, ?, ?, ?, 1, 1, 0.95)""",
                (run_id, key, val, val),
            )
        conn.commit()
    return run_id


# ── Test Class 1: Marketplaces Array ──────────────────────────────────────────


class TestMarketplacesArray:
    """Payload must include marketplaces[] with public marketplace."""

    def test_payload_has_marketplaces_key(self):
        """Payload includes 'marketplaces' key."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, errors = build_cd_payload(run_id, overrides=overrides)
        assert "marketplaces" in payload, "Payload must include 'marketplaces' array"

    def test_marketplaces_has_public_marketplace(self):
        """Marketplaces contains public marketplace with ID 10000."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        marketplaces = payload.get("marketplaces", [])
        assert len(marketplaces) >= 1
        assert marketplaces[0]["marketplaceId"] == 10000

    def test_marketplace_searchable_true(self):
        """Public marketplace is searchable by default."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        mp = payload["marketplaces"][0]
        assert mp.get("searchable") is True

    def _get_warehouse_id(self):
        from api.database import get_connection

        with get_connection() as conn:
            wh = conn.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
            return wh[0] if wh else None


# ── Test Class 2: Tags Array ─────────────────────────────────────────────────


class TestTagsArray:
    """Payload must include tags[] with automation metadata."""

    def _build_payload(self, auction_code="COPART"):
        from api.database import get_connection
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run(auction_code)
        with get_connection() as conn:
            wh = conn.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
            wh_id = wh[0] if wh else None

        overrides = OperatorOverrides(
            warehouse_id=wh_id,
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        return build_cd_payload(run_id, overrides=overrides)

    def test_payload_has_tags_key(self):
        """Payload includes 'tags' key."""
        payload, _ = self._build_payload()
        assert "tags" in payload, "Payload must include 'tags' array"

    def test_tags_has_automation_version(self):
        """Tags include automationVersion."""
        payload, _ = self._build_payload()
        tags = payload.get("tags", [])
        tag_keys = {t["key"] for t in tags}
        assert "automationVersion" in tag_keys

    def test_tags_has_source_system(self):
        """Tags include sourceSystem."""
        payload, _ = self._build_payload()
        tags = payload.get("tags", [])
        tag_keys = {t["key"] for t in tags}
        assert "sourceSystem" in tag_keys

    def test_tags_has_auction_source(self):
        """Tags include auctionSource with correct value."""
        payload, _ = self._build_payload("COPART")
        tags = payload.get("tags", [])
        auction_tag = next((t for t in tags if t["key"] == "auctionSource"), None)
        assert auction_tag is not None
        assert auction_tag["value"] == "COPART"

    def test_tags_different_auction_source(self):
        """Tags reflect correct auction source for IAA."""
        payload, _ = self._build_payload("IAA")
        tags = payload.get("tags", [])
        auction_tag = next((t for t in tags if t["key"] == "auctionSource"), None)
        assert auction_tag is not None
        assert auction_tag["value"] == "IAA"


# ── Test Class 3: Load-Specific Terms Template ──────────────────────────────


class TestLoadSpecificTermsTemplate:
    """loadSpecificTerms should have default template when no override."""

    def _get_warehouse_id(self):
        from api.database import get_connection

        with get_connection() as conn:
            wh = conn.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
            return wh[0] if wh else None

    def test_terms_default_when_no_override(self):
        """loadSpecificTerms populated from template when not overridden."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
            # NOTE: load_specific_terms is NOT set — should get default
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        terms = payload.get("loadSpecificTerms", "")
        # Should contain the template text
        assert "857-895-8777" in terms, "Default terms should include phone number"

    def test_terms_includes_pickup_name(self):
        """Default terms template includes pickup location name."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        terms = payload.get("loadSpecificTerms", "")
        assert "Copart Clearwater" in terms, "Terms should include pickup name"

    def test_terms_includes_warehouse_name(self):
        """Default terms template includes warehouse name."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        wh_id = self._get_warehouse_id()
        overrides = OperatorOverrides(
            warehouse_id=wh_id,
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        terms = payload.get("loadSpecificTerms", "")
        # Should contain some warehouse name
        assert "Warehouse" in terms or "warehouse" in terms.lower(), \
            "Terms should include warehouse/delivery location name"

    def test_terms_override_takes_precedence(self):
        """Explicit load_specific_terms override replaces template."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
            load_specific_terms="Custom terms from operator",
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        assert payload.get("loadSpecificTerms") == "Custom terms from operator"


# ── Test Class 4: Payment Method Validation ──────────────────────────────────


class TestPaymentMethodValidation:
    """Payment method values should be valid CD API enums."""

    VALID_PAYMENT_METHODS = {
        "CASH_CERTIFIED_FUNDS",
        "CERTIFIED_FUNDS",
        "CHECK",
        "WIRE_TRANSFER",
        "ACH",
        "COMCHECK",
        "COMPANY_CHECK",
        "CASH",
    }

    VALID_PAYMENT_TIMES = {
        "IMMEDIATELY",
        "TWO_BUSINESS_DAYS",
        "FIVE_BUSINESS_DAYS",
        "TEN_BUSINESS_DAYS",
        "FIFTEEN_BUSINESS_DAYS",
        "THIRTY_BUSINESS_DAYS",
    }

    VALID_TERMS_BEGIN = {
        "PICKUP",
        "DELIVERY",
        "RECEIVING_SIGNED_BOL",
    }

    def _get_warehouse_id(self):
        from api.database import get_connection

        with get_connection() as conn:
            wh = conn.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
            return wh[0] if wh else None

    def test_default_cod_payment_method_valid(self):
        """Default COD payment method is a valid CD enum."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        cod_method = payload["price"]["cod"]["paymentMethod"]
        assert cod_method in self.VALID_PAYMENT_METHODS, \
            f"COD payment method '{cod_method}' not in valid enums"

    def test_default_balance_payment_method_valid(self):
        """Default balance payment method is a valid CD enum."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        balance_method = payload["price"]["balance"]["balancePaymentMethod"]
        assert balance_method in self.VALID_PAYMENT_METHODS, \
            f"Balance payment method '{balance_method}' not in valid enums"

    def test_default_balance_payment_time_valid(self):
        """Default balance payment time is a valid CD enum."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        balance_time = payload["price"]["balance"]["paymentTime"]
        assert balance_time in self.VALID_PAYMENT_TIMES, \
            f"Balance payment time '{balance_time}' not in valid enums"

    def test_default_terms_begin_valid(self):
        """Default balance terms begin on is a valid CD enum."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        terms_begin = payload["price"]["balance"]["balancePaymentTermsBeginOn"]
        assert terms_begin in self.VALID_TERMS_BEGIN, \
            f"Terms begin '{terms_begin}' not in valid enums"


# ── Test Class 5: Full V2 Payload Structure ──────────────────────────────────


class TestFullV2PayloadStructure:
    """Verify complete CD API V2 payload has all required top-level keys."""

    def _get_warehouse_id(self):
        from api.database import get_connection

        with get_connection() as conn:
            wh = conn.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
            return wh[0] if wh else None

    def _build_full_payload(self):
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(
            warehouse_id=self._get_warehouse_id(),
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
            trailer_type="OPEN",
            requires_inspection=True,
            load_specific_terms="Custom terms",
            transport_special_instructions="Mon-Fri 8am-5pm",
        )
        return build_cd_payload(run_id, overrides=overrides)

    def test_required_top_level_keys(self):
        """Payload has all required top-level keys per CD V2 spec."""
        payload, errors = self._build_full_payload()
        required_keys = [
            "externalId",
            "trailerType",
            "hasInOpVehicle",
            "requiresInspection",
            "availableDate",
            "expirationDate",
            "price",
            "stops",
            "vehicles",
            "marketplaces",
        ]
        for key in required_keys:
            assert key in payload, f"Missing required key: {key}"

    def test_stops_have_two_entries(self):
        """Stops array has exactly 2 entries (pickup + delivery)."""
        payload, _ = self._build_full_payload()
        assert len(payload["stops"]) == 2

    def test_pickup_stop_number_is_1(self):
        """First stop is pickup with stopNumber=1."""
        payload, _ = self._build_full_payload()
        assert payload["stops"][0]["stopNumber"] == 1

    def test_delivery_stop_number_is_2(self):
        """Second stop is delivery with stopNumber=2."""
        payload, _ = self._build_full_payload()
        assert payload["stops"][1]["stopNumber"] == 2

    def test_vehicle_linked_to_stops(self):
        """Vehicle references correct stop numbers."""
        payload, _ = self._build_full_payload()
        vehicle = payload["vehicles"][0]
        assert vehicle["pickupStopNumber"] == 1
        assert vehicle["dropoffStopNumber"] == 2

    def test_price_has_required_structure(self):
        """Price has total, cod{}, and balance{} sub-objects."""
        payload, _ = self._build_full_payload()
        price = payload["price"]
        assert "total" in price
        assert "cod" in price
        assert "balance" in price
        assert price["total"] == 500.0

    def test_dates_in_iso_format(self):
        """Dates are ISO 8601 with T00:00:00Z suffix."""
        payload, _ = self._build_full_payload()
        assert payload["availableDate"].endswith("T00:00:00Z")
        assert payload["expirationDate"].endswith("T00:00:00Z")

    def test_vehicle_has_required_fields(self):
        """Vehicle entry has all required fields."""
        payload, _ = self._build_full_payload()
        vehicle = payload["vehicles"][0]
        assert vehicle["vin"] == "1HGBH41JXMN109186"
        assert vehicle["year"] == 2021
        assert vehicle["make"] == "Honda"
        assert vehicle["model"] == "Civic"

    def test_buyer_reference_in_pickup(self):
        """Pickup stop includes buyer reference number."""
        payload, _ = self._build_full_payload()
        pickup = payload["stops"][0]
        assert pickup.get("buyerReferenceNumber") == "535527"

    def test_optional_fields_present(self):
        """Optional fields (loadSpecificTerms, transportationReleaseNotes) included."""
        payload, _ = self._build_full_payload()
        assert "loadSpecificTerms" in payload
        assert "transportationReleaseNotes" in payload


# ── Test Class 6: User Corrections Override Extraction Data ──────────────────


class TestUserCorrectionsInExport:
    """Export must use user-corrected values from review_items over extracted values."""

    def test_corrected_pickup_address_in_payload(self):
        """When user corrects pickup_address, export uses corrected value."""
        from api.database import get_connection
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()

        # Simulate user correction: change pickup_address
        with get_connection() as conn:
            conn.execute(
                "UPDATE review_items SET corrected_value = ? WHERE run_id = ? AND source_key = 'pickup_address'",
                ("10 INDUSTRIAL DRIVE", run_id),
            )
            conn.commit()

        with get_connection() as conn:
            wh = conn.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
            wh_id = wh[0] if wh else None

        overrides = OperatorOverrides(
            warehouse_id=wh_id,
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        pickup = payload["stops"][0]
        assert pickup["address"] == "10 INDUSTRIAL DRIVE", (
            f"Expected corrected address '10 INDUSTRIAL DRIVE', got '{pickup['address']}'"
        )

    def test_corrected_city_in_payload(self):
        """When user corrects pickup_city, export uses corrected value."""
        from api.database import get_connection
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()

        with get_connection() as conn:
            conn.execute(
                "UPDATE review_items SET corrected_value = ? WHERE run_id = ? AND source_key = 'pickup_city'",
                ("NORTH SMITHFIELD", run_id),
            )
            conn.commit()

        with get_connection() as conn:
            wh = conn.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
            wh_id = wh[0] if wh else None

        overrides = OperatorOverrides(
            warehouse_id=wh_id,
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        pickup = payload["stops"][0]
        assert pickup["city"] == "NORTH SMITHFIELD"

    def test_uncorrected_fields_use_predicted_value(self):
        """Fields without corrections still use predicted (extracted) values."""
        from api.database import get_connection
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()

        with get_connection() as conn:
            wh = conn.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
            wh_id = wh[0] if wh else None

        overrides = OperatorOverrides(
            warehouse_id=wh_id,
            final_price=500.0,
            available_date=datetime.now().strftime("%Y-%m-%d"),
        )
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        pickup = payload["stops"][0]
        # Original predicted values should be used when no correction
        assert pickup["state"] == "FL"
        assert pickup["postalCode"] == "33637"


# ── Test Class 7: Copart Extraction Prompt ───────────────────────────────────


class TestCopartExtractionPrompt:
    """HaikuExtractor prompt must include Copart-specific address guidance."""

    def test_prompt_mentions_physical_address_of_lot(self):
        """Extraction prompt includes PHYSICAL ADDRESS OF LOT guidance for Copart."""
        from services.haiku_extractor import EXTRACTION_PROMPT

        assert "PHYSICAL ADDRESS OF LOT" in EXTRACTION_PROMPT, (
            "Extraction prompt must mention 'PHYSICAL ADDRESS OF LOT' for Copart documents"
        )

    def test_prompt_warns_against_member_address(self):
        """Extraction prompt warns not to use MEMBER/buyer mailing address."""
        from services.haiku_extractor import EXTRACTION_PROMPT

        assert "MEMBER" in EXTRACTION_PROMPT and "mailing" in EXTRACTION_PROMPT.lower(), (
            "Extraction prompt must warn against using MEMBER/buyer mailing address"
        )


# ── Test Class 8: Load ID Suffix ─────────────────────────────────────────────


class TestLoadIdSuffix:
    """Load ID must always include sequence suffix (1, 2, 3...)."""

    @pytest.fixture(autouse=True)
    def isolated_load_ids_db(self, tmp_path):
        """Use a completely isolated DB for load_id tests via DATABASE_PATH."""
        import importlib

        db_path = str(tmp_path / "test_load_ids.db")
        old_db_path = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = db_path

        import api.database
        importlib.reload(api.database)

        import api.routes.listings
        importlib.reload(api.routes.listings)
        api.routes.listings.init_load_ids_schema()

        yield db_path

        # Restore
        if old_db_path:
            os.environ["DATABASE_PATH"] = old_db_path
        else:
            os.environ.pop("DATABASE_PATH", None)
        importlib.reload(api.database)

    def test_first_load_id_has_suffix_1(self):
        """First load ID for a make/model/date must end with '1'."""
        from api.routes.listings import create_load_id

        result = create_load_id("Toyota", "Prius")
        assert result is not None
        load_id, seq = result
        assert seq == 1
        assert load_id.endswith("1"), f"First load_id should end with '1', got '{load_id}'"

    def test_second_load_id_has_suffix_2(self):
        """Second load ID for same make/model/date must end with '2'."""
        from api.routes.listings import create_load_id

        create_load_id("Toyota", "Prius")
        result2 = create_load_id("Toyota", "Prius")
        assert result2 is not None
        load_id2, seq2 = result2
        assert seq2 == 2
        assert load_id2.endswith("2"), f"Second load_id should end with '2', got '{load_id2}'"

    def test_consecutive_load_ids_share_base(self):
        """Consecutive load IDs for same make/model share the same base prefix."""
        from api.routes.listings import create_load_id

        load_id1, _ = create_load_id("Volvo", "XC90")
        load_id2, _ = create_load_id("Volvo", "XC90")
        # Both should share the base (everything except the trailing digit)
        base1 = load_id1[:-1]
        base2 = load_id2[:-1]
        assert base1 == base2, f"Base should match: '{base1}' vs '{base2}'"
        assert load_id1[-1] == "1" and load_id2[-1] == "2"


# ── Test Class 9: ExternalId Uses Load ID ────────────────────────────────────


class TestExternalIdUsesLoadId:
    """CD export externalId must use resolved load_id, not DC-{date} fallback."""

    def test_external_id_from_overrides(self):
        """externalId should use overrides.load_id when provided."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(load_id="226VOLXC1")
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        assert payload.get("externalId") == "226VOLXC1"

    def test_external_id_from_resolved_load_id(self):
        """externalId should use resolved load_id from review_items when no overrides."""
        from api.database import get_connection
        from api.routes.exports import build_cd_payload

        run_id = _create_test_run()
        # Add load_id to review_items (simulating extraction output)
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO review_items (run_id, source_key, predicted_value, export_field) VALUES (?, 'load_id', '226VOLXC1', 1)",
                (run_id,),
            )
            conn.commit()
        payload, _ = build_cd_payload(run_id)
        assert payload.get("externalId") == "226VOLXC1", (
            f"externalId should be resolved load_id '226VOLXC1', got '{payload.get('externalId')}'"
        )

    def test_external_id_from_outputs_json_load_id(self):
        """externalId should use load_id from outputs_json via auto-load when no overrides."""
        import json

        from api.database import get_connection
        from api.routes.exports import build_cd_payload

        run_id = _create_test_run()
        # Set load_id in outputs_json (simulating saved Review state)
        with get_connection() as conn:
            current = conn.execute(
                "SELECT outputs_json FROM extraction_runs WHERE id=?", (run_id,)
            ).fetchone()[0]
            outputs = json.loads(current)
            outputs["load_id"] = "226TOYCI1"
            conn.execute(
                "UPDATE extraction_runs SET outputs_json=? WHERE id=?",
                (json.dumps(outputs), run_id),
            )
            conn.commit()
        payload, _ = build_cd_payload(run_id)
        assert payload.get("externalId") == "226TOYCI1"

    def test_shipper_order_id_matches_external_id(self):
        """shipperOrderId must be the same as externalId (both use load_id)."""
        from api.routes.exports import OperatorOverrides, build_cd_payload

        run_id = _create_test_run()
        overrides = OperatorOverrides(load_id="226HONCI1")
        payload, _ = build_cd_payload(run_id, overrides=overrides)
        assert payload.get("shipperOrderId") == payload.get("externalId"), (
            f"shipperOrderId '{payload.get('shipperOrderId')}' should match externalId '{payload.get('externalId')}'"
        )
