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


def _make_quote(suggested=500.0, low=400.0, high=600.0, confidence=0.8):
    """Create a mock MIPriceQuote."""
    from api.mi_client import MIPriceQuote

    return MIPriceQuote(
        suggested_price=suggested,
        low_price=low,
        high_price=high,
        confidence=confidence,
        source="MARKET_INTELLIGENCE",
    )


def _make_engine(quote=None):
    """Create PricingEngine with mocked PricingService."""
    mock_service = MagicMock()
    mock_service.get_recommended_price.return_value = quote
    engine = PricingEngine(pricing_service=mock_service, cache_ttl=CACHE_TTL_SECONDS)
    return engine


def _default_input(**overrides) -> PricingInput:
    """Create a default PricingInput."""
    defaults = dict(
        pickup_city="MANHEIM",
        pickup_state="PA",
        delivery_city="AYER",
        delivery_state="MA",
        urgency=Urgency.STANDARD,
    )
    defaults.update(overrides)
    return PricingInput(**defaults)


# =============================================================================
# BASE FORMULA TESTS
# =============================================================================


class TestBaseFormula:
    """Test base price formula: avg_dispatch + (spread × 0.5)."""

    def test_base_with_spread(self):
        """Base = suggested + ((avg_listing - suggested) × 0.5)."""
        # suggested=500, low=400, high=600 → avg_listing=500, spread=0
        quote = _make_quote(suggested=500.0, low=400.0, high=600.0)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        assert result.avg_dispatch_price == 500.0
        assert result.spread == 0.0  # avg_listing (500) - suggested (500)
        assert result.base_price == 500.0

    def test_base_with_positive_spread(self):
        """Positive spread increases base price."""
        # suggested=400, low=450, high=550 → avg_listing=500, spread=100
        quote = _make_quote(suggested=400.0, low=450.0, high=550.0)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        assert result.avg_dispatch_price == 400.0
        assert result.spread == 100.0
        assert result.base_price == 450.0  # 400 + (100 × 0.5)

    def test_base_with_negative_spread(self):
        """Negative spread decreases base price."""
        # suggested=600, low=400, high=500 → avg_listing=450, spread=-150
        quote = _make_quote(suggested=600.0, low=400.0, high=500.0)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        assert result.spread == -150.0
        assert result.base_price == 525.0  # 600 + (-150 × 0.5)

    def test_base_no_low_high(self):
        """When low/high missing, spread=0."""
        quote = _make_quote(suggested=500.0, low=None, high=None)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        assert result.spread == 0.0
        assert result.base_price == 500.0

    def test_source_is_market_intelligence(self):
        """Source should be MI when quote is available."""
        engine = _make_engine(_make_quote())
        result = engine.calculate(_default_input())
        assert result.source == PriceSource.MARKET_INTELLIGENCE


# =============================================================================
# URGENCY MODIFIER TESTS
# =============================================================================


class TestUrgencyModifiers:
    """Test urgency multipliers."""

    def test_standard_multiplier(self):
        """STANDARD = ×1.0, no change."""
        engine = _make_engine(_make_quote(suggested=500.0, low=None, high=None))
        result = engine.calculate(_default_input(urgency=Urgency.STANDARD))

        assert result.urgency == Urgency.STANDARD
        assert result.urgency_multiplier == 1.0
        assert result.recommended_price == 500.0

    def test_priority_multiplier(self):
        """PRIORITY = ×1.12."""
        engine = _make_engine(_make_quote(suggested=500.0, low=None, high=None))
        result = engine.calculate(_default_input(urgency=Urgency.PRIORITY))

        assert result.urgency == Urgency.PRIORITY
        assert result.urgency_multiplier == 1.12
        assert result.recommended_price == 560.0  # 500 × 1.12

    def test_urgent_multiplier(self):
        """URGENT = ×1.25."""
        engine = _make_engine(_make_quote(suggested=500.0, low=None, high=None))
        result = engine.calculate(_default_input(urgency=Urgency.URGENT))

        assert result.urgency == Urgency.URGENT
        assert result.urgency_multiplier == 1.25
        assert result.recommended_price == 625.0  # 500 × 1.25


# =============================================================================
# FLOOR TESTS
# =============================================================================


