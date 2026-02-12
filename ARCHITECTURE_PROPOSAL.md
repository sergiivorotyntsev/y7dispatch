# Y7Dispatch: Comprehensive System Architecture Proposal

> **Version**: 2.1 | **Date**: 2026-02-11
> **Domain**: dispatch.y7agency.com
> **Infrastructure**: DigitalOcean

---

## Critical Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Source of Truth** | Database (SQLite/PostgreSQL) | Single SOT avoids conflicts; Sheets API has rate limits |
| **Sheets Sync** | One-way (DB→Sheets) + webhook override | Polling is unreliable; Apps Script webhook is instant |
| **Golden Dataset Size** | 150 documents (50 per auction) | 10 docs = 10% error swing; 50 docs = 2% (statistically valid) |
| **RingCentral SMS** | PAUSED — separate scope | Orthogonal to core pipeline; dilutes focus |
| **Email Error Handling** | DLQ + deduplication + retry | Production requires no silent failures |
| **Backup Strategy** | DO Spaces every 6h | RPO=6h, RTO=1h, tested restore |
| **Claude Model** | claude-haiku-4-5-20251001 | Unified across all docs; verify current pricing |

---

## Executive Summary

This document outlines the complete architecture for the Y7Dispatch vehicle transport automation system. The proposal addresses:

