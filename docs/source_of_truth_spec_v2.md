# Source of Truth Specification v2

This document specifies the "Source of Truth" behavior for Google Sheets integration with Central Dispatch Listings API V2.

## Schema Version: 3

## 1. Core Principle

**Google Sheet is the ONLY source of data for CD export.**

- Ingestion (PDF/email) does upsert to Sheet but CANNOT break manual edits
- Export to CD is built ONLY from Sheet values (with override resolution)
- Manual corrections always take precedence

## 2. Primary Key: dispatch_id

### Format

```
DC-{YYYYMMDD}-{AUCTION}-{HASH}
```

Example: `DC-20260130-COPART-ABC12345`

### Components

| Part | Description |
|------|-------------|
| `DC` | Fixed prefix |
| `YYYYMMDD` | Date of ingestion |
| `AUCTION` | Source: COPART/IAA/MANHEIM/UNK |
| `HASH` | 8-char SHA1 hash |

### Hash Priority

The hash is computed from (in priority order):
1. `gate_pass` (if available)
2. `auction_reference` (if available)
3. `vin` (if available)
4. `attachment_hash` (fallback)

### CD API Mapping

```
dispatch_id -> externalId (<=50 chars)
```

## 3. State Machine: row_status

### States

| Status | Description |
|--------|-------------|
| `NEW` | Just imported, not yet reviewed |
| `READY` | Validated, ready for CD export |
| `HOLD` | On hold, don't export |
| `ERROR` | Validation or export error |
| `EXPORTED` | Successfully exported to CD |
| `RETRY` | Manual retry requested |
| `CANCELLED` | Cancelled, don't process |

### Valid Transitions

```
┌─────────┐
│   NEW   │
└────┬────┘
     │
     ├──────────────┬──────────────┐
     ▼              ▼              ▼
┌─────────┐   ┌─────────┐   ┌───────────┐
│  READY  │   │  HOLD   │   │ CANCELLED │
└────┬────┘   └────┬────┘   └───────────┘
     │              │
     ├──────┬───────┤
     │      │       │
     ▼      ▼       ▼
┌────────┐ ┌─────┐ ┌───────────┐
│EXPORTED│ │ERROR│ │ CANCELLED │
└────────┘ └──┬──┘ └───────────┘
              │
              ├──────────────┬──────────────┐
              ▼              ▼              ▼
         ┌─────────┐   ┌─────────┐   ┌───────────┐
         │  RETRY  │   │  HOLD   │   │ CANCELLED │
         └────┬────┘   └─────────┘   └───────────┘
              │
              ├──────────────┐
              ▼              ▼
         ┌────────┐     ┌─────────┐
         │EXPORTED│     │  ERROR  │
         └────────┘     └─────────┘
```

### Transition Rules

| From | To | Condition |
|------|-----|-----------|
| NEW | READY | All required fields filled + validation passes |
| NEW | HOLD | Operator marks as hold |
| NEW | CANCELLED | Operator cancels |
| READY | EXPORTED | CD API success |
| READY | ERROR | CD API failure or validation error |
| READY | HOLD | Operator marks as hold |
| READY | CANCELLED | Operator cancels |
| ERROR | RETRY | Operator requests retry |
| ERROR | HOLD | Operator marks as hold |
| ERROR | CANCELLED | Operator cancels |
| RETRY | EXPORTED | CD API success |
| RETRY | ERROR | CD API failure |
| RETRY | HOLD | Operator marks as hold |
| HOLD | READY | Operator un-holds (if valid) |
| HOLD | CANCELLED | Operator cancels |

### Ingestion Rule

**Ingestion NEVER changes row_status**, except:
- Creating new row → sets `NEW`
- Updating SYSTEM/AUDIT fields (timestamps, hashes, scores)

## 4. Column Classes

| Class | Description | Ingestion Writes? |
|-------|-------------|-------------------|
| `PK` | Primary key (dispatch_id) | Yes (on insert) |
| `SYSTEM` | Automation metadata | Yes |
| `AUDIT` | Export tracking | Yes |
| `LOCK` | Protection flags | No (operator only) |
| `BASE` | Business data | Yes (with rules) |
| `OVERRIDE` | Manual corrections | **NEVER** |

## 5. Lock Flags

### lock_all

When `lock_all=TRUE`:
- Ingestion updates ONLY: `SYSTEM` and `AUDIT` columns
- All `BASE` columns are protected
- Use case: Row is fully reviewed, prevent any extraction changes

