"""
Central Dispatch Integration

Endpoints for testing and exporting to Central Dispatch.
"""

import asyncio
import time
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from api.routes.integrations.utils import (
    TestConnectionResponse,
    log_integration_action,
)

router = APIRouter(prefix="/cd", tags=["Central Dispatch"])


class CDDryRunRequest(BaseModel):
    """Request to validate an extraction for CD export."""

    run_id: int


class CDDryRunResponse(BaseModel):
    """Response from CD dry run validation."""

    run_id: int
    is_valid: bool
    payload: dict[str, Any]
    validation_errors: list[str]
    warnings: list[str] = []


class CDExportRequest(BaseModel):
    """Request to export to Central Dispatch."""

    run_id: int


class CDExportResponse(BaseModel):
    """Response from CD export."""

    run_id: int
    status: str
    cd_listing_id: Optional[str] = None
    message: str
    attempts: int = 1


@router.post("/test", response_model=TestConnectionResponse)
async def test_cd_connection():
    """
    Test Central Dispatch API connection.

    Verifies API credentials and marketplace access.
    """
    from api.routes.settings import load_settings

    start_time = time.time()
    settings = load_settings()
    cd = settings.get("cd", {})

    username = cd.get("username")
    password = cd.get("password")
    marketplace_id = cd.get("marketplace_id")
    use_sandbox = cd.get("sandbox", True)

    if not username or not password:
        log_integration_action("cd", "test", "failed", error="CD credentials not configured")
        return TestConnectionResponse(
            status="error",
            message="Central Dispatch not configured. Set username and password in settings.",
        )

    base_url = (
        "https://api.sandbox.centraldispatch.com"
        if use_sandbox
        else "https://api.centraldispatch.com"
    )

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base_url}/user/profile",
                auth=(username, password),
                headers={
                    "Accept": "application/vnd.coxauto.v2+json",
                },
                timeout=15.0,
            )

        duration_ms = int((time.time() - start_time) * 1000)

        if response.status_code == 200:
            data = response.json()
            log_integration_action(
                "cd",
                "test",
                "success",
                details={"environment": "sandbox" if use_sandbox else "production"},
                duration_ms=duration_ms,
            )
            return TestConnectionResponse(
                status="ok",
                message="Connected to Central Dispatch",
                details={
                    "environment": "sandbox" if use_sandbox else "production",
                    "marketplace_id": marketplace_id,
                    "user": data.get("username", username),
                },
                duration_ms=duration_ms,
            )
        elif response.status_code == 401:
            log_integration_action(
                "cd", "test", "failed", error="Invalid credentials", duration_ms=duration_ms
            )
            return TestConnectionResponse(
                status="error",
                message="Invalid credentials",
                duration_ms=duration_ms,
            )
        else:
            error_msg = response.text[:200]
            log_integration_action("cd", "test", "failed", error=error_msg, duration_ms=duration_ms)
            return TestConnectionResponse(
                status="error",
                message=f"CD API error: {response.status_code}",
                details={"error": error_msg},
                duration_ms=duration_ms,
            )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        log_integration_action("cd", "test", "failed", error=str(e), duration_ms=duration_ms)
        return TestConnectionResponse(
            status="error",
            message=f"Connection failed: {str(e)}",
            duration_ms=duration_ms,
        )


@router.post("/dry-run", response_model=CDDryRunResponse)
async def cd_dry_run(data: CDDryRunRequest):
    """
    Validate an extraction run for CD export.

    Checks all required fields and validates format.
    Does not actually send to CD.
    """
    from api.routes.exports import build_cd_payload

    payload, errors = build_cd_payload(data.run_id)

    warnings = []
    if payload.get("price", {}).get("total", 0) <= 0:
        warnings.append("Price is zero - will use default price")

    dropoff = payload.get("stops", [{}])[-1] if payload.get("stops") else {}
    if dropoff.get("address") == "TBD":
        warnings.append("Dropoff address is TBD - update before export")

    log_integration_action(
        "cd",
        "dry_run",
        "success" if not errors else "failed",
        details={
            "run_id": data.run_id,
            "errors": len(errors),
            "warnings": len(warnings),
        },
    )

    return CDDryRunResponse(
        run_id=data.run_id,
        is_valid=len(errors) == 0,
        payload=payload,
        validation_errors=errors,
        warnings=warnings,
    )


@router.post("/export", response_model=CDExportResponse)
async def cd_export_with_retry(data: CDExportRequest):
    """
    Export to Central Dispatch with automatic retry.

    Retries up to 3 times with exponential backoff on failure.
    """
    from api.models import ExportJobRepository, ExtractionRunRepository
    from api.routes.exports import build_cd_payload, send_to_cd
    from api.routes.settings import load_settings

    start_time = time.time()
    settings = load_settings()
    cd = settings.get("cd", {})
    use_sandbox = cd.get("sandbox", True)

    payload, errors = build_cd_payload(data.run_id)

    if errors:
        log_integration_action(
            "cd", "export", "failed", details={"run_id": data.run_id}, error="; ".join(errors)
        )
        return CDExportResponse(
            run_id=data.run_id,
            status="error",
            message=f"Validation failed: {'; '.join(errors)}",
        )

    max_retries = 3
    retry_delays = [2, 4, 8]
    last_error = None

    for attempt in range(max_retries):
        try:
            success, response = send_to_cd(payload, sandbox=use_sandbox)

            if success:
                job_id = ExportJobRepository.create(
                    run_id=data.run_id,
                    target="central_dispatch",
                    payload_json=payload,
                )
                ExportJobRepository.update(
                    job_id,
                    status="completed",
                    response_json=response,
                )
                ExtractionRunRepository.update(data.run_id, status="exported")

                duration_ms = int((time.time() - start_time) * 1000)
                log_integration_action(
                    "cd",
                    "export",
                    "success",
                    details={
                        "run_id": data.run_id,
                        "attempts": attempt + 1,
                        "listing_id": response.get("id"),
                    },
                    duration_ms=duration_ms,
                )

                return CDExportResponse(
                    run_id=data.run_id,
                    status="ok",
                    cd_listing_id=str(response.get("id", "")),
                    message="Successfully exported to Central Dispatch",
                    attempts=attempt + 1,
                )
            else:
                last_error = response.get("error", "Unknown error")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delays[attempt])

        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delays[attempt])

    duration_ms = int((time.time() - start_time) * 1000)
    log_integration_action(
        "cd",
        "export",
        "failed",
        details={"run_id": data.run_id, "attempts": max_retries},
        error=last_error,
        duration_ms=duration_ms,
    )

    return CDExportResponse(
        run_id=data.run_id,
        status="error",
        message=f"Export failed after {max_retries} attempts: {last_error}",
        attempts=max_retries,
    )
