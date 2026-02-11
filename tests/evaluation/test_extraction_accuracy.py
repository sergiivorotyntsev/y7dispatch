"""
Extraction Accuracy Test Harness (Phase 0.2)

Tests extraction quality against golden dataset.
Runs as part of CI to prevent regression.

Usage:
    pytest tests/evaluation/test_extraction_accuracy.py -v
    pytest tests/evaluation/test_extraction_accuracy.py --auction-type copart
    pytest tests/evaluation/test_extraction_accuracy.py --min-score 80

Configuration:
    Set EXTRACTION_MIN_SCORE env var to override minimum passing score (default: 75)
"""

import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.evaluation.metrics import (
    ExtractionMetrics,
    calculate_metrics,
    compare_values,
)

logger = logging.getLogger(__name__)

# Configuration
GOLDEN_DATASET_PATH = Path(__file__).parent / "golden_dataset"
MIN_EXTRACTION_SCORE = float(os.getenv("EXTRACTION_MIN_SCORE", "75"))
MIN_FIELD_F1 = float(os.getenv("EXTRACTION_MIN_FIELD_F1", "0.80"))

# Required fields that must meet minimum thresholds
CRITICAL_FIELDS = [
    "vehicle_vin",
    "vehicle_year",
    "vehicle_make",
    "vehicle_model",
    "pickup_city",
    "pickup_state",
]


@dataclass
class GoldenDocument:
    """A golden dataset document with expected values."""

    path: Path
    auction_type: str
    category: str  # standard, edge_cases, missing_fields, multi_vehicle
    expected_fields: dict[str, Any]
    metadata: dict[str, Any]


def load_golden_dataset(
    auction_type: Optional[str] = None,
    category: Optional[str] = None,
) -> list[GoldenDocument]:
    """
    Load golden dataset documents.

    Args:
        auction_type: Filter by auction (copart, iaa, manheim)
        category: Filter by category (standard, edge_cases, etc.)

    Returns:
        List of GoldenDocument objects
    """
    documents = []

    auction_dirs = (
        [GOLDEN_DATASET_PATH / auction_type]
        if auction_type
        else list(GOLDEN_DATASET_PATH.iterdir())
    )

    for auction_dir in auction_dirs:
        if not auction_dir.is_dir():
            continue

        auction = auction_dir.name.upper()

        category_dirs = (
            [auction_dir / category]
            if category
            else list(auction_dir.iterdir())
        )

        for cat_dir in category_dirs:
            if not cat_dir.is_dir():
                continue

            cat = cat_dir.name

            # Find PDF files with corresponding JSON
            for pdf_path in cat_dir.glob("*.pdf"):
                json_path = pdf_path.with_suffix(".json")

                if not json_path.exists():
                    logger.warning(f"No expected JSON for {pdf_path}")
                    continue

                with open(json_path) as f:
                    data = json.load(f)

                doc = GoldenDocument(
                    path=pdf_path,
                    auction_type=auction,
                    category=cat,
                    expected_fields=data.get("expected_fields", {}),
                    metadata=data.get("metadata", {}),
                )
                documents.append(doc)

    return documents