### lock_delivery

When `lock_delivery=TRUE`:
- Ingestion does NOT touch delivery stop fields:
  - `dropoff_*` (all dropoff fields)
  - `delivery_warehouse_id`
  - `warehouse_recommended_id`
- Use case: Warehouse manually selected, prevent routing changes

### lock_release_notes

When `lock_release_notes=TRUE`:
- Ingestion does NOT touch:
  - `transportation_release_notes`
  - `load_specific_terms`
- Use case: Release notes manually edited

## 6. Warehouse Selection Mode

### warehouse_selected_mode

| Value | Description |
|-------|-------------|
| `AUTO` | System-recommended warehouse (ingestion can update delivery) |
| `MANUAL` | Operator-selected warehouse (blocks delivery updates) |

### Rules

- When `MANUAL`: All delivery fields are protected (same as `lock_delivery=TRUE`)
- Ingestion sets `AUTO` by default on insert
- Operator changes to `MANUAL` when selecting specific warehouse

## 7. Override Pattern

### Purpose

Allows manual corrections without losing extraction data.

### Pattern

For field `X`:
- Base field: `X` (filled by ingestion)
- Override field: `override_X` (manual correction)
- Final value: `override_X` if non-empty, else `X`

### Supported Overrides

| Base Field | Override Field |
|------------|----------------|
| `trailer_type` | `override_trailer_type` |
| `available_date` | `override_available_date` |
| `expiration_date` | `override_expiration_date` |
| `desired_delivery_date` | `override_desired_delivery_date` |
| `price_total` | `override_price_total` |
| `transportation_release_notes` | `override_transportation_release_notes` |
| `pickup_address` | `override_pickup_address` |
| `pickup_city` | `override_pickup_city` |
| `pickup_state` | `override_pickup_state` |
| `pickup_postal_code` | `override_pickup_postal_code` |
| `dropoff_address` | `override_dropoff_address` |
| `dropoff_city` | `override_dropoff_city` |
| `dropoff_state` | `override_dropoff_state` |
| `dropoff_postal_code` | `override_dropoff_postal_code` |
| `vehicle_vin` | `override_vehicle_vin` |
| `vehicle_year` | `override_vehicle_year` |
| `vehicle_make` | `override_vehicle_make` |
| `vehicle_model` | `override_vehicle_model` |
| `vehicle_is_inoperable` | `override_vehicle_is_inoperable` |

### Ingestion Rule

**Ingestion NEVER writes to `override_*` columns.**

## 8. Non-Destructive Upsert Rules

### Insert (New Row)

When row doesn't exist:
1. Generate `dispatch_id` if not provided
2. Fill all extracted fields
3. Set `row_status=NEW`
4. Set `warehouse_selected_mode=AUTO`
5. Set all `lock_*=FALSE`
6. Set `ingested_at` and `updated_at`

### Update (Existing Row)

When row exists, apply rules in order:

#### Rule 1: Check lock_all

```
IF lock_all=TRUE:
    UPDATE ONLY: SYSTEM + AUDIT columns
    SKIP: All BASE columns
    EXIT
```

#### Rule 2: Check row_status for fill-only mode

```
IF row_status != NEW:
    MODE = fill_only
    # Only fill empty fields, don't overwrite
ELSE:
    MODE = normal
```

#### Rule 3: Check delivery protection

```
IF lock_delivery=TRUE OR warehouse_selected_mode=MANUAL:
    SKIP: All dropoff_* fields
    SKIP: delivery_warehouse_id
    SKIP: warehouse_recommended_id
```

#### Rule 4: Check release notes protection

```
IF lock_release_notes=TRUE:
    SKIP: transportation_release_notes
    SKIP: load_specific_terms
```

#### Rule 5: Apply updates

```
FOR each field in extracted_record:
    IF field is OVERRIDE class:
        SKIP (never write)

    IF fill_only mode AND field has value in sheet:
        SKIP (don't overwrite)

    IF field value changed:
        UPDATE field
```

#### Rule 6: Always update timestamps

```
UPDATE updated_at = now()
```

### Upsert Response

```json
{
  "action": "insert" | "update",
  "dispatch_id": "DC-20260130-COPART-ABC12345",
  "updated_fields": ["vehicle_vin", "pickup_city", ...],
  "skipped_fields": [
    {"field": "price_total", "reason": "fill_only_mode"},
    {"field": "dropoff_address", "reason": "lock_delivery"},
    {"field": "override_vin", "reason": "override_column"}
  ],
  "protection_snapshot": {
    "row_status": "READY",
    "lock_all": false,
    "lock_delivery": true,
    "lock_release_notes": false,
    "warehouse_selected_mode": "MANUAL"
  }
}
```

## 9. READY Validation (CD V2 Requirements)

Row can only be set to `READY` if ALL of the following pass:

### Required Fields

| Field | Requirement |
|-------|-------------|
| `dispatch_id` | Non-empty, <=50 chars |
| `trailer_type` | OPEN / ENCLOSED / DRIVEAWAY |
| `available_date` | YYYY-MM-DD, today to +30 days |
| `expiration_date` | YYYY-MM-DD, > available_date |
| `price_total` | > 0 |
| `marketplace_id` | Integer |

### Pickup Stop (stops[0])

| Field | Requirement |
|-------|-------------|
| `pickup_stop_number` | = 1 |
| `pickup_address` | Non-empty |
| `pickup_city` | Non-empty |
| `pickup_state` | 2-letter code |
| `pickup_postal_code` | Non-empty |
| `pickup_country` | US or CA |

### Dropoff Stop (stops[1])

| Field | Requirement |
|-------|-------------|
| `dropoff_stop_number` | = 2 |
| `dropoff_address` | Non-empty |
| `dropoff_city` | Non-empty |
| `dropoff_state` | 2-letter code |
| `dropoff_postal_code` | Non-empty |
| `dropoff_country` | US or CA |

### Vehicle (vehicles[0])

| Field | Requirement |
|-------|-------------|
| `vehicle_vin` | Exactly 17 characters |

### Date Rules

1. `available_date` must be >= today
2. `available_date` must be <= today + 30 days
3. `expiration_date` must be > `available_date`

### Override Resolution

Validation uses final values:
```
final_value = override_X if override_X else X
```

## 10. CD API V2 Payload Structure

### Example Payload

```json
{
  "externalId": "DC-20260130-COPART-ABC12345",
  "trailerType": "OPEN",
  "hasInOpVehicle": false,
  "availableDate": "2026-01-30",
  "expirationDate": "2026-02-15",
  "transportationReleaseNotes": "Gate pass: ABC123",
  "price": {
    "total": 450.00,
    "cod": {
      "amount": 450.00,
      "paymentMethod": "CASH",
      "paymentLocation": "DELIVERY"
    }
  },
  "stops": [
    {
      "stopNumber": 1,
      "locationName": "Copart Dallas",
      "address": "123 Auction Blvd",
      "city": "Dallas",
      "state": "TX",
      "postalCode": "75001",
      "country": "US",
      "locationType": "AUCTION"
    },
    {
      "stopNumber": 2,
      "locationName": "ABC Warehouse",
      "address": "456 Industrial Way",
      "city": "Houston",
      "state": "TX",
      "postalCode": "77001",
      "country": "US",
      "locationType": "BUSINESS"
    }
  ],
  "vehicles": [
    {
      "pickupStopNumber": 1,
      "dropoffStopNumber": 2,
      "vin": "1HGBH41JXMN109186",
      "year": 2021,
      "make": "Honda",
      "model": "Civic",
      "isInoperable": false,
      "lotNumber": "12345678"
    }
  ],
  "marketplaces": [
    {
      "marketplaceId": 12345,
      "digitalOffersEnabled": true,
      "searchable": true,
      "offersAutoAcceptEnabled": false
    }
  ]
}
```

## 11. CLI Commands

### Upsert PDF to Sheet

```bash
python main.py sheets-upsert invoice.pdf
python main.py sheets-upsert invoice.pdf --sheet Pickups
```

### Export to CD

```bash
# Dry run (preview)
python main.py cd-export --from-sheet --dry-run

# Export with limit
python main.py cd-export --from-sheet --limit 10

# Preview payload for single row
python main.py cd-export --from-sheet --preview --dispatch-id DC-20260130-COPART-ABC12345
```

## 12. Files Reference

| File | Description |
|------|-------------|
| `schemas/sheets_schema_v3.py` | Column definitions, validation |
| `services/sheets_exporter_v3.py` | Source of Truth upsert logic |
| `services/cd_sheet_exporter_v2.py` | CD V2 payload builder |
| `cd_field_mapping_v2.yaml` | Sheet → CD field mapping |

---

*Schema Version 3 - January 2026*
*Based on CD Listings API V2*
