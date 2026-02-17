# Y7Dispatch Week 3: CD-Aligned Review UI + Business Logic

Based on completed CD_FIELD_CONFIG with all business rules confirmed by Product Owner.

---

## DAY 10: Review Page Restructure + Load ID + Manheim Logic

### Context
The Review page currently shows 26+ extracted fields in a flat list. 
It must be restructured to mirror the Central Dispatch "Create Listing" form layout.
Internal-only fields (seller_name, sale_price, total_amount, order_id) should be 
moved to a collapsible "Document Details" section at the bottom.

### Step 1: Review.jsx — New Layout Structure

Restructure web/src/pages/Review.jsx into these sections (matching CD form):

```
1. EXTRACTION INFO BAR (top)
   - Document name, auction type badge (COPART/IAA/MANHEIM)  
   - Extraction method badge (Claude Haiku / Zone Fallback)
   - Extraction cost, confidence score

2. VEHICLE INFORMATION (extracted, editable)
   - VIN (readonly after extraction, verified)
   - Year, Make, Model (extracted, editable)
   - Color (extracted, editable, optional)
   - Lot Number (extracted, editable)
   - Vehicle Type: DEFAULT "CAR" — note: "CD auto-detects from VIN"
   - Inoperable toggle (extracted, default false)
   - Trailer Type dropdown: OPEN (default) / ENCLOSED / DRIVEAWAY

3. PICK-UP LOCATION (extracted, editable)
   - Location Name (extracted: "Copart Riverview")
   - Address, City, State, ZIP (extracted)
   - Phone (extracted if available, manual if not)
   - Location Type dropdown: AUCTION (default) / DEALERSHIP / RESIDENCE / BUSINESS
   - Buyer Reference Number (extracted: buyer_id)
   - Contact Name (manual, optional)

4. DELIVERY LOCATION (from warehouse selector)
   - Warehouse dropdown (populated from GET /api/settings/warehouses)
   - When selected: auto-fill name, address, city, state, zip, phone, contact
   - Location Type: from warehouse record
   - Manual override option: "Enter address manually"

5. DATES
   - Date Available to Ship: 
     * Default: today
     * If Manheim + release date extracted: use that date
     * If Manheim + NO ONSITE VEHICLE RELEASE: show WARNING banner
     * Editable date picker
   - Expiration Date: auto = available + 30 days (readonly, auto-calculated)
   - Desired Delivery Date: empty by default, optional date picker

6. PRICING AND PAYMENT
   - Amount to Pay Carrier: from PricingEngine suggested_price
     * Show CD Price Check Plus result alongside (if available)
     * Final price input (editable)
   - COP/COD Amount: default 0.00 (editable)
   - COP/COD Payment Method: CASH_CERTIFIED_FUNDS (if COD > 0)
   - COP/COD Location: DELIVERY (if COD > 0)
   - Balance Amount: auto = total - COD (readonly)
   - Balance Payment Method: CERTIFIED_FUNDS (default, dropdown)
   - Balance Payment Time: 2_BUSINESS_DAYS (default, dropdown)
   - Balance Terms Begin On: RECEIVING_SIGNED_BOL (default, dropdown)

7. ADDITIONAL INFO
   - Your Load ID: auto-generated, readonly but copyable
     * Algorithm: M(no leading zero) + DD + first 3 Make + first 2 Model + seq
     * Example: 216TOYPR (Feb 16, Toyota Prius, first today)
     * If duplicate today: 216TOYPR2
   - Gate Pass: extracted from email (if available), goes to additionalInfo
   - Additional Vehicle Information: Gate Pass auto-filled, editable
   - Load-Specific Terms: template auto-filled, editable
     * Template: "TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY). 
       Pick-up location - {pickup_name}, Delivery - {warehouse_name}"
   - Transport Special Instructions: from warehouse record, editable
   - Request carrier use CD App: checkbox, default CHECKED

8. DOCUMENT DETAILS (collapsible, internal reference only — NOT sent to CD)
   - Buyer Name, Buyer ID (internal)
   - Seller Name, Seller ID
   - Sale Date, Sale Price, Total Amount
   - Order ID, Reference ID
   - Raw extraction data

9. EXPORT ACTIONS (bottom)
   - Preflight check summary (X fields ready, Y need review)
   - "Export to Central Dispatch" button
   - "Save to Google Sheets" button
   - Export Preview Modal (existing)
```

