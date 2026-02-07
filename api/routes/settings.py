"""Settings management endpoints."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.database import get_connection
from api.listing_fields import (
    FieldCategory,
    FieldSourceType,
    get_registry,
)

logger = logging.getLogger(__name__)

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


# =============================================================================
# FIELD TAXONOMY ENDPOINTS
# =============================================================================


@router.get("/fields/schema")
async def get_field_schema():
    """
    Get the complete field schema including taxonomy.

    Returns all fields with their:
    - category (cd_required, cd_optional, internal)
    - source_type (extracted, constant, warehouse_ref, user_input, computed)
    - validation rules
    - display settings
    """
    registry = get_registry()
    return registry.to_json_schema()


@router.get("/fields/taxonomy")
async def get_field_taxonomy():
    """
    Get a summary of field taxonomy for Settings UI.

    Returns:
    - Count and list of CD_REQUIRED fields
    - Count and list of CD_OPTIONAL fields
    - Count and list of INTERNAL fields
    - Fields grouped by source type
    """
    registry = get_registry()
    return registry.get_taxonomy_summary()


@router.get("/fields/by-category/{category}")
async def get_fields_by_category(category: str):
    """
    Get all fields for a specific category.

    Categories:
    - cd_required: Required for Central Dispatch API
    - cd_optional: Optional in CD API
    - internal: Not sent to CD API
    """
    try:
        cat = FieldCategory(category)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {[c.value for c in FieldCategory]}",
        )

    registry = get_registry()
    fields = registry.get_fields_by_category(cat)

    return {
        "category": category,
        "count": len(fields),
        "fields": [
            {
                "key": f.key,
                "label": f.label,
                "section": f.section.value,
                "source_type": f.source_type.value,
                "required": f.required,
                "export_only": f.export_only,
            }
            for f in fields
        ],
    }


@router.get("/fields/by-source/{source_type}")
async def get_fields_by_source(source_type: str):
    """
    Get all fields for a specific source type.

    Source types:
    - extracted: Value extracted from document
    - constant: Static default value
    - warehouse_ref: Value from warehouse reference data
    - user_input: Value entered manually by user
    - computed: Value computed from other fields
    """
    try:
        st = FieldSourceType(source_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source type. Must be one of: {[s.value for s in FieldSourceType]}",
        )

    registry = get_registry()
    fields = registry.get_fields_by_source_type(st)

    return {
        "source_type": source_type,
        "count": len(fields),
        "fields": [
            {
                "key": f.key,
                "label": f.label,
                "section": f.section.value,
                "category": f.category.value,
                "extraction_hint": f.extraction_hint,
            }
            for f in fields
        ],
    }


@router.get("/fields/for-mode/{mode}")
async def get_fields_for_mode(mode: str):
    """
    Get fields relevant for a specific mode.

    Modes:
    - training: Fields for extraction review (no export_only fields)
    - review: All visible fields
    - export: All CD API fields (required + optional)
    """
    if mode not in ["training", "review", "export"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid mode. Must be one of: training, review, export",
        )

    registry = get_registry()
    fields = registry.get_fields_for_mode(mode)

    return {
        "mode": mode,
        "count": len(fields),
        "fields": [
            {
                "key": f.key,
                "label": f.label,
                "section": f.section.value,
                "category": f.category.value,
                "source_type": f.source_type.value,
                "required": f.required,
                "editable_in_review": f.editable_in_review,
            }
            for f in fields
        ],
    }


@router.get("/fields/extracted")
async def get_extracted_fields():
    """
    Get all fields that should be extracted from documents.

    These are fields with source_type = EXTRACTED.
    Useful for configuring extraction rules and validation.
    """
    registry = get_registry()
    fields = registry.get_extracted_fields()

    return {
        "count": len(fields),
        "fields": [
            {
                "key": f.key,
                "label": f.label,
                "section": f.section.value,
                "category": f.category.value,
                "extraction_hint": f.extraction_hint,
                "validation_regex": f.validation_regex,
            }
            for f in fields
        ],
    }


# =============================================================================
# FIELD CONFIGURATION PERSISTENCE
# =============================================================================


class FieldConfigUpdate(BaseModel):
    """Single field config update."""

    field_key: str
    source_type: Optional[str] = None
    default_value: Optional[str] = None
    is_required: Optional[bool] = None
    is_editable: Optional[bool] = None


class FieldConfigsBatchUpdate(BaseModel):
    """Batch update for field configs."""

    updates: dict[str, dict[str, Any]]  # field_key -> {source_type, default_value, ...}


class FieldConfigResponse(BaseModel):
    """Field config response."""

    field_key: str
    source_type: str
    default_value: Optional[str] = None
    is_required: bool = False
    is_editable: bool = True
    updated_at: Optional[str] = None


def _init_field_configs_table():
    """Initialize field_configs table for storing user overrides."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS field_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                field_key TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL DEFAULT 'extracted',
                default_value TEXT,
                is_required BOOLEAN DEFAULT FALSE,
                is_editable BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_field_configs_key ON field_configs(field_key)")
        conn.commit()


