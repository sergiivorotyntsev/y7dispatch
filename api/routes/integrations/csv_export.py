"""
CSV Export Integration

Endpoints for exporting data as CSV.
"""

import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from api.database import get_connection
from api.routes.integrations.utils import log_integration_action

router = APIRouter(prefix="/extractions", tags=["Export"])


@router.get("/export/csv")
async def export_extractions_csv(
    status: Optional[str] = Query(None),
    auction_type_id: Optional[str] = Query(None),  # Accept string, convert manually
    source: Optional[str] = Query(None),
    limit: int = Query(1000, le=10000),
    offset: int = Query(0, ge=0),
):
    """
    Export extraction runs as CSV.

    Includes all fields and review corrections.
    """
    # Convert auction_type_id from string to int (handles empty string from frontend)
    auction_type_id_int = None
    if auction_type_id and auction_type_id.strip():
        try:
            auction_type_id_int = int(auction_type_id)
        except ValueError:
            pass

    sql = """
        SELECT
            e.id as run_id,
            e.uuid,
            e.document_id,
            d.filename as document_filename,
            d.source as document_source,
            e.auction_type_id,
            at.code as auction_type_code,
            at.name as auction_type_name,
            e.status,
            e.extraction_score,
            e.extractor_kind,
            e.created_at,
            e.completed_at
        FROM extraction_runs e
        LEFT JOIN documents d ON e.document_id = d.id
        LEFT JOIN auction_types at ON e.auction_type_id = at.id
        WHERE 1=1
    """
    params = []

    if status and status.strip():
        sql += " AND e.status = ?"
        params.append(status)
    if auction_type_id_int:
        sql += " AND e.auction_type_id = ?"
        params.append(auction_type_id_int)
    if source and source.strip():
        sql += " AND d.source = ?"
        params.append(source)

    sql += " ORDER BY e.created_at DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

        run_ids = [row["run_id"] for row in rows]
        review_items = {}
        if run_ids:
            placeholders = ",".join("?" * len(run_ids))
            items_sql = f"""
                SELECT run_id, source_key, predicted_value, corrected_value
                FROM review_items
                WHERE run_id IN ({placeholders})
            """
            items = conn.execute(items_sql, run_ids).fetchall()
            for item in items:
                key = (item["run_id"], item["source_key"])
                review_items[key] = item["corrected_value"] or item["predicted_value"]

    all_keys = set()
    for row in rows:
        for key in review_items:
            if key[0] == row["run_id"]:
                all_keys.add(key[1])
    all_keys = sorted(all_keys)

    output = io.StringIO()
    writer = csv.writer(output)

    header = [
        "run_id",
        "uuid",
        "document_id",
        "document_filename",
        "document_source",
        "auction_type_code",
        "auction_type_name",
        "status",
        "extraction_score",
        "extractor_kind",
        "created_at",
        "completed_at",
    ] + all_keys
    writer.writerow(header)

    for row in rows:
        row_data = [
            row["run_id"],
            row["uuid"],
            row["document_id"],
            row["document_filename"],
            row["document_source"],
            row["auction_type_code"],
            row["auction_type_name"],
            row["status"],
            row["extraction_score"],
            row["extractor_kind"],
            row["created_at"],
            row["completed_at"],
        ]
        for key in all_keys:
            row_data.append(review_items.get((row["run_id"], key), ""))
        writer.writerow(row_data)

    log_integration_action("csv_export", "extractions", "success", details={"rows": len(rows)})

    filename = f"extractions_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
