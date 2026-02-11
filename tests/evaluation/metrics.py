"""
Extraction Metrics Calculator (Phase 0.2)

Provides precision, recall, F1 score calculations for extraction evaluation.
Used for baseline measurement and regression testing.

Metrics:
- Precision: Of extracted values, how many are correct?
- Recall: Of expected values, how many did we extract?
- F1 Score: Harmonic mean of precision and recall
- Extraction Score: Weighted aggregate of field-level metrics
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class FieldCategory(str, Enum):
    """Field categories for weighted scoring."""

    CD_REQUIRED = "cd_required"  # Central Dispatch required fields
    CD_RECOMMENDED = "cd_recommended"  # CD recommended fields
    CD_OPTIONAL = "cd_optional"  # CD optional fields
    INTERNAL = "internal"  # Internal tracking fields


# Field weights for extraction score calculation
FIELD_WEIGHTS = {
    # CD Required (weight: 3.0) - blocking for export
    "vehicle_vin": 3.0,
    "vehicle_year": 3.0,
    "vehicle_make": 3.0,
    "vehicle_model": 3.0,
    "pickup_city": 3.0,
    "pickup_state": 3.0,
    # CD Recommended (weight: 2.0) - important but not blocking
    "pickup_zip": 2.0,
    "pickup_address": 2.0,
    "vehicle_lot": 2.0,
    "vehicle_type": 2.0,
    # CD Optional (weight: 1.0)
    "pickup_phone": 1.0,
    "pickup_name": 1.0,
    "buyer_id": 1.0,
    "buyer_name": 1.0,
    "sale_date": 1.0,
    "total_amount": 1.0,
    "vehicle_color": 1.0,
    "seller_name": 1.0,
}


@dataclass
class FieldMetrics:
    """Metrics for a single field across all documents."""

    field_key: str
    true_positives: int = 0  # Correctly extracted
    false_positives: int = 0  # Extracted but wrong
    false_negatives: int = 0  # Expected but not extracted
    true_negatives: int = 0  # Correctly not extracted (when no value expected)

    @property
    def precision(self) -> float:
        """Precision: TP / (TP + FP)"""
        total = self.true_positives + self.false_positives
        return self.true_positives / total if total > 0 else 0.0

    @property
    def recall(self) -> float:
        """Recall: TP / (TP + FN)"""
        total = self.true_positives + self.false_negatives
        return self.true_positives / total if total > 0 else 0.0

    @property
    def f1_score(self) -> float:
        """F1 Score: 2 * (precision * recall) / (precision + recall)"""
        p, r = self.precision, self.recall
        return 2 * (p * r) / (p + r) if (p + r) > 0 else 0.0

    @property
    def accuracy(self) -> float:
        """Accuracy: (TP + TN) / (TP + TN + FP + FN)"""
        total = (
            self.true_positives
            + self.true_negatives
            + self.false_positives
            + self.false_negatives
        )
        return (self.true_positives + self.true_negatives) / total if total > 0 else 0.0

    @property
    def weight(self) -> float:
        """Field weight for weighted scoring."""
        return FIELD_WEIGHTS.get(self.field_key, 1.0)

    def to_dict(self) -> dict:
        return {
            "field_key": self.field_key,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "accuracy": round(self.accuracy, 4),
            "tp": self.true_positives,
            "fp": self.false_positives,
            "fn": self.false_negatives,
            "tn": self.true_negatives,
            "weight": self.weight,
        }


@dataclass
class ExtractionMetrics:
    """Aggregate metrics for extraction evaluation."""

    # Per-field metrics
    field_metrics: dict[str, FieldMetrics] = field(default_factory=dict)

    # Aggregate counts
    total_documents: int = 0
    successful_extractions: int = 0
    failed_extractions: int = 0

    # By auction type
    by_auction_type: dict[str, dict] = field(default_factory=dict)

    @property
    def macro_precision(self) -> float:
        """Macro-averaged precision across all fields."""
        if not self.field_metrics:
            return 0.0
        return sum(m.precision for m in self.field_metrics.values()) / len(
            self.field_metrics
        )

    @property
    def macro_recall(self) -> float:
        """Macro-averaged recall across all fields."""
        if not self.field_metrics:
            return 0.0
        return sum(m.recall for m in self.field_metrics.values()) / len(
            self.field_metrics
        )

    @property
    def macro_f1(self) -> float:
        """Macro-averaged F1 score across all fields."""
        if not self.field_metrics:
            return 0.0
        return sum(m.f1_score for m in self.field_metrics.values()) / len(
            self.field_metrics
        )

    @property
    def weighted_f1(self) -> float:
        """Weighted F1 score (by field importance)."""
        if not self.field_metrics:
            return 0.0
        total_weight = sum(m.weight for m in self.field_metrics.values())
        if total_weight == 0:
            return 0.0
        weighted_sum = sum(
            m.f1_score * m.weight for m in self.field_metrics.values()
        )
        return weighted_sum / total_weight

    @property
    def extraction_score(self) -> float:
        """
        Overall extraction quality score (0-100).

        Combines:
        - Weighted F1 score (70%)
        - Success rate (20%)
        - Required fields coverage (10%)
        """
        # Component 1: Weighted F1 (70%)
        weighted_f1_component = self.weighted_f1 * 0.7

        # Component 2: Success rate (20%)
        success_rate = (
            self.successful_extractions / self.total_documents
            if self.total_documents > 0
            else 0.0
        )
        success_component = success_rate * 0.2

        # Component 3: Required fields coverage (10%)
        required_fields = [
            "vehicle_vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "pickup_city",
            "pickup_state",
        ]
        required_coverage = 0.0
        for field_key in required_fields:
            if field_key in self.field_metrics:
                required_coverage += self.field_metrics[field_key].recall
        required_coverage = required_coverage / len(required_fields)
        required_component = required_coverage * 0.1

        return (weighted_f1_component + success_component + required_component) * 100

    def to_dict(self) -> dict:
        return {
            "summary": {
                "total_documents": self.total_documents,
                "successful_extractions": self.successful_extractions,
                "failed_extractions": self.failed_extractions,
                "extraction_score": round(self.extraction_score, 2),
                "macro_precision": round(self.macro_precision, 4),
                "macro_recall": round(self.macro_recall, 4),
                "macro_f1": round(self.macro_f1, 4),
                "weighted_f1": round(self.weighted_f1, 4),
            },
            "by_field": {
                k: v.to_dict() for k, v in sorted(self.field_metrics.items())
            },
            "by_auction_type": self.by_auction_type,
        }


def normalize_value(value: Any, field_key: str) -> Optional[str]:
    """
    Normalize a value for comparison.

    Returns None if value is empty/null.
    """
    if value is None:
        return None

    value_str = str(value).strip()
    if not value_str or value_str.lower() in ("none", "null", "n/a", ""):
        return None

    # Field-specific normalization
    if "vin" in field_key.lower():
        # VIN: uppercase, remove spaces
        return value_str.upper().replace(" ", "").replace("-", "")

    if "state" in field_key.lower():
        # State: uppercase, first 2 chars
        return value_str.upper()[:2]

    if "zip" in field_key.lower() or "postal" in field_key.lower():
        # ZIP: digits only, first 5
        digits = re.sub(r"\D", "", value_str)
        return digits[:5] if digits else None

    if "phone" in field_key.lower():
        # Phone: digits only
        digits = re.sub(r"\D", "", value_str)
        return digits if len(digits) >= 10 else None

    if "date" in field_key.lower():
        # Date: extract YYYY-MM-DD
        value_str = value_str.split("T")[0].split(" ")[0]
        return value_str

    if "amount" in field_key.lower() or "price" in field_key.lower():
        # Amount: extract numeric value
        cleaned = re.sub(r"[^\d.]", "", value_str)
        try:
            return str(round(float(cleaned), 2))
        except ValueError:
            return None

    if "year" in field_key.lower():
        # Year: extract 4-digit year
        match = re.search(r"\b(19|20)\d{2}\b", value_str)
        return match.group(0) if match else None

    # Default: lowercase for comparison
    return value_str.lower()


def compare_values(
    expected: Any, extracted: Any, field_key: str
) -> tuple[bool, str]:
    """
    Compare expected and extracted values.

    Returns:
        Tuple of (is_match, match_type)
    """
    exp_norm = normalize_value(expected, field_key)
    ext_norm = normalize_value(extracted, field_key)

    # Both null/empty
    if exp_norm is None and ext_norm is None:
        return True, "both_empty"

    # One is null
    if exp_norm is None:
        return False, "unexpected_extraction"
    if ext_norm is None:
        return False, "missing_extraction"

    # Exact match
    if exp_norm == ext_norm:
        return True, "exact"

    # Fuzzy match for addresses and cities
    if "address" in field_key or "city" in field_key or "name" in field_key:
        if fuzzy_match(exp_norm, ext_norm):
            return True, "fuzzy"

    # Partial match for model names
    if "model" in field_key.lower():
        if partial_match(exp_norm, ext_norm):
            return True, "partial"

    return False, "mismatch"


def fuzzy_match(expected: str, extracted: str, threshold: float = 0.8) -> bool:
    """
    Fuzzy string matching based on token overlap.
    """
    exp_tokens = set(expected.lower().split())
    ext_tokens = set(extracted.lower().split())

    # Remove noise words
    noise = {"the", "a", "an", "of", "in", "at", "to", "inc", "llc", "corp"}
    exp_tokens -= noise
    ext_tokens -= noise

    if not exp_tokens:
        return not ext_tokens

    overlap = len(exp_tokens & ext_tokens)
    return overlap / len(exp_tokens) >= threshold


def partial_match(expected: str, extracted: str) -> bool:
    """
    Check if one string contains the other (for model names).
    """
    exp_lower = expected.lower().replace("-", " ").replace("_", " ")
    ext_lower = extracted.lower().replace("-", " ").replace("_", " ")

    return exp_lower in ext_lower or ext_lower in exp_lower


def calculate_field_metrics(
    documents: list[dict],
    field_key: str,
) -> FieldMetrics:
    """
    Calculate metrics for a single field across all documents.

    Args:
        documents: List of {"expected": {...}, "extracted": {...}} dicts
        field_key: Field to evaluate

    Returns:
        FieldMetrics for the field
    """
    metrics = FieldMetrics(field_key=field_key)

    for doc in documents:
        expected = doc.get("expected", {}).get(field_key)
        extracted = doc.get("extracted", {}).get(field_key)

        exp_norm = normalize_value(expected, field_key)
        ext_norm = normalize_value(extracted, field_key)

        has_expected = exp_norm is not None
        has_extracted = ext_norm is not None

        if has_expected and has_extracted:
            is_match, _ = compare_values(expected, extracted, field_key)
            if is_match:
                metrics.true_positives += 1
            else:
                metrics.false_positives += 1
        elif has_expected and not has_extracted:
            metrics.false_negatives += 1
        elif not has_expected and has_extracted:
            metrics.false_positives += 1
        else:
            metrics.true_negatives += 1

    return metrics


def calculate_metrics(
    documents: list[dict],
    fields: Optional[list[str]] = None,
) -> ExtractionMetrics:
    """
    Calculate aggregate extraction metrics.

    Args:
        documents: List of {
            "expected": {...},
            "extracted": {...},
            "auction_type": "COPART|IAA|MANHEIM",
            "extraction_success": bool
        }
        fields: Optional list of fields to evaluate (default: all from FIELD_WEIGHTS)

    Returns:
        ExtractionMetrics with per-field and aggregate metrics
    """
    if fields is None:
        fields = list(FIELD_WEIGHTS.keys())

    metrics = ExtractionMetrics()
    metrics.total_documents = len(documents)

    # Count successes/failures
    for doc in documents:
        if doc.get("extraction_success", True):
            metrics.successful_extractions += 1
        else:
            metrics.failed_extractions += 1

    # Calculate per-field metrics
    for field_key in fields:
        field_metrics = calculate_field_metrics(documents, field_key)
        metrics.field_metrics[field_key] = field_metrics

    # Calculate by auction type
    auction_docs = {}
    for doc in documents:
        auction_type = doc.get("auction_type", "UNKNOWN")
        if auction_type not in auction_docs:
            auction_docs[auction_type] = []
        auction_docs[auction_type].append(doc)

    for auction_type, docs in auction_docs.items():
        auction_metrics = calculate_metrics(docs, fields)
        metrics.by_auction_type[auction_type] = {
            "count": len(docs),
            "extraction_score": round(auction_metrics.extraction_score, 2),
            "macro_f1": round(auction_metrics.macro_f1, 4),
        }

    return metrics
