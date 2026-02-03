"""
Email Webhook Integration

Endpoints for receiving emails via HTTP webhook.
This allows email forwarding from:
- Microsoft Power Automate / Logic Apps
- SendGrid Inbound Parse
- Mailgun Routes
- Other email-to-HTTP services

Usage:
1. Configure your email system to forward emails to POST /api/integrations/webhook/email
2. Include PDF attachments as base64-encoded data
3. The system will process PDFs and create extraction runs
"""

import base64
import hashlib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from api.database import get_connection
from api.models import DocumentRepository, ExtractionRunRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Webhook"])


# =============================================================================
# MODELS
# =============================================================================


class EmailAttachment(BaseModel):
    """Email attachment in webhook payload."""

    filename: str
    content_type: str = "application/pdf"
    content_base64: str  # Base64-encoded file content
    size: Optional[int] = None


class EmailWebhookPayload(BaseModel):
    """
    Webhook payload for forwarded email.

    Compatible with:
    - Microsoft Power Automate format
    - SendGrid Inbound Parse (converted)
    - Custom email forwarding scripts
    """

    # Email metadata
    message_id: Optional[str] = None
    subject: Optional[str] = None
    sender: Optional[str] = Field(None, alias="from")
    to: Optional[str] = None
    date: Optional[str] = None

    # Body
    body_text: Optional[str] = None
    body_html: Optional[str] = None

    # Attachments
    attachments: list[EmailAttachment] = []

    # Optional: specify auction type
    auction_type_id: Optional[int] = None
    auction_type_code: Optional[str] = None

    class Config:
        populate_by_name = True


class WebhookResponse(BaseModel):
    """Response from webhook endpoint."""

    status: str
    message: str
    processed: int = 0
    documents: list[dict[str, Any]] = []
    errors: list[str] = []


# =============================================================================
# WEBHOOK SECRET VALIDATION
# =============================================================================


def _get_webhook_secret() -> Optional[str]:
    """Get webhook secret from settings."""
    from api.routes.settings import load_settings

    settings = load_settings()
    return settings.get("webhook", {}).get("secret")


def _validate_webhook_secret(provided_secret: Optional[str]) -> bool:
    """Validate webhook secret."""
    expected = _get_webhook_secret()
    if not expected:
        # No secret configured - allow all (not recommended for production)
        return True
    return provided_secret == expected


def _log_webhook_event(
    event_type: str,
    status: str,
    message_id: str = None,
    subject: str = None,
    sender: str = None,
    processed_count: int = 0,
    error: str = None,
):
    """Log webhook event to database."""
    entry_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow().isoformat() + "Z"

    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS webhook_activity_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message_id TEXT,
                subject TEXT,
                sender TEXT,
                status TEXT NOT NULL,
                processed_count INTEGER DEFAULT 0,
                error TEXT
            )
        """)
        conn.execute(
            """
            INSERT INTO webhook_activity_log
            (id, timestamp, event_type, message_id, subject, sender, status, processed_count, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                entry_id,
                timestamp,
                event_type,
                message_id,
                subject,
                sender,
                status,
                processed_count,
                error,
            ),
        )
        conn.commit()


# =============================================================================
# EMAIL WEBHOOK ENDPOINT
# =============================================================================


@router.post("/email", response_model=WebhookResponse)
async def receive_email_webhook(
    payload: EmailWebhookPayload,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
    authorization: Optional[str] = Header(None),
):
    """
    Receive email via webhook.

    This endpoint accepts forwarded emails with PDF attachments
    and processes them through the extraction pipeline.

    **Authentication:**
    - Option 1: X-Webhook-Secret header
    - Option 2: Authorization: Bearer <secret>

    **Request body (JSON):**
    ```json
    {
        "message_id": "optional-message-id",
        "subject": "Email Subject",
        "from": "sender@example.com",
        "date": "2024-01-15T10:30:00Z",
        "body_text": "Email body text",
        "attachments": [
            {
                "filename": "document.pdf",
                "content_type": "application/pdf",
                "content_base64": "JVBERi0xLjQK..."
            }
        ],
        "auction_type_code": "COPART"  // optional
    }
    ```

    **Response:**
    ```json
    {
        "status": "ok",
        "message": "Processed 2 PDF attachments",
        "processed": 2,
        "documents": [
            {"document_id": 123, "run_id": 456, "filename": "doc.pdf"}
        ],
        "errors": []
    }
    ```
    """
    # Validate authentication
    secret = x_webhook_secret
    if not secret and authorization:
        if authorization.startswith("Bearer "):
            secret = authorization[7:]

    if not _validate_webhook_secret(secret):
        _log_webhook_event("email", "rejected", error="Invalid webhook secret")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # Process email
    documents = []
    errors = []

    message_id = payload.message_id or f"webhook-{uuid.uuid4().hex[:8]}"

    # Find auction type
    auction_type_id = payload.auction_type_id
    if not auction_type_id and payload.auction_type_code:
        with get_connection() as conn:
            at = conn.execute(
                "SELECT id FROM auction_types WHERE code = ? AND is_active = TRUE",
                (payload.auction_type_code.upper(),),
            ).fetchone()
            if at:
                auction_type_id = at["id"]

    # Default auction type if not specified
    if not auction_type_id:
        auction_type_id = 1  # Default to first auction type

    # Process PDF attachments
    upload_path = Path("data/uploads/webhook")
    upload_path.mkdir(parents=True, exist_ok=True)

    for attachment in payload.attachments:
        # Only process PDFs
        if not attachment.filename.lower().endswith(".pdf"):
            continue
        if attachment.content_type and "pdf" not in attachment.content_type.lower():
            continue

        try:
            # Decode base64 content
            file_bytes = base64.b64decode(attachment.content_base64)
            sha256 = hashlib.sha256(file_bytes).hexdigest()

            # Check for duplicate
            existing = DocumentRepository.get_by_sha256(sha256)
            if existing:
                documents.append(
                    {
                        "document_id": existing.id,
                        "run_id": None,
                        "filename": attachment.filename,
                        "status": "duplicate",
                    }
                )
                continue

            # Save file
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_filename = "".join(
                c if c.isalnum() or c in ".-_" else "_" for c in attachment.filename
            )
            unique_filename = f"{timestamp}_{uuid.uuid4().hex[:8]}_{safe_filename}"
            file_path = upload_path / unique_filename
            file_path.write_bytes(file_bytes)

            # Extract text
            raw_text = ""
            try:
                import pdfplumber

                with pdfplumber.open(file_path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            raw_text += text + "\n"
            except Exception as e:
                logger.warning(f"PDF text extraction failed: {e}")

            # Auto-detect auction type from text if not specified
            if not payload.auction_type_code and raw_text:
                auction_type_id = _detect_auction_type(raw_text) or auction_type_id

            # Create document
            doc_id = DocumentRepository.create(
                auction_type_id=auction_type_id,
                dataset_split="train",
                filename=attachment.filename,
                file_path=str(file_path),
                file_size=len(file_bytes),
                sha256=sha256,
                raw_text=raw_text,
                uploaded_by=f"webhook:{payload.sender or 'unknown'}",
            )

            # Create extraction run
            run_id = ExtractionRunRepository.create(
                document_id=doc_id,
                auction_type_id=auction_type_id,
                extractor_kind="rule",
            )

            # Check if scanned (low text content)
            if len(raw_text.strip()) < 100:
                ExtractionRunRepository.update(
                    run_id,
                    status="manual_required",
                    errors_json=[{"error": "Scanned PDF - OCR required"}],
                )
            else:
                # Run extraction
                from api.routes.extractions import run_extraction

                run_extraction(run_id, doc_id, auction_type_id)

            documents.append(
                {
                    "document_id": doc_id,
                    "run_id": run_id,
                    "filename": attachment.filename,
                    "status": "processed",
                }
            )

        except Exception as e:
            logger.error(f"Failed to process attachment {attachment.filename}: {e}")
            errors.append(f"{attachment.filename}: {str(e)}")

    processed = len([d for d in documents if d.get("status") == "processed"])

    _log_webhook_event(
        "email",
        "success" if processed > 0 else "no_pdfs",
        message_id=message_id,
        subject=payload.subject,
        sender=payload.sender,
        processed_count=processed,
    )

    return WebhookResponse(
        status="ok" if processed > 0 else "no_pdfs",
        message=(
            f"Processed {processed} PDF attachment(s)" if processed else "No PDF attachments found"
        ),
        processed=processed,
        documents=documents,
        errors=errors,
    )


def _detect_auction_type(text: str) -> Optional[int]:
    """Detect auction type from text content."""
    text_upper = text.upper()

    with get_connection() as conn:
        auction_types = conn.execute(
            "SELECT id, code, extractor_config FROM auction_types WHERE is_active = TRUE"
        ).fetchall()

    for at in auction_types:
        config = at["extractor_config"]
        if config:
            try:
                cfg = json.loads(config) if isinstance(config, str) else config
                patterns = cfg.get("patterns", [])
                for pattern in patterns:
                    if pattern.upper() in text_upper:
                        return at["id"]
            except Exception:
                pass

    return None


# =============================================================================
# MULTIPART/FORM-DATA ENDPOINT (for SendGrid, Mailgun)
# =============================================================================


@router.post("/email/multipart", response_model=WebhookResponse)
async def receive_email_multipart(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """
    Receive email via multipart form data.

    This endpoint is compatible with:
    - SendGrid Inbound Parse
    - Mailgun Routes

    The form should include:
    - from: sender email
    - subject: email subject
    - text: plain text body
    - attachment1, attachment2, etc.: PDF files
    """
    # Validate authentication
    if not _validate_webhook_secret(x_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    form = await request.form()

    # Extract email metadata
    sender = form.get("from", form.get("sender", ""))
    subject = form.get("subject", "")
    body_text = form.get("text", form.get("body-plain", ""))

    # Find attachments
    attachments = []
    for key in form.keys():
        if key.startswith("attachment") or key == "file":
            file = form[key]
            if hasattr(file, "read") and hasattr(file, "filename"):
                if file.filename and file.filename.lower().endswith(".pdf"):
                    content = await file.read()
                    attachments.append(
                        EmailAttachment(
                            filename=file.filename,
                            content_type="application/pdf",
                            content_base64=base64.b64encode(content).decode(),
                            size=len(content),
                        )
                    )

    # Process using the main webhook handler
    payload = EmailWebhookPayload(
        subject=subject,
        sender=sender,
        body_text=body_text,
        attachments=attachments,
    )

    return await receive_email_webhook(payload, x_webhook_secret, None)


# =============================================================================
# WEBHOOK CONFIGURATION & TESTING
# =============================================================================


@router.get("/config")
async def get_webhook_config():
    """Get webhook configuration (without revealing the secret)."""
    from api.routes.settings import load_settings

    settings = load_settings()
    webhook_config = settings.get("webhook", {})

    has_secret = bool(webhook_config.get("secret"))

    return {
        "configured": has_secret,
        "endpoints": {
            "json": "/api/integrations/webhook/email",
            "multipart": "/api/integrations/webhook/email/multipart",
        },
        "authentication": {
            "method": "X-Webhook-Secret header or Authorization: Bearer <secret>",
            "required": has_secret,
        },
    }


@router.post("/test")
async def test_webhook_endpoint(
    x_webhook_secret: Optional[str] = Header(None, alias="X-Webhook-Secret"),
):
    """
    Test webhook endpoint connectivity and authentication.

    Returns status of authentication and system readiness.
    """
    auth_valid = _validate_webhook_secret(x_webhook_secret)

    return {
        "status": "ok" if auth_valid else "auth_required",
        "message": (
            "Webhook endpoint is ready" if auth_valid else "Invalid or missing X-Webhook-Secret"
        ),
        "authentication": "valid" if auth_valid else "invalid",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/activity")
async def get_webhook_activity(limit: int = 50):
    """Get recent webhook activity log."""
    try:
        with get_connection() as conn:
            # Check if table exists
            table_check = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='webhook_activity_log'
            """).fetchone()

            if not table_check:
                return {"items": [], "total": 0}

            rows = conn.execute(
                """
                SELECT * FROM webhook_activity_log
                ORDER BY timestamp DESC
                LIMIT ?
            """,
                (limit,),
            ).fetchall()

            return {
                "items": [dict(row) for row in rows],
                "total": len(rows),
            }
    except Exception as e:
        return {"items": [], "total": 0, "error": str(e)}
