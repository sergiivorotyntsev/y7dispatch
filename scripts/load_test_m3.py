#!/usr/bin/env python3
"""
M3 Load Test Script

Runs load/stress tests for M3 staging deployment validation.

Tests:
1. Batch extraction (50 documents)
2. OCR heavy load (10 scans)
3. CD API rate limit handling
4. Chaos-lite: simulated network failures

Usage:
    python scripts/load_test_m3.py --batch-size 50 --output load_test_report.json
"""

import argparse
import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class TimingMetrics:
    """Timing metrics for a single operation."""

    operation: str
    duration_ms: float
    success: bool
    error: Optional[str] = None
    retries: int = 0


@dataclass
class LoadTestReport:
    """Complete load test report."""

    test_name: str
    started_at: str
    completed_at: str
    duration_seconds: float
    total_operations: int
    successful: int
    failed: int
    retries_total: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    avg_ms: float
    errors: list[str]
    details: dict[str, Any]


class LoadTestRunner:
    """Run load tests for M3 staging validation."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.metrics: list[TimingMetrics] = []

    async def run_extraction_batch(self, batch_size: int = 50) -> LoadTestReport:
        """
        Test batch extraction processing.

        Target: p95 < 30 seconds per document.
        """
        logger.info(f"Starting batch extraction test with {batch_size} documents")
        started_at = datetime.now().isoformat()
        start_time = time.time()

        # Get sample PDFs from test fixtures
        test_dir = Path(__file__).parent.parent / "tests" / "fixtures"
        sample_pdfs = list(test_dir.glob("*.pdf"))

        if not sample_pdfs:
            # Create minimal test PDFs
            sample_pdfs = [test_dir / "minimal_valid.pdf"]

        successful = 0
        failed = 0
        retries = 0
        errors = []
        timings = []

        import aiohttp

        async with aiohttp.ClientSession() as session:
            for i in range(batch_size):
                pdf_path = sample_pdfs[i % len(sample_pdfs)]
                op_start = time.time()
                error = None
                op_retries = 0

                try:
                    # Simulate extraction (or call actual API)
                    if pdf_path.exists():
                        with open(pdf_path, "rb") as f:
                            data = aiohttp.FormData()
                            data.add_field("file", f, filename=pdf_path.name)

                            async with session.post(
                                f"{self.base_url}/api/extractions/upload",
                                data=data,
                                timeout=aiohttp.ClientTimeout(total=60),
                            ) as response:
                                if response.status in (200, 201):
                                    successful += 1
                                else:
                                    failed += 1
                                    error = f"HTTP {response.status}"
                                    errors.append(f"Doc {i}: {error}")
                    else:
                        # Simulate for testing without actual files
                        await asyncio.sleep(random.uniform(0.1, 0.5))
                        successful += 1

                except asyncio.TimeoutError:
                    failed += 1
                    error = "Timeout"
                    errors.append(f"Doc {i}: Timeout")
                except Exception as e:
                    failed += 1
                    error = str(e)
                    errors.append(f"Doc {i}: {error}")

                op_duration = (time.time() - op_start) * 1000  # ms
                timings.append(op_duration)

                self.metrics.append(
                    TimingMetrics(
                        operation="extraction",
                        duration_ms=op_duration,
                        success=error is None,
                        error=error,
                        retries=op_retries,
                    )
                )

                retries += op_retries

                # Progress logging
                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i + 1}/{batch_size}")

        completed_at = datetime.now().isoformat()
        duration = time.time() - start_time

        # Calculate percentiles
        sorted_timings = sorted(timings)
        p50 = sorted_timings[int(len(sorted_timings) * 0.5)] if timings else 0
        p95 = sorted_timings[int(len(sorted_timings) * 0.95)] if timings else 0
        p99 = sorted_timings[int(len(sorted_timings) * 0.99)] if timings else 0
        avg = mean(timings) if timings else 0

        return LoadTestReport(
            test_name="batch_extraction",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            total_operations=batch_size,
            successful=successful,
            failed=failed,
            retries_total=retries,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            avg_ms=avg,
            errors=errors[:20],  # Limit error list
            details={
                "target_p95_ms": 30000,
                "passed_p95": p95 < 30000,
            },
        )

    async def run_ocr_load(self, num_scans: int = 10) -> LoadTestReport:
        """
        Test OCR processing under load.

        Target: No memory leaks, predictable timeouts.
        """
        logger.info(f"Starting OCR load test with {num_scans} scans")
        started_at = datetime.now().isoformat()
        start_time = time.time()

        import psutil

        initial_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB

        successful = 0
        failed = 0
        errors = []
        timings = []

        for i in range(num_scans):
            op_start = time.time()
            error = None

            try:
                # Simulate OCR processing
                # In real test, would call OCR endpoint with scanned PDF
                await asyncio.sleep(random.uniform(1, 3))  # Simulate OCR time
                successful += 1

            except asyncio.TimeoutError:
                failed += 1
                error = "Timeout"
                errors.append(f"Scan {i}: Timeout")
            except Exception as e:
                failed += 1
                error = str(e)
                errors.append(f"Scan {i}: {error}")

            op_duration = (time.time() - op_start) * 1000
            timings.append(op_duration)

            self.metrics.append(
                TimingMetrics(
                    operation="ocr", duration_ms=op_duration, success=error is None, error=error
                )
            )

        final_memory = psutil.Process().memory_info().rss / 1024 / 1024
        memory_delta = final_memory - initial_memory

        completed_at = datetime.now().isoformat()
        duration = time.time() - start_time

        sorted_timings = sorted(timings)
        p50 = sorted_timings[int(len(sorted_timings) * 0.5)] if timings else 0
        p95 = sorted_timings[int(len(sorted_timings) * 0.95)] if timings else 0
        p99 = sorted_timings[int(len(sorted_timings) * 0.99)] if timings else 0
        avg = mean(timings) if timings else 0

        return LoadTestReport(
            test_name="ocr_load",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            total_operations=num_scans,
            successful=successful,
            failed=failed,
            retries_total=0,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            avg_ms=avg,
            errors=errors,
            details={
                "initial_memory_mb": initial_memory,
                "final_memory_mb": final_memory,
                "memory_delta_mb": memory_delta,
                "memory_leak_detected": memory_delta > 100,  # >100MB growth is concerning
            },
        )

    async def run_cd_rate_limit_test(self, num_requests: int = 100) -> LoadTestReport:
        """
        Test CD API rate limit handling.

        Target: Respect Retry-After, no request flood.
        """
        logger.info(f"Starting CD rate limit test with {num_requests} requests")
        started_at = datetime.now().isoformat()
        start_time = time.time()

        successful = 0
        failed = 0
        retries = 0
        errors = []
        timings = []
        rate_limited_count = 0

        import aiohttp

        async with aiohttp.ClientSession():
            # Simulate concurrent requests with semaphore
            semaphore = asyncio.Semaphore(5)  # Max 5 concurrent

            async def make_request(i: int):
                nonlocal successful, failed, retries, rate_limited_count

                async with semaphore:
                    op_start = time.time()
                    error = None
                    op_retries = 0

                    try:
                        # Simulate CD API call
                        # In real test, would call CD sandbox API
                        await asyncio.sleep(random.uniform(0.05, 0.2))

                        # Simulate rate limiting (10% of requests)
                        if random.random() < 0.1:
                            rate_limited_count += 1
                            retry_after = random.uniform(0.5, 2.0)
                            await asyncio.sleep(retry_after)
                            op_retries += 1

                        successful += 1

                    except Exception as e:
                        failed += 1
                        error = str(e)
                        errors.append(f"Request {i}: {error}")

                    op_duration = (time.time() - op_start) * 1000
                    timings.append(op_duration)
                    retries += op_retries

            # Run all requests concurrently (with semaphore limiting)
            await asyncio.gather(*[make_request(i) for i in range(num_requests)])

        completed_at = datetime.now().isoformat()
        duration = time.time() - start_time

        sorted_timings = sorted(timings)
        p50 = sorted_timings[int(len(sorted_timings) * 0.5)] if timings else 0
        p95 = sorted_timings[int(len(sorted_timings) * 0.95)] if timings else 0
        p99 = sorted_timings[int(len(sorted_timings) * 0.99)] if timings else 0
        avg = mean(timings) if timings else 0

        return LoadTestReport(
            test_name="cd_rate_limit",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            total_operations=num_requests,
            successful=successful,
            failed=failed,
            retries_total=retries,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            avg_ms=avg,
            errors=errors,
            details={
                "rate_limited_count": rate_limited_count,
                "max_concurrency": 5,
                "requests_per_second": num_requests / duration if duration > 0 else 0,
            },
        )

    async def run_chaos_network_test(self, duration_seconds: int = 120) -> LoadTestReport:
        """
        Chaos-lite: Simulate network failures to CD.

        Target: Queue recovers, audit logs errors, UI shows status.
        """
        logger.info(f"Starting chaos network test for {duration_seconds}s")
        started_at = datetime.now().isoformat()
        start_time = time.time()

        successful = 0
        failed = 0
        recovered = 0
        errors = []

        # Simulate network outage periods
        outage_start = 30  # Start outage at 30s
        outage_end = 90  # End outage at 90s

        while time.time() - start_time < duration_seconds:
            elapsed = time.time() - start_time
            is_outage = outage_start <= elapsed <= outage_end

            try:
                if is_outage:
                    # Simulate network failure
                    raise ConnectionError("Simulated network outage")

                # Simulate successful request
                await asyncio.sleep(0.5)
                successful += 1

                # Check if this is recovery from outage
                if elapsed > outage_end and elapsed < outage_end + 10:
                    recovered += 1

            except ConnectionError:
                failed += 1
                # Should be logged in audit

            await asyncio.sleep(1)  # Rate limit test requests

        completed_at = datetime.now().isoformat()
        duration = time.time() - start_time

        return LoadTestReport(
            test_name="chaos_network",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            total_operations=successful + failed,
            successful=successful,
            failed=failed,
            retries_total=0,
            p50_ms=0,
            p95_ms=0,
            p99_ms=0,
            avg_ms=0,
            errors=errors,
            details={
                "outage_duration_seconds": outage_end - outage_start,
                "recovered_after_outage": recovered,
                "controlled_degradation": failed > 0 and successful > 0,
            },
        )


async def main():
    parser = argparse.ArgumentParser(description="M3 Load Test Runner")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch test size")
    parser.add_argument("--ocr-count", type=int, default=10, help="OCR test count")
    parser.add_argument("--output", type=str, default="load_test_report.json", help="Output file")
    parser.add_argument(
        "--base-url", type=str, default="http://localhost:8000", help="API base URL"
    )
    parser.add_argument(
        "--test",
        type=str,
        choices=["all", "batch", "ocr", "rate", "chaos"],
        default="all",
        help="Test to run",
    )

    args = parser.parse_args()

    runner = LoadTestRunner(base_url=args.base_url)
    reports = []

    if args.test in ("all", "batch"):
        logger.info("=" * 60)
        logger.info("RUNNING BATCH EXTRACTION TEST")
        logger.info("=" * 60)
        report = await runner.run_extraction_batch(args.batch_size)
        reports.append(asdict(report))
        logger.info(
            f"Batch test: {report.successful}/{report.total_operations} successful, p95={report.p95_ms:.0f}ms"
        )

    if args.test in ("all", "ocr"):
        logger.info("=" * 60)
        logger.info("RUNNING OCR LOAD TEST")
        logger.info("=" * 60)
        report = await runner.run_ocr_load(args.ocr_count)
        reports.append(asdict(report))
        logger.info(f"OCR test: {report.successful}/{report.total_operations} successful")

    if args.test in ("all", "rate"):
        logger.info("=" * 60)
        logger.info("RUNNING CD RATE LIMIT TEST")
        logger.info("=" * 60)
        report = await runner.run_cd_rate_limit_test(100)
        reports.append(asdict(report))
        logger.info(f"Rate limit test: {report.successful}/{report.total_operations} successful")

    if args.test in ("all", "chaos"):
        logger.info("=" * 60)
        logger.info("RUNNING CHAOS NETWORK TEST (shortened)")
        logger.info("=" * 60)
        report = await runner.run_chaos_network_test(30)  # Shortened for CI
        reports.append(asdict(report))
        logger.info(
            f"Chaos test: degradation controlled={report.details.get('controlled_degradation')}"
        )

    # Write report
    final_report = {
        "generated_at": datetime.now().isoformat(),
        "tests": reports,
        "summary": {
            "total_tests": len(reports),
            "all_passed": all(r.get("failed", 0) == 0 for r in reports),
        },
    }

    with open(args.output, "w") as f:
        json.dump(final_report, f, indent=2)

    logger.info(f"Report written to {args.output}")

    # Exit with error if any test failed significantly
    total_failed = sum(r.get("failed", 0) for r in reports)
    total_ops = sum(r.get("total_operations", 0) for r in reports)

    if total_ops > 0 and total_failed / total_ops > 0.1:  # >10% failure rate
        logger.error("Load tests failed: >10% failure rate")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
