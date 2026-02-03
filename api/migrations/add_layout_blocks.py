#!/usr/bin/env python3
"""
Migration: Add Layout Blocks and Field Evidence tables

Adds:
- layout_blocks table for spatial document structure
- field_evidence table for extraction provenance tracking

Run with: python -m api.migrations.add_layout_blocks
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from api.database import get_connection


def run_migration():
    """Run the migration to add layout blocks and field evidence tables."""
    print("Running migration: add_layout_blocks")

    with get_connection() as conn:
        # Create layout_blocks table
        print("  Creating layout_blocks table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS layout_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                block_id TEXT NOT NULL,
                page_num INTEGER NOT NULL DEFAULT 0,
                x0 REAL NOT NULL,
                y0 REAL NOT NULL,
                x1 REAL NOT NULL,
                y1 REAL NOT NULL,
                text TEXT,
                block_type TEXT DEFAULT 'data',
                label TEXT,
                text_source TEXT DEFAULT 'native' CHECK (text_source IN ('native', 'ocr', 'hybrid')),
                confidence REAL DEFAULT 1.0,
                element_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id),
                UNIQUE(document_id, block_id)
            )
        """)

        # Create indexes for layout_blocks
        print("  Creating indexes for layout_blocks...")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_layout_blocks_document
            ON layout_blocks(document_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_layout_blocks_label
            ON layout_blocks(label)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_layout_blocks_type
            ON layout_blocks(block_type)
        """)

        # Create field_evidence table
        print("  Creating field_evidence table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS field_evidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                field_key TEXT NOT NULL,
                block_id INTEGER,
                text_snippet TEXT,
                page_num INTEGER,
                bbox_json TEXT,
                rule_id TEXT,
                extraction_method TEXT,
                confidence REAL DEFAULT 1.0,
                value_source TEXT DEFAULT 'extracted',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES extraction_runs(id),
                FOREIGN KEY (block_id) REFERENCES layout_blocks(id)
            )
        """)

        # Create indexes for field_evidence
        print("  Creating indexes for field_evidence...")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_field_evidence_run
            ON field_evidence(run_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_field_evidence_field
            ON field_evidence(field_key)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_field_evidence_block
            ON field_evidence(block_id)
        """)

        conn.commit()
        print("Migration completed successfully!")


def check_migration():
    """Check if migration has been applied."""
    with get_connection() as conn:
        # Check if tables exist
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('layout_blocks', 'field_evidence')"
        ).fetchall()
        return len(tables) == 2


if __name__ == "__main__":
    if check_migration():
        print("Migration already applied (tables exist)")
    else:
        run_migration()
