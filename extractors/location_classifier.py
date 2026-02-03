"""
Location Classifier Module (M3.P0.6)

Provides pickup/delivery disambiguation for extracted addresses.
Uses keyword heuristics, spatial zones, and auction profile hints
to determine whether an address is pickup or delivery.

Key rules:
- Warehouse delivery is NEVER extracted from document
- Delivery address comes from warehouse constants only
- Pickup address is extracted from auction documents
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LocationType(Enum):
    """Type of location in the transport order."""

    PICKUP = "pickup"
    DELIVERY = "delivery"
    UNKNOWN = "unknown"


class LocationConfidence(Enum):
    """Confidence level in location classification."""

    HIGH = "high"  # Clear keyword match or profile rule
    MEDIUM = "medium"  # Partial match or spatial inference
    LOW = "low"  # Best guess


@dataclass
class ClassifiedLocation:
    """A classified location with type and confidence."""

    location_type: LocationType
    confidence: LocationConfidence
    address_text: str
    matched_keywords: list[str] = None
    matched_rule: Optional[str] = None
    source: str = "keyword"  # keyword, spatial, profile, default

    def __post_init__(self):
        if self.matched_keywords is None:
            self.matched_keywords = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.location_type.value,
            "confidence": self.confidence.value,
            "address_text": self.address_text[:200] if self.address_text else None,
            "matched_keywords": self.matched_keywords,
            "matched_rule": self.matched_rule,
            "source": self.source,
        }


class LocationClassifier:
    """
    Classifies locations as pickup or delivery.

    Uses multiple strategies:
    1. Keyword matching (highest priority)
    2. Spatial position in document
    3. Auction profile hints
    4. Default rules
    """

    # Pickup keywords (strong indicators)
    PICKUP_KEYWORDS_STRONG = [
        r"\bPICK[-\s]?UP\b",
        r"\bRELEASE\b",
        r"\bLOT\s*LOCATION\b",
        r"\bBUYER\s*PICKUP\b",
        r"\bVEHICLE\s*LOCATION\b",
        r"\bSELLER\b",
        r"\bAUCTION\s*(LOCATION|FACILITY|YARD)\b",
        r"\bPHYSICAL\s*ADDRESS\s*(?:OF\s*)?LOT\b",
    ]

    # Pickup keywords (weak indicators)
    PICKUP_KEYWORDS_WEAK = [
        r"\bFROM\b",
        r"\bORIGIN\b",
        r"\bSTART\b",
        r"\bCOPART\b",
        r"\bIAA\b",
        r"\bMANHEIM\b",
        r"\bADESA\b",
    ]

    # Delivery keywords (should NOT be in pickup address)
    DELIVERY_KEYWORDS = [
        r"\bDELIVER(?:Y|ED|S)?\b",
        r"\bDROP[-\s]?OFF\b",
        r"\bDESTINATION\b",
        r"\bSHIP\s*TO\b",
        r"\bBUYER\s*ADDRESS\b",
        r"\bTO\s*LOCATION\b",
    ]

    # Warehouse indicators (should be delivery ONLY)
    WAREHOUSE_KEYWORDS = [
        r"\bWAREHOUSE\b",
        r"\bDISTRIBUTION\b",
        r"\bSTORAGE\b",
        r"\bTERMINAL\b",
        r"\bYARD\b(?!\s*(?:LOCATION|ADDRESS))",  # Not "yard location"
    ]

    # Auction profiles with pickup zone hints
    AUCTION_PROFILES = {
        "COPART": {
            "pickup_labels": ["PHYSICAL ADDRESS OF LOT", "SELLER", "LOT LOCATION"],
            "pickup_zone": "top_left",
            "never_delivery_from_doc": True,
        },
        "IAA": {
            "pickup_labels": ["PICKUP LOCATION", "BRANCH", "FACILITY"],
            "pickup_zone": "top",
            "never_delivery_from_doc": True,
        },
        "MANHEIM": {
            "pickup_labels": ["SELLER LOCATION", "AUCTION"],
            "pickup_zone": "left",
            "never_delivery_from_doc": True,
        },
    }

    def __init__(self):
        # Compile patterns for efficiency
        self._pickup_strong = [re.compile(p, re.IGNORECASE) for p in self.PICKUP_KEYWORDS_STRONG]
        self._pickup_weak = [re.compile(p, re.IGNORECASE) for p in self.PICKUP_KEYWORDS_WEAK]
        self._delivery = [re.compile(p, re.IGNORECASE) for p in self.DELIVERY_KEYWORDS]
        self._warehouse = [re.compile(p, re.IGNORECASE) for p in self.WAREHOUSE_KEYWORDS]

    def classify(
        self,
        address_text: str,
        context_text: str = None,
        auction_code: str = None,
        position_hint: str = None,
    ) -> ClassifiedLocation:
        """
        Classify a location as pickup or delivery.

        Args:
            address_text: The address text to classify
            context_text: Surrounding text for context (label, section, etc.)
            auction_code: Auction type code (COPART, IAA, MANHEIM)
            position_hint: Position in document (top, bottom, left, right)

        Returns:
            ClassifiedLocation with type and confidence
        """
        if not address_text:
            return ClassifiedLocation(
                location_type=LocationType.UNKNOWN,
                confidence=LocationConfidence.LOW,
                address_text="",
            )

        # Combine address and context for keyword matching
        full_text = f"{context_text or ''} {address_text}"

        # Check for delivery keywords first (should disqualify as pickup)
        delivery_matches = self._match_patterns(full_text, self._delivery)
        if delivery_matches:
            return ClassifiedLocation(
                location_type=LocationType.DELIVERY,
                confidence=LocationConfidence.HIGH,
                address_text=address_text,
                matched_keywords=delivery_matches,
                source="keyword",
            )

        # Check for warehouse keywords (delivery only)
        warehouse_matches = self._match_patterns(address_text, self._warehouse)
        if warehouse_matches:
            return ClassifiedLocation(
                location_type=LocationType.DELIVERY,
                confidence=LocationConfidence.HIGH,
                address_text=address_text,
                matched_keywords=warehouse_matches,
                matched_rule="warehouse_keyword",
                source="keyword",
            )

        # Check for strong pickup keywords
        pickup_strong = self._match_patterns(full_text, self._pickup_strong)
        if pickup_strong:
            return ClassifiedLocation(
                location_type=LocationType.PICKUP,
                confidence=LocationConfidence.HIGH,
                address_text=address_text,
                matched_keywords=pickup_strong,
                source="keyword",
            )

        # Check for weak pickup keywords
        pickup_weak = self._match_patterns(full_text, self._pickup_weak)
        if pickup_weak:
            return ClassifiedLocation(
                location_type=LocationType.PICKUP,
                confidence=LocationConfidence.MEDIUM,
                address_text=address_text,
                matched_keywords=pickup_weak,
                source="keyword",
            )

        # Check auction profile
        if auction_code and auction_code.upper() in self.AUCTION_PROFILES:
            profile = self.AUCTION_PROFILES[auction_code.upper()]

            # Check profile labels
            for label in profile.get("pickup_labels", []):
                if label.upper() in (context_text or "").upper():
                    return ClassifiedLocation(
                        location_type=LocationType.PICKUP,
                        confidence=LocationConfidence.HIGH,
                        address_text=address_text,
                        matched_rule=f"profile:{auction_code}:{label}",
                        source="profile",
                    )

            # Check spatial position
            if position_hint and profile.get("pickup_zone"):
                if position_hint.lower() in profile["pickup_zone"]:
                    return ClassifiedLocation(
                        location_type=LocationType.PICKUP,
                        confidence=LocationConfidence.MEDIUM,
                        address_text=address_text,
                        matched_rule=f"zone:{position_hint}",
                        source="spatial",
                    )

        # Default: assume pickup for auction documents
        # (delivery comes from warehouse constants)
        return ClassifiedLocation(
            location_type=LocationType.PICKUP,
            confidence=LocationConfidence.LOW,
            address_text=address_text,
            matched_rule="default_pickup",
            source="default",
        )

    def _match_patterns(self, text: str, patterns: list[re.Pattern]) -> list[str]:
        """Find all matching patterns in text."""
        matches = []
        for pattern in patterns:
            if pattern.search(text):
                matches.append(pattern.pattern)
        return matches

    def is_definitely_pickup(
        self,
        address_text: str,
        context_text: str = None,
        auction_code: str = None,
    ) -> tuple[bool, str]:
        """
        Check if an address is definitely a pickup location.

        Args:
            address_text: Address text
            context_text: Context text (label, section)
            auction_code: Auction code

        Returns:
            Tuple of (is_pickup, reason)
        """
        result = self.classify(address_text, context_text, auction_code)

        if result.location_type == LocationType.PICKUP:
            if result.confidence == LocationConfidence.HIGH:
                return True, f"High confidence: {result.matched_keywords or result.matched_rule}"
            elif result.confidence == LocationConfidence.MEDIUM:
                return True, f"Medium confidence: {result.matched_keywords or result.matched_rule}"
            else:
                return True, "Low confidence (default)"

        return False, f"Classified as {result.location_type.value}"

    def is_likely_delivery(
        self,
        address_text: str,
        context_text: str = None,
    ) -> tuple[bool, str]:
        """
        Check if an address is likely a delivery location.

        IMPORTANT: Delivery addresses should come from warehouse constants,
        not from document extraction.

        Args:
            address_text: Address text
            context_text: Context text

        Returns:
            Tuple of (is_delivery, reason)
        """
        result = self.classify(address_text, context_text)

        if result.location_type == LocationType.DELIVERY:
            return True, f"Delivery keywords: {result.matched_keywords}"

        return False, "No delivery indicators"

    def should_extract_from_document(
        self,
        location_type: LocationType,
        auction_code: str = None,
    ) -> tuple[bool, str]:
        """
        Check if a location type should be extracted from document.

        Key rule: DELIVERY is NEVER extracted from document
        (comes from warehouse constants only)

        Args:
            location_type: Type of location
            auction_code: Auction code

        Returns:
            Tuple of (should_extract, reason)
        """
        if location_type == LocationType.DELIVERY:
            return False, "Delivery address comes from warehouse constants only"

        if location_type == LocationType.PICKUP:
            return True, "Pickup address is extracted from document"

        return False, "Unknown location type"


def classify_location(
    address_text: str,
    context_text: str = None,
    auction_code: str = None,
) -> ClassifiedLocation:
    """
    Convenience function to classify a location.

    Args:
        address_text: Address to classify
        context_text: Context (label, surrounding text)
        auction_code: Auction code

    Returns:
        ClassifiedLocation
    """
    classifier = LocationClassifier()
    return classifier.classify(address_text, context_text, auction_code)


def is_pickup_address(
    address_text: str,
    context_text: str = None,
    auction_code: str = None,
) -> bool:
    """
    Quick check if address is a pickup location.

    Args:
        address_text: Address text
        context_text: Context text
        auction_code: Auction code

    Returns:
        True if likely pickup
    """
    classifier = LocationClassifier()
    result = classifier.classify(address_text, context_text, auction_code)
    return result.location_type == LocationType.PICKUP


def is_delivery_address(
    address_text: str,
    context_text: str = None,
) -> bool:
    """
    Quick check if address is a delivery location.

    WARNING: Delivery addresses should NOT be extracted from documents.
    Use warehouse constants instead.

    Args:
        address_text: Address text
        context_text: Context text

    Returns:
        True if likely delivery (should be discarded from extraction)
    """
    classifier = LocationClassifier()
    result = classifier.classify(address_text, context_text)
    return result.location_type == LocationType.DELIVERY


# Singleton instance
_location_classifier = None


def get_location_classifier() -> LocationClassifier:
    """Get or create the location classifier singleton."""
    global _location_classifier
    if _location_classifier is None:
        _location_classifier = LocationClassifier()
    return _location_classifier
