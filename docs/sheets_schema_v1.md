# Google Sheets Schema v1 - Source of Truth

## Overview

The **Pickups** sheet is the single source of truth for all pickup/transport data. The automation system uses upsert mode to create or update records without overwriting manual edits.

**Schema Version:** 1
**Total Columns:** 89

## Key Concepts

### 1. Column Classes

| Class | Count | Description | Import Behavior |
|-------|-------|-------------|-----------------|
| **IMMUTABLE** | 5 | Never change after creation | Set once on create, never updated |
| **SYSTEM** | 65 | Updated by automation | Updated on each import |
| **USER** | 19 | Human-editable only | Never touched by import |

### 2. Primary Key (pickup_uid)

The `pickup_uid` column is the primary key, computed as a 16-character SHA1 hash.

**Algorithm:**
```python
def compute_pickup_uid(auction, gate_pass, lot_number, vin, attachment_hash):
    # Priority 1: auction + gate_pass
    if gate_pass:
        return sha1(f"{auction}|{gate_pass}".lower())[:16]

    # Priority 2: auction + lot_number
    if lot_number:
        return sha1(f"{auction}|{lot_number}".lower())[:16]

    # Priority 3: auction + vin
    if vin:
        return sha1(f"{auction}|{vin}".upper())[:16]

    # Priority 4: fallback to attachment_hash
    return sha1(f"{auction}|{attachment_hash}".lower())[:16]
```

### 3. Base/Override/Final Pattern

Many fields use a three-column pattern:

| Column | Class | Description |
|--------|-------|-------------|
| `{field}_base` | SYSTEM | Value from parser |
| `{field}_override` | USER | Manual override |
| `{field}_final` | SYSTEM | Computed: override if set, else base |

**Example:**
- `vin_base` = "1HGBH41JXMN109186" (from PDF)
- `vin_override` = "" (empty, no override)
- `vin_final` = "1HGBH41JXMN109186" (uses base)

If user sets `vin_override` = "CORRECTED_VIN":
- `vin_final` = "CORRECTED_VIN" (uses override)

### 4. Lock Import Protection

When `lock_import = TRUE`:
- Import only updates `last_ingested_at`
- All other columns are preserved
- Use this to protect manually curated rows

---

## Column Reference

### 1. Identification & Sources

| Column | Type | Class | Description |
|--------|------|-------|-------------|
| `pickup_uid` | string | IMMUTABLE | Primary key (16-char hash) |
| `status` | enum | USER | NEW, NEEDS_REVIEW, READY_FOR_CD, EXPORTED_TO_CD, FAILED, LOCKED |
| `created_at` | datetime | IMMUTABLE | Row creation timestamp |
| `last_ingested_at` | datetime | SYSTEM | Last import timestamp |
| `auction_detected` | enum | SYSTEM | COPART, IAA, MANHEIM, UNKNOWN |
| `auction_ref_base` | string | SYSTEM | Lot/stock/order ID |
| `gate_pass_base` | string | SYSTEM | Gate pass code |
| `source_email_message_id` | string | IMMUTABLE | Original email ID |
| `source_email_date` | datetime | SYSTEM | Email received date |
| `attachment_name` | string | SYSTEM | PDF filename |
| `attachment_hash` | string | IMMUTABLE | SHA256 of attachment |

### 2. Vehicle Information

| Column | Type | Class | Description |
|--------|------|-------|-------------|
| `vin_base` | string | SYSTEM | VIN from parser |
| `vin_override` | string | USER | Manual VIN correction |
| `vin_final` | string | SYSTEM | Final VIN for export |
| `year_base` | integer | SYSTEM | Year from parser |
| `year_override` | integer | USER | Manual year |
| `year_final` | integer | SYSTEM | Final year |
| `make_base` | string | SYSTEM | Make from parser |
| `make_override` | string | USER | Manual make |
| `make_final` | string | SYSTEM | Final make |
| `model_base` | string | SYSTEM | Model from parser |
| `model_override` | string | USER | Manual model |
| `model_final` | string | SYSTEM | Final model |
| `vehicle_type_base` | enum | SYSTEM | car/suv/truck/van/motorcycle/other |
| `vehicle_type_override` | enum | USER | Manual type |
| `vehicle_type_final` | enum | SYSTEM | Final type |
| `running_base` | enum | SYSTEM | yes/no/unknown |
| `running_override` | enum | USER | Manual running status |
| `running_final` | enum | SYSTEM | Final running status |
| `mileage_base` | integer | SYSTEM | Mileage from parser |
| `mileage_override` | integer | USER | Manual mileage |
| `mileage_final` | integer | SYSTEM | Final mileage |
| `color_base` | string | SYSTEM | Color from parser |
| `color_override` | string | USER | Manual color |
| `color_final` | string | SYSTEM | Final color |

