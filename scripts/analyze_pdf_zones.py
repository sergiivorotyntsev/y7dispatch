#!/usr/bin/env python3
"""
Analyze Copart invoice PDF to determine exact zone boundaries for extraction.
Outputs page dimensions, text coordinates, and column boundaries.
"""

from collections import defaultdict

import pdfplumber

PDF_PATH = "/home/user/y7dispatch/tests/sample_docs/invoice.pdf"

def analyze_pdf():
    with pdfplumber.open(PDF_PATH) as pdf:
        page = pdf.pages[0]

        # 1. Page dimensions
        width = page.width
        height = page.height
        print("=" * 80)
        print("1. PAGE DIMENSIONS")
        print("=" * 80)
        print(f"   Width:  {width:.2f} points")
        print(f"   Height: {height:.2f} points")
        print(f"   Aspect: {width/height:.3f}")
        print()

        # 2. Extract all characters with coordinates
        chars = page.chars
        print("=" * 80)
        print("2. CHARACTER-LEVEL EXTRACTION (first 40% of page height)")
        print("=" * 80)

        # Filter to header area (first 40% of page)
        header_cutoff = height * 0.40
        header_chars = [c for c in chars if c['top'] < header_cutoff]

        # Group characters into words/lines by proximity
        # Sort by y position then x position
        header_chars_sorted = sorted(header_chars, key=lambda c: (round(c['top'], 0), c['x0']))

        # Group by approximate line (within 3 points of y)
        lines = defaultdict(list)
        for c in header_chars_sorted:
            line_key = round(c['top'] / 3) * 3  # Group within 3 points
            lines[line_key].append(c)

        print(f"\n   Total characters in header area: {len(header_chars)}")
        print(f"   Header cutoff Y: {header_cutoff:.2f}")
        print()

        # 3. Find key column headers
        print("=" * 80)
        print("3. KEY COLUMN HEADERS - Finding exact positions")
        print("=" * 80)

        # Extract words with their bounding boxes
        words = page.extract_words(keep_blank_chars=True, x_tolerance=3, y_tolerance=3)

        # Find key headers
        key_headers = ["MEMBER:", "PHYSICAL ADDRESS OF LOT:", "SELLER:"]
        header_positions = {}

        for word in words:
            text = word['text'].strip()
            if text in key_headers or any(h.startswith(text) for h in key_headers):
                header_positions[text] = {
                    'x0': word['x0'],
                    'x1': word['x1'],
                    'top': word['top'],
                    'bottom': word['bottom'],
                    'text': text
                }

        # Also search for partial matches
        for word in words:
            text = word['text'].strip()
            if 'MEMBER' in text and 'MEMBER' not in str(header_positions):
                header_positions[f"MEMBER_match: {text}"] = {
                    'x0': word['x0'],
                    'x1': word['x1'],
                    'top': word['top'],
                    'bottom': word['bottom'],
                    'text': text
                }
            if 'PHYSICAL' in text:
                header_positions[f"PHYSICAL_match: {text}"] = {
                    'x0': word['x0'],
                    'x1': word['x1'],
                    'top': word['top'],
                    'bottom': word['bottom'],
                    'text': text
                }
            if 'SELLER' in text:
                header_positions[f"SELLER_match: {text}"] = {
                    'x0': word['x0'],
                    'x1': word['x1'],
                    'top': word['top'],
                    'bottom': word['bottom'],
                    'text': text
                }

        print("\n   Found header positions:")
        for name, pos in sorted(header_positions.items(), key=lambda x: x[1]['x0']):
            pct_x0 = (pos['x0'] / width) * 100
            pct_x1 = (pos['x1'] / width) * 100
            print(f"   {name}")
            print(f"      X: {pos['x0']:.1f} - {pos['x1']:.1f} pts  ({pct_x0:.1f}% - {pct_x1:.1f}%)")
            print(f"      Y: {pos['top']:.1f} - {pos['bottom']:.1f} pts")
        print()

        # 4. Analyze all text in the header row area
        print("=" * 80)
        print("4. TEXT IN HEADER ROW AREA (Y: 60-150 pts)")
        print("=" * 80)

        header_row_words = [w for w in words if 60 < w['top'] < 150]
        header_row_words_sorted = sorted(header_row_words, key=lambda w: (round(w['top']/5)*5, w['x0']))

        current_y = None
        for word in header_row_words_sorted:
            y_bucket = round(word['top']/5)*5
            if current_y != y_bucket:
                current_y = y_bucket
                print(f"\n   --- Line at Y ~ {y_bucket} ---")
            pct = (word['x0'] / width) * 100
            print(f"   X:{word['x0']:6.1f} ({pct:5.1f}%) | \"{word['text']}\"")
        print()

        # 5. Determine column boundaries
        print("=" * 80)
        print("5. RECOMMENDED ZONE BOUNDARIES")
        print("=" * 80)

        # Find the actual positions of key elements
        member_x = None
        physical_x = None
        seller_x = None

        for word in words:
            text = word['text'].strip()
            if text.startswith('MEMBER:'):
                member_x = word['x0']
            if text.startswith('PHYSICAL'):
                physical_x = word['x0']
            if text == 'SELLER:':
                seller_x = word['x0']

        print("\n   Column header X positions:")
        print(f"      MEMBER:                starts at X = {member_x}")
        print(f"      PHYSICAL ADDRESS...:   starts at X = {physical_x}")
        print(f"      SELLER:                starts at X = {seller_x}")

        if member_x and physical_x and seller_x:
            # Calculate boundaries (midpoints between columns)
            left_boundary = (member_x + physical_x) / 2
            right_boundary = (physical_x + seller_x) / 2

            print("\n   Suggested column boundaries:")
            print(f"      Left column (MEMBER):     X = 0 to {left_boundary:.1f} pts")
            print(f"      Center column (ADDRESS):  X = {left_boundary:.1f} to {right_boundary:.1f} pts")
            print(f"      Right column (SELLER):    X = {right_boundary:.1f} to {width:.1f} pts")

            print(f"\n   As percentages of page width ({width:.1f} pts):")
            print(f"      Left column:    0% to {(left_boundary/width)*100:.1f}%")
            print(f"      Center column:  {(left_boundary/width)*100:.1f}% to {(right_boundary/width)*100:.1f}%")
            print(f"      Right column:   {(right_boundary/width)*100:.1f}% to 100%")

        # 6. Detailed character dump for the three-column area
        print()
        print("=" * 80)
        print("6. DETAILED TEXT BY ZONE (Y: 60-150, three columns)")
        print("=" * 80)

        # Get all words in the zone
        zone_words = [w for w in words if 60 < w['top'] < 150]

        if member_x and physical_x and seller_x:
            left_bound = (member_x + physical_x) / 2
            right_bound = (physical_x + seller_x) / 2

            left_col = [w for w in zone_words if w['x0'] < left_bound]
            center_col = [w for w in zone_words if left_bound <= w['x0'] < right_bound]
            right_col = [w for w in zone_words if w['x0'] >= right_bound]

            print("\n   LEFT COLUMN (MEMBER/Buyer):")
            for w in sorted(left_col, key=lambda x: (x['top'], x['x0'])):
                print(f"      Y:{w['top']:6.1f} X:{w['x0']:6.1f} | \"{w['text']}\"")

            print("\n   CENTER COLUMN (PHYSICAL ADDRESS):")
            for w in sorted(center_col, key=lambda x: (x['top'], x['x0'])):
                print(f"      Y:{w['top']:6.1f} X:{w['x0']:6.1f} | \"{w['text']}\"")

            print("\n   RIGHT COLUMN (SELLER):")
            for w in sorted(right_col, key=lambda x: (x['top'], x['x0'])):
                print(f"      Y:{w['top']:6.1f} X:{w['x0']:6.1f} | \"{w['text']}\"")

        # 7. Final recommendations
        print()
        print("=" * 80)
        print("7. FINAL ZONE CONFIGURATION RECOMMENDATIONS")
        print("=" * 80)

        if member_x and physical_x and seller_x:
            # Add some padding to the boundaries
            left_bound = physical_x - 5  # Just before PHYSICAL starts
            right_bound = seller_x - 5   # Just before SELLER starts

            print(f"""
   For zone-based extraction, use these boundaries:

   Page dimensions: {width:.1f} x {height:.1f} points

   MEMBER/BUYER ZONE (Left Column):
      X: 0 to {left_bound:.1f} pts (0% to {(left_bound/width)*100:.1f}%)
      Y: 60 to 150 pts (header section)

   PICKUP ADDRESS ZONE (Center Column):
      X: {left_bound:.1f} to {right_bound:.1f} pts ({(left_bound/width)*100:.1f}% to {(right_bound/width)*100:.1f}%)
      Y: 60 to 150 pts (header section)

   SELLER ZONE (Right Column):
      X: {right_bound:.1f} to {width:.1f} pts ({(right_bound/width)*100:.1f}% to 100%)
      Y: 60 to 150 pts (header section)

   Python dict format for extractors/copart.py:

   ZONES = {{
       'member': {{'x0': 0, 'x1': {left_bound:.1f}, 'y0': 60, 'y1': 150}},
       'pickup_address': {{'x0': {left_bound:.1f}, 'x1': {right_bound:.1f}, 'y0': 60, 'y1': 150}},
       'seller': {{'x0': {right_bound:.1f}, 'x1': {width:.1f}, 'y0': 60, 'y1': 150}},
   }}

   As percentages (more portable across different PDF sizes):

   ZONES_PCT = {{
       'member': {{'x0': 0, 'x1': {(left_bound/width)*100:.1f}, 'y0': {(60/height)*100:.1f}, 'y1': {(150/height)*100:.1f}}},
       'pickup_address': {{'x0': {(left_bound/width)*100:.1f}, 'x1': {(right_bound/width)*100:.1f}, 'y0': {(60/height)*100:.1f}, 'y1': {(150/height)*100:.1f}}},
       'seller': {{'x0': {(right_bound/width)*100:.1f}, 'x1': 100, 'y0': {(60/height)*100:.1f}, 'y1': {(150/height)*100:.1f}}},
   }}
""")

if __name__ == "__main__":
    analyze_pdf()
