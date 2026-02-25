"""
Fill missing ZIP3 coordinates in _ZIP3_COORDS.

Reads current dict from distance_service.py, fills gaps in 005-999 range
using nearest-neighbor interpolation with state centroid fallback.

Output: Python dict literal ready to paste into distance_service.py.
"""

import ast
import re
import sys
from pathlib import Path

# State centroids (approximate geographic center)
STATE_CENTROIDS = {
    "PR": (18.2, -66.5),
    "VI": (18.3, -64.9),
    "CT": (41.6, -72.7),
    "MA": (42.4, -71.8),
    "ME": (45.3, -69.0),
    "NH": (43.2, -71.6),
    "NJ": (40.1, -74.4),
    "NY": (43.0, -75.5),
    "PA": (41.2, -77.2),
    "RI": (41.7, -71.5),
    "VT": (44.0, -72.7),
    "DC": (38.9, -77.0),
    "DE": (39.2, -75.5),
    "MD": (39.0, -76.6),
    "VA": (37.4, -79.5),
    "WV": (38.6, -80.5),
    "NC": (35.8, -79.0),
    "SC": (34.0, -81.0),
    "GA": (32.7, -83.5),
    "FL": (28.1, -81.6),
    "AL": (32.3, -86.9),
    "MS": (32.4, -89.7),
    "TN": (35.5, -86.6),
    "KY": (37.8, -84.3),
    "OH": (40.4, -82.8),
    "IN": (40.3, -86.1),
    "MI": (44.3, -84.5),
    "IA": (42.0, -93.2),
    "WI": (43.8, -89.4),
    "MN": (46.7, -94.7),
    "SD": (43.9, -99.9),
    "ND": (47.5, -100.5),
    "MT": (46.8, -110.4),
    "IL": (40.6, -89.3),
    "MO": (38.6, -92.2),
    "KS": (38.5, -98.8),
    "NE": (41.1, -98.3),
    "LA": (30.9, -92.3),
    "AR": (34.7, -92.4),
    "OK": (35.0, -97.1),
    "TX": (31.0, -100.0),
    "CO": (39.5, -105.8),
    "WY": (43.0, -107.6),
    "ID": (44.1, -114.7),
    "UT": (39.3, -111.1),
    "AZ": (34.0, -111.1),
    "NM": (34.5, -105.9),
    "NV": (38.8, -116.4),
    "CA": (36.8, -119.4),
    "HI": (21.3, -157.8),
    "OR": (43.8, -120.6),
    "WA": (47.8, -120.7),
    "AK": (64.2, -152.5),
}

# ZIP3 range → state mapping
ZIP3_STATE_RANGES = [
    (5, 9, "PR"),
    (10, 27, "MA"),
    (28, 29, "RI"),
    (30, 34, "NH"),
    (35, 39, "VT"),
    (40, 49, "MA"),  # CT overlap, but MA centroid close enough
    (50, 54, "MA"),
    (55, 56, "CT"),
    (57, 59, "CT"),
    (60, 69, "CT"),
    (70, 89, "NJ"),
    (90, 99, "MILITARY"),  # APO/FPO — skip
    (100, 149, "NY"),
    (150, 196, "PA"),
    (197, 199, "DE"),
    (200, 205, "DC"),
    (206, 219, "MD"),
    (220, 246, "VA"),
    (247, 253, "WV"),
    (254, 268, "WV"),
    (270, 289, "NC"),
    (290, 299, "SC"),
    (300, 319, "GA"),
    (320, 339, "FL"),
    (340, 342, "MILITARY"),  # APO — skip
    (343, 349, "FL"),
    (350, 369, "AL"),
    (370, 385, "TN"),
    (386, 397, "MS"),
    (398, 399, "GA"),
    (400, 427, "KY"),
    (430, 458, "OH"),
    (460, 479, "IN"),
    (480, 499, "MI"),
    (500, 528, "IA"),
    (530, 549, "WI"),
    (550, 567, "MN"),
    (570, 577, "SD"),
    (580, 588, "ND"),
    (590, 599, "MT"),
    (600, 629, "IL"),
    (630, 658, "MO"),
    (660, 679, "KS"),
    (680, 693, "NE"),
    (700, 714, "LA"),
    (716, 729, "AR"),
    (730, 749, "OK"),
    (750, 799, "TX"),
    (800, 816, "CO"),
    (820, 831, "WY"),
    (832, 838, "ID"),
    (840, 847, "UT"),
    (850, 865, "AZ"),
    (870, 884, "NM"),
    (889, 898, "NV"),
    (900, 935, "CA"),
    (936, 966, "CA"),  # includes some Pacific territories
    (967, 968, "HI"),
    (970, 979, "OR"),
    (980, 994, "WA"),
    (995, 999, "AK"),
]


