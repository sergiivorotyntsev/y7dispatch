"""
Regression Test Runner (M3.P1.9)

Runs extraction tests on golden dataset and reports accuracy metrics.

Usage:
    python -m tests.regression_runner --dataset golden_copart
    python -m tests.regression_runner --file tests/golden/doc_001.pdf --expected tests/golden/doc_001.json

Features:
- Run extraction on individual PDFs or entire datasets
- Compare results to ground truth JSON
- Calculate per-field accuracy metrics
- Generate regression reports
"""

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class FieldResult:
    """Result for a single field comparison."""

    field_key: str
    expected: Any
    extracted: Any
    is_match: bool
    match_type: str = "exact"  # exact, fuzzy, partial
    confidence: float = 0.0
    error: Optional[str] = None


@dataclass
class DocumentResult:
    """Result for a single document test."""

    document_path: str
    document_name: str
    auction_type: Optional[str] = None
    total_fields: int = 0
    matched_fields: int = 0
    accuracy: float = 0.0
    field_results: list[FieldResult] = field(default_factory=list)
    extraction_time_ms: int = 0
    error: Optional[str] = None


@dataclass
class RegressionReport:
    """Aggregate regression test report."""

    run_id: str
    run_at: str
    dataset_name: str = ""
    total_documents: int = 0
    successful_extractions: int = 0
    failed_extractions: int = 0
    overall_accuracy: float = 0.0
    field_accuracy: dict[str, float] = field(default_factory=dict)
    document_results: list[DocumentResult] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_at": self.run_at,
            "dataset_name": self.dataset_name,
            "summary": {
                "total_documents": self.total_documents,
                "successful_extractions": self.successful_extractions,
                "failed_extractions": self.failed_extractions,
                "overall_accuracy": round(self.overall_accuracy, 2),
            },
            "field_accuracy": {k: round(v, 2) for k, v in self.field_accuracy.items()},
            "duration_ms": self.duration_ms,
            "documents": [
                {
                    "name": d.document_name,
                    "auction_type": d.auction_type,
                    "accuracy": round(d.accuracy, 2),
                    "matched": d.matched_fields,
                    "total": d.total_fields,
                    "error": d.error,
                }
                for d in self.document_results
            ],
        }


