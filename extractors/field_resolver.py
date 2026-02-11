"""
Field Value Resolution with Full Precedence

Combines values from multiple sources according to precedence rules:

1. USER_OVERRIDE - Manual user correction (highest priority)
2. WAREHOUSE_CONST - Warehouse-specific constants
3. AUCTION_CONST - Auction profile defaults
4. EXTRACTED - From document extraction
5. DEFAULT - Default values from field mappings (lowest priority)

This module provides a unified interface for resolving field values
and tracking where each value came from.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# P0.3: CANONICAL KEYS AND ALIASES
# Single Source of Truth for field key normalization
# =============================================================================

# Canonical key -> list of aliases (bidirectional)
KEY_ALIASES = {
    # Pickup address fields
    "pickup_postal_code": ["pickup_zip"],
    "pickup_location_name": ["pickup_name"],
    "pickup_contact_name": ["pickup_contact"],
    # Delivery/Dropoff address fields (normalize to delivery_*)
    "delivery_postal_code": ["delivery_zip", "dropoff_postal_code", "dropoff_zip"],
    "delivery_location_name": ["delivery_name", "dropoff_location_name", "dropoff_name"],
    "delivery_contact_name": ["delivery_contact", "dropoff_contact_name", "dropoff_contact"],
    "delivery_address": ["dropoff_address"],
    "delivery_city": ["dropoff_city"],
    "delivery_state": ["dropoff_state"],
    "delivery_phone": ["dropoff_phone"],
    # Vehicle fields
    "vehicle_is_inoperable": ["vehicle_condition", "is_inoperable"],
    # Lot/Stock number unification (F2 fix)
    # Copart uses lot_number, IAA/Manheim use stock_number
    # Canonical key is vehicle_lot for CD API compatibility
    "vehicle_lot": ["lot_number", "stock_number"],
}

# Build reverse lookup: alias -> canonical
ALIAS_TO_CANONICAL = {}
for canonical, aliases in KEY_ALIASES.items():
    for alias in aliases:
        ALIAS_TO_CANONICAL[alias] = canonical
    # Canonical key also maps to itself
    ALIAS_TO_CANONICAL[canonical] = canonical


def normalize_field_key(key: str) -> str:
    """
    Normalize a field key to its canonical form.

    Args:
        key: Field key to normalize (e.g., "pickup_zip", "dropoff_city")

    Returns:
        Canonical key (e.g., "pickup_postal_code", "delivery_city")
    """
    return ALIAS_TO_CANONICAL.get(key, key)


def get_all_key_variants(key: str) -> list[str]:
    """
    Get all variants of a field key (canonical + aliases).

    Useful for looking up values that might be stored under different keys.
    """
    canonical = normalize_field_key(key)
    variants = [canonical]
    if canonical in KEY_ALIASES:
        variants.extend(KEY_ALIASES[canonical])
    return variants


class FieldValueSource(str, Enum):
    """Source of field value (in precedence order, high to low)."""

    USER_OVERRIDE = "user_override"  # Manual user correction
    WAREHOUSE_CONST = "warehouse_const"  # Warehouse-specific constant
    AUCTION_CONST = "auction_const"  # Auction profile constant
    EXTRACTED = "extracted"  # Extracted from document
    DEFAULT = "default"  # Default value from mapping
    EMPTY = "empty"  # No value found


# Precedence order (index 0 = highest)
PRECEDENCE_ORDER = [
    FieldValueSource.USER_OVERRIDE,
    FieldValueSource.WAREHOUSE_CONST,
    FieldValueSource.AUCTION_CONST,
    FieldValueSource.EXTRACTED,
    FieldValueSource.DEFAULT,
]


@dataclass
class ResolvedField:
    """A resolved field value with source tracking."""

    field_key: str
    value: Any
    source: FieldValueSource
    confidence: float = 1.0

    # Alternative values from lower-priority sources
    alternatives: dict[str, Any] = field(default_factory=dict)

    # Metadata
    extracted_value: Optional[Any] = None  # Original extracted value
    rule_id: Optional[str] = None  # Rule that extracted the value
    block_id: Optional[str] = None  # Layout block ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_key": self.field_key,
            "value": self.value,
            "source": self.source.value,
            "confidence": self.confidence,
            "alternatives": self.alternatives,
            "extracted_value": self.extracted_value,
        }


@dataclass
class ResolutionContext:
    """Context for field resolution."""

    auction_code: Optional[str] = None
    warehouse_code: Optional[str] = None
    user_overrides: dict[str, Any] = field(default_factory=dict)
    default_values: dict[str, Any] = field(default_factory=dict)


class FieldResolver:
    """
    Resolves field values using multiple sources with precedence.

    Example usage:
        resolver = FieldResolver()
        context = ResolutionContext(
            auction_code="COPART",
            warehouse_code="DEN-01",
            user_overrides={"pickup_phone": "555-1234"},
        )
        resolved = resolver.resolve_all(extracted_fields, context)
    """

    def __init__(self):
        # Lazy import to avoid circular dependencies
        self._auction_service = None
        self._warehouse_service = None

    @property
    def auction_service(self):
        if self._auction_service is None:
            from api.auction_profiles import get_profile_service

            self._auction_service = get_profile_service()
        return self._auction_service

    @property
    def warehouse_service(self):
        if self._warehouse_service is None:
            from api.warehouse_constants import get_constants_service

            self._warehouse_service = get_constants_service()
        return self._warehouse_service

    def resolve_field(
        self,
        field_key: str,
        extracted_value: Any,
        context: ResolutionContext,
    ) -> ResolvedField:
        """
        Resolve a single field value using all available sources.

        Args:
            field_key: Field being resolved
            extracted_value: Value extracted from document
            context: Resolution context with auction/warehouse info

        Returns:
            ResolvedField with final value and source
        """
        candidates = []  # List of (source, value, confidence)

        # 1. Check user overrides (highest priority)
        if field_key in context.user_overrides:
            override = context.user_overrides[field_key]
            if override is not None:
                candidates.append((FieldValueSource.USER_OVERRIDE, override, 1.0))

        # 2. Check warehouse constants
        if context.warehouse_code:
            wc = self.warehouse_service.get_constants(context.warehouse_code)
            if wc and wc.should_apply(field_key, extracted_value):
                value = wc.get_value(field_key)
                if value is not None:
                    candidates.append((FieldValueSource.WAREHOUSE_CONST, value, 0.95))

        # 3. Check auction profile
        if context.auction_code:
            profile = self.auction_service.get_profile(context.auction_code)
            if profile and profile.should_apply_default(field_key, extracted_value):
                value = profile.get_default_value(field_key)
                if value is not None:
                    candidates.append((FieldValueSource.AUCTION_CONST, value, 0.9))

        # 4. Use extracted value
        if extracted_value is not None and str(extracted_value).strip():
            candidates.append((FieldValueSource.EXTRACTED, extracted_value, 0.85))

        # 5. Check default values
        if field_key in context.default_values:
            default = context.default_values[field_key]
            if default is not None:
                candidates.append((FieldValueSource.DEFAULT, default, 0.5))

        # Select highest-priority value
        if not candidates:
            return ResolvedField(
                field_key=field_key,
                value=None,
                source=FieldValueSource.EMPTY,
                confidence=0.0,
                extracted_value=extracted_value,
            )

        # Sort by precedence order
        candidates.sort(key=lambda c: PRECEDENCE_ORDER.index(c[0]))

        # Use highest-priority candidate
        best_source, best_value, best_confidence = candidates[0]

        # Build alternatives from remaining candidates
        alternatives = {}
        for source, value, _conf in candidates[1:]:
            alternatives[source.value] = value

        return ResolvedField(
            field_key=field_key,
            value=best_value,
            source=best_source,
            confidence=best_confidence,
            alternatives=alternatives,
            extracted_value=extracted_value,
        )

    def resolve_all(
        self,
        extracted_fields: dict[str, Any],
        context: ResolutionContext,
        additional_fields: list[str] = None,
    ) -> dict[str, ResolvedField]:
        """
        Resolve all fields using multiple sources.

        Args:
            extracted_fields: Fields extracted from document
            context: Resolution context
            additional_fields: Extra field keys to resolve (even if not extracted)

        Returns:
            Dict of field_key -> ResolvedField
        """
        # P0.3: Normalize extracted fields to canonical keys
        normalized_extracted = {}
        for key, value in extracted_fields.items():
            canonical_key = normalize_field_key(key)
            # If we already have a value for canonical key, prefer non-empty
            existing = normalized_extracted.get(canonical_key)
            if existing is None or (not str(existing).strip() and value and str(value).strip()):
                normalized_extracted[canonical_key] = value

        # Collect all field keys to resolve (using canonical keys)
        field_keys = set(normalized_extracted.keys())

        # Normalize user_overrides keys
        normalized_overrides = {
            normalize_field_key(k): v for k, v in context.user_overrides.items()
        }
        field_keys.update(normalized_overrides.keys())

        # Normalize default_values keys
        normalized_defaults = {normalize_field_key(k): v for k, v in context.default_values.items()}
        field_keys.update(normalized_defaults.keys())

        if additional_fields:
            field_keys.update(normalize_field_key(k) for k in additional_fields)

        # Add fields from auction profile
        if context.auction_code:
            profile = self.auction_service.get_profile(context.auction_code)
            if profile:
                field_keys.update(normalize_field_key(k) for k in profile.field_defaults.keys())

        # Add fields from warehouse constants
        if context.warehouse_code:
            wc = self.warehouse_service.get_constants(context.warehouse_code)
            if wc:
                field_keys.update(normalize_field_key(k) for k in wc.constants.keys())

        # Create normalized context
        normalized_context = ResolutionContext(
            auction_code=context.auction_code,
            warehouse_code=context.warehouse_code,
            user_overrides=normalized_overrides,
            default_values=normalized_defaults,
        )

        # Resolve each field
        results = {}
        for field_key in sorted(field_keys):
            extracted = normalized_extracted.get(field_key)
            results[field_key] = self.resolve_field(field_key, extracted, normalized_context)

        return results

    def get_final_values(
        self,
        extracted_fields: dict[str, Any],
        context: ResolutionContext,
    ) -> dict[str, Any]:
        """
        Get final values only (without source tracking).

        Convenience method when you just need the resolved values.
        """
        resolved = self.resolve_all(extracted_fields, context)
        return {k: v.value for k, v in resolved.items() if v.value is not None}

    def get_sources_summary(
        self, resolved_fields: dict[str, ResolvedField]
    ) -> dict[str, dict[str, Any]]:
        """
        Get a summary of field sources for diagnostics.
        """
        summary = {}
        for field_key, resolved in resolved_fields.items():
            summary[field_key] = {
                "value": resolved.value,
                "source": resolved.source.value,
                "confidence": resolved.confidence,
                "has_alternatives": len(resolved.alternatives) > 0,
            }
        return summary


def resolve_with_precedence(
    extracted_fields: dict[str, Any],
    auction_code: str = None,
    warehouse_code: str = None,
    user_overrides: dict[str, Any] = None,
    default_values: dict[str, Any] = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Convenience function to resolve fields with precedence.

    Args:
        extracted_fields: Fields extracted from document
        auction_code: Auction type code (e.g., "COPART")
        warehouse_code: Warehouse code (e.g., "DEN-01")
        user_overrides: User corrections
        default_values: Default field values

    Returns:
        Tuple of (final_values dict, source_map dict)
    """
    resolver = FieldResolver()
    context = ResolutionContext(
        auction_code=auction_code,
        warehouse_code=warehouse_code,
        user_overrides=user_overrides or {},
        default_values=default_values or {},
    )

    resolved = resolver.resolve_all(extracted_fields, context)

    final_values = {}
    source_map = {}

    for field_key, field_resolved in resolved.items():
        if field_resolved.value is not None:
            final_values[field_key] = field_resolved.value
            source_map[field_key] = field_resolved.source.value

    return final_values, source_map


# Singleton instance
_field_resolver = None


def get_field_resolver() -> FieldResolver:
    """Get or create the field resolver singleton."""
    global _field_resolver
    if _field_resolver is None:
        _field_resolver = FieldResolver()
    return _field_resolver
