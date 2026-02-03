"""
Metrics API Routes (M3.P1.5)

Provides extraction metrics, quality monitoring, and drift detection.

Endpoints:
- GET /metrics/extractions - Extraction metrics with grouping
- GET /metrics/quality - Quality and fill rate metrics
- GET /metrics/drift/alerts - Drift detection alerts
- GET /metrics/summary - Dashboard summary
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/metrics", tags=["Metrics"])


# =============================================================================
# MODELS
# =============================================================================


class ExtractionMetric(BaseModel):
    """Extraction metric data point."""

    group_key: str
    count: int
    avg_raw_text_length: float = 0
    avg_words_count: float = 0
    ocr_applied_count: int = 0
    ocr_applied_rate: float = 0
    avg_layout_blocks: float = 0
    avg_evidence_coverage: float = 0
    avg_extraction_score: float = 0


class QualityMetric(BaseModel):
    """Quality metric data point."""

    group_key: str
    total_runs: int
    ready_count: int = 0
    needs_review_count: int = 0
    failed_count: int = 0
    exported_count: int = 0
    fill_rate: float = 0
    required_fill_rate: float = 0
    blocking_issues_count: int = 0
    pickup_parse_success_rate: float = 0
    classification_confidence_avg: float = 0


class DriftAlert(BaseModel):
    """Drift detection alert."""

    alert_type: str
    severity: str  # warning, critical
    auction_code: Optional[str]
    message: str
    current_value: float
    threshold: float
    days_below: int = 0
    created_at: str


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _get_date_range(days: int = 7) -> tuple[str, str]:
    """Get date range for queries."""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def _parse_metrics_json(metrics_json) -> dict:
    """Parse metrics JSON from database."""
    if not metrics_json:
        return {}
    if isinstance(metrics_json, dict):
        return metrics_json
    try:
        return json.loads(metrics_json)
    except (json.JSONDecodeError, TypeError):
        return {}


# =============================================================================
# EXTRACTION METRICS ENDPOINT
# =============================================================================


@router.get("/extractions")
async def get_extraction_metrics(
    group_by: str = Query("day", enum=["auction", "warehouse", "day", "source"]),
    days: int = Query(7, ge=1, le=90),
    auction_code: Optional[str] = None,
):
    """
    Get extraction metrics with grouping.

    Metrics include:
    - Raw text length and word count
    - OCR applied rate
    - Layout blocks count
    - Evidence coverage
    - Extraction score
    """
    start_date, end_date = _get_date_range(days)

    with get_connection() as conn:
        # Build base query
        if group_by == "day":
            group_expr = "DATE(r.created_at)"
        elif group_by == "auction":
            group_expr = "COALESCE(at.code, 'UNKNOWN')"
        elif group_by == "source":
            group_expr = "COALESCE(json_extract(r.metrics_json, '$.detected_source'), 'UNKNOWN')"
        else:  # warehouse
            group_expr = "COALESCE(json_extract(r.outputs_json, '$.warehouse_id'), 'NONE')"

        sql = f"""
            SELECT
                {group_expr} as group_key,
                COUNT(*) as count,
                AVG(COALESCE(json_extract(r.metrics_json, '$.raw_text_length'), 0)) as avg_raw_text_length,
                AVG(COALESCE(json_extract(r.metrics_json, '$.words_count'), 0)) as avg_words_count,
                SUM(CASE WHEN json_extract(r.metrics_json, '$.ocr_applied') = 1 THEN 1 ELSE 0 END) as ocr_applied_count,
                AVG(COALESCE(json_extract(r.metrics_json, '$.layout_blocks_count'), 0)) as avg_layout_blocks,
                AVG(COALESCE(json_extract(r.metrics_json, '$.evidence_coverage'), 0)) as avg_evidence_coverage,
                AVG(COALESCE(r.extraction_score, 0)) as avg_extraction_score
            FROM extraction_runs r
            LEFT JOIN auction_types at ON r.auction_type_id = at.id
            WHERE DATE(r.created_at) >= ? AND DATE(r.created_at) <= ?
        """
        params = [start_date, end_date]

        if auction_code:
            sql += " AND at.code = ?"
            params.append(auction_code)

        sql += f" GROUP BY {group_expr} ORDER BY group_key"

        rows = conn.execute(sql, params).fetchall()

    metrics = []
    for row in rows:
        count = row["count"] or 0
        metrics.append(
            ExtractionMetric(
                group_key=str(row["group_key"]),
                count=count,
                avg_raw_text_length=row["avg_raw_text_length"] or 0,
                avg_words_count=row["avg_words_count"] or 0,
                ocr_applied_count=row["ocr_applied_count"] or 0,
                ocr_applied_rate=(row["ocr_applied_count"] or 0) / count * 100 if count > 0 else 0,
                avg_layout_blocks=row["avg_layout_blocks"] or 0,
                avg_evidence_coverage=row["avg_evidence_coverage"] or 0,
                avg_extraction_score=row["avg_extraction_score"] or 0,
            )
        )

    return {
        "group_by": group_by,
        "days": days,
        "start_date": start_date,
        "end_date": end_date,
        "metrics": [m.dict() for m in metrics],
    }


# =============================================================================
# QUALITY METRICS ENDPOINT
# =============================================================================


@router.get("/quality")
async def get_quality_metrics(
    group_by: str = Query("auction", enum=["auction", "day"]),
    days: int = Query(7, ge=1, le=90),
):
    """
    Get quality and fill rate metrics.

    Metrics include:
    - Status distribution (ready, needs_review, failed, exported)
    - Fill rate for all fields
    - Required field fill rate
    - Blocking issues count
    - Pickup parse success rate
    - Classification confidence
    """
    start_date, end_date = _get_date_range(days)

    with get_connection() as conn:
        if group_by == "day":
            group_expr = "DATE(r.created_at)"
        else:
            group_expr = "COALESCE(at.code, 'UNKNOWN')"

        sql = f"""
            SELECT
                {group_expr} as group_key,
                COUNT(*) as total_runs,
                SUM(CASE WHEN r.status = 'ready' THEN 1 ELSE 0 END) as ready_count,
                SUM(CASE WHEN r.status = 'needs_review' THEN 1 ELSE 0 END) as needs_review_count,
                SUM(CASE WHEN r.status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                SUM(CASE WHEN r.status = 'exported' THEN 1 ELSE 0 END) as exported_count,
                AVG(COALESCE(json_extract(r.metrics_json, '$.fields_filled_count'), 0) * 1.0 /
                    NULLIF(json_extract(r.metrics_json, '$.fields_extracted_count'), 0) * 100) as fill_rate,
                AVG(COALESCE(json_extract(r.metrics_json, '$.required_fields_filled'), 0) * 1.0 /
                    NULLIF(json_extract(r.metrics_json, '$.required_fields_total'), 4) * 100) as required_fill_rate,
                SUM(CASE WHEN json_extract(r.metrics_json, '$.has_pickup_address') = 1 THEN 1 ELSE 0 END) as pickup_success,
                AVG(COALESCE(json_extract(r.metrics_json, '$.classification_score'), 0)) as classification_confidence_avg
            FROM extraction_runs r
            LEFT JOIN auction_types at ON r.auction_type_id = at.id
            WHERE DATE(r.created_at) >= ? AND DATE(r.created_at) <= ?
            GROUP BY {group_expr}
            ORDER BY group_key
        """

        rows = conn.execute(sql, [start_date, end_date]).fetchall()

    metrics = []
    for row in rows:
        total = row["total_runs"] or 0
        metrics.append(
            QualityMetric(
                group_key=str(row["group_key"]),
                total_runs=total,
                ready_count=row["ready_count"] or 0,
                needs_review_count=row["needs_review_count"] or 0,
                failed_count=row["failed_count"] or 0,
                exported_count=row["exported_count"] or 0,
                fill_rate=row["fill_rate"] or 0,
                required_fill_rate=row["required_fill_rate"] or 0,
                pickup_parse_success_rate=(
                    (row["pickup_success"] or 0) / total * 100 if total > 0 else 0
                ),
                classification_confidence_avg=row["classification_confidence_avg"] or 0,
            )
        )

    return {
        "group_by": group_by,
        "days": days,
        "start_date": start_date,
        "end_date": end_date,
        "metrics": [m.dict() for m in metrics],
    }


# =============================================================================
# DRIFT DETECTION
# =============================================================================

# Drift thresholds
DRIFT_THRESHOLDS = {
    "fill_rate": {"warning": 70, "critical": 50},
    "required_fill_rate": {"warning": 80, "critical": 60},
    "ocr_rate": {"warning": 30, "critical": 50},  # Alert if OCR rate is too high
    "classification_confidence": {"warning": 0.3, "critical": 0.2},
}


@router.get("/drift/alerts")
async def get_drift_alerts(
    days_threshold: int = Query(3, ge=1, le=7, description="Days below threshold to trigger alert"),
    include_warnings: bool = Query(True),
):
    """
    Get drift detection alerts (M3.P1.6).

    Alerts are generated when metrics fall below thresholds
    for a specified number of consecutive days.
    """
    alerts = []

    with get_connection() as conn:
        # Check fill rate by auction for last N days
        for check_days in range(1, days_threshold + 1):
            date = (datetime.utcnow() - timedelta(days=check_days)).strftime("%Y-%m-%d")

            rows = conn.execute(
                """
                SELECT
                    COALESCE(at.code, 'UNKNOWN') as auction_code,
                    COUNT(*) as total,
                    AVG(COALESCE(json_extract(r.metrics_json, '$.required_fields_filled'), 0) * 1.0 /
                        NULLIF(json_extract(r.metrics_json, '$.required_fields_total'), 4) * 100) as fill_rate,
                    AVG(COALESCE(json_extract(r.metrics_json, '$.classification_score'), 0)) as confidence,
                    SUM(CASE WHEN json_extract(r.metrics_json, '$.ocr_applied') = 1 THEN 1 ELSE 0 END) * 100.0 /
                        COUNT(*) as ocr_rate
                FROM extraction_runs r
                LEFT JOIN auction_types at ON r.auction_type_id = at.id
                WHERE DATE(r.created_at) = ?
                GROUP BY at.code
            """,
                [date],
            ).fetchall()

            for row in rows:
                auction = row["auction_code"]
                total = row["total"]

                if total < 5:  # Skip if not enough data
                    continue

                # Check fill rate
                fill_rate = row["fill_rate"] or 0
                if fill_rate < DRIFT_THRESHOLDS["required_fill_rate"]["critical"]:
                    alerts.append(
                        DriftAlert(
                            alert_type="fill_rate_critical",
                            severity="critical",
                            auction_code=auction,
                            message=f"Required fill rate critically low for {auction}",
                            current_value=fill_rate,
                            threshold=DRIFT_THRESHOLDS["required_fill_rate"]["critical"],
                            days_below=check_days,
                            created_at=datetime.utcnow().isoformat(),
                        )
                    )
                elif (
                    fill_rate < DRIFT_THRESHOLDS["required_fill_rate"]["warning"]
                    and include_warnings
                ):
                    alerts.append(
                        DriftAlert(
                            alert_type="fill_rate_warning",
                            severity="warning",
                            auction_code=auction,
                            message=f"Required fill rate below threshold for {auction}",
                            current_value=fill_rate,
                            threshold=DRIFT_THRESHOLDS["required_fill_rate"]["warning"],
                            days_below=check_days,
                            created_at=datetime.utcnow().isoformat(),
                        )
                    )

                # Check OCR rate (high OCR rate may indicate source document changes)
                ocr_rate = row["ocr_rate"] or 0
                if ocr_rate > DRIFT_THRESHOLDS["ocr_rate"]["critical"]:
                    alerts.append(
                        DriftAlert(
                            alert_type="ocr_rate_critical",
                            severity="critical",
                            auction_code=auction,
                            message=f"OCR rate unusually high for {auction} - may indicate document format change",
                            current_value=ocr_rate,
                            threshold=DRIFT_THRESHOLDS["ocr_rate"]["critical"],
                            days_below=check_days,
                            created_at=datetime.utcnow().isoformat(),
                        )
                    )

                # Check classification confidence
                confidence = row["confidence"] or 0
                if confidence < DRIFT_THRESHOLDS["classification_confidence"]["critical"]:
                    alerts.append(
                        DriftAlert(
                            alert_type="classification_critical",
                            severity="critical",
                            auction_code=auction,
                            message=f"Classification confidence very low for {auction}",
                            current_value=confidence,
                            threshold=DRIFT_THRESHOLDS["classification_confidence"]["critical"],
                            days_below=check_days,
                            created_at=datetime.utcnow().isoformat(),
                        )
                    )

    # Deduplicate alerts (keep most recent)
    seen = set()
    unique_alerts = []
    for alert in alerts:
        key = (alert.alert_type, alert.auction_code)
        if key not in seen:
            seen.add(key)
            unique_alerts.append(alert)

    return {
        "alerts": [a.dict() for a in unique_alerts],
        "alert_count": len(unique_alerts),
        "critical_count": sum(1 for a in unique_alerts if a.severity == "critical"),
        "warning_count": sum(1 for a in unique_alerts if a.severity == "warning"),
        "thresholds": DRIFT_THRESHOLDS,
    }


# =============================================================================
# DASHBOARD SUMMARY
# =============================================================================


@router.get("/summary")
async def get_metrics_summary(
    days: int = Query(7, ge=1, le=30),
):
    """
    Get summary metrics for ops dashboard.

    Returns aggregated metrics for quick overview.
    """
    start_date, end_date = _get_date_range(days)

    with get_connection() as conn:
        # Total counts
        totals = conn.execute(
            """
            SELECT
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'exported' THEN 1 ELSE 0 END) as exported,
                SUM(CASE WHEN status = 'needs_review' THEN 1 ELSE 0 END) as needs_review,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) as processing,
                AVG(COALESCE(extraction_score, 0)) as avg_score
            FROM extraction_runs
            WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?
        """,
            [start_date, end_date],
        ).fetchone()

        # By auction type
        by_auction = conn.execute(
            """
            SELECT
                COALESCE(at.code, 'UNKNOWN') as auction,
                COUNT(*) as count,
                SUM(CASE WHEN r.status = 'exported' THEN 1 ELSE 0 END) as exported
            FROM extraction_runs r
            LEFT JOIN auction_types at ON r.auction_type_id = at.id
            WHERE DATE(r.created_at) >= ? AND DATE(r.created_at) <= ?
            GROUP BY at.code
            ORDER BY count DESC
        """,
            [start_date, end_date],
        ).fetchall()

        # Recent trend (last 7 days)
        trend = conn.execute(
            """
            SELECT
                DATE(created_at) as day,
                COUNT(*) as count,
                SUM(CASE WHEN status = 'exported' THEN 1 ELSE 0 END) as exported
            FROM extraction_runs
            WHERE DATE(created_at) >= ?
            GROUP BY DATE(created_at)
            ORDER BY day DESC
            LIMIT 7
        """,
            [start_date],
        ).fetchall()

    total_runs = totals["total_runs"] or 0

    return {
        "period": {"start": start_date, "end": end_date, "days": days},
        "totals": {
            "total_runs": total_runs,
            "exported": totals["exported"] or 0,
            "needs_review": totals["needs_review"] or 0,
            "failed": totals["failed"] or 0,
            "processing": totals["processing"] or 0,
            "success_rate": (totals["exported"] or 0) / total_runs * 100 if total_runs > 0 else 0,
            "avg_extraction_score": totals["avg_score"] or 0,
        },
        "by_auction": [
            {
                "auction": row["auction"],
                "count": row["count"],
                "exported": row["exported"],
                "rate": row["exported"] / row["count"] * 100 if row["count"] > 0 else 0,
            }
            for row in by_auction
        ],
        "trend": [
            {
                "day": row["day"],
                "count": row["count"],
                "exported": row["exported"],
            }
            for row in trend
        ],
    }
