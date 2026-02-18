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


class RunPricingResponse(BaseModel):
    """Full pricing response for a run ID with all market data."""

    run_id: int
    suggested_price: Optional[float] = None
    source: str = "MANUAL_REQUIRED"
    floor: Optional[float] = None
    ceiling: Optional[float] = None
    avg_dispatch: Optional[float] = None
    avg_listing: Optional[float] = None
    spread: Optional[float] = None
    warnings: list[str] = Field(default_factory=list)
    urgency: str = "STANDARD"
    urgency_multiplier: float = 1.0
    data_points: int = 0
    cached: bool = False
    distance_miles: Optional[float] = None
    pickup_location: Optional[str] = None
    delivery_location: Optional[str] = None


@router.get("/recommend/{run_id}", response_model=RunPricingResponse)
def get_run_pricing(run_id: int, urgency: str = "STANDARD") -> RunPricingResponse:
    """
    Get full pricing recommendation for an extraction run.

    Reads extraction data from DB and returns full market data
    including floor/ceiling, avg dispatch/listing, spread, and warnings.
    Accepts urgency query param to adjust recommendation.
    """
    import json

    from api.models import ExtractionRunRepository, ReviewItemRepository

    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    # Collect field values from review items + outputs
    items = ReviewItemRepository.get_by_run(run_id)
    data = {}
    for item in items:
        value = item.corrected_value if item.corrected_value else item.predicted_value
        data[item.source_key] = value

    if run.outputs_json:
        outputs = run.outputs_json if isinstance(run.outputs_json, dict) else json.loads(run.outputs_json)
        for key, value in outputs.items():
            if key not in data:
                data[key] = value

    # Extract locations
    pickup_city = data.get("pickup_city")
    pickup_state = data.get("pickup_state")
    delivery_city = data.get("delivery_city") or data.get("dropoff_city")
    delivery_state = data.get("delivery_state") or data.get("dropoff_state")

    pickup_location = f"{pickup_city}, {pickup_state}" if pickup_city and pickup_state else None
    delivery_location = f"{delivery_city}, {delivery_state}" if delivery_city and delivery_state else None

    # Need both locations for pricing
    if not pickup_city or not pickup_state or not delivery_city or not delivery_state:
        return RunPricingResponse(
            run_id=run_id,
            source="MANUAL_REQUIRED",
            warnings=["Missing pickup or delivery location"],
            pickup_location=pickup_location,
            delivery_location=delivery_location,
        )

    # Parse urgency
    try:
        urg = Urgency(urgency.upper())
    except ValueError:
        urg = Urgency.STANDARD

    # Build domain objects
    origin = Address(
        city=pickup_city,
        state=pickup_state,
        postal_code=data.get("pickup_zip"),
    )
    destination = Address(
        city=delivery_city,
        state=delivery_state,
        postal_code=data.get("delivery_zip") or data.get("dropoff_zip"),
    )
    vehicle = Vehicle(
        vin=data.get("vehicle_vin"),
        year=int(data["vehicle_year"]) if data.get("vehicle_year") else None,
        make=data.get("vehicle_make"),
        model=data.get("vehicle_model"),
        vehicle_type=data.get("vehicle_type", "SEDAN"),
        is_operable=str(data.get("vehicle_is_inoperable", "false")).lower() not in ("true", "yes", "1"),
    )

    try:
        engine = get_pricing_engine()
        rec = engine.calculate_recommended_price(
            origin=origin,
            destination=destination,
            vehicle=vehicle,
            urgency=urg,
        )

        return RunPricingResponse(
            run_id=run_id,
            suggested_price=rec.price,
            source=rec.source.value,
            floor=rec.floor,
            ceiling=rec.ceiling,
            avg_dispatch=rec.avg_dispatch_price,
            avg_listing=rec.avg_listing_price,
            spread=rec.spread,
            warnings=rec.warnings,
            urgency=rec.urgency.value,
            urgency_multiplier=rec.urgency_multiplier,
            data_points=rec.market_data_count,
            cached=rec.cached,
            distance_miles=rec.distance_miles,
            pickup_location=pickup_location,
            delivery_location=delivery_location,
        )
    except Exception as e:
        logger.error(f"Pricing engine error for run {run_id}: {e}", exc_info=True)
        return RunPricingResponse(
            run_id=run_id,
            source="MANUAL_REQUIRED",
            warnings=[f"Pricing calculation failed: {str(e)}"],
            pickup_location=pickup_location,
            delivery_location=delivery_location,
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


# =============================================================================
# CD MARKET INTELLIGENCE — PRICE CHECK PLUS
# =============================================================================


class CDMarketPriceResponse(BaseModel):
    """Response from CD Market Intelligence Price Check Plus."""

    run_id: int
    predicted_price: Optional[float] = None
    price_range: Optional[dict] = None  # {"low": float, "high": float}
    price_per_mile: Optional[float] = None
    avg_dispatch: Optional[float] = None
    avg_listing: Optional[float] = None
    spread: Optional[float] = None
    distance_miles: Optional[float] = None
    data_points: int = 0
    source: str = "cd_market_intelligence"
    pickup_location: Optional[str] = None
    delivery_location: Optional[str] = None
    error: Optional[str] = None


@router.get("/cd-market-intelligence/{run_id}", response_model=CDMarketPriceResponse)
def get_cd_market_price(run_id: int, warehouse_id: Optional[int] = None) -> CDMarketPriceResponse:
    """
    Get pricing from CD Market Intelligence (Price Check Plus).

    Reads extraction data for pickup location and vehicle info,
    uses warehouse for delivery location, and calls the CD MI API
    with OAuth2 Bearer token.
    """
    import json

    from api.database import get_connection
    from api.mi_client import MIStop, MIVehicle, create_authenticated_mi_client
    from api.models import ExtractionRunRepository, ReviewItemRepository
    from api.routes.warehouses import init_warehouses_schema

    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    # Collect field values
    items = ReviewItemRepository.get_by_run(run_id)
    data = {}
    for item in items:
        value = item.corrected_value if item.corrected_value else item.predicted_value
        data[item.source_key] = value

    if run.outputs_json:
        outputs = run.outputs_json if isinstance(run.outputs_json, dict) else json.loads(run.outputs_json)
        for key, value in outputs.items():
            if key not in data:
                data[key] = value

    # Pickup location from extraction
    pickup_city = data.get("pickup_city")
    pickup_state = data.get("pickup_state")
    pickup_zip = data.get("pickup_zip")

    if not pickup_city or not pickup_state:
        return CDMarketPriceResponse(
            run_id=run_id,
            error="Missing pickup location — city and state required",
        )

    # Delivery location from warehouse
    delivery_city = None
    delivery_state = None
    delivery_zip = None

    wh_id = warehouse_id or data.get("warehouse_id")
    if wh_id:
        init_warehouses_schema()
        with get_connection() as conn:
            wh_row = conn.execute(
                "SELECT * FROM warehouses WHERE id = ?", (wh_id,)
            ).fetchone()

        if wh_row:
            delivery_city = wh_row["city"]
            delivery_state = wh_row["state"]
            delivery_zip = wh_row["zip_code"]

    # Fallback to extracted delivery
    if not delivery_city:
        delivery_city = data.get("delivery_city") or data.get("dropoff_city")
        delivery_state = data.get("delivery_state") or data.get("dropoff_state")
        delivery_zip = data.get("delivery_zip") or data.get("dropoff_zip")

    if not delivery_city or not delivery_state:
        return CDMarketPriceResponse(
            run_id=run_id,
            error="Missing delivery location — select a warehouse first",
        )

    pickup_location = f"{pickup_city}, {pickup_state}"
    delivery_location = f"{delivery_city}, {delivery_state}"

    # Build MI request
    pickup_stop = MIStop(
        stop_number=1,
        city=pickup_city,
        state=pickup_state,
        postal_code=pickup_zip,
    )
    dropoff_stop = MIStop(
        stop_number=2,
        city=delivery_city,
        state=delivery_state,
        postal_code=delivery_zip,
    )

    vehicle_type = data.get("vehicle_type", "SEDAN")
    is_inop = str(data.get("vehicle_is_inoperable", "false")).lower() in ("true", "yes", "1")

    vehicle = MIVehicle(
        vin=data.get("vehicle_vin"),
        year=int(data["vehicle_year"]) if data.get("vehicle_year") else None,
        make=data.get("vehicle_make"),
        model=data.get("vehicle_model"),
        vehicle_type=vehicle_type,
        is_operable=not is_inop,
    )

    # Call CD MI API with OAuth2 token
    try:
        mi_client = create_authenticated_mi_client()
        quote = mi_client.get_list_prices(
            stops=[pickup_stop, dropoff_stop],
            vehicles=[vehicle],
            is_enclosed=False,
            limit=5,
        )
    except Exception as e:
        logger.error(f"CD MI API call failed for run {run_id}: {e}", exc_info=True)
        return CDMarketPriceResponse(
            run_id=run_id,
            error=f"CD API error: {str(e)}",
            pickup_location=pickup_location,
            delivery_location=delivery_location,
        )

    if not quote:
        return CDMarketPriceResponse(
            run_id=run_id,
            error="No pricing data returned from CD Market Intelligence",
            pickup_location=pickup_location,
            delivery_location=delivery_location,
        )

    # Handle 403 / subscription error
    if quote.error:
        return CDMarketPriceResponse(
            run_id=run_id,
            error=quote.error,
            pickup_location=pickup_location,
            delivery_location=delivery_location,
        )

    # Calculate price per mile
    price_per_mile = None
    if quote.distance_miles and quote.distance_miles > 0 and quote.suggested_price:
        price_per_mile = round(quote.suggested_price / quote.distance_miles, 2)

    return CDMarketPriceResponse(
        run_id=run_id,
        predicted_price=quote.suggested_price,
        price_range={"low": quote.low_price, "high": quote.high_price}
        if quote.low_price is not None
        else None,
        price_per_mile=price_per_mile,
        avg_dispatch=quote.avg_dispatch,
        avg_listing=quote.avg_listing,
        spread=quote.spread,
        distance_miles=quote.distance_miles,
        data_points=quote.data_points,
        source="cd_market_intelligence",
        pickup_location=pickup_location,
        delivery_location=delivery_location,
    )
