"""
Pricing API Routes

Provides pricing recommendations using CD Market Intelligence API.
Implements hybrid workflow: system suggests, user confirms/adjusts.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.pricing_engine import (
    Address,
    PriceRecommendation,
    PriceSource,
    PriceStatus,
    PricingEngine,
    Urgency,
    Vehicle,
    get_pricing_engine,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pricing", tags=["Pricing"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class LocationRequest(BaseModel):
    """Location for pricing calculation."""

    city: str = Field(..., description="City name")
    state: str = Field(..., min_length=2, max_length=2, description="2-letter state code")
    postal_code: Optional[str] = Field(None, description="ZIP code")
    latitude: Optional[float] = Field(None, description="Latitude for precise distance")
    longitude: Optional[float] = Field(None, description="Longitude for precise distance")


class VehicleRequest(BaseModel):
    """Vehicle info for pricing."""

    vin: Optional[str] = Field(None, min_length=17, max_length=17, description="VIN")
    year: Optional[int] = Field(None, ge=1900, le=2035, description="Model year")
    make: Optional[str] = Field(None, description="Vehicle make")
    model: Optional[str] = Field(None, description="Vehicle model")
    vehicle_type: str = Field("SEDAN", description="Vehicle type: SEDAN, SUV, TRUCK, VAN, etc.")
    is_operable: bool = Field(True, description="Whether vehicle is operable")


class PricingRequest(BaseModel):
    """Request for price recommendation."""

    origin: LocationRequest = Field(..., description="Pickup location")
    destination: LocationRequest = Field(..., description="Delivery location")
    vehicle: VehicleRequest = Field(default_factory=VehicleRequest, description="Vehicle details")
    urgency: str = Field("STANDARD", description="Urgency: STANDARD, PRIORITY, URGENT")
    is_enclosed: bool = Field(False, description="Whether enclosed trailer required")


class PricingResponse(BaseModel):
    """Response with price recommendation."""

    # Core result
    suggested_price: Optional[float] = Field(None, description="Recommended price")
    source: str = Field(..., description="Price source: CD_MARKET_INTELLIGENCE, MANUAL_REQUIRED")
    status: str = Field(..., description="Status: PENDING_REVIEW, MANUAL")
    reason: Optional[str] = Field(None, description="Explanation if price unavailable")

    # Market data
    avg_dispatch_price: Optional[float] = Field(None, description="Average dispatch price")
    avg_listing_price: Optional[float] = Field(None, description="Average listing price")
    spread: Optional[float] = Field(None, description="Difference between listing and dispatch")
    market_data_count: int = Field(0, description="Number of market data points")

    # Constraints
    floor: Optional[float] = Field(None, description="Minimum price floor")
    ceiling: Optional[float] = Field(None, description="Maximum price ceiling")
    distance_miles: Optional[float] = Field(None, description="Estimated distance")

    # Urgency
    urgency: str = Field("STANDARD", description="Applied urgency level")
    urgency_multiplier: float = Field(1.0, description="Urgency price multiplier")

    # Warnings
    warnings: list[str] = Field(default_factory=list, description="Price warnings")


class BatchPricingRequest(BaseModel):
    """Request for batch price recommendations."""

    requests: list[PricingRequest] = Field(
        ..., max_length=50, description="Up to 50 pricing requests"
    )


class BatchPricingResponse(BaseModel):
    """Response with multiple price recommendations."""

    results: list[PricingResponse]
    success_count: int
    failure_count: int


class OverrideRequest(BaseModel):
    """Request to record user price override."""

    original_suggested_price: Optional[float] = Field(None, description="Original suggested price")
    final_price: float = Field(..., gt=0, description="User's final price decision")
    avg_dispatch_price: Optional[float] = Field(None, description="Market reference price")


class OverrideResponse(BaseModel):
    """Response after applying override."""

    final_price: float
    source: str
    status: str
    warnings: list[str]


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.post("/recommend", response_model=PricingResponse)
def get_price_recommendation(request: PricingRequest) -> PricingResponse:
    """
    Get recommended listing price for a transport.

    Uses CD Market Intelligence API to fetch market data and calculates
    a recommended price with floor/ceiling constraints.

    The response includes:
    - suggested_price: Recommended price (None if manual entry required)
    - source: Where the price came from
    - floor/ceiling: Price constraints applied
    - warnings: Edge case warnings (below/above market)

    Workflow:
    1. Call this endpoint to get suggestion
    2. Display in Sheets: suggested_price | price_source | final_price (override)
    3. If final_price empty → use suggested_price
    4. If final_price filled → use override
    """
    try:
        # Parse urgency
        try:
            urgency = Urgency(request.urgency.upper())
        except ValueError:
            urgency = Urgency.STANDARD

        # Build domain objects
        origin = Address(
            city=request.origin.city,
            state=request.origin.state,
            postal_code=request.origin.postal_code,
            latitude=request.origin.latitude,
            longitude=request.origin.longitude,
        )

        destination = Address(
            city=request.destination.city,
            state=request.destination.state,
            postal_code=request.destination.postal_code,
            latitude=request.destination.latitude,
            longitude=request.destination.longitude,
        )

        vehicle = Vehicle(
            vin=request.vehicle.vin,
            year=request.vehicle.year,
            make=request.vehicle.make,
            model=request.vehicle.model,
            vehicle_type=request.vehicle.vehicle_type,
            is_operable=request.vehicle.is_operable,
        )

        # Get recommendation
        engine = get_pricing_engine()
        recommendation = engine.calculate_recommended_price(
            origin=origin,
            destination=destination,
            vehicle=vehicle,
            urgency=urgency,
            is_enclosed=request.is_enclosed,
        )

        return PricingResponse(
            suggested_price=recommendation.price,
            source=recommendation.source.value,
            status=recommendation.status.value,
            reason=recommendation.reason,
            avg_dispatch_price=recommendation.avg_dispatch_price,
            avg_listing_price=recommendation.avg_listing_price,
            spread=recommendation.spread,
            market_data_count=recommendation.market_data_count,
            floor=recommendation.floor,
            ceiling=recommendation.ceiling,
            distance_miles=recommendation.distance_miles,
            urgency=recommendation.urgency.value,
            urgency_multiplier=recommendation.urgency_multiplier,
            warnings=recommendation.warnings,
        )

    except Exception as e:
        logger.error(f"Pricing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pricing calculation failed: {str(e)}")


@router.post("/recommend/batch", response_model=BatchPricingResponse)
def get_batch_price_recommendations(request: BatchPricingRequest) -> BatchPricingResponse:
    """
    Get price recommendations for multiple transports.

    Useful for processing batches of documents from email.
    Limited to 50 requests per batch.
    """
    results = []
    success_count = 0
    failure_count = 0

    for pricing_request in request.requests:
        try:
            response = get_price_recommendation(pricing_request)
            results.append(response)
            if response.suggested_price is not None:
                success_count += 1
            else:
                failure_count += 1
        except HTTPException:
            # Return partial result for failed request
            results.append(
                PricingResponse(
                    suggested_price=None,
                    source=PriceSource.MANUAL_REQUIRED.value,
                    status=PriceStatus.MANUAL.value,
                    reason="Request processing failed",
                    warnings=["⚠ Failed to get price recommendation"],
                )
            )
            failure_count += 1

    return BatchPricingResponse(
        results=results,
        success_count=success_count,
        failure_count=failure_count,
    )


@router.post("/override", response_model=OverrideResponse)
def record_price_override(request: OverrideRequest) -> OverrideResponse:
    """
    Record user's price override decision.

    This endpoint validates the user's price against market data
    and returns appropriate warnings.

    Use when user modifies the suggested price in Sheets.
    """
    engine = get_pricing_engine()
    warnings = []

    # Validate against market
    if request.avg_dispatch_price and request.avg_dispatch_price > 0:
        ratio = request.final_price / request.avg_dispatch_price

        if ratio < 0.90:
            warnings.append("⚠ Below market — pickup may be slow")
        elif ratio > 1.30:
            warnings.append("⚠ Above market — may overpay")

    # Determine status
    if request.original_suggested_price is None:
        status = PriceStatus.MANUAL.value
    elif abs(request.final_price - request.original_suggested_price) < 0.01:
        status = PriceStatus.ACCEPTED.value
    else:
        status = PriceStatus.ADJUSTED.value

    return OverrideResponse(
        final_price=request.final_price,
        source=PriceSource.USER_OVERRIDE.value,
        status=status,
        warnings=warnings,
    )


@router.get("/config")
def get_pricing_config() -> dict:
    """
    Get current pricing configuration.

    Returns floor/ceiling rules, urgency multipliers, and warning thresholds.
    """
    engine = get_pricing_engine()
    config = engine.config

    return {
        "urgency_multipliers": {
            "STANDARD": config.urgency_standard,
            "PRIORITY": config.urgency_priority,
            "URGENT": config.urgency_urgent,
        },
        "floor_constraints": {
            "per_mile_minimum": config.per_mile_floor,
            "absolute_minimum": config.absolute_floor,
            "market_floor_multiplier": config.market_floor_multiplier,
        },
        "ceiling_constraints": {
            "per_mile_maximum_open": config.per_mile_ceiling_open,
            "per_mile_maximum_enclosed": config.per_mile_ceiling_enclosed,
            "market_ceiling_multiplier": config.market_ceiling_multiplier,
        },
        "warning_thresholds": {
            "low_price_warning": config.low_price_warning_threshold,
            "high_price_warning": config.high_price_warning_threshold,
        },
    }
