# Y7Dispatch - Full Application Audit
**Generated:** 2026-02-24T21:04:30.861664
**Branch:** claude/create-claude-md-OomNZ
**Last commit:** 5016de2f test: Day 15 comprehensive E2E suite â€” 69 tests across 16 classes

## Part 1: Project Structure & Size

| Area | Lines | Files |
|------|-------|-------|
| Python Backend (api/, services/) | ~39,942 | 70 |
| Python Tests | ~23,535 | 53 |
| Frontend (JSX/JS) | ~12,960 | 41 |
| **Total** | **~76,437** | **164** |

### Largest Files (complexity hotspots)
| File | Lines |
|------|-------|
| api/routes/extractions.py | 2781 |
| api/routes/exports.py | 2695 |
| api/models.py | 2392 |
| api/workers/email_worker.py | 2159 |
| api/listing_fields.py | 1962 |
| web/src/pages/Documents.jsx | 1740 |
| api/routes/documents.py | 1543 |
| web/src/pages/TestLab.jsx | 1303 |
| web/src/pages/Review.jsx | 1183 |
| services/distance_service.py | 1113 |

## Part 2: Database Schema (34 tables)

- **auction_profiles** (3 rows, 10 cols): id, auction_type_id, auction_code, name, description, profile_json, version, is_active...
- **auction_types** (4 rows, 11 cols): id, name, code, parent_id, is_base, is_custom, is_active, description...
- **audit_events** (25 rows, 15 cols): id, event_type, entity_type, entity_id, run_id, document_id, request_id, payload_hash...
- **brokers** (2 rows, 6 cols): id, code, name, is_active, created_at, updated_at
- **cd_listings** (9 rows, 8 cols): id, run_id, cd_listing_id, etag, external_id, sandbox, created_at, updated_at
- **config_snapshots** (0 rows, 5 cols): id, created_at, config_type, config_data, description
- **distance_cache** (28 rows, 11 cols): id, origin_zip, destination_warehouse_id, distance_miles, distance_text, duration_minutes, duration_text, transport_price...
- **dlq_entries** (0 rows, 19 cols): id, email_id, email_subject, email_from, email_date, failure_reason, failure_details, attachment_filename...
- **documents** (145 rows, 22 cols): id, uuid, auction_type_id, dataset_split, filename, file_path, file_size, sha256...
- **email_activity_log** (1924 rows, 9 cols): id, timestamp, message_id, subject, sender, status, rule_matched, run_id...
- **email_log** (216 rows, 18 cols): id, message_id, thread_id, sender, sender_name, subject, received_date, body_preview...
- **export_jobs** (15 rows, 16 cols): id, uuid, run_id, dispatch_id, cd_listing_id, status, payload_json, response_json...
- **extraction_runs** (156 rows, 17 cols): id, uuid, document_id, auction_type_id, extractor_kind, model_version_id, status, extraction_score...
- **extraction_templates** (3 rows, 10 cols): id, template_id, name, auction_type, version, zones_json, description, is_active...
- **field_configs** (1 rows, 8 cols): id, field_key, source_type, default_value, is_required, is_editable, created_at, updated_at
- **field_evidence** (3 rows, 12 cols): id, run_id, field_key, block_id, text_snippet, page_num, bbox_json, rule_id...
- **field_mappings** (76 rows, 19 cols): id, auction_type_id, source_key, internal_key, cd_key, transform, is_required, default_value...
- **integration_audit_log** (23 rows, 10 cols): id, timestamp, integration, action, status, user, request_id, details_json...
- **integration_credentials** (4 rows, 8 cols): id, service, config_json_encrypted, enabled, last_tested_at, last_test_status, created_at, updated_at
- **layout_blocks** (17 rows, 15 cols): id, document_id, block_id, page_num, x0, y0, x1, y1...
- **load_ids** (149 rows, 8 cols): id, load_id, base_id, make, model, sequence, created_date, created_at
- **logs** (0 rows, 6 cols): id, run_id, timestamp, level, message, details
- **model_versions** (0 rows, 14 cols): id, uuid, auction_type_id, version_tag, base_model, adapter_type, adapter_uri, config_json...
- **production_corrections** (9 rows, 13 cols): id, run_id, document_id, auction_type_id, auction_type_code, field_key, old_value, new_value...
- **review_items** (4134 rows, 15 cols): id, run_id, source_key, internal_key, cd_key, predicted_value, corrected_value, is_match_ok...
- **runs** (0 rows, 20 cols): id, created_at, source_type, status, email_message_id, attachment_hash, attachment_name, auction_detected...
- **sqlite_sequence** (22 rows, 2 cols): name, seq
- **template_feedback** (0 rows, 10 cols): id, template_id, document_id, extraction_run_id, field_key, extracted_value, corrected_value, zone_name...
- **template_versions** (0 rows, 6 cols): id, auction_type_id, version_tag, description, is_active, created_at
- **training_examples** (845 rows, 11 cols): id, uuid, auction_type_id, document_id, input_text, input_chunks_json, labels_json, source_review_item_ids...
- **training_jobs** (0 rows, 14 cols): id, uuid, auction_type_id, model_version_id, status, progress, current_step, total_steps...
- **warehouse_constants** (0 rows, 7 cols): id, warehouse_id, warehouse_code, constants_json, is_active, created_at, updated_at
- **warehouses** (9 rows, 27 cols): id, code, name, address, city, state, zip_code, country...
- **weather_cache** (19 rows, 6 cols): id, cache_key, alerts_json, route_states, checked_at, expires_at

