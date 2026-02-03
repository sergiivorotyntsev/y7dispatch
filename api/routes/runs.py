"""Run history and logs endpoints."""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.database import RunHistory, RunLogs

router = APIRouter()


# ----- Pydantic Models -----


class RunResponse(BaseModel):
    """Run record response."""

    id: str
    created_at: str
    source_type: str
    status: str
    email_message_id: Optional[str] = None
    attachment_hash: Optional[str] = None
    attachment_name: Optional[str] = None
    auction_detected: Optional[str] = None
    extraction_score: Optional[float] = None
    warehouse_id: Optional[str] = None
    warehouse_reason: Optional[str] = None
    clickup_task_id: Optional[str] = None
    clickup_task_url: Optional[str] = None
    cd_listing_id: Optional[str] = None
    cd_payload_summary: Optional[str] = None
    sheets_spreadsheet_id: Optional[str] = None
    sheets_row_index: Optional[int] = None
    error_message: Optional[str] = None
    config_version: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class RunListResponse(BaseModel):
    """Response for listing runs."""

    runs: list[RunResponse]
    total: int
    limit: int
    offset: int


class LogEntry(BaseModel):
    """Log entry."""

    id: int
    run_id: str
    timestamp: str
    level: str
    message: str
    details: Optional[dict[str, Any]] = None


class StatsResponse(BaseModel):
    """Run statistics response."""

    total: int
    last_24h: int
    by_status: dict[str, int]
    by_auction: dict[str, int]
    by_source: dict[str, int]


# ----- Endpoints -----


@router.get("/", response_model=RunListResponse)
async def list_runs(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    source_type: Optional[str] = Query(
        default=None, description="Filter by source: email, upload, batch"
    ),
    status: Optional[str] = Query(
        default=None, description="Filter by status: pending, processing, ok, failed, error"
    ),
    auction: Optional[str] = Query(
        default=None, description="Filter by auction: COPART, IAA, MANHEIM"
    ),
):
    """
    List runs with optional filtering.

    Returns paginated list of processing runs.
    """
    runs = RunHistory.list_runs(
        limit=limit,
        offset=offset,
        source_type=source_type,
        status=status,
        auction=auction,
    )

    stats = RunHistory.get_stats()

    return RunListResponse(
        runs=[
            RunResponse(
                id=r.id,
                created_at=r.created_at,
                source_type=r.source_type,
                status=r.status,
                email_message_id=r.email_message_id,
                attachment_hash=r.attachment_hash,
                attachment_name=r.attachment_name,
                auction_detected=r.auction_detected,
                extraction_score=r.extraction_score,
                warehouse_id=r.warehouse_id,
                warehouse_reason=r.warehouse_reason,
                clickup_task_id=r.clickup_task_id,
                clickup_task_url=r.clickup_task_url,
                cd_listing_id=r.cd_listing_id,
                cd_payload_summary=r.cd_payload_summary,
                sheets_spreadsheet_id=r.sheets_spreadsheet_id,
                sheets_row_index=r.sheets_row_index,
                error_message=r.error_message,
                config_version=r.config_version,
                metadata=r.metadata,
            )
            for r in runs
        ],
        total=stats["total"],
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=StatsResponse)
async def get_run_stats():
    """
    Get run statistics.

    Returns aggregate counts by status, auction, and source.
    """
    stats = RunHistory.get_stats()

    return StatsResponse(
        total=stats["total"],
        last_24h=stats["last_24h"],
        by_status=stats["by_status"],
        by_auction=stats["by_auction"],
        by_source=stats["by_source"],
    )


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(run_id: str):
    """
    Get a single run by ID.
    """
    run = RunHistory.get_run(run_id)

    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return RunResponse(
        id=run.id,
        created_at=run.created_at,
        source_type=run.source_type,
        status=run.status,
        email_message_id=run.email_message_id,
        attachment_hash=run.attachment_hash,
        attachment_name=run.attachment_name,
        auction_detected=run.auction_detected,
        extraction_score=run.extraction_score,
        warehouse_id=run.warehouse_id,
        warehouse_reason=run.warehouse_reason,
        clickup_task_id=run.clickup_task_id,
        clickup_task_url=run.clickup_task_url,
        cd_listing_id=run.cd_listing_id,
        cd_payload_summary=run.cd_payload_summary,
        sheets_spreadsheet_id=run.sheets_spreadsheet_id,
        sheets_row_index=run.sheets_row_index,
        error_message=run.error_message,
        config_version=run.config_version,
        metadata=run.metadata,
    )


