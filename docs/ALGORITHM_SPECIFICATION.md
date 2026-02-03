# Vehicle Transport Document Processing - Algorithm Specification

**Version:** 1.0
**Date:** 2026-02-02
**Status:** For Product Owner Review

---

## 1. System Overview

The system automates creation of vehicle transport listings in Central Dispatch from auction documents (PDFs). It extracts data from documents, allows review/correction, learns from corrections, and exports to Central Dispatch API.

### 1.1 Key Modules

| Module | Purpose |
|--------|---------|
| **Documents** | Production workflow - upload, extract, review, export to CD |
| **Test Lab** | Training environment - upload samples, correct fields, train model |
| **Warehouses** | Delivery location configuration |
| **Settings** | API integrations configuration |

---

## 2. Document Processing Flow

### 2.1 Two Separate Workflows

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PRODUCTION WORKFLOW (Documents)                   │
├─────────────────────────────────────────────────────────────────────┤
│  Upload PDF → Auto-Extract → Review & Edit → Select Warehouse →     │
│  Preview Listing → Export to Central Dispatch                       │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                    TRAINING WORKFLOW (Test Lab)                      │
├─────────────────────────────────────────────────────────────────────┤
│  Upload PDF → Auto-Extract → Review & Correct → Save Corrections →  │
│  Update Training Data → Retrain Model                               │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Workflow Differences

| Aspect | Production (Documents) | Training (Test Lab) |
|--------|----------------------|---------------------|
| **Goal** | Export to Central Dispatch | Improve extraction accuracy |
| **Document Type** | Real auction documents | Sample documents for training |
| **After Review** | Export listing | Save as training example |
| **Warehouse Selection** | Required before export | Not applicable |
| **Export Button** | Yes | No (blocked for test docs) |

---

## 3. Documents Page Specification

### 3.1 Column Structure

