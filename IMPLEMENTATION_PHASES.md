# Y7Dispatch: Implementation Phases

> **Version**: 1.0 | **Date**: 2026-02-11
> **Status**: Draft for Approval

---

## Overview

Phased implementation plan for Y7Dispatch email-to-CD pipeline with Claude Haiku extraction.

**Total estimated phases**: 4
**Core deliverables**: Email→Claude→Sheets→CD automation

---

## Phase 0: Foundation & Evaluation Harness

**Goal**: Establish measurement infrastructure before building features.

### Deliverables

| # | Deliverable | Description |
|---|-------------|-------------|
| 0.1 | **Golden Dataset** | 30 annotated documents (10 Copart, 10 IAA, 10 Manheim) with ground truth for all CD-required fields |
| 0.2 | **Evaluation Framework** | Automated test harness: precision/recall/F1 per field, overall extraction score |
| 0.3 | **Regression Suite** | CI integration: any PR that drops metrics below threshold is blocked |
| 0.4 | **Cost Tracking** | Per-request cost logging (tokens in/out, model used, cached/uncached) |
| 0.5 | **Baseline Metrics** | Run current extractors against golden set, establish baseline |

### Acceptance Criteria

- [ ] `pytest tests/evaluation/` runs against golden set
- [ ] GitHub Actions workflow blocks PRs with >5% metric drop
- [ ] Dashboard shows cost per document in real-time
- [ ] Baseline report generated: current accuracy per field

### Technical Details

```
tests/
├── evaluation/
│   ├── golden_dataset/
│   │   ├── copart/
│   │   │   ├── doc_001.pdf
│   │   │   ├── doc_001_ground_truth.json
│   │   │   └── ...
│   │   ├── iaa/
│   │   └── manheim/
│   ├── test_extraction_accuracy.py
│   ├── metrics.py  # precision, recall, F1, extraction_score
│   └── conftest.py
```

---

## Phase 1: Claude Haiku Integration (Grounded Extraction)

**Goal**: Replace/augment current extractors with Claude Haiku + evidence tracking.

### Deliverables

| # | Deliverable | Description |
|---|-------------|-------------|
| 1.1 | **Haiku Extractor Service** | `services/haiku_extractor.py` — PDF + email body extraction |
| 1.2 | **Structured Output Schema** | Tool use definitions for guaranteed JSON output with all CD fields |
| 1.3 | **Citations/Evidence Tracking** | Link each extracted field to source location (page, text span) |
| 1.4 | **Post-Validation Layer** | VIN decode verification, address normalization (USPS), date validation |
| 1.5 | **Confidence Scoring** | Per-field confidence 0.0-1.0, aggregate document score |
| 1.6 | **Prompt Caching** | Cache template prompts for 90% token savings on repeated docs |

### Acceptance Criteria

- [ ] Extraction accuracy ≥90% on golden set (improvement over baseline)
- [ ] Every extracted field has `source_page`, `source_text` evidence
- [ ] VIN validation passes for 100% of valid VINs
- [ ] Average cost per document <$0.05

### Technical Details

```python
# services/haiku_extractor.py

class HaikuExtractor:
    MODEL = "claude-haiku-4-5-20251001"  # Updated model ID

    async def extract_with_evidence(
        self,
        document: bytes,
        document_type: Literal["pdf", "email"]
    ) -> ExtractionResult:
        """
        Extract fields with citations/evidence.

        Returns:
            ExtractionResult with:
            - fields: dict[str, ExtractedField]
            - evidence: dict[str, Citation]
            - confidence: float
            - tokens_used: TokenUsage
        """
```

```python
# schemas/extraction.py

class ExtractedField(BaseModel):
    value: Any
    confidence: float  # 0.0-1.0
    source: FieldSource  # EXTRACTED | VALIDATED | DEFAULT

class Citation(BaseModel):
    field_name: str
    page_number: int
    text_span: str
    bounding_box: Optional[BoundingBox]  # For PDF visual evidence

class ExtractionResult(BaseModel):
    fields: dict[str, ExtractedField]
    evidence: dict[str, Citation]
    confidence: float
    tokens_used: TokenUsage
    cost_usd: float
```

---

## Phase 2: Email Pipeline & Google Sheets Integration

**Goal**: Automate email→extraction→Sheets flow with single unified spreadsheet.

### Deliverables

| # | Deliverable | Description |
|---|-------------|-------------|
| 2.1 | **Email Processor Upgrade** | Parse email body with Claude Haiku, detect PDF attachments |
| 2.2 | **Gate Pass Logic** | Extract Gate Pass (Copart/IAA) or Vehicle Release ID (Manheim), flag if missing |
| 2.3 | **Unified Sheets Schema** | Single spreadsheet for all auctions/customers with filter columns |
| 2.4 | **Bidirectional Sync** | SQLite ↔ Sheets sync with override respect |
| 2.5 | **Manual Export Script** | Google Apps Script for one-click CD export from Sheets |
| 2.6 | **Field Status UI** | Visual indicators: green (complete), yellow (needs review), red (missing required) |

### Acceptance Criteria

- [ ] Email arrives → row appears in Sheets within 60 seconds
- [ ] Gate Pass missing → red indicator, no export block
- [ ] Vehicle Release ID (Manheim) correctly identified and stored
- [ ] User edits in Sheets reflect in DB within 30 seconds
- [ ] Export script creates CD listing successfully

### Technical Details