def get_state_for_zip3(zip3_int: int) -> str:
    """Get state code for a ZIP3 integer."""
    for start, end, state in ZIP3_STATE_RANGES:
        if start <= zip3_int <= end:
            return state
    return "UNKNOWN"


def main():
    # Read current _ZIP3_COORDS from distance_service.py
    svc_path = Path(__file__).parent.parent / "services" / "distance_service.py"
    content = svc_path.read_text(encoding="utf-8")

    match = re.search(r"_ZIP3_COORDS\s*=\s*\{", content)
    if not match:
        print("ERROR: _ZIP3_COORDS not found in distance_service.py")
        sys.exit(1)

    # Find matching closing brace
    start = match.end() - 1
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
        if depth == 0:
            end = i + 1
            break

    dict_str = content[start:end]
    existing = ast.literal_eval(dict_str)
    print(f"Existing keys: {len(existing)}")

    # Find missing ZIP3s in 005-999
    all_zip3 = set(f"{i:03d}" for i in range(5, 1000))
    present = set(existing.keys())
    missing = sorted(all_zip3 - present)
    print(f"Missing keys: {len(missing)}")

    # Fill missing keys
    new_entries = {}
    skipped_military = 0

    for zip3_str in missing:
        zip3_int = int(zip3_str)
        state = get_state_for_zip3(zip3_int)

        if state == "MILITARY":
            skipped_military += 1
            continue

        if state == "UNKNOWN":
            # Try nearest neighbor anyway
            pass

        # Strategy 1: find nearest existing key in SAME state (±1, ±2, ... up to ±10)
        found_neighbor = False
        for delta in range(1, 11):
            for neighbor_int in [zip3_int - delta, zip3_int + delta]:
                neighbor_str = f"{neighbor_int:03d}"
                if neighbor_str in existing:
                    neighbor_state = get_state_for_zip3(neighbor_int)
                    if neighbor_state != state and state != "UNKNOWN":
                        continue  # Skip cross-state neighbors
                    lat, lon = existing[neighbor_str]
                    # Small offset to differentiate: shift lat by ±0.3 per delta
                    offset = 0.3 * (1 if zip3_int > neighbor_int else -1)
                    new_entries[zip3_str] = (round(lat + offset, 1), round(lon, 1))
                    found_neighbor = True
                    break
            if found_neighbor:
                break

        if not found_neighbor:
            # Strategy 2: use state centroid
            if state in STATE_CENTROIDS:
                new_entries[zip3_str] = STATE_CENTROIDS[state]
            else:
                # Last resort: geographic center of US
                new_entries[zip3_str] = (39.8, -98.6)
                print(f"  WARNING: no neighbor or centroid for {zip3_str} (state={state})")

    print(f"New entries: {len(new_entries)}")
    print(f"Skipped (military): {skipped_military}")
    print(f"Total after merge: {len(existing) + len(new_entries)}")
    coverage = (len(existing) + len(new_entries)) / 995 * 100
    print(f"Coverage: {coverage:.1f}%")

    # Show first 10 new entries
    print("\nFirst 10 new entries:")
    for i, (k, v) in enumerate(sorted(new_entries.items())):
        if i >= 10:
            break
        state = get_state_for_zip3(int(k))
        print(f"  \"{k}\": {v},  # {state}")

    # Write the merged dict to stdout as Python literal
    merged = {**existing, **new_entries}
    output_path = Path(__file__).parent / "zip3_fill_output.py"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Generated by fill_zip3.py — paste into distance_service.py\n")
        f.write(f"# Existing: {len(existing)}, Added: {len(new_entries)}, Total: {len(merged)}\n\n")
        f.write("_ZIP3_COORDS = {\n")
        for key in sorted(merged.keys()):
            lat, lon = merged[key]
            state = get_state_for_zip3(int(key))
            f.write(f'    "{key}": ({lat}, {lon}),  # {state}\n')
        f.write("}\n")

    print(f"\nFull dict written to: {output_path}")
    print("Review the file, then paste into distance_service.py")


if __name__ == "__main__":
    main()
