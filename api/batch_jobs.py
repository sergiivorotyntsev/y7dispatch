"""
Batch Jobs Module (M3.BatchQueue)

Provides job-based batch processing for CD export operations.
Jobs run asynchronously and provide progress tracking.

Features:
- Job creation with unique ID
- Asynchronous processing
- Progress tracking (polling/WebSocket ready)
- Preflight validation
- Rate limiting with semaphore
- Retry with exponential backoff
- Detailed results per run
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from api.database import get_connection
from api.models import DocumentRepository, ExtractionRunRepository

logger = logging.getLogger(__name__)


class BatchJobStatus(str, Enum):
    """Status of a batch job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchItemStatus(str, Enum):
    """Status of an item within a batch job."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass
class BatchJobProgress:
    """Progress tracking for a batch job."""

    total: int = 0
    processed: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    blocked: int = 0
    current_run_id: Optional[int] = None
    started_at: Optional[str] = None
    estimated_remaining_seconds: Optional[int] = None

    @property
    def percent_complete(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.processed / self.total) * 100


@dataclass
class BatchItemResult:
    """Result for a single item in a batch job."""

    run_id: int
    document_filename: Optional[str] = None
    status: BatchItemStatus = BatchItemStatus.PENDING
    cd_listing_id: Optional[str] = None
    error_message: Optional[str] = None
    blocking_issues: list[str] = None
    processed_at: Optional[str] = None

    def __post_init__(self):
        if self.blocking_issues is None:
            self.blocking_issues = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "document_filename": self.document_filename,
            "status": self.status.value,
            "cd_listing_id": self.cd_listing_id,
            "error_message": self.error_message,
            "blocking_issues": self.blocking_issues,
            "processed_at": self.processed_at,
        }


def _init_batch_jobs_table():
    """Initialize batch_jobs table."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_type TEXT NOT NULL DEFAULT 'cd_export',
                status TEXT NOT NULL DEFAULT 'pending',
                run_ids_json TEXT NOT NULL,
                options_json TEXT,
                progress_json TEXT,
                results_json TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_by TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_batch_jobs_status
            ON batch_jobs(status)
        """)
        conn.commit()


class BatchJobRepository:
    """Repository for batch job operations."""

    @staticmethod
    def create(
        run_ids: list[int],
        job_type: str = "cd_export",
        options: dict = None,
        created_by: str = None,
    ) -> int:
        """Create a new batch job."""
        _init_batch_jobs_table()

        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO batch_jobs
                   (job_type, run_ids_json, options_json, created_by)
                   VALUES (?, ?, ?, ?)""",
                (
                    job_type,
                    json.dumps(run_ids),
                    json.dumps(options) if options else None,
                    created_by,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(job_id: int) -> Optional[dict]:
        """Get batch job by ID."""
        _init_batch_jobs_table()

        with get_connection() as conn:
            row = conn.execute("SELECT * FROM batch_jobs WHERE id = ?", (job_id,)).fetchone()

            if row:
                data = dict(row)
                # Parse JSON fields
                if data.get("run_ids_json"):
                    data["run_ids"] = json.loads(data["run_ids_json"])
                if data.get("options_json"):
                    data["options"] = json.loads(data["options_json"])
                if data.get("progress_json"):
                    data["progress"] = json.loads(data["progress_json"])
                if data.get("results_json"):
                    data["results"] = json.loads(data["results_json"])
                return data

        return None

    @staticmethod
    def update(
        job_id: int,
        status: str = None,
        progress: dict = None,
        results: list[dict] = None,
        error_message: str = None,
        started_at: str = None,
        completed_at: str = None,
    ) -> None:
        """Update batch job."""
        updates = []
        params = []

        if status:
            updates.append("status = ?")
            params.append(status)

        if progress:
            updates.append("progress_json = ?")
            params.append(json.dumps(progress))

        if results is not None:
            updates.append("results_json = ?")
            params.append(json.dumps(results))

        if error_message:
            updates.append("error_message = ?")
            params.append(error_message)

        if started_at:
            updates.append("started_at = ?")
            params.append(started_at)

        if completed_at:
            updates.append("completed_at = ?")
            params.append(completed_at)

        if not updates:
            return

        params.append(job_id)
        sql = f"UPDATE batch_jobs SET {', '.join(updates)} WHERE id = ?"

        with get_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

    @staticmethod
    def list_recent(limit: int = 20, status: str = None) -> list[dict]:
        """List recent batch jobs."""
        _init_batch_jobs_table()

        sql = "SELECT * FROM batch_jobs WHERE 1=1"
        params = []

        if status:
            sql += " AND status = ?"
            params.append(status)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        jobs = []
        for row in rows:
            data = dict(row)
            if data.get("run_ids_json"):
                data["run_ids"] = json.loads(data["run_ids_json"])
            if data.get("progress_json"):
                data["progress"] = json.loads(data["progress_json"])
            jobs.append(data)

        return jobs


class BatchJobProcessor:
    """
    Processes batch jobs asynchronously.

    Handles:
    - Preflight validation
    - Rate-limited CD API calls
    - Progress tracking
    - Error handling and retry
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        retry_attempts: int = 3,
        backoff_base: float = 2.0,
    ):
        self.max_concurrent = max_concurrent
        self.retry_attempts = retry_attempts
        self.backoff_base = backoff_base
        self._semaphore: Optional[asyncio.Semaphore] = None

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore

    async def process_job(
        self,
        job_id: int,
        sandbox: bool = True,
        post_only_ready: bool = True,
    ) -> dict:
        """
        Process a batch job.

        Args:
            job_id: Batch job ID
            sandbox: Use CD sandbox environment
            post_only_ready: Only post runs without blocking issues

        Returns:
            Dict with job results
        """
        job = BatchJobRepository.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        if job["status"] != BatchJobStatus.PENDING.value:
            raise ValueError(f"Job {job_id} is not pending (status: {job['status']})")

        run_ids = job.get("run_ids", [])
        job.get("options", {}) or {}

        # Initialize progress
        progress = BatchJobProgress(
            total=len(run_ids),
            started_at=datetime.utcnow().isoformat(),
        )

        # Update job status
        BatchJobRepository.update(
            job_id,
            status=BatchJobStatus.RUNNING.value,
            started_at=datetime.utcnow().isoformat(),
            progress={
                "total": progress.total,
                "processed": 0,
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "blocked": 0,
            },
        )

        results: list[BatchItemResult] = []

        try:
            # Process each run
            for i, run_id in enumerate(run_ids):
                progress.current_run_id = run_id
                progress.processed = i

                # Update progress
                BatchJobRepository.update(
                    job_id,
                    progress={
                        "total": progress.total,
                        "processed": progress.processed,
                        "success": progress.success,
                        "failed": progress.failed,
                        "skipped": progress.skipped,
                        "blocked": progress.blocked,
                        "current_run_id": run_id,
                        "percent_complete": progress.percent_complete,
                    },
                )

                # Process single run
                result = await self._process_single_run(
                    run_id=run_id,
                    sandbox=sandbox,
                    post_only_ready=post_only_ready,
                )

                results.append(result)

                # Update counters
                if result.status == BatchItemStatus.SUCCESS:
                    progress.success += 1
                elif result.status == BatchItemStatus.FAILED:
                    progress.failed += 1
                elif result.status == BatchItemStatus.SKIPPED:
                    progress.skipped += 1
                elif result.status == BatchItemStatus.BLOCKED:
                    progress.blocked += 1

            # Final update
            progress.processed = len(run_ids)
            final_status = (
                BatchJobStatus.COMPLETED.value
                if progress.failed == 0
                else BatchJobStatus.COMPLETED.value  # Still completed, but with failures
            )

            BatchJobRepository.update(
                job_id,
                status=final_status,
                progress={
                    "total": progress.total,
                    "processed": progress.processed,
                    "success": progress.success,
                    "failed": progress.failed,
                    "skipped": progress.skipped,
                    "blocked": progress.blocked,
                    "percent_complete": 100.0,
                },
                results=[r.to_dict() for r in results],
                completed_at=datetime.utcnow().isoformat(),
            )

            return {
                "job_id": job_id,
                "status": final_status,
                "total": progress.total,
                "success": progress.success,
                "failed": progress.failed,
                "skipped": progress.skipped,
                "blocked": progress.blocked,
                "results": [r.to_dict() for r in results],
            }

        except Exception as e:
            logger.error(f"Batch job {job_id} failed: {e}")
            BatchJobRepository.update(
                job_id,
                status=BatchJobStatus.FAILED.value,
                error_message=str(e),
                completed_at=datetime.utcnow().isoformat(),
            )
            raise

    async def _process_single_run(
        self,
        run_id: int,
        sandbox: bool,
        post_only_ready: bool,
    ) -> BatchItemResult:
        """Process a single extraction run."""
        from api.listing_fields import get_registry
        from api.models import ExportJobRepository
        from api.routes.exports import (
            build_cd_payload,
            get_cd_listing_info,
            send_to_cd_with_retry,
        )

        result = BatchItemResult(run_id=run_id)

        # Get run info
        run = ExtractionRunRepository.get_by_id(run_id)
        if not run:
            result.status = BatchItemStatus.FAILED
            result.error_message = "Extraction run not found"
            return result

        doc = DocumentRepository.get_by_id(run.document_id)
        result.document_filename = doc.filename if doc else None

        # Check if test document
        if doc:
            with get_connection() as conn:
                is_test = conn.execute(
                    "SELECT is_test FROM documents WHERE id = ?", (doc.id,)
                ).fetchone()
                if is_test and is_test[0]:
                    result.status = BatchItemStatus.SKIPPED
                    result.error_message = "Test document"
                    return result

        # Check if already exported (allow update)
        get_cd_listing_info(run_id)

        # Check blocking issues
        registry = get_registry()
        outputs = run.outputs_json or {}
        if isinstance(outputs, str):
            outputs = json.loads(outputs)

        warehouse_selected = bool(outputs.get("warehouse_id") or outputs.get("delivery_address"))
        issues = registry.get_blocking_issues(outputs, warehouse_selected=warehouse_selected)

        if issues:
            result.blocking_issues = [i["issue"] for i in issues]
            if post_only_ready:
                result.status = BatchItemStatus.BLOCKED
                result.error_message = "Has blocking issues"
                return result

        # Build payload
        payload, errors = build_cd_payload(run_id)
        if errors:
            result.status = BatchItemStatus.FAILED
            result.error_message = "; ".join(errors)
            return result

        # Send to CD with rate limiting
        async with self.semaphore:
            success, response, cd_listing_id = await send_to_cd_with_retry(
                payload,
                sandbox=sandbox,
                run_id=run_id,
            )

        result.processed_at = datetime.utcnow().isoformat()

        # Create export job record
        job_id = ExportJobRepository.create(
            run_id=run_id,
            target="central_dispatch",
            payload_json=payload,
        )

        if success:
            ExportJobRepository.update(
                job_id,
                status="completed",
                response_json=response,
                cd_listing_id=cd_listing_id,
            )
            ExtractionRunRepository.update(run_id, status="exported")

            result.status = BatchItemStatus.SUCCESS
            result.cd_listing_id = cd_listing_id
        else:
            error_msg = response.get("error", "Export failed")
            ExportJobRepository.update(
                job_id,
                status="failed",
                response_json=response,
                error_message=error_msg,
            )

            result.status = BatchItemStatus.FAILED
            result.error_message = error_msg

        return result


async def run_batch_job(job_id: int, sandbox: bool = True) -> dict:
    """
    Run a batch job asynchronously.

    This is the main entry point for processing a batch job.
    Can be called from a background task or async endpoint.

    Args:
        job_id: Batch job ID
        sandbox: Use CD sandbox environment

    Returns:
        Dict with job results
    """
    processor = BatchJobProcessor()
    return await processor.process_job(job_id, sandbox=sandbox)


def create_batch_job(
    run_ids: list[int],
    options: dict = None,
    created_by: str = None,
) -> int:
    """
    Create a new batch job.

    Args:
        run_ids: List of extraction run IDs to process
        options: Job options (sandbox, post_only_ready, etc.)
        created_by: User who created the job

    Returns:
        Job ID
    """
    return BatchJobRepository.create(
        run_ids=run_ids,
        job_type="cd_export",
        options=options,
        created_by=created_by,
    )


def get_batch_job_status(job_id: int) -> Optional[dict]:
    """
    Get batch job status and progress.

    Args:
        job_id: Batch job ID

    Returns:
        Dict with job status, progress, and results (if completed)
    """
    job = BatchJobRepository.get_by_id(job_id)
    if not job:
        return None

    return {
        "id": job["id"],
        "status": job["status"],
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "progress": job.get("progress"),
        "results": job.get("results"),
        "error_message": job.get("error_message"),
    }
