"""Pickup address validation against auction directory and ZIP database.

Validates extracted pickup fields (name, address, city, state, zip) by:
1. Looking up the auction facility in the directory by zip code
2. Cross-checking ZIP ↔ city/state via zippopotam.us API
3. Basic format checks (5-digit ZIP, 2-letter state)

ZIP lookups are cached in SQLite (zip_cache table).
"""

import json
import logging
import re

import httpx

from api.database import get_connection

logger = logging.getLogger(__name__)

ZIPPOPOTAM_URL = "https://api.zippopotam.us/us/{zip}"
ZIPPOPOTAM_TIMEOUT = 5  # seconds

# Valid US state abbreviations
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI", "GU", "AS", "MP",
}


def init_zip_cache_table():
    """Create zip_cache table if it doesn't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS zip_cache (
                zip_code TEXT PRIMARY KEY,
                city TEXT,
                state TEXT,
                cached_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def _get_directory_for_type(auction_type: str) -> dict:
    """Get the appropriate directory dict for an auction type."""
    at = (auction_type or "").upper()
    from services.auction_directory import (
        COPART_LOCATIONS,
        IAA_LOCATIONS,
        MANHEIM_LOCATIONS,
    )
    if at == "COPART":
        return COPART_LOCATIONS
    elif at == "IAA":
        return IAA_LOCATIONS
    elif at == "MANHEIM":
        return MANHEIM_LOCATIONS
    return {}


def _lookup_by_zip(directory: dict, zip_code: str) -> tuple[str | None, dict | None]:
    """Find a facility in the directory by zip code.

    Returns (facility_name, facility_data) or (None, None).
    """
    if not zip_code:
        return None, None
    for name, loc in directory.items():
        if loc.get("zip", "") == zip_code:
            return name, loc
    return None, None


def _compare_field(extracted: str, directory: str) -> str:
    """Compare two field values case-insensitively.

    Returns 'verified' if they match, 'mismatch' if they don't.
    """
    e = (extracted or "").strip().upper()
    d = (directory or "").strip().upper()
    if not e and not d:
        return "verified"
    if e == d:
        return "verified"
    return "mismatch"


class PickupAddressValidator:
    """Validates pickup address against auction directory and ZIP database."""

    def validate(self, auction_type: str, extracted_fields: dict,
                 original_pickup: dict = None) -> dict:
        """Validate pickup address fields.

        Args:
            auction_type: "COPART", "IAA", "MANHEIM", etc.
            extracted_fields: dict with pickup_name, pickup_address,
                pickup_city, pickup_state, pickup_zip (post-processed values)
            original_pickup: Optional dict with Haiku's original extraction
                BEFORE directory post-processing. Used to detect when directory
                replaced Haiku's values (circular validation prevention).

        Returns dict with fields (per-field status), directory_match, zip_city_match.

        Statuses:
            "verified" — post-processed value matches directory AND original Haiku
                extraction also matched (or no original available)
            "corrected_by_directory" — post-processed value matches directory BUT
                original Haiku extraction was different (directory replaced it)
            "mismatch" — value doesn't match directory or has invalid format
            "unverified" — no directory entry found for this ZIP
        """
        ext_name = str(extracted_fields.get("pickup_name") or "").strip()
        ext_addr = str(extracted_fields.get("pickup_address") or "").strip()
        ext_city = str(extracted_fields.get("pickup_city") or "").strip()
        ext_state = str(extracted_fields.get("pickup_state") or "").strip()
        ext_zip = str(extracted_fields.get("pickup_zip") or "").strip()

        fields = {}
        directory_match = False

        # ── Step 1: Directory lookup by ZIP ──────────────────────────
        directory = _get_directory_for_type(auction_type)
        fac_name, fac_data = _lookup_by_zip(directory, ext_zip)

        if fac_name and fac_data:
            directory_match = True
            dir_addr = fac_data.get("address", "")
            dir_city = fac_data.get("city", "")
            dir_state = fac_data.get("state", "")
            dir_zip = fac_data.get("zip", "")

            # Compare current (post-processed) values with directory
            field_pairs = [
                ("pickup_name", ext_name, fac_name),
                ("pickup_address", ext_addr, dir_addr),
                ("pickup_city", ext_city, dir_city),
                ("pickup_state", ext_state, dir_state),
            ]
            for key, ext_val, dir_val in field_pairs:
                status = _compare_field(ext_val, dir_val)
                field_entry = {
                    "status": status,
                    "extracted": ext_val,
                    "directory": dir_val,
                }
                # If original_pickup is available and field was "verified" against
                # directory, check if original Haiku extraction was DIFFERENT.
                # If so, directory replaced Haiku's value → "corrected_by_directory".
                if status == "verified" and original_pickup:
                    orig_val = str(original_pickup.get(key) or "").strip()
                    if orig_val and _compare_field(orig_val, dir_val) != "verified":
                        field_entry["status"] = "corrected_by_directory"
                        field_entry["original"] = orig_val
                fields[key] = field_entry

            fields["pickup_zip"] = {
                "status": "verified",
                "extracted": ext_zip,
                "directory": dir_zip,
            }
            # Check if original ZIP was different (directory replaced it)
            if original_pickup:
                orig_zip = str(original_pickup.get("pickup_zip") or "").strip()
                if orig_zip and orig_zip != ext_zip:
                    fields["pickup_zip"]["status"] = "corrected_by_directory"
                    fields["pickup_zip"]["original"] = orig_zip
        else:
            # Not in directory — mark as unverified
            for key in ["pickup_name", "pickup_address", "pickup_city", "pickup_state", "pickup_zip"]:
                val = extracted_fields.get(key, "")
                fields[key] = {
                    "status": "unverified",
                    "extracted": str(val or "").strip(),
                    "directory": None,
                }

        # ── Step 2: Format checks ────────────────────────────────────
        # ZIP: must be 5 digits
        if ext_zip and not re.match(r"^\d{5}$", ext_zip):
            fields["pickup_zip"] = {
                **fields.get("pickup_zip", {}),
                "status": "mismatch",
                "extracted": ext_zip,
                "message": f"Invalid ZIP format: '{ext_zip}' (expected 5 digits)",
            }

        # State: must be 2-letter valid US state
        if ext_state and ext_state.upper() not in _US_STATES:
            fields["pickup_state"] = {
                **fields.get("pickup_state", {}),
                "status": "mismatch",
                "extracted": ext_state,
                "message": f"Invalid state code: '{ext_state}'",
            }

        # Address: must not be empty
        if not ext_addr:
            fields["pickup_address"]["status"] = "mismatch"
            fields["pickup_address"]["message"] = "Pickup address is empty"

        # ── Step 3: ZIP ↔ city/state cross-check ─────────────────────
        zip_city_match = None
        if ext_zip and re.match(r"^\d{5}$", ext_zip):
            zip_info = self._lookup_zip(ext_zip)
            if zip_info:
                zip_city = zip_info.get("city", "")
                zip_state = zip_info.get("state", "")

                # Cross-check state
                if zip_state and ext_state:
                    if ext_state.upper() != zip_state.upper():
                        fields["pickup_state"] = {
                            "status": "mismatch",
                            "extracted": ext_state,
                            "directory": fields.get("pickup_state", {}).get("directory"),
                            "zip_expected": zip_state,
                            "message": f"ZIP {ext_zip} is in {zip_state}, not {ext_state}",
                        }

                # Cross-check city (less strict — cities can have aliases)
                if zip_city and ext_city:
                    if ext_city.upper() == zip_city.upper():
                        zip_city_match = True
                    else:
                        zip_city_match = False
                        # Only override if not already verified by directory
                        if fields.get("pickup_city", {}).get("status") != "verified":
                            fields["pickup_city"] = {
                                "status": "mismatch",
                                "extracted": ext_city,
                                "directory": fields.get("pickup_city", {}).get("directory"),
                                "zip_expected": zip_city,
                                "message": f"ZIP {ext_zip} maps to {zip_city}, not {ext_city}",
                            }

        return {
            "fields": fields,
            "directory_match": directory_match,
            "zip_city_match": zip_city_match,
        }

    # ── ZIP lookup with cache ────────────────────────────────────────

    def _lookup_zip(self, zip_code: str) -> dict | None:
        """Look up city/state for ZIP code. Uses DB cache, then API."""
        # Check cache
        cached = self._get_zip_cache(zip_code)
        if cached is not None:
            return cached

        # Call zippopotam.us
        url = ZIPPOPOTAM_URL.format(zip=zip_code)
        try:
            resp = httpx.get(url, timeout=ZIPPOPOTAM_TIMEOUT)
            if resp.status_code == 404:
                # Invalid ZIP — cache empty result
                result = {"city": None, "state": None}
                self._save_zip_cache(zip_code, result)
                return result
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("ZIP lookup failed for %s: %s", zip_code, exc)
            return None

        places = data.get("places", [])
        if not places:
            result = {"city": None, "state": None}
        else:
            result = {
                "city": places[0].get("place name", ""),
                "state": places[0].get("state abbreviation", ""),
            }

        self._save_zip_cache(zip_code, result)
        return result

    def _get_zip_cache(self, zip_code: str) -> dict | None:
        """Check SQLite cache for ZIP lookup."""
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT city, state FROM zip_cache WHERE zip_code = ?",
                    (zip_code,),
                ).fetchone()
                if row:
                    return {"city": row["city"], "state": row["state"]}
        except Exception:
            pass
        return None

    def _save_zip_cache(self, zip_code: str, result: dict) -> None:
        """Save ZIP lookup to cache."""
        try:
            with get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO zip_cache (zip_code, city, state) VALUES (?, ?, ?)",
                    (zip_code, result.get("city"), result.get("state")),
                )
                conn.commit()
        except Exception as exc:
            logger.warning("Failed to cache ZIP %s: %s", zip_code, exc)