class RegressionRunner:
    """
    Runs regression tests on PDF documents.

    Compares extraction results against ground truth JSON files.
    """

    # Fields to compare
    REQUIRED_FIELDS = [
        "vehicle_vin",
        "pickup_city",
        "pickup_state",
        "pickup_address",
    ]

    OPTIONAL_FIELDS = [
        "vehicle_year",
        "vehicle_make",
        "vehicle_model",
        "vehicle_lot",
        "buyer_id",
        "buyer_name",
        "reference_id",
        "sale_date",
        "total_amount",
        "pickup_zip",
        "pickup_name",
    ]

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def run_single(
        self,
        pdf_path: str,
        expected_json_path: str,
    ) -> DocumentResult:
        """
        Run extraction on a single document and compare to expected results.

        Args:
            pdf_path: Path to PDF file
            expected_json_path: Path to expected results JSON

        Returns:
            DocumentResult with comparison results
        """
        result = DocumentResult(
            document_path=pdf_path,
            document_name=Path(pdf_path).name,
        )

        # Load expected results
        try:
            with open(expected_json_path) as f:
                expected = json.load(f)
        except Exception as e:
            result.error = f"Failed to load expected JSON: {e}"
            return result

        result.auction_type = expected.get("auction_type")

        # Run extraction
        import time

        start_time = time.time()

        try:
            extracted = self._run_extraction(pdf_path)
        except Exception as e:
            result.error = f"Extraction failed: {e}"
            result.extraction_time_ms = int((time.time() - start_time) * 1000)
            return result

        result.extraction_time_ms = int((time.time() - start_time) * 1000)

        # Compare fields
        all_fields = self.REQUIRED_FIELDS + self.OPTIONAL_FIELDS
        expected_fields = expected.get("fields", {})

        for field_key in all_fields:
            expected_value = expected_fields.get(field_key)
            extracted_value = extracted.get(field_key)

            # Only compare fields that have expected values
            if expected_value is None:
                continue

            result.total_fields += 1

            is_match, match_type = self._compare_values(field_key, expected_value, extracted_value)

            field_result = FieldResult(
                field_key=field_key,
                expected=expected_value,
                extracted=extracted_value,
                is_match=is_match,
                match_type=match_type,
            )
            result.field_results.append(field_result)

            if is_match:
                result.matched_fields += 1

        # Calculate accuracy
        if result.total_fields > 0:
            result.accuracy = result.matched_fields / result.total_fields * 100

        return result

    def run_dataset(
        self,
        dataset_path: str,
        pattern: str = "*.pdf",
    ) -> RegressionReport:
        """
        Run regression tests on a dataset directory.

        Expects:
        - PDF files matching pattern
        - JSON files with same name (e.g., doc_001.pdf -> doc_001.json)

        Args:
            dataset_path: Path to dataset directory
            pattern: Glob pattern for PDF files

        Returns:
            RegressionReport with aggregate results
        """
        import time
        from uuid import uuid4

        start_time = time.time()

        report = RegressionReport(
            run_id=str(uuid4())[:8],
            run_at=datetime.utcnow().isoformat(),
            dataset_name=Path(dataset_path).name,
        )

        # Find PDF files
        dataset_dir = Path(dataset_path)
        pdf_files = list(dataset_dir.glob(pattern))

        if not pdf_files:
            logger.warning(f"No PDF files found in {dataset_path} matching {pattern}")
            return report

        report.total_documents = len(pdf_files)

        # Process each document
        field_matches = dict.fromkeys(self.REQUIRED_FIELDS + self.OPTIONAL_FIELDS, 0)
        field_totals = dict.fromkeys(self.REQUIRED_FIELDS + self.OPTIONAL_FIELDS, 0)

        for pdf_path in pdf_files:
            # Look for expected JSON
            json_path = pdf_path.with_suffix(".json")
            if not json_path.exists():
                logger.warning(f"No expected JSON for {pdf_path.name}")
                report.failed_extractions += 1
                continue

            if self.verbose:
                logger.info(f"Testing: {pdf_path.name}")

            result = self.run_single(str(pdf_path), str(json_path))
            report.document_results.append(result)

            if result.error:
                report.failed_extractions += 1
            else:
                report.successful_extractions += 1

                # Aggregate field accuracy
                for fr in result.field_results:
                    field_totals[fr.field_key] += 1
                    if fr.is_match:
                        field_matches[fr.field_key] += 1

        # Calculate field accuracy
        for field_key in field_matches:
            total = field_totals[field_key]
            if total > 0:
                report.field_accuracy[field_key] = field_matches[field_key] / total * 100

        # Calculate overall accuracy
        total_matched = sum(r.matched_fields for r in report.document_results)
        total_fields = sum(r.total_fields for r in report.document_results)
        if total_fields > 0:
            report.overall_accuracy = total_matched / total_fields * 100

        report.duration_ms = int((time.time() - start_time) * 1000)

        return report

    def _run_extraction(self, pdf_path: str) -> dict[str, Any]:
        """
        Run extraction on a PDF file.

        Uses the block extractor with fallback to pattern extraction.
        """
        from extractors.block_extractor import BlockExtractor
        from extractors.spatial_parser import parse_document

        # Parse document
        structure = parse_document(pdf_path)

        # Extract fields
        extractor = BlockExtractor()
        results = extractor.extract_all_fields(structure, use_fallback=True)

        # Build output dict
        extracted = {}
        for field_key, result in results.items():
            if result.success and result.value:
                extracted[field_key] = result.value

        return extracted

    def _compare_values(
        self,
        field_key: str,
        expected: Any,
        extracted: Any,
    ) -> tuple[bool, str]:
        """
        Compare expected and extracted values.

        Supports:
        - Exact match
        - Case-insensitive match
        - VIN validation (17 chars)
        - Fuzzy string matching for addresses

        Returns:
            Tuple of (is_match, match_type)
        """
        if expected is None:
            return extracted is None, "exact"

        if extracted is None:
            return False, "missing"

        # Convert to strings for comparison
        expected_str = str(expected).strip()
        extracted_str = str(extracted).strip()

        # Exact match
        if expected_str == extracted_str:
            return True, "exact"

        # Case-insensitive match
        if expected_str.lower() == extracted_str.lower():
            return True, "case_insensitive"

        # Field-specific comparisons
        if field_key == "vehicle_vin":
            # VIN: must be exact match
            return expected_str.upper() == extracted_str.upper(), "vin"

        if field_key in ("pickup_state", "delivery_state"):
            # State: case-insensitive, 2 letters
            return expected_str.upper() == extracted_str.upper(), "state"

        if field_key in ("pickup_zip", "delivery_zip"):
            # ZIP: compare digits only
            exp_digits = "".join(c for c in expected_str if c.isdigit())
            ext_digits = "".join(c for c in extracted_str if c.isdigit())
            return exp_digits[:5] == ext_digits[:5], "zip"

        if field_key in ("total_amount",):
            # Amount: compare numeric value
            try:
                exp_num = float(expected_str.replace("$", "").replace(",", ""))
                ext_num = float(extracted_str.replace("$", "").replace(",", ""))
                return abs(exp_num - ext_num) < 0.01, "amount"
            except ValueError:
                return False, "amount_error"

        if "address" in field_key or "city" in field_key:
            # Address: fuzzy match
            return self._fuzzy_match(expected_str, extracted_str), "fuzzy"

        return False, "no_match"

    def _fuzzy_match(self, expected: str, extracted: str, threshold: float = 0.8) -> bool:
        """
        Fuzzy string matching for addresses.

        Uses simple token-based comparison.
        """
        # Normalize
        exp_tokens = set(expected.lower().split())
        ext_tokens = set(extracted.lower().split())

        # Remove common noise
        noise = {"the", "a", "an", "of", "in", "at", "to"}
        exp_tokens -= noise
        ext_tokens -= noise

        if not exp_tokens:
            return not ext_tokens

        # Calculate overlap
        overlap = len(exp_tokens & ext_tokens)
        score = overlap / len(exp_tokens)

        return score >= threshold


