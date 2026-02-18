# Y7Dispatch Development Journal

> Complete history of all work done on the Y7Dispatch vehicle transport automation project.
> Auto-generated from git history and session context on 2026-02-16.

---

## Project Overview

**Y7Dispatch** automates the vehicle transport dispatcher workflow:
- **Input**: Auction documents (PDF invoices, gate passes, condition reports) from Copart, IAA, and Manheim
- **Process**: Layout-aware extraction → Review UI with evidence overlay → Export
- **Output**: Central Dispatch Listings API V2 payloads

**Tech Stack**: Python/FastAPI backend, React/Vite/Tailwind frontend, SQLite, Claude Haiku extraction

---

## Milestone 0: Project Foundation

### Initial Setup
| Commit | Description |
|--------|-------------|
| `62f67bc` | Initial commit |
| `8c3decd` | Add CLAUDE.md persistent context file |

### Core Architecture
| Commit | Description |
|--------|-------------|
| `0d7aaa8` | Architecture proposal for email→CD pipeline |
| `8d6b10f` | Implementation phases for Y7Dispatch automation pipeline |
| `1c65957` | Address 8 critical architecture issues in proposal |

---

## Milestone 1: Extraction Pipeline

### Phase 0: Foundation & Evaluation Harness
| Commit | Description |
|--------|-------------|
| `65c5e95` | Implement Foundation & Evaluation Harness |
| `3567286` | Register DLQ routes in main FastAPI app |

### Phase 1: HaikuExtractor + Block Extraction
| Commit | Description |
|--------|-------------|
| `e5006d1` | Implement HaikuExtractor for LLM-based document extraction |
| `5a97dcc` | Round 1 extraction complete — 23/23 documents success |
| `631bb19` | Add batch extraction test script for iterative model training |
| `d052258` | Unify lot_number/stock_number into vehicle_lot at extraction level |
| `5e110fe` | Implement hybrid pricing engine with CD Market Intelligence |

### Zone-Based Extraction
| Commit | Description |
|--------|-------------|
| `a82527e` | Implement zone-based extraction for 100% accuracy |
| `d9a7343` | Implement zone-based extraction (continued) |
| `9feca7b` | Fix warehouse import error, add Zone Templates to Test Lab |
| `9924c81` | Add visual zone editor with document background |

---

## Milestone 2: Central Dispatch Integration

### CD API V2 Models & Payload
| Commit | Description |
|--------|-------------|
| `34bbc6c` | Add Pydantic schemas and enums for CD Listings API v2 |
| `96c255e` | Add CD field matrix with gap analysis |
| `dee75c2` | Add CD payload preview + push endpoints |
| `1c5e4d6` | Use application/vnd.coxauto.v2+json for CD API headers |
| `c895297` | Add CD payload preview modal and API methods |
| `e416560` | Add sectioned CD listing form with inline editing |
| `91b07dc` | Add 59 unit tests for CD Listings API v2 Pydantic models |
| `905af4d` | E2E: CD listings API dry-run smoke test |
| `555f256` | CD API V2 requirements (Blocks 1-10) |
| `246728a` | Improve CD API payload builder for V2 requirements |

### Field Taxonomy & Registry
| Commit | Description |
|--------|-------------|
| `6cb40f2` | Implement field taxonomy with CD categories and source types |
| `c3b28d6` | Add Fields tab to Settings UI for field taxonomy visualization |
| `1cfea27` | Extraction pipeline uses field registry for review items |

### UI Development
| Commit | Description |
|--------|-------------|
| `e991ef3` | Fix Documents UI issues (Hybrid A+B implementation) |
| `3bfe5c1` | Simplify project — remove brokers, simplify warehouses and UI |
| `64537c5` | Decompose TestLab + add Documents pagination/sorting |
| `f72021e` | Add Market Intelligence pricing + fix PDF overlay coordinates |
| `2d08fa0` | Add zone visualization to Review & Correct page |
| `55133a5` | Add training feedback loop with learning visibility |
| `93fafe8` | Separate Training and Production modes in Review page |
| `54bd165` | Replace PDFViewer with PdfZoneViewer in Review page |

### Bug Fixes (M2)
| Commit | Description |
|--------|-------------|
| `ec08f84` | Improve Copart address extraction to filter buyer addresses |
| `84b80e1` | Improve Copart extractor for street address and MEMBER field |
| `03d7095` | Fix extraction endpoint crash, price display, warehouse selection |
| `eba2cfa` | Fix ZIP validation, location type auto-select, price editing |
| `83d4731` | Comprehensive UI and extraction fixes for CD API V2 |
| `5d226fc` | Resolve field key mismatch causing pickup_zip validation failure |
| `f3d1bb1` | Fix Documents navigation + VIN duplicate detection + Zone editing |
| `d57b631` | Fix preflight validation + zone extraction + warehouse display |
| `a780934` | Fix Test Lab training mode + zone preview + Export Preview fields |

