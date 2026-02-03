"""Manheim (Cox Automotive) document extractor."""

import logging
import re
from datetime import datetime
from typing import Optional

from extractors.address_parser import extract_lines_after_label
from extractors.base import BaseExtractor
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
        work_order_match = re.search(r"Work\s*Order\s*#?\s*:?\s*(\d+)", full_text)
        if work_order_match:
            invoice.stock_number = work_order_match.group(1)

        # Extract pickup location with phone (using universal method)
        pickup_location = self._extract_pickup_location(full_text, pdf_path)
        if pickup_location:
            invoice.pickup_address = pickup_location

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
        """
        # Manheim-specific label patterns
        manheim_patterns = [
            r"Pickup\s*Location\s*Address[:\s]*",
            r"Manheim\s*Location[:\s]*",
            r"Vehicle\s*Location[:\s]*",
            r"Release\s*Location[:\s]*",
            r"Pickup\s*Address[:\s]*",
        ]

        return self.extract_pickup_address_universal(
            text=text, pdf_path=pdf_path, label_patterns=manheim_patterns, source_name="Manheim"
        )

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

        # Fallback: try default patterns
        seller_patterns = [
            r"Seller[:\s]*\n([A-Z][A-Za-z\s\-\.]+?)(?:\n|SOLD)",
            r"Seller[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n|SOLD)",
            r"Consignor[:\s]+([A-Z][A-Za-z\s\-\.]+?)(?:\n)",
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
