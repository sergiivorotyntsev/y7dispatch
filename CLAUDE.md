# CLAUDE.md — Persistent Context for Vehicle Transport / Control Panel

> This file maintains project context for AI assistants. Update when architecture changes.

---

## 1. Project Goal

**Vehicle Transport Automation (y7dispatch)** — automate dispatcher document workflow:
- **Input**: Documents from email or manual upload (PDF invoices, gate passes, auction sheets)
- **Process**: Layout-aware extraction (blocks/spatial parsing) → Review UI with evidence overlay → Export
- **Output**: Central Dispatch listings via CD API

**Key requirements**:
- Layout-aware extraction preserving document structure (blocks, spatial coordinates)
- Provenance/evidence: every extracted field links back to source PDF region
- Auction profiles (Copart, IAA, Manheim) with specific parsing rules
- Warehouse constants (delivery locations are constants, not extracted from PDF)
- Async job queue for batch processing
- Full audit trail for compliance
- Metrics/observability endpoints
- E2E test coverage with golden sets

---

## 2. Tech Stack

### Backend (Python/FastAPI)
```
api/               # FastAPI routes, models, database
  ├── routes/      # REST endpoints (documents, listings, jobs, metrics)
  ├── models.py    # SQLModel entities (Document, Listing, AuditLog, BatchJob)
  ├── database.py  # SQLite + migrations
  ├── cd_client.py # Central Dispatch API client
  ├── batch_jobs.py, batch_queue.py  # Async job processing
  └── audit_log.py # Audit trail service

extractors/        # Document extraction pipeline
  ├── base.py      # BaseExtractor interface
  ├── block_extractor.py  # Layout-aware block extraction
  ├── spatial_parser.py   # Coordinate-based field detection
  ├── field_resolver.py   # Multi-source field resolution with precedence
  ├── copart.py, iaa.py, manheim.py  # Auction-specific extractors
  ├── ocr_strategy.py     # OCR fallback for scanned docs
  └── address_parser.py   # US address normalization

services/          # Business logic layer
  ├── orchestrator.py     # Pipeline orchestration
  ├── cd_exporter.py      # Central Dispatch export logic
  ├── warehouse.py        # Warehouse constants management
  └── sheets_*.py         # Google Sheets integration

core/              # Shared utilities
models/            # Pydantic schemas
schemas/           # OpenAPI/JSON schemas
```

### Frontend (React + Vite + Tailwind)
```
web/src/
  ├── components/   # React components
  ├── pages/        # Route pages (Documents, Review, Listings)
  └── services/     # API client hooks

ui/                # Legacy/static UI assets
```

### Configuration
```
cd_field_mapping.yaml     # Central Dispatch field mapping
cd_field_mapping_v2.yaml  # V2 mapping with validation rules
cd_defaults.yaml          # Default values for CD fields
warehouses.yaml           # Warehouse constants (addresses, codes)
.env.example              # Environment variables template
```

### Tests & QA
```
tests/             # pytest unit/integration tests
e2e/               # Playwright E2E tests
scripts/           # Utility scripts, load testing
diagnostics/       # Debug tools, extraction diagnostics

CI: GitHub Actions
- pytest with coverage
- Playwright E2E
- Staging gate before prod deploy
```

### Key Dependencies
- `pdfplumber` — PDF text/table extraction
- `pytesseract` + `pdf2image` — OCR fallback
- `fastapi` + `uvicorn` — API server
- `sqlmodel` — ORM (SQLite backend)
- `httpx` — Async HTTP client
- `tenacity` — Retry logic

---

## 3. Current Stage (M0–M3)

### M0–M2: Extraction Pipeline (COMPLETE)
- Block-based extraction with spatial coordinates
- OCR strategy for scanned documents
- Auction-specific extractors (Copart, IAA, Manheim)
- Field resolver with precedence rules
- Metrics and debug endpoints

### M3: Production Workflow (IN PROGRESS)
- Batch job processing with queue
- Audit trail for all operations
- Metrics endpoints (`/api/metrics/*`)
- UI evidence overlay (PDF viewer with field highlights)
- Preflight validation banner

### Current Issues (CD-aligned fix pack needed)
1. **Documents/Review UI**: Documents not recognized, fields empty
2. **Field mapping mismatch**: Extracted fields don't align with Central Dispatch API schema
3. **Missing validation**: Some required CD fields not validated before export
4. **Evidence overlay**: PDF coordinates not rendering correctly in Review UI

### Next Steps
- Fix CD field mapping alignment (see `cd_field_mapping_v2.yaml`)
- Implement Market Intelligence API for pricing (PROMPT 5)
- Add preflight validation before CD export
- Improve error messaging in Review UI

---

## 4. Domain Rules

### Field Resolution Precedence (CRITICAL)
```
1. USER_OVERRIDE    — Manual edits in Review UI (highest priority)
2. WAREHOUSE_CONST  — Warehouse constants (delivery addresses)
3. AUCTION_CONST    — Auction profile defaults
4. EXTRACTED        — Values from document extraction
5. DEFAULT          — Fallback defaults from cd_defaults.yaml
```

### Key Business Rules

**Delivery Location**:
- ALWAYS from `warehouses.yaml` constants
- NEVER extracted from PDF (user selects warehouse, system fills address)

**Pickup Location**:
- Extracted from document (auction address)
- Normalized via `address_parser.py`

**Pricing**:
- Use Central Dispatch Market Intelligence API (see PROMPT 5)
- Fallback to auction profile defaults if API unavailable

**Vehicle Identification**:
- VIN is primary key (17 chars, validated)
- Year/Make/Model extracted, cross-validated against VIN decode

**Dates**:
- All dates normalized to ISO 8601
- Pickup dates validated against auction schedule

### Central Dispatch Field Categories
```yaml
Required:    VIN, Year, Make, Model, PickupCity, PickupState,
             DeliveryCity, DeliveryState, VehicleType
Recommended: PickupZip, DeliveryZip, Price, AvailableDate
Optional:    Notes, SpecialInstructions, Operable, Enclosed
```

---

## 5. Quick Reference

### Run Development
```bash
# Backend
pip install -e ".[dev]"
uvicorn api.main:app --reload --port 8000

# Frontend
cd web && npm install && npm run dev

# Tests
pytest tests/ -v
cd e2e && npx playwright test
```

### Key API Endpoints
```
POST /api/documents/upload     # Upload document
GET  /api/documents/{id}       # Get document with extraction
POST /api/listings/export      # Export to Central Dispatch
GET  /api/jobs/{id}            # Check job status
GET  /api/metrics/extraction   # Extraction metrics
```

### Environment Variables
```
CD_API_KEY          # Central Dispatch API key
CD_API_BASE_URL     # CD API base URL
DATABASE_URL        # SQLite path (default: ./dispatch.db)
GOOGLE_CREDENTIALS  # Google Sheets service account JSON
```

---

## 6. Files to Reference

| Topic | Files |
|-------|-------|
| Field mapping | `cd_field_mapping.yaml`, `cd_field_mapping_v2.yaml` |
| Warehouse constants | `warehouses.yaml`, `api/warehouse_constants.py` |
| Extraction pipeline | `extractors/*.py`, especially `field_resolver.py` |
| CD integration | `api/cd_client.py`, `services/cd_exporter.py` |
| Audit/metrics | `api/audit_log.py`, `api/routes/metrics.py` |
| UI components | `web/src/components/`, `web/src/pages/` |

---

*Last updated: 2026-02-03*
