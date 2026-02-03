# Google Sheets Schema v2 - CD Listings API V2

This document describes the Google Sheets schema used as the **Source of Truth** for exporting vehicle transport data to Central Dispatch Listings API V2.

## Overview

| Property | Value |
|----------|-------|
| **Schema Version** | 2 |
| **Total Columns** | 86 |
| **Required Columns** | 18 |
| **Protected Columns** | 14 |
| **Lock Columns** | 3 |

## Key Concepts

### dispatch_id (Primary Key)

Each row is uniquely identified by `dispatch_id`. Format:

```
DC-{YYYYMMDD}-{AUCTION}-{HASH}
```

Example: `DC-20260130-COPART-ABC12345`

The hash is computed from (in priority order):
1. `gate_pass` (auction gate pass)
2. `auction_reference` (lot/order ID)
3. `vin` (vehicle VIN)
4. `attachment_hash` (source PDF hash)

### Row Status (State Machine)

```
NEW → READY → EXPORTED
         ↓
       HOLD
         ↓
       ERROR → RETRY → EXPORTED
         ↓
     CANCELLED
```

| Status | Description |
|--------|-------------|
| `NEW` | Just imported, not yet reviewed |
| `READY` | Validated, ready for CD export |
| `HOLD` | On hold, don't export |
| `ERROR` | Validation or export error |
| `EXPORTED` | Successfully exported to CD |
| `RETRY` | Manual retry requested |
| `CANCELLED` | Cancelled, don't process |

### Column Classes

| Class | Description |
|-------|-------------|
| `REQUIRED` | Must be filled for READY status |
| `SYSTEM` | Updated by automation |
| `PROTECTED` | Never overwritten if has value (`override_*` fields) |
| `LOCK` | Boolean flags that protect groups of fields |

### Override Pattern

For fields that may need manual correction, there are corresponding `override_*` columns:

- Base field: `vin` (from PDF extraction)
- Override field: `override_vin` (manual correction)
- Final value: `override_vin` if set, otherwise `vin`

### Lock Flags

| Flag | Effect |
|------|--------|
| `lock_all` | Blocks ALL updates except audit fields |
| `lock_delivery` | Blocks updates to `delivery_*` fields |
| `lock_release_notes` | Blocks updates to `release_notes` |

Additionally, `warehouse_selected_mode=MANUAL` blocks delivery field updates.

---

## Column Reference

### 1. Identity & Sources

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `dispatch_id` | REQUIRED | Yes | `shipperReferenceNumber` | Primary key |
| `row_status` | SYSTEM | Yes | - | Row lifecycle status |
| `auction_source` | SYSTEM | Yes | - | COPART/IAA/MANHEIM/UNKNOWN |
| `auction_reference` | SYSTEM | No | - | Lot/order ID from auction |
| `gate_pass` | SYSTEM | No | - | Gate pass code |
| `attachment_hash` | SYSTEM | No | - | SHA256 of source PDF |
| `email_message_id` | SYSTEM | No | - | Source email Message-ID |
| `ingested_at` | SYSTEM | No | - | First import timestamp |
| `updated_at` | SYSTEM | No | - | Last update timestamp |
| `extraction_score` | SYSTEM | No | - | Parser confidence 0-100 |

### 2. Vehicle (vehicles[0])

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `vin` | REQUIRED | Yes | `vehicles[0].vin` | Vehicle VIN |
| `year` | SYSTEM | No | `vehicles[0].year` | Vehicle year |
| `make` | SYSTEM | No | `vehicles[0].make` | Vehicle make |
| `model` | SYSTEM | No | `vehicles[0].model` | Vehicle model |
| `vehicle_type` | SYSTEM | No | `vehicles[0].vehicleType` | car/suv/truck/van |
| `operable` | SYSTEM | No | `vehicles[0].operable` | TRUE/FALSE |
| `notes_vehicle` | SYSTEM | No | `vehicles[0].notes` | Vehicle notes |
| `override_vin` | PROTECTED | No | - | Manual VIN override |
| `override_year` | PROTECTED | No | - | Manual year override |
| `override_make` | PROTECTED | No | - | Manual make override |
| `override_model` | PROTECTED | No | - | Manual model override |
| `override_operable` | PROTECTED | No | - | Manual operable override |

