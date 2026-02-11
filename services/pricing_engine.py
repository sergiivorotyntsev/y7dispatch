"""Pricing Engine for Vehicle Transport.

Implements hybrid pricing strategy:
- System suggests price based on CD Market Intelligence
- User confirms/adjusts via Google Sheets

Pricing Formula (adaptive):
1. Fetch historical data from CD API (dispatch + listing prices)
2. Calculate avg_dispatch_price (actual transactions)
3. Apply urgency modifier (STANDARD/PRIORITY/URGENT)
4. Apply floor/ceiling constraints
5. Generate warnings for edge cases

Floor/Ceiling Rules:
- Per-mile minimum: $0.40/mile
- Absolute minimum: $100
- Operational floor: avg_dispatch × 0.85
- Per-mile maximum: $3.00/mile (open), $4.00/mile (enclosed)
- Multiplier ceiling: avg_dispatch × 1.50
"""

import logging
import math
import statistics
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from api.mi_client import (
    MarketIntelligenceClient,
    MIClientConfig,
    MIPriceQuote,
    MIStop,
    MIVehicle,
)

logger = logging.getLogger(__name__)


class Urgency(str, Enum):
    """Pickup urgency level."""

    STANDARD = "STANDARD"  # 5-7 days
    PRIORITY = "PRIORITY"  # 2-4 days
    URGENT = "URGENT"  # 24-48h


class PriceSource(str, Enum):
    """Source of the price recommendation."""

    CD_MARKET_INTELLIGENCE = "CD_MARKET_INTELLIGENCE"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    FALLBACK_ESTIMATE = "FALLBACK_ESTIMATE"
    USER_OVERRIDE = "USER_OVERRIDE"


class PriceStatus(str, Enum):
    """Status of price in the workflow."""

    PENDING_REVIEW = "PENDING_REVIEW"  # Awaiting user confirmation
    ACCEPTED = "ACCEPTED"  # User accepted suggested price
    ADJUSTED = "ADJUSTED"  # User modified the price
    MANUAL = "MANUAL"  # No suggestion available, user entered manually


@dataclass
class Address:
    """Location for pricing calculation."""

    city: str
    state: str
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    def to_mi_stop(self, stop_number: int) -> MIStop:
        """Convert to Market Intelligence stop."""
        return MIStop(
            stop_number=stop_number,
            city=self.city,
            state=self.state,
            postal_code=self.postal_code,
            latitude=self.latitude,
            longitude=self.longitude,
        )


@dataclass
class Vehicle:
    """Vehicle info for pricing."""

    vin: Optional[str] = None
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    vehicle_type: str = "SEDAN"
    is_operable: bool = True

    def to_mi_vehicle(self) -> MIVehicle:
        """Convert to Market Intelligence vehicle."""
        return MIVehicle(
            vin=self.vin,
            year=self.year,
            make=self.make,
            model=self.model,
            vehicle_type=self.vehicle_type,
            is_operable=self.is_operable,
        )


@dataclass
class MarketDataPoint:
    """Single data point from market intelligence."""

    listing_price: Optional[float] = None
    dispatch_price: Optional[float] = None


@dataclass
class PriceRecommendation:
    """Result of price calculation."""

    # Recommended price (None if manual required)
    price: Optional[float] = None

    # Metadata
    source: PriceSource = PriceSource.MANUAL_REQUIRED
    status: PriceStatus = PriceStatus.PENDING_REVIEW
    reason: Optional[str] = None

    # Market data stats
    avg_dispatch_price: Optional[float] = None
    avg_listing_price: Optional[float] = None
    spread: Optional[float] = None
    market_data_count: int = 0

    # Constraints applied
    floor: Optional[float] = None
    ceiling: Optional[float] = None
    distance_miles: Optional[float] = None

    # Urgency
    urgency: Urgency = Urgency.STANDARD
    urgency_multiplier: float = 1.0

    # Warnings
    warnings: list[str] = field(default_factory=list)

    # Raw data for debugging
    raw_quote: Optional[MIPriceQuote] = None


