"""
Warehouse Management API

Full warehouse CRUD with:
- Business hours (by day of week)
- Timezone support
- Appointment rules
- Contact information
- Gate pass / release requirements
"""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from api.database import get_connection

router = APIRouter(prefix="/api/warehouses", tags=["Warehouses"])


# =============================================================================
# MODELS
# =============================================================================


class BusinessHours(BaseModel):
    """Business hours for a single day."""

    open: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Opening time HH:MM")
    close: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="Closing time HH:MM")
    closed: bool = Field(False, description="Is this day closed")


class WeeklyHours(BaseModel):
    """Weekly business hours."""

    monday: Optional[BusinessHours] = None
    tuesday: Optional[BusinessHours] = None
    wednesday: Optional[BusinessHours] = None
    thursday: Optional[BusinessHours] = None
    friday: Optional[BusinessHours] = None
    saturday: Optional[BusinessHours] = None
    sunday: Optional[BusinessHours] = None


class AppointmentRules(BaseModel):
    """Rules for scheduling appointments."""

    required: bool = Field(False, description="Appointment required for pickup")
    min_notice_hours: int = Field(24, description="Minimum hours notice required")
    max_advance_days: int = Field(7, description="Maximum days in advance to schedule")
    slot_duration_minutes: int = Field(30, description="Duration of each slot")
    slots_per_hour: int = Field(2, description="Number of slots per hour")
    blackout_dates: list[str] = Field(
        default_factory=list, description="Dates unavailable (YYYY-MM-DD)"
    )


class ContactInfo(BaseModel):
    """Contact information."""

    phone: Optional[str] = None
    email: Optional[str] = None
    booking_link: Optional[str] = None
    gate_phone: Optional[str] = None
    notes: Optional[str] = None


class PickupRequirements(BaseModel):
    """Requirements for vehicle pickup."""

    gate_pass_required: bool = Field(False, description="Gate pass needed")
    release_required: bool = Field(False, description="Release document needed")
    id_required: bool = Field(True, description="Valid ID required")
    cdl_required: bool = Field(False, description="CDL required")
    appointment_only: bool = Field(False, description="Appointment only - no walk-ins")
    special_instructions: Optional[str] = None


class WarehouseCreate(BaseModel):
    """Request to create a warehouse."""

    code: str = Field(..., min_length=1, max_length=20, description="Unique code (uppercase)")
    name: str = Field(..., min_length=1, max_length=100)
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: str = Field("US", max_length=2)
    timezone: str = Field("America/New_York", description="IANA timezone")
    hours: Optional[WeeklyHours] = None
    appointment_rules: Optional[AppointmentRules] = None
    contact: Optional[ContactInfo] = None
    requirements: Optional[PickupRequirements] = None
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def code_uppercase(cls, v: str) -> str:
        return v.upper()


class WarehouseUpdate(BaseModel):
    """Request to update a warehouse."""

    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None
    hours: Optional[WeeklyHours] = None
    appointment_rules: Optional[AppointmentRules] = None
    contact: Optional[ContactInfo] = None
    requirements: Optional[PickupRequirements] = None
    is_active: Optional[bool] = None


class WarehouseResponse(BaseModel):
    """Warehouse response."""

    id: int
    code: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: str = "US"
    timezone: str = "America/New_York"
    hours: Optional[WeeklyHours] = None
    appointment_rules: Optional[AppointmentRules] = None
    contact: Optional[ContactInfo] = None
    requirements: Optional[PickupRequirements] = None
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class WarehouseListResponse(BaseModel):
    """Warehouse list response."""

    items: list[WarehouseResponse]
    total: int


# =============================================================================
# SCHEMA INITIALIZATION
# =============================================================================


