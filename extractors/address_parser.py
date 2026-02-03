"""
Shared address parsing utilities for all auction extractors.

Handles various address formats commonly found in auction documents:
- "City State ZIP" (e.g., "Flint Michigan 48507")
- "City, State ZIP" (e.g., "Dallas, TX 75001")
- Multi-line formats with street address, city/state/zip on separate lines
- Phone number extraction nearby
"""

import re
from dataclasses import dataclass
from typing import Optional

from models.vehicle import Address

# US State name to abbreviation mapping
STATE_ABBREVS = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}

# Reverse mapping: abbreviation to full name
ABBREV_TO_STATE = {v: k.title() for k, v in STATE_ABBREVS.items()}


def normalize_state(state_str: str) -> str:
    """
    Convert state name or abbreviation to two-letter abbreviation.

    Examples:
        "Michigan" -> "MI"
        "MI" -> "MI"
        "michigan" -> "MI"
    """
    if not state_str:
        return ""
    state_str = state_str.strip()

    # Already a valid abbreviation
    if len(state_str) == 2 and state_str.upper().isalpha():
        return state_str.upper()

    # Look up full name
    return STATE_ABBREVS.get(state_str.lower(), state_str.upper()[:2])


def normalize_phone(phone: str) -> str:
    """
    Normalize phone number to standard format: (XXX) XXX-XXXX

    Examples:
        "8107200981" -> "(810) 720-0981"
        "810-720-0981" -> "(810) 720-0981"
        "(810) 720-0981" -> "(810) 720-0981"
    """
    if not phone:
        return ""

    # Extract digits only
    digits = re.sub(r"\D", "", phone)

    # Format if we have 10 digits
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits[0] == "1":
        # Handle country code
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"

    return phone


@dataclass
class ParsedAddress:
    """Parsed address components."""

    name: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "US"
    phone: Optional[str] = None

    def to_address(self) -> Optional[Address]:
        """Convert to Address model if valid."""
        if not (self.city and self.state):
            return None
        return Address(
            name=self.name,
            street=self.street,
            city=self.city,
            state=self.state,
            postal_code=self.postal_code,
            country=self.country,
            phone=self.phone,
        )

    def is_valid(self) -> bool:
        """Check if address has minimum required fields."""
        return bool(self.city and self.state)


def extract_phone_from_text(text: str) -> Optional[str]:
    """
    Extract phone number from text.

    Returns normalized phone format (XXX) XXX-XXXX or None.
    """
    phone_patterns = [
        r"\((\d{3})\)\s*(\d{3})[-.\s]?(\d{4})",  # (810) 720-0981
        r"(\d{3})[-.\s](\d{3})[-.\s](\d{4})",  # 810-720-0981
        r"(\d{3})(\d{3})(\d{4})",  # 8107200981
    ]

    for pattern in phone_patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) == 3:
                return f"({groups[0]}) {groups[1]}-{groups[2]}"

    return None