### Step 2: Load ID Algorithm

Create utility function in services/ or api/routes/:

```python
def generate_load_id(make: str, model: str, date: datetime = None) -> str:
    """
    Generate CD Load ID.
    Format: MDD + first 3 chars Make + first 2 chars Model + sequence
    Example: 216TOYPR (Feb 16, Toyota Prius)
    If duplicate exists today: 216TOYPR2
    
    Rules:
    - Month: no leading zero (2 not 02)
    - Day: always 2 digits (01-31)
    - Make: first 3 uppercase letters
    - Model: first 2 uppercase letters  
    - Sequence: none for first, 2 for second, 3 for third
    """
```

Backend: GET /api/listings/generate-load-id?make=Toyota&model=Prius
- Check DB for existing load IDs today with same prefix
- Return next available ID

### Step 3: Manheim Release Date Extraction

In services/haiku_extractor.py EXTRACTION_PROMPT, add instruction:

```
For MANHEIM documents:
- Look for "ONSITE VEHICLE RELEASE" section
- If found, check for "Vehicle is releasable on [Month DD, YYYY] at [time] [timezone]"
  Extract as: manheim_release_date (ISO format)
- If ONSITE VEHICLE RELEASE section exists but NO release date mentioned:
  Set manheim_release_date = "AVAILABLE_NOW"  
- If NO "ONSITE VEHICLE RELEASE" section at all:
  Set manheim_release_date = "NO_RELEASE_DOCUMENT"
  (This triggers a warning in UI: "No Onsite Vehicle Release found")

- If document says "This vehicle is not located at a Manheim facility":
  Set manheim_offsite = true
  Extract the offsite address separately as offsite_address, offsite_city, offsite_state, offsite_zip
```

### Step 4: Inoperable Detection Enhancement

In EXTRACTION_PROMPT, add:
```
For vehicle_is_inoperable:
- Default: false (OPERABLE)
- Set true if document contains: "INOP", "INOPERABLE", "NON-RUNNING", "NON-RUN"  
- Set false if: "RUN AND DRIVE", "RUNS AND DRIVES", "OPERABLE"
- Note: Copart/IAA emails may have a second attachment (condition report)
  with this info in the filename. Check for "RUN_AND_DRIVE" in filename patterns.
```

### Step 5: Tests

File: tests/e2e/test_review_ui_logic.py
- test_load_id_generation: basic, duplicate, edge cases
- test_load_id_sequence: multiple same vehicle in one day
- test_manheim_release_date_parsing: with date, AVAILABLE_NOW, NO_RELEASE_DOCUMENT
- test_load_specific_terms_template: variable substitution
- test_default_payment_fields: COD=0, balance=total, certified funds, 2 biz days, BOL

### Step 6: Commit

```
feat: Review page restructure — CD-aligned layout, Load ID algorithm, Manheim release logic
```

---

## DAY 11: Warehouse Management + Delivery Integration + Copart Directory

### Context
Delivery address comes from warehouse database (Settings > Warehouses).
The warehouse system already exists in the app but needs to be verified 
and integrated into the Review page delivery section.
Also: Copart location phone directory needed for pickup_phone.

### Step 1: Verify Warehouse System

Check existing warehouse implementation:
- api/routes/settings.py or warehouses.py — CRUD endpoints
- Database table schema
- Frontend WarehouseTab in Settings

Required warehouse fields for CD export:
- id, name, address, city, state, zip, country (US)
- phone, contact_name, contact_phone
- location_type (Dealership/Business/Residence)
- transport_special_instructions (work schedule, appointment info)
- is_default (boolean — default delivery location)

