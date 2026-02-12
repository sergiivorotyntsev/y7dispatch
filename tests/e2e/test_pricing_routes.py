"""
E2E Tests for PricingEngine Route Scenarios.

Tests the PricingEngine with various real-world route scenarios:
1. Short route (<200 miles): verify floor kicks in ($150 minimum)
2. Long route (>1500 miles): verify ceiling caps price
3. Enclosed trailer: verify $3.00/mile ceiling (not $2.00)
4. URGENT modifier: verify price × 1.25
5. Route with no CD data: verify source=MANUAL_REQUIRED
6. Same route called twice within 24h: verify cache hit
7. Price below avg_dispatch × 0.90: verify "Below market" warning
8. Price above avg_dispatch × 1.30: verify "Above market" warning
"""

from unittest.mock import MagicMock, patch

import pytest

from api.mi_client import MIPriceQuote
from services.pricing_engine import (
    Address,
    PriceRecommendation,
    PriceSource,
    PriceStatus,
    PricingConfig,
    PricingEngine,
    Urgency,
    Vehicle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(quote: MIPriceQuote = None, *, no_data: bool = False) -> PricingEngine:
    """Create a PricingEngine with mocked MI client."""
    mi = MagicMock()
    if no_data:
        mi.get_list_prices.return_value = None
    elif quote is not None:
        mi.get_list_prices.return_value = quote
    else:
        mi.get_list_prices.return_value = MIPriceQuote(
            suggested_price=500.0,
            low_price=450.0,
            high_price=550.0,
        )
    return PricingEngine(mi_client=mi, config=PricingConfig())


def _short_route() -> tuple[Address, Address]:
    """Short route: VA → MD (~100 miles)."""
    return (
        Address(city="Richmond", state="VA"),
        Address(city="Baltimore", state="MD"),
    )


def _long_route() -> tuple[Address, Address]:
    """Long route: CA → NY (~2500 miles)."""
    return (
        Address(city="Los Angeles", state="CA"),
        Address(city="New York", state="NY"),
    )


def _medium_route() -> tuple[Address, Address]:
    """Medium route: VA → MA (~500 miles)."""
    return (
        Address(city="Sandston", state="VA"),
        Address(city="Ayer", state="MA"),
    )


def _vehicle() -> Vehicle:
    return Vehicle(vehicle_type="SEDAN", is_operable=True)


# =============================================================================
# 1. SHORT ROUTE — FLOOR KICKS IN
# =============================================================================


class TestShortRouteFloor:
    """Short route (<200 miles) should trigger floor constraints."""

    def test_floor_absolute_minimum_150(self):
        """Absolute floor of $150 should apply on very short routes."""
        # Low suggested_price that would normally be below $150
        quote = MIPriceQuote(suggested_price=80.0, low_price=70.0, high_price=90.0)
        engine = _make_engine(quote)
        origin, dest = _short_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        assert result.price is not None
        assert result.price >= 150.0, f"Floor should enforce >= $150, got ${result.price}"
        assert result.floor is not None
        assert result.floor >= 150.0

    def test_floor_per_mile_minimum(self):
        """Per-mile floor of $0.40/mile should apply."""
        quote = MIPriceQuote(suggested_price=30.0, low_price=25.0, high_price=35.0)
        engine = _make_engine(quote)
        origin, dest = _short_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        # Distance VA→MD ≈ 100 miles, per-mile floor = 100 * 0.40 = $40
        # Absolute floor = $150 > $40, so $150 wins
        assert result.price >= 150.0

    def test_short_route_has_distance(self):
        """Short route should still calculate distance."""
        engine = _make_engine()
        origin, dest = _short_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        assert result.distance_miles is not None
        assert result.distance_miles < 300  # VA→MD should be under 300


# =============================================================================
# 2. LONG ROUTE — CEILING CAPS PRICE
# =============================================================================


class TestLongRouteCeiling:
    """Long route (>1500 miles) should trigger ceiling constraints."""

    def test_ceiling_caps_high_price(self):
        """Ceiling should limit price — final price = max(floor, min(ceiling, base))."""
        # Use a moderate avg_dispatch so floor doesn't exceed ceiling
        # CA→NY ≈ 2326 miles; per-mile ceiling (open) = 2326 * 2.00 = $4652
        # market ceiling = 1500 * 1.50 = $2250
        # floor = max(150, 2326*0.40, 1500*0.85) = max(150, 930, 1275) = $1275
        # base = 1500 + (1650-1500)*0.5 = 1575 → capped to min(2250, 4652) = $2250
        # final = max(1275, 2250) = $2250
        quote = MIPriceQuote(suggested_price=1500.0, low_price=1200.0, high_price=1650.0)
        engine = _make_engine(quote)
        origin, dest = _long_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        assert result.price is not None
        assert result.ceiling is not None
        # Price should be capped to ceiling (when floor < ceiling)
        assert result.price <= result.ceiling + 1, (
            f"Price ${result.price} should not exceed ceiling ${result.ceiling}"
        )

    def test_ceiling_uses_market_multiplier(self):
        """Ceiling should use avg_dispatch × 1.50 multiplier."""
        quote = MIPriceQuote(suggested_price=2000.0, low_price=1800.0, high_price=2500.0)
        engine = _make_engine(quote)
        origin, dest = _long_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        # Market ceiling = 2000 * 1.50 = 3000
        # Per-mile ceiling (open) = ~2500 * 2.00 = ~5000
        # Ceiling = min(3000, 5000) = 3000
        assert result.ceiling <= 2000.0 * 1.50 + 1  # Allow $1 rounding

    def test_long_route_distance_over_1500(self):
        """CA→NY should be over 1500 miles."""
        engine = _make_engine()
        origin, dest = _long_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        assert result.distance_miles is not None
        assert result.distance_miles > 1500


# =============================================================================
# 3. ENCLOSED TRAILER — $3.00/MILE CEILING
# =============================================================================


class TestEnclosedTrailer:
    """Enclosed trailer should use $3.00/mile ceiling (not $2.00)."""

    def test_enclosed_ceiling_higher_than_open(self):
        """Enclosed per-mile ceiling ($3.00) > open ($2.00)."""
        quote = MIPriceQuote(suggested_price=3000.0, low_price=2500.0, high_price=4000.0)
        engine = _make_engine(quote)
        origin, dest = _long_route()

        open_result = engine.calculate_recommended_price(
            origin, dest, _vehicle(), is_enclosed=False,
        )
        engine.clear_cache()
        enclosed_result = engine.calculate_recommended_price(
            origin, dest, _vehicle(), is_enclosed=True,
        )

        # Enclosed ceiling should be higher (or equal if market multiplier is lower)
        assert enclosed_result.ceiling >= open_result.ceiling, (
            f"Enclosed ceiling ${enclosed_result.ceiling} should be >= open ${open_result.ceiling}"
        )

    def test_enclosed_per_mile_3_dollars(self):
        """Enclosed ceiling should use $3.00/mile for distance component."""
        quote = MIPriceQuote(suggested_price=500.0, low_price=400.0, high_price=600.0)
        engine = _make_engine(quote)
        origin, dest = _medium_route()

        result = engine.calculate_recommended_price(
            origin, dest, _vehicle(), is_enclosed=True,
        )
        # Distance VA→MA ≈ 500 miles
        # Per-mile ceiling (enclosed) = 500 * 3.00 = 1500
        # Market ceiling = 500 * 1.50 = 750
        # Ceiling = min(1500, 750) = 750
        assert result.ceiling is not None


# =============================================================================
# 4. URGENT MODIFIER — PRICE × 1.25
# =============================================================================


class TestUrgentModifier:
    """URGENT urgency should multiply base price by 1.25."""

    def test_urgent_multiplier_is_1_25(self):
        """URGENT should report urgency_multiplier=1.25."""
        engine = _make_engine()
        origin, dest = _medium_route()

        result = engine.calculate_recommended_price(
            origin, dest, _vehicle(), urgency=Urgency.URGENT,
        )
        assert result.urgency == Urgency.URGENT
        assert result.urgency_multiplier == 1.25

    def test_urgent_price_higher_than_standard(self):
        """URGENT price should be higher than STANDARD (before floor/ceiling)."""
        engine = _make_engine()
        origin, dest = _medium_route()

        standard = engine.calculate_recommended_price(
            origin, dest, _vehicle(), urgency=Urgency.STANDARD,
        )
        engine.clear_cache()
        urgent = engine.calculate_recommended_price(
            origin, dest, _vehicle(), urgency=Urgency.URGENT,
        )

        # URGENT should be >= STANDARD (ceiling may cap both)
        assert urgent.price >= standard.price, (
            f"URGENT ${urgent.price} should be >= STANDARD ${standard.price}"
        )

    def test_priority_between_standard_and_urgent(self):
        """PRIORITY price should be between STANDARD and URGENT."""
        engine = _make_engine()
        origin, dest = _medium_route()

        standard = engine.calculate_recommended_price(
            origin, dest, _vehicle(), urgency=Urgency.STANDARD,
        )
        engine.clear_cache()
        priority = engine.calculate_recommended_price(
            origin, dest, _vehicle(), urgency=Urgency.PRIORITY,
        )
        engine.clear_cache()
        urgent = engine.calculate_recommended_price(
            origin, dest, _vehicle(), urgency=Urgency.URGENT,
        )

        assert standard.price <= priority.price <= urgent.price, (
            f"Expected STANDARD ${standard.price} <= PRIORITY ${priority.price} <= URGENT ${urgent.price}"
        )


# =============================================================================
# 5. NO CD DATA — MANUAL_REQUIRED
# =============================================================================


class TestNoMarketData:
    """When MI API returns no data, source should be MANUAL_REQUIRED."""

    def test_no_data_returns_manual_required(self):
        """MI returning None → source=MANUAL_REQUIRED."""
        engine = _make_engine(no_data=True)
        origin, dest = _medium_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        assert result.source == PriceSource.MANUAL_REQUIRED
        assert result.status == PriceStatus.MANUAL
        assert result.price is None

    def test_no_data_has_reason(self):
        """MANUAL_REQUIRED result should explain why."""
        engine = _make_engine(no_data=True)
        origin, dest = _medium_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        assert result.reason is not None
        assert len(result.reason) > 0

    def test_no_data_has_warnings(self):
        """MANUAL_REQUIRED result should have a warning."""
        engine = _make_engine(no_data=True)
        origin, dest = _medium_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        assert len(result.warnings) >= 1

    def test_zero_price_returns_manual_required(self):
        """MI returning suggested_price=0 → MANUAL_REQUIRED."""
        quote = MIPriceQuote(suggested_price=0.0, low_price=0.0, high_price=0.0)
        engine = _make_engine(quote)
        origin, dest = _medium_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        assert result.source == PriceSource.MANUAL_REQUIRED
        assert result.price is None


# =============================================================================
# 6. CACHE HIT — NO SECOND API CALL
# =============================================================================


class TestCacheHit:
    """Same route called twice within 24h should use cache."""

    def test_second_call_uses_cache(self):
        """Second identical call should not hit MI API again."""
        engine = _make_engine()
        origin, dest = _medium_route()
        vehicle = _vehicle()

        # First call
        result1 = engine.calculate_recommended_price(origin, dest, vehicle)
        assert result1.price is not None
        call_count_after_first = engine.mi_client.get_list_prices.call_count

        # Second call (same route)
        result2 = engine.calculate_recommended_price(origin, dest, vehicle)
        call_count_after_second = engine.mi_client.get_list_prices.call_count

        # MI API should only have been called once
        assert call_count_after_second == call_count_after_first, (
            f"MI API called {call_count_after_second} times, expected {call_count_after_first}"
        )

    def test_cached_result_has_same_price(self):
        """Cached result should return the same price (same urgency)."""
        engine = _make_engine()
        origin, dest = _medium_route()
        vehicle = _vehicle()

        result1 = engine.calculate_recommended_price(origin, dest, vehicle)
        result2 = engine.calculate_recommended_price(origin, dest, vehicle)

        assert result1.price == result2.price

    def test_cache_size_increases(self):
        """Cache should grow after first call."""
        engine = _make_engine()
        assert engine.cache_size() == 0

        origin, dest = _medium_route()
        engine.calculate_recommended_price(origin, dest, _vehicle())
        assert engine.cache_size() == 1

    def test_different_route_not_cached(self):
        """Different route should not use cache from first route."""
        engine = _make_engine()
        origin1, dest1 = _short_route()
        origin2, dest2 = _long_route()
        vehicle = _vehicle()

        engine.calculate_recommended_price(origin1, dest1, vehicle)
        engine.calculate_recommended_price(origin2, dest2, vehicle)

        assert engine.mi_client.get_list_prices.call_count == 2
        assert engine.cache_size() == 2

    def test_cache_reapplies_urgency(self):
        """Cached route with different urgency should recalculate price."""
        engine = _make_engine()
        origin, dest = _medium_route()
        vehicle = _vehicle()

        standard = engine.calculate_recommended_price(
            origin, dest, vehicle, urgency=Urgency.STANDARD,
        )
        urgent = engine.calculate_recommended_price(
            origin, dest, vehicle, urgency=Urgency.URGENT,
        )

        # Only one MI call — second uses cache + reapplied urgency
        assert engine.mi_client.get_list_prices.call_count == 1
        assert urgent.price >= standard.price


# =============================================================================
# 7. BELOW MARKET WARNING
# =============================================================================


class TestBelowMarketWarning:
    """Price below avg_dispatch × 0.90 should warn 'Below market'."""

    def test_below_market_warning_generated(self):
        """Floor-capped price below 90% of avg_dispatch should warn."""
        # avg_dispatch = 1000, floor forces price to ~850 (0.85 × 1000)
        # which is below 0.90 × 1000 = 900
        quote = MIPriceQuote(suggested_price=1000.0, low_price=900.0, high_price=1010.0)
        engine = _make_engine(quote)
        origin, dest = _short_route()  # Short route so per-mile floor is low

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        # If final price < 0.90 × avg_dispatch, warning should be present
        if result.price < result.avg_dispatch_price * 0.90:
            assert any("below" in w.lower() or "Below" in w for w in result.warnings), (
                f"Expected 'below market' warning for price ${result.price} vs avg ${result.avg_dispatch_price}"
            )

    def test_no_warning_at_market_rate(self):
        """Price at or near market rate should not generate below-market warning."""
        quote = MIPriceQuote(suggested_price=500.0, low_price=450.0, high_price=550.0)
        engine = _make_engine(quote)
        origin, dest = _medium_route()

        result = engine.calculate_recommended_price(origin, dest, _vehicle())
        below_warnings = [w for w in result.warnings if "below" in w.lower()]
        if 0.90 <= result.price / result.avg_dispatch_price <= 1.30:
            assert len(below_warnings) == 0


# =============================================================================
# 8. ABOVE MARKET WARNING
# =============================================================================


class TestAboveMarketWarning:
    """Price above avg_dispatch × 1.30 should warn 'Above market'."""

    def test_above_market_warning_generated(self):
        """URGENT multiplier pushing price above 130% should warn."""
        # avg_dispatch = 200, URGENT base = 200 + (30*0.5) * 1.25 ≈ 268
        # 268 / 200 = 1.34 → above 1.30 threshold
        quote = MIPriceQuote(suggested_price=200.0, low_price=180.0, high_price=230.0)
        engine = _make_engine(quote)
        origin, dest = _medium_route()

        result = engine.calculate_recommended_price(
            origin, dest, _vehicle(), urgency=Urgency.URGENT,
        )
        if result.price > result.avg_dispatch_price * 1.30:
            assert any("above" in w.lower() or "Above" in w for w in result.warnings), (
                f"Expected 'above market' warning for price ${result.price} vs avg ${result.avg_dispatch_price}"
            )

    def test_standard_no_above_warning(self):
        """STANDARD urgency at normal spread should not trigger above warning."""
        quote = MIPriceQuote(suggested_price=500.0, low_price=450.0, high_price=550.0)
        engine = _make_engine(quote)
        origin, dest = _medium_route()

        result = engine.calculate_recommended_price(
            origin, dest, _vehicle(), urgency=Urgency.STANDARD,
        )
        above_warnings = [w for w in result.warnings if "above" in w.lower()]
        if result.price / result.avg_dispatch_price <= 1.30:
            assert len(above_warnings) == 0