@router.get("/fields/configs")
async def get_field_configs():
    """
    Get all user-configured field overrides.

    Returns field configurations that override the default taxonomy.
    """
    _init_field_configs_table()

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM field_configs ORDER BY field_key"
        ).fetchall()

    return {
        "configs": [
            FieldConfigResponse(
                field_key=row["field_key"],
                source_type=row["source_type"],
                default_value=row["default_value"],
                is_required=bool(row["is_required"]),
                is_editable=bool(row["is_editable"]),
                updated_at=row["updated_at"],
            )
            for row in rows
        ]
    }


@router.put("/fields/configs")
async def update_field_configs(data: FieldConfigsBatchUpdate):
    """
    Batch update field configurations.

    Accepts a dict of field_key -> config updates.
    Creates new configs or updates existing ones.
    """
    _init_field_configs_table()

    now = datetime.utcnow().isoformat()
    updated = 0
    created = 0

    with get_connection() as conn:
        for field_key, updates in data.updates.items():
            # Check if exists
            existing = conn.execute(
                "SELECT id FROM field_configs WHERE field_key = ?",
                (field_key,)
            ).fetchone()

            if existing:
                # Build update
                set_parts = ["updated_at = ?"]
                params = [now]

                if "source_type" in updates:
                    set_parts.append("source_type = ?")
                    params.append(updates["source_type"])
                if "default_value" in updates:
                    set_parts.append("default_value = ?")
                    params.append(updates["default_value"])
                if "is_required" in updates or "required" in updates:
                    set_parts.append("is_required = ?")
                    params.append(updates.get("is_required", updates.get("required", False)))
                if "is_editable" in updates or "editable_in_review" in updates:
                    set_parts.append("is_editable = ?")
                    params.append(updates.get("is_editable", updates.get("editable_in_review", True)))

                params.append(field_key)
                conn.execute(
                    f"UPDATE field_configs SET {', '.join(set_parts)} WHERE field_key = ?",
                    params
                )
                updated += 1
            else:
                # Insert new
                conn.execute(
                    """
                    INSERT INTO field_configs
                    (field_key, source_type, default_value, is_required, is_editable, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        field_key,
                        updates.get("source_type", "extracted"),
                        updates.get("default_value"),
                        updates.get("is_required", updates.get("required", False)),
                        updates.get("is_editable", updates.get("editable_in_review", True)),
                        now,
                        now,
                    )
                )
                created += 1

        conn.commit()

    logger.info(f"Field configs: updated={updated}, created={created}")
    return {"status": "ok", "updated": updated, "created": created}


@router.put("/fields/configs/{field_key}")
async def update_single_field_config(field_key: str, data: FieldConfigUpdate):
    """
    Update a single field configuration.
    """
    _init_field_configs_table()

    now = datetime.utcnow().isoformat()

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM field_configs WHERE field_key = ?",
            (field_key,)
        ).fetchone()

        if existing:
            set_parts = ["updated_at = ?"]
            params = [now]

            if data.source_type is not None:
                set_parts.append("source_type = ?")
                params.append(data.source_type)
            if data.default_value is not None:
                set_parts.append("default_value = ?")
                params.append(data.default_value)
            if data.is_required is not None:
                set_parts.append("is_required = ?")
                params.append(data.is_required)
            if data.is_editable is not None:
                set_parts.append("is_editable = ?")
                params.append(data.is_editable)

            params.append(field_key)
            conn.execute(
                f"UPDATE field_configs SET {', '.join(set_parts)} WHERE field_key = ?",
                params
            )
        else:
            conn.execute(
                """
                INSERT INTO field_configs
                (field_key, source_type, default_value, is_required, is_editable, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    field_key,
                    data.source_type or "extracted",
                    data.default_value,
                    data.is_required or False,
                    data.is_editable if data.is_editable is not None else True,
                    now,
                    now,
                )
            )

        conn.commit()

    return {"status": "ok", "field_key": field_key}


@router.delete("/fields/configs/{field_key}")
async def delete_field_config(field_key: str):
    """
    Delete a field configuration (revert to default).
    """
    _init_field_configs_table()

    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM field_configs WHERE field_key = ?",
            (field_key,)
        )
        conn.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Config for {field_key} not found")

    return {"status": "ok", "deleted": field_key}