```yaml
# sheets_schema_unified.yaml

columns:
  # Primary Key
  - name: dispatch_id
    type: string
    class: PK

  # Source Identification
  - name: auction_type
    type: enum[COPART, IAA, MANHEIM]
    class: FILTER

  - name: customer_name
    type: string
    class: FILTER

  # Gate Pass / Release Document
  - name: release_document_type
    type: enum[GATE_PASS, VEHICLE_RELEASE_ID, NONE]
    class: BASE

  - name: release_document_value
    type: string
    class: BASE

  - name: release_document_status
    type: enum[present, missing]
    class: STATUS
    # UI: green if present, red if missing

  # ... remaining CD fields
```

---

## Phase 3: Central Dispatch Export & Market Intelligence

**Goal**: Automated export to CD with dynamic pricing.

### Deliverables

| # | Deliverable | Description |
|---|-------------|-------------|
| 3.1 | **Market Intelligence Integration** | CD API pricing lookup, cache results 24h |
| 3.2 | **Preflight Validation** | Check all required fields before export, show actionable errors |
| 3.3 | **Export Workflow** | One-click export from UI/Sheets with confirmation |
| 3.4 | **Retry & Idempotency** | ETag support, automatic retry with backoff |
| 3.5 | **Audit Trail** | Log all export attempts, results, errors |
| 3.6 | **Batch Export** | Select multiple rows, export in sequence with rate limiting |

### Acceptance Criteria

- [ ] Price fetched from CD Market Intelligence API, fallback to manual
- [ ] Export fails gracefully with clear error message if validation fails
- [ ] Successful export → `cd_listing_id` populated, `row_status = EXPORTED`
- [ ] All exports logged with timestamp, user, result

### Technical Details

```python
# services/cd_exporter.py

class CDExporter:
    async def preflight_check(self, dispatch_id: str) -> PreflightResult:
        """
        Validate all required fields before export.

        Returns:
            PreflightResult:
            - ready: bool
            - errors: list[ValidationError]
            - warnings: list[ValidationWarning]
        """

    async def get_market_price(
        self,
        origin: Address,
        destination: Address,
        vehicle: Vehicle
    ) -> PriceEstimate:
        """
        Fetch price from CD Market Intelligence API.

        Cache results for 24 hours.
        Fallback: return None, require manual price entry.
        """

    async def export_listing(
        self,
        dispatch_id: str,
        price_override: Optional[float] = None
    ) -> ExportResult:
        """
        Export to Central Dispatch.

        - Validates all fields
        - Fetches price if not overridden
        - Creates/updates listing via CD API
        - Updates row_status and cd_listing_id
        - Logs to audit trail
        """
```

---

## Phase 4: RingCentral SMS Automation

**Goal**: Carrier communication automation with business hours logic.

### Deliverables

| # | Deliverable | Description |
|---|-------------|-------------|
| 4.1 | **Webhook Handler** | Receive SMS via RingCentral webhook |
| 4.2 | **Business Hours Logic** | 9:00-21:00 → auto-response, otherwise → template |
| 4.3 | **Intent Parser** | Claude Haiku for SMS intent: pricing/availability/status |
| 4.4 | **Response Templates** | Configurable templates per intent type |
| 4.5 | **Carrier Database** | Link phone numbers to carrier profiles |
| 4.6 | **Conversation History** | Store SMS threads for context |

### Acceptance Criteria

- [ ] SMS received during business hours → intelligent response within 30 seconds
- [ ] SMS outside hours → "We'll respond during business hours" template
- [ ] Pricing inquiry → response with CD Market Intelligence range
- [ ] All SMS logged with carrier attribution

### Technical Details

```python
# config/sms_config.yaml

business_hours:
  timezone: America/New_York
  start: "09:00"
  end: "21:00"

templates:
  out_of_hours: |
    Thank you for contacting Y7 Dispatch.
    Our business hours are 9 AM - 9 PM EST.
    We'll respond to your inquiry shortly.

  pricing_response: |
    Route: {origin_city}, {origin_state} → {dest_city}, {dest_state}
    Estimated price: ${low_price} - ${high_price}
    Vehicle: {year} {make} {model}

    Reply YES to request pickup.
```

---

## Milestone Summary

| Phase | Name | Key Outcome | Dependencies |
|-------|------|-------------|--------------|
| **0** | Foundation | Evaluation harness, golden dataset | None |
| **1** | Claude Haiku | Grounded extraction with evidence | Phase 0 |
| **2** | Email→Sheets | Automated ingestion pipeline | Phase 1 |
| **3** | CD Export | Market pricing, automated export | Phase 2 |
| **4** | SMS Automation | Carrier communication | Phase 3 |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Claude API cost overrun | Cost tracking from Phase 0, alerts at 80% budget |
| Extraction accuracy regression | CI gate on evaluation metrics |
| CD API changes | Abstract client, version headers, regression tests |
| Gate Pass missing | Non-blocking with visual indicator, manual override |
| Email format variations | Expand golden dataset, add failing cases |

---

## Success Metrics

| Metric | Phase 0 Baseline | Phase 3 Target |
|--------|------------------|----------------|
| Extraction accuracy (VIN) | TBD | ≥99% |
| Extraction accuracy (Address) | TBD | ≥95% |
| End-to-end latency | N/A | <60 seconds |
| Cost per document | N/A | <$0.05 |
| Export success rate | N/A | ≥98% |
| Manual intervention rate | 100% | <10% |

---

## Next Steps

1. **Review and approve** this implementation plan
2. **Create Golden Dataset** (Phase 0.1) — requires 30 sample documents
3. **Set up evaluation infrastructure** (Phase 0.2-0.4)
4. **Begin Phase 1** after baseline metrics established

---

*Document generated: 2026-02-11*
*Author: Claude Code Assistant*
