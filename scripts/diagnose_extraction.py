#!/usr/bin/env python3
"""
Diagnostic script for extraction pipeline issues.

Run this script to diagnose why fields are empty in Review & Post.

Usage:
    python scripts/diagnose_extraction.py [document_id]

If no document_id provided, analyzes the last 5 uploaded documents.
"""

import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.database import get_connection
from api.models import DocumentRepository, ReviewItemRepository


def diagnose_document(doc_id: int):
    """Diagnose extraction pipeline for a specific document."""
    print(f"\n{'=' * 60}")
    print(f"DIAGNOSING DOCUMENT ID: {doc_id}")
    print(f"{'=' * 60}")

    # Get document
    doc = DocumentRepository.get_by_id(doc_id)
    if not doc:
        print(f"ERROR: Document {doc_id} not found!")
        return

    print("\n1. DOCUMENT INFO")
    print(f"   Filename: {doc.filename}")
    print(f"   File path: {doc.file_path}")
    print(f"   Auction type ID: {doc.auction_type_id}")
    print(f"   Created: {doc.created_at}")

    # Check raw text
    raw_text = doc.raw_text or ""
    print("\n2. TEXT EXTRACTION")
    print(f"   Raw text length: {len(raw_text)} characters")

    if len(raw_text) < 100:
        print("   ⚠️  WARNING: Very short text! Likely needs OCR.")
        print(f"   First 200 chars: {raw_text[:200]}")
    else:
        print("   ✓ Text extraction OK")
        print(f"   First 300 chars:\n   {raw_text[:300].replace(chr(10), chr(10) + '   ')}")

    # Get extraction runs
    with get_connection() as conn:
        runs = conn.execute(
            "SELECT * FROM extraction_runs WHERE document_id = ? ORDER BY created_at DESC",
            (doc_id,),
        ).fetchall()

    if not runs:
        print("\n3. EXTRACTION RUNS")
        print("   ⚠️  NO EXTRACTION RUNS FOUND!")
        print("   The document was uploaded but extraction never ran.")
        return

    for run in runs:
        run = dict(run)
        print(f"\n3. EXTRACTION RUN (ID: {run['id']})")
        print(f"   Status: {run['status']}")
        print(f"   Extractor kind: {run['extractor_kind']}")
        print(f"   Extraction score: {run['extraction_score']}")
        print(f"   Processing time: {run['processing_time_ms']} ms")
        print(f"   Created: {run['created_at']}")

        # Check errors
        if run["errors_json"]:
            errors = (
                json.loads(run["errors_json"])
                if isinstance(run["errors_json"], str)
                else run["errors_json"]
            )
            print("\n   ⚠️  ERRORS:")
            for err in errors:
                print(f"      - {err}")

        # Check outputs
        outputs_json = run["outputs_json"]
        if outputs_json:
            outputs = json.loads(outputs_json) if isinstance(outputs_json, str) else outputs_json
            print("\n4. EXTRACTED OUTPUTS")
            print(f"   Total fields: {len(outputs)}")

            filled = {k: v for k, v in outputs.items() if v is not None and v != ""}
            print(f"   Filled fields: {len(filled)}")

            if filled:
                print("\n   Extracted values:")
                for key, value in filled.items():
                    val_str = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
                    print(f"      {key}: {val_str}")
            else:
                print("   ⚠️  ALL FIELDS ARE EMPTY!")
        else:
            print("\n4. EXTRACTED OUTPUTS")
            print("   ⚠️  outputs_json is NULL/empty!")

        # Check review items
        items = ReviewItemRepository.get_by_run(run["id"])
        print("\n5. REVIEW ITEMS")
        print(f"   Total items: {len(items)}")

        filled_items = [i for i in items if i.predicted_value or i.corrected_value]
        print(f"   Items with values: {len(filled_items)}")

        if filled_items:
            print("\n   Sample filled items:")
            for item in filled_items[:5]:
                value = item.corrected_value or item.predicted_value
                val_str = str(value)[:40] + "..." if len(str(value)) > 40 else str(value)
                print(f"      {item.source_key}: {val_str} (confidence: {item.confidence})")