def parse_city_state_zip(line: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse a line containing city, state, and ZIP code.

    Handles formats:
        - "Flint Michigan 48507"
        - "Dallas, TX 75001"
        - "New York NY 10001"
        - "Los Angeles, California 90001"

    Returns: (city, state_abbrev, zip_code) or (None, None, None) if not matched
    """
    if not line:
        return None, None, None

    line = line.strip()

    # Pattern 1: City, State ZIP (with comma)
    match = re.match(r"([A-Za-z][A-Za-z\s\.]*?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)", line)
    if match:
        return match.group(1).strip(), match.group(2), match.group(3)

    # Pattern 2: City State(full name) ZIP - e.g., "Flint Michigan 48507"
    match = re.match(r"([A-Za-z][A-Za-z\s\.]*?)\s+([A-Za-z]{2,})\s+(\d{5}(?:-\d{4})?)", line)
    if match:
        city = match.group(1).strip()
        state_candidate = match.group(2)
        zip_code = match.group(3)

        # Check if state_candidate is a valid state
        state_abbrev = normalize_state(state_candidate)
        if len(state_abbrev) == 2 and state_abbrev.isalpha():
            # Verify it's a real state
            if state_abbrev in ABBREV_TO_STATE or state_candidate.lower() in STATE_ABBREVS:
                return city, state_abbrev, zip_code

    # Pattern 3: City State(abbreviation) ZIP (no comma)
    match = re.match(r"([A-Za-z][A-Za-z\s\.]*?)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)", line)
    if match:
        return match.group(1).strip(), match.group(2), match.group(3)

    return None, None, None


def extract_address_from_section(
    section_text: str,
    location_label: str = None,
) -> ParsedAddress:
    """
    Extract address components from a text section.

    Args:
        section_text: Text containing address information
        location_label: Optional label/name for the location (e.g., "Copart Dallas")

    Returns:
        ParsedAddress with extracted components
    """
    result = ParsedAddress(name=location_label)

    if not section_text:
        return result

    # Split into lines and filter empty
    lines = [line.strip() for line in section_text.split("\n") if line.strip()]

    if not lines:
        return result

    # Look for city/state/zip pattern in each line
    city_state_zip_idx = -1
    for i, line in enumerate(lines):
        city, state, zip_code = parse_city_state_zip(line)
        if city and state:
            result.city = city
            result.state = state
            result.postal_code = zip_code
            city_state_zip_idx = i
            break

    if city_state_zip_idx == -1:
        return result

    # Try to extract street address from line before city/state/zip
    if city_state_zip_idx > 0:
        potential_street = lines[city_state_zip_idx - 1]
        # Street should contain a number
        if re.search(r"\d", potential_street):
            result.street = potential_street

    # Try to extract location name from first line (if different from street)
    if len(lines) > 0 and city_state_zip_idx > 1:
        # First line might be location name
        first_line = lines[0]
        if first_line != result.street and not re.search(r"\d{5}", first_line):
            result.name = first_line
    elif len(lines) > 0 and city_state_zip_idx == 1:
        # Two line format: name/city then city/state/zip, with street on first line
        # Re-check if first line looks more like a name than address
        first_line = lines[0]
        if not re.search(r"\d", first_line):
            result.name = first_line
            result.street = None  # Clear street, we don't have it

    # Look for phone number after the address
    if city_state_zip_idx < len(lines) - 1:
        for line in lines[city_state_zip_idx + 1 :]:
            phone = extract_phone_from_text(line)
            if phone:
                result.phone = phone
                break

    # Also check the whole section for phone if not found
    if not result.phone:
        result.phone = extract_phone_from_text(section_text)

    return result


def extract_lines_after_label(text: str, label_pattern: str, max_lines: int = 6) -> list[str]:
    """
    Extract lines that appear AFTER (below) a label in the text.

    This handles the common pattern in auction documents where:
    - Label is on one line (e.g., "PHYSICAL ADDRESS OF LOT:")
    - Values are on subsequent lines below the label

    Args:
        text: Full document text
        label_pattern: Regex pattern to find the label
        max_lines: Maximum number of lines to capture after the label

    Returns:
        List of lines after the label (stripped, non-empty)
    """
    lines = text.split("\n")
    result = []
    found_label = False

    for _i, line in enumerate(lines):
        stripped = line.strip()

        # Check if this line contains the label
        if not found_label and re.search(label_pattern, stripped, re.IGNORECASE):
            found_label = True
            # Check if there's content on the same line after the label
            # (remove the label part and check for remaining content)
            after_label = re.sub(
                label_pattern + r"[:\s]*", "", stripped, flags=re.IGNORECASE
            ).strip()
            if after_label and len(after_label) > 3:
                # Content is on the same line as label
                result.append(after_label)
            continue

        if found_label:
            if not stripped:
                # Empty line might signal end of section
                if len(result) > 0:
                    break
                continue

            # Stop if we hit another section header
            # Must be: ALL CAPS + ending with colon (like "MEMBER:"), or specific field labels
            if re.match(r"^[A-Z][A-Z\s]{2,}:\s*$", stripped):
                # All caps followed by colon only
                break
            if re.match(
                r"^(MEMBER|LOT#?|VEHICLE|VIN|SALE\s*DATE|BUYER|SELLER|TOTAL|PAYMENT|RECEIPT|STOCK|INVOICE)[:\s]*$",
                stripped,
                re.IGNORECASE,
            ):
                # Known field labels
                break

            result.append(stripped)

            if len(result) >= max_lines:
                break

    return result


def extract_address_after_label(
    text: str,
    label_patterns: list[str],
    end_patterns: list[str] = None,
    location_prefix: str = None,
) -> Optional[Address]:
    """
    Extract address that follows a specific label in the text.

    Handles two common patterns:
    1. Label and value on same line: "Location: 123 Main St, City, ST 12345"
    2. Label on one line, value on lines BELOW (common in Copart/IAA):
       PHYSICAL ADDRESS OF LOT:
       123 Main St
       City ST 12345

    Args:
        text: Full document text
        label_patterns: List of regex patterns to find the address label
                        (e.g., ["Pick-Up Location", "PHYSICAL ADDRESS OF LOT"])
        end_patterns: List of patterns that mark the end of the address section
                      (e.g., ["Stock", "Invoice", "Sale Date"])
        location_prefix: Prefix to add to location name (e.g., "IAA", "Copart")

    Returns:
        Address object or None if not found
    """
    if not text:
        return None

    if end_patterns is None:
        end_patterns = [
            r"\n\s*\n",  # Double newline
            r"Stock",
            r"Invoice",
            r"Sale\s*Date",
            r"Buyer",
            r"Receipt",
            r"Total",
            r"Payment",
        ]

    # First, try the new line-based extraction (label above, value below)
    for label_pattern in label_patterns:
        lines = extract_lines_after_label(text, label_pattern)
        if lines:
            # Join lines and try to parse as address section
            section_text = "\n".join(lines)
            parsed = extract_address_from_section(section_text)

            if parsed.is_valid():
                # Add location prefix if provided
                if location_prefix and parsed.name:
                    if location_prefix.upper() not in parsed.name.upper():
                        parsed.name = f"{location_prefix} {parsed.name}"
                elif location_prefix and not parsed.name:
                    parsed.name = location_prefix
                return parsed.to_address()

    # Build end pattern regex for fallback methods
    end_regex = "|".join(f"(?:{p})" for p in end_patterns)

    # Fallback: try inline extraction (label and value on same line/section)
    for label_pattern in label_patterns:
        # Find the label and capture text after it
        regex = rf"{label_pattern}[:\s]*(.+?)(?:{end_regex})"
        match = re.search(regex, text, re.IGNORECASE | re.DOTALL)

        if match:
            section = match.group(1)
            parsed = extract_address_from_section(section)

            if parsed.is_valid():
                # Add location prefix if provided
                if location_prefix and parsed.name:
                    if location_prefix.upper() not in parsed.name.upper():
                        parsed.name = f"{location_prefix} {parsed.name}"
                elif location_prefix and not parsed.name:
                    parsed.name = location_prefix

                return parsed.to_address()

    # Final fallback: try to find address pattern anywhere after any label
    for label_pattern in label_patterns:
        match = re.search(rf"{label_pattern}[:\s]*(.{{50,500}})", text, re.IGNORECASE | re.DOTALL)
        if match:
            section = match.group(1)
            parsed = extract_address_from_section(section)

            if parsed.is_valid():
                if location_prefix and not parsed.name:
                    parsed.name = location_prefix
                return parsed.to_address()

    return None


def extract_inline_address(
    text: str,
    pattern: str,
) -> Optional[Address]:
    """
    Extract address from an inline format (all on one line or comma-separated).

    Args:
        text: Text to search
        pattern: Regex pattern that captures (name, street, city, state, zip)

    Returns:
        Address object or None
    """
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None

    groups = match.groups()
    if len(groups) >= 5:
        return Address(
            name=groups[0].strip() if groups[0] else None,
            street=groups[1].strip() if groups[1] else None,
            city=groups[2].strip().rstrip(",") if groups[2] else None,
            state=normalize_state(groups[3]) if groups[3] else None,
            postal_code=groups[4] if groups[4] else None,
            country="US",
        )

    return None


# Pre-defined label patterns for common auction documents
PICKUP_LABELS = [
    r"Pick[-\s]?Up\s*Location",
    r"Pick[-\s]?Up\s*Address",
    r"PICKUP\s*(?:LOCATION|ADDRESS)",
    r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT",
    r"LOT\s*(?:LOCATION|ADDRESS)",
    r"Sold\s*At\s*Branch",
]

DELIVERY_LABELS = [
    r"Delivery\s*(?:Location|Address)",
    r"Drop[-\s]?Off\s*(?:Location|Address)",
    r"Destination",
    r"Ship\s*To",
]


def extract_pickup_address(
    text: str,
    source: str = None,
    custom_labels: list[str] = None,
) -> Optional[Address]:
    """
    Convenience function to extract pickup address from auction document.

    Args:
        text: Full document text
        source: Auction source name (e.g., "IAA", "Copart", "Manheim")
        custom_labels: Additional label patterns to try

    Returns:
        Address object or None
    """
    labels = list(PICKUP_LABELS)
    if custom_labels:
        labels.extend(custom_labels)

    return extract_address_after_label(
        text,
        label_patterns=labels,
        location_prefix=source,
    )


def extract_delivery_address(
    text: str,
    custom_labels: list[str] = None,
) -> Optional[Address]:
    """
    Convenience function to extract delivery address from document.

    Args:
        text: Full document text
        custom_labels: Additional label patterns to try

    Returns:
        Address object or None
    """
    labels = list(DELIVERY_LABELS)
    if custom_labels:
        labels.extend(custom_labels)

    return extract_address_after_label(
        text,
        label_patterns=labels,
    )


# =============================================================================
# CD API VALIDATION (M3.P0.4)
# =============================================================================

# Valid US state codes for CD API
US_STATE_CODES = set(STATE_ABBREVS.values()) | {"DC", "PR", "VI", "GU", "AS", "MP"}


def validate_state_for_cd(state: str) -> tuple[bool, str]:
    """
    Validate state code for CD API requirements.

    CD API requires 2-letter state abbreviation.

    Args:
        state: State value to validate

    Returns:
        Tuple of (is_valid, normalized_value_or_error)
    """
    if not state:
        return False, "State is required"

    # Normalize
    normalized = normalize_state(state)

    if len(normalized) != 2:
        return False, f"Invalid state: {state} (must be 2-letter code)"

    if normalized.upper() not in US_STATE_CODES:
        return False, f"Unknown state code: {normalized}"

    return True, normalized.upper()


def validate_zip_for_cd(zip_code: str) -> tuple[bool, str]:
    """
    Validate ZIP code for CD API requirements.

    CD API accepts 5-digit or 9-digit (ZIP+4) format.

    Args:
        zip_code: ZIP code to validate

    Returns:
        Tuple of (is_valid, normalized_value_or_error)
    """
    if not zip_code:
        return False, "ZIP code is required"

    # Clean to digits only
    digits = re.sub(r"[^0-9]", "", zip_code)

    if len(digits) == 5:
        return True, digits

    if len(digits) == 9:
        return True, f"{digits[:5]}-{digits[5:]}"

    return False, f"Invalid ZIP code: {zip_code} (must be 5 or 9 digits)"


def validate_address_for_cd(address: ParsedAddress) -> tuple[bool, list[str]]:
    """
    Validate parsed address for Central Dispatch API requirements.

    CD API requires:
    - address (street) - required for stops
    - city - required
    - state - 2-letter code required
    - postalCode - 5 or 9 digits required

    Args:
        address: ParsedAddress to validate

    Returns:
        Tuple of (is_valid, list of validation errors)
    """
    errors = []

    # Validate street address
    if not address.street:
        errors.append("Street address is required")

    # Validate city
    if not address.city:
        errors.append("City is required")
    elif len(address.city) < 2:
        errors.append(f"City too short: {address.city}")

    # Validate state
    if not address.state:
        errors.append("State is required")
    else:
        state_valid, state_result = validate_state_for_cd(address.state)
        if not state_valid:
            errors.append(state_result)
        else:
            address.state = state_result  # Update with normalized value

    # Validate ZIP code
    if not address.postal_code:
        errors.append("ZIP code is required")
    else:
        zip_valid, zip_result = validate_zip_for_cd(address.postal_code)
        if not zip_valid:
            errors.append(zip_result)
        else:
            address.postal_code = zip_result  # Update with normalized value

    return len(errors) == 0, errors


def calculate_address_confidence(address: ParsedAddress) -> float:
    """
    Calculate confidence score for a parsed address.

    Args:
        address: ParsedAddress to score

    Returns:
        Float between 0.0 and 1.0
    """
    score = 0.0
    max_score = 4.0  # Base weights for main fields

    # Street address (0.8 weight)
    if address.street:
        score += 0.8
        # Bonus if street has number
        if re.search(r"\d", address.street):
            score += 0.2
    else:
        max_score -= 0.2  # Reduce penalty if no street

    # City (1.0 weight)
    if address.city:
        score += 1.0
        # Bonus for reasonable length
        if len(address.city) >= 3:
            score += 0.1

    # State (1.2 weight - critical for CD)
    if address.state:
        score += 1.0
        # Bonus for valid state code
        if address.state.upper() in US_STATE_CODES:
            score += 0.2

    # ZIP code (1.0 weight)
    if address.postal_code:
        score += 0.8
        # Bonus for valid format
        digits = re.sub(r"[^0-9]", "", address.postal_code)
        if len(digits) in (5, 9):
            score += 0.2

    return min(1.0, score / max_score)


def parse_and_validate_address(
    text: str,
    source_hint: str = None,
) -> tuple[ParsedAddress, list[str], float]:
    """
    Parse address text and validate for CD API.

    Args:
        text: Address text to parse
        source_hint: Optional source hint (e.g., "COPART", "IAA")

    Returns:
        Tuple of (ParsedAddress, validation_errors, confidence_score)
    """
    # Use existing parser
    parsed = extract_address_from_section(text, location_label=source_hint)

    # Validate for CD
    is_valid, errors = validate_address_for_cd(parsed)

    # Calculate confidence
    confidence = calculate_address_confidence(parsed)

    return parsed, errors, confidence


def get_address_parser():
    """Get address parser instance (for consistency with other modules)."""

    # This module uses functions rather than a class, but provide
    # this for API consistency
    class AddressParserWrapper:
        def parse(self, text, source_hint=None):
            return parse_and_validate_address(text, source_hint)

        def validate(self, address):
            return validate_address_for_cd(address)

    return AddressParserWrapper()