### 3. Pickup Location

| Column | Type | Class | Description |
|--------|------|-------|-------------|
| `pickup_address1_base` | string | SYSTEM | Street address from parser |
| `pickup_address1_override` | string | USER | Manual address |
| `pickup_address1_final` | string | SYSTEM | Final address |
| `pickup_city_base` | string | SYSTEM | City from parser |
| `pickup_city_override` | string | USER | Manual city |
| `pickup_city_final` | string | SYSTEM | Final city |
| `pickup_state_base` | string | SYSTEM | State from parser |
| `pickup_state_override` | string | USER | Manual state |
| `pickup_state_final` | string | SYSTEM | Final state |
| `pickup_zip_base` | string | SYSTEM | ZIP from parser |
| `pickup_zip_override` | string | USER | Manual ZIP |
| `pickup_zip_final` | string | SYSTEM | Final ZIP |
| `pickup_contact_base` | string | SYSTEM | Contact from parser |
| `pickup_contact_override` | string | USER | Manual contact |
| `pickup_contact_final` | string | SYSTEM | Final contact |
| `pickup_phone_base` | string | SYSTEM | Phone from parser |
| `pickup_phone_override` | string | USER | Manual phone |
| `pickup_phone_final` | string | SYSTEM | Final phone |

### 4. Delivery / Warehouse

| Column | Type | Class | Description |
|--------|------|-------|-------------|
| `warehouse_id_base` | string | SYSTEM | Auto-suggested warehouse |
| `warehouse_id_override` | string | USER | Manual warehouse selection |
| `warehouse_id_final` | string | SYSTEM | Final warehouse ID |
| `warehouse_name_final` | string | SYSTEM | Warehouse name (lookup) |
| `delivery_address1_final` | string | SYSTEM | From warehouse data |
| `delivery_city_final` | string | SYSTEM | From warehouse data |
| `delivery_state_final` | string | SYSTEM | From warehouse data |
| `delivery_zip_final` | string | SYSTEM | From warehouse data |
| `delivery_contact_final` | string | SYSTEM | From warehouse data |
| `delivery_phone_final` | string | SYSTEM | From warehouse data |

### 5. Pricing / Trailer / Dates

| Column | Type | Class | Description |
|--------|------|-------|-------------|
| `price_base` | float | SYSTEM | Calculated price |
| `price_override` | float | USER | Manual price |
| `price_final` | float | SYSTEM | Final price for CD |
| `currency` | string | SYSTEM | Always "USD" |
| `trailer_type_base` | enum | SYSTEM | open/enclosed/driveaway |
| `trailer_type_override` | enum | USER | Manual trailer type |
| `trailer_type_final` | enum | SYSTEM | Final trailer type |
| `pickup_date_base` | date | SYSTEM | Derived pickup date |
| `pickup_date_override` | date | USER | Manual pickup date |
| `pickup_date_final` | date | SYSTEM | Final pickup date |
| `delivery_date_base` | date | SYSTEM | Calculated delivery date |
| `delivery_date_override` | date | USER | Manual delivery date |
| `delivery_date_final` | date | SYSTEM | Final delivery date |

### 6. Central Dispatch Export

