"""
Attachment download and listing endpoints.

Provides shareable download links for vehicle release PDFs,
condition reports, and other attachments linked to extraction runs.
"""

import json
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.database import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Attachments"])

ATTACHMENTS_DIR = Path("data/attachments")


class AttachmentInfo(BaseModel):
    filename: str
    original_filename: str = ""
    type: str = "other"
    url: str = ""


class AttachmentListResponse(BaseModel):
    run_id: int
    attachments: list[AttachmentInfo] = Field(default_factory=list)


@router.get("/api/documents/{run_id}/attachments/{filename}")
async def download_attachment(run_id: int, filename: str):
    """
    Download an attachment by run ID and filename.

    Public endpoint — shareable with carriers for vehicle release docs.
    """
    # Sanitize filename to prevent path traversal
    safe_filename = Path(filename).name
    file_path = ATTACHMENTS_DIR / str(run_id) / safe_filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Ensure resolved path is within attachments dir
    try:
        file_path.resolve().relative_to(ATTACHMENTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    # Detect media type from file extension
    media_type, _ = mimetypes.guess_type(safe_filename)
    if not media_type:
        media_type = "application/octet-stream"

    # Serve inline (no Content-Disposition: attachment) so browsers can
    # display PDFs in iframe and images in img tags.
    # Omitting `filename` prevents Starlette from setting Content-Disposition: attachment.
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
    )


@router.get("/api/documents/{run_id}/attachments", response_model=AttachmentListResponse)
async def list_attachments(run_id: int):
    """List all attachments for an extraction run."""
    with get_connection() as conn:
        # Ensure column exists
        try:
            conn.execute(
                "ALTER TABLE extraction_runs ADD COLUMN attachments_json TEXT DEFAULT '[]'"
            )
            conn.commit()
        except Exception:
            pass

        row = conn.execute(
            "SELECT attachments_json FROM extraction_runs WHERE id = ?", (run_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Extraction run {run_id} not found")

    attachments = []
    if row["attachments_json"]:
        try:
            attachments = json.loads(row["attachments_json"])
        except Exception:
            attachments = []

    return AttachmentListResponse(
        run_id=run_id,
        attachments=[AttachmentInfo(**a) for a in attachments],
    )
