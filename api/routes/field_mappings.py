"""
Field Mappings / Templates API

Manage extraction field mappings for each auction type:
- Define fields to extract
- Map to internal/CD keys
- Configure validation rules
- Version control templates
"""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.database import get_connection

router = APIRouter(prefix="/api/templates", tags=["Templates"])


# =============================================================================
# MODELS
# =============================================================================


class FieldMappingCreate(BaseModel):
    """Create a field mapping."""

    source_key: str = Field(..., min_length=1, max_length=100)
    internal_key: str = Field(..., min_length=1, max_length=100)
    cd_key: Optional[str] = Field(None, max_length=100, description="Central Dispatch API key")
    display_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    field_type: str = Field("text", description="text, date, number, boolean, address, vin")
    is_required: bool = False
    default_value: Optional[str] = None
    validation_regex: Optional[str] = None
    validation_message: Optional[str] = None
    transform: Optional[str] = Field(
        None, description="Transform function: uppercase, lowercase, trim, date_format"
    )
    extraction_hints: Optional[list[str]] = Field(
        None, description="Keywords/patterns to help extraction"
    )
    display_order: int = Field(0, ge=0)
    is_active: bool = True


class FieldMappingUpdate(BaseModel):
    """Update a field mapping."""

    source_key: Optional[str] = None
    internal_key: Optional[str] = None
    cd_key: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    field_type: Optional[str] = None
    is_required: Optional[bool] = None
    default_value: Optional[str] = None
    validation_regex: Optional[str] = None
    validation_message: Optional[str] = None
    transform: Optional[str] = None
    extraction_hints: Optional[list[str]] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class FieldMappingResponse(BaseModel):
    """Field mapping response."""

    id: int
    auction_type_id: int
    source_key: str
    internal_key: str
    cd_key: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    field_type: str = "text"
    is_required: bool = False
    default_value: Optional[str] = None
    validation_regex: Optional[str] = None
    validation_message: Optional[str] = None
    transform: Optional[str] = None
    extraction_hints: Optional[list[str]] = None
    display_order: int = 0
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TemplateVersionCreate(BaseModel):
    """Create a template version."""

    version_tag: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None
    is_active: bool = False


class TemplateVersionResponse(BaseModel):
    """Template version response."""

    id: int
    auction_type_id: int
    version_tag: str
    description: Optional[str] = None
    is_active: bool = False
    field_count: int = 0
    created_at: Optional[str] = None


class TemplateResponse(BaseModel):
    """Full template with fields."""

    auction_type_id: int
    auction_type_code: str
    auction_type_name: str
    active_version: Optional[str] = None
    versions: list[TemplateVersionResponse]
    fields: list[FieldMappingResponse]


# =============================================================================
# SCHEMA EXTENSIONS
# =============================================================================


