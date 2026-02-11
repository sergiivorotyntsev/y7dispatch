# Y7Dispatch: Development Directive v3.0

> **Date**: 2026-02-11
> **Status**: ACTIVE — Replaces all prior task lists
> **Scope**: Phases 0–3 stabilization + parallel UI track
> **Principle**: Ship a working pipeline. Every commit must move closer to 6 green checks.

---

## CORE RULE

Nothing gets built, refactored, or "improved" unless it directly serves one of the **6 Production Gates** below. If a task doesn't map to a gate — it waits.

### 6 Production Gates (ALL must be GREEN before any new scope)

```
[ ] GATE 1: Email → DB row < 60 sec (Copart, IAA, Manheim)
[ ] GATE 2: VIN extraction accuracy ≥ 99% on golden set
[ ] GATE 3: Address extraction accuracy ≥ 95% on golden set
[ ] GATE 4: CD export success ≥ 98% on 20 real listings
[ ] GATE 5: Zero silent failures (every error → DLQ or alert)
[ ] GATE 6: Market Intelligence pricing works with manual fallback
```

---

## TRACK A: Backend Pipeline (PRIMARY)

### A1. Dead Code Removal (IMMEDIATE — Day 1)

**Do first. No exceptions.**

| Action | Why |
|--------|-----|
| Delete `services/training_service.py` ML training logic | Placeholder code, 0% functional. Claude Haiku at 90%+ makes ML unnecessary at this volume. Re-add only if accuracy drops below 95% AND golden set exceeds 500 docs |
| Delete Sheets exporter v1 and v2 | Keep only v3. Three live versions = untestable. v3 is the unified schema |
| Delete ClickUp integration stub | Non-functional, adds confusion |
| Remove `TODO: Implement ML extraction` from `api/routes/extractions.py:704` | Dead reference to deleted feature |
| Remove `TODO: analyze why prediction was wrong` from `services/training_service.py:334` | File is being deleted |
| Audit all 58 endpoints — disable any that serve deleted features | Fewer endpoints = smaller attack surface, easier testing |

**After cleanup, run full test suite. Fix any breakage. Commit as `chore: remove dead code and unused integrations`.**

### A2. E2E Tests (Week 1 — Gates 1, 4, 5)

Write exactly **5 E2E tests**. Each test covers the full pipeline, not mocked layers:

```python
# tests/e2e/test_pipeline.py

class TestCopartPipeline:
    """Real Copart PDF → extraction → DB row → Sheet row"""
    def test_email_to_sheet_row(self):
        # 1. Simulate email with real Copart PDF attachment
        # 2. Assert: DB row created within 60 sec
        # 3. Assert: VIN matches ground truth
        # 4. Assert: pickup address matches ground truth
        # 5. Assert: gate_pass extracted from email body
        # 6. Assert: row_status = NEW

class TestIAAPipeline:
    """Same flow for IAA"""

class TestManheimPipeline:
    """Same flow for Manheim"""

class TestCDExport:
    """DB row → preflight check → CD API export"""
    def test_export_valid_listing(self):
        # 1. Create DB row with all required fields
        # 2. Run preflight_check → assert ready=True
        # 3. Mock CD API → assert POST /listings called with correct payload
        # 4. Assert: row_status = EXPORTED, cd_listing_id populated

class TestErrorHandling:
    """Corrupted PDF, missing attachment, duplicate email"""
    def test_corrupted_pdf_goes_to_dlq(self):
    def test_duplicate_email_deduplicated(self):
    def test_unknown_auction_type_flags_manual_review(self):
```

**These 5 tests are the acceptance criteria for TRACK A. Pipeline is not "done" until all 5 pass.**

### A3. Sheets Exporter Consolidation (Week 1)

- Delete `sheets_exporter_v1.py`, `sheets_exporter_v2.py`
- Rename `sheets_exporter_v3.py` → `sheets_exporter.py`
- Update all imports
- Verify: DB → Sheets sync works with unified exporter
- Verify: Apps Script webhook (override columns) → DB update works
- Add reconciliation job: every 5 min, compare DB vs Sheets, log diffs

### A4. Market Intelligence Pricing (Week 2 — Gate 6)

Implement `PricingEngine` as defined in approved architecture:

```python
class PricingEngine:
    """
    Hybrid pricing: system recommends, user confirms.
    
    Formula:
      base = avg_dispatch_price + (spread × 0.5)
      where spread = avg_listing_price - avg_dispatch_price
      
    Urgency modifiers:
      STANDARD (5-7 days): ×1.0
      PRIORITY (2-4 days): ×1.12
      URGENT (24-48h):     ×1.25
      
    Floor: max($150, $0.40/mile, avg_dispatch × 0.85)
    Ceiling: min($2.00/mile, avg_dispatch × 1.50)
    
    Fallback: if CD API unavailable → price=None, status=MANUAL_REQUIRED
    """
```