### Step 2: Copart/IAA Phone Directory

Create a reference table or JSON file with auction location phone numbers:

```python
# services/auction_directory.py
COPART_LOCATIONS = {
    "Copart Riverview": {"phone": "(813) 671-3846", "address": "12020 US Highway 301 South", ...},
    "Copart Littleton": {"phone": "(303) 791-1001", "address": "8300 Blakeland Drive", ...},
    # ... populate from Copart website or known locations
}
```

When extraction returns pickup_name like "Copart Riverview" but no phone:
- Auto-fill phone from directory
- Mark as "from directory" (not extracted)

### Step 3: Wire Warehouse to Review Page

In Review.jsx delivery section:
- GET /api/settings/warehouses → populate dropdown
- On select → fill all delivery fields
- Allow manual override
- Save selected warehouse_id with the run

### Step 4: Wire Transport Special Instructions

When warehouse selected:
- Auto-fill transportationReleaseNotes from warehouse.transport_special_instructions
- Editable by operator

### Step 5: Tests + Commit

```
feat: Warehouse delivery integration, Copart phone directory, transport instructions
```

---

## DAY 12: Export Pipeline — CD API V2 Payload Builder + Google Sheets Sync

### Context
Build the actual CD API V2 payload from Review page data.
Also update Google Sheets export to match the new field structure.

### Step 1: CD Listing Payload Builder

Create services/cd_payload_builder.py:

```python
def build_cd_listing_payload(run_data: dict, warehouse: dict, operator_overrides: dict) -> dict:
    """
    Build Central Dispatch Listings API V2 payload.
    
    Maps our internal fields to CD API schema:
    - stops[0] = pickup (from extraction)
    - stops[1] = delivery (from warehouse)
    - vehicles[0] = vehicle info (from extraction)
    - price = from PricingEngine + operator
    - dates = available/expiration/desired delivery
    """
    return {
        "trailerType": operator_overrides.get("trailer_type", "OPEN"),
        "hasInOpVehicle": run_data.get("vehicle_is_inoperable", False),
        "availableDate": ...,  # ISO 8601
        "expirationDate": ...,  # available + 30 days
        "externalId": run_data.get("load_id"),
        "requiresInspection": operator_overrides.get("requires_inspection", True),
        "loadSpecificTerms": operator_overrides.get("load_specific_terms", template),
        "transportationReleaseNotes": warehouse.get("transport_special_instructions", ""),
        "price": {
            "total": operator_overrides["final_price"],
            "cod": {
                "amount": operator_overrides.get("cod_amount", 0),
                "paymentMethod": "CASH_CERTIFIED_FUNDS",
                "paymentLocation": "DELIVERY"
            },
            "balance": {
                "amount": operator_overrides["final_price"] - operator_overrides.get("cod_amount", 0),
                "paymentMethod": "CERTIFIED_FUNDS",
                "paymentTime": "2_BUSINESS_DAYS",  
                "balancePaymentTermsBeginOn": "RECEIVING_SIGNED_BOL"
            }
        },
        "stops": [
            {  # Pickup
                "stopNumber": 1,
                "locationName": run_data.get("pickup_name"),
                "address": run_data.get("pickup_address"),
                "city": run_data.get("pickup_city"),
                "state": run_data.get("pickup_state"),
                "postalCode": run_data.get("pickup_zip"),
                "country": "US",
                "phone": run_data.get("pickup_phone"),
                "locationType": run_data.get("pickup_location_type", "Auction"),
                "buyerReferenceNumber": run_data.get("buyer_id")
            },
            {  # Delivery
                "stopNumber": 2,
                "locationName": warehouse["name"],
                "address": warehouse["address"],
                "city": warehouse["city"],
                "state": warehouse["state"],
                "postalCode": warehouse["zip"],
                "country": "US",
                "phone": warehouse.get("phone"),
                "contactName": warehouse.get("contact_name"),
                "locationType": warehouse.get("location_type", "Business")
            }
        ],
        "vehicles": [{
            "pickupStopNumber": 1,
            "dropoffStopNumber": 2,
            "vin": run_data["vehicle_vin"],
            "year": int(run_data["vehicle_year"]),
            "make": run_data["vehicle_make"],
            "model": run_data["vehicle_model"],
            "vehicleType": run_data.get("vehicle_type", "CAR"),
            "color": run_data.get("vehicle_color"),
            "lotNumber": run_data.get("vehicle_lot"),
            "isInoperable": run_data.get("vehicle_is_inoperable", False),
            "additionalInfo": build_additional_info(run_data)
        }],
        "marketplaces": [{"marketplaceId": 10000, "searchable": True}]
    }
```

