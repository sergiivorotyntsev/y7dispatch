# Frontend Architecture

> React 18 + Vite 5 + Tailwind CSS 3.3 SPA. No UI library — native HTML inputs.

## 1. Tech Stack

| Dependency | Version | Purpose |
|-----------|---------|---------|
| react | ^18.2.0 | UI framework |
| react-dom | ^18.2.0 | DOM rendering |
| react-router-dom | ^6.20.0 | Client-side routing |
| tailwindcss | ^3.3.5 | Utility CSS |
| vite | ^5.0.0 | Build tool + dev server |

### Build & Dev
```bash
npm run dev     # Dev server on :3000, proxy /api → :8000
npm run build   # Output to ../static/ (served by FastAPI)
```

---

## 2. Routing

**File:** `web/src/App.jsx`

| Route | Page Component | Purpose |
|-------|---------------|---------|
| `/` | `Documents` | Production workflow — document list |
| `/review/:runId` | `Review` | Review & edit extraction, export |
| `/email-log` | `EmailLog` | Email ingestion & processing |
| `/test-lab` | `TestLab` | Testing & training |
| `/settings` | `Settings` | Integrations & configuration |

### App Shell
- **Sidebar:** Collapsible (220px expanded / 60px collapsed), persisted in localStorage
- **Auth:** JWT httpOnly cookies, single-user mode
- **Login flow:** `POST /api/auth/login` → cookie set → `GET /api/auth/me` on refresh

---

## 3. Pages

### Documents (`web/src/pages/Documents.jsx`)
Production workflow hub. Lists documents with extraction status, warehouse assignment, pricing.

**State:** `useDocuments()` custom hook (filters, pagination, batch ops)

**Components:**
| Component | Purpose |
|-----------|---------|
| DocumentsHeader | Stats chips (total, ready, needs_review) + upload button |
| DocumentsFilters | Search, status/auction filter, sort, pagination |
| DocumentsTable | Date-grouped rows, warehouse selector, price editor, actions |
| DocumentsBatchBar | Batch approve/hold/archive/auto-assign/post |
| UploadModal | PDF upload with auction type selection |
| ExportPreviewModal | Full CD payload preview |

### Review (`web/src/pages/Review.jsx`)
Core review page — 9 CD-aligned sections. Largest component (~1400 lines).

**Key State:**
```javascript
const [run, setRun] = useState(null)          // Extraction run data
const [fields, setFields] = useState({})      // All field values
const [validation, setValidation] = useState(null)  // VIN + address validation
const [selectedWarehouse, setSelectedWarehouse] = useState(null)
const [distanceMiles, setDistanceMiles] = useState(null)
const [finalPrice, setFinalPrice] = useState(null)
```

**Data Loading Flow:**
1. `getReviewItems(runId)` → run data, fields, outputs
2. `getValidation(runId)` → VIN decode + address validation results
3. `getWarehouseOptionsForRun(runId)` → distance-sorted warehouse list
4. `getFullPricing(runId)` → market intelligence pricing
5. `getRunDuplicates(runId)` → VIN duplicate warnings

**Field Update:**
```javascript
updateField(fieldKey, correctedValue)  // Updates local state
updateExtraction(runId, {fields_json})  // API commit
```

**Export Flow:**
1. `getRunPreflight(runId, mode='export')` → validation check
2. `getCDPayloadPreview(runId)` → full JSON preview
3. `exportToCD([runId], dryRun, sandbox, force, overrides, fieldOverrides)` → send to CD

### Review Sections (9 sections)

**File:** `web/src/components/review/`

| # | Component | Purpose | Key Features |
|---|-----------|---------|-------------|
| 1 | ExtractionInfoBar | Document metadata | Filename, auction type, method, cost, confidence |
| 2 | VehicleSection | Vehicle data | VIN, year/make/model, lot, type, trailer, inoperable toggle, NHTSA validation badges |
| 3 | PickupSection | Pickup location | Name, address, city/state/zip, phone lookup, directory banner (confirmed/mismatch/not_found), per-field suggestion hints |
| 4 | DeliverySection | Delivery location | Warehouse selector with distance-sorted options, manual address override |
| 5 | WeatherAlertsPanel | Route weather | Weather warnings along transport route |
| 6 | DatesSection | Dates | Available, required by, delivery, pickup dates |
| 7 | PricingPaymentSection | Pricing | Market intel, final price, COD, balance, payment methods, $/mile calc |
| 8 | AdditionalInfoSection | Notes | Gate pass, Manheim release info, additional notes |
| 9 | ExportActions | Export controls | Export to CD, preview, send reply, preflight validation |

