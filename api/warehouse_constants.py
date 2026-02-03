"""
Warehouse Constants - Warehouse-Specific Field Overrides

Provides field value overrides that are specific to individual warehouses.
These override auction profile defaults but are overridden by user corrections.

Precedence (high to low):
1. USER_OVERRIDE - Manual user correction
2. WAREHOUSE_CONST - This module's values
3. AUCTION_CONST - From auction profile
4. EXTRACTED - From document extraction
5. DEFAULT - Default values

Examples:
- Warehouse "DEN-01" always uses delivery_phone = "303-555-1234"
- Warehouse "LAX-02" requires specific transport_notes
- Warehouse "NYC-01" uses custom gate pass requirements
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from api.database import get_connection


class ApplyWhen(str, Enum):
    """When to apply a constant value."""

    ALWAYS = "always"  # Always use this value
    IF_EMPTY = "if_empty"  # Only if extracted value is empty
    IF_MISSING = "if_missing"  # Only if field is missing


@dataclass
class WarehouseConstant:
    """A single warehouse-specific constant value."""

    field_key: str
    value: Any
    apply_when: str = "if_empty"  # always, if_empty, if_missing
    description: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WarehouseConstants:
    """All constants for a single warehouse."""

    id: Optional[int] = None
    warehouse_id: int = 0
    warehouse_code: str = ""
    constants: dict[str, WarehouseConstant] = field(default_factory=dict)
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "warehouse_id": self.warehouse_id,
            "warehouse_code": self.warehouse_code,
            "constants": {k: v.to_dict() for k, v in self.constants.items()},
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "WarehouseConstants":
        """Create from dictionary."""
        wc = WarehouseConstants(
            id=data.get("id"),
            warehouse_id=data.get("warehouse_id", 0),
            warehouse_code=data.get("warehouse_code", ""),
            is_active=data.get("is_active", True),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

        for key, val in data.get("constants", {}).items():
            if isinstance(val, dict):
                wc.constants[key] = WarehouseConstant(**val)
            else:
                wc.constants[key] = WarehouseConstant(field_key=key, value=val)

        return wc

    def get_value(self, field_key: str) -> Optional[Any]:
        """Get constant value for a field."""
        const = self.constants.get(field_key)
        if const:
            return const.value
        return None

    def should_apply(self, field_key: str, current_value: Any = None) -> bool:
        """Check if constant should be applied."""
        const = self.constants.get(field_key)
        if not const:
            return False

        if const.apply_when == "always":
            return True
        if const.apply_when == "if_empty" and not current_value:
            return True
        if const.apply_when == "if_missing" and current_value is None:
            return True

        return False


# =============================================================================
# DATABASE SCHEMA
# =============================================================================


def init_warehouse_constants_schema():
    """Initialize warehouse constants database schema."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS warehouse_constants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                warehouse_id INTEGER NOT NULL,
                warehouse_code TEXT NOT NULL,
                constants_json TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (warehouse_id) REFERENCES warehouses(id),
                UNIQUE(warehouse_code)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_warehouse_constants_code
            ON warehouse_constants(warehouse_code)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_warehouse_constants_warehouse
            ON warehouse_constants(warehouse_id)
        """)
        conn.commit()


# =============================================================================
# REPOSITORY
# =============================================================================


class WarehouseConstantsRepository:
    """Repository for warehouse constants operations."""

    @staticmethod
    def create(wc: WarehouseConstants) -> int:
        """Create new warehouse constants."""
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO warehouse_constants
                   (warehouse_id, warehouse_code, constants_json, is_active)
                   VALUES (?, ?, ?, ?)""",
                (wc.warehouse_id, wc.warehouse_code, json.dumps(wc.to_dict()), wc.is_active),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(id: int) -> Optional[WarehouseConstants]:
        """Get by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM warehouse_constants WHERE id = ?", (id,)).fetchone()
            if row:
                data = json.loads(row["constants_json"])
                data["id"] = row["id"]
                data["created_at"] = row["created_at"]
                data["updated_at"] = row["updated_at"]
                return WarehouseConstants.from_dict(data)
            return None

    @staticmethod
    def get_by_code(warehouse_code: str) -> Optional[WarehouseConstants]:
        """Get by warehouse code."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM warehouse_constants WHERE warehouse_code = ? AND is_active = TRUE",
                (warehouse_code.upper(),),
            ).fetchone()
            if row:
                data = json.loads(row["constants_json"])
                data["id"] = row["id"]
                data["created_at"] = row["created_at"]
                data["updated_at"] = row["updated_at"]
                return WarehouseConstants.from_dict(data)
            return None

    @staticmethod
    def get_by_warehouse_id(warehouse_id: int) -> Optional[WarehouseConstants]:
        """Get by warehouse ID."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM warehouse_constants WHERE warehouse_id = ? AND is_active = TRUE",
                (warehouse_id,),
            ).fetchone()
            if row:
                data = json.loads(row["constants_json"])
                data["id"] = row["id"]
                data["created_at"] = row["created_at"]
                data["updated_at"] = row["updated_at"]
                return WarehouseConstants.from_dict(data)
            return None

    @staticmethod
    def list_all(include_inactive: bool = False) -> list[WarehouseConstants]:
        """List all warehouse constants."""
        sql = "SELECT * FROM warehouse_constants"
        if not include_inactive:
            sql += " WHERE is_active = TRUE"
        sql += " ORDER BY warehouse_code"

        with get_connection() as conn:
            rows = conn.execute(sql).fetchall()
            result = []
            for row in rows:
                data = json.loads(row["constants_json"])
                data["id"] = row["id"]
                data["created_at"] = row["created_at"]
                data["updated_at"] = row["updated_at"]
                result.append(WarehouseConstants.from_dict(data))
            return result

    @staticmethod
    def update(wc: WarehouseConstants) -> bool:
        """Update warehouse constants."""
        if not wc.id:
            return False

        wc.updated_at = datetime.utcnow().isoformat()

        with get_connection() as conn:
            conn.execute(
                """UPDATE warehouse_constants SET
                   constants_json = ?, is_active = ?, updated_at = ?
                   WHERE id = ?""",
                (json.dumps(wc.to_dict()), wc.is_active, wc.updated_at, wc.id),
            )
            conn.commit()
            return True

    @staticmethod
    def set_constant(
        warehouse_code: str,
        field_key: str,
        value: Any,
        apply_when: str = "if_empty",
        description: str = None,
    ) -> bool:
        """Set a single constant for a warehouse (convenience method)."""
        wc = WarehouseConstantsRepository.get_by_code(warehouse_code)

        if not wc:
            # Get warehouse ID
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT id FROM warehouses WHERE code = ?", (warehouse_code.upper(),)
                ).fetchone()

                if not row:
                    return False

                wc = WarehouseConstants(
                    warehouse_id=row["id"],
                    warehouse_code=warehouse_code.upper(),
                )
                wc.constants[field_key] = WarehouseConstant(
                    field_key=field_key,
                    value=value,
                    apply_when=apply_when,
                    description=description,
                )
                WarehouseConstantsRepository.create(wc)
        else:
            wc.constants[field_key] = WarehouseConstant(
                field_key=field_key,
                value=value,
                apply_when=apply_when,
                description=description,
            )
            WarehouseConstantsRepository.update(wc)

        return True

    @staticmethod
    def delete_constant(warehouse_code: str, field_key: str) -> bool:
        """Remove a single constant from a warehouse."""
        wc = WarehouseConstantsRepository.get_by_code(warehouse_code)
        if not wc:
            return False

        if field_key in wc.constants:
            del wc.constants[field_key]
            WarehouseConstantsRepository.update(wc)
            return True

        return False


# =============================================================================
# SERVICE
# =============================================================================


class WarehouseConstantsService:
    """Service for applying warehouse constants to field values."""

    def __init__(self):
        self._cache: dict[str, WarehouseConstants] = {}

    def get_constants(self, warehouse_code: str) -> Optional[WarehouseConstants]:
        """Get warehouse constants (cached)."""
        code = warehouse_code.upper()
        if code not in self._cache:
            wc = WarehouseConstantsRepository.get_by_code(code)
            if wc:
                self._cache[code] = wc
        return self._cache.get(code)

    def apply_constants(self, warehouse_code: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Apply warehouse constants to field values."""
        wc = self.get_constants(warehouse_code)
        if not wc:
            return fields

        result = dict(fields)

        for field_key, const in wc.constants.items():
            current_value = result.get(field_key)
            if wc.should_apply(field_key, current_value):
                result[field_key] = const.value

        return result

    def get_field_source(
        self, warehouse_code: str, field_key: str, current_value: Any = None
    ) -> Optional[str]:
        """Get the source type if this field would get a warehouse constant."""
        wc = self.get_constants(warehouse_code)
        if wc and wc.should_apply(field_key, current_value):
            return "warehouse_const"
        return None

    def clear_cache(self):
        """Clear the constants cache."""
        self._cache.clear()


# Singleton instance
_constants_service = None


def get_constants_service() -> WarehouseConstantsService:
    """Get or create the constants service singleton."""
    global _constants_service
    if _constants_service is None:
        _constants_service = WarehouseConstantsService()
    return _constants_service
