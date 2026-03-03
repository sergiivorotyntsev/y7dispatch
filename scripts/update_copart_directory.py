#!/usr/bin/env python3
"""
Update Copart locations in auction_directory.py from a CSV file.

CSV format (header row required):
  name,phone,address,city,state,zip

Example:
  name,phone,address,city,state,zip
  Copart Clearwater,(727) 535-1559,5800 Ulmerton Rd,Clearwater,FL,33760

Usage:
  python scripts/update_copart_directory.py locations.csv [--dry-run]
"""

import csv
import sys
from pathlib import Path


def load_csv(csv_path: str) -> list[dict]:
    """Load locations from CSV file."""
    locations = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"name", "phone", "address", "city", "state", "zip"}
        if not required.issubset(set(reader.fieldnames or [])):
            print(f"ERROR: CSV must have columns: {', '.join(sorted(required))}")
            print(f"Found: {reader.fieldnames}")
            sys.exit(1)

        for row in reader:
            name = row["name"].strip()
            if not name:
                continue
            locations.append({
                "name": name,
                "phone": row["phone"].strip(),
                "address": row["address"].strip(),
                "city": row["city"].strip(),
                "state": row["state"].strip().upper(),
                "zip": row["zip"].strip(),
            })
    return locations


def generate_dict_code(locations: list[dict]) -> str:
    """Generate Python dict literal from locations list."""
    lines = []
    for loc in sorted(locations, key=lambda x: (x["state"], x["city"], x["name"])):
        lines.append(
            f'    "{loc["name"]}": '
            f'{{"phone": "{loc["phone"]}", '
            f'"address": "{loc["address"]}", '
            f'"city": "{loc["city"]}", '
            f'"state": "{loc["state"]}", '
            f'"zip": "{loc["zip"]}"}},')
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    csv_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if not Path(csv_path).exists():
        print(f"ERROR: File not found: {csv_path}")
        sys.exit(1)

    locations = load_csv(csv_path)
    print(f"Loaded {len(locations)} locations from {csv_path}")

    if dry_run:
        print("\n--- DRY RUN: Generated code ---")
        print("COPART_LOCATIONS = {")
        print(generate_dict_code(locations))
        print("}")
        return

    # Read existing directory and merge
    dir_path = Path(__file__).parent.parent / "services" / "auction_directory.py"
    existing_code = dir_path.read_text(encoding="utf-8")

    # Load existing locations for merge
    existing_names = set()
    import re
    for m in re.finditer(r'"(Copart [^"]+)":\s*\{', existing_code):
        existing_names.add(m.group(1))

    new_count = 0
    updated_count = 0
    for loc in locations:
        if loc["name"] in existing_names:
            updated_count += 1
        else:
            new_count += 1

    print(f"New locations: {new_count}")
    print(f"Updates to existing: {updated_count}")
    print(f"\nTo apply, manually update COPART_LOCATIONS in {dir_path}")
    print("Generated dict code:")
    print("\nCOPART_LOCATIONS = {")
    print(generate_dict_code(locations))
    print("}")


if __name__ == "__main__":
    main()
