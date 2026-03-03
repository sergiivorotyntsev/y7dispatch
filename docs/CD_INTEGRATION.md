# Central Dispatch API V2 Integration

> Covers: OAuth2, payload structure, field mapping, export flow, email replies.

## 1. Authentication

**File:** `api/cd_client.py`

### OAuth2 Client Credentials Flow
```
Token URL:  https://id.centraldispatch.com/connect/token
API Base:   https://marketplace-api.centraldispatch.com
Scope:      marketplace
Grant Type: client_credentials
```

### Token Management
- Cached in memory with 60-second refresh margin before expiry
- Auto-refreshes on 401 responses
- Credentials loaded from `credential_store` (service: `cd_api`), fallback to env vars

### Retry & Concurrency
| Setting | Value |
|---------|-------|
| Max retries | 3 |
| Concurrent limit | 5 (semaphore) |
| Backoff base | 2.0 seconds |
| Max delay | 30 seconds |
| Idempotency | SHA256-based deterministic keys |

### ETag Concurrency
- `create_listing()` → POST returns `ETag` in response header
- `update_listing()` → PUT with `If-Match: {etag}` header
- 412 Precondition Failed → auto-refresh ETag via GET, retry
- 409 Conflict → search by `partnerReferenceId` to find existing listing

---

## 2. Payload Structure

**File:** `api/routes/exports.py:298-851` — `build_cd_payload()`

### Complete CD API V2 Payload

```json
{
  "externalId": "216JEEPR1",
  "partnerReferenceId": "CD-RUN-42",
  "shipperOrderId": "216JEEPR1",
  "trailerType": "OPEN",
  "hasInOpVehicle": false,
  "requiresInspection": true,
  "availableDate": "2026-03-03T00:00:00Z",
  "expirationDate": "2026-04-02T00:00:00Z",
  "desiredDeliveryDate": "2026-03-10T00:00:00Z",

  "price": {
    "total": 450.00,
    "cod": {
      "amount": 0,
      "paymentMethod": "CASH_CERTIFIED_FUNDS",
      "paymentLocation": "DELIVERY"
    },
    "balance": {
      "amount": 450.00,
      "balancePaymentMethod": "CERTIFIED_FUNDS",
      "paymentTime": "TWO_BUSINESS_DAYS",
      "balancePaymentTermsBeginOn": "RECEIVING_SIGNED_BOL"
    }
  },

  "stops": [
    {
      "stopNumber": 1,
      "locationName": "Copart North Boston",
      "address": "77 Fitchburg Rd",
      "city": "Ayer",
      "state": "MA",
      "postalCode": "01432",
      "country": "US",
      "locationType": "Auction",
      "phone": "(978) 772-2300",
      "contactName": "John Doe",
      "buyerNumber": "535527"
    },
    {
      "stopNumber": 2,
      "locationName": "Y7 Warehouse Boston",
      "address": "123 Industrial Way",
      "city": "Worcester",
      "state": "MA",
      "postalCode": "01608",
      "country": "US",
      "locationType": "Terminal",
      "phone": "(508) 555-1234",
      "contactPhone": "(508) 555-5678",
      "contactName": "Jane Smith",
      "contactEmailAddress": "warehouse@y7.com",
      "buyerNumber": "REF-001"
    }
  ],

  "vehicles": [
    {
      "pickupStopNumber": 1,
      "dropoffStopNumber": 2,
      "vin": "1C4RJFAG2GC489125",
      "year": 2016,
      "make": "JEEP",
      "model": "GRAND CHEROKEE",
      "color": "WHITE",
      "vehicleType": "SUV",
      "lotNumber": "43666048",
      "isInoperable": false,
      "additionalInfo": "GATE PASS: ABC123"
    }
  ],

  "marketplaces": [
    {
      "marketplaceId": 10000,
      "searchable": true,
      "predispatchNotes": "Please TEXT 857-895-8777 upon pickup"
    }
  ],

  "tags": [
    {"key": "automationVersion", "value": "v2.0"},
    {"key": "sourceSystem", "value": "y7dispatch"},
    {"key": "auctionSource", "value": "COPART"},
    {"key": "gatePass", "value": "ABC123"},
    {"key": "warehouseId", "value": "BOS1"}
  ],

  "loadSpecificTerms": "TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY). Pick-up location - Copart North Boston, Delivery - Y7 Warehouse Boston",
  "transportationReleaseNotes": "Call 30 min before arrival"
}
```

