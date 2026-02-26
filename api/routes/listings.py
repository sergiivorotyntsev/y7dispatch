"""
Listings API Routes

Load ID generation and listing management for Central Dispatch.
"""

import re
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


def _fix_load_ids_with_spaces():
    """One-time migration: fix Load IDs with non-alphanumeric chars (spaces, dashes from model names like 'C 300' or 'E-Class')."""
    import json

    with get_connection() as conn:
        # Find load_ids with any non-alphanumeric characters
        all_rows = conn.execute(
            "SELECT id, load_id, make, model FROM load_ids"
        ).fetchall()
        bad_rows = [r for r in all_rows if re.search(r'[^A-Z0-9]', r["load_id"])]

        if not bad_rows:
            return

        for row in bad_rows:
            old_id = row["load_id"]
            new_id = re.sub(r'[^A-Z0-9]', '', old_id)
            # Also clean the base_id stored for this row
            old_base = conn.execute(
                "SELECT base_id FROM load_ids WHERE id = ?", (row["id"],)
            ).fetchone()
            new_base = re.sub(r'[^A-Z0-9]', '', old_base["base_id"]) if old_base else new_id

            try:
                conn.execute(
                    "UPDATE load_ids SET load_id = ?, base_id = ? WHERE id = ?",
                    (new_id, new_base, row["id"]),
                )
            except sqlite3.IntegrityError:
                # Cleaned ID already exists — append next available sequence
                for seq in range(2, 20):
                    try:
                        new_id_seq = f"{new_id}{seq}"
                        conn.execute(
                            "UPDATE load_ids SET load_id = ?, base_id = ?, sequence = ? WHERE id = ?",
                            (new_id_seq, new_base, seq, row["id"]),
                        )
                        new_id = new_id_seq
                        break
                    except sqlite3.IntegrityError:
                        continue
                else:
                    continue

            # Also fix in extraction_runs outputs_json
            runs = conn.execute(
                "SELECT id, outputs_json FROM extraction_runs WHERE outputs_json LIKE ?",
                (f'%{old_id}%',),
            ).fetchall()
            for run in runs:
                try:
                    outputs = json.loads(run["outputs_json"])
                    if outputs.get("load_id") == old_id:
                        outputs["load_id"] = new_id
                        conn.execute(
                            "UPDATE extraction_runs SET outputs_json = ? WHERE id = ?",
                            (json.dumps(outputs), run["id"]),
                        )
                except (json.JSONDecodeError, TypeError):
                    continue

        conn.commit()


# Initialize on import
init_load_ids_schema()
_fix_load_ids_with_spaces()


# =============================================================================
# REUSABLE LOAD ID GENERATOR
# =============================================================================

