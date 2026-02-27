"""VIN decoder and vehicle validation via NHTSA vPIC API.

Decodes VINs using the free NHTSA Vehicle Product Information Catalog API
and compares decoded year/make/model against extracted values.

Results are cached in SQLite (vin_decode_cache) since VIN data never changes.
"""

import json
import logging
import re
import time

import httpx

from api.database import get_connection

logger = logging.getLogger(__name__)

# Common make aliases — maps variant spellings to canonical name
_MAKE_ALIASES: dict[str, str] = {
    "chevy": "chevrolet",
    "vw": "volkswagen",
    "mb": "mercedes-benz",
    "mercedes": "mercedes-benz",
    "merc": "mercedes-benz",
    "benz": "mercedes-benz",
    "land rover": "land rover",
    "landrover": "land rover",
    "range rover": "land rover",
    "gmc": "gmc",
    "caddy": "cadillac",
    "alfa": "alfa romeo",
    "alfaromeo": "alfa romeo",
    "jag": "jaguar",
    "lexs": "lexus",
    "lex": "lexus",
    "inf": "infiniti",
    "infin": "infiniti",
    "infinty": "infiniti",
    "acur": "acura",
}

NHTSA_BASE = "https://vpic.nhtsa.dot.gov/api/vehicles"
NHTSA_TIMEOUT = 10  # seconds