| Column | Type | Class | Description |
|--------|------|-------|-------------|
| `cd_export_enabled` | boolean | USER | Enable/disable CD export |
| `cd_export_status` | enum | SYSTEM | NOT_READY, READY, SENT, ERROR |
| `cd_listing_id` | string | SYSTEM | CD listing ID after export |
| `cd_last_export_at` | datetime | SYSTEM | Last export timestamp |
| `cd_last_error` | string | SYSTEM | Last error message |
| `cd_payload_json` | json | SYSTEM | Payload snapshot |
| `cd_payload_hash` | string | SYSTEM | Hash for change detection |
| `cd_fields_version` | string | SYSTEM | cd_field_mapping.yaml version |

### 7. ClickUp Export

| Column | Type | Class | Description |
|--------|------|-------|-------------|
| `clickup_task_id` | string | SYSTEM | ClickUp task ID |
| `clickup_task_url` | string | SYSTEM | ClickUp task URL |
| `clickup_status` | string | SYSTEM | Sync status |
| `clickup_last_error` | string | SYSTEM | Last error |

### 8. Quality Control / Audit

| Column | Type | Class | Description |
|--------|------|-------|-------------|
| `extraction_score` | float | SYSTEM | Confidence score 0.0-1.0 |
| `validation_errors` | json | SYSTEM | Validation errors array |
| `lock_import` | boolean | USER | Lock from import updates |
| `notes_user` | string | USER | User comments |
| `automation_version` | string | SYSTEM | Automation version tag |

---

## Upsert Behavior

### On CREATE (new pickup_uid)

All columns are set:
- IMMUTABLE columns: set once
- SYSTEM columns: set from parser
- USER columns: set to defaults (status=NEW, lock_import=FALSE, etc.)
- *_final columns: computed as base (no overrides yet)

### On UPDATE (existing pickup_uid)

Only specific columns are updated:
- IMMUTABLE columns: **never updated**
- USER columns: **never updated** (preserves manual edits)
- SYSTEM columns (non-computed): updated with new parser data
- *_final columns: recomputed using existing overrides

### Locked Rows (lock_import=TRUE)

When a row is locked:
- Only `last_ingested_at` is updated
- All other columns preserved
- Log message: "skipped due to lock"

---

## API Usage

### Writing Data (Ingest)

```python
from services.sheets_exporter import SheetsExporter
from core.config import load_config_from_env

config = load_config_from_env()
exporter = SheetsExporter(config.sheets)

# Single record upsert
result = exporter.upsert_record({
    "auction": "COPART",
    "vin": "1HGBH41JXMN109186",
    "gate_pass": "ABC123",
    "pickup_city": "Dallas",
    "pickup_state": "TX",
    "extraction_score": 0.85,
})
# result = {"action": "created", "pickup_uid": "a1b2c3d4e5f6g7h8", ...}

# Batch upsert
results = exporter.upsert_batch(records)
# results = {"created": 5, "updated": 3, "skipped": 1, "results": [...]}
```

### Reading Data (CD Export)

```python
from services.sheets_source import SheetsSource

source = SheetsSource(config.sheets)

# Get rows ready for CD export
ready = source.list_ready_for_cd()
for pickup in ready:
    payload = pickup.to_cd_payload()
    # Send to CD API...
    source.update_cd_export_result(
        pickup_uid=pickup.pickup_uid,
        success=True,
        listing_id="CD-12345",
        payload_json=json.dumps(payload),
    )
```

---

## Migration Notes

### From Schema v0 (append-only)

1. Add new columns to existing sheet
2. Run migration script to compute `pickup_uid` for existing rows
3. Deploy new code with upsert mode

### Future Schema Changes

Any column additions/changes require:
1. Update `schemas/sheets_schema_v1.py`
2. Increment SCHEMA_VERSION
3. Create migration script if needed
4. Update this documentation

---

## Acceptance Criteria

1. **No duplicates on re-import**: Same PDF creates same pickup_uid, updates existing row
2. **Override preservation**: User edits in *_override columns are never lost
3. **Final value computation**: Changes to override immediately reflect in *_final
4. **Lock protection**: lock_import=TRUE prevents all updates except timestamp
5. **Batch efficiency**: Multiple records use batchUpdate API