def diagnose_last_documents(count: int = 5):
    """Diagnose the last N uploaded documents."""
    print(f"\nFetching last {count} documents...")

    with get_connection() as conn:
        docs = conn.execute(
            "SELECT id, filename, created_at FROM documents ORDER BY created_at DESC LIMIT ?",
            (count,),
        ).fetchall()

    if not docs:
        print("No documents found in database!")
        return

    print(f"\nFound {len(docs)} documents:")
    for doc in docs:
        print(f"  [{doc['id']}] {doc['filename']} ({doc['created_at']})")

    for doc in docs:
        diagnose_document(doc["id"])


def test_extraction_on_document(doc_id: int):
    """Test extraction manually on a document."""
    print(f"\n{'=' * 60}")
    print(f"TESTING EXTRACTION ON DOCUMENT {doc_id}")
    print(f"{'=' * 60}")

    doc = DocumentRepository.get_by_id(doc_id)
    if not doc:
        print(f"ERROR: Document {doc_id} not found!")
        return

    raw_text = doc.raw_text or ""

    if len(raw_text) < 100:
        print(f"\n⚠️  Document has very little text ({len(raw_text)} chars).")
        print("Attempting to re-extract from PDF...")

        if doc.file_path and os.path.exists(doc.file_path):
            import pdfplumber

            with pdfplumber.open(doc.file_path) as pdf:
                pages_text = []
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages_text.append(page_text)
                raw_text = "\n".join(pages_text)
                print(f"Re-extracted text length: {len(raw_text)}")
        else:
            print(f"PDF file not found at: {doc.file_path}")
            return

    # Test classification
    from extractors import ExtractorManager

    manager = ExtractorManager()

    print("\nClassification scores:")
    scores = manager.get_all_scores(doc.file_path) if doc.file_path else []

    if not scores:
        # Classify from text
        extractor = manager.get_extractor_for_text(raw_text)
        if extractor:
            score, patterns = extractor.score(raw_text)
            print(f"  {extractor.source.value}: score={score:.2f}, patterns={patterns}")
        else:
            print("  No extractor matched!")
            return

    for source, score, patterns in scores:
        status = "✓" if score >= 0.3 else "✗"
        print(f"  {status} {source.value}: score={score:.2f}, patterns={patterns}")

    # Test extraction
    print("\nAttempting extraction...")

    if doc.file_path and os.path.exists(doc.file_path):
        result = manager.extract_with_result(doc.file_path)

        print("\nExtraction result:")
        print(f"  Source: {result.source}")
        print(f"  Score: {result.score}")
        print(f"  Text length: {result.text_length}")
        print(f"  Needs OCR: {result.needs_ocr}")
        print(f"  Matched patterns: {result.matched_patterns}")

        if result.invoice:
            inv = result.invoice
            print("\nExtracted invoice data:")
            print(f"  Reference ID: {inv.reference_id}")
            print(f"  Buyer ID: {inv.buyer_id}")
            print(f"  Buyer Name: {inv.buyer_name}")
            print(f"  Sale Date: {inv.sale_date}")

            if inv.pickup_address:
                addr = inv.pickup_address
                print("\n  Pickup Address:")
                print(f"    Name: {addr.name}")
                print(f"    Street: {addr.street}")
                print(f"    City: {addr.city}")
                print(f"    State: {addr.state}")
                print(f"    ZIP: {addr.postal_code}")

            if inv.vehicles:
                for i, v in enumerate(inv.vehicles):
                    print(f"\n  Vehicle {i + 1}:")
                    print(f"    VIN: {v.vin}")
                    print(f"    Year: {v.year}")
                    print(f"    Make: {v.make}")
                    print(f"    Model: {v.model}")
                    print(f"    Color: {v.color}")
                    print(f"    Lot: {v.lot_number}")
        else:
            print("\n⚠️  No invoice extracted!")
            print("The extractor could not parse the document structure.")
    else:
        print(f"PDF file not found at: {doc.file_path}")


def main():
    if len(sys.argv) > 1:
        doc_id = int(sys.argv[1])
        diagnose_document(doc_id)
        test_extraction_on_document(doc_id)
    else:
        diagnose_last_documents(5)


if __name__ == "__main__":
    main()