**Indexes:** 61 total

## Part 3: API Endpoints (216 total)

### Top 10 Route Files by Size
| File | Size (bytes) |
|------|-------------|
| extractions.py | 110,212 |
| exports.py | 98,050 |
| documents.py | 56,638 |
| reviews.py | 30,513 |
| settings.py | 27,592 |
| test.py | 27,467 |
| templates.py | 26,520 |
| warehouses.py | 23,500 |
| weather.py | 23,539 |
| pricing.py | 23,409 |

## Part 4: Service Layer

| Service | Purpose | Size (bytes) |
|---------|---------|-------------|
| distance_service.py | Google Maps / OSRM / Haversine distance | 42,129 |
| cd_exporter.py | Central Dispatch export payload builder | 33,219 |
| weather_service.py | NWS weather alerts + AI summary | 29,433 |
| haiku_extractor.py | AI extraction via Claude Haiku | 27,017 |
| sheets_exporter.py | Google Sheets integration | 25,801 |
| pricing_engine.py | Transport pricing recommendations | 23,587 |
| cd_sheet_exporter.py | CD Sheet export integration | 22,888 |
| correction_rules_service.py | Auto-correction rules from training | 20,799 |
| backup_service.py | Database backup service | 20,007 |
| warehouse.py | Warehouse matching and assignment | 17,049 |
| auction_directory.py | Auction location lookup | 15,617 |
| credential_store.py | Encrypted credential management | 6,940 |

## Part 5: Frontend Architecture

### Pages
| Page | Lines |
|------|-------|
| Documents.jsx | 1740 |
| TestLab.jsx | 1303 |
| Review.jsx | 1183 |
| EmailLog.jsx | 845 |
| Settings.jsx | 86 |

### Review.jsx Component Tree
```
Review.jsx (1183 lines, 17 useState hooks, 3 useEffects)
  +-- ExtractionInfoBar
  +-- EmailContextPanel
  +-- ManualEntryBanner
  +-- VehicleSection
  +-- PickupSection
  +-- DeliverySection
  +-- WeatherAlertsPanel
  +-- DatesSection
  +-- PricingPaymentSection
  +-- AdditionalInfoSection
  +-- DocumentDetails
  +-- ExportActions
  +-- ExportPreviewModal
```

### Components (28 total)
- 12 review/ components (section-based decomposition)
- 6 settings/ tab components
- 3 testlab/ components
- 7 shared components (PDFViewer, ExportPreviewModal, etc.)

