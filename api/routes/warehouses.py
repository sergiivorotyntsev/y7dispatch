"""
Warehouse Management API - Simplified

Simple warehouse CRUD with only essential fields:
- code, name, state, city, address, zip_code

Supports auto-sync from warehouses.yaml on startup.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from api.database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/warehouses", tags=["Warehouses"])


# =============================================================================
# MODELS - Simplified
# =============================================================================


class WarehouseCreate(BaseModel):
    """Request to create a warehouse."""

    code: str = Field(..., min_length=1, max_length=20, description="Unique code")
    name: str = Field(..., min_length=1, max_length=100)
    state: str = Field(..., min_length=2, max_length=2, description="State code (e.g., TX)")
    city: Optional[str] = None
    address: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    location_type: Optional[str] = "BUSINESS"
    transport_special_instructions: Optional[str] = None
    is_default: bool = False

    @field_validator("code")
    @classmethod
    def code_uppercase(cls, v: str) -> str:
        return v.upper()

    @field_validator("state")
    @classmethod
    def state_uppercase(cls, v: str) -> str:
        return v.upper()


class WarehouseUpdate(BaseModel):
    """Request to update a warehouse."""

    name: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    location_type: Optional[str] = None
    transport_special_instructions: Optional[str] = None
    is_default: Optional[bool] = None

    @field_validator("state")
    @classmethod
    def state_uppercase(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else v


class WarehouseResponse(BaseModel):
    """Warehouse response."""

    id: int
    code: str
    name: str
    state: str
    city: Optional[str] = None
    address: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    location_type: Optional[str] = "BUSINESS"
    transport_special_instructions: Optional[str] = None
    is_default: bool = False
    is_active: bool = True


class WarehouseListResponse(BaseModel):
    """Warehouse list response."""

    items: list[WarehouseResponse]
    total: int


# =============================================================================
# SCHEMA INITIALIZATION
# =============================================================================


def init_warehouses_schema():
    """Initialize warehouses table and sync from YAML if empty."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS warehouses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                state TEXT NOT NULL,
                city TEXT,
                address TEXT,
                zip_code TEXT,
                phone TEXT,
                contact_name TEXT,
                transport_special_instructions TEXT,
                is_default BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Add new columns if they don't exist (migration for existing DBs)
        try:
            conn.execute("ALTER TABLE warehouses ADD COLUMN phone TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE warehouses ADD COLUMN contact_name TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE warehouses ADD COLUMN transport_special_instructions TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE warehouses ADD COLUMN is_default BOOLEAN DEFAULT FALSE")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE warehouses ADD COLUMN contact_phone TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE warehouses ADD COLUMN location_type TEXT DEFAULT 'BUSINESS'")
        except Exception:
            pass

        # Create indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouses_code ON warehouses(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouses_active ON warehouses(is_active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouses_state ON warehouses(state)")

        conn.commit()

        # Auto-sync from YAML if table is empty
        count = conn.execute("SELECT COUNT(*) FROM warehouses").fetchone()[0]
        if count == 0:
            _sync_warehouses_from_yaml(conn)


def _sync_warehouses_from_yaml(conn):
    """Load warehouses from warehouses.yaml into database."""
    yaml_paths = [
        Path("warehouses.yaml"),
        Path(__file__).parent.parent.parent / "warehouses.yaml",
    ]

    yaml_file = None
    for p in yaml_paths:
        if p.exists():
            yaml_file = p
            break

    if not yaml_file:
        logger.warning("warehouses.yaml not found, skipping auto-sync")
        return

    try:
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        warehouses = data.get("warehouses", [])
        now = datetime.utcnow().isoformat()

        for wh in warehouses:
            code = str(wh.get("id", "")).upper()
            if not code:
                continue

            # Check if already exists
            existing = conn.execute("SELECT id FROM warehouses WHERE code = ?", (code,)).fetchone()

            if existing:
                continue

            conn.execute(
                """
                INSERT INTO warehouses (code, name, state, city, address, zip_code, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    wh.get("name", code),
                    wh.get("state", ""),
                    wh.get("city"),
                    wh.get("address"),
                    wh.get("zip_code"),
                    True,
                    now,
                    now,
                ),
            )

        conn.commit()
        logger.info(f"Synced {len(warehouses)} warehouses from {yaml_file}")
    except Exception as e:
        logger.error(f"Failed to sync warehouses from YAML: {e}")


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/", response_model=WarehouseResponse, status_code=201)
async def create_warehouse(data: WarehouseCreate):
    """Create a new warehouse."""
    init_warehouses_schema()

    with get_connection() as conn:
        # Check for duplicate code
        existing = conn.execute("SELECT id FROM warehouses WHERE code = ?", (data.code,)).fetchone()

        if existing:
            raise HTTPException(
                status_code=400, detail=f"Warehouse with code '{data.code}' already exists"
            )

        now = datetime.utcnow().isoformat()

        cursor = conn.execute(
            """
            INSERT INTO warehouses (code, name, state, city, address, zip_code, phone, contact_name, contact_phone, location_type, transport_special_instructions, is_default, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data.code,
                data.name,
                data.state,
                data.city,
                data.address,
                data.zip_code,
                data.phone,
                data.contact_name,
                data.contact_phone,
                data.location_type or "BUSINESS",
                data.transport_special_instructions,
                data.is_default,
                True,
                now,
                now,
            ),
        )
        conn.commit()

        warehouse_id = cursor.lastrowid

    return await get_warehouse(warehouse_id)


