"""
PricingEngine — Recommended transport pricing with formula, modifiers, and guardrails.

Consumes MIPriceQuote from api/mi_client.py and applies:
  1. Base formula: avg_dispatch + (spread × 0.5)
  2. Urgency modifiers (STANDARD ×1.0, PRIORITY ×1.12, URGENT ×1.25)
  3. Floor / Ceiling guardrails
  4. Low / High warnings
  5. 24-hour TTL cache
  6. Fallback to MANUAL_REQUIRED when MI API unavailable
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Urgency(Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"
    URGENT = "URGENT"


class PriceSource(Enum):
    MARKET_INTELLIGENCE = "MARKET_INTELLIGENCE"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"


# Urgency multipliers
URGENCY_MULTIPLIERS: dict[Urgency, float] = {
    Urgency.STANDARD: 1.0,
    Urgency.PRIORITY: 1.12,
    Urgency.URGENT: 1.25,
}

# Floor constants
FLOOR_ABSOLUTE = 150.0        # $150 minimum
FLOOR_PER_MILE = 0.40         # $0.40/mile minimum
FLOOR_AVG_FACTOR = 0.85       # 85% of avg_dispatch minimum

# Ceiling constants
CEILING_PER_MILE_OPEN = 2.00      # $2.00/mile max for open
CEILING_PER_MILE_ENCLOSED = 3.00  # $3.00/mile max for enclosed
CEILING_AVG_FACTOR = 1.50         # 150% of avg_dispatch max

# Warning thresholds
WARNING_LOW_FACTOR = 0.90    # below 90% of avg_dispatch
WARNING_HIGH_FACTOR = 1.30   # above 130% of avg_dispatch

# Cache TTL
CACHE_TTL_SECONDS = 86400  # 24 hours


@dataclass
class PricingResult:
    """Result from PricingEngine.calculate()."""

    recommended_price: Optional[float] = None
    base_price: Optional[float] = None
    avg_dispatch_price: Optional[float] = None
    spread: Optional[float] = None
    urgency: Urgency = Urgency.STANDARD
    urgency_multiplier: float = 1.0
    floor_applied: Optional[float] = None
    ceiling_applied: Optional[float] = None
    source: PriceSource = PriceSource.MANUAL_REQUIRED
    warnings: list[str] = field(default_factory=list)
    is_enclosed: bool = False
    distance_miles: Optional[float] = None
    cached: bool = False


@dataclass
class PricingInput:
    """Input for PricingEngine.calculate()."""

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


class _CacheEntry:
    """Internal cache entry with TTL."""

    __slots__ = ("result", "expires_at")

    def __init__(self, result: PricingResult, ttl: int = CACHE_TTL_SECONDS):
        self.result = result
        self.expires_at = time.time() + ttl

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


class PricingEngine:
    """
    Calculates recommended transport price using CD Market Intelligence data.

    Usage:
        from api.mi_client import PricingService
        engine = PricingEngine(pricing_service=PricingService())
        result = engine.calculate(PricingInput(
            pickup_city="MANHEIM", pickup_state="PA",
            delivery_city="AYER", delivery_state="MA",
            urgency=Urgency.STANDARD,
        ))
    """

    def __init__(self, pricing_service=None, cache_ttl: int = CACHE_TTL_SECONDS):
        self._pricing_service = pricing_service
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl

    @property
    def pricing_service(self):
        if self._pricing_service is None:
            from api.mi_client import get_pricing_service

            self._pricing_service = get_pricing_service()
        return self._pricing_service

    def calculate(self, inp: PricingInput) -> PricingResult:
        """
        Calculate recommended transport price.

        Returns PricingResult with recommended_price and metadata.
        Falls back to source=MANUAL_REQUIRED when MI data unavailable.
        """
        result = PricingResult(
            urgency=inp.urgency,
            urgency_multiplier=URGENCY_MULTIPLIERS[inp.urgency],
            is_enclosed=inp.is_enclosed,
            distance_miles=inp.distance_miles,
        )

        # Check cache
        cache_key = self._cache_key(inp)
        cached = self._cache_get(cache_key)
        if cached is not None:
            # Re-apply urgency in case it changed
            return self._apply_urgency_to_cached(cached, inp.urgency)

        # Fetch MI quote
        quote = self._fetch_quote(inp)

        if quote is None:
            result.source = PriceSource.MANUAL_REQUIRED
            result.warnings.append("MI API unavailable — manual price required")
            logger.warning("PricingEngine: MI API returned None, source=MANUAL_REQUIRED")
            return result

        # Extract raw prices from MI quote
        avg_dispatch = quote.suggested_price
        low_price = quote.low_price
        high_price = quote.high_price

        if avg_dispatch is None or avg_dispatch <= 0:
            result.source = PriceSource.MANUAL_REQUIRED
            result.warnings.append("MI API returned invalid price — manual price required")
            return result

        result.avg_dispatch_price = avg_dispatch
        result.source = PriceSource.MARKET_INTELLIGENCE

        # Calculate spread
        if low_price is not None and high_price is not None:
            avg_listing = (low_price + high_price) / 2.0
            spread = avg_listing - avg_dispatch
        else:
            spread = 0.0

        result.spread = spread

        # Base formula: avg_dispatch + (spread × 0.5)
        base = avg_dispatch + (spread * 0.5)
        result.base_price = round(base, 2)

        # Apply urgency modifier
        modified = base * URGENCY_MULTIPLIERS[inp.urgency]

        # Apply floor
        modified = self._apply_floor(
            modified, avg_dispatch, inp.distance_miles, result
        )

        # Apply ceiling
        modified = self._apply_ceiling(
            modified, avg_dispatch, inp.distance_miles, inp.is_enclosed, result
        )

        # Round to nearest dollar
        result.recommended_price = round(modified, 2)

        # Check warnings
        self._check_warnings(result.recommended_price, avg_dispatch, result)

        # Cache the result (before urgency, so we can re-apply)
        self._cache_put(cache_key, result)

        return result

    def _fetch_quote(self, inp: PricingInput):
        """Fetch MIPriceQuote from PricingService."""
        from api.mi_client import PricingRequest

        if not inp.pickup_city or not inp.pickup_state:
            return None
        if not inp.delivery_city or not inp.delivery_state:
            return None

        req = PricingRequest(
            pickup_city=inp.pickup_city,
            pickup_state=inp.pickup_state,
            pickup_postal_code=inp.pickup_zip,
            delivery_city=inp.delivery_city,
            delivery_state=inp.delivery_state,
            delivery_postal_code=inp.delivery_zip,
            vehicle_vin=inp.vehicle_vin,
            vehicle_year=inp.vehicle_year,
            vehicle_make=inp.vehicle_make,
            vehicle_model=inp.vehicle_model,
            vehicle_type=inp.vehicle_type,
            is_operable=inp.is_operable,
            is_enclosed=inp.is_enclosed,
        )

        try:
            return self.pricing_service.get_recommended_price(req)
        except Exception as e:
            logger.error(f"PricingEngine: MI fetch failed: {e}")
            return None

    # -------------------------------------------------------------------------
    # Floor / Ceiling
    # -------------------------------------------------------------------------

    @staticmethod
    def _apply_floor(
        price: float,
        avg_dispatch: float,
        distance_miles: Optional[float],
        result: PricingResult,
    ) -> float:
        """Apply floor: max($150, $0.40/mile, avg_dispatch × 0.85)."""
        floors = [FLOOR_ABSOLUTE, avg_dispatch * FLOOR_AVG_FACTOR]
        if distance_miles and distance_miles > 0:
            floors.append(distance_miles * FLOOR_PER_MILE)

        floor_val = max(floors)
        if price < floor_val:
            result.floor_applied = round(floor_val, 2)
            result.warnings.append(
                f"Price ${price:.2f} raised to floor ${floor_val:.2f}"
            )
            return floor_val
        return price

    @staticmethod
    def _apply_ceiling(
        price: float,
        avg_dispatch: float,
        distance_miles: Optional[float],
        is_enclosed: bool,
        result: PricingResult,
    ) -> float:
        """Apply ceiling: min($X/mile, avg_dispatch × 1.50)."""
        ceilings = [avg_dispatch * CEILING_AVG_FACTOR]

        if distance_miles and distance_miles > 0:
            per_mile = (
                CEILING_PER_MILE_ENCLOSED if is_enclosed else CEILING_PER_MILE_OPEN
            )
            ceilings.append(distance_miles * per_mile)

        ceiling_val = min(ceilings)
        if price > ceiling_val:
            result.ceiling_applied = round(ceiling_val, 2)
            result.warnings.append(
                f"Price ${price:.2f} capped to ceiling ${ceiling_val:.2f}"
            )
            return ceiling_val
        return price

    @staticmethod
    def _check_warnings(
        price: float, avg_dispatch: float, result: PricingResult
    ) -> None:
        """Add low/high warnings if price is outside normal range."""
        low_threshold = avg_dispatch * WARNING_LOW_FACTOR
        high_threshold = avg_dispatch * WARNING_HIGH_FACTOR

        if price < low_threshold:
            result.warnings.append(
                f"Price ${price:.2f} is below 90% of avg dispatch (${low_threshold:.2f})"
            )
        elif price > high_threshold:
            result.warnings.append(
                f"Price ${price:.2f} is above 130% of avg dispatch (${high_threshold:.2f})"
            )

    # -------------------------------------------------------------------------
    # Cache
    # -------------------------------------------------------------------------

    def _cache_key(self, inp: PricingInput) -> str:
        """Build a cache key from route + vehicle info."""
        parts = [
            inp.pickup_city.upper(),
            inp.pickup_state.upper(),
            inp.pickup_zip or "",
            inp.delivery_city.upper(),
            inp.delivery_state.upper(),
            inp.delivery_zip or "",
            inp.vehicle_type,
            str(inp.is_enclosed),
            str(inp.is_operable),
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def _cache_get(self, key: str) -> Optional[PricingResult]:
        """Get cached result if not expired."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.expired:
            del self._cache[key]
            return None
        return entry.result

    def _cache_put(self, key: str, result: PricingResult) -> None:
        """Store result in cache with TTL."""
        self._cache[key] = _CacheEntry(result, self._cache_ttl)

    def _apply_urgency_to_cached(
        self, cached: PricingResult, urgency: Urgency
    ) -> PricingResult:
        """Return a copy of cached result with updated urgency applied."""
        if cached.base_price is None:
            # Fallback result, return as-is
            result = PricingResult(
                source=cached.source,
                warnings=list(cached.warnings),
                urgency=urgency,
                urgency_multiplier=URGENCY_MULTIPLIERS[urgency],
            )
            return result

        result = PricingResult(
            base_price=cached.base_price,
            avg_dispatch_price=cached.avg_dispatch_price,
            spread=cached.spread,
            source=cached.source,
            is_enclosed=cached.is_enclosed,
            distance_miles=cached.distance_miles,
            urgency=urgency,
            urgency_multiplier=URGENCY_MULTIPLIERS[urgency],
            cached=True,
        )

        modified = cached.base_price * URGENCY_MULTIPLIERS[urgency]

        # Re-apply floor/ceiling
        if cached.avg_dispatch_price:
            modified = PricingEngine._apply_floor(
                modified, cached.avg_dispatch_price, cached.distance_miles, result
            )
            modified = PricingEngine._apply_ceiling(
                modified,
                cached.avg_dispatch_price,
                cached.distance_miles,
                cached.is_enclosed,
                result,
            )
            PricingEngine._check_warnings(
                modified, cached.avg_dispatch_price, result
            )

        result.recommended_price = round(modified, 2)
        return result

    def clear_cache(self) -> int:
        """Clear all cached entries. Returns number cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count

    def cache_size(self) -> int:
        """Return number of cached entries (including expired)."""
        return len(self._cache)


# Module-level singleton
_engine: Optional[PricingEngine] = None


def get_pricing_engine() -> PricingEngine:
    """Get the PricingEngine singleton."""
    global _engine
    if _engine is None:
        _engine = PricingEngine()
    return _engine