## Part 6: Configuration

### Active Warehouses
- **Sergii Vorotyntsev** - NATICK, MA 01760 (CROSS_DOCK)
- **TRT International - Argus Motors (TX)** - La Porte, TX 77571 (BUSINESS)

### Auction Types
- Copart (code=COPART, active=1)
- IAA (Insurance Auto Auctions) (code=IAA, active=1)
- Manheim (code=MANHEIM, active=1)
- Other (code=OTHER, active=1)

### Credentials (4 configured)
- anthropic (enabled)
- cd_api (enabled)
- email_oauth (enabled)
- google_maps (enabled)

## Part 7: Current Data State

### Extraction Runs by Status
- needs_review: 134
- approved: 8
- exported: 7
- failed: 4
- manual_required: 3

### By Auction Source
- IAA: 64
- COPART: 56
- MANHEIM: 21
- unknown: 14

### Key Metrics
- Documents: 145, Extraction Runs: 156
- Emails processed: 216
- CD Listings created: 9
- Export jobs: 15 (9 completed, 6 failed_archived)
- Auction cost extracted: 149/155
- Gate pass extracted: 109/155
- Warehouse assigned: 20/155
- Distance cache: 28 entries (all Google)
- Weather cache: 19 entries

## Part 8: Test Suite

**1,264 tests collected** across 45 test files

### Top E2E Test Files
| File | Tests |
|------|-------|
| test_email_filtering.py | 100 |
| test_day15_comprehensive.py | 69 |
| test_cd_export.py | 43 |
| test_review_ui_logic.py | 41 |
| test_error_handling.py | 41 |
| test_auction_classification.py | 39 |
| test_full_pipeline.py | 34 |
| test_flicker_attachment_price.py | 28 |
| test_manheim_pipeline.py | 28 |
| test_cd_payload_v2.py | 26 |

## Part 9: Recent Git History (Last 15 Commits)

```
5016de2f test: Day 15 comprehensive E2E suite â€” 69 tests across 16 classes
fa953000 fix: 4 critical bugs â€” banking PDF exclusion, graceful endpoint degradation, duplicate API calls
fed149cb fix: 4 persistent bugs â€” warehouse export tracking, attachment matching, weather recommendations
49264f33 fix: 6 persistent bugs â€” surgical fixes with verified diagnosis
6fe29d3f docs: add Multi-Agent Collaborative Development Protocol + field name mapping to CLAUDE.md
5410f5d9 feat: multi-agent collaborative fix â€” parallel Review loading, weather AI recommendations, attachment dedup, rate/mile
e4ca6318 feat: multi-agent fix â€” attachments/price/performance/weather AI decision engine
af8987ad fix: price columns (auction/transport/rate), attachment dedup, status-aware editing UI
407086d5 fix: systematic attachment redesign, price single-field, Documents loading, PDF viewer inline
4e65fb39 fix: inline attachment viewing, PDF viewer UX, transport price definitive, attachment switching
eaf52564 fix: attachments in EmailContext, price display, navigation cache, collapsible PDF viewer
40220385 fix: Documents no-flicker warehouse, attachment gallery in Review, transport price display
a95b82c5 fix: Load ID recalculate endpoint, batch export verified, frontend cleanup
1b1d486c feat: 2-step email scanâ†’selectâ†’process, production hardening (Docker, health, backup)
789c9552 feat: batch operations â€” bulk approve/hold/archive with multi-select UI
```

Last 10 commits: 22 files changed, 2,617 insertions(+), 282 deletions(-)

## Part 10: Known Issues & TODOs

### Code TODOs
- `extractions.py:704` - TODO: Implement ML extraction
- `correction_rules_service.py:337` - TODO: analyze why prediction was wrong
- `distance_service.py:299` - TODO: Integrate with CD Market Intelligence API

### Disabled Features
- ClickUp integration (disabled 2026-02-11 per directive v3.1)

### Test Data Notes
- WH 9 contains XSS test payload as name (inactive test warehouse)