---

## Milestone 3: Production Workflow

### Infrastructure
| Commit | Description |
|--------|-------------|
| `9eefec3` | PATCH-ТЗ: Fix Documents → Review → Export flow + Market Intelligence |
| `50d5ec3` | Improve UI field display and add prompt caching |
| `eec9853` | Add files via upload (golden test documents) |
| `bbfde6c` | Update CLAUDE.md with M3 progress |

### CI/CD & Testing
| Commit | Description |
|--------|-------------|
| `8924de0` | Fix SQLite test failures: initialize schema for tests |
| `10cea43` | Fix Ruff lint errors: remove unused imports |
| `e544955` | Fix ruff import ordering in tests/conftest.py |
| `434ceeb` | Fix test: initialize training DB in test fixtures |
| `6bb2b96` | Fix CI: replace black with ruff format, pin ruff==0.14.14 |
| `983757b` | Fix E2E: align Playwright webServer port with Vite config |
| `58fc5ad` | Fix E2E: use 127.0.0.1 instead of localhost to avoid IPv6 ECONNREFUSED |
| `8f3f7b3` | Clarify .gitignore — lockfiles are tracked for CI |
| `b6a3d94` | Update web/package-lock.json transitive deps |
| `70aaa7d` | Fix E2E: fix strict-mode h1 locators and API health assertions |
| `aa52a0b` | Fix E2E: align smoke test selectors with actual UI and fresh DB |
| `29c6a3a` | Fix E2E: use locator.or() instead of mixed CSS/text selectors |

### Pull Requests
| PR | Description |
|----|-------------|
| `#1` | Initial CLAUDE.md and project setup |
| `#2` | PATCH-ТЗ: Documents → Review → Export flow |
| `#3` | CI/CD fixes and test infrastructure |
| `#4` | Merge project structure |

---

## Week 3: CD-Aligned Review UI + Business Logic

### Directive v3.1: Dead Code Removal & Stabilization

**Day 1** — Dead code removal and consolidation
| Commit | Description |
|--------|-------------|
| `2224860` | Day 1 dead code removal — Directive v3.1 implementation |
| `b1a694b` | Day 1 dead code removal — sheets v2/v3 consolidated, clickup deleted |

**Day 2** — E2E pipeline tests
| Commit | Description |
|--------|-------------|
| `aaaed20` | Update Day 2 prompt with corrected test structure and timeline |
| `aae4bda` | Add E2E pipeline tests for Copart and IAA |

**Day 3** — Disable ML training endpoints + Manheim E2E
| Commit | Description |
|--------|-------------|
| `f505b58` | Disable ML training endpoints + Add Manheim E2E tests |
| `93d4e03` | Fix Manheim VIN extraction — handle YMMT: format with colon |
| `5a2148c` | Disable 10 ML training endpoints per directive v3.1 |
| `765f941` | Add E2E pipeline tests for Copart, IAA, Manheim |

### Week 3 Feature Development

**Day 7** — Market Intelligence + Alerting
| Commit | Description |
|--------|-------------|
| `466310c` | Implement PricingEngine with full formula, guardrails, and cache |
| `1abc666` | CD Market Intelligence integration + alerting service |
| `ecc0819` | Merge pricing_engine.py with remote version for API compatibility |

**Day 8** — Pricing route validation + Preflight UI
| Commit | Description |
|--------|-------------|
| `2dbae35` | Fix errors_json serialization + export jobs target key |
| `d22ec51` | Pricing route validation + preflight UI stabilization |
| `b515c70` | Recover lost E2E tests + add pricing/alerting E2E tests |
| `c0d04f8` | Remove hardcoded $450 default — block export when no price set |
| `440d10e` | Fix architecture gaps — SOT enforcement, DLQ alerting, webhook override |
| `9185942` | Switch primary extractor to HaikuExtractor — zone as fallback only |

**Day 9** — Settings + Pricing UI + Export Flow
| Commit | Description |
|--------|-------------|
| `6e644a4` | Settings page — credential management (IMAP, CD API, Sheets, Anthropic) |
| `042b2c3` | Pricing UI on Review page with market data visualization |
| `5cd5b9d` | Export flow UI — preflight check + preview modal + execution |
| `2949594` | Add .secret_key and .claude/ to .gitignore |
| `c2e4db2` | Fix DLQ service connection context manager usage |
| `72c6065` | Frontend cleanup — remove ClickUp dead code, fix duplicate key |
| `d6bfa34` | Fix credential persistence, extraction method display, HaikuExtractor wiring |

