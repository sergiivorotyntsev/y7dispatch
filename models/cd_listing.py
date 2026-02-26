"""
Pydantic v2 schemas for Central Dispatch Listings API v2 Create Listing payload.

Invariants enforced:
  - Exactly 2 stops (pickup + delivery)
  - 1..12 vehicles, no duplicate VINs
  - pickup/dropoff stopNumbers reference valid stops
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from models.cd_enums import (
    DEFAULT_MARKETPLACE_ID,
    LocationType,
    PaymentLocation,
    PaymentMethod,
    SLAType,
    TrailerType,
    VehicleType,
)

VIN_PATTERN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
STATE_PATTERN = re.compile(r"^[A-Z]{2}$")
ZIP_PATTERN = re.compile(r"^\d{5}(-\d{4})?$")


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class CDStop(BaseModel):
    """A pickup or delivery stop."""

    stopNumber: int = Field(..., ge=1, le=2)
    locationType: LocationType = LocationType.DEALERSHIP
    locationName: str | None = None
    address: str = Field(..., min_length=1)
    city: str = Field(..., min_length=1)
    state: str = Field(..., min_length=2, max_length=2)
    postalCode: str = Field(..., min_length=5)
    country: str = Field(default="US", min_length=2, max_length=2)
    contactName: str | None = None
    phone: str | None = None

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        if not STATE_PATTERN.match(v):
            raise ValueError(f"state must be 2 uppercase letters, got '{v}'")
        return v

    @field_validator("postalCode")
    @classmethod
    def validate_postal(cls, v: str) -> str:
        if not ZIP_PATTERN.match(v):
            raise ValueError(f"postalCode must be 5 or 9 digit ZIP, got '{v}'")
        return v


class CDShippingSpecs(BaseModel):
    """Optional vehicle dimensions/weight."""

    length: float | None = None
    width: float | None = None
    height: float | None = None
    weight: float | None = None


class CDVehicle(BaseModel):
    """A vehicle in the listing."""

    pickupStopNumber: int = Field(default=1, ge=1, le=2)
    dropoffStopNumber: int = Field(default=2, ge=1, le=2)
    vin: str = Field(..., min_length=17, max_length=17)
    year: int = Field(..., ge=1900, le=2035)
    make: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    vehicleType: VehicleType = VehicleType.AUTO
    isInoperable: bool = False
    color: str | None = None
    lotNumber: str | None = None
    shippingSpecs: CDShippingSpecs | None = None

    @field_validator("vin")
    @classmethod
    def validate_vin(cls, v: str) -> str:
        v = v.upper().strip()
        if not VIN_PATTERN.match(v):
            raise ValueError(f"VIN must be 17 alphanumeric chars (no I/O/Q), got '{v}'")
        return v


class CDCOD(BaseModel):
    """Cash-on-delivery payment details."""

    amount: float = Field(..., ge=0)
    paymentMethod: PaymentMethod = PaymentMethod.CASH_CERTIFIED_FUNDS
    paymentLocation: PaymentLocation = PaymentLocation.DELIVERY


class CDPrice(BaseModel):
    """Listing price structure."""

    total: float = Field(..., gt=0, le=100000)
    cod: CDCOD | None = None
    balance: float = Field(default=0.0, ge=0)


class CDSLA(BaseModel):
    """Service-level agreement (optional)."""

    type: SLAType = SLAType.STANDARD
    pickupByDate: date | None = None
    deliverByDate: date | None = None


class CDMarketplace(BaseModel):
    """Marketplace visibility settings."""

    marketplaceId: int = Field(default=DEFAULT_MARKETPLACE_ID)
    searchable: bool = True
    digitalOffersEnabled: bool = False
    makeOffersEnabled: bool = True


class CDTag(BaseModel):
    """Key-value tag (e.g. auctionSource=COPART)."""

    name: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Root payload
# ---------------------------------------------------------------------------


class CDListingDraft(BaseModel):
    """
    Complete CD Listings API v2 Create Listing payload.

    Invariants:
      - exactly 2 stops
      - 1..12 vehicles, no duplicate VINs
      - each vehicle's pickupStopNumber / dropoffStopNumber exist in stops
    """

    externalId: str = Field(..., max_length=50)
    shipperOrderId: str | None = None
    partnerReferenceId: str | None = Field(default=None, max_length=50)
    trailerType: TrailerType = TrailerType.OPEN
    hasInOpVehicle: bool = False
    availableDate: date
    expirationDate: date | None = None
    transportationReleaseNotes: str | None = None

    price: CDPrice
    sla: CDSLA | None = None
    stops: list[CDStop] = Field(..., min_length=2, max_length=2)
    vehicles: list[CDVehicle] = Field(..., min_length=1, max_length=12)
    marketplaces: list[CDMarketplace] = Field(default_factory=lambda: [CDMarketplace()])
    tags: list[CDTag] = Field(default_factory=list)

    # ---- cross-field validators ----

    @model_validator(mode="after")
    def check_stops_and_vehicles(self) -> CDListingDraft:
        # Exactly 2 stops
        if len(self.stops) != 2:
            raise ValueError(f"Listing must have exactly 2 stops, got {len(self.stops)}")

        stop_numbers = {s.stopNumber for s in self.stops}
        if stop_numbers != {1, 2}:
            raise ValueError(f"Stops must have stopNumbers 1 and 2, got {stop_numbers}")

        # 1..12 vehicles
        if not (1 <= len(self.vehicles) <= 12):
            raise ValueError(f"Listing must have 1-12 vehicles, got {len(self.vehicles)}")

        # No duplicate VINs
        vins = [v.vin for v in self.vehicles]
        if len(vins) != len(set(vins)):
            dupes = [v for v in vins if vins.count(v) > 1]
            raise ValueError(f"Duplicate VINs: {set(dupes)}")

        # Vehicle stop references valid
        for v in self.vehicles:
            if v.pickupStopNumber not in stop_numbers:
                raise ValueError(
                    f"Vehicle {v.vin}: pickupStopNumber {v.pickupStopNumber} "
                    f"not in stops {stop_numbers}"
                )
            if v.dropoffStopNumber not in stop_numbers:
                raise ValueError(
                    f"Vehicle {v.vin}: dropoffStopNumber {v.dropoffStopNumber} "
                    f"not in stops {stop_numbers}"
                )

        # hasInOpVehicle consistency
        if any(v.isInoperable for v in self.vehicles):
            object.__setattr__(self, "hasInOpVehicle", True)

        return self

    def to_api_dict(self) -> dict:
        """Serialize to the dict CD API expects (camelCase, no None values)."""
        return self.model_dump(mode="json", exclude_none=True)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CDListingCreated(BaseModel):
    """Response after successfully creating a listing."""

    listing_id: str
    external_id: str
    location: str
    etag: str | None = None
    sandbox: bool = True


class CDPayloadPreviewResponse(BaseModel):
    """Preview endpoint response."""

    document_id: int
    run_id: int
    payload: dict
    validation_errors: list[str] = []
    is_valid: bool = True
