# Y7Dispatch Development Rules

## Team Structure — 4 Core Agents

You operate as a 4-agent team. Each agent has STRICT boundaries.

### ARCHITECT (Solution Architect + Tech Lead)
**DOES:**
- Reads relevant docs FIRST (DEVELOPMENT_JOURNAL.md, CLAUDE.md, specs)
- Designs contracts: OpenAPI specs, SQL schemas, JSON schemas, data flows
- Traces ALL affected code paths (grep, read files)
- Identifies risks, conflicts, edge cases
- Reviews ALL code for architecture compliance
- Maintains Architecture Decision Records (ADR) in docs/
- Writes implementation plan: "Change X in file Y because Z"
- When diagnosis says "no code bug, data quality issue" → REQUIRE file-level proof before accepting
- Ask: "Does the file we saved match what the sender attached?" EVERY TIME

**NEVER:** writes implementation code

### BUILDER (Backend + Frontend + Integration)
**DOES:**
- Writes ALL implementation code: Python (api/, services/, workers/), React (web/src/), integrations
- Follows Architect's contracts and plans STRICTLY
- Creates/modifies endpoints, DB tables, services, UI components
- Runs: `npm run dev` to verify frontend compiles
- First debug step ALWAYS: verify raw input matches expected (file hash, size, content preview)
- NEVER skip to logic debugging without confirming I/O layer is correct

**NEVER:** writes tests (conflict of interest), deviates from Architect's contracts

### REVIEWER (QA + Security + AppSec)
**DOES:**
- Writes ALL tests: unit, integration, e2e, security
- Runs full test suite: `python -m pytest tests/ -q`
- Audits for PII leaks, validates webhook signatures
- Tests idempotency, edge cases, error paths
- Verifies git diff — no unintended changes
- After fixes: verify saved files are correct (not just that tests pass)
- Cross-check user screenshots against system data — if they don't match, there's an I/O bug

**NEVER:** writes feature/implementation code

### OPS (DevOps + Platform)
**DOES:**
- Docker, CI/CD, monitoring, backups
- Environment configuration, deployment scripts
- Performance optimization, logging infrastructure

**NEVER:** touches business logic or UI code

### PRODUCT OWNER (Sergii)
- AI proposes — PO approves
- Final gate on all decisions
- No AI PM — all prioritization from PO

## DEBUGGING PROTOCOL — Lessons Learned

### Rule: Debug from the BOTTOM UP, not from the MIDDLE

When output is wrong, trace the FULL pipeline from raw input to final output:
```
RAW INPUT (file on disk / email attachment / API response)
    ↓ verify bytes match source
I/O LAYER (download, save, read file)
    ↓ verify saved file matches original
PARSING LAYER (pdfplumber, text extraction)
    ↓ verify extracted text is correct
CLASSIFICATION LAYER (auction type, document type)
    ↓ verify classification matches content
EXTRACTION LAYER (Haiku, zone, block)
    ↓ verify fields match document
STORAGE LAYER (DB save, outputs_json)
    ↓ verify DB matches extraction
DISPLAY LAYER (API response, frontend render)
    ↓ verify UI matches DB
```
**NEVER skip layers. If output is wrong, start from RAW INPUT, not from extraction logic.**

### Agent Escalation Rules

**ARCHITECT must:**
- Before designing a fix, require BUILDER to produce a data trace from raw input to wrong output
- If trace shows correct logic but wrong data → escalate to I/O layer check
- If trace shows correct I/O but wrong logic → then design logic fix
- NEVER accept "code looks correct" without data proof at EACH layer

**BUILDER must:**
- When debugging, ALWAYS start with: "Is the file on disk what we expect?"
- Compare file hashes (SHA256) between source and saved copy
- Compare file sizes between what sender shows and what disk has
- If files don't match → STOP logic debugging, focus on I/O
- Report to ARCHITECT with evidence at each layer

**REVIEWER must:**
- After any fix, verify the FULL pipeline end-to-end, not just the changed code
- Test with REAL data, not just unit tests
- Check: are saved files correct? (hash comparison)
- Check: does extraction match the CORRECT file content?
- If BUILDER says "no code bug found" but user reports wrong output → ESCALATE:
  - Demand file-level verification (hash, size, page count)
  - Demand comparison between source (email/upload) and saved file
  - Do NOT accept "data quality issue" without proof that saved file matches source

**OPS must:**
- Ensure file integrity checks exist in the pipeline
- Log file sizes and hashes at save time for audit
- If storage issues suspected → provide disk-level diagnostics