class TestFloorGuardrails:
    """Test floor enforcement: max($150, $0.40/mile, avg×0.85)."""

    def test_floor_absolute(self):
        """Price below $150 should be raised to $150."""
        # Use a very low suggested price
        quote = _make_quote(suggested=100.0, low=None, high=None)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        # Floor = max($150, 100×0.85=$85) = $150
        assert result.recommended_price == FLOOR_ABSOLUTE
        assert result.floor_applied == FLOOR_ABSOLUTE

    def test_floor_avg_factor(self):
        """When avg×0.85 is higher than $150, use that."""
        # suggested=500, base=500, but simulate a scenario where
        # a negative spread pulls the base below 85% of avg
        # suggested=500, low=100, high=100 → avg_listing=100, spread=-400
        # base = 500 + (-400 × 0.5) = 300
        # Floor = max($150, 500×0.85=$425) = $425
        quote = _make_quote(suggested=500.0, low=100.0, high=100.0)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        assert result.floor_applied == 425.0
        assert result.recommended_price == 425.0

    def test_floor_per_mile(self):
        """$0.40/mile floor when distance is known."""
        # suggested=300, distance=1000 → $0.40×1000=$400
        # Floor = max($150, 300×0.85=$255, $400) = $400
        # Ceiling = 300×1.50=$450 → not triggered
        quote = _make_quote(suggested=300.0, low=None, high=None)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input(distance_miles=1000.0))

        assert result.floor_applied == 400.0
        assert result.recommended_price == 400.0

    def test_no_floor_when_price_above(self):
        """No floor applied when price is above all floors."""
        quote = _make_quote(suggested=500.0, low=None, high=None)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        assert result.floor_applied is None


# =============================================================================
# CEILING TESTS
# =============================================================================


class TestCeilingGuardrails:
    """Test ceiling enforcement: min($X/mile, avg×1.50)."""

    def test_ceiling_avg_factor(self):
        """Price above avg×1.50 should be capped."""
        # suggested=300, URGENT modifier → 300×1.25=375
        # Ceiling = 300×1.50 = 450 → price 375 < 450, no cap
        # Need base well above ceiling:
        # suggested=200, low=800, high=800 → spread=600, base=200+300=500
        # URGENT → 500×1.25=625
        # Ceiling = 200×1.50=300 → capped at 300
        quote = _make_quote(suggested=200.0, low=800.0, high=800.0)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input(urgency=Urgency.URGENT))

        assert result.ceiling_applied == 300.0
        assert result.recommended_price == 300.0

    def test_ceiling_per_mile_open(self):
        """$2.00/mile ceiling for open trailers."""
        # suggested=200, low=800, high=800, distance=100
        # base=500, URGENT=625
        # Ceiling = min(200×1.50=300, 100×$2.00=$200) = $200
        quote = _make_quote(suggested=200.0, low=800.0, high=800.0)
        engine = _make_engine(quote)
        result = engine.calculate(
            _default_input(urgency=Urgency.URGENT, distance_miles=100.0, is_enclosed=False)
        )

        assert result.ceiling_applied == 200.0
        assert result.recommended_price == 200.0

    def test_ceiling_per_mile_enclosed(self):
        """$3.00/mile ceiling for enclosed trailers."""
        # Same as above but enclosed → 100×$3.00=$300
        # Ceiling = min(200×1.50=300, $300) = $300
        quote = _make_quote(suggested=200.0, low=800.0, high=800.0)
        engine = _make_engine(quote)
        result = engine.calculate(
            _default_input(urgency=Urgency.URGENT, distance_miles=100.0, is_enclosed=True)
        )

        assert result.ceiling_applied == 300.0

    def test_no_ceiling_when_price_below(self):
        """No ceiling applied when price is within range."""
        quote = _make_quote(suggested=500.0, low=None, high=None)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        assert result.ceiling_applied is None


# =============================================================================
# WARNING TESTS
# =============================================================================