@dataclass
class PricingConfig:
    """Configuration for pricing engine."""

    # Urgency multipliers
    urgency_standard: float = 1.0
    urgency_priority: float = 1.12
    urgency_urgent: float = 1.25

    # Floor constraints
    per_mile_floor: float = 0.40  # $/mile minimum
    absolute_floor: float = 100.0  # $ minimum
    market_floor_multiplier: float = 0.85  # × avg_dispatch

    # Ceiling constraints
    per_mile_ceiling_open: float = 3.00  # $/mile max for open trailer
    per_mile_ceiling_enclosed: float = 4.00  # $/mile max for enclosed
    market_ceiling_multiplier: float = 1.50  # × avg_dispatch

    # Warning thresholds
    low_price_warning_threshold: float = 0.90  # warn if < 90% of market
    high_price_warning_threshold: float = 1.30  # warn if > 130% of market

    @classmethod
    def from_yaml(cls, config_path: str = "pricing_config.yaml") -> "PricingConfig":
        """Load configuration from YAML file."""
        from pathlib import Path

        import yaml

        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Pricing config not found at {config_path}, using defaults")
            return cls()

        try:
            with open(path) as f:
                data = yaml.safe_load(f)

            return cls(
                # Urgency
                urgency_standard=data.get("urgency", {}).get("standard", 1.0),
                urgency_priority=data.get("urgency", {}).get("priority", 1.12),
                urgency_urgent=data.get("urgency", {}).get("urgent", 1.25),
                # Floor
                per_mile_floor=data.get("floor", {}).get("per_mile_minimum", 0.40),
                absolute_floor=data.get("floor", {}).get("absolute_minimum", 100.0),
                market_floor_multiplier=data.get("floor", {}).get("market_floor_multiplier", 0.85),
                # Ceiling
                per_mile_ceiling_open=data.get("ceiling", {}).get("per_mile_maximum_open", 3.00),
                per_mile_ceiling_enclosed=data.get("ceiling", {}).get("per_mile_maximum_enclosed", 4.00),
                market_ceiling_multiplier=data.get("ceiling", {}).get("market_ceiling_multiplier", 1.50),
                # Warnings
                low_price_warning_threshold=data.get("warnings", {}).get("low_price_threshold", 0.90),
                high_price_warning_threshold=data.get("warnings", {}).get("high_price_threshold", 1.30),
            )
        except Exception as e:
            logger.error(f"Failed to load pricing config: {e}")
            return cls()


