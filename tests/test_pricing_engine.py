"""
PricingEngine Tests

Tests the full pricing formula:
  Base formula, urgency modifiers, floor/ceiling guardrails,
  warnings, cache, and MI API fallback.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from services.pricing_engine import (
    CACHE_TTL_SECONDS,
    CEILING_AVG_FACTOR,
    CEILING_PER_MILE_ENCLOSED,
    CEILING_PER_MILE_OPEN,
    FLOOR_ABSOLUTE,
    FLOOR_AVG_FACTOR,
    FLOOR_PER_MILE,
    WARNING_HIGH_FACTOR,
    WARNING_LOW_FACTOR,
    PriceSource,
    PricingEngine,
    PricingInput,
    PricingResult,
    Urgency,
)
from api.mi_client import MarketIntelligenceClient, MIPriceQuote


def _make_quote(suggested=500.0, low=400.0, high=600.0, confidence=0.8):
    """Create a mock MIPriceQuote."""
    return MIPriceQuote(
        suggested_price=suggested,
        low_price=low,
        high_price=high,
        confidence=confidence,
        source="MARKET_INTELLIGENCE",
    )


def _make_engine(quote=None):
    """Create PricingEngine with mocked MarketIntelligenceClient."""
    mock_client = MagicMock(spec=MarketIntelligenceClient)
    mock_client.get_list_prices.return_value = quote
    engine = PricingEngine(mi_client=mock_client, cache_ttl=CACHE_TTL_SECONDS)
    return engine


def _default_input(**overrides) -> PricingInput:
    """Create a default PricingInput with empty states (no auto-distance)."""
    defaults = dict(
        pickup_city="MANHEIM",
        pickup_state="PA",
        delivery_city="AYER",
        delivery_state="MA",
        urgency=Urgency.STANDARD,
    )
    defaults.update(overrides)
    return PricingInput(**defaults)


def _no_distance_input(**overrides) -> PricingInput:
    """Create a PricingInput with empty states so distance is None.

    This isolates tests from per-mile floor/ceiling effects.
    """
    defaults = dict(
        pickup_city="CITY_A",
        pickup_state="",
        delivery_city="CITY_B",
        delivery_state="",
        urgency=Urgency.STANDARD,
    )
    defaults.update(overrides)
    return PricingInput(**defaults)


# =============================================================================
# BASE FORMULA TESTS
# =============================================================================


class TestBaseFormula:
    """Test base price formula: avg_dispatch + (spread x 0.5).

    The new engine computes avg_listing = high_price (or suggested*1.1 if None),
    and spread = avg_listing - avg_dispatch.
    """

    def test_base_with_zero_spread(self):
        """When high_price equals suggested, spread is zero."""
        # suggested=500, high=500 -> avg_listing=500, spread=0
        quote = _make_quote(suggested=500.0, low=400.0, high=500.0)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input())

        assert result.avg_dispatch_price == 500.0
        assert result.spread == 0.0
        # base = 500 + (0 * 0.5) = 500
        assert result.price == 500.0

    def test_base_with_positive_spread(self):
        """Positive spread (high > suggested) increases base price."""
        # suggested=400, high=550 -> avg_listing=550, spread=150
        quote = _make_quote(suggested=400.0, low=450.0, high=550.0)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input())

        assert result.avg_dispatch_price == 400.0
        assert result.spread == 150.0
        assert result.price == 475.0  # 400 + (150 x 0.5)

    def test_base_with_negative_spread(self):
        """Negative spread (high < suggested) decreases base price."""
        # suggested=600, high=500 -> avg_listing=500, spread=-100
        quote = _make_quote(suggested=600.0, low=400.0, high=500.0)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input())

        assert result.spread == -100.0
        assert result.price == 550.0  # 600 + (-100 x 0.5)

    def test_base_no_high_price(self):
        """When high_price is None, avg_listing = suggested * 1.1."""
        # suggested=500, high=None -> avg_listing=550, spread=50
        quote = _make_quote(suggested=500.0, low=None, high=None)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input())

        assert result.spread == 50.0  # 550 - 500
        assert result.price == 525.0  # 500 + (50 x 0.5)

    def test_source_is_cd_market_intelligence(self):
        """Source should be CD_MARKET_INTELLIGENCE when quote is available."""
        engine = _make_engine(_make_quote(suggested=500.0, high=500.0))
        result = engine.calculate(_no_distance_input())
        assert result.source == PriceSource.CD_MARKET_INTELLIGENCE


# =============================================================================
# URGENCY MODIFIER TESTS
# =============================================================================


class TestUrgencyModifiers:
    """Test urgency multipliers applied to base price."""

    def test_standard_multiplier(self):
        """STANDARD = x1.0, no change."""
        # suggested=500, high=500 -> base=500
        engine = _make_engine(_make_quote(suggested=500.0, high=500.0))
        result = engine.calculate(_no_distance_input(urgency=Urgency.STANDARD))

        assert result.urgency == Urgency.STANDARD
        assert result.urgency_multiplier == 1.0
        assert result.price == 500.0

    def test_priority_multiplier(self):
        """PRIORITY = x1.12."""
        engine = _make_engine(_make_quote(suggested=500.0, high=500.0))
        result = engine.calculate(_no_distance_input(urgency=Urgency.PRIORITY))

        assert result.urgency == Urgency.PRIORITY
        assert result.urgency_multiplier == 1.12
        assert result.price == 560.0  # 500 x 1.12

    def test_urgent_multiplier(self):
        """URGENT = x1.25."""
        engine = _make_engine(_make_quote(suggested=500.0, high=500.0))
        result = engine.calculate(_no_distance_input(urgency=Urgency.URGENT))

        assert result.urgency == Urgency.URGENT
        assert result.urgency_multiplier == 1.25
        assert result.price == 625.0  # 500 x 1.25


# =============================================================================
# FLOOR TESTS
# =============================================================================


class TestFloorGuardrails:
    """Test floor enforcement: max($150, $0.40/mile, avg*0.85).

    Uses empty states (no distance) for absolute and avg-factor tests,
    and FL->NY (approx 1059 miles) for the per-mile test.
    """

    def test_floor_absolute(self):
        """Price below $150 should be raised to $150."""
        # suggested=100, high=None -> avg_listing=110, spread=10, base=105
        # No distance: floor = max($150, 100*0.85=$85) = $150
        # ceiling = 100*1.50 = $150
        # final = max($150, min($150, 105)) = $150
        quote = _make_quote(suggested=100.0, low=None, high=None)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input())

        assert result.price == FLOOR_ABSOLUTE
        assert result.floor == FLOOR_ABSOLUTE

    def test_floor_avg_factor(self):
        """When avg*0.85 is higher than $150, use that."""
        # suggested=500, high=100 -> avg_listing=100, spread=-400, base=300
        # No distance: floor = max($150, 500*0.85=$425) = $425
        # ceiling = 500*1.50 = $750
        # final = max($425, min($750, 300)) = $425
        quote = _make_quote(suggested=500.0, low=100.0, high=100.0)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input())

        assert result.floor == 425.0
        assert result.price == 425.0

    def test_floor_per_mile(self):
        """$0.40/mile floor when distance is known (FL -> NY route)."""
        # FL->NY is approx 1059 miles (from state centroids)
        # suggested=300, high=None -> avg_listing=330, spread=30, base=315
        # floor = max($150, 1059*$0.40=$423.75, 300*0.85=$255) = $423.75
        # ceiling = min(300*1.50=$450, 1059*$2.00=$2118.77) = $450
        # final = max($423.75, min($450, 315)) = $423.75
        quote = _make_quote(suggested=300.0, low=None, high=None)
        engine = _make_engine(quote)
        result = engine.calculate(PricingInput(
            pickup_city="ORLANDO",
            pickup_state="FL",
            delivery_city="NEW YORK",
            delivery_state="NY",
            urgency=Urgency.STANDARD,
        ))

        # Per-mile floor should be the binding constraint
        assert result.floor > FLOOR_ABSOLUTE
        assert result.floor > 300.0 * FLOOR_AVG_FACTOR  # > $255
        assert result.price == result.floor  # Floor was applied

    def test_no_floor_when_price_above(self):
        """No floor applied when price is above all floors."""
        # suggested=500, high=500 -> base=500
        # No distance: floor = max($150, $425) = $425
        # final = 500 > 425
        quote = _make_quote(suggested=500.0, high=500.0)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input())

        assert result.price > result.floor


# =============================================================================
# CEILING TESTS
# =============================================================================


class TestCeilingGuardrails:
    """Test ceiling enforcement: min($X/mile, avg*1.50).

    Uses empty states for avg-factor and isolation tests,
    and NJ->CT (approx 142 miles) for per-mile ceiling tests.
    """

    def test_ceiling_avg_factor(self):
        """Price above avg*1.50 should be capped."""
        # suggested=200, high=800 -> spread=600, base=500, URGENT=625
        # No distance: floor = max($150, 200*0.85=$170) = $170
        # ceiling = 200*1.50 = $300
        # final = max($170, min($300, 625)) = $300
        quote = _make_quote(suggested=200.0, low=800.0, high=800.0)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input(urgency=Urgency.URGENT))

        assert result.ceiling == 300.0
        assert result.price == 300.0

    def test_ceiling_per_mile_open(self):
        """$2.00/mile ceiling for open trailers (NJ -> CT route)."""
        # NJ->CT approx 142 miles -> $2.00*142=$284.51
        # suggested=300, high=800 -> spread=500, base=550, URGENT=687.5
        # floor = max($150, 142*$0.40=$56.9, 300*$0.85=$255) = $255
        # ceiling = min(300*1.50=$450, 142*$2.00=$284.51) = $284.51
        # final = max($255, min($284.51, 687.5)) = $284.51
        quote = _make_quote(suggested=300.0, low=800.0, high=800.0)
        engine = _make_engine(quote)
        result = engine.calculate(PricingInput(
            pickup_city="TRENTON",
            pickup_state="NJ",
            delivery_city="HARTFORD",
            delivery_state="CT",
            urgency=Urgency.URGENT,
            is_enclosed=False,
        ))

        # Per-mile ceiling (open) should be binding
        assert result.ceiling < 300.0 * CEILING_AVG_FACTOR  # < $450
        assert result.price == result.ceiling

    def test_ceiling_per_mile_enclosed(self):
        """$3.00/mile ceiling for enclosed trailers (NJ -> CT route)."""
        # NJ->CT approx 142 miles -> $3.00*142=$426.76
        # suggested=300, high=800 -> spread=500, base=550, URGENT=687.5
        # floor = max($150, 142*$0.40, 300*0.85=$255) = $255
        # ceiling = min(300*1.50=$450, 142*$3.00=$426.76) = $426.76
        # final = max($255, min($426.76, 687.5)) = $426.76
        quote = _make_quote(suggested=300.0, low=800.0, high=800.0)
        engine = _make_engine(quote)
        result = engine.calculate(PricingInput(
            pickup_city="TRENTON",
            pickup_state="NJ",
            delivery_city="HARTFORD",
            delivery_state="CT",
            urgency=Urgency.URGENT,
            is_enclosed=True,
        ))

        # Per-mile enclosed ceiling is higher than open
        assert result.ceiling < 300.0 * CEILING_AVG_FACTOR  # < $450
        assert result.price == result.ceiling

    def test_no_ceiling_when_price_below(self):
        """No ceiling applied when price is within range."""
        # suggested=500, high=500 -> base=500
        # No distance: ceiling = 500*1.50 = $750
        # final = 500 < 750
        quote = _make_quote(suggested=500.0, high=500.0)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input())

        assert result.price < result.ceiling


# =============================================================================
# WARNING TESTS
# =============================================================================


class TestWarnings:
    """Test low/high price warnings."""

    def test_warning_low(self):
        """Warning when price < avg*0.90."""
        # suggested=500, high=100 -> spread=-400, base=300
        # No distance: floor = max($150, $425) = $425
        # final = $425 < 500*0.90=$450 -> LOW warning
        quote = _make_quote(suggested=500.0, low=100.0, high=100.0)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input())

        assert any("below 90%" in w for w in result.warnings)

    def test_warning_high(self):
        """Warning when price > avg*1.30."""
        # suggested=400, high=600 -> spread=200, base=500
        # URGENT: 500*1.25=625
        # No distance: ceiling = 400*1.50=$600
        # final = min($600, 625) = $600
        # $600 > 400*1.30=$520 -> HIGH warning
        quote = _make_quote(suggested=400.0, low=600.0, high=600.0)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input(urgency=Urgency.URGENT))

        assert any("above 130%" in w for w in result.warnings)

    def test_no_warning_in_normal_range(self):
        """No warnings when price is within normal range."""
        # suggested=500, high=500 -> base=500, STANDARD=500
        # 500/500 = 1.0 -> no warning
        quote = _make_quote(suggested=500.0, high=500.0)
        engine = _make_engine(quote)
        result = engine.calculate(_no_distance_input())

        price_warnings = [
            w for w in result.warnings if "below 90%" in w or "above 130%" in w
        ]
        assert len(price_warnings) == 0


# =============================================================================
# FALLBACK TESTS
# =============================================================================


class TestFallback:
    """Test fallback when MI API is unavailable."""

    def test_none_quote_returns_manual_required(self):
        """When MI returns None, source=MANUAL_REQUIRED."""
        engine = _make_engine(None)
        result = engine.calculate(_default_input())

        assert result.source == PriceSource.MANUAL_REQUIRED
        assert result.price is None
        assert any("manual" in w.lower() for w in result.warnings)

    def test_zero_price_returns_manual_required(self):
        """When MI returns 0 price, source=MANUAL_REQUIRED."""
        quote = _make_quote(suggested=0.0)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        assert result.source == PriceSource.MANUAL_REQUIRED

    def test_negative_price_returns_manual_required(self):
        """When MI returns negative price, source=MANUAL_REQUIRED."""
        quote = _make_quote(suggested=-100.0)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        assert result.source == PriceSource.MANUAL_REQUIRED

    def test_client_exception_returns_manual_required(self):
        """When MI client raises, source=MANUAL_REQUIRED."""
        mock_client = MagicMock(spec=MarketIntelligenceClient)
        mock_client.get_list_prices.side_effect = Exception("Connection timeout")
        engine = PricingEngine(mi_client=mock_client)
        result = engine.calculate(_default_input())

        assert result.source == PriceSource.MANUAL_REQUIRED

    def test_missing_pickup_returns_manual_required(self):
        """When MI client returns None for empty route, source=MANUAL_REQUIRED."""
        # With no valid pickup, the MI client mock returns None
        engine = _make_engine(None)
        result = engine.calculate(PricingInput(
            delivery_city="AYER", delivery_state="MA",
        ))

        assert result.source == PriceSource.MANUAL_REQUIRED


# =============================================================================
# CACHE TESTS
# =============================================================================


class TestCache:
    """Test 24h TTL cache."""

    def test_second_call_uses_cache(self):
        """Second identical request should use cache."""
        quote = _make_quote(suggested=500.0, high=500.0)
        engine = _make_engine(quote)
        inp = _no_distance_input()

        result1 = engine.calculate(inp)
        result2 = engine.calculate(inp)

        assert result1.price == result2.price
        assert result2.cached is True
        # MI client should only be called once
        assert engine.mi_client.get_list_prices.call_count == 1

    def test_different_routes_not_cached(self):
        """Different routes should not share cache."""
        engine = _make_engine(_make_quote(suggested=500.0, high=500.0))

        inp1 = _no_distance_input(pickup_city="MANHEIM", delivery_city="AYER")
        inp2 = _no_distance_input(pickup_city="TAMPA", delivery_city="BOSTON")

        engine.calculate(inp1)
        engine.calculate(inp2)

        assert engine.mi_client.get_list_prices.call_count == 2

    def test_cache_expires(self):
        """Cache entries expire after TTL."""
        mock_client = MagicMock(spec=MarketIntelligenceClient)
        mock_client.get_list_prices.return_value = _make_quote(
            suggested=500.0, high=500.0
        )
        engine = PricingEngine(mi_client=mock_client, cache_ttl=1)  # 1 second TTL

        inp = _no_distance_input()
        engine.calculate(inp)

        # Wait for cache to expire
        time.sleep(1.1)

        result = engine.calculate(inp)
        assert result.cached is False
        assert mock_client.get_list_prices.call_count == 2

    def test_clear_cache(self):
        """clear_cache() should empty all entries."""
        engine = _make_engine(_make_quote(suggested=500.0, high=500.0))
        engine.calculate(_no_distance_input())
        assert engine.cache_size() == 1

        cleared = engine.clear_cache()
        assert cleared == 1
        assert engine.cache_size() == 0

    def test_cached_result_with_different_urgency(self):
        """Cached result should re-apply new urgency modifier."""
        # suggested=500, high=500 -> base=500
        engine = _make_engine(_make_quote(suggested=500.0, high=500.0))

        # First call with STANDARD -> price=500
        result1 = engine.calculate(_no_distance_input(urgency=Urgency.STANDARD))
        assert result1.price == 500.0

        # Second call with URGENT -> should use cache but apply x1.25
        result2 = engine.calculate(_no_distance_input(urgency=Urgency.URGENT))
        assert result2.cached is True
        assert result2.price == 625.0  # 500 x 1.25


# =============================================================================
# SCHEMA TESTS
# =============================================================================


class TestSheetsSchemaColumns:
    """Test that pricing columns exist in sheets schema."""

    def test_suggested_price_column_exists(self):
        """suggested_price column should be in schema."""
        from schemas.sheets_schema_v1 import COLUMNS

        names = [c.name for c in COLUMNS]
        assert "suggested_price" in names

    def test_price_source_column_exists(self):
        """price_source column should be in schema."""
        from schemas.sheets_schema_v1 import COLUMNS

        names = [c.name for c in COLUMNS]
        assert "price_source" in names

    def test_price_warnings_column_exists(self):
        """price_warnings column should be in schema."""
        from schemas.sheets_schema_v1 import COLUMNS

        names = [c.name for c in COLUMNS]
        assert "price_warnings" in names

    def test_urgency_column_exists(self):
        """urgency column should be in schema."""
        from schemas.sheets_schema_v1 import COLUMNS

        names = [c.name for c in COLUMNS]
        assert "urgency" in names

    def test_urgency_enum_values(self):
        """urgency column should have correct enum values."""
        from schemas.sheets_schema_v1 import COLUMNS

        urgency_col = next(c for c in COLUMNS if c.name == "urgency")
        assert set(urgency_col.enum_values) == {"STANDARD", "PRIORITY", "URGENT"}


# =============================================================================
# INTEGRATION SANITY
# =============================================================================


class TestPricingEngineIntegration:
    """Integration-level checks (mocked MI)."""

    def test_full_calculation_with_all_fields(self):
        """Full calculation with all optional fields."""
        engine = _make_engine(_make_quote(suggested=450.0, low=400.0, high=550.0))
        result = engine.calculate(PricingInput(
            pickup_city="MANHEIM",
            pickup_state="PA",
            pickup_zip="17545",
            delivery_city="AYER",
            delivery_state="MA",
            delivery_zip="01432",
            vehicle_vin="YV4A22PMXG1037898",
            vehicle_year=2016,
            vehicle_make="VOLVO",
            vehicle_model="XC90",
            vehicle_type="SUV",
            is_operable=True,
            is_enclosed=False,
            urgency=Urgency.PRIORITY,
        ))

        assert result.source == PriceSource.CD_MARKET_INTELLIGENCE
        assert result.price is not None
        assert result.price > 0
        assert result.urgency == Urgency.PRIORITY

    def test_result_dataclass_fields(self):
        """PricingResult should have all expected fields."""
        result = PricingResult()
        assert hasattr(result, "price")
        assert hasattr(result, "avg_dispatch_price")
        assert hasattr(result, "spread")
        assert hasattr(result, "urgency")
        assert hasattr(result, "urgency_multiplier")
        assert hasattr(result, "floor")
        assert hasattr(result, "ceiling")
        assert hasattr(result, "source")
        assert hasattr(result, "warnings")
        assert hasattr(result, "distance_miles")
        assert hasattr(result, "cached")

    def test_singleton_factory(self):
        """get_pricing_engine() returns singleton."""
        from services.pricing_engine import get_pricing_engine, reset_pricing_engine

        # Reset to ensure clean state
        reset_pricing_engine()
        try:
            engine1 = get_pricing_engine()
            engine2 = get_pricing_engine()
            assert engine1 is engine2
        finally:
            reset_pricing_engine()
