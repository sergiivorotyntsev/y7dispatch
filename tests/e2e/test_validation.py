"""
E2E Tests — VIN Decode + Pickup Address Validation

Tests cover:
  - VIN decoder (decode, validate, invalid VIN, timeout, cache)
  - Address validator (directory match, wrong address, zip mismatch, unknown auction, invalid zip)
  - API endpoints (validate run, get cached result, run not found)
  - Integration (extraction → auto-validation, mismatch detection)
"""

import json
import time
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module", autouse=True)
def _ensure_validation_tables():
    """Ensure validation tables exist (startup event may not fire in TestClient)."""
    from api.routes.validation import init_validation_schema
    init_validation_schema()


# Sample NHTSA response for a valid VIN
NHTSA_RESPONSE_PORSCHE = {
    "Results": [
        {"Variable": "Make", "Value": "PORSCHE"},
        {"Variable": "Model", "Value": "CAYENNE"},
        {"Variable": "Model Year", "Value": "2018"},
        {"Variable": "Body Class", "Value": "Sport Utility Vehicle (SUV)"},
        {"Variable": "Error Code", "Value": "0"},
        {"Variable": "Error Text", "Value": "0 - VIN decoded clean"},
        {"Variable": "Plant Country", "Value": "GERMANY"},
    ]
}

NHTSA_RESPONSE_SUBARU = {
    "Results": [
        {"Variable": "Make", "Value": "SUBARU"},
        {"Variable": "Model", "Value": "BRZ"},
        {"Variable": "Model Year", "Value": "2023"},
        {"Variable": "Body Class", "Value": "Coupe"},
        {"Variable": "Error Code", "Value": "0"},
        {"Variable": "Error Text", "Value": "0 - VIN decoded clean"},
    ]
}


# ═══════════════════════════════════════════════════════════════
# VIN DECODER TESTS
# ═══════════════════════════════════════════════════════════════

class TestVINDecoder:
    """Test VIN decode and vehicle validation."""

    def test_decode_valid_vin(self):
        """Mock NHTSA response → parse correctly."""
        from api.services.vin_decoder import VINDecoder

        decoder = VINDecoder()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = NHTSA_RESPONSE_PORSCHE
        mock_resp.raise_for_status = MagicMock()

        with patch("api.services.vin_decoder.httpx.get", return_value=mock_resp):
            # Clear cache first
            with patch.object(decoder, "_get_cached", return_value=None):
                with patch.object(decoder, "_save_cache"):
                    result = decoder.decode("WP1AA2A58JLB06122")

        assert result["valid"] is True
        assert result["make"] == "PORSCHE"
        assert result["model"] == "CAYENNE"
        assert result["year"] == "2018"
        assert result["error_code"] == "0"

    def test_validate_vehicle_match(self):
        """All fields match → all 'verified'."""
        from api.services.vin_decoder import VINDecoder

        decoder = VINDecoder()
        decoded = {
            "valid": True, "year": "2018", "make": "PORSCHE", "model": "CAYENNE",
            "body_class": "SUV", "error_code": "0", "error_text": None, "raw_response": None,
        }
        with patch.object(decoder, "decode", return_value=decoded):
            result = decoder.validate_vehicle("WP1AA2A58JLB06122", "2018", "PORSCHE", "CAYENNE")

        assert result["vin_valid"] is True
        assert result["fields"]["vin"]["status"] == "verified"
        assert result["fields"]["year"]["status"] == "verified"
        assert result["fields"]["make"]["status"] == "verified"
        assert result["fields"]["model"]["status"] == "verified"
        assert result["error"] is None

    def test_validate_vehicle_mismatch_make(self):
        """Make doesn't match → 'mismatch'."""
        from api.services.vin_decoder import VINDecoder

        decoder = VINDecoder()
        decoded = {
            "valid": True, "year": "2018", "make": "PORSCHE", "model": "CAYENNE",
            "body_class": "SUV", "error_code": "0", "error_text": None, "raw_response": None,
        }
        with patch.object(decoder, "decode", return_value=decoded):
            result = decoder.validate_vehicle("WP1AA2A58JLB06122", "2018", "TOYOTA", "CAYENNE")

        assert result["fields"]["make"]["status"] == "mismatch"
        assert result["fields"]["make"]["decoded"] == "PORSCHE"
        assert result["fields"]["make"]["extracted"] == "TOYOTA"

    def test_validate_vehicle_chevy_alias(self):
        """CHEVY should match CHEVROLET."""
        from api.services.vin_decoder import VINDecoder

        decoder = VINDecoder()
        decoded = {
            "valid": True, "year": "2020", "make": "CHEVROLET", "model": "MALIBU",
            "body_class": "Sedan", "error_code": "0", "error_text": None, "raw_response": None,
        }
        with patch.object(decoder, "decode", return_value=decoded):
            result = decoder.validate_vehicle("1G1ZD5ST5LF000009", "2020", "CHEVY", "MALIBU")

        assert result["fields"]["make"]["status"] == "verified"

    def test_decode_invalid_vin_short(self):
        """VIN < 17 chars → vin_valid=False."""
        from api.services.vin_decoder import VINDecoder

        decoder = VINDecoder()
        result = decoder.decode("ABC123")

        assert result["valid"] is False
        assert result["error_code"] == "FORMAT"

    def test_decode_timeout(self):
        """NHTSA timeout → all 'unverified'."""
        import httpx
        from api.services.vin_decoder import VINDecoder

        decoder = VINDecoder()
        with patch("api.services.vin_decoder.httpx.get", side_effect=httpx.TimeoutException("timeout")):
            with patch.object(decoder, "_get_cached", return_value=None):
                result = decoder.validate_vehicle("WP1AA2A58JLB06122", "2018", "PORSCHE", "CAYENNE")

        assert result["vin_valid"] is None
        assert result["fields"]["vin"]["status"] == "unverified"
        assert result["fields"]["year"]["status"] == "unverified"
        assert result["error"] == "NHTSA API timeout"

    def test_cache_hit(self, tmp_path):
        """Second call should use cache."""
        from api.services.vin_decoder import VINDecoder

        decoder = VINDecoder()
        cached_data = {
            "valid": True, "year": "2023", "make": "SUBARU", "model": "BRZ",
            "body_class": "Coupe", "error_code": "0", "error_text": None,
        }
        with patch.object(decoder, "_get_cached", return_value=cached_data):
            result = decoder.decode("JF1ZNBF18P8758268")

        assert result["make"] == "SUBARU"
        assert result["model"] == "BRZ"

    def test_validate_model_partial_match(self):
        """Partial model match: 'CAMRY' vs 'CAMRY LE' → verified."""
        from api.services.vin_decoder import VINDecoder

        decoder = VINDecoder()
        decoded = {
            "valid": True, "year": "2022", "make": "TOYOTA", "model": "CAMRY LE",
            "body_class": "Sedan", "error_code": "0", "error_text": None, "raw_response": None,
        }
        with patch.object(decoder, "decode", return_value=decoded):
            result = decoder.validate_vehicle("JTDKN3DU5A0000001", "2022", "TOYOTA", "CAMRY")

        assert result["fields"]["model"]["status"] == "verified"