### Step 2: Update Export Endpoint

Modify POST /api/exports/central-dispatch:
- Accept operator overrides (trailer_type, final_price, warehouse_id, etc.)
- Call build_cd_listing_payload()
- Send to CD API V2: POST https://marketplace-api.centraldispatch.com/listings
- Store CD listing ID in DB
- Return success with listing URL

### Step 3: Update Google Sheets Export

Update services/sheets_exporter.py columns to match CD_FIELD_CONFIG:
- Remove: seller_name, seller_id, sale_price, order_id (internal only)
- Add: trailer_type, available_date, load_id, warehouse_name, delivery_city/state/zip
- Add: final_price, cod_amount, balance_amount, payment_method
- Add: cd_listing_id, export_status, extraction_method
- Column order matches CD_FIELD_CONFIG Google Sheets section

### Step 4: Export Preview Modal Update

Update ExportPreviewModal.jsx:
- Show CD API payload preview (formatted JSON)
- Group by: Vehicle Info | Pickup | Delivery | Dates | Pricing
- Highlight required fields that are missing
- Show "Dry Run" option (validate without posting)

### Step 5: Tests + Commit

- test_cd_payload_builder: verify all field mappings
- test_load_specific_terms_template: variable substitution
- test_sheets_export_columns: verify new column layout
- test_export_with_warehouse: end-to-end with warehouse selection

```
feat: CD API V2 payload builder, updated Sheets export, export flow
```

---

## Implementation Notes

### Load ID Algorithm Detail
```
Input: make="Mitsubishi", model="Outlander", date=2026-02-16
Step 1: month = 2 (no leading zero)
Step 2: day = 16 
Step 3: make_prefix = "MIT" (first 3 uppercase)
Step 4: model_prefix = "OU" (first 2 uppercase)
Step 5: base = "216MITOU"
Step 6: check DB for today's load IDs starting with "216MITOU"
Step 7: if none found → return "216MITOU"
         if "216MITOU" exists → return "216MITOU2"
         if "216MITOU2" exists → return "216MITOU3"
```

### Manheim Release Date Patterns
```
Pattern 1: "Vehicle is releasable on Feb 03, 2026 at 12:00 CST"
Pattern 2: "Vehicle is releasable on January 15, 2026 at 08:00 EST"  
Pattern 3: "Vehicle Not Available for Release.\nVehicle is releasable on..."
Action: Parse → ISO date → set as availableDate

No date but ONSITE VEHICLE RELEASE present:
Action: availableDate = today

No ONSITE VEHICLE RELEASE section at all:
Action: WARNING "NO ONSITE VEHICLE RELEASE" → operator must call seller
```

### Load-Specific Terms Template
```
"TEXT 857-895-8777 (ZELLE AVAILABLE THE DAY AFTER DELIVERY). Pick-up location - {pickup_name}, Delivery - {warehouse_name}"

Variables:
- {pickup_name} = extracted pickup location name
- {warehouse_name} = selected warehouse name
```

### Price Display
```
Show two price sources side by side:
1. CD Price Check Plus (from CD Market Intelligence API if subscribed)
2. Our PricingEngine (avg_dispatch + spread calculation)

If either fails → show the other + warning
If both fail → MANUAL_REQUIRED
Never block listing creation due to price error
```
