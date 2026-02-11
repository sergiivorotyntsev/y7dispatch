#!/usr/bin/env python3
"""
Batch extraction test with CSV output for human review.

Usage:
    python scripts/batch_extraction_test.py [--output results.csv]

Outputs:
    - CSV file with extracted fields and columns for user feedback
    - JSON file with full extraction details
"""

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def extract_document(pdf_path: str) -> dict:
    """Extract data from a single PDF and return structured result."""
    import pdfplumber
    from extractors import ExtractorManager

    result = {
        "file": os.path.basename(pdf_path),
        "file_path": pdf_path,
        "status": "error",
        "source": "",
        "score": 0.0,
        "text_length": 0,
        "needs_ocr": False,
        # Invoice fields
        "buyer_id": "",
        "buyer_name": "",
        "seller_name": "",
        "sale_date": "",
        "lot_number": "",
        "total_amount": "",
        # Pickup address
        "pickup_name": "",
        "pickup_street": "",
        "pickup_city": "",
        "pickup_state": "",
        "pickup_zip": "",
        "pickup_phone": "",
        # Vehicle fields (first vehicle)
        "vin": "",
        "year": "",
        "make": "",
        "model": "",
        "color": "",
        "mileage": "",
        "is_inoperable": "",
        # Error info
        "error": "",
    }

    try:
        # Extract text
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                full_text += page_text + "\n"

        result["text_length"] = len(full_text)
        result["needs_ocr"] = len(full_text) < 100

        if result["needs_ocr"]:
            result["status"] = "needs_ocr"
            result["error"] = "Text too short, needs OCR"
            return result

        # Try extractors
        manager = ExtractorManager()
        best_extractor = None
        best_score = 0

        for extractor in manager.extractors:
            score, patterns = extractor.score(full_text)
            if score > best_score:
                best_score = score
                best_extractor = extractor

        result["source"] = best_extractor.source.value if best_extractor else "UNKNOWN"
        result["score"] = round(best_score, 3)

        if best_score < 0.3:
            result["status"] = "low_confidence"
            result["error"] = f"Best score {best_score:.2f} below threshold 0.3"
            return result

        # Extract data
        extraction = best_extractor.extract_with_result(pdf_path, full_text)

        if not extraction.invoice:
            result["status"] = "no_invoice"
            result["error"] = "Extractor matched but no invoice extracted"
            return result

        inv = extraction.invoice
        result["status"] = "success"

        # Invoice fields
        result["buyer_id"] = inv.buyer_id or ""
        result["buyer_name"] = inv.buyer_name or ""
        result["seller_name"] = getattr(inv, 'seller_name', '') or ""
        result["sale_date"] = str(inv.sale_date) if inv.sale_date else ""
        result["lot_number"] = inv.lot_number or ""
        result["total_amount"] = str(inv.total_amount) if inv.total_amount else ""

        # Pickup address
        if inv.pickup_address:
            addr = inv.pickup_address
            result["pickup_name"] = addr.name or ""
            result["pickup_street"] = addr.street or ""
            result["pickup_city"] = addr.city or ""
            result["pickup_state"] = addr.state or ""
            result["pickup_zip"] = addr.postal_code or ""
            result["pickup_phone"] = addr.phone or ""

        # First vehicle
        if inv.vehicles:
            v = inv.vehicles[0]
            result["vin"] = v.vin or ""
            result["year"] = str(v.year) if v.year else ""
            result["make"] = v.make or ""
            result["model"] = v.model or ""
            result["color"] = v.color or ""
            result["mileage"] = str(v.mileage) if v.mileage else ""
            result["is_inoperable"] = "YES" if v.is_inoperable else "NO"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def run_batch_extraction(docs_dir: str, output_csv: str, output_json: str):
    """Run extraction on all PDFs in directory."""

    # Find all PDFs
    pdf_files = sorted(Path(docs_dir).glob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files in {docs_dir}\n")

    results = []

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] Processing: {pdf_path.name}...")
        result = extract_document(str(pdf_path))
        results.append(result)

        status_icon = {
            "success": "[OK]",
            "needs_ocr": "[OCR]",
            "low_confidence": "[LOW]",
            "no_invoice": "[EMPTY]",
            "error": "[ERR]",
        }.get(result["status"], "[?]")

        print(f"  {status_icon} {result['source']} (score={result['score']:.2f})")
        if result["error"]:
            print(f"       Error: {result['error']}")
        if result["vin"]:
            print(f"       VIN: {result['vin']}, {result['year']} {result['make']} {result['model']}")

    # Write CSV for review
    csv_columns = [
        "file", "status", "source", "score",
        # Extracted values
        "vin", "year", "make", "model", "color", "mileage",
        "lot_number", "buyer_id", "buyer_name",
        "pickup_city", "pickup_state", "pickup_zip", "pickup_street",
        "sale_date", "total_amount",
        # Review columns (user fills these)
        "vin_correct", "vin_expected",
        "year_correct", "year_expected",
        "make_correct", "make_expected",
        "model_correct", "model_expected",
        "lot_correct", "lot_expected",
        "pickup_correct", "pickup_expected",
        "notes"
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
            r["pickup_correct"] = ""
            r["pickup_expected"] = ""
            r["notes"] = ""
            writer.writerow(r)

    # Write full JSON
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "docs_count": len(results),
            "success_count": sum(1 for r in results if r["status"] == "success"),
            "results": results
        }, f, indent=2, default=str)

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")

    status_counts = {}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    print(f"\nOutputs:")
    print(f"  CSV for review: {output_csv}")
    print(f"  Full JSON:      {output_json}")
    print(f"\nNext steps:")
    print(f"  1. Open {output_csv} in Excel/Google Sheets")
    print(f"  2. For each row, fill in *_correct columns (Y/N)")
    print(f"  3. If incorrect, fill in *_expected with correct value")
    print(f"  4. Add notes for any issues")
    print(f"  5. Save and send back for analysis")

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Batch extraction test")
    parser.add_argument("--docs-dir", default="tests/sample_docs",
                       help="Directory with PDF files")
    parser.add_argument("--output", default="tests/sample_docs/extraction_review.csv",
                       help="Output CSV file")
    parser.add_argument("--json", default="tests/sample_docs/extraction_results.json",
                       help="Output JSON file")

    args = parser.parse_args()

    run_batch_extraction(args.docs_dir, args.output, args.json)


if __name__ == "__main__":
    main()