def init_vin_cache_table():
    """Create vin_decode_cache table if it doesn't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vin_decode_cache (
                vin TEXT PRIMARY KEY,
                decoded_json TEXT NOT NULL,
                decoded_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def _normalize_make(make: str) -> str:
    """Normalize make name for comparison."""
    if not make:
        return ""
    m = make.strip().lower()
    return _MAKE_ALIASES.get(m, m)


def _compare_makes(a: str, b: str) -> bool:
    """Compare two make names with alias resolution."""
    return _normalize_make(a) == _normalize_make(b)


def _compare_models(extracted: str, decoded: str) -> bool:
    """Compare model names — partial match allowed.

    "CAMRY" matches "CAMRY LE", "Cayenne" matches "Cayenne S", etc.
    """
    if not extracted or not decoded:
        return False
    e = extracted.strip().lower()
    d = decoded.strip().lower()
    if e == d:
        return True
    # Partial: extracted is prefix/substring of decoded or vice-versa
    return e in d or d in e


class VINDecoder:
    """Validates VIN and vehicle info via NHTSA vPIC API."""

    NHTSA_URL = NHTSA_BASE + "/DecodeVin/{vin}?format=json"

    # NHTSA variable IDs for key fields
    _VAR_MAP = {
        "Make": "make",
        "Model": "model",
        "Model Year": "year",
        "Body Class": "body_class",
        "Error Code": "error_code",
        "Error Text": "error_text",
        "Plant City": "plant_city",
        "Plant State": "plant_state",
        "Plant Country": "plant_country",
        "Vehicle Type": "vehicle_type",
        "Drive Type": "drive_type",
        "Fuel Type - Primary": "fuel_type",
    }

    def decode(self, vin: str) -> dict:
        """Decode VIN via NHTSA API.

        Returns dict with valid, year, make, model, body_class, error_code, raw_response.
        Uses SQLite cache — NHTSA is only called once per VIN.
        """
        vin = (vin or "").strip().upper()

        # Basic format check
        if not vin or len(vin) != 17 or not re.match(r"^[A-HJ-NPR-Z0-9]{17}$", vin):
            return {
                "valid": False,
                "year": None,
                "make": None,
                "model": None,
                "body_class": None,
                "error_code": "FORMAT",
                "error_text": f"Invalid VIN format: must be 17 alphanumeric chars (no I/O/Q), got {len(vin) if vin else 0}",
                "raw_response": None,
            }

        # Check cache
        cached = self._get_cached(vin)
        if cached is not None:
            return cached

        # Call NHTSA
        url = self.NHTSA_URL.format(vin=vin)
        try:
            resp = httpx.get(url, timeout=NHTSA_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException:
            logger.warning("NHTSA timeout for VIN %s", vin)
            return {
                "valid": None,
                "year": None,
                "make": None,
                "model": None,
                "body_class": None,
                "error_code": "TIMEOUT",
                "error_text": "NHTSA API timeout",
                "raw_response": None,
            }
        except Exception as exc:
            logger.warning("NHTSA error for VIN %s: %s", vin, exc)
            return {
                "valid": None,
                "year": None,
                "make": None,
                "model": None,
                "body_class": None,
                "error_code": "API_ERROR",
                "error_text": str(exc),
                "raw_response": None,
            }

        # Parse NHTSA response
        result = self._parse_nhtsa(data)
        result["raw_response"] = data

        # Cache
        self._save_cache(vin, result)

        return result

    def validate_vehicle(
        self,
        vin: str,
        extracted_year: str | None,
        extracted_make: str | None,
        extracted_model: str | None,
    ) -> dict:
        """Decode VIN and compare with extracted year/make/model.

        Returns dict with vin_valid, fields (per-field status), error.
        """
        decoded = self.decode(vin)

        # If NHTSA unavailable or VIN format invalid
        if decoded.get("error_code") in ("TIMEOUT", "API_ERROR"):
            return {
                "vin_valid": None,
                "fields": {
                    "vin": {"status": "unverified", "extracted": vin, "decoded": None},
                    "year": {"status": "unverified", "extracted": extracted_year, "decoded": None},
                    "make": {"status": "unverified", "extracted": extracted_make, "decoded": None},
                    "model": {"status": "unverified", "extracted": extracted_model, "decoded": None},
                },
                "error": decoded.get("error_text"),
            }

        if decoded.get("error_code") == "FORMAT":
            return {
                "vin_valid": False,
                "fields": {
                    "vin": {"status": "mismatch", "extracted": vin, "decoded": None,
                            "message": decoded.get("error_text", "Invalid VIN format")},
                    "year": {"status": "unverified", "extracted": extracted_year, "decoded": None},
                    "make": {"status": "unverified", "extracted": extracted_make, "decoded": None},
                    "model": {"status": "unverified", "extracted": extracted_model, "decoded": None},
                },
                "error": decoded.get("error_text"),
            }

        # NHTSA error_code: "0" means no error, anything else is partial/error
        nhtsa_error = decoded.get("error_code", "")
        # Error codes that contain "0" (no error) vs others
        vin_valid = nhtsa_error == "0" or (nhtsa_error and "0" in nhtsa_error.split(","))

        fields = {}

        # VIN itself
        fields["vin"] = {
            "status": "verified" if vin_valid else "mismatch",
            "extracted": vin,
            "decoded": vin,
        }
        if not vin_valid:
            fields["vin"]["message"] = decoded.get("error_text", "NHTSA reports VIN errors")

        # Year
        d_year = str(decoded.get("year") or "").strip()
        e_year = str(extracted_year or "").strip()
        if not d_year:
            fields["year"] = {"status": "unverified", "extracted": e_year, "decoded": None}
        elif d_year == e_year:
            fields["year"] = {"status": "verified", "extracted": e_year, "decoded": d_year}
        else:
            fields["year"] = {"status": "mismatch", "extracted": e_year, "decoded": d_year}

        # Make
        d_make = str(decoded.get("make") or "").strip()
        e_make = str(extracted_make or "").strip()
        if not d_make:
            fields["make"] = {"status": "unverified", "extracted": e_make, "decoded": None}
        elif _compare_makes(e_make, d_make):
            fields["make"] = {"status": "verified", "extracted": e_make, "decoded": d_make}
        else:
            fields["make"] = {"status": "mismatch", "extracted": e_make, "decoded": d_make}

        # Model
        d_model = str(decoded.get("model") or "").strip()
        e_model = str(extracted_model or "").strip()
        if not d_model:
            fields["model"] = {"status": "unverified", "extracted": e_model, "decoded": None}
        elif _compare_models(e_model, d_model):
            fields["model"] = {"status": "verified", "extracted": e_model, "decoded": d_model}
        else:
            fields["model"] = {"status": "mismatch", "extracted": e_model, "decoded": d_model}

        return {
            "vin_valid": vin_valid,
            "fields": fields,
            "error": None,
        }

    # ── Internal helpers ─────────────────────────────────────────────

    def _parse_nhtsa(self, data: dict) -> dict:
        """Parse NHTSA DecodeVin JSON response into flat dict."""
        result = {
            "valid": None,
            "year": None,
            "make": None,
            "model": None,
            "body_class": None,
            "error_code": None,
            "error_text": None,
        }

        results = data.get("Results", [])
        for item in results:
            var_name = item.get("Variable", "")
            value = item.get("Value")
            if value and var_name in self._VAR_MAP:
                key = self._VAR_MAP[var_name]
                result[key] = str(value).strip()

        # Determine validity from error code
        ec = result.get("error_code", "")
        result["valid"] = ec == "0" or (bool(ec) and "0" in ec.split(","))

        return result

    def _get_cached(self, vin: str) -> dict | None:
        """Check SQLite cache for previously decoded VIN."""
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT decoded_json FROM vin_decode_cache WHERE vin = ?",
                    (vin,),
                ).fetchone()
                if row:
                    return json.loads(row["decoded_json"])
        except Exception:
            pass
        return None

    def _save_cache(self, vin: str, result: dict) -> None:
        """Save decode result to SQLite cache."""
        try:
            # Don't cache raw_response (too large), store separately
            cache_data = {k: v for k, v in result.items() if k != "raw_response"}
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO vin_decode_cache (vin, decoded_json) VALUES (?, ?)",
                    (vin, json.dumps(cache_data)),
                )
                conn.commit()
        except Exception as exc:
            logger.warning("Failed to cache VIN decode for %s: %s", vin, exc)
