"""
Broker Reference Data Model

Brokers are companies that operate multiple warehouses across different states.
Example: TRT Logistics has warehouses in TX, GA, CA.

This module provides:
- Broker CRUD operations
- Broker-warehouse relationship management
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from api.database import get_connection


# =============================================================================
# MODELS
# =============================================================================


class BrokerCreate(BaseModel):
    """Request to create a broker."""

    code: str = Field(..., min_length=1, max_length=20, description="Unique code (e.g., TRT, DAYTONACARGO)")
    name: str = Field(..., min_length=1, max_length=100, description="Display name")
    is_active: bool = True


class BrokerUpdate(BaseModel):
    """Request to update a broker."""

    code: Optional[str] = None
    name: Optional[str] = None
    is_active: Optional[bool] = None


class BrokerResponse(BaseModel):
    """Broker response."""

    id: int
    code: str
    name: str
    is_active: bool = True
    warehouse_count: int = 0
    states: list[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BrokerListResponse(BaseModel):
    """Broker list response."""

    items: list[BrokerResponse]
    total: int


# =============================================================================
# SCHEMA INITIALIZATION
# =============================================================================


def init_brokers_schema():
    """Initialize brokers table."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS brokers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_brokers_code ON brokers(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_brokers_active ON brokers(is_active)")
        conn.commit()


# =============================================================================
# REPOSITORY
# =============================================================================


class BrokerRepository:
    """Repository for broker operations."""

    @staticmethod
    def create(data: BrokerCreate) -> int:
        """Create a new broker and return its ID."""
        init_brokers_schema()
        now = datetime.utcnow().isoformat()

        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO brokers (code, name, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (data.code.upper(), data.name, data.is_active, now, now),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(broker_id: int) -> Optional[BrokerResponse]:
        """Get broker by ID with warehouse stats."""
        init_brokers_schema()

        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM brokers WHERE id = ?", (broker_id,)
            ).fetchone()

            if not row:
                return None

            # Get warehouse count and states
            stats = conn.execute(
                """
                SELECT COUNT(*) as count, GROUP_CONCAT(DISTINCT state) as states
                FROM warehouses
                WHERE broker_id = ? AND is_active = TRUE
                """,
                (broker_id,),
            ).fetchone()

            return BrokerResponse(
                id=row["id"],
                code=row["code"],
                name=row["name"],
                is_active=row["is_active"],
                warehouse_count=stats["count"] if stats else 0,
                states=stats["states"].split(",") if stats and stats["states"] else [],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    @staticmethod
    def get_by_code(code: str) -> Optional[BrokerResponse]:
        """Get broker by code."""
        init_brokers_schema()

        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM brokers WHERE code = ?", (code.upper(),)
            ).fetchone()

            if not row:
                return None

            stats = conn.execute(
                """
                SELECT COUNT(*) as count, GROUP_CONCAT(DISTINCT state) as states
                FROM warehouses
                WHERE broker_id = ? AND is_active = TRUE
                """,
                (row["id"],),
            ).fetchone()

            return BrokerResponse(
                id=row["id"],
                code=row["code"],
                name=row["name"],
                is_active=row["is_active"],
                warehouse_count=stats["count"] if stats else 0,
                states=stats["states"].split(",") if stats and stats["states"] else [],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    @staticmethod
    def list_all(active_only: bool = True, limit: int = 100, offset: int = 0) -> BrokerListResponse:
        """List all brokers with warehouse stats."""
        init_brokers_schema()

        sql = """
            SELECT b.*,
                   COUNT(DISTINCT w.id) as warehouse_count,
                   GROUP_CONCAT(DISTINCT w.state) as states
            FROM brokers b
            LEFT JOIN warehouses w ON w.broker_id = b.id AND w.is_active = TRUE
        """
        params = []

        if active_only:
            sql += " WHERE b.is_active = TRUE"

        sql += " GROUP BY b.id ORDER BY b.name ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM brokers" + (" WHERE is_active = TRUE" if active_only else "")
            ).fetchone()[0]

        items = [
            BrokerResponse(
                id=row["id"],
                code=row["code"],
                name=row["name"],
                is_active=row["is_active"],
                warehouse_count=row["warehouse_count"] or 0,
                states=row["states"].split(",") if row["states"] else [],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

        return BrokerListResponse(items=items, total=total)

    @staticmethod
    def update(broker_id: int, data: BrokerUpdate) -> Optional[BrokerResponse]:
        """Update broker."""
        init_brokers_schema()

        updates = {}
        if data.code is not None:
            updates["code"] = data.code.upper()
        if data.name is not None:
            updates["name"] = data.name
        if data.is_active is not None:
            updates["is_active"] = data.is_active

        if not updates:
            return BrokerRepository.get_by_id(broker_id)

        updates["updated_at"] = datetime.utcnow().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [broker_id]

        with get_connection() as conn:
            result = conn.execute(f"UPDATE brokers SET {set_clause} WHERE id = ?", values)
            conn.commit()

            if result.rowcount == 0:
                return None

        return BrokerRepository.get_by_id(broker_id)

    @staticmethod
    def delete(broker_id: int, hard: bool = False) -> bool:
        """Delete broker (soft delete by default)."""
        init_brokers_schema()

        with get_connection() as conn:
            if hard:
                result = conn.execute("DELETE FROM brokers WHERE id = ?", (broker_id,))
            else:
                result = conn.execute(
                    "UPDATE brokers SET is_active = FALSE, updated_at = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), broker_id),
                )
            conn.commit()

            return result.rowcount > 0


# =============================================================================
# SEED DEFAULT BROKERS
# =============================================================================


def seed_default_brokers():
    """Seed default brokers if they don't exist."""
    init_brokers_schema()

    default_brokers = [
        {"code": "TRT", "name": "TRT Logistics"},
        {"code": "DAYTONACARGO", "name": "Daytona Cargo"},
    ]

    for broker_data in default_brokers:
        existing = BrokerRepository.get_by_code(broker_data["code"])
        if not existing:
            BrokerRepository.create(BrokerCreate(**broker_data))