### 3. Pickup Stop (stops[0])

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `pickup_site_id` | SYSTEM | No | `stops[0].siteId` | Pickup site ID |
| `pickup_street1` | REQUIRED | Yes | `stops[0].location.street1` | Street address |
| `pickup_street2` | SYSTEM | No | `stops[0].location.street2` | Street line 2 |
| `pickup_city` | REQUIRED | Yes | `stops[0].location.city` | City |
| `pickup_state` | REQUIRED | Yes | `stops[0].location.state` | State (2-letter) |
| `pickup_postal_code` | REQUIRED | Yes | `stops[0].location.postalCode` | ZIP code |
| `pickup_country` | REQUIRED | Yes | `stops[0].location.country` | Country (US/CA) |
| `pickup_phone` | SYSTEM | No | `stops[0].location.phone` | Location phone |
| `pickup_phone2` | SYSTEM | No | `stops[0].location.phone2` | Phone 2 |
| `pickup_phone3` | SYSTEM | No | `stops[0].location.phone3` | Phone 3 |
| `pickup_contact_name` | SYSTEM | No | `stops[0].contact.name` | Contact name |
| `pickup_contact_phone` | SYSTEM | No | `stops[0].contact.phone` | Contact phone |
| `pickup_contact_cell` | SYSTEM | No | `stops[0].contact.cellPhone` | Contact cell |
| `pickup_instructions` | SYSTEM | No | `stops[0].instructions` | Pickup instructions |
| `override_pickup_street1` | PROTECTED | No | - | Manual address override |
| `override_pickup_city` | PROTECTED | No | - | Manual city override |
| `override_pickup_state` | PROTECTED | No | - | Manual state override |
| `override_pickup_postal_code` | PROTECTED | No | - | Manual ZIP override |

### 4. Delivery Stop (stops[1])

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `delivery_warehouse_id` | REQUIRED | Yes | - | Warehouse FK |
| `delivery_street1` | REQUIRED | Yes | `stops[1].location.street1` | Street address |
| `delivery_street2` | SYSTEM | No | `stops[1].location.street2` | Street line 2 |
| `delivery_city` | REQUIRED | Yes | `stops[1].location.city` | City |
| `delivery_state` | REQUIRED | Yes | `stops[1].location.state` | State (2-letter) |
| `delivery_postal_code` | REQUIRED | Yes | `stops[1].location.postalCode` | ZIP code |
| `delivery_country` | REQUIRED | Yes | `stops[1].location.country` | Country (US/CA) |
| `delivery_phone` | SYSTEM | No | `stops[1].location.phone` | Location phone |
| `delivery_contact_name` | SYSTEM | No | `stops[1].contact.name` | Contact name |
| `delivery_contact_phone` | SYSTEM | No | `stops[1].contact.phone` | Contact phone |
| `delivery_instructions` | SYSTEM | No | `stops[1].instructions` | Delivery instructions |
| `override_delivery_street1` | PROTECTED | No | - | Manual address override |
| `override_delivery_city` | PROTECTED | No | - | Manual city override |
| `override_delivery_state` | PROTECTED | No | - | Manual state override |
| `override_delivery_postal_code` | PROTECTED | No | - | Manual ZIP override |

### 5. Warehouse Selection

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `warehouse_recommended_id` | SYSTEM | No | - | Auto-recommended warehouse |
| `warehouse_recommended_distance_mi` | SYSTEM | No | - | Distance to recommended |
| `warehouse_selected_mode` | SYSTEM | No | - | AUTO/MANUAL |
| `warehouse_selected_at` | SYSTEM | No | - | Selection timestamp |

### 6. Dates / Availability

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `available_datetime` | REQUIRED | Yes | `availableDateTime` | Available for pickup |
| `expiration_datetime` | REQUIRED | Yes | `expirationDateTime` | Listing expiration |
| `override_available_datetime` | PROTECTED | No | - | Manual override |
| `override_expiration_datetime` | PROTECTED | No | - | Manual override |

### 7. Trailer / Load Flags

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `trailer_type` | REQUIRED | Yes | `trailerType` | OPEN/ENCLOSED/DRIVEAWAY |
| `allow_full_load` | SYSTEM | No | `allowFullLoad` | TRUE/FALSE |
| `allow_ltl` | SYSTEM | No | `allowLtl` | TRUE/FALSE |
| `override_trailer_type` | PROTECTED | No | - | Manual override |

### 8. Price

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `price_type` | REQUIRED | Yes | `price.type` | TOTAL/PER_MILE/PER_VEHICLE |
| `price_currency` | REQUIRED | Yes | `price.currency` | USD |
| `price_amount` | REQUIRED | Yes | `price.amount` | Price amount |
| `override_price_amount` | PROTECTED | No | - | Manual override |
| `cod_type` | SYSTEM | No | `price.cod.type` | COD type |
| `cod_amount` | SYSTEM | No | `price.cod.amount` | COD amount |
| `cod_payment_method` | SYSTEM | No | `price.cod.paymentMethod` | Payment method |
| `cod_payment_note` | SYSTEM | No | `price.cod.paymentMethodNote` | Payment note |
| `cod_aux_payment_method` | SYSTEM | No | `price.cod.auxiliaryPaymentMethod` | Aux payment |
| `cod_aux_payment_note` | SYSTEM | No | `price.cod.auxiliaryPaymentMethodNote` | Aux note |
| `balance_type` | SYSTEM | No | `price.balance.type` | Balance type |
| `balance_amount` | SYSTEM | No | `price.balance.amount` | Balance amount |
| `balance_payment_method` | SYSTEM | No | `price.balance.paymentMethod` | Balance payment |
| `balance_payment_note` | SYSTEM | No | `price.balance.paymentMethodNote` | Balance note |

