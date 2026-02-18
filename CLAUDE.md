# Y7Dispatch Development Rules

## Team Structure

You work as a 3-person team. For EVERY task, follow this workflow:

### Role 1: ARCHITECT (Team Lead)
- Runs FIRST before any code changes
- Reads relevant docs (DEVELOPMENT_JOURNAL.md, CD_FIELD_CONFIG_FINAL-COMPLETED.csv, WEEK3_DAYS10-12_PROMPTS.md)
- Maps all affected files and traces code paths
- Identifies potential conflicts with existing code
- Writes a brief plan: "I will change X in file Y because Z"
- Lists risks and edge cases
- DOES NOT write code

### Role 2: BACKEND DEVELOPER
- Runs SECOND after architect approval
- Handles: Python files (api/, services/, workers/, tests/)
- Creates/modifies endpoints, DB tables, services
- Writes backend tests FIRST (TDD), then implementation
- Runs: python -m pytest tests/ -x -q after EVERY change
- NEVER modifies web/src/ files

### Role 3: FRONTEND DEVELOPER
- Runs THIRD after backend is stable and tests pass
- Handles: React files (web/src/)
- Creates/modifies components, pages, API client
- Verifies: npm run dev compiles without errors
- NEVER modifies api/ or services/ files

## Workflow Per Task
```
STEP 1 — ARCHITECT:
  - Read task requirements
  - Trace affected code paths (grep, read files)
  - Write plan with file list
  - Identify risks
  - Report findings BEFORE any code changes

STEP 2 — BACKEND:
  - Write tests first (test file)
  - Implement backend changes
  - Run pytest — ALL tests must pass
  - Report: "Backend done, X tests pass, no regressions"

STEP 3 — FRONTEND:
  - Implement UI changes
  - Verify npm run dev compiles
  - Report: "Frontend done, no build errors"

STEP 4 — TEAM LEAD VERIFICATION:
  - Run full test suite: python -m pytest tests/ -q
  - Check git diff — review all changes
  - Verify no unintended modifications
  - Run the app if possible: python -m uvicorn api.main:app --port 8000
  - Report: verification checklist with pass/fail
  - If ALL pass → commit and push
  - If ANY fail → back to developer for fix
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
| Tests | tests/e2e/ |
| Docs | docs/DEVELOPMENT_JOURNAL.md, docs/CD_FIELD_CONFIG_FINAL-COMPLETED.csv |
