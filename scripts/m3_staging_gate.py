#!/usr/bin/env python3
"""
M3 Staging Gate Runner

Pre-deployment checklist verification for M3 Production Workflow.
Generates deployment report with all required artifacts.

Usage:
    python scripts/m3_staging_gate.py --full
    python scripts/m3_staging_gate.py --quick  # Skip load tests
    python scripts/m3_staging_gate.py --report-only  # Generate report from existing results
"""

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class CheckResult:
    """Result of a single check."""

    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0


@dataclass
class GateSection:
    """A section of the staging gate checklist."""

    name: str
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)


class M3StagingGate:
    """M3 Staging Gate Runner."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.sections: list[GateSection] = []
        self.artifacts: dict[str, str] = {}

    def run_command(self, cmd: list[str], cwd: Optional[Path] = None, timeout: int = 300) -> tuple:
        """Run a command and return (success, output)."""
        try:
            result = subprocess.run(
                cmd, cwd=cwd or self.project_root, capture_output=True, text=True, timeout=timeout
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, f"Command timed out after {timeout}s"
        except Exception as e:
            return False, str(e)

    # =========================================================================
    # 1. STATIC ANALYSIS & CODE QUALITY
    # =========================================================================

    def check_static_analysis(self) -> GateSection:
        """Gate 1.1: Static analysis and code quality checks."""
        checks = []

        # Ruff lint
        import time

        start = time.time()
        passed, output = self.run_command(["ruff", "check", "."])
        checks.append(
            CheckResult(
                name="Ruff lint (Python)",
                passed=passed,
                message="No linting errors" if passed else "Linting errors found",
                details={"output": output[:1000] if not passed else ""},
                duration_seconds=time.time() - start,
            )
        )

        # Black format check
        start = time.time()
        passed, output = self.run_command(["black", "--check", "--diff", "."])
        checks.append(
            CheckResult(
                name="Black format check",
                passed=passed,
                message="Code is formatted" if passed else "Formatting issues found",
                details={"output": output[:1000] if not passed else ""},
                duration_seconds=time.time() - start,
            )
        )

        # Mypy typecheck (warning only)
        start = time.time()
        passed, output = self.run_command(
            ["mypy", "api/", "extractors/", "--ignore-missing-imports", "--no-error-summary"]
        )
        checks.append(
            CheckResult(
                name="Mypy typecheck",
                passed=True,  # Warning only
                message="Typecheck completed (warnings allowed)",
                details={"output": output[:1000], "strict": False},
                duration_seconds=time.time() - start,
            )
        )

        # Frontend build check
        start = time.time()
        passed, output = self.run_command(["npm", "run", "build"], cwd=self.project_root / "web")
        checks.append(
            CheckResult(
                name="Frontend build (TS check)",
                passed=passed,
                message="Build successful" if passed else "Build failed",
                details={"output": output[:1000] if not passed else ""},
                duration_seconds=time.time() - start,
            )
        )

        # Security: No hardcoded secrets
        start = time.time()
        passed, output = self.run_command(
            [
                "grep",
                "-rn",
                "--include=*.py",
                "-E",
                "(api_key|secret|password)\\s*=\\s*['\"][^'\"]+['\"]",
                "api/",
                "extractors/",
            ]
        )
        # grep returns 1 if no matches (which is what we want)
        no_secrets = not passed
        checks.append(
            CheckResult(
                name="No hardcoded secrets",
                passed=no_secrets,
                message="No secrets found" if no_secrets else "Potential secrets in code",
                details={"matches": output[:500] if passed else ""},
                duration_seconds=time.time() - start,
            )
        )

        return GateSection(name="1. Static Analysis & Code Quality", checks=checks)

    # =========================================================================
    # 2. BACKEND TESTS
    # =========================================================================

    def check_backend_tests(self) -> GateSection:
        """Gate 1.2: Backend tests (unit, integration, regression)."""
        checks = []
        import time

        # Unit tests
        start = time.time()
        passed, output = self.run_command(
            [
                "pytest",
                "tests/test_extractors.py",
                "tests/test_config.py",
                "tests/test_listing_fields.py",
                "-v",
                "--tb=short",
            ]
        )
        checks.append(
            CheckResult(
                name="Unit tests",
                passed=passed,
                message="All unit tests pass" if passed else "Unit test failures",
                details={"output": output[-2000:] if not passed else ""},
                duration_seconds=time.time() - start,
            )
        )

        # Integration tests
        start = time.time()
        passed, output = self.run_command(
            [
                "pytest",
                "tests/test_extraction.py",
                "tests/test_api_contracts.py",
                "-v",
                "--tb=short",
            ]
        )
        checks.append(
            CheckResult(
                name="Integration tests",
                passed=passed,
                message="All integration tests pass" if passed else "Integration test failures",
                details={"output": output[-2000:] if not passed else ""},
                duration_seconds=time.time() - start,
            )
        )

        # Regression/Golden tests
        start = time.time()
        passed, output = self.run_command(
            ["pytest", "tests/test_golden_set.py", "tests/test_cd_v2_golden.py", "-v", "--tb=short"]
        )
        checks.append(
            CheckResult(
                name="Regression/Golden tests",
                passed=passed,
                message="Golden set passes" if passed else "Regression failures",
                details={"output": output[-2000:] if not passed else ""},
                duration_seconds=time.time() - start,
            )
        )

        # M3-specific tests
        start = time.time()
        passed, output = self.run_command(
            ["pytest", "tests/test_m3_staging_gate.py", "-v", "--tb=short"]
        )
        checks.append(
            CheckResult(
                name="M3-specific tests",
                passed=passed,
                message="M3 tests pass" if passed else "M3 test failures",
                details={"output": output[-2000:] if not passed else ""},
                duration_seconds=time.time() - start,
            )
        )

        return GateSection(name="2. Backend Tests", checks=checks)

    # =========================================================================
    # 3. E2E TESTS
    # =========================================================================

    def check_e2e_tests(self) -> GateSection:
        """Gate 1.2: E2E smoke tests."""
        checks = []
        import time

        # Playwright smoke tests
        start = time.time()
        passed, output = self.run_command(
            ["npx", "playwright", "test", "--project=chromium", "--reporter=list"],
            cwd=self.project_root / "e2e",
            timeout=600,
        )
        checks.append(
            CheckResult(
                name="E2E smoke tests (Playwright)",
                passed=passed,
                message="Smoke tests pass" if passed else "E2E failures",
                details={"output": output[-3000:] if not passed else ""},
                duration_seconds=time.time() - start,
            )
        )

        # Save E2E report artifact path
        e2e_report = self.project_root / "e2e" / "playwright-report"
        if e2e_report.exists():
            self.artifacts["e2e_report"] = str(e2e_report)

        return GateSection(name="3. E2E Smoke Tests", checks=checks)

    # =========================================================================
    # 4. DATABASE MIGRATIONS
    # =========================================================================

    def check_migrations(self) -> GateSection:
        """Gate: Database migration tests."""
        checks = []
        import time

        # Test on empty DB
        start = time.time()
        test_db = self.project_root / "test_migration_empty.db"
        if test_db.exists():
            test_db.unlink()

        passed, output = self.run_command(
            [
                "python",
                "-c",
                f"import os; os.environ['DATABASE_URL']='sqlite:///{test_db}'; "
                "from api.database import init_db; init_db(); print('OK')",
            ]
        )
        checks.append(
            CheckResult(
                name="Migration on empty DB",
                passed=passed and "OK" in output,
                message="Empty DB migration OK" if passed else "Migration failed",
                details={"output": output[:500] if not passed else ""},
                duration_seconds=time.time() - start,
            )
        )

        # Cleanup
        if test_db.exists():
            test_db.unlink()

        return GateSection(name="4. Database Migrations", checks=checks)

    # =========================================================================
    # 5. REGRESSION REPORT
    # =========================================================================

    def run_regression_report(self) -> dict[str, Any]:
        """Run regression runner and return report."""
        import time

        time.time()

        report_file = self.project_root / "regression_report.json"
        passed, output = self.run_command(
            [
                "python",
                "-m",
                "tests.regression_runner",
                "--dataset",
                "tests/golden_set/sample_docs",
                "--output",
                str(report_file),
            ]
        )

        if report_file.exists():
            with open(report_file) as f:
                report = json.load(f)
            self.artifacts["regression_report"] = str(report_file)
            return report

        return {"error": output, "passed": False}

    # =========================================================================
    # 6. LOAD TESTS (Optional)
    # =========================================================================

    def check_load_tests(self, batch_size: int = 50) -> GateSection:
        """Gate 4: Load/stress tests."""
        checks = []
        import time

        start = time.time()
        report_file = self.project_root / "load_test_report.json"

        passed, output = self.run_command(
            [
                "python",
                "scripts/load_test_m3.py",
                "--batch-size",
                str(batch_size),
                "--test",
                "batch",  # Just batch for CI
                "--output",
                str(report_file),
            ],
            timeout=1800,
        )  # 30 min timeout

        if report_file.exists():
            with open(report_file) as f:
                report = json.load(f)
            self.artifacts["load_test_report"] = str(report_file)

            # Check p95 target
            tests = report.get("tests", [])
            for test in tests:
                if test.get("test_name") == "batch_extraction":
                    p95_ok = test.get("p95_ms", 99999) < 30000
                    checks.append(
                        CheckResult(
                            name="Batch extraction p95 < 30s",
                            passed=p95_ok,
                            message=f"p95={test.get('p95_ms', 0):.0f}ms",
                            details=test,
                            duration_seconds=time.time() - start,
                        )
                    )
        else:
            checks.append(
                CheckResult(
                    name="Load test execution",
                    passed=False,
                    message="Load test failed to produce report",
                    details={"output": output[-1000:]},
                    duration_seconds=time.time() - start,
                )
            )

        return GateSection(name="5. Load Tests", checks=checks)

    # =========================================================================
    # GENERATE REPORT
    # =========================================================================

    def generate_report(self) -> dict[str, Any]:
        """Generate final deployment report."""
        all_passed = all(s.passed for s in self.sections)

        report = {
            "title": "M3 Staging Gate Report",
            "generated_at": datetime.now().isoformat(),
            "git_commit": self._get_git_commit(),
            "overall_passed": all_passed,
            "sections": [],
            "summary": {
                "total_checks": sum(s.total for s in self.sections),
                "passed_checks": sum(s.passed_count for s in self.sections),
                "sections_passed": sum(1 for s in self.sections if s.passed),
                "sections_total": len(self.sections),
            },
            "artifacts": self.artifacts,
            "known_limitations": [
                "OCR: Max processing time 5 minutes per document",
                "CD Sandbox: Rate limited to 100 requests/minute",
                "Batch: Max 100 documents per batch job",
                "Edge cases: Multi-vehicle invoices not fully supported",
            ],
            "next_steps": [
                "Review E2E report for visual verification",
                "Check regression report for field-level accuracy",
                "Verify load test p95 meets targets",
                "Manual UAT on staging environment",
            ],
        }

        for section in self.sections:
            report["sections"].append(
                {
                    "name": section.name,
                    "passed": section.passed,
                    "checks": [asdict(c) for c in section.checks],
                }
            )

        return report

    def _get_git_commit(self) -> str:
        """Get current git commit hash."""
        passed, output = self.run_command(["git", "rev-parse", "HEAD"])
        return output.strip() if passed else "unknown"

    def run_full_gate(self, skip_load: bool = False) -> dict[str, Any]:
        """Run full staging gate checklist."""
        print("=" * 70)
        print("M3 STAGING GATE - PRE-DEPLOYMENT VERIFICATION")
        print("=" * 70)
        print()

        # 1. Static analysis
        print("Running static analysis checks...")
        self.sections.append(self.check_static_analysis())
        self._print_section_result(self.sections[-1])

        # 2. Backend tests
        print("\nRunning backend tests...")
        self.sections.append(self.check_backend_tests())
        self._print_section_result(self.sections[-1])

        # 3. E2E tests
        print("\nRunning E2E smoke tests...")
        self.sections.append(self.check_e2e_tests())
        self._print_section_result(self.sections[-1])

        # 4. Migrations
        print("\nTesting database migrations...")
        self.sections.append(self.check_migrations())
        self._print_section_result(self.sections[-1])

        # 5. Regression report
        print("\nGenerating regression report...")
        regression = self.run_regression_report()
        if "error" not in regression:
            print(f"  Regression report generated: {self.artifacts.get('regression_report')}")

        # 6. Load tests (optional)
        if not skip_load:
            print("\nRunning load tests (this may take a while)...")
            self.sections.append(self.check_load_tests(batch_size=10))  # Reduced for CI
            self._print_section_result(self.sections[-1])

        # Generate final report
        report = self.generate_report()

        # Write report
        report_path = self.project_root / "m3_staging_gate_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport written to: {report_path}")

        # Print summary
        print("\n" + "=" * 70)
        print("STAGING GATE SUMMARY")
        print("=" * 70)
        print(
            f"  Total checks: {report['summary']['passed_checks']}/{report['summary']['total_checks']}"
        )
        print(
            f"  Sections passed: {report['summary']['sections_passed']}/{report['summary']['sections_total']}"
        )
        print()

        if report["overall_passed"]:
            print("  STATUS: PASSED - Ready for staging deployment")
        else:
            print("  STATUS: FAILED - Fix issues before deployment")
            print("\n  Failed sections:")
            for section in self.sections:
                if not section.passed:
                    print(f"    - {section.name}")
                    for check in section.checks:
                        if not check.passed:
                            print(f"      - {check.name}: {check.message}")

        return report

    def _print_section_result(self, section: GateSection):
        """Print section result."""
        status = "PASS" if section.passed else "FAIL"
        print(f"  [{status}] {section.name}: {section.passed_count}/{section.total}")
        for check in section.checks:
            icon = "+" if check.passed else "x"
            print(f"    [{icon}] {check.name}")


def main():
    parser = argparse.ArgumentParser(description="M3 Staging Gate Runner")
    parser.add_argument("--full", action="store_true", help="Run full gate including load tests")
    parser.add_argument("--quick", action="store_true", help="Skip load tests")
    parser.add_argument(
        "--report-only", action="store_true", help="Generate report from existing results"
    )
    parser.add_argument(
        "--output", type=str, default="m3_staging_gate_report.json", help="Report output file"
    )

    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    gate = M3StagingGate(project_root)

    if args.report_only:
        # Just generate report from existing artifacts
        report = gate.generate_report()
    else:
        skip_load = args.quick or not args.full
        report = gate.run_full_gate(skip_load=skip_load)

    # Exit with appropriate code
    sys.exit(0 if report["overall_passed"] else 1)


if __name__ == "__main__":
    main()
