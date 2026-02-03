"""Settings management endpoints."""

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


# ----- Pydantic Models -----


class ExportTargets(BaseModel):
    """Export target configuration."""

    sheets: bool = False
    clickup: bool = False
    cd: bool = False


class SheetsSettings(BaseModel):
    """Google Sheets settings."""

    enabled: bool = False
    spreadsheet_id: str = ""
    sheet_name: str = "Pickups"
    credentials_file: str = "config/sheets_credentials.json"


class ClickUpSettings(BaseModel):
    """ClickUp settings."""

    enabled: bool = False
    api_token: str = ""
    list_id: str = ""
    workspace_id: str = ""


class CDSettings(BaseModel):
    """Central Dispatch settings."""

    enabled: bool = False
    username: str = ""
    password: str = ""
    shipper_id: str = ""


class EmailSettings(BaseModel):
    """Email ingestion settings."""

    enabled: bool = False
    imap_server: str = ""
    imap_port: int = 993
    email_address: str = ""
    password: str = ""


class WarehouseConfig(BaseModel):
    """Warehouse configuration."""

    id: str
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    is_default: bool = False


class AllSettings(BaseModel):
    """All settings combined."""

    export_targets: ExportTargets
    sheets: SheetsSettings
    clickup: ClickUpSettings
    cd: CDSettings
    email: EmailSettings
    warehouses: list[WarehouseConfig] = []
    schema_version: int = 1


class SettingsStatus(BaseModel):
    """Settings status summary."""

    sheets_configured: bool
    clickup_configured: bool
    cd_configured: bool
    email_configured: bool
    warehouses_count: int
    export_targets: list[str]


# ----- Helper Functions -----


def get_settings_path() -> Path:
    """Get the local settings file path."""
    return Path("config/local_settings.json")


def load_settings() -> dict[str, Any]:
    """Load settings from file."""
    path = get_settings_path()
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_settings(settings: dict[str, Any]):
    """Save settings to file."""
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)


def mask_secret(value: str) -> str:
    """Mask a secret value for display."""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


# ----- Endpoints -----


@router.get("/status", response_model=SettingsStatus)
async def get_settings_status():
    """
    Get a summary of configuration status.

    Shows which integrations are configured without exposing secrets.
    """
    settings = load_settings()

    # Check each integration
    sheets_ok = bool(
        settings.get("sheets", {}).get("spreadsheet_id")
        and Path(settings.get("sheets", {}).get("credentials_file", "")).exists()
    )

    clickup_ok = bool(
        settings.get("clickup", {}).get("api_token") and settings.get("clickup", {}).get("list_id")
    )

    cd_ok = bool(settings.get("cd", {}).get("username") and settings.get("cd", {}).get("password"))

    email_ok = bool(
        settings.get("email", {}).get("email_address") and settings.get("email", {}).get("password")
    )

    warehouses = settings.get("warehouses", [])
    export_targets = settings.get("export_targets", [])

    return SettingsStatus(
        sheets_configured=sheets_ok,
        clickup_configured=clickup_ok,
        cd_configured=cd_ok,
        email_configured=email_ok,
        warehouses_count=len(warehouses),
        export_targets=export_targets,
    )


@router.get("/", response_model=AllSettings)
async def get_all_settings():
    """
    Get all settings (secrets masked).
    """
    settings = load_settings()

    # Build response with masked secrets
    return AllSettings(
        export_targets=ExportTargets(
            sheets="sheets" in settings.get("export_targets", []),
            clickup="clickup" in settings.get("export_targets", []),
            cd="cd" in settings.get("export_targets", []),
        ),
        sheets=SheetsSettings(
            enabled="sheets" in settings.get("export_targets", []),
            spreadsheet_id=settings.get("sheets", {}).get("spreadsheet_id", ""),
            sheet_name=settings.get("sheets", {}).get("sheet_name", "Pickups"),
            credentials_file=settings.get("sheets", {}).get("credentials_file", ""),
        ),
        clickup=ClickUpSettings(
            enabled="clickup" in settings.get("export_targets", []),
            api_token=mask_secret(settings.get("clickup", {}).get("api_token", "")),
            list_id=settings.get("clickup", {}).get("list_id", ""),
            workspace_id=settings.get("clickup", {}).get("workspace_id", ""),
        ),
        cd=CDSettings(
            enabled="cd" in settings.get("export_targets", []),
            username=settings.get("cd", {}).get("username", ""),
            password=mask_secret(settings.get("cd", {}).get("password", "")),
            shipper_id=settings.get("cd", {}).get("shipper_id", ""),
        ),
        email=EmailSettings(
            enabled=settings.get("enable_email_ingest", False),
            imap_server=settings.get("email", {}).get("imap_server", ""),
            imap_port=settings.get("email", {}).get("imap_port", 993),
            email_address=settings.get("email", {}).get("email_address", ""),
            password=mask_secret(settings.get("email", {}).get("password", "")),
        ),
        warehouses=[WarehouseConfig(**w) for w in settings.get("warehouses", [])],
        schema_version=settings.get("schema_version", 1),
    )


@router.put("/export-targets")
async def update_export_targets(targets: ExportTargets):
    """
    Update which export targets are enabled.
    """
    settings = load_settings()

    new_targets = []
    if targets.sheets:
        new_targets.append("sheets")
    if targets.clickup:
        new_targets.append("clickup")
    if targets.cd:
        new_targets.append("cd")

    settings["export_targets"] = new_targets
    save_settings(settings)

    return {"status": "ok", "export_targets": new_targets}