**Day 10** — Review Page Restructure + Load ID + Manheim Logic
| Commit | Description |
|--------|-------------|
| `e7d3ef3` | Review page restructure — CD-aligned 9-section layout, Load ID algorithm, Manheim release logic |
| `17606ff` | Fix export payload builder — wire Review UI overrides, correct defaults |

Key changes in Day 10:
- **Review.jsx restructured** from flat field list into 9 CD-aligned sections
- **9 new section components** created in `web/src/components/review/`:
  1. `ExtractionInfoBar.jsx` — doc name, auction badge, method, cost, confidence
  2. `VehicleSection.jsx` — VIN, YMMC, color, lot, type, inoperable, trailer
  3. `PickupSection.jsx` — name, address grid, phone, location type, buyer ref
  4. `DeliverySection.jsx` — warehouse dropdown → auto-fill delivery fields
  5. `DatesSection.jsx` — available date, expiration (+30d), desired delivery, Manheim release warning
  6. `PricingPaymentSection.jsx` — market intel, final price, COD/balance with payment terms
  7. `AdditionalInfoSection.jsx` — Load ID (auto-generated), gate pass, terms template, instructions
  8. `DocumentDetails.jsx` — collapsible internal fields (buyer/seller, sale price, raw JSON)
  9. `ExportActions.jsx` — preflight summary, export/save buttons
- **Load ID algorithm**: `M(no zero)DD + first3Make + first2Model + sequence` (e.g., `216TOYPR`)
- **`api/routes/listings.py`**: New endpoint `GET /api/listings/generate-load-id` with SQLite persistence
- **`services/haiku_extractor.py`**: Added `vehicle_is_inoperable`, `manheim_release_date`, `manheim_offsite` extraction
- **`api/listing_fields.py`**: Added field definitions for new fields

**Day 10 (Export Fix)** — Wire Review UI overrides to CD API payload
- **`api/routes/exports.py`**: Added `OperatorOverrides` Pydantic model, rewrote `build_cd_payload()` to accept and apply overrides
- Fixed 9 bugs: empty delivery stop, wrong price source (purchase vs carrier), COD defaults, Load ID as externalId, terms/notes/inspection missing, expiration +14→+30
- Added `POST /central-dispatch/preview/{run_id}` endpoint for override-aware preview
- **`web/src/api.js`**: Updated `exportToCD()` and `previewCDPayload()` to pass overrides
- **`web/src/components/ExportPreviewModal.jsx`**: Accepts and passes overrides prop
- **`web/src/pages/Review.jsx`**: Passes all state as overrides to ExportPreviewModal
- **36 tests** in `tests/e2e/test_review_ui_logic.py` covering Load ID, Manheim, templates, payment defaults

---

## Architecture & Design Decisions

### Field Resolution Precedence (CRITICAL)
```
1. USER_OVERRIDE    — Manual edits in Review UI (highest priority)
2. WAREHOUSE_CONST  — Warehouse constants (delivery addresses)
3. AUCTION_CONST    — Auction profile defaults
4. EXTRACTED        — Values from document extraction
5. DEFAULT          — Fallback defaults from cd_defaults.yaml
```

### Extraction Pipeline
```
PDF Document
  → Block Extractor (pdfplumber — text/table/spatial)
  → HaikuExtractor (Claude Haiku — LLM-based, primary)
  → Zone Extractor (coordinate-based, fallback)
  → OCR Strategy (pytesseract, for scanned docs)
  → Field Resolver (precedence-based merge)
  → Review Items (with evidence coordinates)
```

### Export Pipeline (Day 10 architecture)
```
Review UI State (React)
  → OperatorOverrides (Pydantic model)
  → build_cd_payload() (merges extraction + overrides + warehouse)
  → CD API V2 payload (stops[], vehicles[], price{})
  → POST /listings (Central Dispatch Marketplace API)
```

### Key Design Choices
- **Props-down pattern**: All state in Review.jsx, section components receive props (no React Context)
- **Native `<input type="date">`**: No date picker dependency for MVP
- **SQLite UNIQUE constraint** for Load ID dedup — leverages single-writer serialization
- **Prompt caching** (Phase 1.6): 90% cost reduction on Haiku extraction calls
- **OperatorOverrides model**: Frontend state → backend payload builder via typed Pydantic model

---

## Test Coverage

| Test File | Count | Coverage |
|-----------|-------|----------|
| `tests/e2e/test_copart_pipeline.py` | ~10 | Copart extraction E2E |
| `tests/e2e/test_iaa_pipeline.py` | ~10 | IAA extraction E2E |
| `tests/e2e/test_manheim_pipeline.py` | ~10 | Manheim extraction E2E |
| `tests/e2e/test_cd_export.py` | ~15 | CD payload builder + export |
| `tests/e2e/test_review_ui_logic.py` | 36 | Load ID, Manheim, terms, payment defaults |
| `tests/e2e/test_pricing_alerting.py` | ~10 | PricingEngine + alerts |
| `tests/test_cd_payload.py` | 59 | CD V2 Pydantic model validation |
| `tests/test_api_contracts.py` | ~20 | API endpoint contracts |
| `tests/e2e/test_warehouse_delivery.py` | 23 | Auction directory, warehouse schema, delivery integration |
| `tests/e2e/test_cd_payload_v2.py` | 26 | Marketplaces, tags, terms template, payment validation |

