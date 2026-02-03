#!/usr/bin/env python3
"""
Direct extraction test on a PDF file.

Usage:
    python scripts/test_extraction_direct.py <path_to_pdf>

Example:
    python scripts/test_extraction_direct.py data/uploads/copart_invoice.pdf
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_extraction(pdf_path: str):
    """Test extraction directly on a PDF file."""
    print(f"\n{'=' * 60}")
    print(f"TESTING EXTRACTION: {pdf_path}")
    print(f"{'=' * 60}")

    if not os.path.exists(pdf_path):
        print(f"ERROR: File not found: {pdf_path}")
        return

    file_size = os.path.getsize(pdf_path)
    print(f"\nFile size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")

    # Step 1: Extract text with pdfplumber
    print("\n1. TEXT EXTRACTION (pdfplumber)")
    print("-" * 40)

    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            print(f"   Pages: {len(pdf.pages)}")

            full_text = ""
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                words = page.extract_words() or []
                print(f"   Page {i + 1}: {len(page_text)} chars, {len(words)} words")
                full_text += page_text + "\n"

            print(f"\n   Total text length: {len(full_text)} chars")

            if len(full_text) < 100:
                print("   ⚠️  VERY SHORT TEXT - likely a scanned PDF, needs OCR!")
            else:
                print("   ✓ Text extraction OK")

            # Show first 500 chars
            print("\n   First 500 characters:")
            print(f"   {'-' * 40}")
            preview = full_text[:500].replace("\n", "\n   ")
            print(f"   {preview}")

    except Exception as e:
        print(f"   ERROR: {e}")
        return

    # Step 2: Classification
    print("\n2. CLASSIFICATION")
    print("-" * 40)

    try:
        from extractors import ExtractorManager

        manager = ExtractorManager()

        # Get scores from all extractors
        best_extractor = None
        best_score = 0

        for extractor in manager.extractors:
            score, patterns = extractor.score(full_text)
            status = "✓" if score >= 0.3 else "✗"
            print(f"   {status} {extractor.source.value}: score={score:.2f}")
            if patterns:
                print(f"      Matched: {patterns[:5]}")

            if score > best_score:
                best_score = score
                best_extractor = extractor

        if best_score >= 0.3:
            print(f"\n   ✓ Detected: {best_extractor.source.value} (score={best_score:.2f})")
        else:
            print(
                f"\n   ⚠️  No confident match! Best: {best_extractor.source.value if best_extractor else 'None'} ({best_score:.2f})"
            )

    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback

        traceback.print_exc()
        return

    # Step 3: Field Extraction
    print("\n3. FIELD EXTRACTION")
    print("-" * 40)

    try:
        if best_extractor and best_score >= 0.3:
            result = best_extractor.extract_with_result(pdf_path, full_text)

            print(f"   Score: {result.score:.2f}")
            print(f"   Needs OCR: {result.needs_ocr}")
            print(f"   Matched patterns: {result.matched_patterns}")

            if result.invoice:
                inv = result.invoice
                print("\n   EXTRACTED DATA:")
                print(f"   {'-' * 30}")

                # Basic info
                print(f"   Reference ID: {inv.reference_id or '(empty)'}")
                print(f"   Buyer ID: {inv.buyer_id or '(empty)'}")
                print(f"   Buyer Name: {inv.buyer_name or '(empty)'}")
                print(f"   Seller Name: {inv.seller_name or '(empty)'}")
                print(f"   Sale Date: {inv.sale_date or '(empty)'}")
                print(f"   Total Amount: {inv.total_amount or '(empty)'}")
                print(f"   Lot Number: {inv.lot_number or '(empty)'}")

                # Pickup address
                if inv.pickup_address:
                    addr = inv.pickup_address
                    print("\n   PICKUP ADDRESS:")
                    print(f"      Name: {addr.name or '(empty)'}")
                    print(f"      Street: {addr.street or '(empty)'}")
                    print(f"      City: {addr.city or '(empty)'}")
                    print(f"      State: {addr.state or '(empty)'}")
                    print(f"      ZIP: {addr.postal_code or '(empty)'}")
                    print(f"      Phone: {addr.phone or '(empty)'}")
                else:
                    print("\n   ⚠️  PICKUP ADDRESS: Not extracted")

                # Vehicles
                if inv.vehicles:
                    for i, v in enumerate(inv.vehicles):
                        print(f"\n   VEHICLE {i + 1}:")
                        print(f"      VIN: {v.vin or '(empty)'}")
                        print(f"      Year: {v.year or '(empty)'}")
                        print(f"      Make: {v.make or '(empty)'}")
                        print(f"      Model: {v.model or '(empty)'}")
                        print(f"      Color: {v.color or '(empty)'}")
                        print(f"      Lot: {v.lot_number or '(empty)'}")
                        print(f"      Mileage: {v.mileage or '(empty)'}")
                        print(f"      Inoperable: {v.is_inoperable}")
                else:
                    print("\n   ⚠️  VEHICLES: None extracted")

                # Count filled fields
                filled = 0
                total = 0
                for attr in [
                    "reference_id",
                    "buyer_id",
                    "buyer_name",
                    "sale_date",
                    "total_amount",
                    "lot_number",
                ]:
                    total += 1
                    if getattr(inv, attr, None):
                        filled += 1

                if inv.pickup_address:
                    for attr in ["street", "city", "state", "postal_code"]:
                        total += 1
                        if getattr(inv.pickup_address, attr, None):
                            filled += 1

                if inv.vehicles:
                    for attr in ["vin", "year", "make", "model"]:
                        total += 1
                        if getattr(inv.vehicles[0], attr, None):
                            filled += 1

                print(f"\n   SUMMARY: {filled}/{total} key fields filled")

            else:
                print("\n   ⚠️  NO INVOICE EXTRACTED!")
                print("   The extractor matched but couldn't parse the document.")
        else:
            print("   ⚠️  Skipping extraction - no confident extractor match")

    except Exception as e:
        print(f"   ERROR during extraction: {e}")
        import traceback

        traceback.print_exc()

    # Step 4: Recommendations
    print("\n4. RECOMMENDATIONS")
    print("-" * 40)

    if len(full_text) < 100:
        print("   • Document needs OCR - text layer is missing or very short")
        print("   • Consider using OCRmyPDF or Tesseract to add text layer")
    elif best_score < 0.3:
        print("   • Document type not recognized (IAA/Copart/Manheim)")
        print("   • May need to add new extractor patterns")
        print("   • Or document is a different format than expected")
    elif not result.invoice:
        print("   • Extractor matched but parsing failed")
        print("   • Check regex patterns in the extractor")
        print("   • Document format may differ from expected")
    else:
        print("   ✓ Extraction working - check which fields are empty and why")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_extraction_direct.py <path_to_pdf>")
        print("\nExample:")
        print("  python scripts/test_extraction_direct.py data/uploads/copart_invoice.pdf")

        # List available PDFs
        uploads_dir = "data/uploads"
        if os.path.exists(uploads_dir):
            pdfs = [f for f in os.listdir(uploads_dir) if f.endswith(".pdf")]
            if pdfs:
                print(f"\nAvailable PDFs in {uploads_dir}/:")
                for pdf in pdfs:
                    size = os.path.getsize(os.path.join(uploads_dir, pdf))
                    print(f"  - {pdf} ({size:,} bytes)")
        return

    pdf_path = sys.argv[1]
    test_extraction(pdf_path)


if __name__ == "__main__":
    main()
