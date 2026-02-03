"""
Integrations Module

Aggregates all integration routers:
- ClickUp
- Google Sheets
- Central Dispatch
- Email
- CSV Export
"""

from typing import List, Optional

from fastapi import APIRouter, Query

from api.routes.integrations import cd, clickup, csv_export, email, oauth, sheets, webhook
from api.routes.integrations.utils import (
    AuditLogEntry,
    decrypt_secret,
    encrypt_secret,
    get_audit_log,
    log_integration_action,
    mask_secret,
)

# Main router that includes all sub-routers
router = APIRouter(prefix="/api/integrations", tags=["Integrations"])

# Include all integration routers
router.include_router(clickup.router)
router.include_router(sheets.router)
router.include_router(cd.router)
router.include_router(email.router)
router.include_router(csv_export.router)
router.include_router(oauth.router)
router.include_router(webhook.router)


# =============================================================================
# AUDIT LOG ENDPOINT
# =============================================================================


@router.get("/audit-log", response_model=list[AuditLogEntry])
async def get_integration_audit_log(
    integration: Optional[str] = Query(None, description="Filter by integration"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500),
):
    """Get integration audit log entries."""
    return get_audit_log(integration=integration, status=status, limit=limit)


# =============================================================================
# WAREHOUSE ENDPOINTS (legacy - kept for backwards compatibility)
# =============================================================================

from pydantic import BaseModel, Field


class WarehouseCreate(BaseModel):
    """Request to create a warehouse (legacy)."""

    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=100)
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None


class WarehouseResponse(BaseModel):
    """Warehouse data (legacy)."""

    code: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None


@router.post("/warehouses", response_model=WarehouseResponse)
async def add_warehouse_legacy(warehouse: WarehouseCreate):
    """Add a new warehouse (legacy - use /api/warehouses instead)."""
    from api.routes.settings import load_settings, save_settings

    settings = load_settings()
    warehouses = settings.get("warehouses", [])

    for w in warehouses:
        if w.get("code") == warehouse.code:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400, detail=f"Warehouse with code '{warehouse.code}' already exists"
            )

    new_warehouse = warehouse.model_dump()
    warehouses.append(new_warehouse)
    settings["warehouses"] = warehouses
    save_settings(settings)

    log_integration_action(
        "warehouses", "add", "success", details={"code": warehouse.code, "name": warehouse.name}
    )

    return WarehouseResponse(**new_warehouse)


@router.delete("/warehouses/{code}")
async def delete_warehouse_legacy(code: str):
    """Delete a warehouse by code (legacy - use /api/warehouses instead)."""
    from api.routes.settings import load_settings, save_settings

    settings = load_settings()
    warehouses = settings.get("warehouses", [])

    original_count = len(warehouses)
    warehouses = [w for w in warehouses if w.get("code") != code]

    if len(warehouses) == original_count:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Warehouse with code '{code}' not found")

    settings["warehouses"] = warehouses
    save_settings(settings)

    log_integration_action("warehouses", "delete", "success", details={"code": code})

    return {"status": "ok", "deleted": code}


# Export utilities for use in other modules
__all__ = [
    "router",
    "encrypt_secret",
    "decrypt_secret",
    "mask_secret",
    "log_integration_action",
    "AuditLogEntry",
]