@router.put("/sheets")
async def update_sheets_settings(sheets: SheetsSettings):
    """
    Update Google Sheets settings.
    """
    settings = load_settings()

    settings["sheets"] = {
        "spreadsheet_id": sheets.spreadsheet_id,
        "sheet_name": sheets.sheet_name,
        "credentials_file": sheets.credentials_file,
    }

    # Update export targets
    targets = set(settings.get("export_targets", []))
    if sheets.enabled:
        targets.add("sheets")
    else:
        targets.discard("sheets")
    settings["export_targets"] = list(targets)

    save_settings(settings)

    return {"status": "ok"}


@router.put("/clickup")
async def update_clickup_settings(clickup: ClickUpSettings):
    """
    Update ClickUp settings.
    """
    settings = load_settings()

    # Don't overwrite token if masked value is sent
    existing_token = settings.get("clickup", {}).get("api_token", "")
    new_token = clickup.api_token if "****" not in clickup.api_token else existing_token

    settings["clickup"] = {
        "api_token": new_token,
        "list_id": clickup.list_id,
        "workspace_id": clickup.workspace_id,
    }

    # Update export targets
    targets = set(settings.get("export_targets", []))
    if clickup.enabled:
        targets.add("clickup")
    else:
        targets.discard("clickup")
    settings["export_targets"] = list(targets)

    save_settings(settings)

    return {"status": "ok"}


@router.put("/cd")
async def update_cd_settings(cd: CDSettings):
    """
    Update Central Dispatch settings.
    """
    settings = load_settings()

    # Don't overwrite password if masked value is sent
    existing_pwd = settings.get("cd", {}).get("password", "")
    new_pwd = cd.password if "****" not in cd.password else existing_pwd

    settings["cd"] = {
        "username": cd.username,
        "password": new_pwd,
        "shipper_id": cd.shipper_id,
    }

    # Update export targets
    targets = set(settings.get("export_targets", []))
    if cd.enabled:
        targets.add("cd")
    else:
        targets.discard("cd")
    settings["export_targets"] = list(targets)

    save_settings(settings)

    return {"status": "ok"}


@router.put("/email")
async def update_email_settings(email: EmailSettings):
    """
    Update email ingestion settings.
    """
    settings = load_settings()

    # Don't overwrite password if masked value is sent
    existing_pwd = settings.get("email", {}).get("password", "")
    new_pwd = email.password if "****" not in email.password else existing_pwd

    settings["email"] = {
        "imap_server": email.imap_server,
        "imap_port": email.imap_port,
        "email_address": email.email_address,
        "password": new_pwd,
    }
    settings["enable_email_ingest"] = email.enabled

    save_settings(settings)

    return {"status": "ok"}


@router.get("/warehouses", response_model=list[WarehouseConfig])
async def get_warehouses():
    """Get all configured warehouses."""
    settings = load_settings()
    return [WarehouseConfig(**w) for w in settings.get("warehouses", [])]


@router.put("/warehouses")
async def update_warehouses(warehouses: list[WarehouseConfig]):
    """Update warehouse list."""
    settings = load_settings()
    settings["warehouses"] = [w.model_dump() for w in warehouses]
    save_settings(settings)

    return {"status": "ok", "count": len(warehouses)}


@router.post("/warehouses")
async def add_warehouse(warehouse: WarehouseConfig):
    """Add a new warehouse."""
    settings = load_settings()
    warehouses = settings.get("warehouses", [])

    # Check for duplicate ID
    if any(w["id"] == warehouse.id for w in warehouses):
        raise HTTPException(
            status_code=400, detail=f"Warehouse with ID {warehouse.id} already exists"
        )

    warehouses.append(warehouse.model_dump())
    settings["warehouses"] = warehouses
    save_settings(settings)

    return {"status": "ok", "warehouse_id": warehouse.id}


@router.delete("/warehouses/{warehouse_id}")
async def delete_warehouse(warehouse_id: str):
    """Delete a warehouse by ID."""
    settings = load_settings()
    warehouses = settings.get("warehouses", [])

    original_count = len(warehouses)
    warehouses = [w for w in warehouses if w["id"] != warehouse_id]

    if len(warehouses) == original_count:
        raise HTTPException(status_code=404, detail=f"Warehouse {warehouse_id} not found")

    settings["warehouses"] = warehouses
    save_settings(settings)

    return {"status": "ok", "deleted": warehouse_id}


@router.post("/test-sheets")
async def test_sheets_connection():
    """
    Test Google Sheets connection.

    Attempts to connect to the configured spreadsheet and
    verify read/write access.
    """
    settings = load_settings()
    sheets_config = settings.get("sheets", {})

    if not sheets_config.get("spreadsheet_id"):
        raise HTTPException(status_code=400, detail="Sheets not configured: missing spreadsheet_id")

    creds_file = sheets_config.get("credentials_file", "config/sheets_credentials.json")
    if not Path(creds_file).exists():
        raise HTTPException(status_code=400, detail=f"Credentials file not found: {creds_file}")

    try:
        from core.config import SheetsConfig
        from services.sheets_exporter import SheetsExporter

        config = SheetsConfig(
            spreadsheet_id=sheets_config["spreadsheet_id"],
            sheet_name=sheets_config.get("sheet_name", "Pickups"),
            credentials_file=creds_file,
        )

        exporter = SheetsExporter(config)

        # Test connection by ensuring headers
        headers_created = exporter.ensure_headers()

        return {
            "status": "ok",
            "message": "Successfully connected to Google Sheets",
            "spreadsheet_id": config.spreadsheet_id,
            "sheet_name": config.sheet_name,
            "headers_created": headers_created,
        }

    except ImportError as e:
        raise HTTPException(
            status_code=500, detail=f"Google Sheets dependencies not installed: {e}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to Sheets: {str(e)}")
