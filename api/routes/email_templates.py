"""
Email Template Management Routes

Endpoints for viewing, editing, previewing, and resetting
the confirmation email reply template.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/email-templates", tags=["Email Templates"])

# Available placeholder variables with descriptions
AVAILABLE_VARIABLES = [
    {"key": "greeting", "description": "\"Hello {name},\" or \"Hello,\""},
    {"key": "sender_name", "description": "Sender's name (empty if unknown)"},
    {"key": "load_id", "description": "Internal Load ID (e.g. 226PORMA1)"},
    {"key": "vin", "description": "Vehicle VIN number(s)"},
    {"key": "warehouse_name", "description": "Warehouse name"},
    {"key": "warehouse_address", "description": "Warehouse street address"},
    {"key": "warehouse_city", "description": "Warehouse city"},
    {"key": "warehouse_state", "description": "Warehouse state"},
    {"key": "warehouse_zip", "description": "Warehouse ZIP code"},
    {"key": "warehouse_phone", "description": "Warehouse phone number"},
    {"key": "warehouse_full_address", "description": "Full address: street, city, state zip"},
    {"key": "warehouse_phone_line", "description": "Phone HTML block (empty if no phone)"},
    {"key": "pickup_name", "description": "Pickup/auction location name (e.g. Copart North Boston)"},
]

# Sample data for preview rendering
SAMPLE_DATA = {
    "greeting": "Hello John,",
    "sender_name": "John",
    "load_id": "226TOYPR1",
    "vin": "4T1BF1FK5EU123456",
    "warehouse_name": "NJ Warehouse",
    "warehouse_address": "123 Main Street",
    "warehouse_city": "Newark",
    "warehouse_state": "NJ",
    "warehouse_zip": "07102",
    "warehouse_phone": "(973) 555-0100",
    "warehouse_full_address": "123 Main Street, Newark, NJ 07102",
    "warehouse_phone_line": '<div style="margin-top:4px;">Phone: (973) 555-0100</div>',
    "pickup_name": "Copart North Boston",
}


class TemplateUpdate(BaseModel):
    body_html: str


class TemplatePreviewRequest(BaseModel):
    body_html: str


@router.get("/reply_confirmation")
async def get_reply_template():
    """Get the current reply confirmation email template."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT template_key, body_html, description, updated_at, updated_by
               FROM email_templates
               WHERE template_key = 'reply_confirmation'"""
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Template not found")

    return {
        "template_key": row["template_key"],
        "body_html": row["body_html"],
        "description": row["description"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
        "available_variables": AVAILABLE_VARIABLES,
    }


@router.put("/reply_confirmation")
async def update_reply_template(data: TemplateUpdate):
    """Update the reply confirmation email template."""
    body = data.body_html

    # Validation
    if not body or not body.strip():
        raise HTTPException(status_code=400, detail="body_html cannot be empty")
    if len(body) > 50000:
        raise HTTPException(
            status_code=400,
            detail=f"body_html too long ({len(body)} chars, max 50000)",
        )
    if "{{load_id}}" not in body:
        raise HTTPException(
            status_code=400,
            detail="Template must contain {{load_id}} placeholder",
        )

    now = datetime.now(timezone.utc).isoformat() + "Z"

    with get_connection() as conn:
        conn.execute(
            """UPDATE email_templates
               SET body_html = ?, updated_at = ?, updated_by = 'ui'
               WHERE template_key = 'reply_confirmation'""",
            (body, now),
        )
        conn.commit()

    logger.info("Reply confirmation template updated via API")
    return {"success": True, "updated_at": now}


@router.post("/reply_confirmation/preview")
async def preview_reply_template(data: TemplatePreviewRequest):
    """Render the template with sample data for preview (does not save)."""
    from api.services.email_replier import ReplyBodyBuilder

    preview_html = ReplyBodyBuilder.render_template(data.body_html, SAMPLE_DATA)
    return {"preview_html": preview_html}


@router.post("/reply_confirmation/reset")
async def reset_reply_template():
    """Reset the reply confirmation template to the default."""
    from api.routes.email_log import _DEFAULT_REPLY_CONFIRMATION_HTML

    now = datetime.now(timezone.utc).isoformat() + "Z"

    with get_connection() as conn:
        conn.execute(
            """UPDATE email_templates
               SET body_html = ?, updated_at = ?, updated_by = 'reset'
               WHERE template_key = 'reply_confirmation'""",
            (_DEFAULT_REPLY_CONFIRMATION_HTML, now),
        )
        conn.commit()

    logger.info("Reply confirmation template reset to default")
    return {"success": True, "updated_at": now}