1. **Email → Claude Haiku API → Document Extraction** pipeline
2. **Template Management System** with field status tracking
3. **Central Dispatch API V2** compliance and automation
4. **Database (SQLite/PostgreSQL)** as single source of truth, **Google Sheets** as read-only view + limited override input
5. **RingCentral Integration** for carrier communication automation
6. **Management UI** for control and monitoring
7. **DigitalOcean Deployment** strategy

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Proposed Architecture](#2-proposed-architecture)
3. [Central Dispatch API V2 Compliance](#3-central-dispatch-api-v2-compliance)
4. [Template Management System](#4-template-management-system)
5. [Claude Haiku Integration](#5-claude-haiku-integration)
6. [Google Sheets Integration](#6-google-sheets-integration)
7. [RingCentral Integration (Future)](#7-ringcentral-integration-future)
8. [Management UI Requirements](#8-management-ui-requirements)
9. [DigitalOcean Deployment](#9-digitalocean-deployment)
10. [Security Considerations](#10-security-considerations)
11. [Open Questions for Clarification](#11-open-questions-for-clarification)

---

## 1. Current State Analysis

### 1.1 Existing Capabilities

| Component | Status | Notes |
|-----------|--------|-------|
| Email Worker | ✅ Implemented | IMAP/OAuth2, PDF detection, rule-based filtering |
| PDF Extraction | ✅ Implemented | pdfplumber + pytesseract OCR fallback |
| Auction Extractors | ✅ Implemented | Copart, IAA, Manheim specific logic |
| Field Resolver | ✅ Implemented | 5-level precedence (USER > WAREHOUSE > AUCTION > EXTRACTED > DEFAULT) |
| Google Sheets V3 | ✅ Implemented | Full CD V2 schema, 90+ columns, upsert logic |
| CD Client | ✅ Implemented | ETag, retry, idempotency, rate limiting |
| Training/Learning | ✅ Implemented | Learns from user corrections |
| Review UI | ⚠️ Partial | Needs field mapping fixes |

### 1.2 Gaps Identified

| Gap | Impact | Priority |
|-----|--------|----------|
| No Claude Haiku for intelligent extraction | Limited to rule-based parsing | HIGH |
| Gate Pass extraction from email body | Missing structured extraction | HIGH |
| Template versioning/management UI | Manual YAML edits only | MEDIUM |
| Field status tracking (draft/validated/locked) | No workflow visibility | MEDIUM |
| RingCentral integration | No carrier auto-response | LOW (Phase 2) |
| Market Intelligence API pricing | Hardcoded prices only | MEDIUM |

---

## 2. Proposed Architecture

### 2.1 High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              EMAIL INBOX                                      │
│                    (dispatch@y7agency.com via IMAP/OAuth2)                   │
└─────────────────────────┬───────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EMAIL PROCESSOR                                       │
│  1. Parse email headers (from, subject, date)                                │
│  2. Extract Gate Pass PIN from email body (Claude Haiku)                     │
│  3. Detect PDF attachments                                                   │
│  4. Apply routing rules                                                      │
└─────────────────────────┬───────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CLAUDE HAIKU EXTRACTION SERVICE                           │
│                                                                              │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐      │
│  │   EMAIL BODY     │    │   PDF DOCUMENT   │    │  TEMPLATE MGMT   │      │
│  │   EXTRACTION     │    │   EXTRACTION     │    │    SERVICE       │      │
│  │                  │    │                  │    │                  │      │
│  │  • Gate Pass PIN │    │  • VIN           │    │  • Field schemas │      │
│  │  • Lot Number    │    │  • Vehicle info  │    │  • Extraction    │      │
│  │  • Pickup date   │    │  • Pickup addr   │    │    prompts       │      │
│  │  • Instructions  │    │  • Lot/Stock #   │    │  • Validation    │      │
│  └────────┬─────────┘    └────────┬─────────┘    │    rules         │      │
│           │                       │              └────────┬─────────┘      │
│           └───────────┬───────────┘                       │                │
│                       │                                   │                │
│                       ▼                                   │                │
│           ┌───────────────────────┐                       │                │
│           │   FIELD RESOLVER      │◄──────────────────────┘                │
│           │   (5-Level Precedence)│                                        │
│           └───────────┬───────────┘                                        │
└───────────────────────┼────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      DATABASE (Single Source of Truth)                       │
│                          SQLite / PostgreSQL                                 │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  Row: dispatch_id | row_status | vehicle_* | pickup_* | dropoff_* │    │
│  │       gate_pass  | extraction_score | cd_listing_id | ...         │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                    │                                        │
│                                    ▼                                        │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │            GOOGLE SHEETS (Read-Only View + Override Input)         │    │
│  │  • DB → Sheets: Full data sync (one-way display)                  │    │
│  │  • Sheets → DB: Override columns only via Apps Script webhook     │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────┬───────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CENTRAL DISPATCH API V2                                   │
│                                                                              │
│  POST /listings → Create listing                                            │
│  PUT  /listings/{id} → Update (with ETag)                                   │
│  GET  /market-intelligence/price → Get pricing                              │
└─────────────────────────┬───────────────────────────────────────────────────┘
                          │
                          ▼ (Phase 2)
┌─────────────────────────────────────────────────────────────────────────────┐
│                    RINGCENTRAL INTEGRATION                                   │
│                                                                              │
│  Webhooks: SMS received → Process carrier inquiry                           │
│  Actions:  Auto-respond with listing details, ETA, pricing                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Component Architecture

```
dispatch.y7agency.com
│
├── /api/                          # FastAPI Backend
│   ├── routes/
│   │   ├── documents.py           # Document upload/processing
│   │   ├── extractions.py         # Extraction runs
│   │   ├── exports.py             # CD export
│   │   ├── templates.py           # Template management [NEW]
│   │   ├── fields.py              # Field status/mapping [NEW]
│   │   ├── haiku.py               # Claude Haiku service [NEW]
│   │   └── integrations/
│   │       ├── email.py           # Email processing
│   │       ├── sheets.py          # Google Sheets
│   │       ├── cd.py              # Central Dispatch
│   │       └── ringcentral.py     # RingCentral [Phase 2]
│   │
│   ├── services/
│   │   ├── haiku_extractor.py     # Claude Haiku extraction [NEW]
│   │   ├── template_service.py    # Template management [NEW]
│   │   ├── field_status_service.py # Field lifecycle [NEW]
│   │   └── ...
│   │
│   └── workers/
│       ├── email_worker.py        # Email polling
│       ├── export_worker.py       # CD export queue
│       └── sync_worker.py         # Sheets sync [NEW]
│
├── /web/                          # React Frontend
│   ├── pages/
│   │   ├── Dashboard.tsx          # Overview metrics
│   │   ├── Documents.tsx          # Document list
│   │   ├── Review.tsx             # Field review/edit
│   │   ├── Templates.tsx          # Template management [NEW]
│   │   ├── Fields.tsx             # Field configuration [NEW]
│   │   └── Settings.tsx           # System settings
│   │
│   └── components/
│       ├── FieldEditor.tsx        # Field value + status
│       ├── TemplateBuilder.tsx    # Visual template config
│       └── ...
│
└── /config/
    ├── cd_field_mapping_v2.yaml   # CD field definitions
    ├── templates/                 # [NEW] Template definitions
    │   ├── copart_v1.yaml
    │   ├── iaa_v1.yaml
    │   └── manheim_v1.yaml
    └── prompts/                   # [NEW] Claude Haiku prompts
        ├── email_extraction.txt
        └── document_extraction.txt
```

---

## 3. Central Dispatch API V2 Compliance

### 3.1 Required Fields (Blocking)

Based on the [CD Listings API V2 documentation](https://api-docs.centraldispatch.com/apis/listings-api-v2-2-0-0/):

| Field | CD Path | Validation | Source |
|-------|---------|------------|--------|
| externalId | `externalId` | ≤50 chars, unique | Generated (dispatch_id) |
| trailerType | `trailerType` | OPEN\|ENCLOSED\|DRIVEAWAY | Default OPEN, auto ENCLOSED for luxury |
| availableDate | `availableDate` | Today..+30 days, ISO 8601 | Today + offset |
| expirationDate | `expirationDate` | > availableDate, ≤30 days | availableDate + 14 |
| **stops[0]** | | | |
| stopNumber | `stops[0].stopNumber` | = 1 | Constant |
| city | `stops[0].city` | Required | Extracted from PDF |
| state | `stops[0].state` | 2-letter code | Extracted |
| postalCode | `stops[0].postalCode` | 5 or 9 digits | Extracted |
| **stops[1]** | | | |
| stopNumber | `stops[1].stopNumber` | = 2 | Constant |
| city | `stops[1].city` | Required | From warehouse constants |
| state | `stops[1].state` | 2-letter code | From warehouse |
| postalCode | `stops[1].postalCode` | Required | From warehouse |
| **vehicles[0]** | | | |
| vin | `vehicles[0].vin` | 17 chars, no I/O/Q | Extracted |
| year | `vehicles[0].year` | 1900-2030, auto-decoded | VIN decode or extracted |
| make | `vehicles[0].make` | Required, auto-decoded | VIN decode or extracted |
| model | `vehicles[0].model` | Required, auto-decoded | VIN decode or extracted |
| vehicleType | `vehicles[0].vehicleType` | Required, auto-decoded | VIN decode |
| pickupStopNumber | `vehicles[0].pickupStopNumber` | = 1 | Constant |
| dropoffStopNumber | `vehicles[0].dropoffStopNumber` | = 2 | Constant |
| **price** | | | |
| total | `price.total` | > 0 | Market Intelligence or manual |
| cod.amount | `price.cod.amount` | Required | = total or split |
| cod.paymentMethod | `price.cod.paymentMethod` | Required | CASH_CERTIFIED_FUNDS default |
| **marketplaces[0]** | | | |
| marketplaceId | `marketplaces[0].marketplaceId` | Integer | 10000 (public) |

### 3.2 API Integration Requirements

```python
# Headers required for V2
headers = {
    "Content-Type": "application/vnd.coxauto.v2+json",
    "Authorization": "Bearer {access_token}",
    "If-Match": "{etag}"  # For updates only
}

# Rate limiting
MAX_CONCURRENT_REQUESTS = 5
RETRY_BACKOFF = [2, 4, 8]  # seconds

# Idempotency
idempotency_key = f"{dispatch_id}:{timestamp}"
```

### 3.3 Market Intelligence API (Pricing)

```
GET /market-intelligence/price
Query params:
  - originCity, originState, originPostalCode
  - destinationCity, destinationState, destinationPostalCode
  - vehicleType, isOperable, trailerType

Response:
{
  "lowPrice": 450.00,
  "averagePrice": 525.00,
  "highPrice": 600.00,
  "confidence": 0.85
}
```

**Recommendation**: Use `averagePrice` as default, allow override in UI.

---

## 4. Template Management System

### 4.1 Template Structure

```yaml
# templates/copart_v1.yaml
template:
  id: "copart_v1"
  name: "Copart Sales Receipt"
  version: 1
  auction_type: "COPART"
  description: "Standard Copart auction PDF extraction"

  # Field definitions with extraction rules
  fields:
    - name: "vehicle_vin"
      cd_field: "vehicles[0].vin"
      required: true
      extraction:
        type: "regex"
        patterns:
          - "VIN[:\\s]*([A-HJ-NPR-Z0-9]{17})"
          - "Vehicle Identification[:\\s]*([A-HJ-NPR-Z0-9]{17})"
      validation:
        type: "vin"
        message: "VIN must be 17 characters, no I/O/Q"
      status_flow: ["draft", "extracted", "validated", "locked"]

    - name: "vehicle_lot_number"
      cd_field: "vehicles[0].lotNumber"
      required: true
      extraction:
        type: "label_below"
        labels: ["LOT #", "LOT NUMBER", "STOCK #"]
      validation:
        type: "regex"
        pattern: "^\\d{6,10}$"

    - name: "gate_pass"
      source: "email_body"  # Special: extracted from email, not PDF
      extraction:
        type: "claude_haiku"
        prompt: "Extract the Gate Pass PIN code from this email"
      required: true

    - name: "pickup_address"
      cd_field: "stops[0].address"
      extraction:
        type: "spatial_block"
        section: "PICKUP_LOCATION"

  # Templates for generated text
  transportation_release_notes: |
    LOT#: {vehicle_lot_number}
    Gate Pass: {gate_pass}

    COPART lot pickup. Present LOT# and Gate Pass at gate.
    Driver must verify vehicle condition before loading.
```

### 4.2 Field Status Lifecycle

```
┌─────────┐     ┌───────────┐     ┌────────────┐     ┌────────┐
│  DRAFT  │────▶│ EXTRACTED │────▶│ VALIDATED  │────▶│ LOCKED │
└─────────┘     └───────────┘     └────────────┘     └────────┘
     │                │                  │                │
     │                │                  │                │
     ▼                ▼                  ▼                ▼
  User can         System            User review       No changes
  edit freely      extracted         approved          allowed
                   value             value
```

### 4.3 Template Management UI Features

1. **Template List View**
   - Filter by auction type
   - Version history
   - Active/inactive toggle
   - Clone template

2. **Template Editor**
   - Visual field builder
   - Extraction rule configuration
   - Validation rule configuration
   - Test against sample PDFs
   - Preview generated output

3. **Field Mapping View**
   - CD field ↔ Template field mapping
   - Required/optional indicators
   - Validation status per field
   - Override capability

---

## 5. Claude Haiku Integration

### 5.1 Service Architecture

```python
# services/haiku_extractor.py

class HaikuExtractor:
    """
    Claude Haiku-based intelligent extraction service.

    Pricing (2026) — VERIFY CURRENT RATES:
    - Check https://www.anthropic.com/pricing for latest
    - Haiku 4.5 pricing may differ from 3.5
    - With batch API: 50% discount typically available

    Estimated cost per document: ~$0.01-0.05
    """

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-haiku-4-5-20251001"  # Haiku 4.5

    async def extract_from_email_body(
        self,
        email_body: str,
        template: Template
    ) -> dict[str, ExtractedField]:
        """Extract structured data from email body."""

        prompt = self._build_email_prompt(email_body, template)

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        return self._parse_response(response, template)

    async def extract_from_pdf(
        self,
        pdf_text: str,
        pdf_blocks: list[LayoutBlock],
        template: Template
    ) -> dict[str, ExtractedField]:
        """Extract structured data from PDF content."""

        prompt = self._build_pdf_prompt(pdf_text, pdf_blocks, template)

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )

        return self._parse_response(response, template)
```

### 5.2 Extraction Prompts

```
# prompts/email_extraction.txt

You are extracting structured data from vehicle transport emails.

Email content:
---
{email_body}
---

Extract the following fields in JSON format:
{field_definitions}

Rules:
1. Gate Pass PIN is typically a 4-8 character alphanumeric code
2. Lot numbers are typically 6-10 digit numbers
3. Pickup dates should be in YYYY-MM-DD format
4. If a field is not found, return null

Return ONLY valid JSON, no explanation:
{
  "gate_pass": "...",
  "lot_number": "...",
  "pickup_date": "...",
  "special_instructions": "..."
}
```

### 5.3 Cost Optimization

| Strategy | Savings | Implementation |
|----------|---------|----------------|
| Batch API | 50% | Queue non-urgent extractions |
| Prompt Caching | 90% | Cache template prompts |
| Field-level extraction | Variable | Only extract missing fields |
| Hybrid approach | ~70% | Use regex first, Haiku for ambiguous |

**Recommended approach**: Hybrid extraction
1. Run regex/rule-based extraction first (free)
2. Calculate confidence score per field
3. Send low-confidence fields (< 0.8) to Claude Haiku
4. Use Claude Haiku for email body extraction (always)

### 5.4 Email Pipeline Error Handling (CRITICAL)

Production reliability requires robust error handling for the email pipeline:

#### 5.4.1 Failure Scenarios

| Scenario | Detection | Action |
|----------|-----------|--------|
| Corrupted PDF | pdfplumber exception | Move to DLQ, alert, create MANUAL_REVIEW row |
| Email without attachment | No PDF detected | Log warning, skip (not an error) |
| Duplicate email | Hash match in DB | Skip silently, log for audit |
| Unknown auction format | No template match | Create row with status=MANUAL_REVIEW |
| Claude API failure | API exception/timeout | Retry with backoff, then DLQ |
| Extraction below threshold | Confidence < 0.5 | Flag for review, don't auto-export |

#### 5.4.2 Dead Letter Queue (DLQ)

```python
# models/dlq.py

class DeadLetterEntry(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid4()))
    email_id: str
    email_subject: str
    failure_reason: str  # CORRUPTED_PDF | EXTRACTION_FAILED | API_ERROR | UNKNOWN_FORMAT
    failure_details: str  # Stack trace or error message
    attachment_hash: Optional[str]
    created_at: datetime
    retry_count: int = 0
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None  # User who manually resolved
```

#### 5.4.3 Deduplication Strategy

```python
# Deduplication hash = SHA256(email_message_id + attachment_sha256)
def get_dedup_hash(email: Email, attachment: bytes) -> str:
    content = f"{email.message_id}:{hashlib.sha256(attachment).hexdigest()}"
    return hashlib.sha256(content.encode()).hexdigest()

# Check before processing
if await db.exists(DocumentHash, hash=dedup_hash):
    logger.info(f"Duplicate detected: {email.subject}")
    return  # Skip silently
```

#### 5.4.4 Retry Strategy

```python
# Email processing retry with exponential backoff
RETRY_CONFIG = {
    "max_attempts": 3,
    "base_delay": 5,  # seconds
    "max_delay": 60,
    "exponential_base": 2
}

# After max retries: move to DLQ with failure_reason
```

#### 5.4.5 Alerting

| Event | Channel | Urgency |
|-------|---------|---------|
| DLQ entry created | Email + Slack | Medium |
| DLQ > 5 unresolved entries | Email + SMS | High |
| Extraction success rate < 80% (1h window) | Slack | Medium |
| Claude API errors > 10/hour | Email + Slack | High |

---

## 6. Google Sheets Integration

### 6.1 Architecture: Database as Single Source of Truth

**CRITICAL**: The database (SQLite/PostgreSQL) is the **single source of truth**. Google Sheets is:
- **Read-only view** for data display and filtering
- **Limited input layer** for override columns only (via Apps Script webhook, NOT polling)

This architecture avoids:
- Two sources of truth causing data conflicts
- Google Sheets API rate limits (~60 req/min)
- Risk of users accidentally breaking sheet structure

### 6.2 Current Schema (V3)

The existing `sheets_schema_v3.py` is well-designed and matches CD API V2:

- **90+ columns** organized by category
- **Column classes**: PK, SYSTEM, AUDIT, LOCK, BASE, OVERRIDE
- **Row status state machine**: NEW → READY → EXPORTED
- **Override pattern**: `override_{field}` takes precedence

### 6.3 Sync Strategy

```
┌─────────────────┐                              ┌─────────────────┐
│   SQLite DB     │                              │  Google Sheets  │
│  (Single SOT)   │                              │  (View + Input) │
└────────┬────────┘                              └────────┬────────┘
         │                                                │
         │  ┌────────────────────────────────────────┐   │
         │  │           SYNC DIRECTION               │   │
         │  │                                        │   │
         ├──┼──▶ DB → Sheets: ALL data (one-way)    │   │
         │  │    • Full row sync every N minutes    │   │
         │  │    • Triggered on document ingestion  │   │
         │  │                                        │   │
         │  │    Sheets → DB: OVERRIDE columns ONLY │◀──┤
         │  │    • Via Apps Script onEdit webhook   │   │
         │  │    • NOT via polling (no rate limits) │   │
         │  │    • Immediate, per-cell changes      │   │
         │  └────────────────────────────────────────┘   │
         │                                                │
         ▼                                                ▼
```

**Sync rules**:
1. **DB → Sheets**: Full data sync (one-way, display only)
2. **Sheets → DB**: Override columns ONLY via Apps Script `onEdit` webhook
3. **No polling**: Apps Script triggers POST to `/api/sheets/override` on edit
4. **Lock respect**: Never overwrite locked fields
5. **Reconciliation**: Background job every 5 min to catch any missed webhooks

### 6.3 Export Features

| Feature | Status | Notes |
|---------|--------|-------|
| Create row on ingestion | ✅ | With all extracted fields |
| Update existing row | ✅ | Respects locks and overrides |
| Non-destructive upsert | ✅ | Fill-only mode available |
| Status updates | ✅ | State machine enforced |
| CD export tracking | ✅ | cd_listing_id, cd_exported_at |

---

## 7. RingCentral Integration (PAUSED — Future Scope)

> **Status**: PAUSED — This feature is orthogonal to the core email→extraction→CD pipeline.
> **Rationale**: Carrier communication via SMS is a separate product with different requirements.
> Focus first on Phases 0-3 (core extraction and export pipeline).
> **Future path**: RingCentral bot can have read-only access to loads database when ready.

### 7.1 Architecture Overview (For Future Reference)

```
┌─────────────────────────────────────────────────────────────────┐
│                     RINGCENTRAL PLATFORM                         │
│                                                                  │
│  SMS Webhook ────────────────────────────────────────────────▶  │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   Y7 DISPATCH API                        │   │
│  │                                                          │   │
│  │  POST /api/webhooks/ringcentral/sms                     │   │
│  │       │                                                  │   │
│  │       ▼                                                  │   │
│  │  ┌─────────────────┐    ┌─────────────────────────────┐ │   │
│  │  │ Message Router  │───▶│ Claude Haiku Intent Parser  │ │   │
│  │  └─────────────────┘    └─────────────────────────────┘ │   │
│  │                                    │                     │   │
│  │       ┌────────────────────────────┼─────────────────┐  │   │
│  │       ▼                            ▼                 ▼  │   │
│  │  ┌─────────┐    ┌─────────────┐    ┌────────────────┐  │   │
│  │  │ PRICING │    │ AVAILABILITY│    │ BOOKING STATUS │  │   │
│  │  │ INQUIRY │    │   CHECK     │    │    INQUIRY     │  │   │
│  │  └────┬────┘    └──────┬──────┘    └───────┬────────┘  │   │
│  │       │                │                    │           │   │
│  │       └────────────────┴────────────────────┘           │   │
│  │                        │                                │   │
│  │                        ▼                                │   │
│  │               ┌─────────────────┐                       │   │
│  │               │ Response Builder │                       │   │
│  │               └────────┬────────┘                       │   │
│  │                        │                                │   │
│  └────────────────────────┼────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│                    SMS Send API                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Use Cases

| Intent | Example Message | Auto-Response |
|--------|-----------------|---------------|
| Price inquiry | "What's the price for NJ to CA?" | "Based on our routes: $550-650 for standard auto. Reply YES to book." |
| Availability | "Do you have any loads from TX?" | "3 vehicles available from TX: [list]. Reply with LOT# for details." |
| Status check | "Status on LOT 12345678?" | "LOT 12345678: Pickup scheduled 02/15. Driver ETA 2pm." |
| Book confirmation | "YES to 12345678" | "Confirmed! Dispatch sheet sent to your email. Driver: John D, (555) 123-4567" |

### 7.3 Implementation Requirements

```python
# Webhook handler
@router.post("/webhooks/ringcentral/sms")
async def handle_sms_webhook(payload: RingSMSWebhook):
    # 1. Parse incoming message
    sender = payload.from_number
    message = payload.body

    # 2. Identify carrier (from contact database)
    carrier = await get_carrier_by_phone(sender)

    # 3. Parse intent with Claude
    intent = await claude_parse_intent(message)

    # 4. Generate response
    response = await generate_carrier_response(intent, carrier)

    # 5. Send via RingCentral API
    await ringcentral_send_sms(sender, response)
```

### 7.4 RingCentral API Setup

Based on [RingCentral Developer Docs](https://developers.ringcentral.com/guide/notifications/webhooks/quick-start):

1. **Create RingCentral App** → Get client_id, client_secret
2. **Configure Webhook URL**: `https://dispatch.y7agency.com/api/webhooks/ringcentral/sms`
3. **Subscribe to events**: SMS received, Call received
4. **Webhook verification**: Return `Validation-Token` header

---

## 8. Management UI Requirements

### 8.1 Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│  Y7 DISPATCH CONTROL PANEL           dispatch.y7agency.com      │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  TODAY'S METRICS                                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │    12    │  │     8    │  │     3    │  │     1    │        │
│  │ Received │  │ Exported │  │ Pending  │  │  Errors  │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│                                                                  │
│  RECENT ACTIVITY                                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 10:32  Email received: Copart - 2024 Toyota Camry       │   │
│  │ 10:33  Extraction complete: 95% confidence              │   │
│  │ 10:35  Exported to CD: Listing #CD-2026-0211-A3B4      │   │
│  │ 10:40  Carrier inquiry via SMS: +1 (555) 123-4567       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  QUICK ACTIONS                                                  │
│  [+ Upload Document]  [Sync Sheets]  [Test Connections]        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Template Management Page

```
┌─────────────────────────────────────────────────────────────────┐
│  TEMPLATES                                    [+ New Template]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ COPART_V1           Active    v1.2    12 fields         │   │
│  │ Last updated: 2026-02-10     Usage: 156 documents       │   │
│  │ [Edit] [Clone] [Test] [Deactivate]                      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ IAA_V1               Active    v1.0    11 fields         │   │
│  │ Last updated: 2026-02-08     Usage: 89 documents        │   │
│  │ [Edit] [Clone] [Test] [Deactivate]                      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ MANHEIM_V1           Active    v1.1    13 fields         │   │
│  │ Last updated: 2026-02-05     Usage: 45 documents        │   │
│  │ [Edit] [Clone] [Test] [Deactivate]                      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.3 Field Configuration Page

```
┌─────────────────────────────────────────────────────────────────┐
│  FIELD MAPPINGS                              [Export YAML]       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  CD REQUIRED FIELDS                                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ vehicles[0].vin                                         │   │
│  │   Source: vehicle_vin  │  Status: VALIDATED             │   │
│  │   Extraction: regex    │  Validation: VIN format        │   │
│  │   [Configure] [Test]                                    │   │
│  ├─────────────────────────────────────────────────────────┤   │
│  │ stops[0].city                                           │   │
│  │   Source: pickup_city  │  Status: EXTRACTED             │   │
│  │   Extraction: spatial  │  Validation: required          │   │
│  │   [Configure] [Test]                                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  CD OPTIONAL FIELDS                                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ vehicles[0].color                                       │   │
│  │   Source: vehicle_color │  Status: DRAFT                │   │
│  │   [Configure] [Test]                                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. DigitalOcean Deployment

### 9.1 Infrastructure Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     DIGITALOCEAN                                 │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    App Platform                          │   │
│  │                                                          │   │
│  │  ┌──────────────┐   ┌──────────────┐   ┌────────────┐  │   │
│  │  │   Web App    │   │   API App    │   │   Worker   │  │   │
│  │  │   (React)    │   │  (FastAPI)   │   │   (Celery) │  │   │
│  │  │   Static     │   │   2 dynos    │   │   1 dyno   │  │   │
│  │  └──────┬───────┘   └──────┬───────┘   └─────┬──────┘  │   │
│  │         │                  │                  │         │   │
│  │         └──────────────────┼──────────────────┘         │   │
│  │                            │                            │   │
│  │                            ▼                            │   │
│  │  ┌─────────────────────────────────────────────────┐   │   │
│  │  │              Managed Database                    │   │   │
│  │  │              PostgreSQL (or SQLite on Volume)    │   │   │
│  │  └─────────────────────────────────────────────────┘   │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────────────────┐   │   │
│  │  │              Spaces (S3-compatible)              │   │   │
│  │  │              PDF Storage, Backups                │   │   │
│  │  └─────────────────────────────────────────────────┘   │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  DNS: dispatch.y7agency.com → App Platform                      │
│  SSL: Managed by DigitalOcean                                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 Recommended Configuration

| Component | Size | Cost/month | Notes |
|-----------|------|------------|-------|
| **App Platform - API** | Basic (2 dynos) | $24 | FastAPI + Uvicorn |
| **App Platform - Worker** | Basic (1 dyno) | $12 | Email/export workers |
| **App Platform - Static** | Free | $0 | React frontend |
| **Managed PostgreSQL** | Basic (1GB) | $15 | Or use SQLite on Volume |
| **Spaces (10GB)** | Standard | $5 | PDF storage |
| **Domain** | Existing | $0 | dispatch.y7agency.com |
| **Total** | | **~$56/month** | |

### 9.3 Deployment Configuration

```yaml
# .do/app.yaml
name: y7dispatch
region: nyc
domains:
  - domain: dispatch.y7agency.com
    type: PRIMARY

services:
  - name: api
    github:
      repo: your-org/y7dispatch
      branch: main
      deploy_on_push: true
    source_dir: /
    dockerfile_path: Dockerfile.api
    instance_size_slug: basic-xxs
    instance_count: 2
    http_port: 8000
    routes:
      - path: /api
    envs:
      - key: DATABASE_URL
        scope: RUN_TIME
        value: ${db.DATABASE_URL}
      - key: ANTHROPIC_API_KEY
        scope: RUN_TIME
        type: SECRET
      - key: CD_API_KEY
        scope: RUN_TIME
        type: SECRET
      - key: GOOGLE_CREDENTIALS
        scope: RUN_TIME
        type: SECRET

  - name: web
    github:
      repo: your-org/y7dispatch
      branch: main
    source_dir: /web
    build_command: npm run build
    environment_slug: node-js
    routes:
      - path: /

workers:
  - name: email-worker
    github:
      repo: your-org/y7dispatch
      branch: main
    dockerfile_path: Dockerfile.worker
    instance_size_slug: basic-xxs
    instance_count: 1
    envs:
      - key: DATABASE_URL
        scope: RUN_TIME
        value: ${db.DATABASE_URL}

databases:
  - name: db
    engine: PG
    version: "15"
    size: db-s-1vcpu-1gb
    num_nodes: 1
```

### 9.4 CI/CD Pipeline

```yaml
# .github/workflows/deploy.yml
name: Deploy to DigitalOcean

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: |
          pip install -e ".[dev]"
          pytest tests/ -v
          cd web && npm test

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to App Platform
        uses: digitalocean/app_action@v1
        with:
          app_name: y7dispatch
          token: ${{ secrets.DIGITALOCEAN_TOKEN }}
```

---

## 10. Security Considerations

### 10.1 API Key Management

| Key | Storage | Rotation |
|-----|---------|----------|
| Anthropic (Claude) | DO Secrets | 90 days |
| Central Dispatch | DO Secrets | 90 days |
| Google Sheets | DO Secrets (JSON) | On-demand |
| RingCentral | DO Secrets | 90 days |
| IMAP Password | DO Secrets | On-demand |

### 10.2 Data Protection

- **PII in PDFs**: VINs, addresses stored in DB
- **Encryption at rest**: DigitalOcean default encryption
- **HTTPS**: Enforced via App Platform
- **Access logs**: Retained 30 days

### 10.3 Audit Trail

All operations logged:
- Document uploads/processing
- Field edits with user attribution
- CD export attempts/results
- Email processing activity

---

## 11. Open Questions for Clarification

### ⚠️ BLOCKING: Must Resolve Before Phase 1

These questions MUST be answered before starting implementation:

### 11.1 Business Logic (BLOCKING)

1. **Pricing Strategy** ⚠️ BLOCKING:
   - Who sets the final price? System auto? User always reviews? Hybrid?
   - If auto: What's the formula? `averagePrice` from CD MI API? With markup?
   - Floor/ceiling limits? (e.g., never below $200, never above $2000?)
   - Fallback if CD Market Intelligence unavailable?

   **Decision required**: Define exact pricing algorithm before Phase 1 coding.

   ```
   Example pricing algorithm (needs approval):
   1. Fetch CD Market Intelligence averagePrice
   2. Apply 5% markup for margin
   3. Round to nearest $25
   4. Floor: $250, Ceiling: $3000
   5. Fallback: Use auction profile default + distance calculation
   6. Final price: ALWAYS require user confirmation before CD export
   ```

2. **Warehouse Selection**:
   - Current: Manual selection or auto-nearest
   - Should auto-routing consider capacity, costs, transit time?

3. **Gate Pass Handling**:
   - What if Gate Pass is missing from email?
   - Should we block export or use placeholder?
   - **Current decision**: Flag as NEEDS_REVIEW, don't block export

### 11.2 Integration Priorities

4. **RingCentral Scope**:
   - SMS only, or voice calls too?
   - Auto-response always, or during business hours only?
   - Carrier verification before responding?

5. **Google Sheets**:
   - Single sheet or multiple tabs (by auction type)?
   - Who has edit access? Need row-level locking?
   - Real-time sync or batch (every N minutes)?

### 11.3 Technical Decisions

6. **Database**:
   - Keep SQLite (simpler) or migrate to PostgreSQL (scalable)?
   - Current data volume and expected growth?

7. **Claude Haiku Usage**:
   - All documents or only when rule-based fails?
   - Budget limit per month?

8. **Monitoring**:
   - Email/SMS alerts on failures?
   - Integration with external monitoring (DataDog, etc.)?

---

## Next Steps

1. **Review this proposal** and provide answers to open questions
2. **Prioritize features** for Phase 1 implementation
3. **Set up DigitalOcean** App Platform and domain
4. **Implement Claude Haiku** email/PDF extraction
5. **Build Template Management UI**
6. **Integrate Market Intelligence API** for pricing
7. **Phase 2**: RingCentral automation

---

## Sources

- [Central Dispatch API Developer Portal](https://api-docs.centraldispatch.com/)
- [Central Dispatch Listings API V2](https://api-docs.centraldispatch.com/apis/listings-api-v2-2-0-0/)
- [RingCentral Webhook Notifications](https://developers.ringcentral.com/guide/notifications/webhooks/quick-start)
- [RingCentral SMS Guide](https://developers.ringcentral.com/guide/messaging)
- [Claude API Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Anthropic Claude API Documentation](https://docs.anthropic.com/)
- [DigitalOcean App Platform](https://docs.digitalocean.com/products/app-platform/)

---

*Document generated: 2026-02-11*
*Author: Claude Code Assistant*