### PickupSection Directory Features
```
confirmed  → green banner: "Confirmed by directory (Copart North Boston)"
not_found  → yellow banner: "Not in directory — verify manually"
mismatch   → blue banner: "Directory differs — review highlighted fields"
              + per-field hints: 'Directory: "77 Fitchburg Rd" — use this' [button]
```

### EmailLog (`web/src/pages/EmailLog.jsx`)
Email ingestion and processing interface.

**Features:**
- 2-step: scan date range → select → process
- Status filter: processed, skipped, failed, ready, new, thread_reply, duplicate
- Expandable rows: body preview, attachments, linked documents
- Auto-poll status indicator
- Batch selection + process

### Settings (`web/src/pages/Settings.jsx`)
6-tab configuration interface.

| Tab | Component | Purpose |
|-----|-----------|---------|
| Credentials | CredentialsTab | OAuth clients, API keys |
| Warehouses | WarehousesTab | Warehouse CRUD (name, address, phone, hours) |
| Central Dispatch | CDTab | CD config, pre-dispatch notes per auction type |
| Email | EmailTab | Email rules, polling settings |
| Email Templates | EmailTemplateEditor | Reply confirmation HTML editor |
| Audit Log | AuditLogTab | Integration audit trail |

### TestLab (`web/src/pages/TestLab.jsx`)
Testing and training interface.

**Tabs:** Training, Zone Templates, Production Corrections, Auction Type Management

---

## 4. API Client

**File:** `web/src/api.js`

All API calls go through the centralized `api` object. Features:
- **GET request deduplication** — prevents duplicate network calls via `_inflight` Map
- **401 handling** — `window.location.reload()` → triggers auth check → Login
- **FormData** for file uploads (auto-removes Content-Type for boundary)

### Key Methods (by category)

```javascript
// Auth
api.login(username, password)
api.logout()
api.getAuthMe()

// Documents
api.listDocuments(params)    // Paginated list
api.uploadDocument(file, auctionTypeId)
api.holdDocument(docId, reason, note)
api.autoAssignWarehouse(docIds)

// Extractions
api.runExtraction(documentId, forceMl)  // async (sync=false)
api.getRunStatus(runId)                 // Poll async status

// Review
api.getReviewItems(runId)
api.updateExtraction(id, data)
api.validateRun(runId)
api.getRunDuplicates(runId)

// Export
api.previewCDPayload(runId, overrides, fieldOverrides)
api.exportToCD(runIds, dryRun, sandbox, force, overrides, fieldOverrides)

// Pricing
api.getFullPricing(runId, urgency)
api.getCDMarketPrice(runId, warehouseId)

// Warehouses
api.getWarehouseOptionsForRun(runId)  // Distance-sorted

// Email
api.scanEmails(sinceDate, untilDate)
api.processSelectedEmails(messageIds)
api.sendConfirmationReply(runId)
api.previewConfirmationReply(runId)
```

---

## 5. Validation Badges (UI)

**File:** `web/src/components/review/PickupSection.jsx`

| Status | Color | Label |
|--------|-------|-------|
| `verified` | Green | "Verified" |
| `corrected_by_directory` | Amber | "Directory Corrected" |
| `mismatch` | Red | "Mismatch" + clickable "Use {value}" |
| `unverified` | Yellow | "Unverified" |

---

## 6. Styling

**File:** `web/src/index.css`

Tailwind CSS with custom utility classes:
- `.badge` / `.badge-success/error/warning/info` — inline badges
- `.card` / `.card-header` / `.card-body` — card containers
- `.form-input` / `.form-select` — form elements
- `.btn` / `.btn-primary/secondary/success/danger` — buttons
- `.spinner` — CSS loading animation
- `.hide-narrow` — responsive hiding (< 1280px)

**No UI library** — all inputs are native HTML `<input>`, `<select>`, `<textarea>`.
