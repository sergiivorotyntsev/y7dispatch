#!/usr/bin/env python3
"""
Batch extraction test using Claude Haiku with CSV output for human review.

Phase 1 iterative testing:
- Round 1: Run extraction, user reviews, I adjust prompt
- Round 2: New docs, repeat
- Round 3: Final tuning

Usage:
    # Set API key first
    export ANTHROPIC_API_KEY=your-key-here

    # Run extraction
    python scripts/haiku_batch_test.py --docs-dir tests/sample_docs --output round1_results.csv
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_batch_extraction(docs_dir: str, output_csv: str, output_json: str):
    """Run Haiku extraction on all PDFs and generate review files."""

    from services.haiku_extractor import HaikuExtractor, ExtractionResult

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set!")
        print("\nTo set it:")
        print("  export ANTHROPIC_API_KEY=your-key-here")
        print("\nGet your key from: https://console.anthropic.com/")
        sys.exit(1)

    # Find all PDFs
    pdf_files = sorted(Path(docs_dir).glob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files in {docs_dir}\n")

    if not pdf_files:
        print("No PDF files found!")
        sys.exit(1)

    # Initialize extractor
    extractor = HaikuExtractor(api_key=api_key)

    results = []
    total_cost = 0.0
    total_tokens = 0

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] Processing: {pdf_path.name}...")

        try:
            result = extractor.extract(str(pdf_path))
        except Exception as e:
            print(f"  [ERR] {e}")
            result = ExtractionResult(error=str(e))

        # Build row for CSV
        row = {
            "file": pdf_path.name,
            "file_path": str(pdf_path),
            "status": "success" if not result.error else "error",
            "auction_type": result.auction_type,
            "confidence": round(result.confidence, 3),
            "cost_usd": result.cost_usd,
            "tokens": result.tokens_used.total_tokens,
            "error": result.error or "",
        }

        # Add all extracted fields
        field_names = [
            "vehicle_vin", "vehicle_year", "vehicle_make", "vehicle_model",
            "vehicle_color", "vehicle_type", "vehicle_lot",
            "pickup_name", "pickup_address", "pickup_city", "pickup_state", "pickup_zip", "pickup_phone",
            "buyer_id", "buyer_name", "seller_name", "sale_date", "total_amount"
        ]

        for field_name in field_names:
            if field_name in result.fields:
                field = result.fields[field_name]
                row[field_name] = str(field.value) if field.value is not None else ""
                row[f"{field_name}_conf"] = round(field.confidence, 2)
            else:
                row[field_name] = ""
                row[f"{field_name}_conf"] = 0.0

        results.append(row)

        total_cost += result.cost_usd
        total_tokens += result.tokens_used.total_tokens

        # Print status
        if result.error:
            print(f"  [ERR] {result.error}")
        else:
            filled_fields = sum(1 for fn in field_names if row.get(fn))
            print(f"  [OK] {result.auction_type} | conf={result.confidence:.2f} | fields={filled_fields}/18 | cost=${result.cost_usd:.4f}")

            # Show key fields
            vin = row.get("vehicle_vin", "")[:17]
            year = row.get("vehicle_year", "")
            make = row.get("vehicle_make", "")
            model = row.get("vehicle_model", "")
            if vin:
                print(f"       VIN: {vin} | {year} {make} {model}")

    # Write CSV for review
    csv_columns = [
        "file", "status", "auction_type", "confidence", "cost_usd", "tokens",
        # Vehicle fields
        "vehicle_vin", "vehicle_vin_conf",
        "vehicle_year", "vehicle_year_conf",
        "vehicle_make", "vehicle_make_conf",
        "vehicle_model", "vehicle_model_conf",
        "vehicle_color", "vehicle_color_conf",
        "vehicle_type", "vehicle_type_conf",
        "vehicle_lot", "vehicle_lot_conf",
        # Pickup fields
        "pickup_name", "pickup_name_conf",
        "pickup_address", "pickup_address_conf",
        "pickup_city", "pickup_city_conf",
        "pickup_state", "pickup_state_conf",
        "pickup_zip", "pickup_zip_conf",
        "pickup_phone", "pickup_phone_conf",
        # Buyer/seller fields
        "buyer_id", "buyer_id_conf",
        "buyer_name", "buyer_name_conf",
        "seller_name", "seller_name_conf",
        "sale_date", "sale_date_conf",
        "total_amount", "total_amount_conf",
        # Review columns (user fills these)
        "vin_correct", "vin_expected",
        "year_correct", "year_expected",
        "make_correct", "make_expected",
        "model_correct", "model_expected",
        "lot_correct", "lot_expected",
        "pickup_city_correct", "pickup_city_expected",
        "pickup_state_correct", "pickup_state_expected",
        "overall_notes",
        # Error
        "error"
    ]

    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=csv_columns, extrasaction='ignore')
        writer.writeheader()

        for r in results:
            # Add empty review columns
            r["vin_correct"] = ""
            r["vin_expected"] = ""
            r["year_correct"] = ""
            r["year_expected"] = ""
            r["make_correct"] = ""
            r["make_expected"] = ""
            r["model_correct"] = ""
            r["model_expected"] = ""
            r["lot_correct"] = ""
            r["lot_expected"] = ""
            r["pickup_city_correct"] = ""
            r["pickup_city_expected"] = ""
            r["pickup_state_correct"] = ""
            r["pickup_state_expected"] = ""
            r["overall_notes"] = ""
            writer.writerow(r)

    # Write full JSON
    json_results = []
    for r in results:
        json_results.append({
            "file": r["file"],
            "status": r["status"],
            "auction_type": r["auction_type"],
            "confidence": r["confidence"],
            "cost_usd": r["cost_usd"],
            "tokens": r["tokens"],
            "error": r["error"],
            "fields": {
                k: {"value": r.get(k), "confidence": r.get(f"{k}_conf", 0)}
                for k in [
                    "vehicle_vin", "vehicle_year", "vehicle_make", "vehicle_model",
                    "vehicle_color", "vehicle_type", "vehicle_lot",
                    "pickup_name", "pickup_address", "pickup_city", "pickup_state", "pickup_zip", "pickup_phone",
                    "buyer_id", "buyer_name", "seller_name", "sale_date", "total_amount"
                ]
            }
        })

    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "model": "claude-haiku-4-5-20251001",
            "docs_count": len(results),
            "success_count": sum(1 for r in results if r["status"] == "success"),
            "total_cost_usd": round(total_cost, 4),
            "total_tokens": total_tokens,
            "results": json_results
        }, f, indent=2, default=str)

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Documents processed: {len(results)}")
    print(f"  Successful: {sum(1 for r in results if r['status'] == 'success')}")
    print(f"  Errors: {sum(1 for r in results if r['status'] == 'error')}")
    print(f"  Total cost: ${total_cost:.4f}")
    print(f"  Total tokens: {total_tokens:,}")
    print(f"  Avg cost per doc: ${total_cost/len(results):.4f}")

    print(f"\nOutputs:")
    print(f"  CSV for review: {output_csv}")
    print(f"  Full JSON:      {output_json}")

    print(f"\n" + "=" * 60)
    print("NEXT STEPS - Iterative Training")
    print("=" * 60)
    print(f"""
1. Open {output_csv} in Excel or Google Sheets

2. For each row, review extracted values and fill in:
   - *_correct columns: Y (correct) or N (incorrect)
   - *_expected columns: the correct value (if incorrect)
   - overall_notes: any observations

3. Save the file and share it back

4. I will analyze the errors and:
   - Adjust the extraction prompt
   - Add specific rules for problem cases
   - Run again on the next batch of documents

Repeat for 3 rounds to optimize extraction accuracy.
""")

    return results


def main():
    parser = argparse.ArgumentParser(description="Haiku batch extraction test")
    parser.add_argument("--docs-dir", default="tests/sample_docs",
                       help="Directory with PDF files")
    parser.add_argument("--output", default="tests/sample_docs/haiku_extraction_review.csv",
                       help="Output CSV file")
    parser.add_argument("--json", default="tests/sample_docs/haiku_extraction_results.json",
                       help="Output JSON file")

    args = parser.parse_args()

    run_batch_extraction(args.docs_dir, args.output, args.json)


if __name__ == "__main__":
    main()
