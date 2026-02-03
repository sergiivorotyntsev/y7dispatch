"""IAA (Insurance Auto Auctions) document extractor."""

import logging
import re
from datetime import datetime
from typing import Optional

from extractors.address_parser import (
    extract_lines_after_label,
)
from extractors.base import BaseExtractor
from models.vehicle import (
    Address,
    AuctionInvoice,
    AuctionSource,
    LocationType,
    Vehicle,
)

logger = logging.getLogger(__name__)


class IAAExtractor(BaseExtractor):
    """Extractor for IAA Buyer Receipt documents."""

    # Default label patterns for fields (can be overridden by learned rules)
    DEFAULT_LABELS = {
        "pickup_address": [
            r"Pick-?Up\s*Location",
            r"Sold\s*At\s*Branch",
            r"Branch\s*Location",
            r"Pickup\s*Address",
        ],
        "buyer_name": [
            r"Buyer\s*Name",
            r"SOLD\s*TO",
            r"Purchaser",
            r"Bill\s*To",
        ],
        "seller_name": [
            r"Seller",
            r"Owner",
            r"Consigner",
        ],
    }

    @property
    def source(self) -> AuctionSource:
        return AuctionSource.IAA

    @property
    def indicators(self) -> list:
        return [
            "Insurance Auto Auctions",
            "Insurance Auto Auctions Corp",
            "Buyer Receipt",
            "IAAI",
            "IAA",
            "Pick-Up Location",
            "StockNo",
            "Sold At Branch",
            "Receipt #",
        ]

    @property
    def indicator_weights(self) -> dict:
        return {
            "Insurance Auto Auctions": 5.0,  # Very strong - unique to IAA
            "Insurance Auto Auctions Corp": 5.0,  # Very strong - unique to IAA
            "Buyer Receipt": 2.0,  # Strong for IAA
            "IAAI": 3.0,
            "IAA": 2.5,  # Be careful - could match in other text
            "Pick-Up Location": 1.5,  # IAA specific format
            "StockNo": 1.5,  # IAA specific
            "Sold At Branch": 2.0,  # IAA specific
            "Receipt #": 1.0,
        }

    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        text = self.extract_text(pdf_path)
        if not self.can_extract(text):
            return None

        # Load learned rules before extraction
        self.load_learned_rules()

        invoice = AuctionInvoice(source=self.source, buyer_id="", buyer_name="")

        # Extract receipt number
        receipt_match = re.search(r"Receipt\s*#\s*(\d+)", text)
        if receipt_match:
            invoice.receipt_number = receipt_match.group(1)

        # Extract buyer ID
        buyer_match = re.search(r"Buyer\s*#\s*(\d+)", text)
        if buyer_match:
            invoice.buyer_id = buyer_match.group(1)

        # Extract buyer name using learned rules or defaults
        invoice.buyer_name = self._extract_buyer_name(text)

        # Extract seller name using learned rules or defaults
        invoice.seller_name = self._extract_seller_name(text)

        # Extract sale date
        date_patterns = [
            r"Sale\s*Date[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
            r"Purchase\s*Date[:\s]+(\d{1,2}/\d{1,2}/\d{4})",
            r"(\d{1,2}/\d{1,2}/\d{4})",
        ]
        for pattern in date_patterns:
            date_match = re.search(pattern, text)
            if date_match:
                try:
                    invoice.sale_date = datetime.strptime(date_match.group(1), "%m/%d/%Y")
                    break
                except ValueError:
                    continue

        # Extract pickup location with phone (using universal method)
        pickup_location = self._extract_pickup_location(text, pdf_path)
        if pickup_location:
            invoice.pickup_address = pickup_location

        # Extract stock number
        stock_match = re.search(r"StockNo\s*(\d{3}-\d+|\d+)", text)
        if stock_match:
            invoice.stock_number = stock_match.group(1)

        # Extract vehicle
        vehicle = self._extract_vehicle(text)
        if vehicle:
            invoice.vehicles.append(vehicle)

        # Extract total amount
        total_patterns = [
            r"Total\s+\$?([\d,]+\.?\d*)\s+\$?([\d,]+\.?\d*)",
            r"Total\s*Due[:\s]*\$?([\d,]+\.?\d*)",
            r"Amount\s*Due[:\s]*\$?([\d,]+\.?\d*)",
        ]
        for pattern in total_patterns:
            total_match = re.search(pattern, text, re.IGNORECASE)
            if total_match:
                try:
                    invoice.total_amount = float(total_match.group(1).replace(",", ""))
                    if invoice.total_amount > 0:
                        break
                except ValueError:
                    continue

        invoice.location_type = LocationType.ONSITE
        return invoice

    def _extract_pickup_location(self, text: str, pdf_path: str = None) -> Optional[Address]:
        """
        Extract pickup address using universal base class method.

        IAA-specific label patterns are passed to the universal extractor.
        """
        # First, try to extract branch/location name for better identification
        location_name = self._extract_branch_name(text) or "IAA"

        # IAA-specific label patterns
        iaa_patterns = [
            r"Pick[-\s]?Up\s*Location[:\s]*",
            r"Sold\s*At\s*Branch[:\s]*",
            r"Branch\s*(?:Location)?[:\s]*",
            r"Pickup\s*Address[:\s]*",
            r"IAAI?\s*[-–]\s*",
        ]

        addr = self.extract_pickup_address_universal(
            text=text, pdf_path=pdf_path, label_patterns=iaa_patterns, source_name=location_name
        )

        return addr

    def _extract_branch_name(self, text: str) -> Optional[str]:
        """Extract IAA branch/location name from document."""
        # Try various patterns to find the branch name
        branch_patterns = [
            r"Sold\s*At\s*Branch[:\s]*([^\n]+)",  # "Sold At Branch: IAA Tampa South"
            r"Branch[:\s]+([A-Z][A-Za-z\s\-]+?)(?:\n|$)",  # "Branch: Tampa South"
            r"IAA\s*[-–]\s*([A-Z][A-Za-z\s]+?)(?:\n|\d|$)",  # "IAA - Tampa South"
            r"Insurance\s+Auto\s+Auctions?\s*[-–]\s*([A-Z][A-Za-z\s]+?)(?:\n|\d|$)",  # Full name variant
            r"Pick[-\s]?Up\s*Location[:\s]*([A-Z][A-Za-z\s\-]+?)(?:,|\n|\d{5})",  # "Pick-Up Location: Tampa South"
        ]

        for pattern in branch_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Clean up common suffixes
                name = re.sub(r"\s*(Branch|Location|Facility)$", "", name, flags=re.IGNORECASE)
                if len(name) > 2 and len(name) < 50:
                    # Add "IAA" prefix if not present
                    if not name.upper().startswith("IAA"):
                        name = f"IAA {name}"
                    return name.strip()

        return None

    def _parse_address_from_lines(
        self,
        lines: list,
        exclude_patterns: list = None,
        source_name: str = None,  # Match base class parameter name
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

        # Also check first line for city/state/zip format
        if not city:
            parsed_city, parsed_state, parsed_zip = self.parse_address(street)
            if parsed_city and parsed_state:
                city, state, zip_code = parsed_city, parsed_state, parsed_zip
                street = ""

        if street or (city and state):
            # Use source_name if provided, otherwise default to "IAA"
            name = source_name or "IAA"
            return Address(
                name=name,
                street=street,
                city=city,
                state=state,
                postal_code=zip_code,
            )

        return None

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
            r"Buyer\s*Name[:\s]+([A-Za-z][A-Za-z\s\-\.]+?)(?:\n|Buyer\s*#)",
            r"SOLD\s*TO[:\s]+([A-Za-z][A-Za-z\s\-\.]+?)(?:\n|\d)",
            r"Purchaser[:\s]+([A-Za-z][A-Za-z\s\-\.]+?)(?:\n|\d)",
            r"Bill\s*To[:\s]+([A-Za-z][A-Za-z\s\-\.]+?)(?:\n)",
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

        # Fallback: try default patterns
        seller_patterns = [
            r"Seller[:\s]*\n([A-Z][A-Za-z\s\-\.]+?)(?:\n|SOLD)",
            r"Seller[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n|SOLD)",
            r"Owner[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n)",
        ]
        for pattern in seller_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                seller = match.group(1).strip()
                seller = re.sub(r"\s+\d+.*$", "", seller)
                if len(seller) > 2 and len(seller) < 100:
                    return seller

        return ""

    def _extract_vehicle(self, text: str) -> Optional[Vehicle]:
        vehicle_pattern = r"(\d{3}-\d+)\s+(?:[A-Z]-\d+\s+)?(\d{4})\s+([A-Z]+)\s+([A-Z0-9\s]+?)\s+(White|Black|Silver|Gray|Grey|Red|Blue|Green|Brown|Gold|Beige|Tan)\s+([\d,]+)\s+([A-HJ-NPR-Z0-9]{17})"
        match = re.search(vehicle_pattern, text)

        if match:
            mileage_str = match.group(6).replace(",", "")
            mileage = int(mileage_str) if mileage_str.isdigit() else None
            make = match.group(3).strip()
            model = match.group(4).strip()

            return Vehicle(
                vin=match.group(7),
                year=int(match.group(2)),
                make=make,
                model=model,
                color=match.group(5),
                mileage=mileage,
                vehicle_type=self.detect_vehicle_type(make, model),
                lot_number=match.group(1),
            )

        vin = self.extract_vin(text)
        if vin:
            year_match = re.search(r"\b(20\d{2}|19\d{2})\s+([A-Z]+)\s+([A-Z0-9\s]+)", text)
            if year_match:
                make = year_match.group(2).strip()
                model = year_match.group(3).strip()
                return Vehicle(
                    vin=vin,
                    year=int(year_match.group(1)),
                    make=make,
                    model=model,
                    vehicle_type=self.detect_vehicle_type(make, model),
                    mileage=self.extract_mileage(text),
                )
        return None