def print_report(report: RegressionReport, detailed: bool = False):
    """Print regression report to console."""
    print("\n" + "=" * 60)
    print("REGRESSION TEST REPORT")
    print("=" * 60)
    print(f"Run ID: {report.run_id}")
    print(f"Dataset: {report.dataset_name}")
    print(f"Run at: {report.run_at}")
    print(f"Duration: {report.duration_ms}ms")
    print()
    print("SUMMARY")
    print("-" * 40)
    print(f"Total documents: {report.total_documents}")
    print(f"Successful: {report.successful_extractions}")
    print(f"Failed: {report.failed_extractions}")
    print(f"Overall accuracy: {report.overall_accuracy:.1f}%")
    print()

    print("FIELD ACCURACY")
    print("-" * 40)
    for field_key, accuracy in sorted(report.field_accuracy.items()):
        indicator = "✓" if accuracy >= 90 else "⚠" if accuracy >= 70 else "✗"
        print(f"  {indicator} {field_key}: {accuracy:.1f}%")
    print()

    if detailed:
        print("DOCUMENT DETAILS")
        print("-" * 40)
        for doc in report.document_results:
            status = "✓" if not doc.error and doc.accuracy >= 80 else "⚠" if not doc.error else "✗"
            print(
                f"  {status} {doc.document_name}: {doc.accuracy:.1f}% ({doc.matched_fields}/{doc.total_fields})"
            )
            if doc.error:
                print(f"      Error: {doc.error}")

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Regression Test Runner")
    parser.add_argument("--dataset", help="Path to dataset directory")
    parser.add_argument("--file", help="Single PDF file to test")
    parser.add_argument("--expected", help="Expected results JSON (for single file)")
    parser.add_argument("--output", help="Output JSON file for report")
    parser.add_argument("--detailed", action="store_true", help="Show detailed results")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    runner = RegressionRunner(verbose=args.verbose)

    if args.file:
        if not args.expected:
            print("Error: --expected required when using --file")
            sys.exit(1)

        result = runner.run_single(args.file, args.expected)
        print(f"\nDocument: {result.document_name}")
        print(f"Accuracy: {result.accuracy:.1f}% ({result.matched_fields}/{result.total_fields})")
        if result.error:
            print(f"Error: {result.error}")

        for fr in result.field_results:
            status = "✓" if fr.is_match else "✗"
            print(f"  {status} {fr.field_key}: expected={fr.expected}, got={fr.extracted}")

    elif args.dataset:
        report = runner.run_dataset(args.dataset)
        print_report(report, detailed=args.detailed)

        if args.output:
            with open(args.output, "w") as f:
                json.dump(report.to_dict(), f, indent=2)
            print(f"\nReport saved to: {args.output}")

    else:
        print("Error: Either --dataset or --file required")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