def init_warehouses_schema():
    """Initialize warehouses table."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS warehouses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                address TEXT,
                city TEXT,
                state TEXT,
                zip_code TEXT,
                country TEXT DEFAULT 'US',
                timezone TEXT DEFAULT 'America/New_York',
                hours_json TEXT,
                appointment_rules_json TEXT,
                contact_json TEXT,
                requirements_json TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouses_code ON warehouses(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouses_active ON warehouses(is_active)")
        conn.commit()


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
            INSERT INTO warehouses
            (code, name, address, city, state, zip_code, country, timezone,
             hours_json, appointment_rules_json, contact_json, requirements_json,
             is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                data.code,
                data.name,
                data.address,
                data.city,
                data.state,
                data.zip_code,
                data.country,
                data.timezone,
                data.hours.model_dump_json() if data.hours else None,
                data.appointment_rules.model_dump_json() if data.appointment_rules else None,
                data.contact.model_dump_json() if data.contact else None,
                data.requirements.model_dump_json() if data.requirements else None,
                data.is_active,
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
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all warehouses."""
    init_warehouses_schema()

    sql = "SELECT * FROM warehouses WHERE 1=1"
    params = []

    if active_only:
        sql += " AND is_active = TRUE"

    sql += " ORDER BY name ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM warehouses" + (" WHERE is_active = TRUE" if active_only else "")
        ).fetchone()[0]

    items = []
    for row in rows:
        items.append(_row_to_response(dict(row)))

    return WarehouseListResponse(items=items, total=total)


@router.get("/{id}", response_model=WarehouseResponse)
async def get_warehouse(id: int):
    """Get a warehouse by ID."""
    init_warehouses_schema()

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM warehouses WHERE id = ?", (id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Warehouse not found")

    return _row_to_response(dict(row))


@router.get("/code/{code}", response_model=WarehouseResponse)
async def get_warehouse_by_code(code: str):
    """Get a warehouse by code."""
    init_warehouses_schema()

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM warehouses WHERE code = ?", (code.upper(),)).fetchone()

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
    if data.address is not None:
        updates["address"] = data.address
    if data.city is not None:
        updates["city"] = data.city
    if data.state is not None:
        updates["state"] = data.state
    if data.zip_code is not None:
        updates["zip_code"] = data.zip_code
    if data.country is not None:
        updates["country"] = data.country
    if data.timezone is not None:
        updates["timezone"] = data.timezone
    if data.hours is not None:
        updates["hours_json"] = data.hours.model_dump_json()
    if data.appointment_rules is not None:
        updates["appointment_rules_json"] = data.appointment_rules.model_dump_json()
    if data.contact is not None:
        updates["contact_json"] = data.contact.model_dump_json()
    if data.requirements is not None:
        updates["requirements_json"] = data.requirements.model_dump_json()
    if data.is_active is not None:
        updates["is_active"] = data.is_active

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


def _row_to_response(row: dict) -> WarehouseResponse:
    """Convert database row to response model."""
    hours = None
    if row.get("hours_json"):
        try:
            hours = WeeklyHours(**json.loads(row["hours_json"]))
        except Exception:
            pass

    appointment_rules = None
    if row.get("appointment_rules_json"):
        try:
            appointment_rules = AppointmentRules(**json.loads(row["appointment_rules_json"]))
        except Exception:
            pass

    contact = None
    if row.get("contact_json"):
        try:
            contact = ContactInfo(**json.loads(row["contact_json"]))
        except Exception:
            pass

    requirements = None
    if row.get("requirements_json"):
        try:
            requirements = PickupRequirements(**json.loads(row["requirements_json"]))
        except Exception:
            pass

    return WarehouseResponse(
        id=row["id"],
        code=row["code"],
        name=row["name"],
        address=row.get("address"),
        city=row.get("city"),
        state=row.get("state"),
        zip_code=row.get("zip_code"),
        country=row.get("country", "US"),
        timezone=row.get("timezone", "America/New_York"),
        hours=hours,
        appointment_rules=appointment_rules,
        contact=contact,
        requirements=requirements,
        is_active=row.get("is_active", True),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )
