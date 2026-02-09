"""
Template Management API Routes

Endpoints for managing zone-based extraction templates.
Users can view, create, and modify templates for different document types.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.database import get_connection
from extractors.zone_extractor import (
    DocumentTemplate,
    DocumentZone,
    FieldType,
    ZoneField,
    get_zone_extractor,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/templates", tags=["Templates"])


# =============================================================================
# DATABASE SCHEMA
# =============================================================================


def init_templates_schema():
    """Initialize database tables for templates"""
    with get_connection() as conn:
        # Templates table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extraction_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                auction_type TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                zones_json TEXT NOT NULL,
                description TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Template usage/feedback table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS template_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id TEXT NOT NULL,
                document_id INTEGER,
                extraction_run_id INTEGER,
                field_key TEXT NOT NULL,
                extracted_value TEXT,
                corrected_value TEXT,
                zone_name TEXT,
                feedback_type TEXT DEFAULT 'correction',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        """)

        # Create indexes
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_templates_auction_type ON extraction_templates(auction_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_template_feedback_template ON template_feedback(template_id)"
        )

        conn.commit()
        logger.info("Templates schema initialized")


# Initialize schema on import
try:
    init_templates_schema()
except Exception as e:
    logger.warning(f"Could not initialize templates schema: {e}")


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class ZoneFieldModel(BaseModel):
    """API model for zone field"""

    key: str
    field_type: str = "text"
    pattern: Optional[str] = None
    label: Optional[str] = None
    required: bool = False


class ZoneModel(BaseModel):
    """API model for document zone"""

    name: str
    x0: float = Field(..., ge=0, le=100, description="Left edge (%)")
    y0: float = Field(..., ge=0, le=100, description="Top edge (%)")
    x1: float = Field(..., ge=0, le=100, description="Right edge (%)")
    y1: float = Field(..., ge=0, le=100, description="Bottom edge (%)")
    fields: list[ZoneFieldModel] = []
    description: Optional[str] = None


class TemplateModel(BaseModel):
    """API model for document template"""

    template_id: str
    name: str
    auction_type: str
    version: int = 1
    zones: list[ZoneModel] = []
    description: Optional[str] = None
    is_active: bool = True


class TemplateResponse(BaseModel):
    """Response model for template"""

    id: Optional[int] = None
    template_id: str
    name: str
    auction_type: str
    version: int
    zones: list[ZoneModel]
    description: Optional[str] = None
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TemplateListResponse(BaseModel):
    """Response model for template list"""

    items: list[TemplateResponse]
    total: int


class ZoneExtractionRequest(BaseModel):
    """Request model for zone-based extraction"""

    document_id: int
    auction_type: Optional[str] = None
    template_id: Optional[str] = None


class ZoneExtractionResponse(BaseModel):
    """Response model for zone extraction result"""

    fields: dict
    zone_texts: dict
    confidence: float
    template_id: str
    warnings: list[str] = []


class TemplateFeedbackRequest(BaseModel):
    """Request for template correction feedback"""

    template_id: str
    document_id: Optional[int] = None
    extraction_run_id: Optional[int] = None
    field_key: str
    extracted_value: Optional[str] = None
    corrected_value: str
    zone_name: Optional[str] = None


# =============================================================================
# REPOSITORY
# =============================================================================


class TemplateRepository:
    """Database operations for templates"""

    @staticmethod
    def list_all(auction_type: Optional[str] = None, active_only: bool = True) -> list[dict]:
        """List all templates"""
        with get_connection() as conn:
            sql = "SELECT * FROM extraction_templates WHERE 1=1"
            params = []

            if auction_type:
                sql += " AND auction_type = ?"
                params.append(auction_type)

            if active_only:
                sql += " AND is_active = TRUE"

            sql += " ORDER BY auction_type, version DESC"

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_by_id(template_id: str) -> Optional[dict]:
        """Get template by ID"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM extraction_templates WHERE template_id = ?", (template_id,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_by_auction_type(auction_type: str) -> Optional[dict]:
        """Get active template for auction type"""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM extraction_templates WHERE auction_type = ? AND is_active = TRUE ORDER BY version DESC LIMIT 1",
                (auction_type,),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def create(template: TemplateModel) -> int:
        """Create new template"""
        with get_connection() as conn:
            zones_json = json.dumps([z.model_dump() for z in template.zones])

            cursor = conn.execute(
                """
                INSERT INTO extraction_templates
                (template_id, name, auction_type, version, zones_json, description, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    template.template_id,
                    template.name,
                    template.auction_type,
                    template.version,
                    zones_json,
                    template.description,
                    template.is_active,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def update(template_id: str, template: TemplateModel) -> bool:
        """Update template"""
        with get_connection() as conn:
            zones_json = json.dumps([z.model_dump() for z in template.zones])

            conn.execute(
                """
                UPDATE extraction_templates
                SET name = ?, zones_json = ?, description = ?, is_active = ?,
                    version = ?, updated_at = CURRENT_TIMESTAMP
                WHERE template_id = ?
            """,
                (
                    template.name,
                    zones_json,
                    template.description,
                    template.is_active,
                    template.version,
                    template_id,
                ),
            )
            conn.commit()
            return True

    @staticmethod
    def delete(template_id: str) -> bool:
        """Delete template"""
        with get_connection() as conn:
            conn.execute("DELETE FROM extraction_templates WHERE template_id = ?", (template_id,))
            conn.commit()
            return True

    @staticmethod
    def save_feedback(feedback: TemplateFeedbackRequest) -> int:
        """Save template feedback/correction"""
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO template_feedback
                (template_id, document_id, extraction_run_id, field_key,
                 extracted_value, corrected_value, zone_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    feedback.template_id,
                    feedback.document_id,
                    feedback.extraction_run_id,
                    feedback.field_key,
                    feedback.extracted_value,
                    feedback.corrected_value,
                    feedback.zone_name,
                ),
            )
            conn.commit()
            return cursor.lastrowid


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def db_to_response(row: dict) -> TemplateResponse:
    """Convert database row to response model"""
    zones_data = json.loads(row.get("zones_json", "[]"))
    zones = [ZoneModel(**z) for z in zones_data]

    return TemplateResponse(
        id=row.get("id"),
        template_id=row["template_id"],
        name=row["name"],
        auction_type=row["auction_type"],
        version=row.get("version", 1),
        zones=zones,
        description=row.get("description"),
        is_active=row.get("is_active", True),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def db_to_domain(row: dict) -> DocumentTemplate:
    """Convert database row to domain DocumentTemplate for ZoneExtractor"""
    zones_data = json.loads(row.get("zones_json", "[]"))
    zones = []

    for z in zones_data:
        fields = [
            ZoneField(
                key=f["key"],
                field_type=FieldType(f.get("field_type", "text")),
                pattern=f.get("pattern"),
                label=f.get("label"),
                required=f.get("required", False),
            )
            for f in z.get("fields", [])
        ]
        zones.append(
            DocumentZone(
                name=z["name"],
                x0=z["x0"],
                y0=z["y0"],
                x1=z["x1"],
                y1=z["y1"],
                fields=fields,
                description=z.get("description"),
            )
        )

    return DocumentTemplate(
        template_id=row["template_id"],
        name=row["name"],
        auction_type=row["auction_type"],
        version=row.get("version", 1),
        zones=zones,
        description=row.get("description"),
        is_active=row.get("is_active", True),
    )


def sync_default_templates():
    """
    Sync templates between database and ZoneExtractor.
    Called at startup to ensure templates are properly loaded.

    Priority:
    1. Load existing templates FROM database (user edits preserved)
    2. Create defaults only if no DB record exists
    """
    extractor = get_zone_extractor()

    # First, load ALL existing templates from database into extractor
    all_db_templates = TemplateRepository.list_all(active_only=False)
    loaded_auction_types = set()

    for row in all_db_templates:
        try:
            template = db_to_domain(row)
            extractor.register_template(template)
            loaded_auction_types.add(template.auction_type)
            logger.info(f"Loaded template from database: {template.template_id}")
        except Exception as e:
            logger.warning(f"Failed to load template {row.get('template_id')}: {e}")

    # Then, create defaults only for auction types not in database
    for auction_type, template in list(extractor.templates.items()):
        if auction_type in loaded_auction_types:
            # Already loaded from DB, skip
            continue

        existing = TemplateRepository.get_by_id(template.template_id)

        if not existing:
            # Convert to API model
            zones = []
            for zone in template.zones:
                fields = [
                    ZoneFieldModel(
                        key=f.key,
                        field_type=f.field_type.value,
                        pattern=f.pattern,
                        label=f.label,
                        required=f.required,
                    )
                    for f in zone.fields
                ]
                zones.append(
                    ZoneModel(
                        name=zone.name,
                        x0=zone.x0,
                        y0=zone.y0,
                        x1=zone.x1,
                        y1=zone.y1,
                        fields=fields,
                        description=zone.description,
                    )
                )

            api_template = TemplateModel(
                template_id=template.template_id,
                name=template.name,
                auction_type=template.auction_type,
                version=template.version,
                zones=zones,
                description=template.description,
                is_active=template.is_active,
            )

            TemplateRepository.create(api_template)
            logger.info(f"Created default template: {template.template_id}")


# Sync defaults at import
try:
    sync_default_templates()
except Exception as e:
    logger.warning(f"Could not sync default templates: {e}")


# =============================================================================
# API ENDPOINTS
# =============================================================================


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    auction_type: Optional[str] = Query(None, description="Filter by auction type"),
    active_only: bool = Query(True, description="Only active templates"),
):
    """List all extraction templates"""
    rows = TemplateRepository.list_all(auction_type=auction_type, active_only=active_only)
    items = [db_to_response(r) for r in rows]
    return TemplateListResponse(items=items, total=len(items))


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: str):
    """Get template by ID"""
    row = TemplateRepository.get_by_id(template_id)
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    return db_to_response(row)


@router.post("", response_model=TemplateResponse)
async def create_template(template: TemplateModel):
    """Create new extraction template"""
    # Check if template_id already exists
    existing = TemplateRepository.get_by_id(template.template_id)
    if existing:
        raise HTTPException(status_code=400, detail="Template ID already exists")

    # Create in database
    TemplateRepository.create(template)

    # Register with extractor
    extractor = get_zone_extractor()
    doc_template = _api_to_domain(template)
    extractor.register_template(doc_template)

    # Return created template
    row = TemplateRepository.get_by_id(template.template_id)
    return db_to_response(row)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(template_id: str, template: TemplateModel):
    """Update existing template"""
    existing = TemplateRepository.get_by_id(template_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")

    # Update in database
    template.template_id = template_id  # Ensure ID matches
    TemplateRepository.update(template_id, template)

    # Update in extractor
    extractor = get_zone_extractor()
    doc_template = _api_to_domain(template)
    extractor.register_template(doc_template)

    # Return updated template
    row = TemplateRepository.get_by_id(template_id)
    return db_to_response(row)


@router.delete("/{template_id}")
async def delete_template(template_id: str):
    """Delete template"""
    existing = TemplateRepository.get_by_id(template_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")

    TemplateRepository.delete(template_id)
    return {"message": f"Template {template_id} deleted"}


@router.post("/extract", response_model=ZoneExtractionResponse)
async def extract_with_zones(request: ZoneExtractionRequest):
    """
    Run zone-based extraction on a document.

    This extracts fields using the template's zone definitions from DATABASE,
    ensuring correct data is extracted from the right regions.

    IMPORTANT: Uses extract_with_logging() which loads template from DB,
    not from singleton cache.
    """
    from api.models import DocumentRepository

    # Get document
    doc = DocumentRepository.get_by_id(request.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Determine auction type
    auction_type = request.auction_type
    if not auction_type:
        # Get from document's auction_type_id
        from api.models import AuctionTypeRepository

        at = AuctionTypeRepository.get_by_id(doc.auction_type_id)
        auction_type = at.code if at else None

    if not auction_type:
        raise HTTPException(status_code=400, detail="Could not determine auction type")

    # Run extraction using extract_with_logging() which loads from DB
    extractor = get_zone_extractor()
    result = extractor.extract_with_logging(doc.file_path, auction_type)

    return ZoneExtractionResponse(
        fields=result.fields,
        zone_texts=result.zone_texts,
        confidence=result.confidence,
        template_id=result.template_id,
        warnings=result.warnings,
    )


@router.post("/feedback")
async def submit_feedback(feedback: TemplateFeedbackRequest):
    """
    Submit feedback for template improvement.

    When a user corrects an extracted value, this feedback is stored
    and can be used to improve the template's zone definitions.
    """
    feedback_id = TemplateRepository.save_feedback(feedback)
    return {"message": "Feedback saved", "feedback_id": feedback_id}


@router.get("/{template_id}/zones/preview")
async def preview_zones(
    template_id: str,
    document_id: int = Query(..., description="Document to preview zones on"),
):
    """
    Get zone preview data for a document.

    Returns the text extracted from each zone for visual debugging.
    Uses the LATEST template from database, not cached version.
    """
    import json

    from api.models import DocumentRepository

    template_row = TemplateRepository.get_by_id(template_id)
    if not template_row:
        raise HTTPException(status_code=404, detail="Template not found")

    doc = DocumentRepository.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Build template from database (not from extractor cache)
    zones_data = json.loads(template_row.get("zones_json", "[]"))
    zones = []
    for zd in zones_data:
        fields = []
        for fd in zd.get("fields", []):
            if isinstance(fd, dict):
                field_type_str = fd.get("field_type", "text").lower()
                field_type = FieldType.TEXT
                for ft in FieldType:
                    if ft.value == field_type_str:
                        field_type = ft
                        break
                zone_field = ZoneField(
                    key=fd.get("key", ""),
                    field_type=field_type,
                    pattern=fd.get("pattern"),
                    label=fd.get("label"),
                    required=fd.get("required", False),
                )
                zone_field.apply_defaults()
                fields.append(zone_field)

        zone = DocumentZone(
            name=zd.get("name", ""),
            x0=float(zd.get("x0", 0)),
            y0=float(zd.get("y0", 0)),
            x1=float(zd.get("x1", 100)),
            y1=float(zd.get("y1", 100)),
            description=zd.get("description", ""),
            fields=fields,
        )
        zones.append(zone)

    if not zones:
        raise HTTPException(status_code=400, detail="No zones defined in template")

    # Get zone extractor for text extraction
    extractor = get_zone_extractor()

    zone_data = []
    for zone in zones:
        text = extractor.extract_zone_text(doc.file_path, zone)
        zone_data.append(
            {
                "name": zone.name,
                "description": zone.description,
                "bbox": {"x0": zone.x0, "y0": zone.y0, "x1": zone.x1, "y1": zone.y1},
                "text": text,
                "fields": [f.key for f in zone.fields],
            }
        )

    return {
        "template_id": template_id,
        "document_id": document_id,
        "zones": zone_data,
    }


class LivePreviewRequest(BaseModel):
    """Request for live zone preview (unsaved zones)"""
    document_id: int
    zones: list[ZoneModel]


@router.post("/zones/live-preview")
async def live_preview_zones(request: LivePreviewRequest):
    """
    Preview zones with CUSTOM coordinates (not from DB).

    Use this when editing zones to see the text BEFORE saving.
    This endpoint accepts zones from the request body, not from database.
    """
    from api.models import DocumentRepository

    doc = DocumentRepository.get_by_id(request.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not request.zones:
        raise HTTPException(status_code=400, detail="No zones provided")

    # Build zones from request (not from DB)
    zones = []
    for zd in request.zones:
        fields = []
        for fd in zd.fields:
            field_type = FieldType.TEXT
            for ft in FieldType:
                if ft.value == fd.field_type.lower():
                    field_type = ft
                    break
            zone_field = ZoneField(
                key=fd.key,
                field_type=field_type,
                pattern=fd.pattern,
                label=fd.label,
                required=fd.required,
            )
            zone_field.apply_defaults()
            fields.append(zone_field)

        zone = DocumentZone(
            name=zd.name,
            x0=float(zd.x0),
            y0=float(zd.y0),
            x1=float(zd.x1),
            y1=float(zd.y1),
            description=zd.description or "",
            fields=fields,
        )
        zones.append(zone)

    # Get zone extractor for text extraction
    extractor = get_zone_extractor()

    zone_data = []
    for zone in zones:
        text = extractor.extract_zone_text(doc.file_path, zone)
        zone_data.append(
            {
                "name": zone.name,
                "description": zone.description,
                "bbox": {"x0": zone.x0, "y0": zone.y0, "x1": zone.x1, "y1": zone.y1},
                "text": text,
                "fields": [f.key for f in zone.fields],
            }
        )

    return {
        "document_id": request.document_id,
        "zones": zone_data,
        "source": "live_preview",  # Indicates this is from request, not DB
    }


def _api_to_domain(api_template: TemplateModel) -> DocumentTemplate:
    """Convert API model to domain model"""
    zones = []
    for z in api_template.zones:
        fields = []
        for f in z.fields:
            zone_field = ZoneField(
                key=f.key,
                field_type=FieldType(f.field_type),
                pattern=f.pattern,
                label=f.label,
                required=f.required,
            )
            # Apply default patterns/types for known fields
            zone_field.apply_defaults()
            fields.append(zone_field)

        zones.append(
            DocumentZone(
                name=z.name,
                x0=z.x0,
                y0=z.y0,
                x1=z.x1,
                y1=z.y1,
                fields=fields,
                description=z.description,
            )
        )

    return DocumentTemplate(
        template_id=api_template.template_id,
        name=api_template.name,
        auction_type=api_template.auction_type,
        version=api_template.version,
        zones=zones,
        description=api_template.description,
        is_active=api_template.is_active,
    )
