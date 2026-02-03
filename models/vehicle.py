"""Data models for vehicle transport automation."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


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
            "country": self.country,
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
            "isInoperable": self.is_inoperable,
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
    vehicles: list[Vehicle] = field(default_factory=list)
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
        pickup_stop = (
            self.invoice.pickup_address.to_cd_stop(1) if self.invoice.pickup_address else {}
        )
        delivery_stop = self.delivery_address.to_cd_stop(2)
        vehicles = [v.to_cd_vehicle() for v in self.invoice.vehicles]

        listing = {
            "trailerType": self.trailer_type.value,
            "hasInOpVehicle": has_inop,
            "availableDate": (self.available_date or datetime.utcnow()).strftime(
                "%Y-%m-%dT00:00:00Z"
            ),
            "price": {
                "total": self.price,
                "cod": {
                    "amount": self.price,
                    "paymentMethod": "CASH_CERTIFIED_FUNDS",
                    "paymentLocation": "DELIVERY",
                },
            },
            "stops": [pickup_stop, delivery_stop],
            "vehicles": vehicles,
            "marketplaces": [{"marketplaceId": marketplace_id}],
        }

        if self.expiration_date:
            listing["expirationDate"] = self.expiration_date.strftime("%Y-%m-%dT00:00:00Z")
        if self.desired_delivery_date:
            listing["desiredDeliveryDate"] = self.desired_delivery_date.strftime(
                "%Y-%m-%dT00:00:00Z"
            )
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
                listing["transportationReleaseNotes"] = (
                    f"{location_info}. {listing['transportationReleaseNotes']}"
                )
            else:
                listing["transportationReleaseNotes"] = location_info

        return listing
