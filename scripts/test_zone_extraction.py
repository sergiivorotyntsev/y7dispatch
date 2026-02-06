#!/usr/bin/env python3
"""
Test Zone Extraction on Sample Documents

This script tests both traditional pattern extraction and new zone-based extraction
on all sample documents to compare results and identify improvements needed.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pdfplumber
from extractors.zone_extractor import get_zone_extractor, ZoneExtractor
from extractors import ExtractorManager


def extract_raw_text(pdf_path: str) -> str:
    """Extract raw text from PDF for analysis"""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text(layout=True) or ""
            return text
    except Exception as e:
        return f"ERROR: {e}"


def classify_document(text: str) -> str:
    """Classify document type based on content"""
    text_upper = text.upper()

    if "COPART" in text_upper or "SOLD THROUGH COPART" in text_upper:
        return "COPART"
    elif "IAAI" in text_upper or "INSURANCE AUTO AUCTIONS" in text_upper or "IAA" in text_upper:
        return "IAA"
    elif "MANHEIM" in text_upper:
        return "MANHEIM"
    else:
        return "UNKNOWN"


def test_pattern_extraction(pdf_path: str, text: str) -> dict:
    """Test traditional pattern-based extraction"""
    manager = ExtractorManager()

    try:
        extractor = manager.get_extractor_for_text(text)
        if extractor:
            result = extractor.extract_with_result(pdf_path, text)

            fields = {}
            if result.invoice:
                inv = result.invoice
                fields["auction_source"] = result.source.value if result.source else None
                fields["reference_id"] = inv.reference_id
                fields["buyer_id"] = inv.buyer_id
                fields["buyer_name"] = inv.buyer_name
                fields["sale_date"] = str(inv.sale_date) if inv.sale_date else None
                fields["total_amount"] = inv.total_amount

                if inv.pickup_address:
                    addr = inv.pickup_address
                    fields["pickup_name"] = addr.name
                    fields["pickup_address"] = addr.street
                    fields["pickup_city"] = addr.city
                    fields["pickup_state"] = addr.state
                    fields["pickup_zip"] = addr.postal_code

                if inv.vehicles:
                    v = inv.vehicles[0]
                    fields["vehicle_vin"] = v.vin
                    fields["vehicle_year"] = v.year
                    fields["vehicle_make"] = v.make
                    fields["vehicle_model"] = v.model
                    fields["vehicle_lot"] = v.lot_number

            return {
                "success": True,
                "extractor": extractor.source.value if extractor.source else "unknown",
                "score": result.score,
                "fields": fields,
            }
        else:
            return {"success": False, "error": "No extractor matched"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def test_zone_extraction(pdf_path: str, auction_type: str) -> dict:
    """Test zone-based extraction"""
    try:
        extractor = get_zone_extractor()
        result = extractor.extract(pdf_path, auction_type)

        return {
            "success": True,
            "template_id": result.template_id,
            "confidence": result.confidence,
            "fields": result.fields,
            "zone_texts": result.zone_texts,
            "warnings": result.warnings,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def analyze_document(pdf_path: str) -> dict:
    """Analyze a single document with both extraction methods"""
    filename = os.path.basename(pdf_path)
    print(f"\n{'='*60}")
    print(f"Analyzing: {filename}")
    print(f"{'='*60}")

    # Extract raw text
    text = extract_raw_text(pdf_path)
    text_preview = text[:500] if text else ""

    # Classify document
    doc_type = classify_document(text)
    print(f"Document Type: {doc_type}")
    print(f"Text Length: {len(text)} chars")

    # Pattern extraction
    print("\n--- Pattern Extraction ---")
    pattern_result = test_pattern_extraction(pdf_path, text)
    if pattern_result["success"]:
        print(f"Extractor: {pattern_result.get('extractor')}")
        print(f"Score: {pattern_result.get('score', 0):.2f}")
        fields = pattern_result.get("fields", {})
        print("Fields extracted:")
        for k, v in fields.items():
            if v:
                print(f"  {k}: {v}")
    else:
        print(f"Error: {pattern_result.get('error')}")

    # Zone extraction
    print("\n--- Zone Extraction ---")
    zone_result = test_zone_extraction(pdf_path, doc_type)
    if zone_result["success"]:
        print(f"Template: {zone_result.get('template_id')}")
        print(f"Confidence: {zone_result.get('confidence', 0):.2f}")
        fields = zone_result.get("fields", {})
        print("Fields extracted:")
        for k, v in fields.items():
            if v:
                print(f"  {k}: {v}")

        if zone_result.get("warnings"):
            print("Warnings:")
            for w in zone_result["warnings"]:
                print(f"  ⚠️ {w}")

        # Print zone texts for debugging
        print("\nZone Texts:")
        for zone_name, zone_text in zone_result.get("zone_texts", {}).items():
            preview = zone_text[:150].replace('\n', ' ') if zone_text else "(empty)"
            print(f"  [{zone_name}]: {preview}...")
    else:
        print(f"Error: {zone_result.get('error')}")

    # Compare results
    print("\n--- Comparison ---")
    pattern_fields = pattern_result.get("fields", {}) if pattern_result["success"] else {}
    zone_fields = zone_result.get("fields", {}) if zone_result["success"] else {}

    # Key fields to compare
    key_fields = [
        "pickup_address", "pickup_city", "pickup_state", "pickup_zip",
        "vehicle_vin", "vehicle_year", "vehicle_make", "vehicle_model"
    ]

    differences = []
    for field in key_fields:
        p_val = pattern_fields.get(field)
        z_val = zone_fields.get(field)

        if p_val != z_val:
            differences.append({
                "field": field,
                "pattern": p_val,
                "zone": z_val,
            })

    if differences:
        print("Differences found:")
        for d in differences:
            print(f"  {d['field']}:")
            print(f"    Pattern: {d['pattern']}")
            print(f"    Zone:    {d['zone']}")
    else:
        print("No differences in key fields")

    return {
        "filename": filename,
        "doc_type": doc_type,
        "text_length": len(text),
        "text_preview": text_preview,
        "pattern_result": pattern_result,
        "zone_result": zone_result,
        "differences": differences,
    }


def run_all_tests():
    """Run tests on all sample documents"""
    sample_dir = Path(__file__).parent.parent / "tests" / "sample_docs"

    if not sample_dir.exists():
        print(f"Sample directory not found: {sample_dir}")
        return

    pdf_files = list(sample_dir.glob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files")

    results = []
    for pdf_path in sorted(pdf_files):
        result = analyze_document(str(pdf_path))
        results.append(result)

    # Summary report
    print("\n" + "="*60)
    print("SUMMARY REPORT")
    print("="*60)

    # Group by document type
    by_type = {}
    for r in results:
        doc_type = r["doc_type"]
        if doc_type not in by_type:
            by_type[doc_type] = []
        by_type[doc_type].append(r)

    print(f"\nDocuments by type:")
    for doc_type, docs in by_type.items():
        print(f"  {doc_type}: {len(docs)} documents")

    # Extraction success rates
    pattern_success = sum(1 for r in results if r["pattern_result"]["success"])
    zone_success = sum(1 for r in results if r["zone_result"]["success"])

    print(f"\nExtraction success:")
    print(f"  Pattern: {pattern_success}/{len(results)}")
    print(f"  Zone: {zone_success}/{len(results)}")

    # Field extraction rates
    print(f"\nKey field extraction (Pattern vs Zone):")
    key_fields = ["pickup_address", "pickup_city", "pickup_state", "pickup_zip", "vehicle_vin"]

    for field in key_fields:
        pattern_count = sum(1 for r in results
                          if r["pattern_result"]["success"]
                          and r["pattern_result"].get("fields", {}).get(field))
        zone_count = sum(1 for r in results
                        if r["zone_result"]["success"]
                        and r["zone_result"].get("fields", {}).get(field))
        print(f"  {field}: Pattern={pattern_count}, Zone={zone_count}")

    # Documents with differences
    docs_with_diff = [r for r in results if r.get("differences")]
    print(f"\nDocuments with differences: {len(docs_with_diff)}")

    # Common issues
    print("\n" + "="*60)
    print("ISSUES AND RECOMMENDATIONS")
    print("="*60)

    issues = []

    # Check for zone extraction failures
    for r in results:
        if not r["zone_result"]["success"]:
            issues.append(f"Zone extraction failed for {r['filename']}: {r['zone_result'].get('error')}")
        elif r["zone_result"].get("warnings"):
            for w in r["zone_result"]["warnings"]:
                issues.append(f"{r['filename']}: {w}")

    if issues:
        print("\nIssues found:")
        for issue in issues[:20]:  # Limit to 20
            print(f"  - {issue}")

    # Save detailed results to JSON
    output_path = sample_dir / "extraction_test_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nDetailed results saved to: {output_path}")

    return results


if __name__ == "__main__":
    run_all_tests()
