# API Reference

> All endpoints grouped by domain. Base URL: `/api/`.

## Authentication

All endpoints require JWT auth via httpOnly cookie (except `/auth/login`, `/health`).

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/login` | Login (username/password → JWT cookie) |
| POST | `/auth/logout` | Logout (clear cookie) |
| GET | `/auth/me` | Get current user info |

---

## Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (returns dependency statuses) |
| GET | `/ready` | Readiness probe |
| GET | `/live` | Liveness probe |

---

## Documents

| Method | Path | Description |
|--------|------|-------------|
| POST | `/documents/upload` | Upload PDF (multipart form) |
| GET | `/documents/` | List documents (paginated, filterable) |
| GET | `/documents/stats` | Document count by status |
| GET | `/documents/{id}` | Get document details |
| GET | `/documents/{id}/text` | Get extracted text |
| GET | `/documents/{id}/file` | Download PDF file (Cache-Control: immutable, ETag: SHA256) |
| GET | `/documents/{id}/page/{n}/image` | Render page as image (DPI configurable) |
| GET | `/documents/{id}/export-preview` | Quick export preview |
| DELETE | `/documents/{id}` | Delete document |
| POST | `/documents/check-vin-duplicate` | Check VIN before upload |
| POST | `/documents/set-hold` | Place document on hold |
| POST | `/documents/release-hold` | Release from hold |
| POST | `/documents/archive` | Archive document |
| POST | `/documents/unarchive` | Unarchive document |
| POST | `/documents/auto-assign-warehouse` | Auto-assign nearest warehouse |

---

## Extractions

| Method | Path | Description |
|--------|------|-------------|
| POST | `/extractions/run` | Start extraction (sync or async) |
| GET | `/extractions/status/{run_id}` | Poll async extraction status |
| GET | `/extractions/` | List extraction runs (paginated) |
| GET | `/extractions/stats` | Extraction statistics |
| GET | `/extractions/needs-review` | Runs needing review |
| GET | `/extractions/{id}` | Get extraction run details |
| PUT | `/extractions/{id}` | Update extraction (field corrections) |
| GET | `/extractions/{id}/debug` | Debug info for extraction |
| GET | `/extractions/{run_id}/email-context` | Email context for run |
| GET | `/extractions/{run_id}/duplicates` | VIN duplicate info |

---

## Review

| Method | Path | Description |
|--------|------|-------------|
| GET | `/review/{run_id}` | Get review items for run |
| GET | `/review/{run_id}/core` | Combined: run + document + review items (replaces 3 calls) |
| PUT | `/review/{run_id}/item/{item_id}` | Update single review item |
| POST | `/review/submit` | Submit review corrections |
| POST | `/review/{run_id}/approve` | Approve extraction |
| GET | `/review/{run_id}/evidence` | Field extraction evidence (bboxes) |
| GET | `/review/{run_id}/preflight` | Pre-export validation check |

---

## Validation

| Method | Path | Description |
|--------|------|-------------|
| POST | `/runs/{run_id}/validate` | Run VIN + address validation |
| GET | `/runs/{run_id}/validation` | Get validation results |

---

## Exports (Central Dispatch)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/exports/central-dispatch` | Export to CD (dry-run or live) |
| GET/POST | `/exports/central-dispatch/preview/{run_id}` | Preview CD payload |
| POST | `/exports/batch-post` | Batch export multiple runs |
| POST | `/exports/batch-post/preflight` | Batch preflight validation |
| GET | `/exports/cd-listing/{run_id}` | Get CD listing + ETag |
| GET | `/exports/jobs` | List export jobs |
| GET | `/exports/jobs/{job_id}` | Get export job details |
| POST | `/exports/jobs/{job_id}/retry` | Retry failed export |
| GET | `/exports/field-registry` | List all field definitions |
| GET | `/exports/field-registry/blocking-issues/{run_id}` | Blocking validation errors |
| GET | `/exports/pricing/{run_id}` | Get pricing for run |
| GET | `/exports/audit-trail/{run_id}` | Export audit trail |

### Export Request Body
```json
{
  "run_ids": [42],
  "dry_run": true,
  "overrides": {
    "warehouse_id": 1,
    "trailer_type": "OPEN",
    "price_total": 450.00,
    "cod_amount": 0,
    "available_date": "2026-03-03"
  },
  "field_overrides": {
    "buyer_id": "535527",
    "vehicle_color": "WHITE"
  }
}
```

---

## Warehouses

| Method | Path | Description |
|--------|------|-------------|
| GET | `/warehouses/` | List all warehouses |
| POST | `/warehouses/` | Create warehouse |
| GET | `/warehouses/{id}` | Get warehouse details |
| PUT | `/warehouses/{id}` | Update warehouse |
| DELETE | `/warehouses/{id}` | Soft-delete warehouse |
| GET | `/warehouses/options` | Distance-sorted options (by pickup ZIP) |
| GET | `/warehouses/options-for-run/{run_id}` | Options for specific run |
| POST | `/warehouses/sync-yaml` | Sync from warehouses.yaml |

---

## Pricing

| Method | Path | Description |
|--------|------|-------------|
| POST | `/pricing/recommend` | Get pricing recommendation |
| POST | `/pricing/recommend/batch` | Batch pricing |
| POST | `/pricing/override` | Override price |
| GET | `/pricing/{run_id}` | Get full pricing for run |
| GET | `/pricing/config` | Get pricing configuration |
| GET | `/pricing/cd-market-intelligence` | CD market data |

