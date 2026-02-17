# Central Dispatch API v2 → Y7Dispatch Field Mapping

## CD Listing API: POST /listings — Required vs Optional Fields

### TOP-LEVEL FIELDS

| CD API Field | Required | Type | Source | Our Field | Status |
|---|---|---|---|---|---|
| trailerType | ✅ default OPEN | OPEN/ENCLOSED/DRIVEAWAY | MANUAL (operator) | — | NOT EXTRACTED, needs UI dropdown |
| hasInOpVehicle | ✅ default true | boolean | EXTRACTED | vehicle_is_inoperable | ✅ HAVE |
| availableDate | ✅ REQUIRED | ISO 8601 datetime | MANUAL (operator sets) | available_date | ⚠️ MANUAL field |
| expirationDate | optional (auto 30d) | ISO 8601 datetime | AUTO (availableDate + 30d) | — | AUTO-CALCULATE |
| desiredDeliveryDate | optional | ISO 8601 datetime | MANUAL | — | NOT IN UI |
| externalId | optional ≤50 chars | string | AUTO (lot#_VIN last 6) | — | AUTO-GENERATE |
| partnerReferenceId | optional ≤50 chars | string | AUTO (reference_id) | reference_id | ✅ HAVE |
| shipperOrderId | optional ≤50 chars | string | AUTO (order_id) | order_id | ✅ HAVE |
| loadSpecificTerms | optional ≤500 chars | string | MANUAL | — | NOT IN UI |
| transportationReleaseNotes | optional | string | MANUAL | — | NOT IN UI |
| requiresInspection | optional default false | boolean | MANUAL | — | NOT IN UI |

### PRICE OBJECT (price.*)

| CD API Field | Required | Type | Source | Our Field | Status |
|---|---|---|---|---|---|
| price.total | ✅ REQUIRED | number | PricingEngine → operator override | suggested_price / final_price | ✅ HAVE |
| price.cod.amount | ✅ REQUIRED | number | OPERATOR | — | NOT IN UI — needs COP/COD section |
| price.cod.paymentMethod | ✅ REQUIRED | CASH_CERTIFIED_FUNDS / CHECK / etc | OPERATOR default | — | NOT IN UI |
| price.cod.paymentLocation | ✅ REQUIRED | PICKUP / DELIVERY | OPERATOR default | — | NOT IN UI |
| price.balance.amount | conditional | number | AUTO (total - cod) | — | AUTO-CALCULATE |
| price.balance.paymentTime | conditional | string | OPERATOR default | — | NOT IN UI |
| price.balance.paymentMethod | conditional | string | OPERATOR default | — | NOT IN UI |

### STOPS ARRAY (exactly 2 required)

**Stop 1 = Pickup (from auction document)**

| CD API Field | Required | Type | Source | Our Field | Status |
|---|---|---|---|---|---|
| stops[0].stopNumber | ✅ | always 1 | HARDCODED | — | AUTO |
| stops[0].locationName | optional | string | EXTRACTED | pickup_name | ✅ HAVE |
| stops[0].address | ✅ REQUIRED | string | EXTRACTED | pickup_address | ✅ HAVE |
| stops[0].city | ✅ REQUIRED | string | EXTRACTED | pickup_city | ✅ HAVE |
| stops[0].state | ✅ REQUIRED | string (2-letter) | EXTRACTED | pickup_state | ✅ HAVE |
| stops[0].postalCode | ✅ REQUIRED | string | EXTRACTED | pickup_zip | ✅ HAVE |
| stops[0].country | optional default US | string | HARDCODED "US" | — | AUTO |
| stops[0].phone | optional | string | EXTRACTED | pickup_phone | ⚠️ MANUAL if not in doc |
| stops[0].contactName | optional | string | MANUAL | — | NOT EXTRACTED |
| stops[0].contactPhone | optional | string | MANUAL | — | NOT EXTRACTED |
| stops[0].locationType | optional | string | EXTRACTED | pickup_location_type | ✅ HAVE |

**Stop 2 = Delivery (buyer/warehouse — NOT in auction document)**

| CD API Field | Required | Type | Source | Our Field | Status |
|---|---|---|---|---|---|
| stops[1].stopNumber | ✅ | always 2 | HARDCODED | — | AUTO |
| stops[1].locationName | optional | string | WAREHOUSE LOOKUP | delivery_name | ⚠️ from warehouse DB |
| stops[1].address | ✅ REQUIRED | string | WAREHOUSE LOOKUP | delivery_address | ⚠️ from warehouse DB |
| stops[1].city | ✅ REQUIRED | string | WAREHOUSE LOOKUP | delivery_city | ⚠️ from warehouse DB |
| stops[1].state | ✅ REQUIRED | string (2-letter) | WAREHOUSE LOOKUP | delivery_state | ⚠️ from warehouse DB |
| stops[1].postalCode | ✅ REQUIRED | string | WAREHOUSE LOOKUP | delivery_zip | ⚠️ from warehouse DB |
| stops[1].country | optional | string | HARDCODED "US" | — | AUTO |
| stops[1].phone | optional | string | WAREHOUSE LOOKUP | delivery_phone | ⚠️ from warehouse DB |
| stops[1].contactName | optional | string | WAREHOUSE LOOKUP | — | from warehouse DB |
| stops[1].contactPhone | optional | string | WAREHOUSE LOOKUP | — | from warehouse DB |

### VEHICLES ARRAY (1-12 vehicles per listing)

| CD API Field | Required | Type | Source | Our Field | Status |
|---|---|---|---|---|---|
| vehicles[0].vin | ✅ REQUIRED | string 17 chars | EXTRACTED | vehicle_vin | ✅ HAVE (100% accuracy) |
| vehicles[0].year | ✅ REQUIRED | integer | EXTRACTED | vehicle_year | ✅ HAVE (100% accuracy) |
| vehicles[0].make | ✅ REQUIRED | string | EXTRACTED | vehicle_make | ✅ HAVE (100% accuracy) |
| vehicles[0].model | ✅ REQUIRED | string | EXTRACTED | vehicle_model | ✅ HAVE (100% accuracy) |
| vehicles[0].vehicleType | ✅ REQUIRED | CAR/SUV/VAN/TRUCK/MOTORCYCLE/... | EXTRACTED | vehicle_type | ✅ HAVE |
| vehicles[0].color | optional | string | EXTRACTED | vehicle_color | ✅ HAVE |
| vehicles[0].lotNumber | optional | string | EXTRACTED | vehicle_lot | ✅ HAVE |
| vehicles[0].licensePlate | optional | string | NOT EXTRACTED | — | NOT IN DOC |
| vehicles[0].isInoperable | optional | boolean | EXTRACTED | vehicle_is_inoperable | ✅ HAVE |
| vehicles[0].tariff | optional | number | NOT USED | — | SKIP |
| vehicles[0].additionalInfo | optional ≤500 | string | MANUAL | — | NOT IN UI |
| vehicles[0].pickupStopNumber | ✅ | always 1 | HARDCODED | — | AUTO |
| vehicles[0].dropoffStopNumber | ✅ | always 2 | HARDCODED | — | AUTO |
| vehicles[0].externalVehicleId | optional | string | AUTO (VIN) | — | AUTO |
| vehicles[0].trim | optional | string | NOT EXTRACTED | — | SKIP |
| vehicles[0].shippingSpecs | optional | object (h/w/l/weight) | NOT EXTRACTED | — | SKIP |

---

## FIELD CATEGORIES FOR UI

### 1. EXTRACTED FROM DOCUMENT (Haiku reads from PDF)
These fields appear on Review page after upload, operator can correct if wrong:

- vehicle_vin ✅
- vehicle_year ✅
- vehicle_make ✅
- vehicle_model ✅
- vehicle_type ✅
- vehicle_color ✅
- vehicle_lot ✅
- vehicle_is_inoperable ✅
- pickup_name ✅
- pickup_address ✅
- pickup_city ✅
- pickup_state ✅
- pickup_zip ✅
- pickup_location_type ✅
- buyer_id ✅ (internal ref, not for CD)
- buyer_name ✅ (internal ref, not for CD)
- seller_name ✅ (internal ref, not for CD)
- sale_date ✅ (internal ref, not for CD)
- total_amount ✅ (purchase price, not transport price)

### 2. OPERATOR-SET FIELDS (Manual input in UI before export)
These fields are NOT in the auction document — operator must set them:

- trailerType: OPEN / ENCLOSED / DRIVEAWAY (dropdown)
- availableDate: when vehicle ready to ship (date picker)
- price.total: transport price from PricingEngine or manual
- price.cod.amount: how much carrier gets paid
- price.cod.paymentMethod: CASH_CERTIFIED_FUNDS / CHECK
- price.cod.paymentLocation: PICKUP / DELIVERY

### 3. WAREHOUSE/DELIVERY (from warehouse database)
Delivery address comes from warehouse settings, not from document:

- delivery_name (warehouse name)
- delivery_address, city, state, zip (warehouse address)
- delivery_phone, delivery_contact (warehouse contact)

### 4. AUTO-GENERATED (system fills in)
- externalId: auto-generate from lot + VIN
- partnerReferenceId: from reference_id or auto
- stops[0].stopNumber: always 1
- stops[1].stopNumber: always 2
- vehicles[0].pickupStopNumber: always 1
- vehicles[0].dropoffStopNumber: always 2
- country: always "US"
- expirationDate: availableDate + 30 days

### 5. NOT NEEDED — Remove from UI
These extracted fields are internal reference only, NOT sent to CD API:

- buyer_id (our internal Copart member number)
- buyer_name (our company name — already in CD account)
- buyer_address (our address — not needed)
- seller_name (insurance company — not for CD)
- seller_id (Copart seller code)
- sale_date (auction sale date, not ship date)
- sale_price (what we paid at auction, not transport price)
- total_amount (purchase cost, not transport price)
- order_id (Copart order number)
- reference_id (can map to externalId)
- pickup_phone (rarely in doc, usually manual)
- gate_pass (internal auction use only)

---

## GOOGLE SHEETS COLUMNS (for operator review)

| Column | Source | Editable | Purpose |
|---|---|---|---|
| A: Document | AUTO | No | filename |
| B: Auction | EXTRACTED | No | COPART/IAA/MANHEIM |
| C: VIN | EXTRACTED | Yes | 17 chars |
| D: Year | EXTRACTED | Yes | 4 digits |
| E: Make | EXTRACTED | Yes | Toyota, Ford, etc |
| F: Model | EXTRACTED | Yes | Camry, Edge, etc |
| G: Color | EXTRACTED | Yes | optional |
| H: Vehicle Type | EXTRACTED | Yes | CAR/SUV/VAN/TRUCK |
| I: Lot Number | EXTRACTED | Yes | auction lot# |
| J: Inoperable | EXTRACTED | Yes | TRUE/FALSE |
| K: Pickup Name | EXTRACTED | Yes | Copart Riverview |
| L: Pickup Address | EXTRACTED | Yes | 12020 US Highway 301 |
| M: Pickup City | EXTRACTED | Yes | Riverview |
| N: Pickup State | EXTRACTED | Yes | FL |
| O: Pickup ZIP | EXTRACTED | Yes | 33578 |
| P: Pickup Type | EXTRACTED | Yes | AUCTION/DEALER |
| Q: Trailer Type | OPERATOR | Yes | OPEN/ENCLOSED |
| R: Available Date | OPERATOR | Yes | MM/DD/YYYY |
| S: Delivery Name | WAREHOUSE | Yes | warehouse name |
| T: Delivery Address | WAREHOUSE | Yes | warehouse address |
| U: Delivery City | WAREHOUSE | Yes | warehouse city |
| V: Delivery State | WAREHOUSE | Yes | warehouse state |
| W: Delivery ZIP | WAREHOUSE | Yes | warehouse zip |
| X: Suggested Price | SYSTEM | No | from PricingEngine |
| Y: Final Price | OPERATOR | Yes | override or accept |
| Z: Price Source | SYSTEM | No | CD_MARKET_INTEL/MANUAL |
| AA: COD Amount | OPERATOR | Yes | carrier payment |
| AB: COD Method | OPERATOR | Yes | CASH/CHECK |
| AC: Status | SYSTEM | No | DRAFT/READY/EXPORTED |
| AD: CD Listing ID | SYSTEM | No | after export |
| AE: Extraction Method | SYSTEM | No | haiku/zone_fallback |
| AF: Notes | OPERATOR | Yes | free text |

---

## WHAT TO FIX IN UI

### Remove from Review page (internal data, not for CD):
- buyer_id, buyer_name, buyer_address
- seller_name, seller_id
- sale_date, sale_price, total_amount (purchase price)
- order_id, gate_pass

### Add to Review page (required for CD export):
- Trailer Type dropdown (OPEN/ENCLOSED/DRIVEAWAY)
- Available Date picker
- Delivery section (from warehouse or manual input)
- COD/Payment section (amount, method, location)

### Keep on Review page (extracted, editable):
- VIN, Year, Make, Model, Color, Type
- Lot Number, Inoperable
- Pickup: Name, Address, City, State, ZIP, Type
- Pricing section (already built Day 9)
