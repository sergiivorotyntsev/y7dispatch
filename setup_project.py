#!/usr/bin/env python3
"""
Setup script for Vehicle Transport Automation project.
Run this file to create all project folders and files.

Usage:
    python setup_project.py
"""

import os

FILES = {
    # ============== models/vehicle.py ==============
    "models/vehicle.py": '''"""Data models for vehicle transport automation."""
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class AuctionSource(Enum):
    IAA = "IAA"
    MANHEIM = "MANHEIM"
    COPART = "COPART"


class LocationType(Enum):
    ONSITE = "ONSITE"
    OFFSITE = "OFFSITE"


class TrailerType(Enum):
    OPEN = "OPEN"
    ENCLOSED = "ENCLOSED"
    DRIVEAWAY = "DRIVEAWAY"


class VehicleType(Enum):
    CAR = "CAR"
    SUV = "SUV"
    TRUCK = "TRUCK"
    VAN = "VAN"
    MOTORCYCLE = "MOTORCYCLE"
    OTHER = "OTHER"


@dataclass
class Address:
    """Physical address."""
    name: Optional[str] = None
    street: Optional[str] = None
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = "US"
    phone: Optional[str] = None
    contact_name: Optional[str] = None

    def to_cd_stop(self, stop_number: int) -> dict:
        """Convert to Central Dispatch stop format."""
        stop = {
            "stopNumber": stop_number,
            "city": self.city,
            "state": self.state,
            "postalCode": self.postal_code,
            "country": self.country
        }
        if self.name:
            stop["locationName"] = self.name
        if self.street:
            stop["address"] = self.street
        if self.phone:
            stop["phone"] = self.phone
        if self.contact_name:
            stop["contactName"] = self.contact_name
        return stop


@dataclass
class Vehicle:
    """Vehicle information."""
    vin: str
    year: int
    make: str
    model: str
    color: Optional[str] = None
    mileage: Optional[int] = None
    vehicle_type: VehicleType = VehicleType.SUV
    is_inoperable: bool = False
    is_oversized: bool = False
    lot_number: Optional[str] = None
    license_plate: Optional[str] = None

    def to_cd_vehicle(self, pickup_stop: int = 1, dropoff_stop: int = 2) -> dict:
        """Convert to Central Dispatch vehicle format."""
        vehicle = {
            "pickupStopNumber": pickup_stop,
            "dropoffStopNumber": dropoff_stop,
            "vin": self.vin,
            "year": self.year,
            "make": self.make,
            "model": self.model,
            "vehicleType": self.vehicle_type.value,
            "isInoperable": self.is_inoperable
        }
        if self.color:
            vehicle["color"] = self.color
        if self.lot_number:
            vehicle["lotNumber"] = self.lot_number
        if self.license_plate:
            vehicle["licensePlate"] = self.license_plate
        return vehicle


@dataclass
class AuctionInvoice:
    """Parsed auction invoice data."""
    source: AuctionSource
    buyer_id: str
    buyer_name: str
    receipt_number: Optional[str] = None
    sale_date: Optional[datetime] = None
    pickup_address: Optional[Address] = None
    location_type: LocationType = LocationType.ONSITE
    release_id: Optional[str] = None
    stock_number: Optional[str] = None
    lot_number: Optional[str] = None
    vehicles: List[Vehicle] = field(default_factory=list)
    total_amount: Optional[float] = None
    notes: Optional[str] = None

    @property
    def reference_id(self) -> str:
        """Get the appropriate reference ID based on auction source."""
        if self.source == AuctionSource.MANHEIM:
            return self.release_id or self.stock_number or ""
        elif self.source == AuctionSource.COPART:
            return self.lot_number or ""
        else:  # IAA
            return self.stock_number or ""


@dataclass
class TransportListing:
    """Central Dispatch listing data."""
    invoice: AuctionInvoice
    delivery_address: Address
    price: float
    trailer_type: TrailerType = TrailerType.OPEN
    available_date: Optional[datetime] = None
    expiration_date: Optional[datetime] = None
    desired_delivery_date: Optional[datetime] = None
    load_specific_terms: Optional[str] = None
    transport_notes: Optional[str] = None
    external_id: Optional[str] = None

    def to_cd_listing(self, marketplace_id: int = 10000) -> dict:
        """Convert to Central Dispatch listing API format."""
        has_inop = any(v.is_inoperable for v in self.invoice.vehicles)
        pickup_stop = self.invoice.pickup_address.to_cd_stop(1) if self.invoice.pickup_address else {}
        delivery_stop = self.delivery_address.to_cd_stop(2)
        vehicles = [v.to_cd_vehicle() for v in self.invoice.vehicles]

        listing = {
            "trailerType": self.trailer_type.value,
            "hasInOpVehicle": has_inop,
            "availableDate": (self.available_date or datetime.utcnow()).strftime("%Y-%m-%dT00:00:00Z"),
            "price": {
                "total": self.price,
                "cod": {
                    "amount": self.price,
                    "paymentMethod": "CASH_CERTIFIED_FUNDS",
                    "paymentLocation": "DELIVERY"
                }
            },
            "stops": [pickup_stop, delivery_stop],
            "vehicles": vehicles,
            "marketplaces": [{"marketplaceId": marketplace_id}]
        }

        if self.expiration_date:
            listing["expirationDate"] = self.expiration_date.strftime("%Y-%m-%dT00:00:00Z")
        if self.desired_delivery_date:
            listing["desiredDeliveryDate"] = self.desired_delivery_date.strftime("%Y-%m-%dT00:00:00Z")
        if self.external_id:
            listing["externalId"] = self.external_id
        if self.load_specific_terms:
            listing["loadSpecificTerms"] = self.load_specific_terms
        if self.transport_notes:
            listing["transportationReleaseNotes"] = self.transport_notes

        if self.invoice.reference_id:
            ref_note = f"Reference: {self.invoice.reference_id}"
            if self.invoice.source == AuctionSource.MANHEIM:
                ref_note = f"Release ID: {self.invoice.reference_id}"
            elif self.invoice.source == AuctionSource.COPART:
                ref_note = f"LOT#: {self.invoice.reference_id}"
            elif self.invoice.source == AuctionSource.IAA:
                ref_note = f"Stock#: {self.invoice.reference_id}"

            location_info = f"{self.invoice.location_type.value} - {ref_note}"
            if "transportationReleaseNotes" in listing:
                listing["transportationReleaseNotes"] = f"{location_info}. {listing['transportationReleaseNotes']}"
            else:
                listing["transportationReleaseNotes"] = location_info

        return listing
''',
    # ============== extractors/__init__.py ==============
    "extractors/__init__.py": '''"""Extractor manager - auto-detects document type and uses appropriate extractor."""
from typing import Optional, List

from extractors.base import BaseExtractor
from extractors.iaa import IAAExtractor
from extractors.manheim import ManheimExtractor
from extractors.copart import CopartExtractor
from models.vehicle import AuctionInvoice


class ExtractorManager:
    """Manages multiple extractors and auto-detects document types."""

    def __init__(self):
        self.extractors: List[BaseExtractor] = [
            IAAExtractor(),
            ManheimExtractor(),
            CopartExtractor()
        ]

    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        """Extract data from a PDF, auto-detecting the document type."""
        for extractor in self.extractors:
            try:
                text = extractor.extract_text(pdf_path)
                if extractor.can_extract(text):
                    result = extractor.extract(pdf_path)
                    if result:
                        return result
            except Exception as e:
                print(f"Extractor {extractor.__class__.__name__} failed: {e}")
                continue
        return None

    def get_extractor_for_text(self, text: str) -> Optional[BaseExtractor]:
        for extractor in self.extractors:
            if extractor.can_extract(text):
                return extractor
        return None


def extract_from_pdf(pdf_path: str) -> Optional[AuctionInvoice]:
    """Extract auction invoice data from a PDF file."""
    manager = ExtractorManager()
    return manager.extract(pdf_path)
''',
    # ============== extractors/base.py ==============
    "extractors/base.py": '''"""Base extractor class for auction invoices."""
import re
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple
import pdfplumber

from models.vehicle import AuctionInvoice, Vehicle, Address, AuctionSource, LocationType, VehicleType


class BaseExtractor(ABC):
    """Base class for auction document extractors."""

    @property
    @abstractmethod
    def source(self) -> AuctionSource:
        pass

    @abstractmethod
    def can_extract(self, text: str) -> bool:
        pass

    @abstractmethod
    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        pass

    def extract_text(self, pdf_path: str) -> str:
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\\n"
        return text

    def extract_pages_text(self, pdf_path: str) -> List[str]:
        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                pages.append(page_text or "")
        return pages

    @staticmethod
    def clean_text(text: str) -> str:
        text = re.sub(r'\\s+', ' ', text)
        return text.strip()

    @staticmethod
    def extract_vin(text: str) -> Optional[str]:
        pattern = r'\\b[A-HJ-NPR-Z0-9]{17}\\b'
        match = re.search(pattern, text)
        return match.group(0) if match else None

    @staticmethod
    def extract_phone(text: str) -> Optional[str]:
        patterns = [
            r'\\(?\\d{3}\\)?[-.\\s]?\\d{3}[-.\\s]?\\d{4}',
            r'\\d{3}[-.\\s]\\d{3}[-.\\s]\\d{4}'
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None

    @staticmethod
    def extract_zip(text: str) -> Optional[str]:
        pattern = r'\\b\\d{5}(?:-\\d{4})?\\b'
        match = re.search(pattern, text)
        return match.group(0) if match else None

    @staticmethod
    def parse_address(text: str) -> Tuple[str, str, str]:
        pattern = r'([A-Za-z\\s]+)[,\\s]+([A-Z]{2})[\\s.,]+(\\d{5}(?:-\\d{4})?)'
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip(), match.group(2), match.group(3)
        return "", "", ""

    @staticmethod
    def detect_vehicle_type(make: str, model: str) -> VehicleType:
        combined = f"{make} {model}".upper()

        suv_keywords = ['SUV', 'XC90', 'XC60', 'XC40', 'DURANGO', 'CHEROKEE',
                       'TUCSON', 'KONA', 'EXPLORER', 'TAHOE', 'SUBURBAN']
        car_keywords = ['SEDAN', 'COUPE', 'HARDTOP', 'GIULIA', 'E 300', 'CAMRY', 'ACCORD']
        truck_keywords = ['TRUCK', 'F-150', 'SILVERADO', 'RAM', 'TUNDRA']
        van_keywords = ['VAN', 'CARAVAN', 'ODYSSEY', 'SIENNA']

        for keyword in suv_keywords:
            if keyword in combined:
                return VehicleType.SUV
        for keyword in car_keywords:
            if keyword in combined:
                return VehicleType.CAR
        for keyword in truck_keywords:
            if keyword in combined:
                return VehicleType.TRUCK
        for keyword in van_keywords:
            if keyword in combined:
                return VehicleType.VAN

        return VehicleType.SUV

    @staticmethod
    def extract_year(text: str) -> Optional[int]:
        pattern = r'\\b(19|20)\\d{2}\\b'
        match = re.search(pattern, text)
        if match:
            return int(match.group(0))
        return None

    @staticmethod
    def extract_mileage(text: str) -> Optional[int]:
        patterns = [
            r'Mileage[:\\s]+(\\d{1,3}(?:,\\d{3})*|\\d+)',
            r'(\\d{1,3}(?:,\\d{3})*)\\s*(?:Miles|Mi\\.?)'
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                mileage = match.group(1).replace(',', '')
                return int(mileage)
        return None

    @staticmethod
    def extract_amount(text: str, keyword: str = None) -> Optional[float]:
        if keyword:
            pattern = rf'{keyword}[:\\s]*\\$?\\s*([\\d,]+(?:\\.\\d{2})?)'
        else:
            pattern = r'\\$\\s*([\\d,]+(?:\\.\\d{2})?)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = match.group(1).replace(',', '')
            return float(amount)
        return None
''',
    # ============== extractors/iaa.py ==============
    "extractors/iaa.py": '''"""IAA (Insurance Auto Auctions) document extractor."""
import re
from typing import Optional
from datetime import datetime

from extractors.base import BaseExtractor
from models.vehicle import AuctionInvoice, Vehicle, Address, AuctionSource, LocationType, VehicleType


class IAAExtractor(BaseExtractor):
    """Extractor for IAA Buyer Receipt documents."""

    @property
    def source(self) -> AuctionSource:
        return AuctionSource.IAA

    def can_extract(self, text: str) -> bool:
        indicators = ['Insurance Auto Auctions', 'Buyer Receipt', 'IAAI BRE', 'IAA Doc']
        return any(ind.lower() in text.lower() for ind in indicators)

    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        text = self.extract_text(pdf_path)
        if not self.can_extract(text):
            return None

        invoice = AuctionInvoice(source=self.source, buyer_id="", buyer_name="")

        receipt_match = re.search(r'Receipt\\s*#\\s*(\\d+)', text)
        if receipt_match:
            invoice.receipt_number = receipt_match.group(1)

        buyer_match = re.search(r'Buyer\\s*#\\s*(\\d+)', text)
        if buyer_match:
            invoice.buyer_id = buyer_match.group(1)

        buyer_name_match = re.search(r'Buyer\\s*Name\\s+([A-Za-z\\s]+(?:Inc|LLC|Corp)?)', text)
        if buyer_name_match:
            invoice.buyer_name = buyer_name_match.group(1).strip()

        date_match = re.search(r'Sale\\s*Date\\s+(\\d{1,2}/\\d{1,2}/\\d{4})', text)
        if date_match:
            try:
                invoice.sale_date = datetime.strptime(date_match.group(1), '%m/%d/%Y')
            except ValueError:
                pass

        pickup_location = self._extract_pickup_location(text)
        if pickup_location:
            invoice.pickup_address = pickup_location

        stock_match = re.search(r'StockNo\\s*(\\d{3}-\\d+|\\d+)', text)
        if stock_match:
            invoice.stock_number = stock_match.group(1)

        vehicle = self._extract_vehicle(text)
        if vehicle:
            invoice.vehicles.append(vehicle)

        total_match = re.search(r'Total\\s+\\$?([\\d,]+\\.?\\d*)\\s+\\$?([\\d,]+\\.?\\d*)', text)
        if total_match:
            try:
                invoice.total_amount = float(total_match.group(1).replace(',', ''))
            except ValueError:
                pass

        invoice.location_type = LocationType.ONSITE
        return invoice

    def _extract_pickup_location(self, text: str) -> Optional[Address]:
        location_pattern = r'Pick-Up Location[:\\s]*([A-Za-z/\\s\\-\\.]+)\\n([^\\n]+)\\n([A-Za-z\\s]+)\\s+([A-Z]{2})\\s+(\\d{5})'
        match = re.search(location_pattern, text)

        if match:
            return Address(
                name=match.group(1).strip(),
                street=match.group(2).strip(),
                city=match.group(3).strip(),
                state=match.group(4),
                postal_code=match.group(5),
                country="US"
            )
        return None

    def _extract_vehicle(self, text: str) -> Optional[Vehicle]:
        vehicle_pattern = r'(\\d{3}-\\d+)\\s+(?:[A-Z]-\\d+\\s+)?(\\d{4})\\s+([A-Z]+)\\s+([A-Z0-9\\s]+?)\\s+(White|Black|Silver|Gray|Grey|Red|Blue|Green|Brown|Gold|Beige|Tan)\\s+([\\d,]+)\\s+([A-HJ-NPR-Z0-9]{17})'
        match = re.search(vehicle_pattern, text)

        if match:
            mileage_str = match.group(6).replace(',', '')
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
                lot_number=match.group(1)
            )

        vin = self.extract_vin(text)
        if vin:
            year_match = re.search(r'\\b(20\\d{2}|19\\d{2})\\s+([A-Z]+)\\s+([A-Z0-9\\s]+)', text)
            if year_match:
                make = year_match.group(2).strip()
                model = year_match.group(3).strip()
                return Vehicle(
                    vin=vin,
                    year=int(year_match.group(1)),
                    make=make,
                    model=model,
                    vehicle_type=self.detect_vehicle_type(make, model),
                    mileage=self.extract_mileage(text)
                )
        return None
''',
    # ============== extractors/manheim.py ==============
    "extractors/manheim.py": '''"""Manheim (Cox Automotive) document extractor."""
import re
from typing import Optional
from datetime import datetime

from extractors.base import BaseExtractor
from models.vehicle import AuctionInvoice, Vehicle, Address, AuctionSource, LocationType, VehicleType


class ManheimExtractor(BaseExtractor):
    """Extractor for Manheim Bill of Sale and Vehicle Release documents."""

    @property
    def source(self) -> AuctionSource:
        return AuctionSource.MANHEIM

    def can_extract(self, text: str) -> bool:
        indicators = ['Manheim', 'Cox Automotive', 'BILL OF SALE', 'VEHICLE RELEASE', 'Manheim.com']
        return any(ind.lower() in text.lower() for ind in indicators)

    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        pages_text = self.extract_pages_text(pdf_path)
        full_text = '\\n'.join(pages_text)

        if not self.can_extract(full_text):
            return None

        invoice = AuctionInvoice(source=self.source, buyer_id="", buyer_name="")

        account_match = re.search(r'Account\\s*#?\\s*:?\\s*(\\d+)', full_text)
        if account_match:
            invoice.buyer_id = account_match.group(1)

        buyer_match = re.search(r'(?:Name|Buyer)\\s+([A-Z][A-Za-z\\s]+(?:INC|LLC|CORP|Inc|Llc|Corp)?)', full_text)
        if buyer_match:
            invoice.buyer_name = buyer_match.group(1).strip()

        date_patterns = [
            r'Sale\\s*Date\\s+(\\d{1,2}-[A-Z]{3}-\\d{4})',
            r'Sale\\s*Date\\s+(\\d{1,2}/\\d{1,2}/\\d{4})',
            r'Purchase\\s*Date\\s+[A-Za-z]+,\\s+([A-Za-z]+\\s+\\d{1,2},\\s+\\d{4})'
        ]
        for pattern in date_patterns:
            date_match = re.search(pattern, full_text, re.IGNORECASE)
            if date_match:
                date_str = date_match.group(1)
                for fmt in ['%d-%b-%Y', '%m/%d/%Y', '%b %d, %Y']:
                    try:
                        invoice.sale_date = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                break

        invoice.location_type = self._detect_location_type(full_text)

        release_match = re.search(r'Release\\s*ID\\s+([A-Z0-9]+)', full_text)
        if release_match:
            invoice.release_id = release_match.group(1)

        work_order_match = re.search(r'Work\\s*Order\\s*#?\\s*:?\\s*(\\d+)', full_text)
        if work_order_match:
            invoice.stock_number = work_order_match.group(1)

        pickup_location = self._extract_pickup_location(full_text)
        if pickup_location:
            invoice.pickup_address = pickup_location

        vehicle = self._extract_vehicle(full_text)
        if vehicle:
            invoice.vehicles.append(vehicle)

        total_match = re.search(r'(?:Final\\s*Sale\\s*Price|TOTAL|SUB\\s*TOTAL)\\s*\\$?\\s*([\\d,]+\\.?\\d*)', full_text, re.IGNORECASE)
        if total_match:
            try:
                invoice.total_amount = float(total_match.group(1).replace(',', ''))
            except ValueError:
                pass

        return invoice

    def _detect_location_type(self, text: str) -> LocationType:
        offsite_indicators = ['OFFSITE VEHICLE RELEASE', 'not located at a Manheim facility']
        for indicator in offsite_indicators:
            if indicator.lower() in text.lower():
                return LocationType.OFFSITE
        return LocationType.ONSITE

    def _extract_pickup_location(self, text: str) -> Optional[Address]:
        pickup_patterns = [
            r'Pickup\\s*Location\\s+Address\\s+([A-Za-z\\s\\-]+)\\n\\s*(\\d+[A-Za-z0-9\\s\\.\\-]+)\\n\\s*([A-Za-z\\s]+),?\\s*([A-Z]{2})\\s+(\\d{5}(?:-\\d{4})?)',
            r'Address\\s+(\\d+[A-Za-z0-9\\s\\.\\-]+)\\n\\s*([A-Za-z\\s]+),?\\s*([A-Z]{2})\\s+(\\d{5}(?:-\\d{4})?)',
        ]

        for pattern in pickup_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 5:
                    return Address(
                        name=groups[0].strip(),
                        street=groups[1].strip(),
                        city=groups[2].strip(),
                        state=groups[3],
                        postal_code=groups[4],
                        country="US"
                    )
                elif len(groups) == 4:
                    return Address(
                        street=groups[0].strip(),
                        city=groups[1].strip(),
                        state=groups[2],
                        postal_code=groups[3],
                        country="US"
                    )
        return None

    def _extract_vehicle(self, text: str) -> Optional[Vehicle]:
        ymmt_patterns = [
            r'YMMT\\s+(\\d{4})\\s+([A-Za-z\\-]+)\\s+([A-Za-z0-9\\s\\-]+)',
            r'Vehicle\\s*Information\\s*\\n.*?(\\d{4})\\s+([A-Za-z\\-]+)\\s+([A-Za-z0-9\\s\\-]+)',
        ]

        year, make, model = None, None, None

        for pattern in ymmt_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                year = int(match.group(1))
                make = match.group(2).strip()
                model = match.group(3).strip()
                break

        vin = self.extract_vin(text)

        if not (year and make and vin):
            return None

        color = None
        color_match = re.search(r'Color\\s+([A-Za-z]+)', text)
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
            vehicle_type=self.detect_vehicle_type(make, model or "")
        )
''',
    # ============== extractors/copart.py ==============
    "extractors/copart.py": '''"""Copart document extractor."""
import re
from typing import Optional
from datetime import datetime

from extractors.base import BaseExtractor
from models.vehicle import AuctionInvoice, Vehicle, Address, AuctionSource, LocationType, VehicleType


class CopartExtractor(BaseExtractor):
    """Extractor for Copart Sales Receipt/Bill of Sale documents."""

    @property
    def source(self) -> AuctionSource:
        return AuctionSource.COPART

    def can_extract(self, text: str) -> bool:
        indicators = ['Copart', 'Sales Receipt/Bill of Sale', 'SOLD THROUGH COPART', 'MEMBER:', 'PHYSICAL ADDRESS OF LOT']
        return any(ind.lower() in text.lower() for ind in indicators)

    def extract(self, pdf_path: str) -> Optional[AuctionInvoice]:
        text = self.extract_text(pdf_path)
        if not self.can_extract(text):
            return None

        invoice = AuctionInvoice(source=self.source, buyer_id="", buyer_name="")

        member_match = re.search(r'MEMBER[:\\s]+(\\d+)', text)
        if member_match:
            invoice.buyer_id = member_match.group(1)

        lot_match = re.search(r'LOT#[:\\s]+(\\d+)', text)
        if lot_match:
            invoice.lot_number = lot_match.group(1)

        date_patterns = [r'Sale[:\\s]+(\\d{1,2}/\\d{1,2}/\\d{4})', r'(\\d{1,2}/\\d{1,2}/\\d{4})']
        for pattern in date_patterns:
            date_match = re.search(pattern, text)
            if date_match:
                date_str = date_match.group(1)
                for fmt in ['%m/%d/%Y', '%m/%d/%y']:
                    try:
                        invoice.sale_date = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                if invoice.sale_date:
                    break

        pickup_location = self._extract_pickup_location(text)
        if pickup_location:
            invoice.pickup_address = pickup_location

        vehicle = self._extract_vehicle(text)
        if vehicle:
            vehicle.lot_number = invoice.lot_number
            invoice.vehicles.append(vehicle)

        total_patterns = [r'Sale\\s*Price\\s*\\$?([\\d,]+\\.?\\d*)', r'Net\\s*Due\\s*\\(USD\\)\\s*\\$?([\\d,]+\\.?\\d*)']
        for pattern in total_patterns:
            total_match = re.search(pattern, text, re.IGNORECASE)
            if total_match:
                try:
                    invoice.total_amount = float(total_match.group(1).replace(',', ''))
                    if invoice.total_amount > 0:
                        break
                except ValueError:
                    pass

        invoice.location_type = LocationType.ONSITE
        return invoice

    def _extract_pickup_location(self, text: str) -> Optional[Address]:
        patterns = [
            r'PHYSICAL\\s*ADDRESS\\s*(?:OF\\s*)?LOT[:\\s]+([^\\n]+)\\n\\s*([A-Za-z\\s]+)\\s+([A-Z]{2})\\s+(\\d{5})',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                groups = match.groups()
                return Address(
                    street=groups[0].strip(),
                    city=groups[1].strip(),
                    state=groups[2],
                    postal_code=groups[3],
                    country="US",
                    name="Copart"
                )
        return None

    def _extract_vehicle(self, text: str) -> Optional[Vehicle]:
        vehicle_patterns = [
            r'VEHICLE[:\\s]+(\\d{4})\\s+([A-Z]+(?:\\-[A-Z]+)?)\\s+([A-Z0-9\\s\\-]+?)\\s+(BLACK|WHITE|SILVER|GRAY|GREY|RED|BLUE|GREEN|BROWN|GOLD|BEIGE|TAN)',
            r'VEHICLE[:\\s]+(\\d{4})\\s+([A-Z]+(?:\\-[A-Z]+)?)\\s+([A-Z0-9\\s\\-]+)',
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
            vehicle_type=self.detect_vehicle_type(make or "", model or "")
        )
''',
    # ============== extractors/gate_pass.py ==============
    "extractors/gate_pass.py": '''"""Gate Pass / PIN extractor from email body."""
import re
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class GatePassInfo:
    code: str
    raw_match: str
    source_hint: Optional[str] = None


class GatePassExtractor:
    """Extracts gate pass/PIN codes from email body text."""

    PATTERNS = [
        (r'Gate\\s*Pass\\s*(?:Pin|Code|#|Number)?\\s*[:#]?\\s*([A-Za-z0-9\\-]{4,20})', 'generic'),
        (r'(?:IAA|IAAI)\\s*(?:Gate\\s*)?Pass\\s*[:#]?\\s*([A-Za-z0-9\\-]{4,20})', 'IAA'),
        (r'(?:Release|Lot)\\s*(?:Code|#|Pin)\\s*[:#]?\\s*([A-Za-z0-9\\-]{4,20})', 'COPART'),
        (r'(?:Release\\s*ID|Pickup\\s*Code|Pickup\\s*Pin)\\s*[:#]?\\s*([A-Za-z0-9\\-]{4,20})', 'MANHEIM'),
        (r'(?:Pickup|Gate|Access)\\s*PIN\\s*[:#]?\\s*([A-Za-z0-9\\-]{4,20})', 'generic'),
        (r'Auth(?:orization)?\\s*Code\\s*[:#]?\\s*([A-Za-z0-9\\-]{4,20})', 'generic'),
        (r'Pass\\s*(?:Code|#)\\s*[:#]?\\s*([A-Za-z0-9\\-]{4,20})', 'generic'),
        (r'\\b(?:code|pin)\\s*[:#]\\s*([A-Za-z0-9\\-]{4,20})\\b', 'generic'),
    ]

    @classmethod
    def extract_from_text(cls, text: str) -> List[GatePassInfo]:
        results = []
        seen_codes = set()

        for pattern, source_hint in cls.PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                code = match.group(1).strip().upper()
                if code in seen_codes:
                    continue
                if cls._is_valid_code(code):
                    seen_codes.add(code)
                    results.append(GatePassInfo(
                        code=code,
                        raw_match=match.group(0).strip(),
                        source_hint=source_hint if source_hint != 'generic' else None
                    ))
        return results

    @classmethod
    def extract_primary(cls, text: str) -> Optional[str]:
        results = cls.extract_from_text(text)
        if not results:
            return None
        for r in results:
            if r.source_hint:
                return r.code
        return results[0].code

    @staticmethod
    def _is_valid_code(code: str) -> bool:
        if len(code) < 4 or len(code) > 20:
            return False
        if not re.match(r'^[A-Z0-9\\-]+$', code):
            return False
        common_words = {'CODE', 'PASS', 'GATE', 'PIN', 'NONE', 'NULL', 'TEST'}
        if code in common_words:
            return False
        return True


def extract_text_from_email_body(msg) -> str:
    """Extract plain text from email message body."""
    text_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    text_parts.append(payload.decode(charset, errors='replace'))
            elif content_type == 'text/html':
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    html = payload.decode(charset, errors='replace')
                    text_parts.append(_html_to_text(html))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or 'utf-8'
            content = payload.decode(charset, errors='replace')
            if msg.get_content_type() == 'text/html':
                content = _html_to_text(content)
            text_parts.append(content)

    return '\\n\\n'.join(text_parts)


def _html_to_text(html: str) -> str:
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<br\\s*/?>', '\\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    return text.strip()
''',
    # ============== services/clickup.py ==============
    "services/clickup.py": '''"""ClickUp API client for creating vehicle pickup tasks."""
import os
import json
import logging
import time
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import requests

logger = logging.getLogger(__name__)


@dataclass
class ClickUpTask:
    name: str
    description: str
    priority: int = 3
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None


class ClickUpClient:
    API_BASE = "https://api.clickup.com/api/v2"

    def __init__(self, token: str, list_id: str, timeout: int = 30):
        self.token = token
        self.list_id = list_id
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": token,
            "Content-Type": "application/json"
        })

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, retries: int = 3) -> requests.Response:
        url = f"{self.API_BASE}{endpoint}"
        for attempt in range(retries):
            try:
                response = self._session.request(method=method, url=url, json=data, timeout=self.timeout)
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    time.sleep(retry_after)
                    continue
                return response
            except requests.RequestException as e:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise
        raise ClickUpAPIError("Max retries exceeded")

    def create_task(self, task: ClickUpTask) -> Dict[str, Any]:
        payload = {"name": task.name, "description": task.description, "priority": task.priority}
        if task.tags:
            payload["tags"] = task.tags

        response = self._make_request("POST", f"/list/{self.list_id}/task", data=payload)

        if response.status_code in (200, 201):
            data = response.json()
            return {"success": True, "task_id": data.get("id"), "url": data.get("url"), "response": data}
        else:
            raise ClickUpAPIError(f"Failed to create task: {response.text}")

    def validate_credentials(self) -> bool:
        try:
            response = self._make_request("GET", "/user")
            return response.status_code == 200
        except Exception:
            return False


class ClickUpAPIError(Exception):
    pass


def create_client_from_env() -> ClickUpClient:
    token = os.environ.get("CLICKUP_TOKEN")
    list_id = os.environ.get("CLICKUP_LIST_ID")
    if not token:
        raise ValueError("CLICKUP_TOKEN environment variable required")
    if not list_id:
        raise ValueError("CLICKUP_LIST_ID environment variable required")
    return ClickUpClient(token=token, list_id=list_id)


def create_vehicle_pickup_task(
    client: ClickUpClient,
    vin: str,
    lot_number: str,
    vehicle_desc: str,
    pickup_address: str,
    gate_pass: Optional[str] = None,
    source: str = "UNKNOWN",
    additional_notes: Optional[str] = None
) -> Dict[str, Any]:
    name = f"Pickup: {vehicle_desc} | LOT {lot_number}"

    desc_parts = [
        f"**Source:** {source}",
        f"**VIN:** {vin}",
        f"**Lot #:** {lot_number}",
        f"**Vehicle:** {vehicle_desc}",
        "",
        f"**Pickup Address:**",
        pickup_address
    ]

    if gate_pass:
        desc_parts.insert(4, f"**Gate Pass:** {gate_pass}")

    if additional_notes:
        desc_parts.extend(["", "**Notes:**", additional_notes])

    task = ClickUpTask(name=name, description="\\n".join(desc_parts), priority=3, tags=[source.lower()])
    return client.create_task(task)
''',
    # ============== services/idempotency.py ==============
    "services/idempotency.py": '''"""Idempotency storage for email deduplication."""
import sqlite3
import hashlib
import logging
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class IdempotencyStore:
    def __init__(self, db_path: str = "processed_emails.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT UNIQUE NOT NULL,
                    thread_root_id TEXT,
                    message_id TEXT,
                    attachment_hash TEXT,
                    source_type TEXT,
                    result_type TEXT,
                    result_id TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)
            conn.commit()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def compute_attachment_hash(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def extract_thread_root_id(message_id: Optional[str], in_reply_to: Optional[str], references: Optional[str]) -> str:
        if references:
            refs = references.strip().split()
            if refs:
                return refs[0].strip('<>')
        if in_reply_to:
            return in_reply_to.strip('<>')
        if message_id:
            return message_id.strip('<>')
        return f"unknown-{datetime.utcnow().isoformat()}"

    def generate_idempotency_key(self, thread_root_id: str, attachment_hash: str) -> str:
        return f"{thread_root_id}:{attachment_hash}"

    def is_processed(self, idempotency_key: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT 1 FROM processed_items WHERE idempotency_key = ?", (idempotency_key,))
            return cursor.fetchone() is not None

    def is_attachment_processed_in_thread(self, thread_root_id: str, attachment_hash: str) -> Tuple[bool, Optional[str]]:
        key = self.generate_idempotency_key(thread_root_id, attachment_hash)
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT result_id FROM processed_items WHERE idempotency_key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return True, row['result_id']
            return False, None

    def mark_processed(self, thread_root_id: str, message_id: str, attachment_hash: str, source_type: str, result_type: str, result_id: str, metadata: Optional[str] = None) -> bool:
        key = self.generate_idempotency_key(thread_root_id, attachment_hash)
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """INSERT INTO processed_items (idempotency_key, thread_root_id, message_id, attachment_hash, source_type, result_type, result_id, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (key, thread_root_id, message_id, attachment_hash, source_type, result_type, result_id, metadata)
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False
''',
    # ============== services/central_dispatch.py ==============
    "services/central_dispatch.py": '''"""Central Dispatch API client service."""
import os
import time
import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import requests

from models.vehicle import TransportListing

logger = logging.getLogger(__name__)


@dataclass
class TokenInfo:
    access_token: str
    expires_at: datetime
    refresh_token: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() >= (self.expires_at - timedelta(minutes=5))


class CentralDispatchClient:
    PROD_TOKEN_URL = "https://id.centraldispatch.com/connect/token"
    PROD_API_BASE = "https://marketplace-api.centraldispatch.com"
    PROD_MARKETPLACE_ID = 10000
    API_VERSION_HEADER = "application/vnd.coxauto.v2+json"

    def __init__(self, client_id: str, client_secret: str, marketplace_id: Optional[int] = None, is_test: bool = False):
        self.client_id = client_id
        self.client_secret = client_secret
        self.marketplace_id = marketplace_id or self.PROD_MARKETPLACE_ID
        self.token_url = self.PROD_TOKEN_URL
        self.api_base = self.PROD_API_BASE
        self._token_info: Optional[TokenInfo] = None
        self._session = requests.Session()

    def _get_access_token(self) -> str:
        if self._token_info and not self._token_info.is_expired:
            return self._token_info.access_token

        data = {"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret, "scope": "marketplace"}
        response = self._session.post(self.token_url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
        response.raise_for_status()

        token_data = response.json()
        self._token_info = TokenInfo(
            access_token=token_data["access_token"],
            expires_at=datetime.utcnow() + timedelta(seconds=token_data.get("expires_in", 3600))
        )
        return self._token_info.access_token

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None, extra_headers: Optional[Dict[str, str]] = None, retries: int = 3) -> requests.Response:
        url = f"{self.api_base}{endpoint}"
        for attempt in range(retries):
            try:
                token = self._get_access_token()
                headers = {"Authorization": f"Bearer {token}", "Content-Type": self.API_VERSION_HEADER, "Accept": "application/json"}
                if extra_headers:
                    headers.update(extra_headers)
                response = self._session.request(method=method, url=url, headers=headers, json=data, params=params, timeout=60)
                if response.status_code == 401:
                    self._token_info = None
                    continue
                return response
            except requests.RequestException as e:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise
        raise APIError("Max retries exceeded")

    def create_listing(self, listing: TransportListing) -> Dict[str, Any]:
        listing_data = listing.to_cd_listing(self.marketplace_id)
        response = self._make_request("POST", "/listings", data=listing_data)
        if response.status_code == 201:
            location = response.headers.get("Location", "")
            listing_id = location.split("/")[-1] if location else None
            return {"success": True, "listing_id": listing_id, "etag": response.headers.get("ETag"), "location": location}
        else:
            raise APIError(f"Failed to create listing: {response.text}")

    def validate_credentials(self) -> bool:
        try:
            self._get_access_token()
            return True
        except Exception:
            return False


class AuthenticationError(Exception):
    pass


class APIError(Exception):
    pass


def create_client_from_env() -> CentralDispatchClient:
    client_id = os.environ.get("CD_CLIENT_ID")
    client_secret = os.environ.get("CD_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("CD_CLIENT_ID and CD_CLIENT_SECRET environment variables must be set")
    marketplace_id = os.environ.get("CD_MARKETPLACE_ID")
    return CentralDispatchClient(client_id=client_id, client_secret=client_secret, marketplace_id=int(marketplace_id) if marketplace_id else None)
''',
    # ============== .gitignore ==============
    ".gitignore": """# Environment variables (NEVER commit!)
.env
.env.local
.env.production

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
ENV/

# SQLite databases
*.db
processed_emails.db

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# Logs
*.log
""",
    # ============== .env.example ==============
    ".env.example": """# Email Configuration (IMAP)
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_ADDRESS=info@y7agency.com
EMAIL_PASSWORD=your-app-password-here
EMAIL_FOLDER=INBOX
EMAIL_CHECK_INTERVAL=60

# ClickUp Configuration (REQUIRED)
CLICKUP_TOKEN=pk_your_token_here
CLICKUP_LIST_ID=901317344729

# Central Dispatch Configuration (OPTIONAL)
CD_CLIENT_ID=your-client-id
CD_CLIENT_SECRET=your-client-secret
CD_MARKETPLACE_ID=10000
""",
    # ============== requirements.txt ==============
    "requirements.txt": """pdfplumber>=0.10.0
requests>=2.28.0
""",
}


def main():
    print("Setting up Vehicle Transport Automation project...")
    print()

    # Create directories
    dirs = ["models", "extractors", "services", "tests"]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"Created directory: {d}/")

    # Create files
    for filepath, content in FILES.items():
        # Unescape the content
        content = content.replace("\\'", "'")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Created: {filepath}")

    # Create __init__.py files
    for d in ["models", "services", "tests"]:
        init_path = f"{d}/__init__.py"
        if not os.path.exists(init_path):
            with open(init_path, "w") as f:
                f.write("")
            print(f"Created: {init_path}")

    print()
    print("=" * 50)
    print("Setup complete!")
    print()
    print("Next steps:")
    print("1. Copy .env.example to .env and fill in your credentials")
    print("2. Install dependencies: pip install -r requirements.txt")
    print("3. Run: python -m services.orchestrator --validate")
    print("=" * 50)


if __name__ == "__main__":
    main()