@router.get("/{run_id}/logs", response_model=list[LogEntry])
async def get_run_logs(run_id: str):
    """
    Get logs for a specific run.
    """
    # Verify run exists
    run = RunHistory.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    logs = RunLogs.get_logs(run_id)

    return [
        LogEntry(
            id=log["id"],
            run_id=log["run_id"],
            timestamp=log["timestamp"],
            level=log["level"],
            message=log["message"],
            details=log.get("details"),
        )
        for log in logs
    ]


@router.get("/logs/search")
async def search_logs(
    query: Optional[str] = Query(default=None, description="Search in log messages"),
    run_id: Optional[str] = Query(default=None, description="Filter by run ID"),
    level: Optional[str] = Query(default=None, description="Filter by level: INFO, WARNING, ERROR"),
    limit: int = Query(default=100, le=500),
):
    """
    Search logs across all runs.
    """
    logs = RunLogs.search_logs(
        query=query,
        run_id=run_id,
        level=level,
        limit=limit,
    )

    return {
        "logs": [
            LogEntry(
                id=log["id"],
                run_id=log["run_id"],
                timestamp=log["timestamp"],
                level=log["level"],
                message=log["message"],
                details=log.get("details"),
            )
            for log in logs
        ],
        "count": len(logs),
    }


@router.delete("/{run_id}")
async def delete_run(run_id: str):
    """
    Delete a run and its logs.
    """
    run = RunHistory.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    from api.database import get_connection

    with get_connection() as conn:
        # Delete logs first (foreign key)
        conn.execute("DELETE FROM logs WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        conn.commit()

    return {"status": "ok", "deleted": run_id}


@router.post("/retry/{run_id}")
async def retry_run(run_id: str):
    """
    Retry a failed run.

    Creates a new run with the same parameters.
    """
    run = RunHistory.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if run.status not in ("failed", "error"):
        raise HTTPException(
            status_code=400, detail=f"Run {run_id} is not failed (status: {run.status})"
        )

    # Create new run with same parameters
    new_run_id = RunHistory.create_run(
        source_type=run.source_type,
        attachment_name=run.attachment_name,
        attachment_hash=run.attachment_hash,
        email_message_id=run.email_message_id,
    )

    # Add log entry
    RunLogs.add_log(
        new_run_id,
        "INFO",
        f"Retry of run {run_id}",
        details={"original_run_id": run_id, "original_error": run.error_message},
    )

    return {
        "status": "ok",
        "new_run_id": new_run_id,
        "original_run_id": run_id,
        "message": "Run created for retry - you need to trigger processing separately",
    }


@router.get("/export/csv")
async def export_runs_csv(
    source_type: Optional[str] = None,
    status: Optional[str] = None,
    auction: Optional[str] = None,
    limit: int = Query(default=1000, le=10000),
):
    """
    Export runs to CSV format.
    """
    import csv
    import io

    from fastapi.responses import StreamingResponse

    runs = RunHistory.list_runs(
        limit=limit,
        source_type=source_type,
        status=status,
        auction=auction,
    )

    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(
        [
            "id",
            "created_at",
            "source_type",
            "status",
            "auction_detected",
            "extraction_score",
            "attachment_name",
            "warehouse_id",
            "clickup_task_id",
            "cd_listing_id",
            "error_message",
        ]
    )

    # Rows
    for run in runs:
        writer.writerow(
            [
                run.id,
                run.created_at,
                run.source_type,
                run.status,
                run.auction_detected,
                run.extraction_score,
                run.attachment_name,
                run.warehouse_id,
                run.clickup_task_id,
                run.cd_listing_id,
                run.error_message,
            ]
        )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=runs_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        },
    )
