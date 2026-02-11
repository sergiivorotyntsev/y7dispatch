"""Manheim (Cox Automotive) document extractor."""

import logging
import re
from datetime import datetime
from typing import Optional

from extractors.address_parser import extract_lines_after_label
from extractors.base import BaseExtractor
from extractors.location_lookup import get_manheim_location_name
from models.vehicle import (
    Address,
    AuctionInvoice,
    AuctionSource,
    LocationType,
    Vehicle,
)

logger = logging.getLogger(__name__)


class ManheimExtractor(BaseExtractor):
    """Extractor for Manheim Bill of Sale and Vehicle Release documents."""

    # Default label patterns for fields (can be overridden by learned rules)
    DEFAULT_LABELS = {
        "pickup_address": [
            r"Pickup\s*Location\s*Address",
            r"Manheim\s*Location",
            r"Vehicle\s*Location",
            r"Release\s*Location",
            r"Pickup\s*Address",
        ],
        "buyer_name": [
            r"(?:Name|Buyer)",
            r"SOLD\s*TO",
            r"Purchaser",
            r"Bill\s*To",
            r"Dealer\s*Name",
        ],
        "seller_name": [
            r"Seller",
            r"Consignor",
            r"Owner",
        ],
    }

    @property
    def source(self) -> AuctionSource:
        return AuctionSource.MANHEIM

    @property
    def indicators(self) -> list:
        return [
            "Manheim",
            "Cox Automotive",
            "BILL OF SALE",
            "VEHICLE RELEASE",
            "Manheim.com",
            "Release ID",
            "YMMT",
            "OFFSITE VEHICLE RELEASE",
        ]

    @property
    def indicator_weights(self) -> dict:
        return {
            "Manheim": 3.0,
            "Cox Automotive": 2.0,
            "Manheim.com": 2.5,
            "BILL OF SALE": 1.0,
            "VEHICLE RELEASE": 1.5,
            "Release ID": 1.5,
            "YMMT": 1.0,
            "OFFSITE VEHICLE RELEASE": 2.0,
        }

    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        pages_text = self.extract_pages_text(pdf_path)
        full_text = "\n".join(pages_text)

        if not self.can_extract(full_text):
            return None

        # Load learned rules before extraction
        self.load_learned_rules()

        invoice = AuctionInvoice(source=self.source, buyer_id="", buyer_name="")

        # Extract buyer/account ID
        account_match = re.search(r"Account\s*#?\s*:?\s*(\d+)", full_text)
        if account_match:
            invoice.buyer_id = account_match.group(1)

        # Extract buyer name using learned rules or defaults
        invoice.buyer_name = self._extract_buyer_name(full_text)

        # Extract seller name using learned rules or defaults
        invoice.seller_name = self._extract_seller_name(full_text)

        # Extract sale date (multiple formats)
        date_patterns = [
            (r"Sale\s*Date[:\s]+(\d{1,2}-[A-Z]{3}-\d{4})", "%d-%b-%Y"),
            (r"Sale\s*Date[:\s]+(\d{1,2}/\d{1,2}/\d{4})", "%m/%d/%Y"),
            (r"Purchase\s*Date[:\s]+[A-Za-z]+,\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", "%B %d, %Y"),
            (r"Date[:\s]+(\d{1,2}/\d{1,2}/\d{4})", "%m/%d/%Y"),
        ]
        for pattern, fmt in date_patterns:
            date_match = re.search(pattern, full_text, re.IGNORECASE)
            if date_match:
                date_str = date_match.group(1)
                try:
                    invoice.sale_date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    # Try alternative formats
                    for alt_fmt in ["%d-%b-%Y", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"]:
                        try:
                            invoice.sale_date = datetime.strptime(date_str, alt_fmt)
                            break
                        except ValueError:
                            continue
                    if invoice.sale_date:
                        break

        invoice.location_type = self._detect_location_type(full_text)

        # Extract release ID
        release_match = re.search(r"Release\s*ID[:\s]+([A-Z0-9]+)", full_text)
        if release_match:
            invoice.release_id = release_match.group(1)

        # Extract work order / stock number
        # F2 fix: Use unified vehicle_lot field
        work_order_match = re.search(r"Work\s*Order\s*#?\s*:?\s*(\d+)", full_text)
        if work_order_match:
            invoice.vehicle_lot = work_order_match.group(1)

        # Extract release availability date if different from sale date
        release_date = self._extract_release_available_date(full_text)
        if release_date:
            invoice.release_available_date = release_date

        # Extract pickup location with phone (using universal method)
        pickup_location = self._extract_pickup_location(full_text, pdf_path)
        if pickup_location:
            invoice.pickup_address = pickup_location

        # For OFFSITE releases, extract seller address for pickup_name resolution
        if invoice.location_type == LocationType.OFFSITE:
            seller_address = self._extract_seller_address(full_text)
            if seller_address:
                invoice.seller_address = seller_address

            # Resolve pickup name if not set
            if pickup_location and (not pickup_location.name or pickup_location.name == "Manheim"):
                resolved_name = self._resolve_pickup_name(
                    pickup_location, invoice.seller_name, seller_address
                )
                if resolved_name:
                    pickup_location.name = resolved_name
                    logger.info(f"Resolved OFFSITE pickup name: {resolved_name}")
                else:
                    # Flag that this needs manual lookup
                    logger.warning(
                        f"OFFSITE pickup name needs manual lookup: "
                        f"{pickup_location.street}, {pickup_location.city}, {pickup_location.state}"
                    )

            # Generate release notes for OFFSITE
            invoice.release_notes = self._generate_release_notes(
                invoice.location_type, invoice.seller_name, pickup_location
            )

        # Extract vehicle
        vehicle = self._extract_vehicle(full_text)
        if vehicle:
            invoice.vehicles.append(vehicle)

        # Extract total amount
        total_patterns = [
            r"(?:Final\s*Sale\s*Price|TOTAL|SUB\s*TOTAL)[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"Amount\s*Due[:\s]*\$?\s*([\d,]+\.?\d*)",
            r"Balance\s*Due[:\s]*\$?\s*([\d,]+\.?\d*)",
        ]
        for pattern in total_patterns:
            total_match = re.search(pattern, full_text, re.IGNORECASE)
            if total_match:
                try:
                    invoice.total_amount = float(total_match.group(1).replace(",", ""))
                    if invoice.total_amount > 0:
                        break
                except ValueError:
                    continue

        return invoice

    def _detect_location_type(self, text: str) -> LocationType:
        offsite_indicators = ["OFFSITE VEHICLE RELEASE", "not located at a Manheim facility"]
        for indicator in offsite_indicators:
            if indicator.lower() in text.lower():
                return LocationType.OFFSITE
        return LocationType.ONSITE

    def _extract_pickup_location(self, text: str, pdf_path: str = None) -> Optional[Address]:
        """
        Extract pickup address using universal base class method.

        Manheim-specific label patterns are passed to the universal extractor.
        Then applies location lookup to resolve proper location name.
        """
        # Manheim-specific label patterns
        manheim_patterns = [
            r"Pickup\s*Location\s*Address[:\s]*",
            r"Manheim\s*Location[:\s]*",
            r"Vehicle\s*Location[:\s]*",
            r"Release\s*Location[:\s]*",
            r"Pickup\s*Address[:\s]*",
        ]

        addr = self.extract_pickup_address_universal(
            text=text, pdf_path=pdf_path, label_patterns=manheim_patterns, source_name="Manheim"
        )

        # Apply location lookup for better name resolution
        if addr and (not addr.name or addr.name == "Manheim"):
            lookup_name = get_manheim_location_name(
                city=addr.city,
                state=addr.state,
                zip_code=addr.postal_code,
                street=addr.street,
            )
            if lookup_name:
                addr.name = lookup_name
                logger.debug(f"Resolved pickup location name: {lookup_name}")

        return addr

    def _extract_buyer_name(self, text: str) -> str:
        """Extract buyer name using learned rules or defaults."""
        # Check for learned rule
        rule = self.get_learned_rule("buyer_name")

        if rule and rule.label_patterns:
            for label_pattern in rule.label_patterns:
                lines = extract_lines_after_label(text, label_pattern, max_lines=3)
                if lines:
                    # Get the first non-excluded line that looks like a name
                    for line in lines:
                        if not rule.should_exclude(line):
                            # Clean up the buyer name
                            buyer_name = re.sub(r"\s+\d+.*$", "", line.strip())
                            if (
                                len(buyer_name) > 2
                                and len(buyer_name) < 100
                                and re.match(r"^[A-Z]", buyer_name)
                            ):
                                return buyer_name

        # Fallback: try default patterns
        buyer_name_patterns = [
            r"(?:Name|Buyer)[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n|Account)",
            r"SOLD\s*TO[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n|\d)",
            r"Purchaser[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n|\d)",
            r"Bill\s*To[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n)",
            r"Dealer\s*Name[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n)",
        ]
        for pattern in buyer_name_patterns:
            name_match = re.search(pattern, text, re.IGNORECASE)
            if name_match:
                buyer_name = name_match.group(1).strip()
                buyer_name = re.sub(r"\s+\d+.*$", "", buyer_name)
                if len(buyer_name) > 2 and len(buyer_name) < 100:
                    return buyer_name

        return ""

    def _extract_seller_name(self, text: str) -> str:
        """Extract seller name using learned rules or defaults."""
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

        # Manheim-specific patterns (try first - most reliable)

        # Pattern 1: Line format "OVE [Seller Name] [Buyer Name]"
        ove_pattern = r"\b(?:OVE|SIMULCAST|INLANE|ONLINE)\s+([A-Z][A-Za-z\s\-\.,]+?)\s+(?:BROADWAY|[A-Z]+\s+MOTORING)"
        ove_match = re.search(ove_pattern, text, re.IGNORECASE)
        if ove_match:
            seller = ove_match.group(1).strip()
            if len(seller) > 2 and len(seller) < 100:
                return seller

        # Pattern 2: Invoice line format "BROADWAY MOTORING INC [Seller Name] Cox Automotive"
        invoice_pattern = r"BROADWAY\s+MOTORING\s+INC\s+([A-Z][A-Za-z\s\-\.,]+?)\s+Cox\s*Automotive"
        invoice_match = re.search(invoice_pattern, text, re.IGNORECASE)
        if invoice_match:
            seller = invoice_match.group(1).strip()
            if len(seller) > 2 and len(seller) < 100:
                return seller

        # Pattern 3: REMIT PAYMENT TO section
        remit_pattern = r"REMIT\s*PAYMENT\s*TO[:\s]*\n([A-Z][A-Za-z\s\-\.,]+?)\n\d+"
        remit_match = re.search(remit_pattern, text, re.IGNORECASE)
        if remit_match:
            seller = remit_match.group(1).strip()
            if len(seller) > 2 and len(seller) < 100:
                return seller

        # Fallback: generic seller patterns (less reliable for Manheim)
        seller_patterns = [
            r"Seller[:\s]*\n([A-Z][A-Za-z\s\-\.,]+?)(?:\n|SOLD)",
            r"Seller[:\s]+([A-Z][A-Za-z\s\-\.,]+?)(?:\n|SOLD)",
            r"Consignor[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n)",
        ]
        # Words to exclude - these are not valid seller names
        exclude_words = ["buyer", "purchaser", "sold", "rep", "signature"]

        for pattern in seller_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                seller = match.group(1).strip()
                seller = re.sub(r"\s+\d+.*$", "", seller)
                # Skip if this is an excluded word
                if seller.lower() in exclude_words:
                    continue
                if len(seller) > 2 and len(seller) < 100:
                    return seller

        return ""

    def _extract_vehicle(self, text: str) -> Optional[Vehicle]:
        # YMMT = Year Make Model Trim
        # Model extraction should stop at newline, VIN, Color, Body, or other field markers
        ymmt_patterns = [
            # Pattern that stops at newline or field markers
            r"YMMT\s+(\d{4})\s+([A-Za-z\-]+)\s+([A-Za-z0-9\s\-]+?)(?:\n|VIN|Color|Body|Entry|Odo|Mile)",
            r"Vehicle\s*Information\s*\n.*?(\d{4})\s+([A-Za-z\-]+)\s+([A-Za-z0-9\s\-]+?)(?:\n|VIN)",
            # Fallback - take less greedy match
            r"YMMT\s+(\d{4})\s+([A-Za-z\-]+)\s+([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+)?)",
        ]

        year, make, model = None, None, None

        for pattern in ymmt_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                year = int(match.group(1))
                make = match.group(2).strip()
                model = match.group(3).strip()
                # Clean up model - remove any trailing markers that slipped through
                model = re.sub(
                    r"\s*(VIN|Color|Body|Entry|Odo|Mile).*$", "", model, flags=re.IGNORECASE
                )
                model = model.strip()
                if model:
                    break

        vin = self.extract_vin(text)

        if not (year and make and vin):
            return None

        color = None
        color_match = re.search(r"Color\s+([A-Za-z]+)", text)
        if color_match:
            color = color_match.group(1)

        mileage = self.extract_mileage(text)

        return Vehicle(
            vin=vin,
            year=year,
            make=make,
            model=model or "Unknown",
            color=color,
            mileage=mileage,
            vehicle_type=self.detect_vehicle_type(make, model or ""),
        )

    def _extract_release_available_date(self, text: str) -> Optional[datetime]:
        """
        Extract release availability date if specified in document.

        Looks for patterns like:
        - "Available for release: Jan 15, 2025"
        - "Available after: 01/15/2025"
        - "Release available: 15-JAN-2025"
        """
        release_date_patterns = [
            # "Available for release: Jan 15, 2025"
            (
                r"Available\s*(?:for)?\s*release[:\s]+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
                ["%B %d, %Y", "%b %d, %Y", "%B %d %Y"],
            ),
            # "Available after: 01/15/2025"
            (
                r"Available\s*(?:after|from)[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
                ["%m/%d/%Y"],
            ),
            # "Release available: 15-JAN-2025"
            (
                r"Release\s*available[:\s]+(\d{1,2}-[A-Za-z]{3}-\d{4})",
                ["%d-%b-%Y"],
            ),
            # "Ready for pickup: 01/15/2025"
            (
                r"Ready\s*(?:for)?\s*pickup[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
                ["%m/%d/%Y"],
            ),
        ]

        for pattern, formats in release_date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                for fmt in formats:
                    try:
                        return datetime.strptime(date_str, fmt)
                    except ValueError:
                        continue

        return None

    def _extract_seller_address(self, text: str) -> Optional[Address]:
        """
        Extract seller address for OFFSITE pickup name resolution.

        In OFFSITE releases, the pickup location is often at the seller's address.
        Manheim format has columns: Seller (left) | Buyer (right)
        """
        # Get seller name first
        seller_name = self._extract_seller_name(text)
        if not seller_name:
            return None

        # Pattern for Manheim Bill of Sale format:
        # Line: "OVE [Seller Name] [Buyer Name]"
        # Next: "[Seller Street] [Buyer Street]"
        # Next: "[Seller City, ST ZIP] [Buyer City, ST ZIP]"
        #
        # The seller's address appears in the LEFT column

        # Find the line with seller name, then get address from following lines
        lines = text.split("\n")
        seller_name_upper = seller_name.upper()

        for i, line in enumerate(lines):
            if seller_name_upper in line.upper() and i + 2 < len(lines):
                # Next line should have street addresses
                street_line = lines[i + 1].strip()
                csz_line = lines[i + 2].strip()

                # Extract seller's street (first address in the line)
                # Format: "[Seller Street] [Buyer Street]"
                # Streets are typically separated by multiple spaces or buyer keywords
                street_match = re.match(
                    r"(\d+\s+[A-Z][A-Za-z\s]+(?:DR|ST|AVE|RD|BLVD|WAY|LN|CT|PL))",
                    street_line,
                    re.IGNORECASE,
                )
                if street_match:
                    street = street_match.group(1).strip()

                    # Extract seller's city/state/zip (first in the line)
                    # Format: "CITY, ST ZIP [US] ..."
                    csz_match = re.match(
                        r"([A-Z][A-Za-z\s]+),?\s*([A-Z]{2})\s+(\d{5})",
                        csz_line,
                        re.IGNORECASE,
                    )
                    if csz_match:
                        return Address(
                            name=seller_name,
                            street=street,
                            city=csz_match.group(1).strip(),
                            state=csz_match.group(2).upper(),
                            postal_code=csz_match.group(3),
                        )

        # Fallback: look for seller address in REMIT PAYMENT TO section
        remit_pattern = r"REMIT\s*PAYMENT\s*TO[:\s]*\n([^\n]+)\n([^\n]+)\n([^\n]+)"
        remit_match = re.search(remit_pattern, text, re.IGNORECASE)
        if remit_match:
            name_line = remit_match.group(1).strip()
            street_line = remit_match.group(2).strip()
            csz_line = remit_match.group(3).strip()

            csz_match = re.search(
                r"([A-Za-z\s]+),?\s*([A-Z]{2})\s+(\d{5})", csz_line
            )
            if csz_match:
                return Address(
                    name=name_line,
                    street=street_line,
                    city=csz_match.group(1).strip(),
                    state=csz_match.group(2),
                    postal_code=csz_match.group(3),
                )

        return None

    def _generate_release_notes(
        self,
        location_type: LocationType,
        seller_name: Optional[str],
        pickup_address: Optional[Address],
    ) -> str:
        """
        Generate release notes for Central Dispatch based on location type.

        For OFFSITE releases, includes information about the pickup location
        and any special instructions.
        """
        notes = []

        if location_type == LocationType.OFFSITE:
            notes.append("OFFSITE VEHICLE RELEASE")
            notes.append("Vehicle is not located at a Manheim facility.")
            notes.append("Transporter must present release document at pickup.")

            if seller_name and pickup_address:
                # Check if pickup is at seller location
                if pickup_address.name and seller_name.upper() in pickup_address.name.upper():
                    notes.append(f"Pickup at seller location: {seller_name}")

        return " | ".join(notes) if notes else ""

    def _resolve_pickup_name(
        self,
        pickup_address: Optional[Address],
        seller_name: Optional[str],
        seller_address: Optional[Address],
    ) -> Optional[str]:
        """
        Resolve pickup location name for OFFSITE releases.

        Logic:
        1. If pickup address has a name (not generic "Manheim"), use it
        2. Try lookup from known Manheim/partner locations
        3. If seller address matches pickup address, use seller name
        4. Otherwise, flag for manual lookup

        Returns:
            Location name or None if manual lookup needed
        """
        if not pickup_address:
            return None

        # If pickup already has a specific name, use it
        if pickup_address.name and pickup_address.name != "Manheim":
            return pickup_address.name

        # Try lookup from reference data
        lookup_name = get_manheim_location_name(
            city=pickup_address.city,
            state=pickup_address.state,
            zip_code=pickup_address.postal_code,
            street=pickup_address.street,
        )
        if lookup_name:
            logger.info(f"Resolved pickup name from reference: {lookup_name}")
            return lookup_name

        # Check if seller address matches pickup address
        if seller_name and seller_address:
            # Compare addresses (normalize for comparison)
            pickup_street = (pickup_address.street or "").upper().strip()
            seller_street = (seller_address.street or "").upper().strip()

            pickup_city = (pickup_address.city or "").upper().strip()
            seller_city = (seller_address.city or "").upper().strip()

            pickup_state = (pickup_address.state or "").upper().strip()
            seller_state = (seller_address.state or "").upper().strip()

            # If addresses match, use seller name
            if (
                pickup_street
                and pickup_street == seller_street
                and pickup_city == seller_city
                and pickup_state == seller_state
            ):
                logger.info(f"Resolved pickup name from seller match: {seller_name}")
                return seller_name

            # Also check if just city/state match (for OFFSITE at seller)
            if pickup_city == seller_city and pickup_state == seller_state:
                # Cities match - likely seller location
                logger.info(
                    f"Resolved pickup name from seller city match: {seller_name}"
                )
                return seller_name

        # Flag for manual lookup (needs web search or manual entry)
        return None