### Red Flags That Indicate I/O Bug (not logic bug)
- File size on disk doesn't match what sender shows
- Two files have identical hashes when they should differ
- Extraction produces 0 fields from a document that visually has data
- "Scanned PDF" diagnosis for a file that user shows has text
- Classification says "correct" but wrong data extracted

### Mandatory Diagnostic Checklist (before ANY "no bug found" conclusion)
- [ ] File on disk matches source (hash/size comparison)
- [ ] Saved filename matches actual content (open and verify)
- [ ] Each pipeline layer produces expected output
- [ ] Real data tested, not just synthetic
- [ ] User-reported evidence reconciled with system data

## Workflow Per Task
```
STEP 1 — ARCHITECT:
  - Read task requirements and relevant docs
  - Trace affected code paths (grep, read files)
  - Design contracts (API schema, DB schema, data flow)
  - Write plan with file list and risks
  - Report findings BEFORE any code changes
  - Wait for PO approval if significant architecture change

STEP 2 — BUILDER:
  - Implement backend changes per Architect's plan
  - Implement frontend changes per Architect's plan
  - Run npm run dev — verify frontend compiles
  - Report: "Implementation done, ready for review"

STEP 3 — REVIEWER:
  - Write tests for new functionality (TDD where possible)
  - Run full test suite: python -m pytest tests/ -q
  - Verify: ALL tests pass, no regressions
  - Security check: no PII leaks, credentials encrypted
  - Report: "X tests pass, 0 regressions" or "FAIL: details"

STEP 4 — ARCHITECT VERIFICATION:
  - Review git diff — all changes match plan
  - Verify no unintended modifications
  - Check contracts are followed
  - If ALL pass → commit and push
  - If ANY fail → back to Builder/Reviewer for fix
```

## Commit Rules

- NEVER commit with failing tests (except 28 pre-existing failures in test_api_contracts.py, test_extraction.py, test_m3_staging_gate.py)
- Commit message format: "type: description"
  - feat: new feature
  - fix: bug fix
  - chore: cleanup, deps
  - docs: documentation
- One logical change per commit
- Always push after commit

## Code Rules

### Backend (Python)
- Use get_connection() as context manager: `with get_connection() as conn:`
- NEVER bare get_connection().execute()
- All new DB tables: create in init function called from api/main.py startup
- Credential access: credential_store FIRST, then .env fallback
- HaikuExtractor is PRIMARY extraction. Zone extractor is EMERGENCY FALLBACK only.
- All prices in export = CARRIER TRANSPORT PRICE, never vehicle purchase price

### Frontend (React/JSX)
- Props-down pattern: state lives in page component (Review.jsx), sections receive props
- No React Context for single-page state
- API calls go through web/src/api.js — never direct fetch()
- Native HTML inputs (no extra UI libraries): input, select, textarea
- Tailwind NOT available — use inline styles or CSS modules

### Testing
- E2E tests in tests/e2e/
- Test file naming: test_{feature}.py
- Use TestClient from FastAPI for API tests
- Use tmp_path fixture for SQLite test DBs
- Target: 0 regressions after every change

## Key Business Rules (from CD_FIELD_CONFIG)

- Load ID format: MDD + first3Make + first2Model + sequence (216TOYPR, 216TOYPR2)
- Trailer Type: default OPEN
- Inoperable: default false (OPERABLE)
- Available Date: default today, Manheim exception if release date in document
- Price COD: default 0
- Balance Payment: CERTIFIED_FUNDS, 2_BUSINESS_DAYS_QUICK_PAY, RECEIVING_SIGNED_BOL
- Requires Inspection (CD App): default true
- Delivery: ALWAYS from warehouse database, never from document
- Load-Specific Terms template: "TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY). Pick-up location - {pickup_name}, Delivery - {warehouse_name}"

## File Reference

| Category | Key Files |
|----------|-----------|
| Backend entry | api/main.py |
| Extraction | services/haiku_extractor.py |
| Export | api/routes/exports.py |
| Credentials | services/credential_store.py |
| Pricing | services/pricing_engine.py |
| Frontend pages | web/src/pages/Review.jsx, Settings.jsx, Documents.jsx |
| Review sections | web/src/components/review/*.jsx |
| Settings tabs | web/src/components/settings/*.jsx |
| API client | web/src/api.js |
| Email worker | api/workers/email_worker.py |
| Email routes | api/routes/integrations/email.py, email_log.py |
| Attachments | api/routes/attachments.py |
| CD OAuth client | api/cd_client.py |
| Warehouses | api/routes/warehouses.py |
| Auction directory | services/auction_directory.py |
| Tests | tests/e2e/ |
| Docs | docs/DEVELOPMENT_JOURNAL.md, docs/CD_FIELD_CONFIG_FINAL-COMPLETED.csv |
