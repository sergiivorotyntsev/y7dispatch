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
6. 24-hour TTL cache for repeated route lookups

Floor/Ceiling Rules:
- Per-mile minimum: $0.40/mile
- Absolute minimum: $150
- Operational floor: avg_dispatch * 0.85
- Per-mile maximum: $2.00/mile (open), $3.00/mile (enclosed)
- Multiplier ceiling: avg_dispatch * 1.50
"""

import hashlib
import logging
import math
import time
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


# =============================================================================
# ENUMS
# =============================================================================


class Urgency(str, Enum):
    """Pickup urgency level."""

    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"
    URGENT = "URGENT"


class PriceSource(str, Enum):
    """Source of the price recommendation."""

    CD_MARKET_INTELLIGENCE = "CD_MARKET_INTELLIGENCE"
    MARKET_INTELLIGENCE = "MARKET_INTELLIGENCE"  # alias
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    FALLBACK_ESTIMATE = "FALLBACK_ESTIMATE"
    USER_OVERRIDE = "USER_OVERRIDE"


class PriceStatus(str, Enum):
    """Status of price in the workflow."""

    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    ADJUSTED = "ADJUSTED"
    MANUAL = "MANUAL"


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class Address:
    """Location for pricing calculation."""

    city: str
    state: str
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    def to_mi_stop(self, stop_number: int) -> MIStop:
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
        return MIVehicle(
            vin=self.vin,
            year=self.year,
            make=self.make,
            model=self.model,
            vehicle_type=self.vehicle_type,
            is_operable=self.is_operable,
        )


@dataclass
class PriceRecommendation:
    """Result of price calculation."""

    price: Optional[float] = None
    source: PriceSource = PriceSource.MANUAL_REQUIRED
    status: PriceStatus = PriceStatus.PENDING_REVIEW
    reason: Optional[str] = None
    avg_dispatch_price: Optional[float] = None
    avg_listing_price: Optional[float] = None
    spread: Optional[float] = None
    market_data_count: int = 0
    floor: Optional[float] = None
    ceiling: Optional[float] = None
    distance_miles: Optional[float] = None
    urgency: Urgency = Urgency.STANDARD
    urgency_multiplier: float = 1.0
    warnings: list[str] = field(default_factory=list)
    raw_quote: Optional[MIPriceQuote] = None
    cached: bool = False


# Backward-compatible aliases for tests
PricingResult = PriceRecommendation


@dataclass
class PricingInput:
    """Backward-compatible input (maps to Address + Vehicle)."""

    pickup_city: str = ""
    pickup_state: str = ""
    pickup_zip: Optional[str] = None
    delivery_city: str = ""
    delivery_state: str = ""
    delivery_zip: Optional[str] = None
    vehicle_vin: Optional[str] = None
    vehicle_year: Optional[int] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_type: str = "SEDAN"
    is_operable: bool = True
    is_enclosed: bool = False
    urgency: Urgency = Urgency.STANDARD
    distance_miles: Optional[float] = None

    def to_address_vehicle(self) -> tuple[Address, Address, Vehicle]:
        origin = Address(
            city=self.pickup_city,
            state=self.pickup_state,
            postal_code=self.pickup_zip,
        )
        destination = Address(
            city=self.delivery_city,
            state=self.delivery_state,
            postal_code=self.delivery_zip,
        )
        vehicle = Vehicle(
            vin=self.vehicle_vin,
            year=self.vehicle_year,
            make=self.vehicle_make,
            model=self.vehicle_model,
            vehicle_type=self.vehicle_type,
            is_operable=self.is_operable,
        )
        return origin, destination, vehicle


# =============================================================================
# CONFIG
# =============================================================================


@dataclass
class PricingConfig:
    """Configuration for pricing engine."""

    urgency_standard: float = 1.0
    urgency_priority: float = 1.12
    urgency_urgent: float = 1.25
    per_mile_floor: float = 0.40
    absolute_floor: float = 150.0
    market_floor_multiplier: float = 0.85
    per_mile_ceiling_open: float = 2.00
    per_mile_ceiling_enclosed: float = 3.00
    market_ceiling_multiplier: float = 1.50
    low_price_warning_threshold: float = 0.90
    high_price_warning_threshold: float = 1.30

    @classmethod
    def from_yaml(cls, config_path: str = "pricing_config.yaml") -> "PricingConfig":
        from pathlib import Path

        import yaml

        path = Path(config_path)
        if not path.exists():
            return cls()

        try:
            with open(path) as f:
                data = yaml.safe_load(f)

            return cls(
                urgency_standard=data.get("urgency", {}).get("standard", 1.0),
                urgency_priority=data.get("urgency", {}).get("priority", 1.12),
                urgency_urgent=data.get("urgency", {}).get("urgent", 1.25),
                per_mile_floor=data.get("floor", {}).get("per_mile_minimum", 0.40),
                absolute_floor=data.get("floor", {}).get("absolute_minimum", 150.0),
                market_floor_multiplier=data.get("floor", {}).get("market_floor_multiplier", 0.85),
                per_mile_ceiling_open=data.get("ceiling", {}).get("per_mile_maximum_open", 2.00),
                per_mile_ceiling_enclosed=data.get("ceiling", {}).get("per_mile_maximum_enclosed", 3.00),
                market_ceiling_multiplier=data.get("ceiling", {}).get("market_ceiling_multiplier", 1.50),
                low_price_warning_threshold=data.get("warnings", {}).get("low_price_threshold", 0.90),
                high_price_warning_threshold=data.get("warnings", {}).get("high_price_threshold", 1.30),
            )
        except Exception as e:
            logger.error(f"Failed to load pricing config: {e}")
            return cls()


# Backward-compatible constants (match Day 6 tests)
FLOOR_ABSOLUTE = 150.0
FLOOR_PER_MILE = 0.40
FLOOR_AVG_FACTOR = 0.85
CEILING_PER_MILE_OPEN = 2.00
CEILING_PER_MILE_ENCLOSED = 3.00
CEILING_AVG_FACTOR = 1.50
WARNING_LOW_FACTOR = 0.90
WARNING_HIGH_FACTOR = 1.30
URGENCY_MULTIPLIERS = {
    Urgency.STANDARD: 1.0,
    Urgency.PRIORITY: 1.12,
    Urgency.URGENT: 1.25,
}
CACHE_TTL_SECONDS = 86400  # 24 hours


# =============================================================================
# CACHE
# =============================================================================


class _CacheEntry:
    """Internal cache entry with TTL."""

    __slots__ = ("result", "expires_at")

    def __init__(self, result: PriceRecommendation, ttl: int = CACHE_TTL_SECONDS):
        self.result = result
        self.expires_at = time.time() + ttl

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


# =============================================================================
# ENGINE
# =============================================================================


class PricingEngine:
    """
    Calculates recommended transport prices using CD Market Intelligence.

    Features:
    - Hybrid workflow (system suggests, user confirms/adjusts)
    - Floor/ceiling guardrails
    - Urgency modifiers
    - 24h TTL cache
    - Haversine distance estimation
    """

    def __init__(
        self,
        mi_client: Optional[MarketIntelligenceClient] = None,
        config: Optional[PricingConfig] = None,
        pricing_service=None,
        cache_ttl: int = CACHE_TTL_SECONDS,
    ):
        self.mi_client = mi_client or MarketIntelligenceClient()
        self.config = config or PricingConfig()
        self._pricing_service = pricing_service
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl

        self._urgency_multipliers = {
            Urgency.STANDARD: self.config.urgency_standard,
            Urgency.PRIORITY: self.config.urgency_priority,
            Urgency.URGENT: self.config.urgency_urgent,
        }

    # -----------------------------------------------------------------
    # Main API (used by api/routes/pricing.py)
    # -----------------------------------------------------------------

    def calculate_recommended_price(
        self,
        origin: Address,
        destination: Address,
        vehicle: Vehicle,
        urgency: Urgency = Urgency.STANDARD,
        is_enclosed: bool = False,
    ) -> PriceRecommendation:
        """Calculate recommended listing price."""
        distance_miles = self._calculate_distance(origin, destination)

        # Check cache
        cache_key = self._make_cache_key(origin, destination, vehicle, is_enclosed)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return self._reapply_urgency(cached, urgency)

        quote = self._fetch_market_data(origin, destination, vehicle, is_enclosed)

        if quote is None:
            return PriceRecommendation(
                price=None,
                source=PriceSource.MANUAL_REQUIRED,
                status=PriceStatus.MANUAL,
                reason="Market data unavailable — enter price manually",
                distance_miles=distance_miles,
                urgency=urgency,
                warnings=["MI API unavailable — manual price required"],
            )

        avg_dispatch = quote.suggested_price
        if not avg_dispatch or avg_dispatch <= 0:
            return PriceRecommendation(
                price=None,
                source=PriceSource.MANUAL_REQUIRED,
                status=PriceStatus.MANUAL,
                reason="MI API returned invalid price",
                warnings=["MI API returned invalid price — manual price required"],
            )

        avg_listing = quote.high_price or (avg_dispatch * 1.1)
        spread = avg_listing - avg_dispatch

        # Base price with spread factor
        base_price = avg_dispatch + (spread * 0.5)

        # Urgency modifier
        urgency_multiplier = self._urgency_multipliers[urgency]
        recommended = base_price * urgency_multiplier

        # Floor/ceiling
        floor = self._calculate_floor(distance_miles, avg_dispatch)
        ceiling = self._calculate_ceiling(distance_miles, avg_dispatch, is_enclosed)
        final_price = max(floor, min(ceiling, recommended))

        # Warnings
        warnings = self._generate_warnings(final_price, avg_dispatch)

        result = PriceRecommendation(
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
            market_data_count=1,
            warnings=warnings,
            raw_quote=quote,
        )

        self._cache_put(cache_key, result)
        return result

    # -----------------------------------------------------------------
    # Backward-compatible API (used by Day 6 tests)
    # -----------------------------------------------------------------

    def calculate(self, inp: PricingInput) -> PriceRecommendation:
        """Backward-compatible calculate from PricingInput."""
        origin, destination, vehicle = inp.to_address_vehicle()
        return self.calculate_recommended_price(
            origin=origin,
            destination=destination,
            vehicle=vehicle,
            urgency=inp.urgency,
            is_enclosed=inp.is_enclosed,
        )

    # -----------------------------------------------------------------
    # Market data
    # -----------------------------------------------------------------

    def _fetch_market_data(
        self,
        origin: Address,
        destination: Address,
        vehicle: Vehicle,
        is_enclosed: bool,
    ) -> Optional[MIPriceQuote]:
        try:
            pickup_stop = origin.to_mi_stop(1)
            dropoff_stop = destination.to_mi_stop(2)
            mi_vehicle = vehicle.to_mi_vehicle()

            return self.mi_client.get_list_prices(
                stops=[pickup_stop, dropoff_stop],
                vehicles=[mi_vehicle],
                is_enclosed=is_enclosed,
            )
        except Exception as e:
            logger.error(f"Market Intelligence API error: {e}")
            return None

    # -----------------------------------------------------------------
    # Distance
    # -----------------------------------------------------------------

    def _calculate_distance(self, origin: Address, destination: Address) -> Optional[float]:
        if all([origin.latitude, origin.longitude, destination.latitude, destination.longitude]):
            return self._haversine_distance(
                (origin.latitude, origin.longitude),
                (destination.latitude, destination.longitude),
            )
        return self._estimate_distance_from_states(origin.state, destination.state)

    @staticmethod
    def _haversine_distance(origin: tuple[float, float], dest: tuple[float, float]) -> float:
        lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
        lat2, lon2 = math.radians(dest[0]), math.radians(dest[1])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        return c * 3956  # Earth radius in miles

    def _estimate_distance_from_states(self, origin_state: str, dest_state: str) -> Optional[float]:
        state_coords = {
            "AL": (32.8, -86.8), "AZ": (34.2, -111.6), "AR": (34.8, -92.2),
            "CA": (37.2, -119.4), "CO": (39.0, -105.5), "CT": (41.6, -72.7),
            "DE": (39.0, -75.5), "FL": (28.6, -82.4), "GA": (32.6, -83.4),
            "ID": (44.4, -114.6), "IL": (40.0, -89.2), "IN": (39.9, -86.3),
            "IA": (42.0, -93.5), "KS": (38.5, -98.4), "KY": (37.8, -85.7),
            "LA": (31.0, -92.0), "ME": (45.4, -69.2), "MD": (39.0, -76.8),
            "MA": (42.2, -71.5), "MI": (44.3, -85.4), "MN": (46.3, -94.3),
            "MS": (32.7, -89.7), "MO": (38.4, -92.5), "MT": (47.0, -109.6),
            "NE": (41.5, -99.8), "NV": (39.3, -116.6), "NH": (43.7, -71.6),
            "NJ": (40.2, -74.7), "NM": (34.4, -106.1), "NY": (42.9, -75.5),
            "NC": (35.5, -79.4), "ND": (47.4, -100.5), "OH": (40.4, -82.8),
            "OK": (35.6, -97.5), "OR": (44.0, -120.5), "PA": (40.9, -77.8),
            "RI": (41.7, -71.5), "SC": (33.9, -80.9), "SD": (44.4, -100.2),
            "TN": (35.8, -86.3), "TX": (31.5, -99.4), "UT": (39.3, -111.7),
            "VT": (44.0, -72.7), "VA": (37.5, -78.8), "WA": (47.4, -120.5),
            "WV": (38.9, -80.5), "WI": (44.6, -90.0), "WY": (43.0, -107.5),
        }
        o = state_coords.get(origin_state.upper())
        d = state_coords.get(dest_state.upper())
        if o and d:
            return self._haversine_distance(o, d)
        return None

    # -----------------------------------------------------------------
    # Floor / Ceiling
    # -----------------------------------------------------------------

    def _calculate_floor(self, distance_miles: Optional[float], avg_dispatch: float) -> float:
        floors = [self.config.absolute_floor]
        if distance_miles and distance_miles > 0:
            floors.append(distance_miles * self.config.per_mile_floor)
        floors.append(avg_dispatch * self.config.market_floor_multiplier)
        return max(floors)

    def _calculate_ceiling(
        self, distance_miles: Optional[float], avg_dispatch: float, is_enclosed: bool
    ) -> float:
        ceilings = [avg_dispatch * self.config.market_ceiling_multiplier]
        if distance_miles and distance_miles > 0:
            per_mile = (
                self.config.per_mile_ceiling_enclosed if is_enclosed
                else self.config.per_mile_ceiling_open
            )
            ceilings.append(distance_miles * per_mile)
        return min(ceilings)

    def _generate_warnings(self, price: float, avg_dispatch: float) -> list[str]:
        warnings = []
        if avg_dispatch <= 0:
            return warnings
        ratio = price / avg_dispatch
        if ratio < self.config.low_price_warning_threshold:
            warnings.append(
                f"Price ${price:.2f} is below 90% of avg dispatch (${avg_dispatch * self.config.low_price_warning_threshold:.2f})"
            )
        elif ratio > self.config.high_price_warning_threshold:
            warnings.append(
                f"Price ${price:.2f} is above 130% of avg dispatch (${avg_dispatch * self.config.high_price_warning_threshold:.2f})"
            )
        return warnings

    # -----------------------------------------------------------------
    # User override
    # -----------------------------------------------------------------

    def apply_user_override(
        self, recommendation: PriceRecommendation, user_price: Optional[float]
    ) -> PriceRecommendation:
        if user_price is None:
            recommendation.status = PriceStatus.ACCEPTED
            return recommendation
        recommendation.price = user_price
        recommendation.source = PriceSource.USER_OVERRIDE
        recommendation.status = PriceStatus.ADJUSTED
        if recommendation.avg_dispatch_price:
            recommendation.warnings = self._generate_warnings(
                user_price, recommendation.avg_dispatch_price
            )
        return recommendation

    # -----------------------------------------------------------------
    # Cache (24h TTL)
    # -----------------------------------------------------------------

    def _make_cache_key(
        self, origin: Address, destination: Address, vehicle: Vehicle, is_enclosed: bool
    ) -> str:
        parts = [
            origin.city.upper(), origin.state.upper(), origin.postal_code or "",
            destination.city.upper(), destination.state.upper(), destination.postal_code or "",
            vehicle.vehicle_type, str(is_enclosed), str(vehicle.is_operable),
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]

    def _cache_get(self, key: str) -> Optional[PriceRecommendation]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.expired:
            del self._cache[key]
            return None
        return entry.result

    def _cache_put(self, key: str, result: PriceRecommendation) -> None:
        self._cache[key] = _CacheEntry(result, self._cache_ttl)

    def _reapply_urgency(
        self, cached: PriceRecommendation, urgency: Urgency
    ) -> PriceRecommendation:
        """Return copy of cached result with updated urgency."""
        if cached.avg_dispatch_price is None or cached.price is None:
            result = PriceRecommendation(
                source=cached.source, status=cached.status,
                warnings=list(cached.warnings), urgency=urgency,
                urgency_multiplier=self._urgency_multipliers[urgency],
                cached=True,
            )
            return result

        avg_dispatch = cached.avg_dispatch_price
        spread = cached.spread or 0.0
        base_price = avg_dispatch + (spread * 0.5)
        modified = base_price * self._urgency_multipliers[urgency]
        floor = self._calculate_floor(cached.distance_miles, avg_dispatch)
        ceiling = self._calculate_ceiling(
            cached.distance_miles, avg_dispatch, False
        )
        final = max(floor, min(ceiling, modified))
        warnings = self._generate_warnings(final, avg_dispatch)

        return PriceRecommendation(
            price=round(final, 2),
            source=cached.source,
            status=cached.status,
            avg_dispatch_price=avg_dispatch,
            avg_listing_price=cached.avg_listing_price,
            spread=spread,
            floor=round(floor, 2),
            ceiling=round(ceiling, 2),
            distance_miles=cached.distance_miles,
            urgency=urgency,
            urgency_multiplier=self._urgency_multipliers[urgency],
            market_data_count=cached.market_data_count,
            warnings=warnings,
            cached=True,
        )

    def clear_cache(self) -> int:
        count = len(self._cache)
        self._cache.clear()
        return count

    def cache_size(self) -> int:
        return len(self._cache)


# =============================================================================
# Module-level singleton
# =============================================================================

_pricing_engine: Optional[PricingEngine] = None


def get_pricing_engine(
    mi_client: Optional[MarketIntelligenceClient] = None,
    config: Optional[PricingConfig] = None,
    config_path: str = "pricing_config.yaml",
) -> PricingEngine:
    """Get or create the pricing engine singleton."""
    global _pricing_engine
    if _pricing_engine is None:
        if config is None:
            config = PricingConfig.from_yaml(config_path)
        _pricing_engine = PricingEngine(mi_client=mi_client, config=config)
    return _pricing_engine


def reset_pricing_engine():
    """Reset the singleton (for testing)."""
    global _pricing_engine
    _pricing_engine = None