def run_extraction(pdf_path: Path) -> dict[str, Any]:
    """
    Run extraction on a PDF file.

    Returns extracted fields dict.
    """
    import pdfplumber

    from extractors import ExtractorManager

    # Extract text
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as e:
        logger.error(f"Failed to read PDF {pdf_path}: {e}")
        return {}

    # Get extractor
    manager = ExtractorManager()
    extractor = manager.get_extractor_for_text(text)

    if not extractor:
        logger.warning(f"No extractor matched for {pdf_path}")
        return {}

    # Run extraction
    try:
        result = extractor.extract_with_result(str(pdf_path), text)
    except Exception as e:
        logger.error(f"Extraction failed for {pdf_path}: {e}")
        return {}

    if not result or not result.invoice:
        return {}

    # Build fields dict
    inv = result.invoice
    fields = {
        "auction_source": result.source.value if result.source else None,
        "reference_id": inv.reference_id,
        "buyer_id": inv.buyer_id,
        "buyer_name": inv.buyer_name,
        "sale_date": str(inv.sale_date) if inv.sale_date else None,
        "total_amount": inv.total_amount,
        "vehicle_lot": inv.vehicle_lot,
    }

    if inv.pickup_address:
        addr = inv.pickup_address
        fields.update({
            "pickup_name": addr.name,
            "pickup_address": addr.street,
            "pickup_city": addr.city,
            "pickup_state": addr.state,
            "pickup_zip": addr.postal_code,
            "pickup_phone": addr.phone,
        })

    if inv.vehicles:
        v = inv.vehicles[0]
        fields.update({
            "vehicle_vin": v.vin,
            "vehicle_year": v.year,
            "vehicle_make": v.make,
            "vehicle_model": v.model,
            "vehicle_color": v.color,
            "vehicle_type": v.vehicle_type.value if v.vehicle_type else None,
        })

    return fields


def evaluate_golden_dataset(
    auction_type: Optional[str] = None,
    category: Optional[str] = None,
) -> ExtractionMetrics:
    """
    Evaluate extraction on golden dataset.

    Returns aggregate metrics.
    """
    documents = load_golden_dataset(auction_type, category)

    if not documents:
        logger.warning("No golden dataset documents found")
        return ExtractionMetrics()

    evaluation_data = []

    for doc in documents:
        extracted = run_extraction(doc.path)

        evaluation_data.append({
            "expected": doc.expected_fields,
            "extracted": extracted,
            "auction_type": doc.auction_type,
            "extraction_success": bool(extracted),
            "category": doc.category,
            "file": str(doc.path.name),
        })

    return calculate_metrics(evaluation_data)


# =============================================================================
# Pytest Tests
# =============================================================================


class TestExtractionAccuracy:
    """Tests for extraction accuracy against golden dataset."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Check if golden dataset exists."""
        if not GOLDEN_DATASET_PATH.exists():
            pytest.skip("Golden dataset not found")

        # Check for at least some documents
        pdf_count = len(list(GOLDEN_DATASET_PATH.glob("**/*.pdf")))
        if pdf_count == 0:
            pytest.skip("No golden dataset PDFs found")

    def test_overall_extraction_score(self):
        """Test that overall extraction score meets minimum threshold."""
        metrics = evaluate_golden_dataset()

        assert metrics.extraction_score >= MIN_EXTRACTION_SCORE, (
            f"Extraction score {metrics.extraction_score:.2f} "
            f"below minimum {MIN_EXTRACTION_SCORE}"
        )

    def test_critical_field_f1(self):
        """Test that critical fields meet F1 score threshold."""
        metrics = evaluate_golden_dataset()

        for field_key in CRITICAL_FIELDS:
            if field_key not in metrics.field_metrics:
                continue

            field_f1 = metrics.field_metrics[field_key].f1_score

            assert field_f1 >= MIN_FIELD_F1, (
                f"Field '{field_key}' F1 score {field_f1:.4f} "
                f"below minimum {MIN_FIELD_F1}"
            )

    @pytest.mark.parametrize("auction_type", ["copart", "iaa", "manheim"])
    def test_auction_type_extraction(self, auction_type: str):
        """Test extraction accuracy by auction type."""
        auction_dir = GOLDEN_DATASET_PATH / auction_type
        if not auction_dir.exists():
            pytest.skip(f"No golden data for {auction_type}")

        metrics = evaluate_golden_dataset(auction_type=auction_type)

        # Each auction type should meet 70% of overall threshold
        min_score = MIN_EXTRACTION_SCORE * 0.7

        assert metrics.extraction_score >= min_score, (
            f"{auction_type.upper()} extraction score {metrics.extraction_score:.2f} "
            f"below minimum {min_score:.2f}"
        )

    def test_vin_extraction_accuracy(self):
        """Test VIN extraction with high accuracy requirement."""
        metrics = evaluate_golden_dataset()

        if "vehicle_vin" not in metrics.field_metrics:
            pytest.skip("No VIN data in golden set")

        vin_metrics = metrics.field_metrics["vehicle_vin"]

        # VIN must be highly accurate (99%+)
        assert vin_metrics.precision >= 0.99, (
            f"VIN precision {vin_metrics.precision:.4f} below 0.99"
        )

    def test_no_regression_from_baseline(self):
        """Test that metrics don't regress from established baseline."""
        baseline_file = GOLDEN_DATASET_PATH / "baseline_metrics.json"

        if not baseline_file.exists():
            pytest.skip("No baseline metrics file")

        with open(baseline_file) as f:
            baseline = json.load(f)

        current = evaluate_golden_dataset()

        # Allow 5% regression tolerance
        tolerance = 0.05
        baseline_score = baseline.get("summary", {}).get("extraction_score", 0)
        min_acceptable = baseline_score * (1 - tolerance)

        assert current.extraction_score >= min_acceptable, (
            f"Extraction score {current.extraction_score:.2f} regressed "
            f"from baseline {baseline_score:.2f} (min: {min_acceptable:.2f})"
        )


