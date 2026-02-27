"""Validation API — VIN decode + pickup address verification.

Endpoints:
  POST /api/runs/{run_id}/validate   — run validation (VIN + pickup)
  GET  /api/runs/{run_id}/validation — get cached validation result
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from api.database import get_connection
from api.services.vin_decoder import VINDecoder, init_vin_cache_table
from api.services.address_validator import PickupAddressValidator, init_zip_cache_table

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["Validation"])


def init_validation_schema():
    """Create validation tables."""
    init_vin_cache_table()
    init_zip_cache_table()
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS validation_results (
                run_id INTEGER PRIMARY KEY,
                vehicle_json TEXT,
                pickup_json TEXT,
                summary_json TEXT,
                validated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def _get_run_data(run_id: int) -> dict:
    """Get extraction outputs + auction type for a run."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT er.outputs_json, er.auction_type_id, at.code AS auction_type_code
               FROM extraction_runs er
               LEFT JOIN auction_types at ON at.id = er.auction_type_id
               WHERE er.id = ?""",
            (run_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Extraction run {run_id} not found")
        outputs = {}
        if row["outputs_json"]:
            try:
                outputs = json.loads(row["outputs_json"])
            except Exception:
                pass
        return {
            "outputs": outputs,
            "auction_type_code": row["auction_type_code"] or "UNKNOWN",
        }


def _build_summary(vehicle_result: dict, pickup_result: dict) -> dict:
    """Build summary counts from validation results."""
    all_fields = {}
    for k, v in vehicle_result.get("fields", {}).items():
        all_fields[f"vehicle_{k}"] = v.get("status", "unverified")
    for k, v in pickup_result.get("fields", {}).items():
        all_fields[k] = v.get("status", "unverified")

    verified = sum(1 for s in all_fields.values() if s == "verified")
    mismatch = sum(1 for s in all_fields.values() if s == "mismatch")
    unverified = sum(1 for s in all_fields.values() if s == "unverified")

    vehicle_ok = all(
        v.get("status") in ("verified", "unverified")
        for v in vehicle_result.get("fields", {}).values()
    )
    pickup_ok = all(
        v.get("status") in ("verified", "unverified")
        for v in pickup_result.get("fields", {}).values()
    )

    return {
        "vehicle_ok": vehicle_ok,
        "pickup_ok": pickup_ok,
        "total_verified": verified,
        "total_mismatch": mismatch,
        "total_unverified": unverified,
    }


@router.post("/{run_id}/validate")
async def validate_run(run_id: int):
    """Run VIN + pickup address validation for an extraction run.

    Always re-runs validation (overwrites previous result).
    """
    run_data = _get_run_data(run_id)
    outputs = run_data["outputs"]
    auction_type = run_data["auction_type_code"]

    # ── VIN validation ───────────────────────────────────────────
    vin = str(outputs.get("vehicle_vin") or "").strip()
    year = str(outputs.get("vehicle_year") or "").strip()
    make = str(outputs.get("vehicle_make") or "").strip()
    model = str(outputs.get("vehicle_model") or "").strip()

    decoder = VINDecoder()
    vehicle_result = decoder.validate_vehicle(vin, year, make, model)

    # ── Pickup validation ────────────────────────────────────────
    pickup_fields = {
        "pickup_name": outputs.get("pickup_name", ""),
        "pickup_address": outputs.get("pickup_address", ""),
        "pickup_city": outputs.get("pickup_city", ""),
        "pickup_state": outputs.get("pickup_state", ""),
        "pickup_zip": outputs.get("pickup_zip", ""),
    }

    addr_validator = PickupAddressValidator()
    pickup_result = addr_validator.validate(auction_type, pickup_fields)

    # ── Summary ──────────────────────────────────────────────────
    summary = _build_summary(vehicle_result, pickup_result)

    # ── Save to DB ───────────────────────────────────────────────
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO validation_results
               (run_id, vehicle_json, pickup_json, summary_json, validated_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (
                run_id,
                json.dumps(vehicle_result),
                json.dumps(pickup_result),
                json.dumps(summary),
            ),
        )
        conn.commit()

    return {
        "run_id": run_id,
        "vehicle": vehicle_result.get("fields", {}),
        "pickup": pickup_result.get("fields", {}),
        "summary": summary,
    }


@router.get("/{run_id}/validation")
async def get_validation(run_id: int):
    """Get cached validation result for a run. Returns 404 if not yet validated."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM validation_results WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="No validation result for this run")

    vehicle = json.loads(row["vehicle_json"]) if row["vehicle_json"] else {}
    pickup = json.loads(row["pickup_json"]) if row["pickup_json"] else {}
    summary = json.loads(row["summary_json"]) if row["summary_json"] else {}

    return {
        "run_id": run_id,
        "vehicle": vehicle.get("fields", {}),
        "pickup": pickup.get("fields", {}),
        "summary": summary,
        "validated_at": row["validated_at"],
    }