class PricingEngine:
    """
    Calculates recommended transport prices using CD Market Intelligence.

    Hybrid workflow:
    1. System fetches market data and calculates recommendation
    2. User reviews in Google Sheets (suggested_price column)
    3. User accepts or enters override (final_price column)
    4. If final_price empty → use suggested_price
    5. If final_price filled → use override

    Usage:
        engine = PricingEngine()
        recommendation = await engine.calculate_recommended_price(
            origin=Address(city="Dallas", state="TX"),
            destination=Address(city="Houston", state="TX"),
            vehicle=Vehicle(year=2020, make="Toyota", model="Camry"),
            urgency=Urgency.STANDARD,
        )
    """

    def __init__(
        self,
        mi_client: Optional[MarketIntelligenceClient] = None,
        config: Optional[PricingConfig] = None,
    ):
        self.mi_client = mi_client or MarketIntelligenceClient()
        self.config = config or PricingConfig()

        self._urgency_multipliers = {
            Urgency.STANDARD: self.config.urgency_standard,
            Urgency.PRIORITY: self.config.urgency_priority,
            Urgency.URGENT: self.config.urgency_urgent,
        }

    def calculate_recommended_price(
        self,
        origin: Address,
        destination: Address,
        vehicle: Vehicle,
        urgency: Urgency = Urgency.STANDARD,
        is_enclosed: bool = False,
    ) -> PriceRecommendation:
        """
        Calculate recommended listing price.

        Args:
            origin: Pickup location
            destination: Delivery location
            vehicle: Vehicle details
            urgency: Pickup urgency level
            is_enclosed: Whether enclosed trailer required

        Returns:
            PriceRecommendation with suggested price or MANUAL_REQUIRED status
        """
        # 1. Calculate distance for floor/ceiling
        distance_miles = self._calculate_distance(origin, destination)

        # 2. Fetch market data from CD MI API
        quote = self._fetch_market_data(origin, destination, vehicle, is_enclosed)

        if quote is None:
            # API unavailable - manual entry required
            return PriceRecommendation(
                price=None,
                source=PriceSource.MANUAL_REQUIRED,
                status=PriceStatus.MANUAL,
                reason="Market data unavailable - enter price manually",
                distance_miles=distance_miles,
                urgency=urgency,
                warnings=["⚠ Market data unavailable"],
            )

        # 3. Extract pricing data
        # CD MI API returns suggested price directly
        # We treat it as avg_dispatch for our formula
        avg_dispatch = quote.suggested_price
        avg_listing = quote.high_price or (avg_dispatch * 1.1)  # Estimate if not provided
        spread = avg_listing - avg_dispatch

        # 4. Base recommended price (use dispatch price as base)
        base_price = avg_dispatch

        # 5. Apply urgency modifier
        urgency_multiplier = self._urgency_multipliers[urgency]
        recommended = base_price * urgency_multiplier

        # 6. Calculate floor/ceiling
        floor = self._calculate_floor(distance_miles, avg_dispatch)
        ceiling = self._calculate_ceiling(distance_miles, avg_dispatch, is_enclosed)

        # 7. Apply constraints
        final_price = max(floor, min(ceiling, recommended))

        # 8. Generate warnings
        warnings = self._generate_warnings(final_price, avg_dispatch)

        logger.info(
            f"Pricing: {origin.city},{origin.state} → {destination.city},{destination.state} | "
            f"market=${avg_dispatch:.0f} | urgency={urgency.value} | "
            f"recommended=${final_price:.0f} | floor=${floor:.0f} | ceiling=${ceiling:.0f}"
        )

        return PriceRecommendation(
            price=round(final_price, 2),
            source=PriceSource.CD_MARKET_INTELLIGENCE,
            status=PriceStatus.PENDING_REVIEW,
            avg_dispatch_price=avg_dispatch,
            avg_listing_price=avg_listing,
            spread=spread,
            floor=round(floor, 2),
            ceiling=round(ceiling, 2),
            distance_miles=round(distance_miles, 1) if distance_miles else None,
            urgency=urgency,
            urgency_multiplier=urgency_multiplier,
            market_data_count=1,  # Single quote from API
            warnings=warnings,
            raw_quote=quote,
        )

    def _fetch_market_data(
        self,
        origin: Address,
        destination: Address,
        vehicle: Vehicle,
        is_enclosed: bool,
    ) -> Optional[MIPriceQuote]:
        """Fetch market data from CD Market Intelligence API."""
        try:
            pickup_stop = origin.to_mi_stop(1)
            dropoff_stop = destination.to_mi_stop(2)
            mi_vehicle = vehicle.to_mi_vehicle()

            return self.mi_client.get_list_prices(
                stops=[pickup_stop, dropoff_stop],
                vehicles=[mi_vehicle],
                is_enclosed=is_enclosed,
                limit=5,
            )
        except ValueError as e:
            logger.warning(f"Invalid pricing request: {e}")
            return None
        except Exception as e:
            logger.error(f"Market Intelligence API error: {e}")
            return None

    def _calculate_distance(self, origin: Address, destination: Address) -> Optional[float]:
        """Calculate distance between origin and destination using Haversine."""
        if not all([origin.latitude, origin.longitude, destination.latitude, destination.longitude]):
            # Fallback: estimate from state codes
            return self._estimate_distance_from_states(origin.state, destination.state)

        return self._haversine_distance(
            (origin.latitude, origin.longitude),
            (destination.latitude, destination.longitude),
        )

    @staticmethod
    def _haversine_distance(origin: tuple[float, float], dest: tuple[float, float]) -> float:
        """Calculate distance in miles using Haversine formula."""
        lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
        lat2, lon2 = math.radians(dest[0]), math.radians(dest[1])

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))

        # Earth radius in miles
        r = 3956
        return c * r

    def _estimate_distance_from_states(self, origin_state: str, dest_state: str) -> Optional[float]:
        """Rough distance estimate based on state centroids."""
        # State centroids (approximate lat/lng)
        state_coords = {
            "AL": (32.8, -86.8), "AK": (64.0, -153.0), "AZ": (34.2, -111.6),
            "AR": (34.8, -92.2), "CA": (37.2, -119.4), "CO": (39.0, -105.5),
            "CT": (41.6, -72.7), "DE": (39.0, -75.5), "FL": (28.6, -82.4),
            "GA": (32.6, -83.4), "HI": (20.8, -156.3), "ID": (44.4, -114.6),
            "IL": (40.0, -89.2), "IN": (39.9, -86.3), "IA": (42.0, -93.5),
            "KS": (38.5, -98.4), "KY": (37.8, -85.7), "LA": (31.0, -92.0),
            "ME": (45.4, -69.2), "MD": (39.0, -76.8), "MA": (42.2, -71.5),
            "MI": (44.3, -85.4), "MN": (46.3, -94.3), "MS": (32.7, -89.7),
            "MO": (38.4, -92.5), "MT": (47.0, -109.6), "NE": (41.5, -99.8),
            "NV": (39.3, -116.6), "NH": (43.7, -71.6), "NJ": (40.2, -74.7),
            "NM": (34.4, -106.1), "NY": (42.9, -75.5), "NC": (35.5, -79.4),
            "ND": (47.4, -100.5), "OH": (40.4, -82.8), "OK": (35.6, -97.5),
            "OR": (44.0, -120.5), "PA": (40.9, -77.8), "RI": (41.7, -71.5),
            "SC": (33.9, -80.9), "SD": (44.4, -100.2), "TN": (35.8, -86.3),
            "TX": (31.5, -99.4), "UT": (39.3, -111.7), "VT": (44.0, -72.7),
            "VA": (37.5, -78.8), "WA": (47.4, -120.5), "WV": (38.9, -80.5),
            "WI": (44.6, -90.0), "WY": (43.0, -107.5),
        }

        origin_coords = state_coords.get(origin_state.upper())
        dest_coords = state_coords.get(dest_state.upper())

        if origin_coords and dest_coords:
            return self._haversine_distance(origin_coords, dest_coords)

        return None

    def _calculate_floor(self, distance_miles: Optional[float], avg_dispatch: float) -> float:
        """Calculate price floor."""
        floors = [self.config.absolute_floor]

        if distance_miles:
            floors.append(distance_miles * self.config.per_mile_floor)

        floors.append(avg_dispatch * self.config.market_floor_multiplier)

        return max(floors)

    def _calculate_ceiling(
        self, distance_miles: Optional[float], avg_dispatch: float, is_enclosed: bool
    ) -> float:
        """Calculate price ceiling."""
        ceilings = []

        if distance_miles:
            per_mile_rate = (
                self.config.per_mile_ceiling_enclosed
                if is_enclosed
                else self.config.per_mile_ceiling_open
            )
            ceilings.append(distance_miles * per_mile_rate)

        ceilings.append(avg_dispatch * self.config.market_ceiling_multiplier)

        if ceilings:
            return min(ceilings)

        # Fallback: 150% of market
        return avg_dispatch * 1.5

    def _generate_warnings(self, price: float, avg_dispatch: float) -> list[str]:
        """Generate warnings for edge cases."""
        warnings = []

        ratio = price / avg_dispatch if avg_dispatch > 0 else 1.0

        if ratio < self.config.low_price_warning_threshold:
            warnings.append("⚠ Below market — pickup may be slow")

        if ratio > self.config.high_price_warning_threshold:
            warnings.append("⚠ Above market — may overpay")

        return warnings

    def apply_user_override(
        self,
        recommendation: PriceRecommendation,
        user_price: Optional[float],
    ) -> PriceRecommendation:
        """
        Apply user's price decision to recommendation.

        Args:
            recommendation: Original recommendation
            user_price: User's final price (None = accept suggested)

        Returns:
            Updated PriceRecommendation
        """
        if user_price is None:
            # User accepted suggested price
            recommendation.status = PriceStatus.ACCEPTED
            return recommendation

        # User entered override
        recommendation.price = user_price
        recommendation.source = PriceSource.USER_OVERRIDE
        recommendation.status = PriceStatus.ADJUSTED

        # Regenerate warnings for user's price
        if recommendation.avg_dispatch_price:
            recommendation.warnings = self._generate_warnings(
                user_price, recommendation.avg_dispatch_price
            )

        return recommendation


# =============================================================================
# Module-level singleton
# =============================================================================

_pricing_engine: Optional[PricingEngine] = None


def get_pricing_engine(
    mi_client: Optional[MarketIntelligenceClient] = None,
    config: Optional[PricingConfig] = None,
    config_path: str = "pricing_config.yaml",
) -> PricingEngine:
    """Get or create the pricing engine singleton.

    Args:
        mi_client: Market Intelligence client (optional)
        config: Pricing configuration (optional, loads from YAML if not provided)
        config_path: Path to YAML config file (default: pricing_config.yaml)
    """
    global _pricing_engine
    if _pricing_engine is None:
        # Load config from YAML if not provided
        if config is None:
            config = PricingConfig.from_yaml(config_path)
        _pricing_engine = PricingEngine(mi_client=mi_client, config=config)
    return _pricing_engine


def reset_pricing_engine():
    """Reset the singleton (for testing)."""
    global _pricing_engine
    _pricing_engine = None
