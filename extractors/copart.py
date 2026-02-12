"""Copart document extractor."""

import logging
import re
from datetime import datetime
from typing import Optional

from extractors.address_parser import extract_lines_after_label
from extractors.base import BaseExtractor
from extractors.location_lookup import get_copart_location_name
from models.vehicle import (
    Address,
    AuctionInvoice,
    AuctionSource,
    LocationType,
    Vehicle,
)

logger = logging.getLogger(__name__)


class CopartExtractor(BaseExtractor):
    """Extractor for Copart Sales Receipt/Bill of Sale documents."""

    # Default label patterns for fields (can be overridden by learned rules)
    DEFAULT_LABELS = {
        "pickup_address": [
            r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT",
            r"LOT\s*(?:LOCATION|ADDRESS)",
        ],
        "buyer_name": [
            r"MEMBER",
            r"SOLD\s*TO",
            r"BUYER",
        ],
        "seller_name": [
            r"SELLER",
            r"SOLD\s*(?:BY|THROUGH)",
        ],
    }

    @property
    def source(self) -> AuctionSource:
        return AuctionSource.COPART

    @property
    def indicators(self) -> list:
        return [
            "Copart",
            "SOLD THROUGH COPART",
            "Sales Receipt/Bill of Sale",
            "MEMBER:",
            "PHYSICAL ADDRESS OF LOT",
            "LOT#",
            "copart.com",
        ]

    @property
    def indicator_weights(self) -> dict:
        return {
            "Copart": 3.0,  # Strong but not as unique
            "SOLD THROUGH COPART": 5.0,  # Very strong - unique to Copart
            "Sales Receipt/Bill of Sale": 1.0,  # Generic, reduce weight
            "MEMBER:": 1.5,
            "PHYSICAL ADDRESS OF LOT": 2.0,  # Copart specific
            "LOT#": 1.0,
            "copart.com": 4.0,  # Very strong - unique to Copart
        }

    @property
    def negative_indicators(self) -> list:
        """Indicators that suggest this is NOT a Copart document."""
        return [
            "Insurance Auto Auctions",
            "IAAI",
            "Buyer Receipt",
            "Manheim",
        ]

    def score(self, text: str) -> tuple:
        """Override score to check for negative indicators."""
        base_score, matched = super().score(text)

        # Check for negative indicators - if found, reduce score significantly
        text_lower = text.lower()
        for neg in self.negative_indicators:
            if neg.lower() in text_lower:
                # Strong negative indicator found - this is likely not Copart
                base_score *= 0.3  # Reduce score by 70%
                break

        return base_score, matched

    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        text = self.extract_text(pdf_path)
        if not self.can_extract(text):
            return None

        # Load learned rules before extraction
        self.load_learned_rules()

        invoice = AuctionInvoice(source=self.source, buyer_id="", buyer_name="")

        # Extract buyer ID (MEMBER number) - try multiple patterns
        member_patterns = [
            r"MEMBER[:\s]+(\d+)",
            r"MEMBER\s*:\s*(\d+)",
            r"MEMBER\s*#?\s*(\d+)",
        ]
        for pattern in member_patterns:
            member_match = re.search(pattern, text, re.IGNORECASE)
            if member_match:
                invoice.buyer_id = member_match.group(1)
                break

        # Extract buyer name using learned rules or defaults
        invoice.buyer_name = self._extract_buyer_name(text)

        # Extract seller name using learned rules or defaults
        invoice.seller_name = self._extract_seller_name(text)

        lot_match = re.search(r"LOT#[:\s]+(\d+)", text)
        if lot_match:
            invoice.vehicle_lot = lot_match.group(1)

        date_patterns = [r"Sale[:\s]+(\d{1,2}/\d{1,2}/\d{4})", r"(\d{1,2}/\d{1,2}/\d{4})"]
        for pattern in date_patterns:
            date_match = re.search(pattern, text)
            if date_match:
                date_str = date_match.group(1)
                for fmt in ["%m/%d/%Y", "%m/%d/%y"]:
                    try:
                        invoice.sale_date = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                if invoice.sale_date:
                    break

        # Extract pickup location using learned rules, spatial parsing, or defaults
        pickup_location = self._extract_pickup_location(text, pdf_path)
        if pickup_location:
            invoice.pickup_address = pickup_location

        vehicle = self._extract_vehicle(text)
        if vehicle:
            vehicle.lot_number = invoice.vehicle_lot  # Uses setter for backward compat
            invoice.vehicles.append(vehicle)

        total_patterns = [
            r"Sale\s*Price\s*\$?([\d,]+\.?\d*)",
            r"Net\s*Due\s*\(USD\)\s*\$?([\d,]+\.?\d*)",
        ]
        for pattern in total_patterns:
            total_match = re.search(pattern, text, re.IGNORECASE)
            if total_match:
                try:
                    invoice.total_amount = float(total_match.group(1).replace(",", ""))
                    if invoice.total_amount > 0:
                        break
                except ValueError:
                    pass

        invoice.location_type = LocationType.ONSITE
        return invoice

    def _extract_pickup_location(self, text: str, pdf_path: str = None) -> Optional[Address]:
        """
        Extract pickup address from Copart document.

        Copart documents have a 3-column layout:
        - Column 1: MEMBER (buyer info)
        - Column 2: PHYSICAL ADDRESS OF LOT (pickup location)
        - Column 3: SELLER

        The text extraction mixes columns, so we use targeted patterns.

        CRITICAL: We must filter out numeric IDs (8+ digits) that appear in SELLER column.
        These can get mixed with address text due to PDF column extraction.
        """
        US_STATES = r"AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY"

        def is_valid_street(s: str) -> bool:
            """Check if string is a valid street address (not a numeric ID)."""
            if not s:
                return False
            s = s.strip()
            # Street starting with 6+ digits = likely a seller/member ID
            if re.match(r"^\d{6,}", s):
                return False
            # Street that is only digits = not valid
            if re.match(r"^\d+$", s.replace(" ", "")):
                return False
            # Valid street should have a number followed by letters
            if re.match(r"^\d{1,5}\s+[A-Za-z]", s):
                return True
            # Also accept "US ROUTE" or "STATE HIGHWAY" patterns
            if re.search(r"(?:US\s*)?(?:ROUTE|RT|HWY|HIGHWAY)", s, re.IGNORECASE):
                return True
            return False

        street, city, state, zip_code = None, None, None, None

        # Strategy 0A (HIGHEST PRIORITY): Look for well-formed address with BLVD/AVE/ST etc.
        # Pattern: <number> <street name with suffix> <city> <state> <zip>
        # Example: "4810 N. LAMB BLVD LAS VEGAS NV 89115"
        street_types = r"(?:ROAD|RD|STREET|ST|AVENUE|AVE|DRIVE|DR|HIGHWAY|HWY|BLVD|BOULEVARD|WAY|LANE|LN|COURT|CT|PARKWAY|PKWY)"
        named_addr_pattern = rf"(\d{{1,5}}\s+[A-Z0-9\.\s]+?{street_types})[,\.\s]+([A-Z]{{2,}}(?:\s+[A-Z]{{2,}})?)\s+({US_STATES})\s+(\d{{5}})"
        named_matches = re.findall(named_addr_pattern, text, re.IGNORECASE)

        for match in named_matches:
            potential_street = match[0].strip()
            potential_city = match[1].strip().upper()
            potential_state = match[2].strip().upper()
            potential_zip = match[3].strip()

            # Skip if this looks like buyer/member address
            if any(ind in potential_city for ind in ["AYER", "BROADWAY", "MOTORING", "FITCHBURG"]):
                continue
            if any(
                ind in potential_street.upper()
                for ind in ["AYER", "BROADWAY", "MOTORING", "FITCHBURG", "MEMBER"]
            ):
                continue

            if is_valid_street(potential_street):
                # Clean up street
                potential_street = re.sub(r"\s{2,}", " ", potential_street)
                location_name = get_copart_location_name(
                    city=potential_city,
                    state=potential_state,
                    zip_code=potential_zip,
                    street=potential_street,
                )
                return Address(
                    name=location_name,
                    street=potential_street.title(),
                    city=potential_city.title(),
                    state=potential_state,
                    postal_code=potential_zip,
                )

        # Strategy 0B: Look specifically after "PHYSICAL ADDRESS OF LOT" label
        # This is reliable for Copart documents
        # Pattern: PHYSICAL ADDRESS OF LOT:\n<street>\n<city> <state> <zip>
        physical_section_pattern = (
            r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT[:\s]*\n?\s*([^\n]+)\n\s*([A-Z][A-Za-z\s]+)\s+("
            + US_STATES
            + r")\s+(\d{5})"
        )
        physical_match = re.search(physical_section_pattern, text, re.IGNORECASE)

        if physical_match:
            potential_street = physical_match.group(1).strip()
            potential_city = physical_match.group(2).strip()
            potential_state = physical_match.group(3).strip().upper()
            potential_zip = physical_match.group(4).strip()

            # Validate street is not a numeric ID
            if is_valid_street(potential_street):
                # Clean the street address
                potential_street = re.sub(r"\s{2,}", " ", potential_street)
                # Remove any trailing noise (SELLER info that leaked in)
                potential_street = re.sub(
                    r"\s+(SELLER|SOLD|PROGRESSIVE|GEICO|INSURANCE).*$",
                    "",
                    potential_street,
                    flags=re.IGNORECASE,
                )

                location_name = get_copart_location_name(
                    city=potential_city,
                    state=potential_state,
                    zip_code=potential_zip,
                    street=potential_street,
                )
                return Address(
                    name=location_name,
                    street=potential_street.title(),
                    city=potential_city.title(),
                    state=potential_state,
                    postal_code=potential_zip,
                )

        # Strategy 1: Find address pattern with street type suffix + city state zip on same or nearby line
        # Example: "4810 N. LAMB BLVD LAS VEGAS NV 89115" or "4810 N LAMB BLVD\nLAS VEGAS NV 89115"
        street_types = r"(?:ROAD|RD|STREET|ST|AVENUE|AVE|DRIVE|DR|HIGHWAY|HWY|BLVD|BOULEVARD|WAY|LANE|LN|COURT|CT|PARKWAY|PKWY|ROUTE|RT|MOUND|CIRCLE|CIR|PLACE|PL)"

        # Pattern for address with multi-word city (like "LAS VEGAS")
        full_address_pattern = rf"(\d{{1,5}}\s+[A-Z0-9\.\s]+{street_types})[,\s]+([A-Z][A-Z\s]{{2,20}})\s+({US_STATES})\s+(\d{{5}})"

        all_addresses = re.findall(full_address_pattern, text, re.IGNORECASE)

        # Filter: prefer address that appears near "PHYSICAL ADDRESS OF LOT"
        physical_addr_pos = text.upper().find("PHYSICAL ADDRESS")

        best_match = None
        best_distance = float("inf")

        for match in all_addresses:
            potential_street = match[0].strip()
            potential_city = match[1].strip().upper()
            potential_state = match[2].strip().upper()
            potential_zip = match[3].strip()

            # Use centralized validation
            if not is_valid_street(potential_street):
                continue

            # Skip if this looks like buyer address (check context)
            buyer_indicators = ["AYER", "BROADWAY", "MOTORING", "FITCHBURG", "MEMBER"]
            if any(ind.upper() in potential_street.upper() for ind in buyer_indicators):
                continue
            if any(ind.upper() == potential_city for ind in buyer_indicators):
                continue

            # Calculate distance from "PHYSICAL ADDRESS" marker
            match_text = f"{potential_street} {potential_city} {potential_state} {potential_zip}"
            match_pos = text.upper().find(match_text.upper()[:30])  # First 30 chars

            if physical_addr_pos >= 0 and match_pos >= 0:
                distance = abs(match_pos - physical_addr_pos)
                if distance < best_distance:
                    best_distance = distance
                    best_match = match
            elif best_match is None:
                best_match = match

        if best_match:
            street = best_match[0].strip()
            city = best_match[1].strip()
            state = best_match[2].strip().upper()
            zip_code = best_match[3].strip()

            # Clean up street
            street = re.sub(r"\s{2,}", " ", street)
            street = re.sub(rf"\s+{re.escape(city)}.*$", "", street, flags=re.IGNORECASE).strip()

            location_name = get_copart_location_name(
                city=city,
                state=state,
                zip_code=zip_code,
                street=street,
            )
            return Address(
                name=location_name,
                street=street.title(),
                city=city.title(),
                state=state,
                postal_code=zip_code,
            )

        # In Copart's mixed 3-column layout, the lot address often appears as:
        # "CITY STATE ZIP STREET_NUMBER US ROUTE XX" or similar patterns

        # First, find all US ROUTE/HIGHWAY patterns
        route_pattern = r"(\d+\s+(?:US|STATE)?\s*(?:ROUTE|RT|HWY|HIGHWAY)\s*\d+)"
        route_matches = re.findall(route_pattern, text, re.IGNORECASE)

        # Then find all city/state/zip patterns
        csz_pattern = rf"([A-Z]{{3,}})\s+({US_STATES})\s+(\d{{5}})"
        csz_matches = re.findall(csz_pattern, text, re.IGNORECASE)

        # Try to match a route with its corresponding city/state/zip
        # Look for pattern: CITY STATE ZIP followed by STREET (on same line or nearby)
        combined_pattern = rf"([A-Z]{{3,}})\s+({US_STATES})\s+(\d{{5}})\s+(\d+\s+(?:US|STATE)?\s*(?:ROUTE|RT|HWY|HIGHWAY)\s*\d+)"
        combined_matches = re.findall(combined_pattern, text, re.IGNORECASE)

        for match in combined_matches:
            potential_city = match[0].strip().upper()
            potential_state = match[1].upper()
            potential_zip = match[2]
            potential_street = match[3].strip().upper()

            # Validate - city should be reasonable (not part of buyer address)
            noise_words = [
                "MEMBER",
                "SELLER",
                "BUYER",
                "SOLD",
                "THROUGH",
                "ROAD",
                "RD",
                "STREET",
                "ST",
                "INC",
                "LLC",
                "MOTORING",
                "FITCHBURG",
                "AYER",
                "BROADWAY",
            ]
            if any(noise.lower() in potential_city.lower() for noise in noise_words):
                continue

            street = potential_street
            city = potential_city
            state = potential_state
            zip_code = potential_zip
            break

        # Fallback: If we found a US ROUTE but not the combined pattern, try to associate them
        if not street and route_matches and csz_matches:
            # Filter CSZ matches to exclude buyer-related cities
            for csz in csz_matches:
                potential_city = csz[0].strip().upper()
                potential_state = csz[1].upper()
                potential_zip = csz[2]

                noise_words = [
                    "MEMBER",
                    "SELLER",
                    "BUYER",
                    "SOLD",
                    "THROUGH",
                    "ROAD",
                    "RD",
                    "STREET",
                    "ST",
                    "INC",
                    "LLC",
                    "MOTORING",
                    "FITCHBURG",
                    "AYER",
                    "BROADWAY",
                ]
                if any(noise.lower() in potential_city.lower() for noise in noise_words):
                    continue

                # Take the first valid city and the first route
                city = potential_city
                state = potential_state
                zip_code = potential_zip
                street = route_matches[0].strip().upper()
                break

        # Strategy 2: Look for address pattern after "PHYSICAL ADDRESS OF LOT"
        if not street:
            lot_addr_patterns = [
                # Pattern: street with number, then city/state/zip on next occurrence
                r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT[:\s]*.*?(\d+\s+[A-Z0-9\s]+(?:ROAD|RD|STREET|ST|AVENUE|AVE|DRIVE|DR|HIGHWAY|HWY|BLVD|BOULEVARD|WAY|LANE|LN|COURT|CT|PARKWAY|PKWY)[A-Z\s]*?)(?:\s+SOLD|\s+SELLER|\s+GEICO|\s+[A-Z]{2}\s+\d{5})",
                # Simpler pattern for street
                r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT[:\s]*[^\d]*(\d+\s+[A-Z0-9\s]+(?:SOUTH|NORTH|EAST|WEST|S|N|E|W)?)",
            ]

            for pattern in lot_addr_patterns:
                match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
                if match:
                    street = match.group(1).strip()
                    # Take only the first line (address shouldn't span multiple lines)
                    street = street.split("\n")[0].strip()
                    # Clean up - remove trailing noise aggressively
                    street = re.sub(
                        r"\s*(SOLD|SELLER|GEICO|MEMBER|BROADWAY|THROUGH|COPART).*$",
                        "",
                        street,
                        flags=re.IGNORECASE,
                    )
                    street = re.sub(r"\s+\d{8,}.*$", "", street)  # Remove 8+ digit numbers (IDs)
                    street = re.sub(r"\s{2,}", " ", street)  # Normalize whitespace
                    street = street.strip()
                    if len(street) > 5 and len(street) < 100:
                        break
                    street = None

        # Strategy 3: Look for city/state/zip pattern associated with lot
        if not city:
            # Look for all city/state/zip patterns
            csz_pattern = r"\b([A-Z][A-Z]+)\s+(WV|FL|TX|CA|GA|NC|AZ|NV|OH|PA|NJ|NY|MA|IL|MI|VA|TN|IN|MO|WI|MD|MN|SC|AL|CO|KY|LA|OR|OK|CT|IA|MS|AR|KS|UT|NM|NE|WA|ID|HI|NH|ME|RI|MT|DE|SD|ND|AK|VT|DC|WY)\s+(\d{5})\b"
            matches = re.findall(csz_pattern, text, re.IGNORECASE)

            # Filter out buyer's city (look for patterns that are NOT near MEMBER/buyer info)
            # Typically the lot city appears near "PHYSICAL ADDRESS" or after route numbers
            for match in matches:
                potential_city = match[0].strip().upper()
                potential_state = match[1].upper()
                potential_zip = match[2]

                # Filter out noise cities
                noise_words = [
                    "MEMBER",
                    "SELLER",
                    "BUYER",
                    "BROADWAY",
                    "GEICO",
                    "COPART",
                    "SOLD",
                    "THROUGH",
                    "ROAD",
                    "RD",
                    "STREET",
                    "ST",
                    "AVENUE",
                    "AVE",
                    "FITCHBURG",
                    "AYER",
                    "ROUTE",
                ]
                if any(noise.lower() in potential_city.lower() for noise in noise_words):
                    continue

                # Prefer city that's near a US ROUTE/HIGHWAY mention or appears with numeric street
                # Check if this city appears near a street address
                city_context_pattern = rf"(?:\d+\s+(?:US|STATE)?\s*(?:ROUTE|RT|HWY|HIGHWAY)\s*\d+|PHYSICAL\s*ADDRESS)[^\n]*?{re.escape(potential_city)}"
                if re.search(city_context_pattern, text, re.IGNORECASE):
                    city = potential_city
                    state = potential_state
                    zip_code = potential_zip
                    break

            # If no context match, take first non-noise city
            if not city:
                for match in matches:
                    potential_city = match[0].strip().upper()
                    potential_state = match[1].upper()
                    potential_zip = match[2]

                    noise_words = [
                        "MEMBER",
                        "SELLER",
                        "BUYER",
                        "BROADWAY",
                        "GEICO",
                        "COPART",
                        "SOLD",
                        "THROUGH",
                        "ROAD",
                        "RD",
                        "STREET",
                        "ST",
                        "AVENUE",
                        "AVE",
                        "FITCHBURG",
                        "AYER",
                    ]
                    if any(noise.lower() in potential_city.lower() for noise in noise_words):
                        continue

                    if len(potential_city) >= 3 and len(potential_city) <= 25:
                        city = potential_city
                        state = potential_state
                        zip_code = potential_zip
                        break

        # Strategy 4: If we have street but no city, try to parse city/state/zip
        # from lines near the street address
        if street and not city:
            # Look for "City, ST ZIP" pattern anywhere in text (case-insensitive)
            # This handles formats like "Houston, TX 77001"
            csz_pattern_mixed = r"([A-Za-z][A-Za-z\s\.]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)"
            csz_match = re.search(csz_pattern_mixed, text)
            if csz_match:
                potential_city = csz_match.group(1).strip()
                potential_state = csz_match.group(2).upper()
                potential_zip = csz_match.group(3)

                # Validate it's not a buyer/seller address by checking context
                match_start = csz_match.start()
                context_before = text[max(0, match_start - 100) : match_start].upper()

                # Accept if near lot address markers or not near buyer/member markers
                if (
                    "PHYSICAL ADDRESS" in context_before
                    or "LOT" in context_before
                    or "COPART" in context_before
                    or ("MEMBER" not in context_before and "BUYER" not in context_before)
                ):
                    city = potential_city
                    state = potential_state
                    zip_code = potential_zip

        # If we couldn't find address parts, try the universal method as fallback
        if not street and not city:
            copart_patterns = [
                r"PHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT[:\s]*",
                r"LOT\s*(?:LOCATION|ADDRESS)[:\s]*",
                r"PICKUP\s*(?:LOCATION|ADDRESS)[:\s]*",
            ]
            return self.extract_pickup_address_universal(
                text=text, pdf_path=pdf_path, label_patterns=copart_patterns, source_name="Copart"
            )

        # Build address
        if street or (city and state):
            location_name = get_copart_location_name(
                city=city,
                state=state,
                zip_code=zip_code,
                street=street,
            )
            return Address(
                name=location_name,
                street=street or "",
                city=city or "",
                state=state or "",
                postal_code=zip_code or "",
            )

        return None

    def _parse_address_from_lines_legacy(
        self, lines: list, exclude_patterns: list = None
    ) -> Optional[Address]:
        """Parse address from extracted lines."""
        if not lines:
            return None

        # Filter out excluded patterns
        if exclude_patterns:
            filtered_lines = []
            for line in lines:
                excluded = False
                for pattern in exclude_patterns:
                    if pattern.lower() in line.lower():
                        excluded = True
                        break
                if not excluded:
                    filtered_lines.append(line)
            lines = filtered_lines

        if not lines:
            return None

        # Try to parse address
        street = lines[0] if lines else ""

        # Look for city/state/zip in remaining lines
        city, state, zip_code = "", "", ""
        for line in lines[1:]:
            parsed_city, parsed_state, parsed_zip = self.parse_address(line)
            if parsed_city and parsed_state:
                city, state, zip_code = parsed_city, parsed_state, parsed_zip
                break

        if street or (city and state):
            location_name = get_copart_location_name(
                city=city,
                state=state,
                zip_code=zip_code,
                street=street,
            )
            return Address(
                name=location_name,
                street=street,
                city=city,
                state=state,
                postal_code=zip_code,
            )

        return None

    def _extract_seller_name(self, text: str) -> str:
        """
        Extract seller name using learned rules or defaults.

        Seller in Copart documents is typically an insurance company.
        Located in the rightmost column of the 3-column layout.
        """
        # Check for learned rule
        rule = self.get_learned_rule("seller_name")

        if rule and rule.label_patterns:
            for label_pattern in rule.label_patterns:
                lines = extract_lines_after_label(text, label_pattern, max_lines=3)
                if lines:
                    # Get the first non-excluded line
                    for line in lines:
                        if not rule.should_exclude(line):
                            # Clean up the seller name
                            seller = re.sub(r"\s+\d+.*$", "", line.strip())
                            if len(seller) > 2 and len(seller) < 100:
                                return seller

        # Fallback patterns with more flexibility
        seller_patterns = [
            # "SELLER: <name>"
            r"SELLER[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n|SOLD|$)",
            # "SELLER\n<name>"
            r"SELLER[:\s]*\n([A-Z][A-Za-z\s\-\.]+?)(?:\n|SOLD|$)",
            # "SOLD THROUGH COPART"... then on next section: insurance company
            r"SOLD\s*THROUGH.*\n.*?([A-Z][A-Za-z\s]+(?:INSURANCE|INS|MUTUAL|CASUALTY)[A-Za-z\s]*)",
        ]

        for pattern in seller_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                seller = match.group(1).strip()
                # Clean up trailing numbers, IDs, dates
                seller = re.sub(r"\s+\d+.*$", "", seller)
                seller = re.sub(r"\s{2,}", " ", seller)
                if len(seller) > 2 and len(seller) < 100:
                    return seller

        # Additional pattern: look for insurance company names
        insurance_patterns = [
            r"(PROGRESSIVE\s*(?:CASUALTY\s*)?(?:INSURANCE)?(?:\s*CO)?)",
            r"(GEICO\s*(?:INSURANCE)?)",
            r"(STATE\s*FARM\s*(?:MUTUAL)?(?:\s*AUTOMOBILE)?(?:\s*INSURANCE)?)",
            r"(ALLSTATE\s*(?:INSURANCE)?(?:\s*CO)?)",
            r"(FARMERS\s*(?:INSURANCE)?)",
            r"(USAA\s*(?:CASUALTY)?(?:\s*INSURANCE)?)",
            r"(LIBERTY\s*MUTUAL\s*(?:INSURANCE)?)",
            r"(TRAVELERS\s*(?:INSURANCE)?(?:\s*CO)?)",
            r"(NATIONWIDE\s*(?:MUTUAL)?(?:\s*INSURANCE)?)",
        ]

        for pattern in insurance_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                seller = match.group(1).strip()
                seller = re.sub(r"\s{2,}", " ", seller)
                return seller

        return ""

    def _extract_buyer_name(self, text: str) -> str:
        """
        Extract buyer name from Copart document.

        In Copart documents, the buyer name typically appears on lines BELOW
        the MEMBER: line, not on the same line. Format:
            MEMBER:
            12345678
            BROADWAY MOTORING INC
        or:
            MEMBER: 12345678
            BROADWAY MOTORING INC

        CRITICAL: Must exclude seller-related text that can appear mixed in
        due to PDF 3-column layout extraction.
        """
        # Common insurance/seller company names to exclude from buyer
        SELLER_INDICATORS = [
            "PROGRESSIVE",
            "GEICO",
            "STATE FARM",
            "ALLSTATE",
            "FARMERS",
            "NATIONWIDE",
            "LIBERTY MUTUAL",
            "USAA",
            "TRAVELERS",
            "HARTFORD",
            "INSURANCE",
            "CASUALTY",
            "ASSURANCE",
            "SOLD THROUGH",
            "SELLER",
            "INS CO",
            "MUTUAL INS",
            "AUTO INS",
            "SOLD BY",
            "CONSIGNED",
        ]

        # Field labels that indicate we've passed the buyer section
        SECTION_INDICATORS = [
            "LOT",
            "VIN",
            "VEHICLE",
            "SALE",
            "DATE",
            "RECEIPT",
            "TOTAL",
            "PHYSICAL",
            "ADDRESS",
            "SELLER",
            "SOLD",
            "LOCATION",
            "PRICE",
        ]

        lines = text.split("\n")
        found_member = False
        found_member_number = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Look for MEMBER line
            if not found_member and re.search(r"MEMBER[:\s]*", stripped, re.IGNORECASE):
                found_member = True
                # Check if member number is on same line
                member_num_match = re.search(r"MEMBER[:\s]*(\d+)", stripped, re.IGNORECASE)
                if member_num_match:
                    found_member_number = True
                continue

            if found_member:
                # Skip empty lines
                if not stripped:
                    continue

                # If we haven't found the member number yet, this line might be it
                if not found_member_number and re.match(r"^\d+$", stripped):
                    found_member_number = True
                    continue

                # After member number, the next non-empty line should be the buyer name
                if found_member_number:
                    # Skip if this is a section indicator (we've passed buyer section)
                    if any(ind in stripped.upper() for ind in SECTION_INDICATORS):
                        continue

                    # Skip if this looks like seller/insurance company
                    if any(ind in stripped.upper() for ind in SELLER_INDICATORS):
                        continue

                    # Check if this looks like a company/person name (not a field label or number)
                    if re.match(r"^[A-Z]", stripped) and len(stripped) > 2 and len(stripped) < 100:
                        # Clean up - remove trailing numbers/dates
                        buyer_name = re.sub(r"\s+\d+.*$", "", stripped)
                        # Double check it's not seller-related after cleanup
                        if not any(ind in buyer_name.upper() for ind in SELLER_INDICATORS):
                            return buyer_name

                # Safety: don't search too far
                if i > 20:
                    break

        # Fallback: try traditional patterns
        buyer_name_patterns = [
            r"SOLD\s*TO[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n|MEMBER)",
            r"BUYER[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n|MEMBER)",
            r"Bill\s*To[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n)",
        ]
        for pattern in buyer_name_patterns:
            name_match = re.search(pattern, text, re.IGNORECASE)
            if name_match:
                buyer_name = name_match.group(1).strip()
                buyer_name = re.sub(r"\s+\d+.*$", "", buyer_name)
                if len(buyer_name) > 2 and len(buyer_name) < 100:
                    return buyer_name

        return ""

    def _extract_vehicle(self, text: str) -> Optional[Vehicle]:
        vehicle_patterns = [
            r"VEHICLE[:\s]+(\d{4})\s+([A-Z]+(?:\-[A-Z]+)?)\s+([A-Z0-9\s\-]+?)\s+(BLACK|WHITE|SILVER|GRAY|GREY|RED|BLUE|GREEN|BROWN|GOLD|BEIGE|TAN)",
            r"VEHICLE[:\s]+(\d{4})\s+([A-Z]+(?:\-[A-Z]+)?)\s+([A-Z0-9\s\-]+)",
        ]

        year, make, model, color = None, None, None, None

        for pattern in vehicle_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                year = int(match.group(1))
                make = match.group(2).strip()
                model = match.group(3).strip()
                if len(match.groups()) > 3:
                    color = match.group(4).capitalize()
                break

        vin = self.extract_vin(text)

        if not (year and make and vin):
            return None

        mileage = self.extract_mileage(text)

        return Vehicle(
            vin=vin,
            year=year,
            make=make.title() if make else "Unknown",
            model=model.title() if model else "Unknown",
            color=color,
            mileage=mileage,
            vehicle_type=self.detect_vehicle_type(make or "", model or ""),
        )