def init_template_schema():
    """Initialize template versioning tables."""
    with get_connection() as conn:
        # Template versions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS template_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_type_id INTEGER NOT NULL,
                version_tag TEXT NOT NULL,
                description TEXT,
                is_active BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (auction_type_id) REFERENCES auction_types(id),
                UNIQUE(auction_type_id, version_tag)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_template_versions_auction
            ON template_versions(auction_type_id)
        """)

        # Add new columns to field_mappings if not exist
        try:
            conn.execute("ALTER TABLE field_mappings ADD COLUMN display_name TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE field_mappings ADD COLUMN field_type TEXT DEFAULT 'text'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE field_mappings ADD COLUMN validation_message TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE field_mappings ADD COLUMN extraction_hints_json TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE field_mappings ADD COLUMN template_version_id INTEGER")
        except Exception:
            pass

        conn.commit()


# =============================================================================
# ROUTES - TEMPLATES
# =============================================================================


@router.get("/", response_model=list[TemplateResponse])
async def list_templates():
    """List all templates (one per auction type)."""
    init_template_schema()

    with get_connection() as conn:
        # Get all auction types
        auction_types = conn.execute(
            "SELECT id, code, name FROM auction_types WHERE is_active = TRUE ORDER BY name"
        ).fetchall()

        templates = []
        for at in auction_types:
            # Get versions
            versions = conn.execute(
                """SELECT * FROM template_versions
                   WHERE auction_type_id = ? ORDER BY created_at DESC""",
                (at["id"],),
            ).fetchall()

            # Get active version
            active_version = None
            for v in versions:
                if v["is_active"]:
                    active_version = v["version_tag"]
                    break

            # Get fields
            fields = conn.execute(
                """SELECT * FROM field_mappings
                   WHERE auction_type_id = ? AND is_active = TRUE
                   ORDER BY display_order, source_key""",
                (at["id"],),
            ).fetchall()

            templates.append(
                TemplateResponse(
                    auction_type_id=at["id"],
                    auction_type_code=at["code"],
                    auction_type_name=at["name"],
                    active_version=active_version,
                    versions=[
                        TemplateVersionResponse(
                            id=v["id"],
                            auction_type_id=v["auction_type_id"],
                            version_tag=v["version_tag"],
                            description=v["description"],
                            is_active=v["is_active"],
                            field_count=len(list(fields)),
                            created_at=v["created_at"],
                        )
                        for v in versions
                    ],
                    fields=[_row_to_field(dict(f)) for f in fields],
                )
            )

    return templates


@router.get("/{auction_type_id}", response_model=TemplateResponse)
async def get_template(auction_type_id: int):
    """Get template for an auction type."""
    init_template_schema()

    with get_connection() as conn:
        at = conn.execute(
            "SELECT id, code, name FROM auction_types WHERE id = ?", (auction_type_id,)
        ).fetchone()

        if not at:
            raise HTTPException(status_code=404, detail="Auction type not found")

        # Get versions
        versions = conn.execute(
            """SELECT * FROM template_versions
               WHERE auction_type_id = ? ORDER BY created_at DESC""",
            (auction_type_id,),
        ).fetchall()

        active_version = None
        for v in versions:
            if v["is_active"]:
                active_version = v["version_tag"]
                break

        # Get fields
        fields = conn.execute(
            """SELECT * FROM field_mappings
               WHERE auction_type_id = ? AND is_active = TRUE
               ORDER BY display_order, source_key""",
            (auction_type_id,),
        ).fetchall()

    return TemplateResponse(
        auction_type_id=at["id"],
        auction_type_code=at["code"],
        auction_type_name=at["name"],
        active_version=active_version,
        versions=[
            TemplateVersionResponse(
                id=v["id"],
                auction_type_id=v["auction_type_id"],
                version_tag=v["version_tag"],
                description=v["description"],
                is_active=v["is_active"],
                field_count=len(fields),
                created_at=v["created_at"],
            )
            for v in versions
        ],
        fields=[_row_to_field(dict(f)) for f in fields],
    )


# =============================================================================
# ROUTES - VERSIONS
# =============================================================================


@router.post("/{auction_type_id}/versions", response_model=TemplateVersionResponse)
async def create_template_version(auction_type_id: int, data: TemplateVersionCreate):
    """Create a new template version."""
    init_template_schema()

    with get_connection() as conn:
        # Verify auction type exists
        at = conn.execute(
            "SELECT id FROM auction_types WHERE id = ?", (auction_type_id,)
        ).fetchone()
        if not at:
            raise HTTPException(status_code=404, detail="Auction type not found")

        # Check for duplicate version
        existing = conn.execute(
            "SELECT id FROM template_versions WHERE auction_type_id = ? AND version_tag = ?",
            (auction_type_id, data.version_tag),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=400, detail=f"Version '{data.version_tag}' already exists"
            )

        # If setting as active, deactivate others
        if data.is_active:
            conn.execute(
                "UPDATE template_versions SET is_active = FALSE WHERE auction_type_id = ?",
                (auction_type_id,),
            )

        cursor = conn.execute(
            """INSERT INTO template_versions (auction_type_id, version_tag, description, is_active)
               VALUES (?, ?, ?, ?)""",
            (auction_type_id, data.version_tag, data.description, data.is_active),
        )
        conn.commit()

        version_id = cursor.lastrowid

        # Get field count
        field_count = conn.execute(
            "SELECT COUNT(*) FROM field_mappings WHERE auction_type_id = ? AND is_active = TRUE",
            (auction_type_id,),
        ).fetchone()[0]

    return TemplateVersionResponse(
        id=version_id,
        auction_type_id=auction_type_id,
        version_tag=data.version_tag,
        description=data.description,
        is_active=data.is_active,
        field_count=field_count,
        created_at=datetime.utcnow().isoformat(),
    )


@router.put("/{auction_type_id}/versions/{version_tag}/activate")
async def activate_template_version(auction_type_id: int, version_tag: str):
    """Activate a template version."""
    init_template_schema()

    with get_connection() as conn:
        # Deactivate all versions
        conn.execute(
            "UPDATE template_versions SET is_active = FALSE WHERE auction_type_id = ?",
            (auction_type_id,),
        )

        # Activate requested version
        result = conn.execute(
            "UPDATE template_versions SET is_active = TRUE WHERE auction_type_id = ? AND version_tag = ?",
            (auction_type_id, version_tag),
        )
        conn.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Version not found")

    return {"status": "ok", "activated": version_tag}


# =============================================================================
# ROUTES - FIELDS
# =============================================================================


@router.get("/{auction_type_id}/fields", response_model=list[FieldMappingResponse])
async def list_fields(
    auction_type_id: int,
    include_inactive: bool = Query(False),
):
    """List fields for an auction type."""
    init_template_schema()

    sql = "SELECT * FROM field_mappings WHERE auction_type_id = ?"
    params = [auction_type_id]

    if not include_inactive:
        sql += " AND is_active = TRUE"

    sql += " ORDER BY display_order, source_key"

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [_row_to_field(dict(row)) for row in rows]


@router.post("/{auction_type_id}/fields", response_model=FieldMappingResponse)
async def create_field(auction_type_id: int, data: FieldMappingCreate):
    """Create a new field mapping."""
    init_template_schema()

    with get_connection() as conn:
        # Check for duplicate source_key
        existing = conn.execute(
            "SELECT id FROM field_mappings WHERE auction_type_id = ? AND source_key = ?",
            (auction_type_id, data.source_key),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail=f"Field '{data.source_key}' already exists")

        now = datetime.utcnow().isoformat()

        cursor = conn.execute(
            """
            INSERT INTO field_mappings
            (auction_type_id, source_key, internal_key, cd_key, display_name, description,
             field_type, is_required, default_value, validation_regex, validation_message,
             transform, extraction_hints_json, display_order, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                auction_type_id,
                data.source_key,
                data.internal_key,
                data.cd_key,
                data.display_name,
                data.description,
                data.field_type,
                data.is_required,
                data.default_value,
                data.validation_regex,
                data.validation_message,
                data.transform,
                json.dumps(data.extraction_hints) if data.extraction_hints else None,
                data.display_order,
                data.is_active,
                now,
                now,
            ),
        )
        conn.commit()

        field_id = cursor.lastrowid

    return await get_field(auction_type_id, field_id)