@router.get("/", response_model=WarehouseListResponse)
async def list_warehouses(
    active_only: bool = Query(True, description="Only return active warehouses"),
    state: Optional[str] = Query(None, description="Filter by state"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all warehouses."""
    init_warehouses_schema()

    sql = "SELECT * FROM warehouses WHERE 1=1"
    params = []

    if active_only:
        sql += " AND is_active = TRUE"

    if state:
        sql += " AND UPPER(state) = UPPER(?)"
        params.append(state)

    count_sql = sql.replace("SELECT *", "SELECT COUNT(*)")
    count_params = list(params)  # Copy params before adding LIMIT/OFFSET

    sql += " ORDER BY state, name ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(count_sql, count_params).fetchone()[0]

    items = [_row_to_response(dict(row)) for row in rows]
    return WarehouseListResponse(items=items, total=total)


@router.get("/states/list", response_model=list[str])
async def list_warehouse_states():
    """Get all unique states that have warehouses."""
    init_warehouses_schema()

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT state FROM warehouses
            WHERE is_active = TRUE AND state IS NOT NULL AND state != ''
            ORDER BY state ASC
            """
        ).fetchall()

    return [row["state"] for row in rows]


@router.post("/sync-yaml")
async def sync_warehouses_from_yaml():
    """Manually trigger sync from warehouses.yaml. Adds new warehouses, skips existing."""
    init_warehouses_schema()

    yaml_paths = [
        Path("warehouses.yaml"),
        Path(__file__).parent.parent.parent / "warehouses.yaml",
    ]

    yaml_file = None
    for p in yaml_paths:
        if p.exists():
            yaml_file = p
            break

    if not yaml_file:
        raise HTTPException(status_code=404, detail="warehouses.yaml not found")

    try:
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        warehouses = data.get("warehouses", [])
        added = 0
        skipped = 0
        now = datetime.utcnow().isoformat()

        with get_connection() as conn:
            for wh in warehouses:
                code = str(wh.get("id", "")).upper()
                if not code:
                    continue

                existing = conn.execute(
                    "SELECT id FROM warehouses WHERE code = ?", (code,)
                ).fetchone()

                if existing:
                    skipped += 1
                    continue

                conn.execute(
                    """
                    INSERT INTO warehouses (code, name, state, city, address, zip_code, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code,
                        wh.get("name", code),
                        wh.get("state", ""),
                        wh.get("city"),
                        wh.get("address"),
                        wh.get("zip_code"),
                        True,
                        now,
                        now,
                    ),
                )
                added += 1

            conn.commit()

        return {"status": "ok", "added": added, "skipped": skipped, "source": str(yaml_file)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")


@router.get("/{id}", response_model=WarehouseResponse)
async def get_warehouse(id: int):
    """Get a warehouse by ID."""
    init_warehouses_schema()

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM warehouses WHERE id = ?", (id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Warehouse not found")

    return _row_to_response(dict(row))


@router.put("/{id}", response_model=WarehouseResponse)
async def update_warehouse(id: int, data: WarehouseUpdate):
    """Update a warehouse."""
    init_warehouses_schema()

    # Build update fields
    updates = {}
    if data.name is not None:
        updates["name"] = data.name
    if data.state is not None:
        updates["state"] = data.state
    if data.city is not None:
        updates["city"] = data.city
    if data.address is not None:
        updates["address"] = data.address
    if data.zip_code is not None:
        updates["zip_code"] = data.zip_code
    if data.phone is not None:
        updates["phone"] = data.phone
    if data.contact_name is not None:
        updates["contact_name"] = data.contact_name
    if data.contact_phone is not None:
        updates["contact_phone"] = data.contact_phone
    if data.location_type is not None:
        updates["location_type"] = data.location_type
    if data.transport_special_instructions is not None:
        updates["transport_special_instructions"] = data.transport_special_instructions
    if data.is_default is not None:
        updates["is_default"] = data.is_default

    if not updates:
        return await get_warehouse(id)

    updates["updated_at"] = datetime.utcnow().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [id]

    with get_connection() as conn:
        result = conn.execute(f"UPDATE warehouses SET {set_clause} WHERE id = ?", values)
        conn.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Warehouse not found")

    return await get_warehouse(id)


@router.delete("/{id}")
async def delete_warehouse(
    id: int, hard: bool = Query(False, description="Hard delete (permanent)")
):
    """Delete a warehouse (soft delete by default)."""
    init_warehouses_schema()

    with get_connection() as conn:
        if hard:
            result = conn.execute("DELETE FROM warehouses WHERE id = ?", (id,))
        else:
            result = conn.execute(
                "UPDATE warehouses SET is_active = FALSE, updated_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), id),
            )
        conn.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Warehouse not found")

    return {"status": "ok", "deleted": id}


# =============================================================================
# HELPERS
# =============================================================================


def _get_warehouse_by_id(warehouse_id: int) -> Optional[dict]:
    """
    Get warehouse data by ID.
    Returns dict with warehouse fields or None if not found.
    Used by other modules for validation.
    """
    init_warehouses_schema()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM warehouses WHERE id = ?", (warehouse_id,)
        ).fetchone()
    if row:
        return dict(row)
    return None


def _row_to_response(row: dict) -> WarehouseResponse:
    """Convert database row to response model."""
    return WarehouseResponse(
        id=row["id"],
        code=row["code"],
        name=row["name"],
        state=row.get("state", ""),
        city=row.get("city"),
        address=row.get("address"),
        zip_code=row.get("zip_code"),
        phone=row.get("phone"),
        contact_name=row.get("contact_name"),
        contact_phone=row.get("contact_phone"),
        location_type=row.get("location_type", "BUSINESS"),
        transport_special_instructions=row.get("transport_special_instructions"),
        is_default=row.get("is_default", False),
        is_active=row.get("is_active", True),
    )