**Google Sheets pricing columns:**

| Column | Type | Behavior |
|--------|------|----------|
| `suggested_price` | SYSTEM | Auto-filled by PricingEngine |
| `price_source` | SYSTEM | CD_MARKET_INTEL / MANUAL_REQUIRED / MANUAL_OVERRIDE |
| `price_warnings` | SYSTEM | "Below market" / "Above market" / empty |
| `final_price` | OVERRIDE | User sets. Empty = accept suggested_price |
| `urgency` | OVERRIDE | STANDARD / PRIORITY / URGENT |

**Rule**: if `final_price` is empty at export time → use `suggested_price`. If `suggested_price` is also empty → block export with error "Price required".

### A5. Golden Dataset Expansion (Ongoing — Gates 2, 3)

Current: 23 documents. Target: 150 (50 per auction).

**Priority order for adding documents:**
1. Documents that caused extraction errors in production (add to `edge_cases/`)
2. Documents from different states (geographic variety)
3. Documents with missing fields (add to `missing_fields/`)
4. Multi-vehicle lots (add to `multi_vehicle/`)
5. Standard documents to fill quota

**Each document added must include `_ground_truth.json` with ALL CD-required fields manually verified.**

---

## TRACK B: Frontend UI (PARALLEL)

> UI development runs in parallel with backend. UI work MUST NOT block or depend on backend tasks from Track A (use mock data/API stubs where backend isn't ready).

### B0. UI Architecture Principles

```
Rules:
1. UI consumes the EXISTING API. Do not create new endpoints for UI convenience.
   If data exists in an endpoint — use it. If it doesn't — it's not needed in UI yet.
   
2. UI must work with mock data when backend is incomplete.
   Every API call has a fallback mock. This decouples frontend velocity from backend.
   
3. UI scope is OPERATOR DASHBOARD — one user (Sergii). 
   No auth system. No multi-tenant. No role-based access.
   Simple, functional, data-dense.

4. UI reflects pipeline state, not controls pipeline logic.
   Business logic lives in backend services. UI displays status and allows overrides.
```

### B1. Fix Evidence Overlay (Week 1)

**Problem**: PDF coordinate space (origin bottom-left) ≠ Canvas/SVG (origin top-left).

**Solution**:
```
canvas_y = page_height - pdf_y - bbox_height
```

**Scope**: Fix the coordinate transform in the overlay component. Test with 5 documents from each auction type. If edge cases remain (rotated pages, multi-column) — hide overlay for those and show text-only evidence instead. Do NOT spend more than 2 days on this.

### B2. Stabilize Existing 4 Pages (Week 1–2)

**Documents page**: Must show list of processed documents with: status badge (NEW/READY/EXPORTED/ERROR), auction type filter, date sort. No new features — fix what's broken.

**Review page**: Must show extracted fields alongside PDF. Each field shows: value, confidence score (color-coded: green ≥0.9, yellow 0.7–0.9, red <0.7), source evidence text. Override input for any field.

**TestLab page**: Upload a PDF → run extraction → show results. This is your testing tool. Must work reliably.

**Settings page**: Connection status for: Email (IMAP), Google Sheets, Central Dispatch API, Claude API. Show last successful sync timestamp for each.

### B3. Add Pricing UI to Review Page (Week 2 — after A4)

When Market Intelligence backend is ready, add to Review page:

```
┌─────────────────────────────────────────────────┐
│ PRICING                                          │
│                                                  │
│ Market Data (CD Intelligence):                   │
│   Avg Dispatch Price:  $485    (3 data points)   │
│   Avg Listing Price:   $550                      │
│   Spread:              $65                        │
│                                                  │
│ Recommended:  $517   [STANDARD ▼]                │
│                                                  │
│ ⚠ Warning: None                                  │
│ Floor: $425  |  Ceiling: $727                    │
│                                                  │
│ Final Price: [_______]  (empty = accept $517)    │
│                                                  │
│ [Export to CD]                                   │
└─────────────────────────────────────────────────┘
```

**Until backend is ready**: show this section with mock data and disabled Export button.

### B4. Export Flow UI (Week 2)

Add to Review page:

1. **Preflight Check button** → calls `/api/exports/preflight/{dispatch_id}`
   - Shows: list of errors (red), warnings (yellow), all-clear (green)
2. **Export button** (enabled only after green preflight)
   - Confirmation modal: "Export to Central Dispatch? Price: $517"
   - On success: show `cd_listing_id`, update status badge
   - On failure: show error message, suggest fix

---

## TRACK C: Infrastructure (AS NEEDED)

### C1. Monitoring (Week 2)

**Minimum viable monitoring — no Prometheus, no Grafana, no dashboards:**

```python
# Simple structured logging → stdout → DigitalOcean Logs

logger.info("pipeline_complete",
    dispatch_id="D-2026-0211-A1",
    auction_type="COPART",
    extraction_accuracy=0.94,
    cost_usd=0.02,
    duration_sec=12.4,
    fields_extracted=15,
    fields_missing=2)

logger.error("extraction_failed",
    dispatch_id="D-2026-0211-A2",
    error="corrupted_pdf",
    sent_to_dlq=True)
```

**Alerts** (Slack webhook or email — pick one):
- DLQ item added → immediate alert
- CD export failed → immediate alert
- Claude API cost > $5/day → daily summary
- Extraction accuracy < 90% on any document → immediate alert

### C2. Database Decision

**Make the call NOW and stop hedging:**

If daily volume < 100 documents → **SQLite** is fine. Simpler backup (copy file), no connection management, zero ops overhead.

If daily volume > 100 OR multi-worker needed → **PostgreSQL** on DigitalOcean Managed.

Current Y7 volume: ~20-50 docs/day → **SQLite. Final answer. Move on.**

---

## EXPLICIT DO-NOT-DO LIST

| Don't | Why |
|-------|-----|
| Don't add new API endpoints | 58 is too many already. Disable unused ones first |
| Don't build ML/PEFT/LoRA anything | Volume too low, Claude Haiku accuracy is sufficient |
| Don't build Template Builder UI | YAML configs work for one operator |
| Don't integrate ClickUp | Out of scope, adds no pipeline value |
| Don't add auth/RBAC to UI | One user. Waste of time |
| Don't refactor to microservices | Monolith is correct for this scale |
| Don't add WebSocket real-time updates | Polling every 30 sec in UI is sufficient |
| Don't write Architecture Decision Records | Document decisions in code comments and this file |
| Don't add Prometheus/Grafana | Structured logs + Slack alerts is enough |
| Don't touch RingCentral SMS | Paused. Separate product |

---

## WEEKLY CADENCE

### Week 1: Clean + Stabilize

| Day | Track A (Backend) | Track B (Frontend) |
|-----|-------------------|-------------------|
| Mon | A1: Delete dead code, run tests | B1: Fix Evidence Overlay |
| Tue | A2: Write E2E test 1-2 (Copart, IAA) | B1: Test overlay with 15 docs |
| Wed | A2: Write E2E test 3 (Manheim) | B2: Fix Documents page bugs |
| Thu | A3: Consolidate Sheets exporter | B2: Fix Review page bugs |
| Fri | A2: Write E2E tests 4-5 (Export, Errors) | B2: Fix TestLab, Settings |

**Week 1 exit criteria**: All 5 E2E tests pass. Dead code removed. One sheets exporter.

### Week 2: Pricing + Export

| Day | Track A (Backend) | Track B (Frontend) |
|-----|-------------------|-------------------|
| Mon | A4: PricingEngine implementation | B3: Pricing UI (mock data) |
| Tue | A4: CD Market Intelligence integration | B3: Connect to real API |
| Wed | A4: Floor/ceiling/warnings logic | B4: Preflight check UI |
| Thu | A4: E2E test for pricing + export flow | B4: Export flow UI |
| Fri | Full pipeline test: 20 real documents | Full UI walkthrough |

**Week 2 exit criteria**: All 6 Production Gates green. Pricing works end-to-end.

### Week 3+: Golden Dataset + Hardening

- Expand golden dataset toward 150 target
- Fix extraction failures found in real documents
- Polish UI based on real usage friction
- Performance optimization if latency > 60 sec

---

## DEFINITION OF DONE

Y7Dispatch Phase 0–3 is **DONE** when:

1. ✅ All 6 Production Gates are GREEN
2. ✅ 5 E2E tests pass in CI
3. ✅ Zero dead code (no stubs, no unused exporters, no placeholder routes)
4. ✅ UI shows pipeline status, extraction results, pricing, and export flow
5. ✅ 20 real documents processed end-to-end without manual intervention
6. ✅ Alerts working (DLQ, export failures, cost)

After this point — and ONLY after — consider: expanding golden dataset to 150, adding new auction types, improving UI polish, reopening RingCentral SMS scope.

---

*This directive supersedes ARCHITECTURE_PROPOSAL.md and IMPLEMENTATION_PHASES.md for task prioritization. Architecture and phases docs remain valid for system design reference.*
