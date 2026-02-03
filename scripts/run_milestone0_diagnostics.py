#!/usr/bin/env python3
"""
Milestone 0.1 Diagnostic Script

Runs extraction on sample documents and collects detailed debug information
to identify why fields may be empty or incorrect.

Saves results to diagnostics/samples/ for analysis.
"""

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extractors import ExtractorManager


@dataclass
class DiagnosticResult:
    """Result of diagnostic analysis for a single document."""

    filename: str
    file_path: str
    file_size_bytes: int

    # Text extraction
    text_extraction_success: bool
    raw_text_length: int
    words_count: int
    pages_count: int
    text_mode: str  # "native", "ocr", "hybrid", "failed"
    text_preview: str

    # Classification
    classification_success: bool
    detected_source: Optional[str]
    classification_score: float
    all_scores: list[dict]
    matched_patterns: list[str]

    # Extraction
    extraction_success: bool
    extraction_score: float
    fields_total: int
    fields_filled: int
    fields_empty: int

    # Key fields status
    has_vehicle_vin: bool
    has_vehicle_ymm: bool  # year, make, model
    has_pickup_address: bool
    has_pickup_city_state: bool
    has_reference_id: bool

    # Extracted values (key fields)
    extracted_fields: dict

    # Field sources
    field_sources: dict

    # Issues detected
    issues: list[str]
    recommendations: list[str]

    # Pipeline invariants
    invariant_text_extracted: bool
    invariant_classified: bool
    invariant_anchor_fields: bool  # at least 3 anchor fields

    # Timing
    extraction_time_ms: int