---

## 3. Field Mapping

**File:** `cd_field_mapping_v2.yaml`

### Top-Level Fields

| CD API V2 Field | Internal Field | Source |
|----------------|---------------|--------|
| `externalId` | `dispatch_id` (= Load ID) | Generated |
| `partnerReferenceId` | `CD-RUN-{run_id}` | Computed |
| `trailerType` | `trailer_type` | Default: OPEN |
| `hasInOpVehicle` | `vehicle_is_inoperable` | Extracted |
| `requiresInspection` | `requires_inspection` | Default: true |
| `availableDate` | `available_date` | Default: today |
| `loadSpecificTerms` | (template) | Generated |
| `transportationReleaseNotes` | `transport_special_instructions` | Warehouse |

### Stop Fields (Pickup = stops[0], Delivery = stops[1])

| CD API V2 Field | Pickup Source | Delivery Source |
|----------------|--------------|----------------|
| `locationName` | `pickup_name` | `warehouse.name` |
| `address` | `pickup_address` | `warehouse.address` |
| `city` | `pickup_city` | `warehouse.city` |
| `state` | `pickup_state` | `warehouse.state` |
| `postalCode` | `pickup_zip` | `warehouse.zip_code` |
| `locationType` | Extraction (default: Auction) | Warehouse (default: Terminal) |
| `phone` | Auction directory phone | `warehouse.phone` |
| `contactPhone` | — | `warehouse.contact_phone` |
| `contactName` | `pickup_contact` | `warehouse.contact_name` |
| `contactEmailAddress` | — | `warehouse.contact_email` |
| `buyerNumber` | `buyer_id` | `warehouse.buyer_reference` |

### Vehicle Fields

| CD API V2 Field | Internal Field |
|----------------|---------------|
| `vin` | `vehicle_vin` |
| `year` | `vehicle_year` |
| `make` | `vehicle_make` |
| `model` | `vehicle_model` |
| `color` | `vehicle_color` |
| `vehicleType` | `vehicle_type` |
| `lotNumber` | `vehicle_lot` |
| `isInoperable` | `vehicle_is_inoperable` |
| `additionalInfo` | Gate pass + Manheim release info |

### Vehicle additionalInfo Construction
```python
parts = []
if gate_pass:
    parts.append(f"GATE PASS: {gate_pass}")
if manheim_release_date and manheim_release_date != "NO_RELEASE_DOCUMENT":
    if manheim_offsite:
        parts.append("VEHICLE RELEASE: OFFSITE")
    else:
        parts.append("VEHICLE RELEASE: ONSITE")
    if manheim_release_date == "AVAILABLE_NOW":
        parts.append("Available now")
    else:
        parts.append(f"Release date: {manheim_release_date}")
additionalInfo = ". ".join(parts)
```

---

## 4. Field Resolution Priority

**File:** `api/routes/exports.py` — `build_cd_payload()`

```
1. EXPORT_OVERRIDES  → field_overrides dict from UI (highest)
2. USER_OVERRIDE     → review_items.corrected_value
3. WAREHOUSE_CONST   → warehouse data for delivery
4. AUCTION_CONST     → auction type defaults
5. EXTRACTED         → extraction_runs.outputs_json
6. DEFAULT           → built-in defaults (lowest)
```

---

## 5. Export Flow

### Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/exports/central-dispatch` | Export (dry-run or live) |
| GET/POST | `/api/exports/central-dispatch/preview/{run_id}` | Preview payload |
| POST | `/api/exports/batch-post` | Batch export |
| GET | `/api/exports/cd-listing/{run_id}` | Get CD listing + ETag |
| POST | `/api/exports/jobs/{job_id}/retry` | Retry failed export |

