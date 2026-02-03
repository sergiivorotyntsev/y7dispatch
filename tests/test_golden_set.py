#!/usr/bin/env python3
"""
Golden Set Regression Tests for Extraction Pipeline

Tests extraction quality against known expected outputs.
Ensures extraction doesn't regress when changes are made.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def normalize_phone(phone: str) -> str:
    """Normalize phone to digits only for comparison."""
    if not phone:
        return ""
    return re.sub(r"\D", "", str(phone))


def normalize_zip(zip_code: str) -> str:
    """Normalize ZIP to 5-digit format for comparison."""
    if not zip_code:
        return ""
    return str(zip_code)[:5]


def normalize_state(state: str) -> str:
    """Normalize state to uppercase 2-letter format."""
    if not state:
        return ""
    return str(state).upper()[:2]


def normalize_date(date_val) -> str:
    """Normalize date to YYYY-MM-DD for comparison."""
    if not date_val:
        return ""
    date_str = str(date_val)
    # Extract date portion
    if "T" in date_str or " " in date_str:
        date_str = date_str.split("T")[0].split(" ")[0]
    return date_str


def normalize_amount(amount) -> float:
    """Normalize amount to float for comparison."""
    if not amount:
        return 0.0
    try:
        return float(str(amount).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def compare_field(key: str, extracted: Any, expected: Any) -> tuple[bool, str]:
    """
    Compare a single field with appropriate normalization.
    Returns (match, reason).
    """
    if expected is None:
        # Expected is null - extraction can be anything
        return True, "Expected null, skip comparison"

    if extracted is None:
        return False, f"Expected '{expected}', got null"

    # Apply normalization based on field type
    if "phone" in key.lower():
        ext_norm = normalize_phone(str(extracted))
        exp_norm = normalize_phone(str(expected))
        match = ext_norm == exp_norm
        return match, f"Normalized phone: '{ext_norm}' vs '{exp_norm}'"

    if "zip" in key.lower():
        ext_norm = normalize_zip(str(extracted))
        exp_norm = normalize_zip(str(expected))
        match = ext_norm == exp_norm
        return match, f"Normalized zip: '{ext_norm}' vs '{exp_norm}'"

    if "state" in key.lower():
        ext_norm = normalize_state(str(extracted))
        exp_norm = normalize_state(str(expected))
        match = ext_norm == exp_norm
        return match, f"Normalized state: '{ext_norm}' vs '{exp_norm}'"

    if "date" in key.lower():
        ext_norm = normalize_date(extracted)
        exp_norm = normalize_date(expected)
        match = ext_norm == exp_norm
        return match, f"Normalized date: '{ext_norm}' vs '{exp_norm}'"

    if "amount" in key.lower():
        ext_norm = normalize_amount(extracted)
        exp_norm = normalize_amount(expected)
        match = abs(ext_norm - exp_norm) < 0.01
        return match, f"Normalized amount: {ext_norm} vs {exp_norm}"

    # String comparison (case-insensitive for most fields)
    ext_str = str(extracted).strip().upper()
    exp_str = str(expected).strip().upper()
    match = ext_str == exp_str

    return match, f"'{extracted}' vs '{expected}'"


def run_extraction(pdf_path: str) -> dict:
    """Run extraction on a PDF and return the extracted fields."""
    import pdfplumber

    from extractors import ExtractorManager

    # Extract text
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    # Get extractor and run
    manager = ExtractorManager()
    extractor = manager.get_extractor_for_text(text)

    if not extractor:
        return {}

    result = extractor.extract_with_result(pdf_path, text)

    if not result.invoice:
        return {}

    # Build extracted fields dict
    inv = result.invoice
    fields = {
        "auction_source": result.source.value if result.source else None,
        "reference_id": inv.reference_id,
        "buyer_id": inv.buyer_id,
        "buyer_name": inv.buyer_name,
        "sale_date": str(inv.sale_date) if inv.sale_date else None,
        "total_amount": str(inv.total_amount) if inv.total_amount else None,
    }

    if inv.pickup_address:
        addr = inv.pickup_address
        fields.update(
            {
                "pickup_name": addr.name,
                "pickup_address": addr.street,
                "pickup_city": addr.city,
                "pickup_state": addr.state,
                "pickup_zip": addr.postal_code,
            }
        )

    if inv.vehicles:
        v = inv.vehicles[0]
        fields.update(
            {
                "vehicle_vin": v.vin,
                "vehicle_year": v.year,
                "vehicle_make": v.make,
                "vehicle_model": v.model,
                "vehicle_color": v.color,
                "vehicle_lot": v.lot_number,
            }
        )

    return fields


def run_golden_test(expected_file: Path, sample_docs_dir: Path) -> dict:
    """
    Run a single golden test.
    Returns test result dict.
    """
    with open(expected_file) as f:
        expected = json.load(f)

    source_file = expected["source_file"]
    pdf_path = sample_docs_dir / source_file

    if not pdf_path.exists():
        return {
            "status": "error",
            "file": source_file,
            "error": f"PDF not found: {pdf_path}",
        }

    # Run extraction
    extracted = run_extraction(str(pdf_path))

    if not extracted:
        return {
            "status": "fail",
            "file": source_file,
            "error": "Extraction returned no results",
        }

    # Compare fields
    expected_fields = expected["expected_fields"]
    passed = []
    failed = []

    for key, exp_value in expected_fields.items():
        ext_value = extracted.get(key)
        match, reason = compare_field(key, ext_value, exp_value)

        if match:
            passed.append(key)
        else:
            failed.append(
                {
                    "field": key,
                    "expected": exp_value,
                    "extracted": ext_value,
                    "reason": reason,
                }
            )

    # Check minimum fields
    filled_count = sum(1 for v in extracted.values() if v is not None and v != "")
    min_required = expected.get("validation", {}).get("min_fields_required", 12)

    # Check VIN length
    vin = extracted.get("vehicle_vin", "")
    vin_valid = len(vin) == 17 if vin else False

    # Check state format
    state = extracted.get("pickup_state", "")
    state_valid = len(state) == 2 if state else False

    status = "pass" if len(failed) == 0 else "fail"

    return {
        "status": status,
        "file": source_file,
        "auction_type": expected["auction_type"],
        "passed_count": len(passed),
        "failed_count": len(failed),
        "total_fields": len(expected_fields),
        "filled_count": filled_count,
        "min_required": min_required,
        "fields_pass_minimum": filled_count >= min_required,
        "vin_valid": vin_valid,
        "state_valid": state_valid,
        "passed_fields": passed,
        "failed_fields": failed,
    }


def run_all_golden_tests() -> dict:
    """
    Run all golden tests.
    Returns summary with detailed results.
    """
    golden_dir = Path(__file__).parent / "golden_set" / "expected"
    sample_docs_dir = Path(__file__).parent / "sample_docs"

    results = []
    total_pass = 0
    total_fail = 0

    expected_files = sorted(golden_dir.glob("*_expected.json"))

    print(f"Running {len(expected_files)} golden tests...")
    print("-" * 60)

    for expected_file in expected_files:
        result = run_golden_test(expected_file, sample_docs_dir)
        results.append(result)

        if result["status"] == "pass":
            total_pass += 1
            status_icon = "OK"
        else:
            total_fail += 1
            status_icon = "FAIL"

        print(f"[{status_icon}] {result['file']}")
        print(f"     Auction: {result.get('auction_type', 'unknown')}")
        print(
            f"     Fields: {result.get('passed_count', 0)}/{result.get('total_fields', 0)} passed"
        )

        if result.get("failed_fields"):
            for fail in result["failed_fields"][:3]:
                print(f"     - {fail['field']}: {fail['reason']}")
            if len(result.get("failed_fields", [])) > 3:
                print(f"     ... and {len(result['failed_fields']) - 3} more failures")
        print()

    print("=" * 60)
    print(f"GOLDEN TEST SUMMARY: {total_pass}/{len(results)} passed")
    print(f"  Pass: {total_pass}")
    print(f"  Fail: {total_fail}")
    print("=" * 60)

    return {
        "total": len(results),
        "passed": total_pass,
        "failed": total_fail,
        "pass_rate": total_pass / len(results) if results else 0,
        "results": results,
    }


if __name__ == "__main__":
    # Suppress extraction warnings
    import logging
    import sys

    logging.getLogger("extractors").setLevel(logging.ERROR)

    summary = run_all_golden_tests()

    # Exit with error if any tests failed
    if summary["failed"] > 0:
        print(f"\n{summary['failed']} test(s) FAILED")
        sys.exit(1)
    else:
        print(f"\nAll {summary['passed']} tests PASSED")
        sys.exit(0)
