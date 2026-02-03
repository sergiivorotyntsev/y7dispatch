"""FastAPI Control Panel for Vehicle Transport Automation.

Run with: uvicorn api.main:app --reload --port 8000

Endpoints:
- /api/settings - Configuration management
- /api/test - Test/Sandbox (upload, preview, dry-run)
- /api/runs - Run history and logs
- /api/health - Health check
- /api/auction-types - Auction type management
- /api/documents - Document upload and management
- /api/extractions - Extraction run management
- /api/review - Review items and submit workflow
- /api/exports - Central Dispatch export
- /api/models - ML model versions and training
"""

import sys
import uuid
from contextvars import ContextVar
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Context variable for request ID - accessible throughout the request lifecycle
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

from api.database import init_db
from api.models import init_schema, seed_base_auction_types
from api.routes import (
    auction_types,
    documents,
    exports,
    extractions,
    field_mappings,
    health,
    integrations,
    metrics,
    models,
    reviews,
    runs,
    settings,
    test,
    training,
    warehouses,
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


app = FastAPI(
    title="Vehicle Transport Automation",
    description="Control Panel for Email-to-ClickUp Pipeline with ML Training Support",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Request ID middleware - add first so it runs for all requests
app.add_middleware(RequestIDMiddleware)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],  # Allow frontend to read request ID
)

# Include original routers
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(test.router, prefix="/api/test", tags=["Test/Sandbox"])
app.include_router(runs.router, prefix="/api/runs", tags=["Runs/History"])

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


# =============================================================================
# EMAIL WORKER ENDPOINTS
# =============================================================================


@app.post("/api/email/poll", tags=["Email"])
async def poll_email_now():
    """
    Poll email inbox now (manual trigger).

    Triggers an immediate poll of the configured email inbox.
    Returns processing results.
    """
    from api.workers.email_worker import get_worker

    worker = get_worker()
    results = worker.poll_once()

    return {
        "status": "ok",
        "processed": len([r for r in results if r.status == "processed"]),
        "skipped": len([r for r in results if r.status == "skipped"]),
        "failed": len([r for r in results if r.status == "failed"]),
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


# Initialize database on startup
@app.on_event("startup")
async def startup():
    # Initialize original schema
    init_db()
    # Initialize new MVP schema
    init_schema()
    # Seed base auction types
    seed_base_auction_types()
    # Initialize warehouses schema
    from api.routes.warehouses import init_warehouses_schema

    init_warehouses_schema()
    # Initialize templates schema
    from api.routes.field_mappings import init_template_schema

    init_template_schema()
    # Initialize training schema
    from api.routes.training import init_training_schema

    init_training_schema()


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