def run_diagnostic(pdf_path: str) -> DiagnosticResult:
    """Run full diagnostic on a single PDF document."""
    import time

    import pdfplumber

    start_time = time.time()
    filename = os.path.basename(pdf_path)
    file_size = os.path.getsize(pdf_path)

    # Initialize result
    result = DiagnosticResult(
        filename=filename,
        file_path=pdf_path,
        file_size_bytes=file_size,
        text_extraction_success=False,
        raw_text_length=0,
        words_count=0,
        pages_count=0,
        text_mode="failed",
        text_preview="",
        classification_success=False,
        detected_source=None,
        classification_score=0.0,
        all_scores=[],
        matched_patterns=[],
        extraction_success=False,
        extraction_score=0.0,
        fields_total=0,
        fields_filled=0,
        fields_empty=0,
        has_vehicle_vin=False,
        has_vehicle_ymm=False,
        has_pickup_address=False,
        has_pickup_city_state=False,
        has_reference_id=False,
        extracted_fields={},
        field_sources={},
        issues=[],
        recommendations=[],
        invariant_text_extracted=False,
        invariant_classified=False,
        invariant_anchor_fields=False,
        extraction_time_ms=0,
    )

    # Step 1: Extract text from PDF
    raw_text = ""
    pages_count = 0

    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages_count = len(pdf.pages)
            result.pages_count = pages_count

            text_parts = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

            raw_text = "\n".join(text_parts)

        if raw_text:
            result.text_extraction_success = True
            result.raw_text_length = len(raw_text)
            result.words_count = len(raw_text.split())
            result.text_mode = "native"
            result.text_preview = raw_text[:500]
            result.invariant_text_extracted = True
        else:
            result.issues.append("No text extracted from PDF - may need OCR")
            result.recommendations.append("Apply OCR to extract text from scanned document")
            result.text_mode = "failed"

    except Exception as e:
        result.issues.append(f"PDF text extraction failed: {str(e)}")
        result.recommendations.append("Check if PDF is corrupted or password-protected")

    # Check text length threshold
    if result.raw_text_length < 100:
        result.issues.append(
            f"Very short text ({result.raw_text_length} chars) - likely OCR needed"
        )
        result.recommendations.append("Document appears to be a scan without text layer")

    # Step 2: Classification
    if raw_text:
        manager = ExtractorManager()

        # Get scores from all extractors
        for extractor in manager.extractors:
            try:
                score, patterns = extractor.score(raw_text)
                result.all_scores.append(
                    {
                        "source": extractor.source.value,
                        "score": score,
                        "patterns": patterns[:5] if patterns else [],
                    }
                )
            except Exception as e:
                result.all_scores.append(
                    {
                        "source": extractor.source.value,
                        "score": 0.0,
                        "error": str(e),
                    }
                )

        # Get best match
        best_extractor = manager.get_extractor_for_text(raw_text)
        if best_extractor:
            result.classification_success = True
            result.detected_source = best_extractor.source.value
            score, patterns = best_extractor.score(raw_text)
            result.classification_score = score
            result.matched_patterns = patterns[:10] if patterns else []
            result.invariant_classified = True
        else:
            result.issues.append("Document classification failed - no extractor matched")
            result.recommendations.append("Check if document format is supported")

    # Step 3: Extraction
    if result.classification_success and raw_text:
        try:
            extractor = manager.get_extractor_for_text(raw_text)
            extraction_result = extractor.extract_with_result(pdf_path, raw_text)

            if extraction_result.invoice:
                result.extraction_success = True
                result.extraction_score = extraction_result.score

                inv = extraction_result.invoice

                # Build extracted fields dict
                fields = {
                    "auction_source": (
                        extraction_result.source.value if extraction_result.source else None
                    ),
                    "reference_id": inv.reference_id,
                    "buyer_id": inv.buyer_id,
                    "buyer_name": inv.buyer_name,
                    "sale_date": str(inv.sale_date) if inv.sale_date else None,
                    "total_amount": str(inv.total_amount) if inv.total_amount else None,
                }

                # Pickup address
                if inv.pickup_address:
                    addr = inv.pickup_address
                    fields.update(
                        {
                            "pickup_name": addr.name,
                            "pickup_address": addr.street,
                            "pickup_city": addr.city,
                            "pickup_state": addr.state,
                            "pickup_zip": addr.postal_code,
                            "pickup_phone": addr.phone,
                        }
                    )

                # Vehicle
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
                            "vehicle_mileage": str(v.mileage) if v.mileage else None,
                        }
                    )

                result.extracted_fields = fields

                # Count filled vs empty
                result.fields_total = len(fields)
                result.fields_filled = sum(1 for v in fields.values() if v is not None and v != "")
                result.fields_empty = result.fields_total - result.fields_filled

                # Check key fields
                result.has_vehicle_vin = bool(fields.get("vehicle_vin"))
                result.has_vehicle_ymm = all(
                    [
                        fields.get("vehicle_year"),
                        fields.get("vehicle_make"),
                        fields.get("vehicle_model"),
                    ]
                )
                result.has_pickup_address = bool(fields.get("pickup_address"))
                result.has_pickup_city_state = bool(fields.get("pickup_city")) and bool(
                    fields.get("pickup_state")
                )
                result.has_reference_id = bool(fields.get("reference_id"))

                # Track field sources
                for key, value in fields.items():
                    result.field_sources[key] = {
                        "value": value,
                        "source": "EXTRACTED" if value else "EMPTY",
                        "method": f"{result.detected_source.lower()}_extractor",
                    }

                # Check anchor fields invariant (at least 3 of: VIN, lot, city, state, facility name)
                anchor_count = sum(
                    [
                        result.has_vehicle_vin,
                        bool(fields.get("vehicle_lot")),
                        bool(fields.get("pickup_city")),
                        bool(fields.get("pickup_state")),
                        bool(fields.get("pickup_name")),
                    ]
                )
                result.invariant_anchor_fields = anchor_count >= 3

                # Generate issues for missing key fields
                if not result.has_vehicle_vin:
                    result.issues.append("VIN not extracted")
                    result.recommendations.append("Check VIN pattern matching in extractor")

                if not result.has_vehicle_ymm:
                    result.issues.append("Vehicle Year/Make/Model incomplete")

                if not result.has_pickup_address:
                    result.issues.append("Pickup address not extracted")
                    result.recommendations.append(
                        "Check address extraction logic for this auction type"
                    )

                if not result.has_pickup_city_state:
                    result.issues.append("Pickup city/state not extracted")

            else:
                result.issues.append("Extraction returned no invoice data")
                result.recommendations.append("Check extractor parsing logic")

        except Exception as e:
            result.issues.append(f"Extraction error: {str(e)}")
            result.recommendations.append("Review extractor code for bugs")

    # Calculate extraction time
    result.extraction_time_ms = int((time.time() - start_time) * 1000)

    # Add invariant failure issues
    if not result.invariant_text_extracted:
        result.issues.insert(0, "INVARIANT FAIL: No text extracted")
    if not result.invariant_classified:
        result.issues.insert(0, "INVARIANT FAIL: Classification failed")
    if not result.invariant_anchor_fields and result.extraction_success:
        result.issues.insert(0, "INVARIANT FAIL: Less than 3 anchor fields extracted")

    return result