| Column | Description | Source |
|--------|-------------|--------|
| **Order ID** | Unique identifier from document (Lot #, Stock #) | Extracted from PDF |
| **Auction** | Source type (COPART, IAA, MANHEIM, OTHER) | Auto-detected |
| **Pickup Location** | State + ZIP where vehicle is located | Extracted from PDF |
| **Warehouse** | Delivery destination (dropdown) | User selection |
| **Status** | Processing status | System |
| **Export Status** | CD export state | System |
| **Source** | How document was received | System |
| **Created** | Upload timestamp | System |
| **Actions** | Review, Export, Delete | User actions |

### 3.2 Status Values

| Status | Color | Meaning |
|--------|-------|---------|
| `needs_review` | Yellow | Extraction complete, needs human verification |
| `reviewed` | Green | Human verified, ready for export |
| `exported` | Blue | Successfully sent to Central Dispatch |
| `failed` | Red | Extraction or export failed |

### 3.3 Export Status Values

| Status | Color | Meaning |
|--------|-------|---------|
| `pending` | Gray | Not yet exported |
| `ready` | Green | Ready to export (all required fields present) |
| `exported` | Blue | Already exported to CD |
| `error` | Red | Export attempted but failed |

### 3.4 Source Values

| Source | Description |
|--------|-------------|
| `manual` | Uploaded manually through UI |
| `email:{address}` | Received via email from specific address |
| `webhook` | Received via webhook API |

### 3.5 Row Click Behavior

- Click on row → Opens **Review & Listing** page (NOT Test Lab's Review & Train)
- Shows all fields that will be exported to Central Dispatch
- Allows editing values before export
- Shows warehouse dropdown selection

---

## 4. Review & Listing Page Specification

### 4.1 Purpose

Production review page for documents ready to export. Different from Test Lab's "Review & Train".

### 4.2 Page Layout

```
┌────────────────────────────────────────────────────────────────────┐
│  Document: invoice_12345.pdf              [Edit Fields] [Export]   │
│  Order ID: 12345678    Auction: COPART    Status: reviewed         │
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──── Vehicle Information ────┐  ┌──── Pickup Location ────────┐ │
│  │ VIN: 1HGCM82633A123456     │  │ Name: Copart Dallas South   │ │
│  │ Year: 2023                  │  │ Address: 123 Industrial Rd  │ │
│  │ Make: Honda                 │  │ City: Dallas                │ │
│  │ Model: Accord               │  │ State: TX  ZIP: 75001       │ │
│  │ Condition: [Operable ▼]     │  │ Phone: (555) 123-4567       │ │
│  └─────────────────────────────┘  └──────────────────────────────┘ │
│                                                                     │
│  ┌──── Delivery Location ──────┐  ┌──── Additional Info ────────┐ │
│  │ Warehouse: [Select... ▼]    │  │ Buyer ID: ABC123            │ │
│  │   > Main Warehouse - Dallas │  │ Lot Number: 12345678        │ │
│  │   > Houston Branch          │  │ Sale Date: 2026-01-15       │ │
│  │   > Austin Location         │  │ Notes: Keys in ignition     │ │
│  │ (auto-fills address below)  │  └──────────────────────────────┘ │
│  │ Address: 456 Commerce St    │                                   │
│  │ City: Dallas                │  ┌──── Transport Instructions ──┐ │
│  │ State: TX  ZIP: 75201       │  │ Appointment required.        │ │
│  └─────────────────────────────┘  │ Hours: Mon-Fri 8am-5pm       │ │
│                                    └──────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────┤
│  [Preview CD Payload]  [Dry Run]           [Cancel]  [Export to CD]│
└────────────────────────────────────────────────────────────────────┘
```

### 4.3 Field Types

| Type | Behavior | Example |
|------|----------|---------|
| **Extracted** | Editable text from PDF | VIN, Address |
| **Dropdown** | Select from predefined values | Vehicle Condition, Warehouse |
| **Constant** | Auto-filled, read-only | Transport instructions from warehouse |
| **Computed** | Calculated by system | Dispatch ID, Expiration Date |

### 4.4 Warehouse Selection Logic

1. User selects warehouse from dropdown
2. System auto-fills delivery address fields
3. System adds transport special instructions
4. Once exported - warehouse field becomes locked (read-only)

### 4.5 Export Button States

| State | Condition | Button |
|-------|-----------|--------|
| **Disabled** | Missing required fields | Gray, shows "Complete required fields" |
| **Disabled** | Already exported | Gray, shows "Already exported" |
| **Enabled** | All fields present | Green, shows "Export to CD" |

---

## 5. Field Mapping Configuration

### 5.1 Available Fields (Central Dispatch API Only)

Fields must come from the official CD API. Custom fields are NOT allowed.

| Field Key | Display Name | Type | Required |
|-----------|--------------|------|----------|
| `vehicle_vin` | VIN | text | Yes |
| `vehicle_year` | Year | number | Yes |
| `vehicle_make` | Make | text | Yes |
| `vehicle_model` | Model | text | Yes |
| `vehicle_color` | Color | text | No |
| `vehicle_type` | Vehicle Type | select | Yes |
| `vehicle_condition` | Condition | select | Yes |
| `pickup_name` | Pickup Name | text | No |
| `pickup_address` | Pickup Address | text | Yes |
| `pickup_city` | Pickup City | text | Yes |
| `pickup_state` | Pickup State | text | Yes |
| `pickup_zip` | Pickup ZIP | text | Yes |
| `pickup_phone` | Pickup Phone | text | No |
| `pickup_contact` | Pickup Contact | text | No |
| `delivery_name` | Delivery Name | text | No |
| `delivery_address` | Delivery Address | text | Yes |
| `delivery_city` | Delivery City | text | Yes |
| `delivery_state` | Delivery State | text | Yes |
| `delivery_zip` | Delivery ZIP | text | Yes |
| `delivery_phone` | Delivery Phone | text | No |
| `delivery_contact` | Delivery Contact | text | No |
| `buyer_id` | Buyer ID | text | No |
| `buyer_name` | Buyer Name | text | No |
| `lot_number` | Lot Number | text | No |
| `stock_number` | Stock Number | text | No |
| `sale_date` | Sale Date | date | No |
| `total_amount` | Total Amount | number | No |
| `notes` | Notes | textarea | No |
| `transport_special_instructions` | Special Instructions | textarea | No |

### 5.2 Field Configuration UI

In Test Lab → Auction Types → Field Mappings:

- **Add Field**: Dropdown of CD API fields only (no free text entry)
- **Source**: "Extracted" (from PDF) or "Constant" (fixed value)
- **Required**: Checkbox - blocks export if empty
- **Active**: Checkbox - include in extraction/export

---

## 6. Training System Specification

### 6.1 Training Data Collection

1. User uploads document in Test Lab
2. System extracts fields using current rules
3. User reviews and corrects incorrect values
4. Corrections saved as training examples
5. System updates extraction rules

### 6.2 Model Versioning

| Field | Description |
|-------|-------------|
| `version` | Auto-incrementing version number |
| `auction_type` | Which auction type this model is for |
| `created_at` | When this version was created |
| `training_examples` | How many examples used to train |
| `status` | draft / training / active |
| `accuracy` | Test accuracy percentage |

### 6.3 Training Impact on Extraction

```
Document Upload → Get Active Model Version → Apply Extraction Rules →
                                      ↓
                  Training Examples → Pattern Learning → Rule Updates
```

Training data MUST affect extraction:
1. Each auction type has extraction rules
2. Rules are updated when user corrects fields
3. New documents use latest rules
4. Model version tracks when rules were last updated

---

## 7. API Integration

### 7.1 Email Receiving Options

| Method | Description | Configuration |
|--------|-------------|---------------|
| **IMAP/OAuth2** | Poll mailbox for new emails | Email server, credentials, folder |
| **Webhook** | Receive HTTP POST with document | Endpoint URL, secret key |

### 7.2 Central Dispatch Export

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/exports/central-dispatch` | POST | Export listings |
| `/api/exports/central-dispatch/preview/{id}` | GET | Preview payload |
| `/api/integrations/cd/dry-run` | POST | Validate without sending |

---

## 8. Error Handling

### 8.1 Document Processing Errors

| Error | User Message | Resolution |
|-------|--------------|------------|
| PDF unreadable | "Could not extract text from PDF" | Try re-uploading or use OCR |
| Unknown auction type | "Could not detect auction source" | Manually select type |
| Missing required fields | "Required fields missing: [list]" | Edit and fill missing fields |

### 8.2 Export Errors

| Error | User Message | Resolution |
|-------|--------------|------------|
| CD API timeout | "Central Dispatch not responding" | Retry later |
| Invalid credentials | "CD authentication failed" | Check settings |
| Validation failed | "Export rejected: [details]" | Fix validation errors |

---

## 9. Tasks for Development Team

### Task 1: Fix Document Detail Page Error
**Priority:** Critical
**Description:** Fix "Internal Server Error" when viewing document details
**Root Cause:** SQL query references non-existent column `cd_field_name` (should be `cd_key`)

### Task 2: Redesign Documents Page
**Priority:** High
**Description:** Update columns per specification section 3.1

### Task 3: Create Review & Listing Page
**Priority:** High
**Description:** Separate page for production document review (not Test Lab)

### Task 4: Fix Field Mapping Dropdown
**Priority:** Medium
**Description:** Change "Add Field" from free text to CD API field dropdown

### Task 5: Implement Model Versioning
**Priority:** Medium
**Description:** Track training model versions with dates

### Task 6: Connect Training to Extraction
**Priority:** High
**Description:** Ensure training corrections affect future extractions

---

## 10. Approval

- [ ] Product Owner reviewed and approved algorithm
- [ ] Technical Lead reviewed implementation plan
- [ ] QA reviewed test scenarios

**Comments:**
_Space for Product Owner feedback_

---

*Document prepared by Development Team*