# ═══════════════════════════════════════════════════════════════
# ADDRESS VALIDATOR TESTS
# ═══════════════════════════════════════════════════════════════

class TestAddressValidator:
    """Test pickup address validation against directory + ZIP."""

    def test_validate_copart_directory_match(self):
        """ZIP 02822 → Copart Exeter, all 'verified'."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()
        with patch.object(validator, "_lookup_zip", return_value={"city": "Exeter", "state": "RI"}):
            result = validator.validate("COPART", {
                "pickup_name": "Copart Exeter",
                "pickup_address": "10 Industrial Dr",
                "pickup_city": "Exeter",
                "pickup_state": "RI",
                "pickup_zip": "02822",
            })

        assert result["directory_match"] is True
        assert result["fields"]["pickup_name"]["status"] == "verified"
        assert result["fields"]["pickup_address"]["status"] == "verified"
        assert result["fields"]["pickup_city"]["status"] == "verified"
        assert result["fields"]["pickup_state"]["status"] == "verified"
        assert result["fields"]["pickup_zip"]["status"] == "verified"

    def test_validate_copart_wrong_address(self):
        """Directory address differs from extracted → 'mismatch'."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()
        with patch.object(validator, "_lookup_zip", return_value={"city": "Exeter", "state": "RI"}):
            result = validator.validate("COPART", {
                "pickup_name": "Copart Exeter",
                "pickup_address": "77 FITCHBURG ROAD",  # wrong address
                "pickup_city": "Exeter",
                "pickup_state": "RI",
                "pickup_zip": "02822",
            })

        assert result["directory_match"] is True
        assert result["fields"]["pickup_address"]["status"] == "mismatch"
        assert result["fields"]["pickup_address"]["directory"] == "10 Industrial Dr"

    def test_validate_zip_city_mismatch(self):
        """ZIP 02822 + city AYER → city mismatch via ZIP cross-check."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()
        # Directory won't match because AYER is not in directory for 02822
        with patch.object(validator, "_lookup_zip", return_value={"city": "Exeter", "state": "RI"}):
            result = validator.validate("IAA", {  # IAA so no directory match
                "pickup_name": "IAA Unknown",
                "pickup_address": "123 Main St",
                "pickup_city": "AYER",
                "pickup_state": "MA",
                "pickup_zip": "02822",
            })

        # State should be mismatch (02822 is RI, not MA)
        assert result["fields"]["pickup_state"]["status"] == "mismatch"
        assert "RI" in (result["fields"]["pickup_state"].get("message") or "")

    def test_validate_unknown_auction_type(self):
        """Unknown auction type → no directory, all 'unverified', ZIP check still works."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()
        with patch.object(validator, "_lookup_zip", return_value={"city": "Boston", "state": "MA"}):
            result = validator.validate("UNKNOWN_AUCTION", {
                "pickup_name": "Some Place",
                "pickup_address": "123 Main St",
                "pickup_city": "Boston",
                "pickup_state": "MA",
                "pickup_zip": "02101",
            })

        assert result["directory_match"] is False
        assert result["fields"]["pickup_name"]["status"] == "unverified"

    def test_validate_invalid_zip_format(self):
        """Non-5-digit ZIP → 'mismatch'."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()
        with patch.object(validator, "_lookup_zip", return_value=None):
            result = validator.validate("COPART", {
                "pickup_name": "Test",
                "pickup_address": "123 Main",
                "pickup_city": "City",
                "pickup_state": "FL",
                "pickup_zip": "ABCDE",
            })

        assert result["fields"]["pickup_zip"]["status"] == "mismatch"
        assert "Invalid ZIP" in result["fields"]["pickup_zip"].get("message", "")


# ═══════════════════════════════════════════════════════════════
# API ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════

class TestValidationAPI:
    """Test validation API endpoints."""

    def _create_test_run(self, client, outputs):
        """Helper: create a test document + extraction run with given outputs.

        Uses minimal schema to avoid conflicts with other test modules that
        create simplified versions of the tables.
        """
        import uuid
        from api.database import get_connection

        with get_connection() as conn:
            # Ensure auction_types exists (minimal — other tests may have created extraction_runs without it)
            conn.execute("""CREATE TABLE IF NOT EXISTS auction_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE,
                is_base BOOLEAN DEFAULT FALSE, is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

            # Get or create COPART auction type
            at = conn.execute("SELECT id FROM auction_types WHERE code = 'COPART'").fetchone()
            if not at:
                conn.execute("INSERT INTO auction_types (name, code, is_base, is_active) VALUES ('Copart', 'COPART', 1, 1)")
                conn.commit()
                at = conn.execute("SELECT id FROM auction_types WHERE code = 'COPART'").fetchone()
            at_id = at["id"]

            # Ensure documents table exists (minimal)
            conn.execute("""CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT NOT NULL,
                filename TEXT NOT NULL, file_path TEXT, auction_type_id INTEGER,
                dataset_split TEXT DEFAULT 'test', is_test BOOLEAN DEFAULT FALSE,
                source TEXT DEFAULT 'test_lab', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

            # Ensure extraction_runs has needed columns (check if auction_type_id exists)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(extraction_runs)").fetchall()}
            if "auction_type_id" not in cols:
                try:
                    conn.execute("ALTER TABLE extraction_runs ADD COLUMN auction_type_id INTEGER")
                except Exception:
                    pass
            if "uuid" not in cols:
                try:
                    conn.execute("ALTER TABLE extraction_runs ADD COLUMN uuid TEXT")
                except Exception:
                    pass
            if "extractor_kind" not in cols:
                try:
                    conn.execute("ALTER TABLE extraction_runs ADD COLUMN extractor_kind TEXT DEFAULT 'rule'")
                except Exception:
                    pass

            # Create test document
            doc_uuid = uuid.uuid4().hex
            run_uuid = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO documents (uuid, filename, file_path, auction_type_id, dataset_split, is_test, source) VALUES (?, ?, ?, ?, 'test', 1, 'test_lab')",
                (doc_uuid, f"test_{time.time()}.pdf", "/tmp/test.pdf", at_id),
            )
            doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Create extraction run
            conn.execute(
                "INSERT INTO extraction_runs (uuid, document_id, auction_type_id, extractor_kind, status, outputs_json) VALUES (?, ?, ?, 'rule', 'needs_review', ?)",
                (run_uuid, doc_id, at_id, json.dumps(outputs)),
            )
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            return run_id

    def test_validate_run_success(self, client):
        """POST /api/runs/{id}/validate → 200 with vehicle + pickup results."""
        outputs = {
            "vehicle_vin": "WP1AA2A58JLB06122",
            "vehicle_year": "2018",
            "vehicle_make": "PORSCHE",
            "vehicle_model": "CAYENNE",
            "pickup_name": "Copart Exeter",
            "pickup_address": "10 Industrial Dr",
            "pickup_city": "Exeter",
            "pickup_state": "RI",
            "pickup_zip": "02822",
        }
        run_id = self._create_test_run(client, outputs)

        # Patch VINDecoder.decode to return controlled data (avoids cache+network issues)
        porsche_decoded = {
            "valid": True, "year": "2018", "make": "PORSCHE", "model": "CAYENNE",
            "body_class": "SUV", "error_code": "0", "error_text": None, "raw_response": None,
        }
        with patch("api.services.vin_decoder.VINDecoder.decode", return_value=porsche_decoded):
            with patch("api.services.address_validator.PickupAddressValidator._lookup_zip",
                       return_value={"city": "Exeter", "state": "RI"}):
                resp = client.post(f"/api/runs/{run_id}/validate")

        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert "vehicle" in data
        assert "pickup" in data
        assert "summary" in data
        assert data["vehicle"]["vin"]["status"] == "verified"
        assert data["vehicle"]["make"]["status"] == "verified"
        assert data["summary"]["vehicle_ok"] is True
        assert data["pickup"]["pickup_name"]["status"] == "verified"

    def test_get_cached_validation(self, client):
        """GET /api/runs/{id}/validation → returns saved result."""
        outputs = {
            "vehicle_vin": "JF1ZNBF18P8758268",
            "vehicle_year": "2023",
            "vehicle_make": "SUBARU",
            "vehicle_model": "BRZ",
            "pickup_name": "Copart Exeter",
            "pickup_address": "10 Industrial Dr",
            "pickup_city": "Exeter",
            "pickup_state": "RI",
            "pickup_zip": "02822",
        }
        run_id = self._create_test_run(client, outputs)

        # First validate
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = NHTSA_RESPONSE_SUBARU
        mock_resp.raise_for_status = MagicMock()

        with patch("api.services.vin_decoder.httpx.get", return_value=mock_resp):
            with patch("api.services.address_validator.httpx.get") as mock_zip:
                zip_resp = MagicMock()
                zip_resp.status_code = 200
                zip_resp.json.return_value = {"places": [{"place name": "Exeter", "state abbreviation": "RI"}]}
                zip_resp.raise_for_status = MagicMock()
                mock_zip.return_value = zip_resp

                client.post(f"/api/runs/{run_id}/validate")

        # Now GET should return cached
        resp = client.get(f"/api/runs/{run_id}/validation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert "validated_at" in data

    def test_get_validation_not_found(self, client):
        """GET /api/runs/999999/validation → 404."""
        resp = client.get("/api/runs/999999/validation")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestValidationIntegration:
    """Integration tests: extraction → validation pipeline."""

    def test_mismatch_detection_vehicle(self):
        """Full pipeline: decode VIN, detect make mismatch."""
        from api.services.vin_decoder import VINDecoder

        decoder = VINDecoder()
        decoded = {
            "valid": True, "year": "2018", "make": "PORSCHE", "model": "CAYENNE",
            "body_class": "SUV", "error_code": "0", "error_text": None, "raw_response": None,
        }
        with patch.object(decoder, "decode", return_value=decoded):
            result = decoder.validate_vehicle("WP1AA2A58JLB06122", "2018", "TOYOTA", "CAMRY")

        assert result["fields"]["make"]["status"] == "mismatch"
        assert result["fields"]["model"]["status"] == "mismatch"
        assert result["vin_valid"] is True  # VIN itself is valid, just wrong extracted data

    def test_mismatch_detection_address(self):
        """Full pipeline: directory match detects address mismatch."""
        from api.services.address_validator import PickupAddressValidator

        validator = PickupAddressValidator()
        with patch.object(validator, "_lookup_zip", return_value={"city": "Exeter", "state": "RI"}):
            result = validator.validate("COPART", {
                "pickup_name": "COPART - AYER",
                "pickup_address": "77 FITCHBURG ROAD",
                "pickup_city": "AYER",
                "pickup_state": "MA",
                "pickup_zip": "02822",
            })

        # All should be mismatched — extracted data is from wrong lot
        assert result["fields"]["pickup_name"]["status"] == "mismatch"
        assert result["fields"]["pickup_address"]["status"] == "mismatch"
        assert result["fields"]["pickup_city"]["status"] == "mismatch"
        assert result["fields"]["pickup_state"]["status"] == "mismatch"
        # ZIP matches (it's the correct ZIP)
        assert result["fields"]["pickup_zip"]["status"] == "verified"
