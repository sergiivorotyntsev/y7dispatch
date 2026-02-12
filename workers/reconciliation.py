"""
Reconciliation Worker — DB ↔ Sheets consistency check.

Runs on a 5-minute interval (when scheduled) to verify that the
Google Sheets export view matches the DB source of truth.

Differences are logged and optionally re-synced from DB → Sheets.

TODO: Wire into scheduler (APScheduler or simple asyncio loop).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ReconciliationResult:
    """Result of a single reconciliation run."""

    run_at: str
    rows_checked: int = 0
    mismatches_found: int = 0
    mismatches_fixed: int = 0
    errors: list = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.mismatches_found == 0 and len(self.errors) == 0


def reconcile_once() -> ReconciliationResult:
    """
    Run a single reconciliation pass.

    Compares export jobs in DB against their Sheets row counterparts.
    Any drift is logged and optionally corrected (DB wins).

    Returns:
        ReconciliationResult with summary of findings.
    """
    result = ReconciliationResult(run_at=datetime.utcnow().isoformat())

    # TODO: Implement full reconciliation logic:
    # 1. Load recent export jobs from DB (last 24h or status=success)
    # 2. For each, read corresponding Sheets row
    # 3. Compare key fields (VIN, price, status, dispatch_id)
    # 4. Log mismatches, optionally re-push DB values to Sheets
    # 5. Alert on persistent drift (>2 consecutive mismatches)

    logger.info(
        f"Reconciliation stub executed at {result.run_at}: "
        f"{result.rows_checked} checked, {result.mismatches_found} mismatches"
    )

    return result


async def run_reconciliation_loop(interval_seconds: int = 300):
    """
    Async loop that runs reconciliation every `interval_seconds`.

    TODO: Wire this into app startup or a dedicated scheduler process.

    Usage:
        import asyncio
        asyncio.create_task(run_reconciliation_loop(300))
    """
    import asyncio

    logger.info(f"Reconciliation loop starting (interval={interval_seconds}s)")

    while True:
        try:
            result = reconcile_once()
            if not result.is_clean:
                logger.warning(
                    f"Reconciliation found issues: "
                    f"{result.mismatches_found} mismatches, {len(result.errors)} errors"
                )
        except Exception as e:
            logger.error(f"Reconciliation loop error: {e}", exc_info=True)

        await asyncio.sleep(interval_seconds)