def run_diagnostics_batch(sample_docs_dir: str, output_dir: str, max_per_type: int = 2):
    """
    Run diagnostics on a batch of documents.

    Selects up to max_per_type documents for each auction type.
    """

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    # Categorize documents by likely auction type
    copart_docs = []
    iaa_docs = []
    manheim_docs = []

    for pdf_file in Path(sample_docs_dir).glob("*.pdf"):
        filename = pdf_file.name.lower()
        if "vehicle_sale_documents" in filename or "copart" in filename:
            copart_docs.append(str(pdf_file))
        elif "invoice" in filename or "iaa" in filename:
            iaa_docs.append(str(pdf_file))
        elif "showreport" in filename or "manheim" in filename:
            manheim_docs.append(str(pdf_file))

    # Select samples
    selected_docs = []
    selected_docs.extend(copart_docs[:max_per_type])
    selected_docs.extend(iaa_docs[:max_per_type])
    selected_docs.extend(manheim_docs[:max_per_type])

    print(f"Running diagnostics on {len(selected_docs)} documents...")
    print(f"  Copart: {len(copart_docs[:max_per_type])}")
    print(f"  IAA: {len(iaa_docs[:max_per_type])}")
    print(f"  Manheim: {len(manheim_docs[:max_per_type])}")
    print("-" * 60)

    results = []
    summary = {
        "total_docs": len(selected_docs),
        "text_extraction_success": 0,
        "classification_success": 0,
        "extraction_success": 0,
        "invariant_pass_all": 0,
        "by_auction_type": {},
        "common_issues": {},
        "timestamp": datetime.now().isoformat(),
    }

    for pdf_path in selected_docs:
        print(f"\nProcessing: {os.path.basename(pdf_path)}")

        result = run_diagnostic(pdf_path)
        results.append(result)

        # Update summary
        if result.text_extraction_success:
            summary["text_extraction_success"] += 1
        if result.classification_success:
            summary["classification_success"] += 1
        if result.extraction_success:
            summary["extraction_success"] += 1
        if (
            result.invariant_text_extracted
            and result.invariant_classified
            and result.invariant_anchor_fields
        ):
            summary["invariant_pass_all"] += 1

        # Track by auction type
        source = result.detected_source or "UNKNOWN"
        if source not in summary["by_auction_type"]:
            summary["by_auction_type"][source] = {
                "count": 0,
                "success": 0,
                "avg_fields_filled": 0,
                "common_missing_fields": [],
            }
        summary["by_auction_type"][source]["count"] += 1
        if result.extraction_success:
            summary["by_auction_type"][source]["success"] += 1
            summary["by_auction_type"][source]["avg_fields_filled"] += result.fields_filled

        # Track common issues
        for issue in result.issues:
            if issue not in summary["common_issues"]:
                summary["common_issues"][issue] = 0
            summary["common_issues"][issue] += 1

        # Print summary for this doc
        status = "OK" if result.extraction_success else "FAIL"
        print(f"  Status: {status}")
        print(f"  Source: {result.detected_source or 'UNKNOWN'}")
        print(f"  Text: {result.words_count} words")
        print(f"  Fields: {result.fields_filled}/{result.fields_total}")
        if result.issues:
            print(
                f"  Issues: {result.issues[0]}"
                + (f" (+{len(result.issues) - 1} more)" if len(result.issues) > 1 else "")
            )

        # Save individual result
        result_file = os.path.join(output_dir, f"{Path(pdf_path).stem}_diagnostic.json")
        with open(result_file, "w") as f:
            json.dump(asdict(result), f, indent=2, default=str)

    # Calculate averages
    for source, data in summary["by_auction_type"].items():
        if data["success"] > 0:
            data["avg_fields_filled"] = round(data["avg_fields_filled"] / data["success"], 1)

    # Sort common issues by frequency
    summary["common_issues"] = dict(
        sorted(summary["common_issues"].items(), key=lambda x: x[1], reverse=True)
    )

    # Save summary
    summary_file = os.path.join(output_dir, "diagnostic_summary.json")
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2)

    # Print summary
    print("\n" + "=" * 60)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 60)
    print(f"Total documents: {summary['total_docs']}")
    print(f"Text extraction success: {summary['text_extraction_success']}/{summary['total_docs']}")
    print(f"Classification success: {summary['classification_success']}/{summary['total_docs']}")
    print(f"Extraction success: {summary['extraction_success']}/{summary['total_docs']}")
    print(f"All invariants pass: {summary['invariant_pass_all']}/{summary['total_docs']}")

    print("\nBy Auction Type:")
    for source, data in summary["by_auction_type"].items():
        print(
            f"  {source}: {data['success']}/{data['count']} success, avg {data['avg_fields_filled']} fields"
        )

    print("\nTop Issues:")
    for issue, count in list(summary["common_issues"].items())[:5]:
        print(f"  [{count}x] {issue}")

    print(f"\nResults saved to: {output_dir}")

    return summary, results


if __name__ == "__main__":
    sample_docs_dir = "tests/sample_docs"
    output_dir = "diagnostics/samples"

    if not os.path.exists(sample_docs_dir):
        print(f"Sample docs directory not found: {sample_docs_dir}")
        sys.exit(1)

    summary, results = run_diagnostics_batch(sample_docs_dir, output_dir, max_per_type=2)

    # Exit with error if critical failures
    if summary["extraction_success"] < summary["total_docs"] * 0.5:
        print("\nWARNING: Less than 50% extraction success rate!")
        sys.exit(1)
