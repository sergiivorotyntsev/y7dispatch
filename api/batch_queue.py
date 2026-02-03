"""
Batch Queue for CD Export Operations

Manages batch job processing for posting multiple listings to Central Dispatch.
Tracks progress, supports cancellation, and provides job status.
"""

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Batch job status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    CANCELLING = "cancelling"
    FAILED = "failed"


@dataclass
class JobItem:
    """Single item in a batch job."""

    run_id: int
    status: str = "pending"  # pending, processing, completed, failed, skipped
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class BatchJob:
    """Batch job definition."""

    job_id: str
    items: list[JobItem]
    status: JobStatus = JobStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    current_index: int = 0
    _cancel_requested: bool = False


class BatchQueue:
    """
    Batch queue manager for CD export operations.

    Features:
    - Job creation with multiple run IDs
    - Progress tracking
    - Cancellation support
    - Deterministic rerun behavior
    """

    def __init__(self, max_workers: int = 3):
        self._jobs: dict[str, BatchJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._max_workers = max_workers

    def create_job(self, run_ids: list[int]) -> str:
        """
        Create a new batch job.

        Args:
            run_ids: List of extraction run IDs to process

        Returns:
            Job ID
        """
        job_id = str(uuid.uuid4())[:8]

        items = [JobItem(run_id=rid) for rid in run_ids]

        job = BatchJob(
            job_id=job_id,
            items=items,
        )

        with self._lock:
            self._jobs[job_id] = job

        logger.info(f"Created batch job {job_id} with {len(run_ids)} items")
        return job_id

    def start_job(self, job_id: str, processor: Callable[[int], dict[str, Any]]) -> bool:
        """
        Start processing a batch job.

        Args:
            job_id: Job ID to start
            processor: Function to process each run_id, returns result dict

        Returns:
            True if started, False if job not found or already running
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False

            if job.status not in (JobStatus.PENDING, JobStatus.CANCELLED):
                return False

            job.status = JobStatus.RUNNING
            job.started_at = datetime.now().isoformat()

        # Start processing in background
        self._executor.submit(self._process_job, job_id, processor)
        return True

    def _process_job(self, job_id: str, processor: Callable[[int], dict[str, Any]]):
        """Process job items sequentially."""
        job = self._jobs.get(job_id)
        if not job:
            return

        for i, item in enumerate(job.items):
            # Check for cancellation
            if job._cancel_requested:
                job.status = JobStatus.CANCELLED
                logger.info(f"Job {job_id} cancelled at item {i}")
                break

            # Skip already processed items (for rerun)
            if item.status in ("completed", "skipped"):
                continue

            job.current_index = i
            item.status = "processing"
            item.started_at = datetime.now().isoformat()

            try:
                result = processor(item.run_id)
                item.result = result
                item.status = "completed" if result.get("success") else "failed"
                if not result.get("success"):
                    item.error = result.get("error", "Unknown error")
            except Exception as e:
                item.status = "failed"
                item.error = str(e)
                logger.error(f"Job {job_id} item {i} failed: {e}")

            item.completed_at = datetime.now().isoformat()

        # Mark job complete
        if not job._cancel_requested:
            job.status = JobStatus.COMPLETED

        job.completed_at = datetime.now().isoformat()
        logger.info(f"Job {job_id} finished with status {job.status.value}")

    def cancel(self, job_id: str) -> bool:
        """
        Cancel a running or pending job.

        Cancellation is best-effort - currently processing items will complete,
        but no new items will start.

        Returns:
            True if cancel requested, False if job not found
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False

            if job.status == JobStatus.RUNNING:
                job._cancel_requested = True
                job.status = JobStatus.CANCELLING
                logger.info(f"Cancel requested for job {job_id}")
                return True
            elif job.status == JobStatus.PENDING:
                job._cancel_requested = True
                job.status = JobStatus.CANCELLED
                job.completed_at = datetime.now().isoformat()
                logger.info(f"Pending job {job_id} cancelled")
                return True

            return False

    def get_status(self, job_id: str) -> Optional[dict[str, Any]]:
        """
        Get job status and progress.

        Returns:
            Status dict with progress info, or None if job not found
        """
        job = self._jobs.get(job_id)
        if not job:
            return None

        completed = sum(1 for i in job.items if i.status == "completed")
        failed = sum(1 for i in job.items if i.status == "failed")
        skipped = sum(1 for i in job.items if i.status == "skipped")
        pending = sum(1 for i in job.items if i.status == "pending")
        processing = sum(1 for i in job.items if i.status == "processing")

        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "total": len(job.items),
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "pending": pending,
            "processing": processing,
            "progress_percent": (
                int((completed + failed + skipped) / len(job.items) * 100) if job.items else 0
            ),
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "current_item": job.current_index,
        }

    def get_results(self, job_id: str) -> Optional[dict[str, Any]]:
        """
        Get detailed results for a completed job.

        Returns:
            Results dict with per-item details, or None if job not found
        """
        job = self._jobs.get(job_id)
        if not job:
            return None

        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "items": [
                {
                    "run_id": item.run_id,
                    "status": item.status,
                    "result": item.result,
                    "error": item.error,
                    "started_at": item.started_at,
                    "completed_at": item.completed_at,
                }
                for item in job.items
            ],
            "summary": {
                "posted": sum(
                    1 for i in job.items if i.result and i.result.get("action") == "posted"
                ),
                "updated": sum(
                    1 for i in job.items if i.result and i.result.get("action") == "updated"
                ),
                "failed": sum(1 for i in job.items if i.status == "failed"),
                "skipped": sum(1 for i in job.items if i.status == "skipped"),
            },
        }

    def list_jobs(self, status: Optional[JobStatus] = None) -> list[dict[str, Any]]:
        """List all jobs, optionally filtered by status."""
        jobs = []
        for job in self._jobs.values():
            if status and job.status != status:
                continue
            jobs.append(self.get_status(job.job_id))
        return jobs

    def cleanup_completed(self, older_than_hours: int = 24) -> int:
        """Remove completed jobs older than specified hours."""
        from datetime import datetime, timedelta

        cutoff = datetime.now() - timedelta(hours=older_than_hours)
        removed = 0

        with self._lock:
            to_remove = []
            for job_id, job in self._jobs.items():
                if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED):
                    if job.completed_at:
                        completed = datetime.fromisoformat(job.completed_at)
                        if completed < cutoff:
                            to_remove.append(job_id)

            for job_id in to_remove:
                del self._jobs[job_id]
                removed += 1

        return removed


# Global batch queue instance
_batch_queue: Optional[BatchQueue] = None


def get_batch_queue() -> BatchQueue:
    """Get global batch queue instance."""
    global _batch_queue
    if _batch_queue is None:
        _batch_queue = BatchQueue()
    return _batch_queue