class TestWarnings:
    """Test low/high price warnings."""

    def test_warning_low(self):
        """Warning when price < avg×0.90."""
        # suggested=500, low=100, high=100 → spread=-400, base=300
        # STANDARD → 300
        # Floor = max($150, 500×0.85=$425) = $425 → price raised to $425
        # $425 < 500×0.90=$450 → LOW warning
        quote = _make_quote(suggested=500.0, low=100.0, high=100.0)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

        assert any("below 90%" in w for w in result.warnings)

    def test_warning_high(self):
        """Warning when price > avg×1.30."""
        # suggested=400, URGENT → need price above 400×1.30=520
        # with no spread, base=400, URGENT=400×1.25=500 < 520 → no warning
        # need spread to push higher: suggested=400, low=600, high=600 → spread=200
        # base=400+100=500, URGENT=500×1.25=625
        # ceiling = 400×1.50=600, so capped to 600
        # 600 > 400×1.30=520 → HIGH warning
        quote = _make_quote(suggested=400.0, low=600.0, high=600.0)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input(urgency=Urgency.URGENT))

        assert any("above 130%" in w for w in result.warnings)

    def test_no_warning_in_normal_range(self):
        """No warnings when price is within normal range."""
        quote = _make_quote(suggested=500.0, low=None, high=None)
        engine = _make_engine(quote)
        result = engine.calculate(_default_input())

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
        assert result.recommended_price is None
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

    def test_service_exception_returns_manual_required(self):
        """When PricingService raises, source=MANUAL_REQUIRED."""
        mock_service = MagicMock()
        mock_service.get_recommended_price.side_effect = Exception("Connection timeout")
        engine = PricingEngine(pricing_service=mock_service)
        result = engine.calculate(_default_input())

        assert result.source == PriceSource.MANUAL_REQUIRED

    def test_missing_pickup_returns_manual_required(self):
        """When pickup city/state missing, source=MANUAL_REQUIRED."""
        engine = _make_engine(_make_quote())
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
        quote = _make_quote(suggested=500.0, low=None, high=None)
        engine = _make_engine(quote)
        inp = _default_input()

        result1 = engine.calculate(inp)
        result2 = engine.calculate(inp)

        assert result1.recommended_price == result2.recommended_price
        assert result2.cached is True
        # Service should only be called once
        assert engine._pricing_service.get_recommended_price.call_count == 1

    def test_different_routes_not_cached(self):
        """Different routes should not share cache."""
        engine = _make_engine(_make_quote())

        inp1 = _default_input(pickup_city="MANHEIM", delivery_city="AYER")
        inp2 = _default_input(pickup_city="TAMPA", delivery_city="BOSTON")

        engine.calculate(inp1)
        engine.calculate(inp2)

        assert engine._pricing_service.get_recommended_price.call_count == 2

    def test_cache_expires(self):
        """Cache entries expire after TTL."""
        engine = PricingEngine(
            pricing_service=MagicMock(
                get_recommended_price=MagicMock(
                    return_value=_make_quote(suggested=500.0, low=None, high=None)
                )
            ),
            cache_ttl=1,  # 1 second TTL for test
        )

        inp = _default_input()
        engine.calculate(inp)

        # Wait for cache to expire
        time.sleep(1.1)

        result = engine.calculate(inp)
        assert result.cached is False
        assert engine._pricing_service.get_recommended_price.call_count == 2

    def test_clear_cache(self):
        """clear_cache() should empty all entries."""
        engine = _make_engine(_make_quote())
        engine.calculate(_default_input())
        assert engine.cache_size() == 1

        cleared = engine.clear_cache()
        assert cleared == 1
        assert engine.cache_size() == 0

    def test_cached_result_with_different_urgency(self):
        """Cached result should re-apply new urgency modifier."""
        engine = _make_engine(_make_quote(suggested=500.0, low=None, high=None))

        # First call with STANDARD
        result1 = engine.calculate(_default_input(urgency=Urgency.STANDARD))
        assert result1.recommended_price == 500.0

        # Second call with URGENT — should use cache but apply ×1.25
        result2 = engine.calculate(_default_input(urgency=Urgency.URGENT))
        assert result2.cached is True
        assert result2.recommended_price == 625.0  # 500 × 1.25


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
            distance_miles=350.0,
        ))

        assert result.source == PriceSource.MARKET_INTELLIGENCE
        assert result.recommended_price is not None
        assert result.recommended_price > 0
        assert result.urgency == Urgency.PRIORITY

    def test_result_dataclass_fields(self):
        """PricingResult should have all expected fields."""
        result = PricingResult()
        assert hasattr(result, "recommended_price")
        assert hasattr(result, "base_price")
        assert hasattr(result, "avg_dispatch_price")
        assert hasattr(result, "spread")
        assert hasattr(result, "urgency")
        assert hasattr(result, "urgency_multiplier")
        assert hasattr(result, "floor_applied")
        assert hasattr(result, "ceiling_applied")
        assert hasattr(result, "source")
        assert hasattr(result, "warnings")
        assert hasattr(result, "is_enclosed")
        assert hasattr(result, "distance_miles")
        assert hasattr(result, "cached")

    def test_singleton_factory(self):
        """get_pricing_engine() returns singleton."""
        from services.pricing_engine import get_pricing_engine

        engine1 = get_pricing_engine()
        engine2 = get_pricing_engine()
        assert engine1 is engine2