---

## Email

| Method | Path | Description |
|--------|------|-------------|
| POST | `/email/poll` | Trigger manual email poll |
| POST | `/email/scan` | Scan emails in date range |
| POST | `/email/process-selected` | Process specific message IDs |
| GET | `/email/poll-status` | Current poll status + settings |
| PUT | `/email/poll-settings` | Update poll interval/settings |
| POST | `/email/worker/start` | Start background worker |
| POST | `/email/worker/stop` | Stop background worker |

### Email Log

| Method | Path | Description |
|--------|------|-------------|
| GET | `/email-log/` | Paginated email log |
| POST | `/email-log/{id}/process` | Process email |
| POST | `/email-log/{id}/skip` | Skip email |
| POST | `/email-log/{id}/reprocess` | Reprocess email |
| GET | `/email-log/stats` | Email stats by status |

### Email Replies

| Method | Path | Description |
|--------|------|-------------|
| POST | `/runs/{run_id}/reply` | Send confirmation reply |
| POST | `/runs/{run_id}/reply/preview` | Preview reply |
| GET | `/runs/{run_id}/reply/status` | Reply status |

### Email Templates

| Method | Path | Description |
|--------|------|-------------|
| GET | `/email-templates/reply_confirmation` | Get reply template |
| PUT | `/email-templates/reply_confirmation` | Update reply template |
| POST | `/email-templates/reply_confirmation/preview` | Preview template |
| POST | `/email-templates/reply_confirmation/reset` | Reset to default |

---

## Settings

| Method | Path | Description |
|--------|------|-------------|
| GET | `/settings/status` | All integration statuses |
| GET/PUT | `/settings/` | Global settings |
| GET/PUT | `/settings/cd` | CD configuration |
| GET/PUT | `/settings/email` | Email configuration |
| GET/PUT | `/settings/warehouses` | Warehouse list |
| GET/PUT | `/settings/export-targets` | Export targets |
| GET/PUT | `/settings/fields` | Field configurations |

---

## Credentials

| Method | Path | Description |
|--------|------|-------------|
| GET | `/credentials/` | List all (secrets masked) |
| GET | `/credentials/{service}` | Get credential |
| PUT | `/credentials/{service}` | Save/update credential |
| DELETE | `/credentials/{service}` | Delete credential |
| POST | `/credentials/{service}/test` | Test credential |

**Services:** `cd_api`, `email_imap`, `email_oauth`, `anthropic`, `google_maps`, `sheets`

---

## Auction Types

| Method | Path | Description |
|--------|------|-------------|
| GET | `/auction-types/` | List all |
| GET | `/auction-types/{id}` | Get by ID |
| GET | `/auction-types/code/{code}` | Get by code |
| POST | `/auction-types/` | Create |
| PUT | `/auction-types/{id}` | Update |
| DELETE | `/auction-types/{id}` | Delete |

---

## Auction Directory

| Method | Path | Description |
|--------|------|-------------|
| GET | `/auction-directory/lookup?name={name}` | Look up auction location |

---

## Weather

| Method | Path | Description |
|--------|------|-------------|
| GET | `/weather/route-alerts` | Alerts by pickup/warehouse ZIP |
| GET | `/weather/route-alerts-for-run/{run_id}` | Alerts for specific run |

---

## Metrics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/metrics/extractions` | Extraction metrics |
| GET | `/metrics/quality` | Quality metrics |
| GET | `/metrics/summary` | Dashboard summary |
| GET | `/metrics/drift/alerts` | Model drift alerts |

---

## OAuth Integration

| Method | Path | Description |
|--------|------|-------------|
| POST | `/integrations/oauth/microsoft/init` | Start Microsoft OAuth flow |
| GET | `/integrations/oauth/callback` | OAuth callback |
| GET | `/integrations/oauth/token/microsoft` | Get Microsoft token status |
| DELETE | `/integrations/oauth/token/microsoft` | Revoke Microsoft token |

---

## Tests & Configuration

### Running Tests
```bash
# Full suite (1459+ tests)
python -m pytest tests/ -q

# Specific test file
python -m pytest tests/e2e/test_copart_directory_advisory.py -v

# Frontend build
cd web && npm run build
```

### Test Structure
| Directory | Files | Tests | Focus |
|-----------|-------|-------|-------|
| `tests/e2e/` | 39 | ~539 | End-to-end pipeline tests |
| `tests/` (root) | 18 | ~546 | Unit tests |
| `tests/evaluation/` | 3 | 5 | Golden dataset accuracy |
| **Total** | **60** | **~1459** | |

### Deployment
```bash
scripts/deploy.sh    # Pull → build → Docker restart → health check
scripts/backup.sh    # DB + config → tar.gz (keeps last 30)
scripts/restore.sh   # Restore from backup archive
```

### Environment Variables (Key)
| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_PATH` | `data/control_panel.db` | SQLite path |
| `ANTHROPIC_API_KEY` | (required) | Claude Haiku extraction |
| `JWT_SECRET` | (dev default) | JWT signing |
| `AUTH_USERNAME` | `sergii` | Login username |
| `CORS_ORIGINS` | `localhost:3000,5173` | CORS domains |
| `LOG_LEVEL` | `INFO` | Logging level |