@router.get("/{auction_type_id}/fields/{field_id}", response_model=FieldMappingResponse)
async def get_field(auction_type_id: int, field_id: int):
    """Get a specific field mapping."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM field_mappings WHERE id = ? AND auction_type_id = ?",
            (field_id, auction_type_id),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Field not found")

    return _row_to_field(dict(row))


@router.put("/{auction_type_id}/fields/{field_id}", response_model=FieldMappingResponse)
async def update_field(auction_type_id: int, field_id: int, data: FieldMappingUpdate):
    """Update a field mapping."""
    updates = {}

    if data.source_key is not None:
        updates["source_key"] = data.source_key
    if data.internal_key is not None:
        updates["internal_key"] = data.internal_key
    if data.cd_key is not None:
        updates["cd_key"] = data.cd_key
    if data.display_name is not None:
        updates["display_name"] = data.display_name
    if data.description is not None:
        updates["description"] = data.description
    if data.field_type is not None:
        updates["field_type"] = data.field_type
    if data.is_required is not None:
        updates["is_required"] = data.is_required
    if data.default_value is not None:
        updates["default_value"] = data.default_value
    if data.validation_regex is not None:
        updates["validation_regex"] = data.validation_regex
    if data.validation_message is not None:
        updates["validation_message"] = data.validation_message
    if data.transform is not None:
        updates["transform"] = data.transform
    if data.extraction_hints is not None:
        updates["extraction_hints_json"] = json.dumps(data.extraction_hints)
    if data.display_order is not None:
        updates["display_order"] = data.display_order
    if data.is_active is not None:
        updates["is_active"] = data.is_active

    if not updates:
        return await get_field(auction_type_id, field_id)

    updates["updated_at"] = datetime.utcnow().isoformat()

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [field_id, auction_type_id]

    with get_connection() as conn:
        result = conn.execute(
            f"UPDATE field_mappings SET {set_clause} WHERE id = ? AND auction_type_id = ?", values
        )
        conn.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Field not found")

    return await get_field(auction_type_id, field_id)


@router.delete("/{auction_type_id}/fields/{field_id}")
async def delete_field(
    auction_type_id: int,
    field_id: int,
    hard: bool = Query(False, description="Hard delete (permanent)"),
):
    """Delete a field mapping."""
    with get_connection() as conn:
        if hard:
            result = conn.execute(
                "DELETE FROM field_mappings WHERE id = ? AND auction_type_id = ?",
                (field_id, auction_type_id),
            )
        else:
            result = conn.execute(
                """UPDATE field_mappings SET is_active = FALSE, updated_at = ?
                   WHERE id = ? AND auction_type_id = ?""",
                (datetime.utcnow().isoformat(), field_id, auction_type_id),
            )
        conn.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Field not found")

    return {"status": "ok", "deleted": field_id}


@router.put("/{auction_type_id}/fields/reorder")
async def reorder_fields(auction_type_id: int, field_ids: list[int]):
    """Reorder fields by providing ordered list of field IDs."""
    with get_connection() as conn:
        for i, field_id in enumerate(field_ids):
            conn.execute(
                "UPDATE field_mappings SET display_order = ? WHERE id = ? AND auction_type_id = ?",
                (i, field_id, auction_type_id),
            )
        conn.commit()

    return {"status": "ok", "reordered": len(field_ids)}


# =============================================================================
# HELPERS
# =============================================================================


def _row_to_field(row: dict) -> FieldMappingResponse:
    """Convert database row to field response."""
    hints = None
    if row.get("extraction_hints_json"):
        try:
            hints = json.loads(row["extraction_hints_json"])
        except Exception:
            pass

    return FieldMappingResponse(
        id=row["id"],
        auction_type_id=row["auction_type_id"],
        source_key=row["source_key"],
        internal_key=row["internal_key"],
        cd_key=row.get("cd_key"),
        display_name=row.get("display_name"),
        description=row.get("description"),
        field_type=row.get("field_type", "text"),
        is_required=row.get("is_required", False),
        default_value=row.get("default_value"),
        validation_regex=row.get("validation_regex"),
        validation_message=row.get("validation_message"),
        transform=row.get("transform"),
        extraction_hints=hints,
        display_order=row.get("display_order", 0),
        is_active=row.get("is_active", True),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )
