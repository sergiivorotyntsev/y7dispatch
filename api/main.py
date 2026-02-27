"""FastAPI Control Panel for Vehicle Transport Automation.

Run with: uvicorn api.main:app --reload --port 8000

Endpoints:
- /api/settings - Configuration management
- /api/test - Test/Sandbox (upload, preview, dry-run)
- /api/health - Health check
- /api/auction-types - Auction type management
- /api/documents - Document upload and management
- /api/extractions - Extraction run management
- /api/review - Review items and submit workflow
- /api/exports - Central Dispatch export
- /api/models - ML model versions and training
- /api/dlq - Dead Letter Queue for failed processing
"""

import asyncio
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Context variable for request ID - accessible throughout the request lifecycle
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

from api.auth import auth_middleware, router as auth_router
from api.database import init_db
from api.models import init_schema, seed_base_auction_types, seed_default_field_mappings
from api.routes import (
    attachments,
    auction_directory,
    auction_types,
    batch,
    cd_listings,
    credentials,
    dlq,
    documents,
    email_log,
    email_templates,
    exports,
    extractions,
    field_mappings,
    health,
    integrations,
    listings,
    metrics,
    models,
    pricing,
    replies,
    reviews,
    settings,
    sheets,
    templates,
    test,
    training,
    validation,
    warehouses,
    weather,
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds a unique request ID to each request.

    - Generates a UUID for each request
    - Sets it in a context variable for access throughout the request
    - Adds X-Request-ID header to responses
    """

    async def dispatch(self, request: Request, call_next):
        # Check if client sent a request ID, otherwise generate one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]

        # Store in context variable for logging/debugging
        request_id_var.set(request_id)

        # Store on request state for easy access
        request.state.request_id = request_id

        # Process request
        response = await call_next(request)

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response


def get_request_id() -> str:
    """Get the current request ID from context."""
    return request_id_var.get()


# =============================================================================
# EMAIL AUTO-POLLING
# =============================================================================

# Poll state (in-memory, resets on restart)
_poll_lock = asyncio.Lock()
_poll_state = {
    "last_poll_at": None,
    "last_poll_error": None,
    "is_polling": False,
    "polls_completed": 0,
}
_auto_poll_task: asyncio.Task | None = None

# Settings file for poll config
_POLL_SETTINGS_FILE = Path(__file__).parent.parent / "config" / "poll_settings.json"


def _load_poll_settings() -> dict:
    """Load auto-poll settings from file."""
    import json
    defaults = {
        "auto_poll_enabled": True,
        "poll_interval_minutes": 5,
        "poll_since_days": 7,
    }
    try:
        if _POLL_SETTINGS_FILE.exists():
            with open(_POLL_SETTINGS_FILE) as f:
                saved = json.load(f)
            defaults.update(saved)
    except Exception:
        pass
    return defaults


def _save_poll_settings(settings: dict):
    """Save auto-poll settings to file."""
    import json
    _POLL_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_POLL_SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


async def _run_email_poll(since_days: int = 7):
    """Run a single email poll with mutex protection."""
    if _poll_lock.locked():
        logger.info("Email poll already in progress, skipping")
        return

    async with _poll_lock:
        _poll_state["is_polling"] = True
        try:
            from api.workers.email_worker import get_worker
            worker = get_worker()
            await asyncio.to_thread(worker.poll_once, since_days=since_days)
            _poll_state["last_poll_at"] = datetime.now(timezone.utc).isoformat() + "Z"
            _poll_state["last_poll_error"] = None
            _poll_state["polls_completed"] += 1
        except Exception as e:
            _poll_state["last_poll_error"] = str(e)
            logger.error(f"Email poll error: {e}")
        finally:
            _poll_state["is_polling"] = False


async def _email_polling_loop():
    """Background loop that polls emails at configurable interval.

    Uses last_poll_at to compute lookback — only checks for NEW emails
    since the last successful poll. Falls back to 1 day on first run.
    Already-processed emails are skipped via message_id dedup in email_log.
    """
    # Initial delay — let app finish startup
    await asyncio.sleep(10)

    while True:
        try:
            settings = _load_poll_settings()
            if settings.get("auto_poll_enabled", True):
                interval = settings.get("poll_interval_minutes", 5)

                # Compute since_days from last_poll_at (default: 1 day for first run)
                since_days = 1
                if _poll_state["last_poll_at"]:
                    try:
                        last = datetime.fromisoformat(_poll_state["last_poll_at"].replace("Z", "+00:00"))
                        delta = (datetime.now(timezone.utc) - last).days
                        since_days = max(0, min(delta + 1, 30))  # +1 for safety overlap
                    except Exception:
                        since_days = 1

                await _run_email_poll(since_days)

                logger.info(f"Email auto-poll complete (since_days={since_days}). Next in {interval} min")
                await asyncio.sleep(interval * 60)
            else:
                # Check again in 60 seconds if disabled
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Email polling loop error: {e}")
            await asyncio.sleep(300)  # 5 min backoff on error


app = FastAPI(
    title="Vehicle Transport Automation",
    description="Control Panel for Email-to-ClickUp Pipeline with ML Training Support",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Request ID middleware - add first so it runs for all requests
app.add_middleware(RequestIDMiddleware)

# CORS for frontend — locked to configured origins
import os as _os
_CORS_ORIGINS = _os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
_CORS_ORIGINS = [o.strip() for o in _CORS_ORIGINS if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,  # Required for httpOnly cookie auth
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],  # Allow frontend to read request ID
)

# JWT auth middleware — runs after CORS so preflight OPTIONS aren't blocked
@app.middleware("http")
async def _auth_middleware(request, call_next):
    return await auth_middleware(request, call_next)

# Auth endpoints (login, logout, me)
app.include_router(auth_router)

# Include original routers
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(test.router, prefix="/api/test", tags=["Test/Sandbox"])

# Include new MVP routers (routes have their own prefix)
app.include_router(auction_types.router)
app.include_router(documents.router)
app.include_router(extractions.router)
app.include_router(reviews.router)
app.include_router(exports.router)
app.include_router(models.router)
app.include_router(integrations.router)
app.include_router(warehouses.router)
app.include_router(field_mappings.router)
app.include_router(training.router, prefix="/api")
app.include_router(metrics.router)  # M3.P1.5: Metrics endpoints
app.include_router(cd_listings.router)  # CD Listings API v2 preview + push
app.include_router(templates.router)  # Zone-based extraction templates
app.include_router(pricing.router)  # Pricing recommendations via CD Market Intelligence
app.include_router(dlq.router, prefix="/api", tags=["DLQ"])  # Dead Letter Queue (Phase 0.7)
app.include_router(sheets.router)  # Sheets webhook override endpoint
app.include_router(credentials.router, prefix="/api/credentials", tags=["Credentials"])
app.include_router(listings.router)  # Load ID generation + listing management
app.include_router(replies.router)  # Email confirmation replies after CD export
app.include_router(email_templates.router)  # Email template management
app.include_router(attachments.router)  # Attachment download/list for vehicle release PDFs
app.include_router(auction_directory.router)  # Auction phone directory lookup
app.include_router(email_log.router)  # Email log browsing + management
app.include_router(weather.router)  # NWS weather alerts along transport routes
app.include_router(batch.router)  # Batch operations: bulk approve/hold/archive
app.include_router(validation.router)  # VIN decode + pickup address validation


# =============================================================================
# EMAIL WORKER ENDPOINTS
# =============================================================================


@app.post("/api/email/poll", tags=["Email"])
async def poll_email_now(
    since_days: int = Query(0, ge=0, le=30),
    since_date: str | None = Query(None, description="ISO date (YYYY-MM-DD) — overrides since_days if provided"),
):
    """
    Poll email inbox now (manual trigger).

    Triggers an immediate poll of the configured email inbox.
    Uses mutex to prevent concurrent polls with auto-poller.
    Use since_days to look back further (0 = today, 7 = past week).
    Alternatively, pass since_date (YYYY-MM-DD) for exact date control.
    """
    # Convert since_date to since_days if provided
    effective_since_days = since_days
    if since_date:
        try:
            target = datetime.strptime(since_date, "%Y-%m-%d")
            delta = (datetime.now() - target).days
            effective_since_days = max(0, min(delta, 30))
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(400, "since_date must be YYYY-MM-DD format")

    if _poll_lock.locked():
        return {"status": "busy", "message": "Poll already in progress", "results": []}

    async with _poll_lock:
        _poll_state["is_polling"] = True
        try:
            from api.workers.email_worker import get_worker

            worker = get_worker()
            results = await asyncio.to_thread(worker.poll_once, since_days=effective_since_days)
            _poll_state["last_poll_at"] = datetime.now(timezone.utc).isoformat() + "Z"
            _poll_state["last_poll_error"] = None
            _poll_state["polls_completed"] += 1

            # Detect VIN duplicates across processed runs
            vin_duplicates = []
            processed_run_ids = [r.run_id for r in results if r.status == "processed" and r.run_id]
            if processed_run_ids:
                try:
                    import json as _json
                    from api.database import get_connection as _gc
                    with _gc() as conn:
                        for run_id in processed_run_ids:
                            row = conn.execute(
                                "SELECT outputs_json FROM extraction_runs WHERE id = ?", (run_id,)
                            ).fetchone()
                            if not row or not row[0]:
                                continue
                            outputs = _json.loads(row[0])
                            vin = outputs.get("vehicle_vin")
                            if not vin or len(vin) != 17:
                                continue
                            # Check for other runs with same VIN
                            existing = conn.execute(
                                "SELECT id, status FROM extraction_runs "
                                "WHERE id != ? AND outputs_json LIKE ? "
                                "ORDER BY id DESC LIMIT 1",
                                (run_id, f'%"{vin}"%'),
                            ).fetchone()
                            if existing:
                                vin_duplicates.append({
                                    "vin": vin,
                                    "new_run_id": run_id,
                                    "existing_run_id": existing["id"],
                                    "existing_status": existing["status"],
                                })
                except Exception:
                    pass  # Non-critical — don't fail the poll

            return {
                "status": "ok",
                "processed": len([r for r in results if r.status == "processed"]),
                "skipped": len([r for r in results if r.status == "skipped"]),
                "failed": len([r for r in results if r.status == "failed"]),
                "vin_duplicates": vin_duplicates,
                "results": [
                    {
                        "message_id": r.message_id,
                        "status": r.status,
                        "rule_matched": r.rule_matched,
                        "document_id": r.document_id,
                        "run_id": r.run_id,
                        "error": r.error,
                    }
                    for r in results
                ],
            }
        except Exception as e:
            _poll_state["last_poll_error"] = str(e)
            raise
        finally:
            _poll_state["is_polling"] = False


@app.post("/api/email/scan", tags=["Email"])
async def scan_email_inbox(request: Request):
    """
    Scan email inbox for messages in a date range WITHOUT processing.

    Returns list of emails with metadata: subject, sender, date, attachments,
    already-processed status, VIN detection, and duplicate warnings.

    Body: { "since_date": "2026-02-04", "until_date": "2026-02-13" }
    """
    body = await request.json()
    since_date = body.get("since_date")
    until_date = body.get("until_date")

    if not since_date:
        from fastapi import HTTPException
        raise HTTPException(400, "since_date is required (YYYY-MM-DD)")

    # Validate date format
    try:
        datetime.strptime(since_date, "%Y-%m-%d")
        if until_date:
            datetime.strptime(until_date, "%Y-%m-%d")
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(400, "Dates must be YYYY-MM-DD format")

    if _poll_lock.locked():
        return {"emails": [], "total": 0, "already_processed": 0, "new": 0,
                "error": "Poll already in progress — try again shortly"}

    async with _poll_lock:
        _poll_state["is_polling"] = True
        try:
            from api.workers.email_worker import get_worker
            worker = get_worker()
            result = await asyncio.to_thread(worker.scan_emails, since_date, until_date)
            return result
        except Exception as e:
            _poll_state["last_poll_error"] = str(e)
            raise
        finally:
            _poll_state["is_polling"] = False


@app.post("/api/email/process-selected", tags=["Email"])
async def process_selected_emails(request: Request):
    """
    Process only selected emails by message_id.

    Body: { "message_ids": ["abc123@gmail.com", "def456@gmail.com"] }
    """
    body = await request.json()
    message_ids = body.get("message_ids", [])

    if not message_ids:
        from fastapi import HTTPException
        raise HTTPException(400, "message_ids list is required and cannot be empty")

    if len(message_ids) > 50:
        from fastapi import HTTPException
        raise HTTPException(400, "Max 50 emails per batch")

    if _poll_lock.locked():
        return {"processed": 0, "failed": 0, "results": [],
                "error": "Poll already in progress — try again shortly"}

    async with _poll_lock:
        _poll_state["is_polling"] = True
        try:
            from api.workers.email_worker import get_worker
            worker = get_worker()
            result = await asyncio.to_thread(worker.process_selected, message_ids)
            _poll_state["last_poll_at"] = datetime.now(timezone.utc).isoformat() + "Z"
            _poll_state["last_poll_error"] = None
            return result
        except Exception as e:
            _poll_state["last_poll_error"] = str(e)
            raise
        finally:
            _poll_state["is_polling"] = False


@app.post("/api/email/worker/start", tags=["Email"])
async def start_email_worker():
    """Start the background email polling worker."""
    from api.workers.email_worker import start_worker

    await start_worker()
    return {"status": "ok", "message": "Email worker started"}


@app.post("/api/email/worker/stop", tags=["Email"])
async def stop_email_worker():
    """Stop the background email polling worker."""
    from api.workers.email_worker import stop_worker

    await stop_worker()
    return {"status": "ok", "message": "Email worker stopped"}


@app.post("/api/email/recover", tags=["Email"])
async def recover_email_processing(since_days: int = Query(7, ge=1, le=30)):
    """
    Emergency recovery: move emails from Processed folder back to Inbox,
    reset all email-sourced data, and re-poll with correct classification.

    Steps:
    1. IMAP COPY all from Processed → Inbox
    2. Delete email_log + email-sourced documents/runs
    3. Re-poll with since_days lookback
    """
    from api.workers.email_worker import (
        get_worker,
        recover_processed_emails,
        reset_email_data,
    )

    # Step 1: Move from Processed → Inbox
    recovery = recover_processed_emails()

    # Step 2: Reset DB data
    reset = reset_email_data()

    # Step 3: Re-poll with lookback
    worker = get_worker()
    results = worker.poll_once(since_days=since_days)

    return {
        "status": "ok",
        "recovery": recovery,
        "reset": reset,
        "reprocessed": len([r for r in results if r.status == "processed"]),
        "skipped": len([r for r in results if r.status == "skipped"]),
        "poll_results": [
            {
                "message_id": r.message_id,
                "status": r.status,
                "rule_matched": r.rule_matched,
                "document_id": r.document_id,
                "run_id": r.run_id,
                "error": r.error,
            }
            for r in results
        ],
    }


@app.get("/api/email/poll-status", tags=["Email"])
async def get_poll_status():
    """Get current auto-polling status and settings."""
    settings = _load_poll_settings()
    return {
        "enabled": settings.get("auto_poll_enabled", True),
        "interval_minutes": settings.get("poll_interval_minutes", 5),
        "since_days": settings.get("poll_since_days", 7),
        "last_poll_at": _poll_state["last_poll_at"],
        "last_poll_error": _poll_state["last_poll_error"],
        "is_polling": _poll_state["is_polling"],
        "polls_completed": _poll_state["polls_completed"],
    }


@app.post("/api/email/poll-settings", tags=["Email"])
async def update_poll_settings(
    enabled: bool | None = None,
    interval_minutes: int | None = None,
    since_days: int | None = None,
):
    """Update auto-polling settings."""
    settings = _load_poll_settings()

    if enabled is not None:
        settings["auto_poll_enabled"] = enabled
    if interval_minutes is not None:
        if interval_minutes not in (1, 2, 5, 10, 15, 30):
            from fastapi import HTTPException
            raise HTTPException(400, "interval_minutes must be 1, 2, 5, 10, 15, or 30")
        settings["poll_interval_minutes"] = interval_minutes
    if since_days is not None:
        if since_days < 0 or since_days > 30:
            from fastapi import HTTPException
            raise HTTPException(400, "since_days must be 0-30")
        settings["poll_since_days"] = since_days

    _save_poll_settings(settings)
    return {"status": "ok", **settings}


@app.post("/api/email/reset", tags=["Email"])
async def reset_email_data_endpoint():
    """
    Reset all email-sourced data (email_log, documents, extraction_runs).

    Preserves manually uploaded documents. Use before re-polling to
    re-process emails with updated classification logic.
    """
    from api.workers.email_worker import reset_email_data

    result = reset_email_data()
    return {"status": "ok", "deleted": result}


# Initialize database on startup
@app.on_event("startup")
async def startup():
    # Configure structured logging from environment
    import os
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_format = os.getenv("LOG_FORMAT", "text")
    if log_format == "json":
        fmt = '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
    else:
        fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO), format=fmt, force=True)
    logger.info("y7dispatch starting (log_level=%s, format=%s)", log_level, log_format)

    # Initialize original schema
    init_db()
    # Initialize new MVP schema (creates tables + runs migrations)
    init_schema()
    # Seed base auction types (needs auction_types table from init_schema)
    seed_base_auction_types()
    # Seed field mappings (needs auction_type rows from seed above)
    seed_default_field_mappings()
    # Initialize warehouses schema
    from api.routes.warehouses import init_warehouses_schema

    init_warehouses_schema()
    # Initialize templates schema
    from api.routes.field_mappings import init_template_schema

    init_template_schema()
    # Initialize training schema
    from api.routes.training import init_training_schema

    init_training_schema()
    # Initialize auction profiles schema
    from api.auction_profiles import init_auction_profiles_schema, seed_default_auction_profiles

    init_auction_profiles_schema()
    seed_default_auction_profiles()
    # Initialize warehouse constants schema
    from api.warehouse_constants import init_warehouse_constants_schema

    init_warehouse_constants_schema()
    # Initialize credentials table
    from services.credential_store import init_credentials_table

    init_credentials_table()
    # Initialize email log table
    from api.routes.email_log import (
        init_email_log_table,
        init_email_replies_table,
        init_email_templates_table,
        seed_default_templates,
    )

    init_email_log_table()
    init_email_replies_table()
    init_email_templates_table()
    seed_default_templates()
    # Initialize validation tables (VIN cache, ZIP cache, validation results)
    from api.routes.validation import init_validation_schema

    init_validation_schema()
    # Wire DLQ alert callback for failed processing notifications
    from api.dlq import get_dlq_service
    from services.alerting import Severity, send_alert

    def _dlq_alert(entry):
        send_alert(
            f"DLQ: {entry.failure_reason.value} — {entry.email_subject}",
            Severity.HIGH,
            context={"dlq_id": entry.id, "email_id": entry.email_id,
                      "reason": entry.failure_reason.value,
                      "details": entry.failure_details},
        )

    get_dlq_service().register_alert_callback(_dlq_alert)

    # Start auto-polling background task
    global _auto_poll_task
    _auto_poll_task = asyncio.create_task(_email_polling_loop())
    logger.info("Email auto-polling background task started")


# Serve frontend (simple HTML for now)
@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Vehicle Transport Automation</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            h1 { color: #333; }
            h2 { color: #555; border-bottom: 1px solid #eee; padding-bottom: 10px; margin-top: 30px; }
            .nav { margin: 20px 0; }
            .nav a { display: inline-block; margin: 5px 10px 5px 0; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 4px; }
            .nav a:hover { background: #0056b3; }
            .status { padding: 10px; background: #d4edda; border-radius: 4px; margin: 10px 0; }
            .section { margin: 15px 0; }
            .section-title { font-weight: bold; color: #333; margin-bottom: 5px; }
            code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Vehicle Transport Automation</h1>
            <p>Control Panel for Email-to-ClickUp Pipeline with ML Training Support</p>

            <div class="status">
                API Server Running - Version 2.0.0
            </div>

            <div class="nav">
                <a href="/api/docs">API Documentation</a>
                <a href="/api/health">Health Check</a>
                <a href="/api/auction-types/">Auction Types</a>
                <a href="/api/documents/">Documents</a>
            </div>

            <h2>Core Workflow APIs</h2>

            <div class="section">
                <div class="section-title">Auction Types</div>
                <code>GET /api/auction-types/</code> - List auction types<br>
                <code>POST /api/auction-types/</code> - Create auction type<br>
            </div>

            <div class="section">
                <div class="section-title">Documents</div>
                <code>POST /api/documents/upload</code> - Upload document (PDF)<br>
                <code>GET /api/documents/</code> - List documents<br>
            </div>

            <div class="section">
                <div class="section-title">Extractions</div>
                <code>POST /api/extractions/run</code> - Run extraction on document<br>
                <code>GET /api/extractions/needs-review</code> - List runs needing review<br>
            </div>

            <div class="section">
                <div class="section-title">Review Workflow</div>
                <code>GET /api/review/{run_id}</code> - Get review items for run<br>
                <code>POST /api/review/submit</code> - Submit review corrections<br>
            </div>

            <div class="section">
                <div class="section-title">Export to Central Dispatch</div>
                <code>POST /api/exports/central-dispatch</code> - Export to CD<br>
                <code>GET /api/exports/central-dispatch/preview/{run_id}</code> - Preview payload<br>
            </div>

            <h2>ML Training APIs</h2>

            <div class="section">
                <div class="section-title">Training Data</div>
                <code>GET /api/review/training-examples/</code> - List training examples<br>
                <code>GET /api/review/training-examples/export</code> - Export as JSONL/CSV<br>
            </div>

            <div class="section">
                <div class="section-title">Model Versions</div>
                <code>GET /api/models/versions</code> - List model versions<br>
                <code>POST /api/models/train</code> - Start training job<br>
                <code>POST /api/models/versions/{id}/promote</code> - Promote to active<br>
            </div>

            <div class="section">
                <div class="section-title">Training Stats</div>
                <code>GET /api/models/training-stats</code> - Training data stats per auction type<br>
            </div>

            <h2>Legacy APIs</h2>

            <div class="section">
                <code>GET/POST /api/settings/*</code> - Settings management<br>
                <code>POST /api/test/upload</code> - Test upload<br>
                <code>GET /api/runs/</code> - Run history<br>
            </div>
        </div>
    </body>
    </html>
    """
