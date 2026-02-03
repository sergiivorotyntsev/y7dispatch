#!/usr/bin/env python3
"""
Database migration: Add metrics_json and field_sources_json columns to extraction_runs.

Run this migration to add observability fields for extraction diagnostics.

Usage:
    python api/migrations/add_extraction_metrics.py
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from api.database import get_connection


def check_column_exists(conn, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def migrate():
    """Run the migration."""
    print("Running migration: add_extraction_metrics")
    print("-" * 50)

    with get_connection() as conn:
        # Check and add metrics_json column
        if not check_column_exists(conn, "extraction_runs", "metrics_json"):
            print("Adding metrics_json column to extraction_runs...")
            conn.execute("ALTER TABLE extraction_runs ADD COLUMN metrics_json TEXT")
            print("  ✓ metrics_json column added")
        else:
            print("  • metrics_json column already exists")

        # Check and add field_sources_json column
        if not check_column_exists(conn, "extraction_runs", "field_sources_json"):
            print("Adding field_sources_json column to extraction_runs...")
            conn.execute("ALTER TABLE extraction_runs ADD COLUMN field_sources_json TEXT")
            print("  ✓ field_sources_json column added")
        else:
            print("  • field_sources_json column already exists")

        conn.commit()

    print("-" * 50)
    print("Migration completed successfully!")


if __name__ == "__main__":
    migrate()
