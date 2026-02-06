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


# CD API Location Types
LOCATION_TYPES = [
    "RESIDENCE",
    "BUSINESS",
    "DEALER",
    "AUCTION",
    "PORT",
    "STORAGE_FACILITY",
    "BODY_SHOP",
    "CROSS_DOCK",
    "OTHER",
]


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
    # V2 fields
    location_type: str = Field("CROSS_DOCK", description="CD API location type")
    buyer_reference: Optional[str] = Field(None, max_length=50, description="Broker buyer code (e.g., DAYTONACARGO)")
    broker_id: Optional[int] = Field(None, description="Associated broker ID")

    @field_validator("code")
    @classmethod
    def code_uppercase(cls, v: str) -> str:
        return v.upper()

    @field_validator("location_type")
    @classmethod
    def validate_location_type(cls, v: str) -> str:
        if v not in LOCATION_TYPES:
            raise ValueError(f"Invalid location type. Must be one of: {LOCATION_TYPES}")
        return v


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
    # V2 fields
    location_type: Optional[str] = None
    buyer_reference: Optional[str] = None
    broker_id: Optional[int] = None

    @field_validator("location_type")
    @classmethod
    def validate_location_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in LOCATION_TYPES:
            raise ValueError(f"Invalid location type. Must be one of: {LOCATION_TYPES}")
        return v


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
    # V2 fields
    location_type: str = "CROSS_DOCK"
    buyer_reference: Optional[str] = None
    broker_id: Optional[int] = None
    broker_name: Optional[str] = None  # Joined from brokers table
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
                location_type TEXT DEFAULT 'CROSS_DOCK',
                buyer_reference TEXT,
                broker_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration: Add V2 columns if they don't exist (MUST run before creating indexes on new columns)
        try:
            conn.execute("ALTER TABLE warehouses ADD COLUMN location_type TEXT DEFAULT 'CROSS_DOCK'")
        except Exception:
            pass  # Column exists
        try:
            conn.execute("ALTER TABLE warehouses ADD COLUMN buyer_reference TEXT")
        except Exception:
            pass  # Column exists
        try:
            conn.execute("ALTER TABLE warehouses ADD COLUMN broker_id INTEGER")
        except Exception:
            pass  # Column exists

        # Create indexes (after migrations ensure columns exist)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouses_code ON warehouses(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouses_active ON warehouses(is_active)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouses_state ON warehouses(state)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouses_broker ON warehouses(broker_id)")

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
             is_active, location_type, buyer_reference, broker_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                data.location_type,
                data.buyer_reference,
                data.broker_id,
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
    if data.location_type is not None:
        updates["location_type"] = data.location_type
    if data.buyer_reference is not None:
        updates["buyer_reference"] = data.buyer_reference
    if data.broker_id is not None:
        updates["broker_id"] = data.broker_id

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
# STATE-FIRST SELECTION ENDPOINTS (Block 10)
# =============================================================================


class BrokerWithCount(BaseModel):
    """Broker with warehouse count."""

    id: int
    code: str
    name: str
    warehouse_count: int


@router.get("/states/list", response_model=list[str])
async def list_warehouse_states():
    """
    Get all unique states that have warehouses.
    Used for state-first warehouse selection flow.
    """
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


@router.get("/brokers/by-state", response_model=list[BrokerWithCount])
async def list_brokers_by_state(state: str = Query(..., description="State code (e.g., TX)")):
    """
    Get brokers with warehouses in a specific state.
    Used for state-first warehouse selection flow.
    """
    init_warehouses_schema()

    with get_connection() as conn:
        # First check if brokers table exists
        brokers_exist = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='brokers'"
        ).fetchone()

        if brokers_exist:
            rows = conn.execute(
                """
                SELECT b.id, b.code, b.name, COUNT(w.id) as warehouse_count
                FROM brokers b
                JOIN warehouses w ON w.broker_id = b.id
                WHERE w.is_active = TRUE AND UPPER(w.state) = UPPER(?)
                GROUP BY b.id, b.code, b.name
                ORDER BY b.name ASC
                """,
                (state,),
            ).fetchall()
            return [
                BrokerWithCount(
                    id=row["id"],
                    code=row["code"],
                    name=row["name"],
                    warehouse_count=row["warehouse_count"],
                )
                for row in rows
            ]
        else:
            # Fallback: return warehouses grouped by buyer_reference if no brokers table
            rows = conn.execute(
                """
                SELECT buyer_reference, COUNT(*) as warehouse_count
                FROM warehouses
                WHERE is_active = TRUE AND UPPER(state) = UPPER(?)
                    AND buyer_reference IS NOT NULL AND buyer_reference != ''
                GROUP BY buyer_reference
                ORDER BY buyer_reference ASC
                """,
                (state,),
            ).fetchall()
            return [
                BrokerWithCount(
                    id=0,
                    code=row["buyer_reference"] or "",
                    name=row["buyer_reference"] or "",
                    warehouse_count=row["warehouse_count"],
                )
                for row in rows
            ]


@router.get("/filter", response_model=WarehouseListResponse)
async def filter_warehouses(
    state: Optional[str] = Query(None, description="Filter by state"),
    broker_id: Optional[int] = Query(None, description="Filter by broker ID"),
    buyer_reference: Optional[str] = Query(None, description="Filter by buyer reference code"),
    active_only: bool = Query(True, description="Only return active warehouses"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Filter warehouses by state and/or broker.
    Used for state-first warehouse selection flow.
    """
    init_warehouses_schema()

    sql = "SELECT * FROM warehouses WHERE 1=1"
    params = []

    if active_only:
        sql += " AND is_active = TRUE"
    if state:
        sql += " AND UPPER(state) = UPPER(?)"
        params.append(state)
    if broker_id:
        sql += " AND broker_id = ?"
        params.append(broker_id)
    if buyer_reference:
        sql += " AND buyer_reference = ?"
        params.append(buyer_reference)

    count_sql = sql.replace("SELECT *", "SELECT COUNT(*)")

    sql += " ORDER BY name ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(count_sql, params[:-2] if params else []).fetchone()[0]

    items = [_row_to_response(dict(row)) for row in rows]
    return WarehouseListResponse(items=items, total=total)


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
        location_type=row.get("location_type", "CROSS_DOCK"),
        buyer_reference=row.get("buyer_reference"),
        broker_id=row.get("broker_id"),
        broker_name=row.get("broker_name"),  # From joined query
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )
