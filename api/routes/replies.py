"""
Email Reply Routes

Endpoints for sending confirmation emails after CD export.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from api.database import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/runs", tags=["Email Replies"])


def _create_graph_reader():
    """Create a GraphEmailReader from stored credentials."""
    from services.credential_store import get_credential_raw

    raw = get_credential_raw("email_oauth")
    if not raw or not raw.get("enabled"):
        return None

    config = raw["config"]
    tenant_id = config.get("tenant_id", "")
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")
    email_address = config.get("email_address", "")

    if not all([tenant_id, client_id, client_secret, email_address]):
        return None

    from core.config import EmailConfig
    from ingest.email_reader import GraphEmailReader

    email_config = EmailConfig(
        provider="graph",
        address=email_address,
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
    )
    reader = GraphEmailReader(email_config)
    return reader


@router.post("/{run_id}/reply")
async def send_reply(run_id: int):
    """Send confirmation email reply for a run after CD export."""
    # Verify run exists
    with get_connection() as conn:
        run = conn.execute(
            "SELECT id FROM extraction_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Verify CD listing exists
    with get_connection() as conn:
        listing = conn.execute(
            "SELECT cd_listing_id FROM cd_listings WHERE run_id = ?", (run_id,)
        ).fetchone()
    if not listing:
        return {"success": False, "error": "No CD listing found for this run"}

    # Check if already sent
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM email_replies WHERE run_id = ? AND status = 'sent'",
            (run_id,),
        ).fetchone()
    if existing:
        return {"success": True, "already_sent": True}

    # Create Graph reader
    graph_reader = _create_graph_reader()
    if not graph_reader:
        return {
            "success": False,
            "error": "Email OAuth2 not configured — cannot send reply",
        }

    # Send via EmailReplier
    from api.services.email_replier import EmailReplier

    replier = EmailReplier(graph_reader)
    result = replier.send_confirmation(run_id)
    return result


@router.get("/{run_id}/reply/status")
async def get_reply_status(run_id: int):
    """Get the status of a confirmation email reply for a run."""
    with get_connection() as conn:
        reply = conn.execute(
            """SELECT status, sent_at, cd_listing_id, error_message
               FROM email_replies
               WHERE run_id = ?
               ORDER BY created_at DESC
               LIMIT 1""",
            (run_id,),
        ).fetchone()

    if not reply:
        return {"status": "not_sent"}

    result = {"status": reply["status"]}
    if reply["sent_at"]:
        result["sent_at"] = reply["sent_at"]
    if reply["cd_listing_id"]:
        result["cd_listing_id"] = reply["cd_listing_id"]
    if reply["error_message"]:
        result["error"] = reply["error_message"]
    return result
