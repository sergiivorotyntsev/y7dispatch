# Technical Specification v2.0 - Central Dispatch Integration

> Detailed requirements based on user feedback (2026-02-06)

---

## Table of Contents

1. [Block 1: CD API Field Mapping Corrections](#block-1-cd-api-field-mapping-corrections)
2. [Block 2: Location Type Enum](#block-2-location-type-enum)
3. [Block 3: Vehicle Fields](#block-3-vehicle-fields)
4. [Block 4: Trailer Type Options](#block-4-trailer-type-options)
5. [Block 5: Pricing & Payment](#block-5-pricing--payment)
6. [Block 6: Warehouse Model Enhancement](#block-6-warehouse-model-enhancement)
7. [Block 7: Broker Reference Data](#block-7-broker-reference-data)
8. [Block 8: Documents List UI](#block-8-documents-list-ui)
9. [Block 9: Field Configuration UI](#block-9-field-configuration-ui)
10. [Block 10: State-First Selection](#block-10-state-first-selection)

---

## Block 1: CD API Field Mapping Corrections

### Issue
Several fields are incorrectly mapped or missing in the CD API payload.

### Required Changes

| Our Field | CD API Field | Notes |
|-----------|--------------|-------|
| `operating_hours` | `stops[].notes` or `transportationReleaseNotes` | Operating hours should go to Special Instructions |
| `gate_pass` | `vehicles[].additionalInfo` | Gate pass code for carrier reference |
| `buyer_id` | `stops[0].buyerNumber` | Buyer reference number at pickup |
| `lot_number` | `vehicles[].lotNumber` | Unified field (extracts "Lot Number" from Copart, "Stock Number" from IAA) |

### Files to Modify
- `api/listing_fields.py` - Update field definitions
- `api/listing_fields.py:build_cd_payload()` - Update payload builder

---

## Block 2: Location Type Enum

### CD API Location Types
Based on Central Dispatch API documentation:

```python
LOCATION_TYPES = [
    "RESIDENCE",
    "BUSINESS",
    "DEALER",
    "AUCTION",
    "PORT",
    "STORAGE_FACILITY",
    "BODY_SHOP",
    "CROSS_DOCK",  # Cross-dock or satellite/staging lot
    "OTHER"
]
```

### Default Values
- **Pickup (stops[0])**: `AUCTION` (always, for auction documents)
- **Delivery (stops[1])**: `CROSS_DOCK` (warehouse default) or `BUSINESS`

### Files to Modify
- `api/listing_fields.py` - Add `pickup_location_type`, `delivery_location_type` fields
- `api/routes/warehouses.py` - Add `location_type` to warehouse model

---

## Block 3: Vehicle Fields

### Lot Number / Stock Number Unification

**Problem**: Currently two separate fields (`vehicle_lot`, `stock_number`)

**Solution**: Single `vehicle_lot` field with multi-pattern extraction:
- Copart pattern: `LOT\s*#?\s*:\s*(\d+)`
- IAA pattern: `STOCK\s*#?\s*:\s*(\w+)`

### Additional Vehicle Information
Gate Pass should map to `vehicles[].additionalInfo` in CD API:

```python
# In build_cd_payload()
vehicle = {
    ...
    "additionalInfo": gate_pass_value  # For carrier reference
}
```

### Files to Modify
- `api/listing_fields.py` - Remove `stock_number`, keep `vehicle_lot` with expanded extraction hints
- `extractors/copart.py`, `extractors/iaa.py` - Both extract to `vehicle_lot`

---

## Block 4: Trailer Type Options

### Current Options
```python
options=["OPEN", "ENCLOSED"]
```

### Required Options
```python
options=["OPEN", "ENCLOSED", "DRIVEAWAY"]
```

### Default Value
- Default: `OPEN`
- Auto-select `ENCLOSED` for luxury makes (BMW, Mercedes, Porsche, etc.)

### Files to Modify
- `api/listing_fields.py` - Add DRIVEAWAY option
- `cd_defaults.yaml` - Update rules

---

## Block 5: Pricing & Payment

### Market Intelligence API Integration

**Endpoint**: `POST /market-intelligence/rates`

**Request**:
```json
{
  "pickupLocation": {
    "city": "HASLET",
    "state": "TX",
    "postalCode": "76052"
  },
  "deliveryLocation": {
    "city": "HOUSTON",
    "state": "TX",
    "postalCode": "77001"
  },
  "vehicleType": "SEDAN",
  "trailerType": "OPEN"
}
```

**Response**:
```json
{
  "estimatedPrice": {
    "low": 350.00,
    "average": 425.00,
    "high": 500.00
  }
}
```

### Payment Fields (New)

| Field | CD API Key | Type | Default |
|-------|-----------|------|---------|
| `balance_payment_method` | `price.balance.balancePaymentMethod` | SELECT | `CERTIFIED_FUNDS` |
| `balance_payment_time` | `price.balance.paymentTime` | SELECT | `2_BUSINESS_DAYS_QUICK_PAY` |
| `balance_terms_begin_on` | `price.balance.balancePaymentTermsBeginOn` | SELECT | `RECEIVING_SIGNED_BOL` |

### Balance Payment Method Options
```python
BALANCE_PAYMENT_METHODS = [
    "CASH",
    "CHECK",
    "CERTIFIED_FUNDS",
    "COMCHECK",
    "ACH",
    "COMPANY_CHECK"
]
```

### Balance Payment Time Options
```python
BALANCE_PAYMENT_TIMES = [
    "IMMEDIATELY",
    "2_BUSINESS_DAYS_QUICK_PAY",
    "5_BUSINESS_DAYS",
    "15_BUSINESS_DAYS",
    "30_BUSINESS_DAYS"
]
```

### Balance Terms Begin On Options
```python
BALANCE_TERMS_BEGIN_ON = [
    "RECEIVING_SIGNED_BOL",
    "VEHICLE_PICKUP",
    "VEHICLE_DELIVERY"
]
```

### Files to Modify
- `api/listing_fields.py` - Add payment fields
- `api/cd_market_intelligence.py` - New file for Market Intelligence API client
- `api/routes/exports.py` - Integrate pricing lookup

---

## Block 6: Warehouse Model Enhancement

### Current Model
```python
@dataclass
class Warehouse:
    id: int
    code: str
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    is_active: bool
```

### Enhanced Model
```python
@dataclass
class Warehouse:
    id: int
    code: str
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    country: str = "US"

    # New fields
    location_type: str = "CROSS_DOCK"  # CD API location type
    buyer_reference: str = ""  # Default: broker code (e.g., "DAYTONACARGO")
    email: str = ""
    contact_phone: str = ""
    contact_name: str = ""
    operating_hours: str = ""

    # Broker relationship
    broker_id: Optional[int] = None  # FK to brokers table

    is_active: bool = True
    is_default: bool = False
```

### Database Migration
```sql
ALTER TABLE warehouses ADD COLUMN location_type TEXT DEFAULT 'CROSS_DOCK';
ALTER TABLE warehouses ADD COLUMN buyer_reference TEXT DEFAULT '';
ALTER TABLE warehouses ADD COLUMN email TEXT DEFAULT '';
ALTER TABLE warehouses ADD COLUMN contact_phone TEXT DEFAULT '';
ALTER TABLE warehouses ADD COLUMN contact_name TEXT DEFAULT '';
ALTER TABLE warehouses ADD COLUMN operating_hours TEXT DEFAULT '';
ALTER TABLE warehouses ADD COLUMN broker_id INTEGER REFERENCES brokers(id);
```

### Files to Modify
- `api/routes/warehouses.py` - Extend schema and routes
- `api/routes/settings.py` - Update WarehouseConfig model

---

## Block 7: Broker Reference Data

### New Broker Model
```python
@dataclass
class Broker:
    id: int
    code: str  # e.g., "DAYTONACARGO", "TRT"
    name: str  # e.g., "Daytona Cargo", "TRT Logistics"
    is_active: bool = True
    created_at: Optional[str] = None
```

### Broker-Warehouse Relationship
- One broker can have multiple warehouses in different states
- Example: TRT has warehouses in TX, GA, CA

### UI Flow
1. User selects destination **State** (dropdown)
2. System shows available **Brokers** with warehouses in that state
3. User selects **Broker**
4. System shows available **Warehouse addresses** for that broker in that state

### Files to Create
- `api/brokers.py` - Broker model and repository

### Files to Modify
- `api/routes/warehouses.py` - Add broker relationship
- `api/main.py` - Initialize brokers table

---

## Block 8: Documents List UI

### Current Columns
- Filename
- Auction Type
- Status
- Created At

### Required Columns
| Column | Source | Format |
|--------|--------|--------|
| Order ID | Extracted `order_id` | `MMDD-MAKE-SEQ` |
| Upload Date/Time | `created_at` | `YYYY-MM-DD HH:MM` |
| Pickup Location | Extracted | `{State} {ZIP}` |
| Delivery Warehouse | Selected warehouse | `{Name} ({State})` |
| Price | `price_total` | `$XXX.XX` |
| Status | Status + validation | Badge with color |
| Actions | - | Edit Price, Select Warehouse, Export to CD |

### Inline Editing
- **Price**: Click to edit, save on blur
- **Warehouse**: Dropdown selector (state-first)
- **Export to CD**: Button (enabled when all required fields filled)

### Files to Modify
- `web/src/pages/Documents.jsx` - Update table columns
- `web/src/api.js` - Add inline update endpoints

---

## Block 9: Field Configuration UI

### Requirements
Each field should be configurable:

1. **Source Type** (how value is obtained):
   - `extracted` - From document parsing
   - `constant` - Predefined default value
   - `warehouse_ref` - From selected warehouse
   - `user_input` - Manual entry
   - `computed` - Calculated from other fields
   - `market_api` - From Market Intelligence API

2. **Default Value** (for constants):
   - If SELECT: Dropdown to choose from options
   - If TEXT/NUMBER: Input field

3. **Editable in Review**: Toggle

### UI Design
```
┌─────────────────────────────────────────────────────────────┐
│ Field: trailer_type                                          │
├─────────────────────────────────────────────────────────────┤
│ Source: [Constant ▼]                                         │
│ Default Value: [OPEN ▼]                                      │
│ ☑ Editable in Review                                        │
│ ☐ Required for Export                                        │
└─────────────────────────────────────────────────────────────┘
```

### Files to Modify
- `web/src/components/settings/FieldsTab.jsx` - Add configuration UI
- `api/routes/settings.py` - Add field config persistence endpoints

---

## Block 10: State-First Selection

### Warehouse Selection Flow

**Step 1: Select State**
```
Destination State: [TX ▼]
```

**Step 2: Select Broker (filtered by state)**
```
Available Brokers:
  [✓] TRT (3 locations in TX)
  [ ] ABC Logistics (1 location in TX)
```

**Step 3: Select Address (filtered by broker + state)**
```
Warehouse Address:
  [✓] TRT - Dallas - 1234 Commerce St, Dallas, TX 75001
  [ ] TRT - Houston - 5678 Main St, Houston, TX 77001
```

### API Endpoints

```
GET /api/warehouses/states
  Response: ["TX", "GA", "CA", "FL", ...]

GET /api/warehouses/brokers?state=TX
  Response: [
    { "id": 1, "code": "TRT", "name": "TRT Logistics", "warehouse_count": 3 },
    { "id": 2, "code": "ABC", "name": "ABC Logistics", "warehouse_count": 1 }
  ]

GET /api/warehouses?state=TX&broker_id=1
  Response: [
    { "id": 10, "name": "TRT Dallas", "address": "1234 Commerce St", ... },
    { "id": 11, "name": "TRT Houston", "address": "5678 Main St", ... }
  ]
```

### Files to Modify
- `api/routes/warehouses.py` - Add filtered endpoints
- `web/src/components/WarehouseSelector.jsx` - New component
- `web/src/pages/Documents.jsx` - Integrate selector

---

## Implementation Priority

### Phase 1: Critical Fixes (Immediate)
1. Block 1: CD API Field Mapping Corrections
2. Block 2: Location Type Enum
3. Block 4: Trailer Type DRIVEAWAY

### Phase 2: Field Enhancements
4. Block 3: Vehicle Fields
5. Block 5: Pricing & Payment (without Market Intelligence)

### Phase 3: Data Model
6. Block 6: Warehouse Model Enhancement
7. Block 7: Broker Reference Data

### Phase 4: UI Improvements
8. Block 8: Documents List UI
9. Block 9: Field Configuration UI
10. Block 10: State-First Selection

### Phase 5: API Integration
11. Market Intelligence API for pricing

---

## Testing Checklist

- [ ] Preview Payload works without errors
- [ ] Location Type shows in payload
- [ ] Gate Pass maps to additionalInfo
- [ ] Buyer ID maps to buyerNumber
- [ ] Lot/Stock Number unified
- [ ] DRIVEAWAY trailer type works
- [ ] Payment fields have correct defaults
- [ ] Warehouse model has new fields
- [ ] Broker selection works
- [ ] Documents list shows all columns
- [ ] State-first selection works
- [ ] Field configuration persists

---

*Last updated: 2026-02-06*
