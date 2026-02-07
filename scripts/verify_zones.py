#!/usr/bin/env python3
"""
Verify zone extraction works correctly with the determined boundaries.
"""

import pdfplumber

PDF_PATH = "/home/user/y7dispatch/tests/sample_docs/invoice.pdf"

# Zone boundaries based on analysis
ZONES = {
    'member': {'x0': 0, 'x1': 175, 'y0': 60, 'y1': 130},
    'pickup_address': {'x0': 175, 'x1': 360, 'y0': 60, 'y1': 130},
    'seller': {'x0': 360, 'x1': 612, 'y0': 60, 'y1': 130},
}

def extract_zone_text(page, zone):
    """Extract text from a specific zone."""
    bbox = (zone['x0'], zone['y0'], zone['x1'], zone['y1'])
    cropped = page.within_bbox(bbox)
    words = cropped.extract_words(x_tolerance=3, y_tolerance=3)

    # Sort by Y then X
    words_sorted = sorted(words, key=lambda w: (w['top'], w['x0']))

    # Group into lines
    lines = []
    current_line = []
    current_y = None

    for word in words_sorted:
        if current_y is None or abs(word['top'] - current_y) < 8:
            current_line.append(word['text'])
            current_y = word['top']
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word['text']]
            current_y = word['top']

    if current_line:
        lines.append(' '.join(current_line))

    return lines

def main():
    with pdfplumber.open(PDF_PATH) as pdf:
        page = pdf.pages[0]

        print("=" * 70)
        print("ZONE EXTRACTION VERIFICATION")
        print("=" * 70)

        for zone_name, zone_bbox in ZONES.items():
            print(f"\n{zone_name.upper()} ZONE:")
            print(f"  Bbox: x0={zone_bbox['x0']}, y0={zone_bbox['y0']}, x1={zone_bbox['x1']}, y1={zone_bbox['y1']}")
            print("  Extracted text:")

            lines = extract_zone_text(page, zone_bbox)
            for line in lines:
                print(f"    -> {line}")

        print("\n" + "=" * 70)
        print("PICKUP ADDRESS EXTRACTION (Key field)")
        print("=" * 70)

        # Extract just the pickup address zone
        pickup_lines = extract_zone_text(page, ZONES['pickup_address'])

        # Skip the header line
        address_lines = [line for line in pickup_lines if not line.startswith('PHYSICAL')]

        print(f"\n  Raw address lines: {address_lines}")

        if address_lines:
            # Parse address
            full_address = ' '.join(address_lines)
            print(f"  Combined address: {full_address}")

            # Try to parse city, state, zip from last line
            if len(address_lines) >= 2:
                street = address_lines[0]
                city_state_zip = address_lines[1]

                # Parse "RIVERVIEW FL 33578"
                parts = city_state_zip.rsplit(' ', 2)
                if len(parts) >= 3:
                    city = parts[0]
                    state = parts[1]
                    zipcode = parts[2]
                    print("\n  Parsed pickup location:")
                    print(f"    Street:  {street}")
                    print(f"    City:    {city}")
                    print(f"    State:   {state}")
                    print(f"    ZIP:     {zipcode}")

if __name__ == "__main__":
    main()