### Export Request
```python
class CDExportRequest:
    run_ids: list[int]
    dry_run: bool = True  # Preview without sending
    overrides: Optional[OperatorOverrides]
    field_overrides: Optional[dict[str, str]]
```

### Export Process
1. Build payload via `build_cd_payload()` → validates required fields
2. If `dry_run=True` → return payload JSON without sending
3. If existing `cd_listings` entry → PUT update with ETag
4. If new → POST create with idempotency key
5. Handle: 201 Created, 204 No Content, 409 Conflict, 412 ETag mismatch, 429 Rate Limit
6. Save to `export_jobs` table + `cd_listings` table
7. Persist field_overrides to `review_items.corrected_value`

---

## 5a. CD API V2 Stops Schema Reference

Fields accepted by the CD API V2 `stops[]` object:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `stopNumber` | integer | YES | 1=pickup, 2=delivery |
| `locationName` | string | NO | Facility/business name |
| `address` | string | YES | Street address |
| `city` | string | YES | City |
| `state` | string | YES | 2-letter state code |
| `postalCode` | string | YES | 5-digit ZIP |
| `country` | string | NO | Default: "US" |
| `locationType` | string | NO | See Section 6 for valid values |
| `phone` | string | NO | Facility main phone |
| `contactName` | string | NO | Contact person name |
| `contactPhone` | string | NO | Contact person phone |
| `contactEmailAddress` | string | NO | Contact email (NOT "email") |
| `buyerNumber` | string | NO | Buyer reference / member ID (NOT "buyerReferenceNumber") |
| `operatingHours` | string | NO | Facility operating hours |

> **Important:** CD API V2 silently ignores unknown fields (returns 201 even with invalid field names). Always verify field names against this schema.

---

## 6. Location Type Normalization

```python
_CD_LOCATION_TYPE_MAP = {
    "AUCTION": "Auction",
    "DEALER": "Dealership", "DEALERSHIP": "Dealership",
    "BUSINESS": "Dealership",
    "WAREHOUSE": "Warehouse", "CROSS_DOCK": "Warehouse",
    "RESIDENCE": "Residence",
    "PORT": "Port",
    "TERMINAL": "Terminal",
    "OTHER": "Other",
}
```

## 7. Payment Time Normalization

```python
_CD_PAYMENT_TIME_MAP = {
    "2_BUSINESS_DAYS": "TWO_BUSINESS_DAYS",
    "2_BUSINESS_DAYS_QUICK_PAY": "TWO_BUSINESS_DAYS",
    "5_BUSINESS_DAYS": "FIVE_BUSINESS_DAYS",
    "IMMEDIATELY": "IMMEDIATELY",
    # V2 format values pass through unchanged
}
```

---

## 8. Email Reply System

**Files:** `api/services/email_replier.py`, `api/routes/replies.py`, `ingest/email_reader.py`

### Flow
1. After CD export completes → user clicks "Send Reply" on Review page
2. System finds original email in `email_log` (by `extraction_run_ids`)
3. Resolves Microsoft Graph message ID (RFC822 → Graph internal ID)
4. Renders HTML template with Load ID, VIN, warehouse info
5. Calls `GraphEmailReader.reply_to_message(graph_message_id, html_body)`
6. Records in `email_replies` table (idempotent — won't re-send)

### Reply Template Variables
```
{{greeting}}          — "Hi John," or "Hello,"
{{load_id}}           — "216JEEPR1"
{{vin}}               — "1C4RJFAG2GC489125"
{{pickup_name}}       — "Copart North Boston"
{{warehouse_name}}    — "Y7 Warehouse Boston"
{{warehouse_full_address}} — "123 Industrial Way, Worcester, MA 01608"
{{warehouse_phone}}   — "(508) 555-1234"
```

### Endpoints
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/runs/{run_id}/reply` | Send confirmation reply |
| POST | `/api/runs/{run_id}/reply/preview` | Preview without sending |
| GET | `/api/runs/{run_id}/reply/status` | Check reply status |