### 9. Marketplace / SLA / Company

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `company_name` | REQUIRED | Yes | `companyName` | Company name |
| `marketplace_ids` | REQUIRED | Yes | `marketplaces` | Marketplace IDs |
| `sla_duration` | SYSTEM | No | `sla.duration` | SLA duration |
| `sla_timezone_offset` | SYSTEM | No | `sla.timeZoneOffset` | Timezone offset |
| `sla_rollover_time` | SYSTEM | No | `sla.rolloverTime` | Rollover time |
| `sla_include_current_day` | SYSTEM | No | `sla.includeCurrentDayAfterRollOver` | Include current day |

### 10. Release Notes / Tags

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `release_notes` | SYSTEM | No | `notes` | Release notes text |
| `tags_json` | SYSTEM | No | `tags` | Tags as JSON array |

### 11. Export Results / Audit

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `cd_listing_id` | SYSTEM | No | - | CD listing ID after export |
| `cd_exported_at` | SYSTEM | No | - | Export timestamp |
| `cd_last_error` | SYSTEM | No | - | Last export error |
| `cd_last_attempt_at` | SYSTEM | No | - | Last attempt timestamp |
| `cd_payload_snapshot` | SYSTEM | No | - | Sent payload JSON |
| `clickup_task_url` | SYSTEM | No | - | ClickUp task URL |
| `clickup_task_id` | SYSTEM | No | - | ClickUp task ID |

### 12. Lock Flags

| Column | Class | Required | CD Field | Description |
|--------|-------|----------|----------|-------------|
| `lock_release_notes` | LOCK | No | - | Lock release_notes |
| `lock_delivery` | LOCK | No | - | Lock delivery_* fields |
| `lock_all` | LOCK | No | - | Lock all fields |

---

## CLI Usage

### Upsert PDF to Sheet

```bash
python main.py sheets-upsert invoice.pdf
python main.py sheets-upsert invoice.pdf --sheet Pickups
```

### Export to Central Dispatch

```bash
# Dry run (no API calls)
python main.py cd-export --from-sheet --dry-run

# Export with limit
python main.py cd-export --from-sheet --limit 10

# Preview payload for single row
python main.py cd-export --from-sheet --preview --dispatch-id DC-20260130-COPART-ABC12345
```

---

## Protection Rules (Upsert Behavior)

When upserting a row that already exists:

1. **`lock_all=TRUE`**: Only audit fields are updated
2. **`override_*` with value**: Base field is not updated
3. **`lock_delivery=TRUE`**: All `delivery_*` fields are protected
4. **`warehouse_selected_mode=MANUAL`**: All `delivery_*` fields are protected
5. **`lock_release_notes=TRUE`**: `release_notes` is protected
6. **`override_vin` exists**: `vin` is not updated

---

## CD Listings API V2 Payload

The exporter builds a ListingRequest payload:

```json
{
  "stops": [
    {
      "type": "PICKUP",
      "location": {
        "street1": "123 Main St",
        "city": "Dallas",
        "state": "TX",
        "postalCode": "75001",
        "country": "US"
      },
      "contact": {
        "name": "John Doe",
        "phone": "555-1234"
      },
      "instructions": "Call before arrival"
    },
    {
      "type": "DELIVERY",
      "location": { ... }
    }
  ],
  "vehicles": [
    {
      "vin": "1HGBH41JXMN109186",
      "year": 2021,
      "make": "Honda",
      "model": "Civic",
      "operable": true
    }
  ],
  "price": {
    "type": "TOTAL",
    "currency": "USD",
    "amount": 450.00,
    "cod": {
      "type": "FULL",
      "amount": 450.00,
      "paymentMethod": "CASH"
    }
  },
  "marketplaces": [
    { "id": "marketplace-123" }
  ],
  "trailerType": "OPEN",
  "availableDateTime": "2026-01-30T08:00:00Z",
  "expirationDateTime": "2026-02-06T23:59:59Z",
  "companyName": "ABC Transport",
  "shipperReferenceNumber": "DC-20260130-COPART-ABC12345"
}
```

---

## Validation for READY Status

Before setting `row_status=READY`, the following are validated:

1. All required fields have values (considering overrides)
2. VIN is exactly 17 characters
3. Price amount is greater than 0
4. Expiration datetime is after available datetime
5. Trailer type is valid (OPEN/ENCLOSED/DRIVEAWAY)

---

*Schema Version 2 - January 2026*