def create_load_id(make: str, model: str) -> tuple[str, int] | None:
    """
    Generate a unique Load ID for today and persist it.

    Format: M(no leading zero) + DD + first3Make(upper) + first2Model(upper) + sequence
    Example: 216TOYPR1 (Feb 16, Toyota Prius, first of day)
    Subsequent: 216TOYPR2, 216TOYPR3, etc.

    Returns (load_id, sequence) tuple, or None if make/model are empty.
    """
    if not make or not model:
        return None

    now = datetime.now()
    month = str(now.month)
    day = now.strftime("%d")

    make_part = re.sub(r'[^A-Z0-9]', '', make.strip().upper())[:3]
    model_part = re.sub(r'[^A-Z0-9]', '', model.strip().upper())[:2]
    base_id = f"{month}{day}{make_part}{model_part}"
    today_str = now.strftime("%Y-%m-%d")

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT load_id, sequence FROM load_ids WHERE base_id = ? AND created_date = ?",
            (base_id, today_str)
        ).fetchall()

        if not rows:
            sequence = 1
        else:
            max_seq = max(r["sequence"] if isinstance(r, dict) else r[1] for r in rows)
            sequence = max_seq + 1
        load_id = f"{base_id}{sequence}"

        try:
            conn.execute(
                "INSERT INTO load_ids (load_id, base_id, make, model, sequence, created_date) VALUES (?, ?, ?, ?, ?, ?)",
                (load_id, base_id, make.strip(), model.strip(), sequence, today_str)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            sequence += 1
            load_id = f"{base_id}{sequence}"
            conn.execute(
                "INSERT INTO load_ids (load_id, base_id, make, model, sequence, created_date) VALUES (?, ?, ?, ?, ?, ?)",
                (load_id, base_id, make.strip(), model.strip(), sequence, today_str)
            )
            conn.commit()

    return (load_id, sequence)


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
    Example: 216TOYPR1 (Feb 16, Toyota Prius, first of day)
    Subsequent: 216TOYPR2, 216TOYPR3, etc.
    """
    result = create_load_id(make, model)
    if not result:
        raise HTTPException(status_code=400, detail="Make and model are required")

    load_id, sequence = result
    return LoadIdResponse(
        load_id=load_id,
        make=make.strip(),
        model=model.strip(),
        sequence=sequence,
    )


@router.post("/backfill-load-ids")
async def backfill_load_ids():
    """
    Backfill load_id for existing extraction runs that have make+model but no load_id.
    Safe to run multiple times — skips runs that already have load_id.
    """
    import json

    updated = 0
    skipped = 0

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, outputs_json FROM extraction_runs
            WHERE outputs_json IS NOT NULL
              AND status NOT IN ('failed', 'cancelled')
        """).fetchall()

    for row in rows:
        try:
            outputs = json.loads(row["outputs_json"]) if row["outputs_json"] else {}
        except (json.JSONDecodeError, TypeError):
            continue

        if outputs.get("load_id"):
            skipped += 1
            continue

        make = outputs.get("vehicle_make")
        model = outputs.get("vehicle_model")
        if not make or not model:
            skipped += 1
            continue

        result = create_load_id(make, model)
        if result:
            outputs["load_id"] = result[0]
            with get_connection() as conn:
                conn.execute(
                    "UPDATE extraction_runs SET outputs_json = ? WHERE id = ?",
                    (json.dumps(outputs), row["id"]),
                )
                conn.commit()
            updated += 1

    return {"updated": updated, "skipped": skipped, "total_checked": len(rows)}


class RecalcLoadIdResponse(BaseModel):
    run_id: int
    old_load_id: str | None
    new_load_id: str
    make: str
    model: str
    sequence: int


@router.post("/recalculate-load-id/{run_id}", response_model=RecalcLoadIdResponse)
async def recalculate_load_id(run_id: int):
    """
    Recalculate Load ID for a specific extraction run.

    Use when make/model has been corrected after initial Load ID generation.
    Removes old Load ID from registry and generates a fresh one.
    """
    import json

    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, outputs_json FROM extraction_runs WHERE id = ?", (run_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Extraction run {run_id} not found")

    try:
        outputs = json.loads(row["outputs_json"]) if row["outputs_json"] else {}
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="Could not parse outputs_json")

    make = outputs.get("vehicle_make", "")
    model = outputs.get("vehicle_model", "")
    if not make or not model:
        raise HTTPException(
            status_code=400,
            detail="Extraction run missing vehicle_make or vehicle_model",
        )

    old_load_id = outputs.get("load_id")

    # Remove old load_id from registry so it can be reused
    if old_load_id:
        with get_connection() as conn:
            conn.execute("DELETE FROM load_ids WHERE load_id = ?", (old_load_id,))
            conn.commit()

    # Generate fresh load_id
    result = create_load_id(make, model)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to generate Load ID")

    new_load_id, sequence = result

    # Update extraction run
    outputs["load_id"] = new_load_id
    with get_connection() as conn:
        conn.execute(
            "UPDATE extraction_runs SET outputs_json = ? WHERE id = ?",
            (json.dumps(outputs), run_id),
        )
        conn.commit()

    return RecalcLoadIdResponse(
        run_id=run_id,
        old_load_id=old_load_id,
        new_load_id=new_load_id,
        make=make,
        model=model,
        sequence=sequence,
    )