# =============================================================================
# CLI Runner
# =============================================================================


def main():
    """Run evaluation and print report."""
    import argparse

    parser = argparse.ArgumentParser(description="Extraction Accuracy Evaluation")
    parser.add_argument("--auction-type", choices=["copart", "iaa", "manheim"])
    parser.add_argument("--category")
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--output", help="Save metrics to JSON file")

    args = parser.parse_args()

    print("=" * 60)
    print("EXTRACTION ACCURACY EVALUATION")
    print("=" * 60)

    metrics = evaluate_golden_dataset(args.auction_type, args.category)

    # Print summary
    print(f"\nTotal documents: {metrics.total_documents}")
    print(f"Successful extractions: {metrics.successful_extractions}")
    print(f"Failed extractions: {metrics.failed_extractions}")
    print(f"\n{'=' * 40}")
    print(f"EXTRACTION SCORE: {metrics.extraction_score:.2f}/100")
    print(f"{'=' * 40}")
    print(f"\nMacro Precision: {metrics.macro_precision:.4f}")
    print(f"Macro Recall: {metrics.macro_recall:.4f}")
    print(f"Macro F1: {metrics.macro_f1:.4f}")
    print(f"Weighted F1: {metrics.weighted_f1:.4f}")

    # Per-field metrics
    print("\nPER-FIELD METRICS:")
    print("-" * 60)
    for field_key, fm in sorted(metrics.field_metrics.items()):
        status = "✓" if fm.f1_score >= 0.8 else "⚠" if fm.f1_score >= 0.6 else "✗"
        print(
            f"  {status} {field_key:25s} "
            f"P={fm.precision:.3f} R={fm.recall:.3f} F1={fm.f1_score:.3f}"
        )

    # By auction type
    if metrics.by_auction_type:
        print("\nBY AUCTION TYPE:")
        print("-" * 40)
        for auction, data in metrics.by_auction_type.items():
            print(
                f"  {auction}: {data['count']} docs, "
                f"score={data['extraction_score']:.1f}, F1={data['macro_f1']:.3f}"
            )

    # Save baseline
    if args.save_baseline:
        baseline_path = GOLDEN_DATASET_PATH / "baseline_metrics.json"
        with open(baseline_path, "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)
        print(f"\nBaseline saved to: {baseline_path}")

    # Save output
    if args.output:
        with open(args.output, "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)
        print(f"\nMetrics saved to: {args.output}")

    print("\n" + "=" * 60)

    # Exit with error if below threshold
    if metrics.extraction_score < MIN_EXTRACTION_SCORE:
        print(f"FAIL: Score {metrics.extraction_score:.2f} < {MIN_EXTRACTION_SCORE}")
        sys.exit(1)
    else:
        print(f"PASS: Score {metrics.extraction_score:.2f} >= {MIN_EXTRACTION_SCORE}")
        sys.exit(0)


if __name__ == "__main__":
    main()
