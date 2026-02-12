"""Location lookup service for auction pickup locations."""

import logging
import os
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class CopartLocationLookup:
    """Lookup service for Copart location names by address."""

    _instance = None
    _locations = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._locations is None:
            self._load_locations()

    def _load_locations(self):
        """Load Copart locations from YAML file."""
        self._locations = []

        # Look for copart_locations.yaml in project root
        locations_file = Path(__file__).parent.parent / "copart_locations.yaml"

        if not locations_file.exists():
            logger.warning(f"Copart locations file not found: {locations_file}")
            return

        try:
            with open(locations_file, "r") as f:
                data = yaml.safe_load(f)
                self._locations = data.get("locations", [])
                logger.info(f"Loaded {len(self._locations)} Copart locations")
        except Exception as e:
            logger.error(f"Error loading Copart locations: {e}")

    def lookup(
        self,
        city: str = None,
        state: str = None,
        zip_code: str = None,
        street: str = None,
    ) -> Optional[str]:
        """
        Lookup Copart location name by address components.

        Priority:
        1. Match by zip code + address pattern (if provided)
        2. Match by zip code only
        3. Match by city + state + address pattern
        4. Match by city + state only

        Args:
            city: City name
            state: State code (2 letters)
            zip_code: ZIP code
            street: Street address for pattern matching

        Returns:
            Location name (e.g., "Copart Denver") or None if not found
        """
        if not self._locations:
            return None

        city_upper = city.upper().strip() if city else ""
        state_upper = state.upper().strip() if state else ""
        zip_clean = zip_code.strip()[:5] if zip_code else ""
        street_upper = street.upper().strip() if street else ""

        best_match = None
        best_score = 0

        for loc in self._locations:
            score = 0

            # Check ZIP match (highest priority)
            if zip_clean and loc.get("zip") == zip_clean:
                score += 10

            # Check state match
            if state_upper and loc.get("state") == state_upper:
                score += 2

            # Check city match
            loc_city = loc.get("city", "").upper()
            if city_upper and loc_city == city_upper:
                score += 5

            # Check address pattern match (bonus)
            address_pattern = loc.get("address_pattern", "").upper()
            if address_pattern and street_upper:
                if address_pattern in street_upper:
                    score += 8

            # Need at least zip or (city + state) match
            if score > best_score and score >= 7:
                best_score = score
                best_match = loc.get("name")

        if best_match:
            logger.debug(
                f"Copart location lookup: {city}, {state} {zip_code} -> {best_match}"
            )
            return best_match

        # Fallback: generate name from city if we have state
        if city and state:
            # Clean city name for display
            city_title = city.strip().title()
            fallback = f"Copart {city_title}"
            logger.debug(f"Copart location fallback: {fallback}")
            return fallback

        return None


class ManheimLocationLookup:
    """Lookup service for Manheim location names by address."""

    _instance = None
    _locations = None
    _partners = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._locations is None:
            self._load_locations()

    def _load_locations(self):
        """Load Manheim locations from YAML file."""
        self._locations = []
        self._partners = []

        # Look for manheim_locations.yaml in project root
        locations_file = Path(__file__).parent.parent / "manheim_locations.yaml"

        if not locations_file.exists():
            logger.warning(f"Manheim locations file not found: {locations_file}")
            return

        try:
            with open(locations_file, "r") as f:
                data = yaml.safe_load(f)
                self._locations = data.get("locations", [])
                self._partners = data.get("partners", [])
                logger.info(
                    f"Loaded {len(self._locations)} Manheim locations, "
                    f"{len(self._partners)} partners"
                )
        except Exception as e:
            logger.error(f"Error loading Manheim locations: {e}")

    def lookup(
        self,
        city: str = None,
        state: str = None,
        zip_code: str = None,
        street: str = None,
    ) -> Optional[str]:
        """
        Lookup Manheim location name by address components.

        Args:
            city: City name
            state: State code (2 letters)
            zip_code: ZIP code
            street: Street address for pattern matching

        Returns:
            Location name (e.g., "Manheim Portland") or None if not found
        """
        if not self._locations:
            return None

        city_upper = city.upper().strip() if city else ""
        state_upper = state.upper().strip() if state else ""
        zip_clean = zip_code.strip()[:5] if zip_code else ""
        street_upper = street.upper().strip() if street else ""

        best_match = None
        best_score = 0

        # Check main locations first
        for loc in self._locations:
            score = 0

            # Check ZIP match (highest priority)
            if zip_clean and loc.get("zip") == zip_clean:
                score += 10

            # Check state match
            if state_upper and loc.get("state") == state_upper:
                score += 2

            # Check city match
            loc_city = loc.get("city", "").upper()
            if city_upper and loc_city == city_upper:
                score += 5

            # Check address pattern match (bonus)
            address_pattern = loc.get("address_pattern", "").upper()
            if address_pattern and street_upper:
                patterns = address_pattern.split("|")
                for pattern in patterns:
                    if pattern in street_upper:
                        score += 8
                        break

            # Need at least zip or (city + state) match
            if score > best_score and score >= 7:
                best_score = score
                best_match = loc.get("name")

        if best_match:
            logger.debug(
                f"Manheim location lookup: {city}, {state} {zip_code} -> {best_match}"
            )
            return best_match

        # Check partner locations
        for partner in self._partners:
            partner_city = partner.get("city", "").upper()
            partner_state = partner.get("state", "").upper()

            if city_upper == partner_city and state_upper == partner_state:
                address_pattern = partner.get("address_pattern", "").upper()
                if address_pattern and street_upper:
                    if address_pattern in street_upper:
                        return partner.get("name")
                elif not address_pattern:
                    return partner.get("name")

        return None


# Singleton instances
_copart_lookup = None
_manheim_lookup = None


def get_copart_location_name(
    city: str = None,
    state: str = None,
    zip_code: str = None,
    street: str = None,
) -> str:
    """
    Get Copart location name for a given address.

    Returns location name from reference data, or generates
    "Copart {City}" as fallback.

    Args:
        city: City name
        state: State code
        zip_code: ZIP code
        street: Street address

    Returns:
        Location name (always returns something, defaults to "Copart")
    """
    global _copart_lookup
    if _copart_lookup is None:
        _copart_lookup = CopartLocationLookup()

    result = _copart_lookup.lookup(city, state, zip_code, street)
    return result or "Copart"


def get_manheim_location_name(
    city: str = None,
    state: str = None,
    zip_code: str = None,
    street: str = None,
) -> Optional[str]:
    """
    Get Manheim location name for a given address.

    Returns location name from reference data, or None if not found.
    Unlike Copart, Manheim doesn't generate fallback names because
    OFFSITE releases should use seller name when addresses match.

    Args:
        city: City name
        state: State code
        zip_code: ZIP code
        street: Street address

    Returns:
        Location name or None if not in reference data
    """
    global _manheim_lookup
    if _manheim_lookup is None:
        _manheim_lookup = ManheimLocationLookup()

    return _manheim_lookup.lookup(city, state, zip_code, street)
