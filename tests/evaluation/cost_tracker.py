"""
Cost Tracking Service (Phase 0.4)

Tracks token usage and costs for Claude API calls.
Provides per-document and aggregate cost analysis.

Usage:
    from tests.evaluation.cost_tracker import CostTracker, get_cost_tracker

    tracker = get_cost_tracker()
    tracker.record_request(
        request_id="doc_001",
        model="claude-haiku-4-5-20251001",
        input_tokens=1500,
        output_tokens=500,
        cached_tokens=1000,
    )

    print(tracker.get_summary())
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Pricing (as of 2026-02 - VERIFY CURRENT RATES)
# https://www.anthropic.com/pricing
MODEL_PRICING = {
    "claude-haiku-4-5-20251001": {
        "input_per_mtok": 0.25,  # $0.25 per million input tokens
        "output_per_mtok": 1.25,  # $1.25 per million output tokens
        "cached_input_per_mtok": 0.025,  # 90% discount for cached
    },
    "claude-sonnet-4-20250514": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "cached_input_per_mtok": 0.30,
    },
    "claude-opus-4-5-20251101": {
        "input_per_mtok": 15.00,
        "output_per_mtok": 75.00,
        "cached_input_per_mtok": 1.50,
    },
    # Fallback for unknown models
    "default": {
        "input_per_mtok": 0.25,
        "output_per_mtok": 1.25,
        "cached_input_per_mtok": 0.025,
    },
}


@dataclass
class RequestCost:
    """Cost breakdown for a single API request."""

    request_id: str
    model: str
    timestamp: datetime
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    total_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    cached_cost: float = 0.0
    total_cost: float = 0.0
    document_type: Optional[str] = None  # pdf, email, etc.
    auction_type: Optional[str] = None  # COPART, IAA, MANHEIM

    def __post_init__(self):
        self.total_tokens = self.input_tokens + self.output_tokens
        self._calculate_costs()

    def _calculate_costs(self):
        """Calculate costs based on model pricing."""
        pricing = MODEL_PRICING.get(self.model, MODEL_PRICING["default"])

        # Non-cached input tokens
        non_cached_input = max(0, self.input_tokens - self.cached_tokens)

        self.input_cost = non_cached_input * pricing["input_per_mtok"] / 1_000_000
        self.cached_cost = self.cached_tokens * pricing["cached_input_per_mtok"] / 1_000_000
        self.output_cost = self.output_tokens * pricing["output_per_mtok"] / 1_000_000
        self.total_cost = self.input_cost + self.cached_cost + self.output_cost

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "model": self.model,
            "timestamp": self.timestamp.isoformat(),
            "tokens": {
                "input": self.input_tokens,
                "output": self.output_tokens,
                "cached": self.cached_tokens,
                "total": self.total_tokens,
            },
            "cost_usd": {
                "input": round(self.input_cost, 6),
                "output": round(self.output_cost, 6),
                "cached": round(self.cached_cost, 6),
                "total": round(self.total_cost, 6),
            },
            "document_type": self.document_type,
            "auction_type": self.auction_type,
        }


@dataclass
class CostSummary:
    """Aggregate cost summary."""

    period_start: datetime
    period_end: datetime
    total_requests: int = 0
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cached_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_cost_per_request: float = 0.0
    avg_tokens_per_request: float = 0.0
    cache_hit_rate: float = 0.0
    by_model: dict = field(default_factory=dict)
    by_document_type: dict = field(default_factory=dict)
    by_auction_type: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "period": {
                "start": self.period_start.isoformat(),
                "end": self.period_end.isoformat(),
            },
            "totals": {
                "requests": self.total_requests,
                "tokens": self.total_tokens,
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
                "cached_tokens": self.total_cached_tokens,
                "cost_usd": round(self.total_cost_usd, 4),
            },
            "averages": {
                "cost_per_request": round(self.avg_cost_per_request, 6),
                "tokens_per_request": round(self.avg_tokens_per_request, 1),
                "cache_hit_rate": round(self.cache_hit_rate, 4),
            },
            "by_model": self.by_model,
            "by_document_type": self.by_document_type,
            "by_auction_type": self.by_auction_type,
        }


class CostTracker:
    """
    Tracks API costs for extraction operations.

    Thread-safe singleton for application-wide cost tracking.
    """

    def __init__(self, persist_path: Optional[Path] = None):
        """
        Initialize cost tracker.

        Args:
            persist_path: Optional path to persist costs to disk
        """
        self._requests: list[RequestCost] = []
        self._lock = threading.Lock()
        self._persist_path = persist_path

        if persist_path and persist_path.exists():
            self._load_from_disk()

    def record_request(
        self,
        request_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        document_type: Optional[str] = None,
        auction_type: Optional[str] = None,
    ) -> RequestCost:
        """
        Record a new API request with costs.

        Returns:
            RequestCost object with calculated costs
        """
        cost = RequestCost(
            request_id=request_id,
            model=model,
            timestamp=datetime.utcnow(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            document_type=document_type,
            auction_type=auction_type,
        )

        with self._lock:
            self._requests.append(cost)

            if self._persist_path:
                self._save_to_disk()

        logger.debug(
            f"Recorded request {request_id}: "
            f"{input_tokens}+{output_tokens} tokens, ${cost.total_cost:.6f}"
        )

        return cost

    def get_summary(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> CostSummary:
        """
        Get cost summary for a time period.

        Args:
            since: Start of period (default: all time)
            until: End of period (default: now)

        Returns:
            CostSummary with aggregate metrics
        """
        with self._lock:
            requests = self._filter_requests(since, until)

        if not requests:
            now = datetime.utcnow()
            return CostSummary(
                period_start=since or now,
                period_end=until or now,
            )

        summary = CostSummary(
            period_start=requests[0].timestamp,
            period_end=requests[-1].timestamp,
            total_requests=len(requests),
        )

        # Aggregate totals
        by_model = {}
        by_doc_type = {}
        by_auction = {}

        for req in requests:
            summary.total_tokens += req.total_tokens
            summary.total_input_tokens += req.input_tokens
            summary.total_output_tokens += req.output_tokens
            summary.total_cached_tokens += req.cached_tokens
            summary.total_cost_usd += req.total_cost

            # By model
            if req.model not in by_model:
                by_model[req.model] = {"count": 0, "cost": 0.0, "tokens": 0}
            by_model[req.model]["count"] += 1
            by_model[req.model]["cost"] += req.total_cost
            by_model[req.model]["tokens"] += req.total_tokens

            # By document type
            doc_type = req.document_type or "unknown"
            if doc_type not in by_doc_type:
                by_doc_type[doc_type] = {"count": 0, "cost": 0.0}
            by_doc_type[doc_type]["count"] += 1
            by_doc_type[doc_type]["cost"] += req.total_cost

            # By auction type
            auction = req.auction_type or "unknown"
            if auction not in by_auction:
                by_auction[auction] = {"count": 0, "cost": 0.0}
            by_auction[auction]["count"] += 1
            by_auction[auction]["cost"] += req.total_cost

        # Calculate averages
        summary.avg_cost_per_request = summary.total_cost_usd / summary.total_requests
        summary.avg_tokens_per_request = summary.total_tokens / summary.total_requests

        if summary.total_input_tokens > 0:
            summary.cache_hit_rate = (
                summary.total_cached_tokens / summary.total_input_tokens
            )

        # Round breakdowns
        summary.by_model = {
            k: {
                "count": v["count"],
                "cost_usd": round(v["cost"], 4),
                "tokens": v["tokens"],
            }
            for k, v in by_model.items()
        }
        summary.by_document_type = {
            k: {"count": v["count"], "cost_usd": round(v["cost"], 4)}
            for k, v in by_doc_type.items()
        }
        summary.by_auction_type = {
            k: {"count": v["count"], "cost_usd": round(v["cost"], 4)}
            for k, v in by_auction.items()
        }

        return summary

    def get_daily_summary(self, date: Optional[datetime] = None) -> CostSummary:
        """Get summary for a specific day."""
        if date is None:
            date = datetime.utcnow()

        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        return self.get_summary(since=start, until=end)

    def get_recent_requests(self, limit: int = 100) -> list[RequestCost]:
        """Get recent requests."""
        with self._lock:
            return self._requests[-limit:]

    def clear(self):
        """Clear all tracked requests."""
        with self._lock:
            self._requests.clear()

            if self._persist_path and self._persist_path.exists():
                self._persist_path.unlink()

    def _filter_requests(
        self,
        since: Optional[datetime],
        until: Optional[datetime],
    ) -> list[RequestCost]:
        """Filter requests by time range."""
        requests = self._requests

        if since:
            requests = [r for r in requests if r.timestamp >= since]

        if until:
            requests = [r for r in requests if r.timestamp <= until]

        return sorted(requests, key=lambda r: r.timestamp)

    def _save_to_disk(self):
        """Persist requests to disk."""
        if not self._persist_path:
            return

        data = [r.to_dict() for r in self._requests[-10000:]]  # Keep last 10k

        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._persist_path, "w") as f:
            json.dump(data, f)

    def _load_from_disk(self):
        """Load requests from disk."""
        if not self._persist_path or not self._persist_path.exists():
            return

        try:
            with open(self._persist_path) as f:
                data = json.load(f)

            for item in data:
                cost = RequestCost(
                    request_id=item["request_id"],
                    model=item["model"],
                    timestamp=datetime.fromisoformat(item["timestamp"]),
                    input_tokens=item["tokens"]["input"],
                    output_tokens=item["tokens"]["output"],
                    cached_tokens=item["tokens"].get("cached", 0),
                    document_type=item.get("document_type"),
                    auction_type=item.get("auction_type"),
                )
                self._requests.append(cost)

        except Exception as e:
            logger.warning(f"Failed to load cost data: {e}")


# Singleton instance
_cost_tracker: Optional[CostTracker] = None
_tracker_lock = threading.Lock()


def get_cost_tracker(persist_path: Optional[Path] = None) -> CostTracker:
    """
    Get or create the cost tracker singleton.

    Args:
        persist_path: Optional path to persist costs

    Returns:
        CostTracker instance
    """
    global _cost_tracker

    with _tracker_lock:
        if _cost_tracker is None:
            default_path = Path(__file__).parent.parent.parent / "data" / "cost_tracking.json"
            _cost_tracker = CostTracker(persist_path or default_path)

        return _cost_tracker


def estimate_extraction_cost(
    text_length: int,
    model: str = "claude-haiku-4-5-20251001",
    use_cache: bool = True,
) -> float:
    """
    Estimate cost for extracting from a document.

    Args:
        text_length: Length of document text in characters
        model: Model to use
        use_cache: Whether prompt caching is enabled

    Returns:
        Estimated cost in USD
    """
    # Rough token estimation: 1 token ≈ 4 chars
    estimated_input_tokens = text_length // 4 + 1000  # +1000 for system prompt
    estimated_output_tokens = 500  # Typical extraction output

    pricing = MODEL_PRICING.get(model, MODEL_PRICING["default"])

    if use_cache:
        # Assume 80% cache hit rate for system prompt
        cached_tokens = int(1000 * 0.8)
        non_cached_tokens = estimated_input_tokens - cached_tokens

        input_cost = non_cached_tokens * pricing["input_per_mtok"] / 1_000_000
        cached_cost = cached_tokens * pricing["cached_input_per_mtok"] / 1_000_000
    else:
        input_cost = estimated_input_tokens * pricing["input_per_mtok"] / 1_000_000
        cached_cost = 0

    output_cost = estimated_output_tokens * pricing["output_per_mtok"] / 1_000_000

    return input_cost + cached_cost + output_cost