Total: ~220 tests (807 pass as of Day 12)

---

**Day 11** — Warehouse Delivery Integration + Auction Directory
| Commit | Description |
|--------|-------------|
| `8f9affd` | Auction directory (95+ locations), warehouse delivery integration, phone auto-fill |

Key changes in Day 11:
- **`services/auction_directory.py`**: 95+ auction locations (50+ Copart, 25+ IAA, 20+ Manheim) with normalized name lookup
- **`api/routes/auction_directory.py`**: `GET /api/auction-directory/lookup` endpoint for phone/address lookup
- **Warehouse schema enhanced**: Added `location_type` (BUSINESS/DEALERSHIP/RESIDENCE/AUCTION) and `contact_phone` to models, CRUD, and export payload
- **Export payload**: `location_type` now pulled from warehouse data (was hardcoded "BUSINESS")
- **PickupSection.jsx**: "Lookup" button auto-fills phone + address from auction directory
- **DeliverySection.jsx**: Shows `contact_phone` and `location_type` in warehouse readout
- **WarehousesTab.jsx**: Form includes contact_phone and location_type fields
- **23 tests** across 4 classes (TestAuctionDirectory, TestWarehouseSchema, TestDeliveryIntegration, TestPickupPhoneAutoFill)

**Day 12** — CD API V2 Payload Builder Enhancements
| Commit | Description |
|--------|-------------|
| `11c7efc` | CD V2 payload: marketplaces, tags, default terms template, ExportPreview update |

Key changes in Day 12:
- **Marketplaces array**: `marketplaces: [{marketplaceId: 10000, searchable: true}]` added to CD payload
- **Tags array**: Automation metadata for CD dashboard filtering: `automationVersion`, `sourceSystem`, `auctionSource`, `gatePass`, `warehouseId`
- **Default loadSpecificTerms**: Template auto-filled when no operator override: `"TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY). Pick-up location - {pickup_name}, Delivery - {warehouse_name}"`
- **ExportPreviewModal**: Shows Marketplaces and Tags sections in table view
- **26 tests** across 5 classes (TestMarketplacesArray, TestTagsArray, TestLoadSpecificTermsTemplate, TestPaymentMethodValidation, TestFullV2PayloadStructure)

---

## File Structure (Key Files)

```
y7dispatch/
├── api/
│   ├── main.py                    # FastAPI app, router registration
│   ├── routes/
│   │   ├── exports.py             # CD export + preview endpoints
│   │   ├── listings.py            # Load ID generation endpoint
│   │   ├── auction_directory.py   # Auction location lookup API (Day 11)
│   │   ├── warehouses.py          # Warehouse CRUD with location_type/contact_phone
│   │   ├── documents.py           # Document upload/management
│   │   ├── settings.py            # Settings + warehouse CRUD
│   │   └── metrics.py             # Extraction/pipeline metrics
│   ├── listing_fields.py          # Field registry with metadata
│   ├── database.py                # SQLite connection + migrations
│   └── cd_client.py               # Central Dispatch HTTP client
├── services/
│   ├── haiku_extractor.py         # Claude Haiku extraction (primary)
│   ├── orchestrator.py            # Pipeline orchestration
│   ├── cd_exporter.py             # Export business logic
│   ├── auction_directory.py       # Auction phone/address directory (Day 11)
│   └── warehouse.py               # Warehouse constants
├── extractors/
│   ├── block_extractor.py         # Layout-aware block extraction
│   ├── spatial_parser.py          # Coordinate-based field detection
│   ├── field_resolver.py          # Multi-source resolution
│   ├── copart.py, iaa.py, manheim.py  # Auction-specific
│   └── ocr_strategy.py            # OCR fallback
├── web/src/
│   ├── pages/
│   │   └── Review.jsx             # Main review page (9-section layout)
│   ├── components/
│   │   ├── review/                # 9 section components (Day 10)
│   │   └── ExportPreviewModal.jsx # Export preview with overrides
│   └── api.js                     # API client
├── tests/
│   └── e2e/                       # E2E test suite (~170 tests)
├── docs/                          # Documentation
├── cd_field_mapping.yaml          # Field mapping config
├── cd_defaults.yaml               # Default field values
├── warehouses.yaml                # Warehouse constants
└── CLAUDE.md                      # AI assistant context
```

---

*Updated: 2026-02-18 | Branch: claude/create-claude-md-OomNZ*
