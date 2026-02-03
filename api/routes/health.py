"""Health check endpoints."""

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

# Version info - updated on build/deploy
APP_VERSION = "1.1.0"
BUILD_TIME = datetime.utcnow().isoformat() + "Z"


def get_git_info() -> dict[str, str]:
    """Get git commit info for version tracking."""
    try:
        git_sha = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
        git_branch = (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
        return {"sha": git_sha, "branch": git_branch}
    except Exception:
        return {"sha": "unknown", "branch": "unknown"}


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    git_sha: str
    git_branch: str
    build_time: str
    checks: dict[str, Any]


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.

    Returns system health status including:
    - Database connectivity
    - Required directories
    - Configuration status
    """
    checks = {}
    overall_status = "healthy"

    # Check database
    try:
        from api.database import DB_PATH

        checks["database"] = {
            "status": "ok" if DB_PATH.exists() else "not_initialized",
            "path": str(DB_PATH),
        }
    except Exception as e:
        checks["database"] = {"status": "error", "error": str(e)}
        overall_status = "unhealthy"

    # Check data directories
    data_dirs = ["data", "datasets", "datasets/runs", "config"]
    for dir_name in data_dirs:
        dir_path = Path(dir_name)
        checks[f"dir_{dir_name.replace('/', '_')}"] = {
            "exists": dir_path.exists(),
            "writable": os.access(dir_path, os.W_OK) if dir_path.exists() else False,
        }

    # Check config files
    config_files = {
        "local_settings": "config/local_settings.json",
        "env_file": ".env",
        "sheets_credentials": os.getenv(
            "SHEETS_CREDENTIALS_FILE", "config/sheets_credentials.json"
        ),
    }
    for name, path in config_files.items():
        checks[f"config_{name}"] = {
            "exists": Path(path).exists(),
        }

    # Check export targets
    try:
        from core.config import load_local_settings

        settings = load_local_settings()
        checks["export_targets"] = {
            "enabled": settings.get("export_targets", []),
        }
    except Exception as e:
        checks["export_targets"] = {"status": "error", "error": str(e)}

    git_info = get_git_info()

    return HealthResponse(
        status=overall_status,
        version=APP_VERSION,
        git_sha=git_info["sha"],
        git_branch=git_info["branch"],
        build_time=BUILD_TIME,
        checks=checks,
    )


@router.get("/ready")
async def readiness_check():
    """Simple readiness probe for k8s/docker."""
    return {"ready": True}


@router.get("/live")
async def liveness_check():
    """Simple liveness probe for k8s/docker."""
    return {"alive": True}
