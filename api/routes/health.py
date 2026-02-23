"""Health check endpoints."""

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

# Version info - updated on build/deploy
APP_VERSION = "1.1.0"
BUILD_TIME = datetime.now(timezone.utc).isoformat() + "Z"


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

    # Check API keys
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    checks["anthropic_api"] = {
        "configured": bool(anthropic_key and anthropic_key != "sk-ant-your-key-here"),
    }

    # Check email credentials via credential store
    try:
        from api.database import get_connection
        with get_connection() as conn:
            email_cred = conn.execute(
                "SELECT id FROM credential_store WHERE service = 'email' LIMIT 1"
            ).fetchone()
            checks["email_config"] = {
                "configured": email_cred is not None,
            }
    except Exception:
        checks["email_config"] = {"configured": False}

    # Check CD API credentials
    cd_id = os.getenv("CD_CLIENT_ID", "")
    checks["cd_api"] = {
        "configured": bool(cd_id and cd_id != "your-client-id"),
    }

    # Database table counts (quick health indicator)
    try:
        from api.database import get_connection
        counts = {}
        with get_connection() as conn:
            for table in ("documents", "extraction_runs", "email_log"):
                try:
                    row = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()
                    counts[table] = row["c"]
                except Exception:
                    counts[table] = -1  # table doesn't exist
        checks["data_counts"] = counts
    except Exception:
        checks["data_counts"] = {}

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
