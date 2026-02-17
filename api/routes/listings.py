"""
Listings API Routes

Load ID generation and listing management for Central Dispatch.
"""

import sqlite3
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.database import get_connection

router = APIRouter(prefix="/api/listings", tags=["Listings"])


# =============================================================================
# SCHEMA
# =============================================================================

def init_load_ids_schema():
    """Ensure load_ids table exists."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS load_ids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                load_id TEXT NOT NULL UNIQUE,
                base_id TEXT NOT NULL,
                make TEXT NOT NULL,
                model TEXT NOT NULL,
                sequence INTEGER NOT NULL DEFAULT 1,
                created_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_load_ids_base_date
            ON load_ids(base_id, created_date)
        """)
        conn.commit()


# Initialize on import
init_load_ids_schema()


# =============================================================================
# MODELS
# =============================================================================

class LoadIdResponse(BaseModel):
    load_id: str
    make: str
    model: str
    sequence: int


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/generate-load-id", response_model=LoadIdResponse)
async def generate_load_id(
    make: str = Query(..., min_length=1, description="Vehicle make (e.g., Toyota)"),
    model: str = Query(..., min_length=1, description="Vehicle model (e.g., Prius)"),
):
    """
    Generate a unique Load ID for today.

    Format: M(no leading zero) + DD + first3Make(upper) + first2Model(upper) + sequence
    Example: 216TOYPR (Feb 16, Toyota Prius, first of day)
    Duplicates: 216TOYPR2, 216TOYPR3, etc.
    """
    now = datetime.now()
    month = str(now.month)  # No leading zero
    day = now.strftime("%d")  # With leading zero

    make_part = make.strip().upper()[:3]
    model_part = model.strip().upper()[:2]
    base_id = f"{month}{day}{make_part}{model_part}"

    today_str = now.strftime("%Y-%m-%d")

    with get_connection() as conn:
        # Find existing IDs for this base today
        rows = conn.execute(
            "SELECT load_id, sequence FROM load_ids WHERE base_id = ? AND created_date = ?",
            (base_id, today_str)
        ).fetchall()

        if not rows:
            load_id = base_id
            sequence = 1
        else:
            max_seq = max(r["sequence"] if isinstance(r, dict) else r[1] for r in rows)
            sequence = max_seq + 1
            load_id = f"{base_id}{sequence}"

        # Insert with retry on collision
        try:
            conn.execute(
                "INSERT INTO load_ids (load_id, base_id, make, model, sequence, created_date) VALUES (?, ?, ?, ?, ?, ?)",
                (load_id, base_id, make.strip(), model.strip(), sequence, today_str)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Race condition: another request inserted the same ID
            # Retry with incremented sequence
            sequence += 1
            load_id = f"{base_id}{sequence}"
            conn.execute(
                "INSERT INTO load_ids (load_id, base_id, make, model, sequence, created_date) VALUES (?, ?, ?, ?, ?, ?)",
                (load_id, base_id, make.strip(), model.strip(), sequence, today_str)
            )
            conn.commit()

    return LoadIdResponse(
        load_id=load_id,
        make=make.strip(),
        model=model.strip(),
        sequence=sequence,
    )
