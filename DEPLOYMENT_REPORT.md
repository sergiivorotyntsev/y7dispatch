# Vehicle Transport Automation - Deployment Report

## Version Info

| Field | Value |
|-------|-------|
| **Commit Hash** | `{GIT_COMMIT_HASH}` |
| **Version** | 1.0.0 |
| **Date** | {DEPLOYMENT_DATE} |
| **Branch** | `claude/setup-project-structure-I6KBV` |

---

## Windows Deployment Commands

### 1. Prerequisites

```powershell
# Verify Python 3.9+
python --version

# Verify pip
pip --version

# Verify Node.js 18+ (for Web UI)
node --version
npm --version
```

### 2. Clone and Setup

```powershell
# Clone repository
git clone https://github.com/{ORG}/CENTRALDISPATCH.git
cd CENTRALDISPATCH

# Run bootstrap script
.\scripts\bootstrap.ps1

# Or manually:
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 3. Configuration

```powershell
# Copy example config
copy .env.example .env

# Edit .env with your settings
notepad .env

# Create local_settings.json
@"
{
  "export_targets": ["sheets"],
  "enable_email_ingest": false,
  "schema_version": 1
}
"@ | Out-File -FilePath "config\local_settings.json" -Encoding UTF8
```

### 4. Run Doctor Check

```powershell
python main.py doctor
```

### 5. Test Sheets Connection

```powershell
python main.py test-sheets --write-test
```

### 6. Start FastAPI Backend

```powershell
uvicorn api.main:app --reload --port 8000
```

### 7. Start Web UI (Development)

```powershell
cd web
npm install
npm run dev
```

### 8. Access Control Panel

- **Web UI**: http://localhost:3000
- **API Docs**: http://localhost:8000/api/docs
- **Health Check**: http://localhost:8000/api/health

---

## Doctor Output

```
==================================================
 Vehicle Transport Automation - System Check
==================================================

[1/6] Python version...
  OK: Python 3.11.x

[2/6] Core dependencies...
  OK: pdfplumber (PDF extraction)
  OK: requests (HTTP client)
  OK: python-dotenv (Environment loading)
  OK: tenacity (Retry logic)
  OK: pyyaml (YAML parsing)

[3/6] Optional dependencies...
  OK: google-auth (Google Sheets)
  OK: google-api-python-client (Google Sheets API)
  OK: streamlit (Web UI)

[4/6] Configuration files...
  OK: .env (Environment variables)
  OK: config/local_settings.json (Local settings)

[5/6] Directory structure...
  OK: extractors/
  OK: services/
  OK: models/
  OK: core/
  OK: ingest/
  OK: tests/

[6/6] Configuration validation...
  Export targets: sheets
  OK: Sheets configured (ID: xxxxxxxxx...)

==================================================
 STATUS: ALL CHECKS PASSED
==================================================
```

---

## Test Sheets Output

```
Testing Google Sheets connection...
--------------------------------------------------
Spreadsheet ID: {SPREADSHEET_ID}
Sheet Name: Sheet1
Credentials: config/service_account.json
Credentials file: EXISTS

[1/3] Testing connection (ensure_headers)...
  OK: Headers created/updated

[2/3] Testing read access...
  OK: Can read from sheet

[3/3] Writing test row...
  OK: Test row written successfully

--------------------------------------------------
SUCCESS: Google Sheets connection is working!
Spreadsheet: https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}
```

---

## UI Screenshots

### Dashboard
![Dashboard](docs/screenshots/dashboard.png)
- Shows integration status (Email, ClickUp, Sheets, CD)
- Last 20 runs with status
- Statistics overview

### Settings
![Settings](docs/screenshots/settings.png)
- Export targets configuration
- Google Sheets settings
- ClickUp/CD/Email settings

### Test Lab
![Test Lab](docs/screenshots/testlab.png)
- Drag & drop PDF upload
- Auction classification result
- Extraction preview
- Sheets row preview
- CD payload preview

### Runs & Logs
![Runs](docs/screenshots/runs.png)
- Filterable runs table
- Run details panel
- Logs viewer
- CSV export

---

## Test Extraction Example

### Input PDF
- **File**: `sample_copart_invoice.pdf`
- **Source**: COPART
- **Size**: 245 KB

### Classification Result
```json
{
  "source": "COPART",
  "score": 87.5,
  "extractor": "CopartExtractor",
  "needs_ocr": false,
  "matched_patterns": [
    "Member Purchase Invoice",
    "COPART INC",
    "Gate Pass",
    "Lot Number"
  ]
}
```

### Extraction Result
```json
{
  "source": "COPART",
  "buyer_id": "12345678",
  "buyer_name": "ABC Transport LLC",
  "reference_id": "INV-2024-001234",
  "total_amount": 15250.00,
  "vehicles": [
    {
      "vin": "1HGBH41JXMN109186",
      "year": 2021,
      "make": "Honda",
      "model": "Civic",
      "lot_number": "87654321",
      "color": "Silver",
      "mileage": 45230
    }
  ],
  "pickup_address": {
    "name": "COPART - Dallas",
    "city": "Dallas",
    "state": "TX",
    "postal_code": "75234"
  }
}
```

### Sheets Row Preview
| Column | Value |
|--------|-------|
| run_id | abc123 |
| auction | COPART |
| vin | 1HGBH41JXMN109186 |
| year | 2021 |
| make | Honda |
| model | Civic |
| lot_number | 87654321 |
| pickup_city | Dallas |
| pickup_state | TX |
| status | OK |
| score | 87.5 |

### CD Payload Preview
```json
{
  "listing": {
    "vehicleInfo": {
      "vin": "1HGBH41JXMN109186",
      "year": 2021,
      "make": "Honda",
      "model": "Civic",
      "condition": "OPERABLE"
    },
    "originInfo": {
      "city": "Dallas",
      "state": "TX",
      "zip": "75234"
    },
    "pickupDate": "2024-01-15",
    "notes": "Lot #87654321"
  }
}
```

---

## Credentials Checklist

### Required for Sheets-Only Mode

| Credential | Status | Where to Get |
|------------|--------|--------------|
| **Google Spreadsheet ID** | [ ] | From your Google Sheets URL: `/d/{ID}/edit` |
| **Service Account JSON** | [ ] | Google Cloud Console > IAM > Service Accounts |
| **Sheet Shared with SA** | [ ] | Share sheet with `...@...iam.gserviceaccount.com` |

### Required for ClickUp Export

| Credential | Status | Where to Get |
|------------|--------|--------------|
| **ClickUp API Token** | [ ] | ClickUp Settings > Apps > Generate API Token |
| **ClickUp List ID** | [ ] | From list URL or API |

### Required for Central Dispatch Export

| Credential | Status | Where to Get |
|------------|--------|--------------|
| **CD Client ID** | [ ] | Central Dispatch API Portal |
| **CD Client Secret** | [ ] | Central Dispatch API Portal |
| **CD Marketplace ID** | [ ] | Your CD account settings |

### Required for Email Ingestion

| Credential | Status | Where to Get |
|------------|--------|--------------|
| **Email Address** | [ ] | Your email provider |
| **IMAP Server** | [ ] | `imap.gmail.com`, `outlook.office365.com`, etc. |
| **App Password** | [ ] | Gmail: Security > App passwords |

---

## Environment Variables Reference

```env
# Google Sheets
SHEETS_ENABLED=true
SHEETS_SPREADSHEET_ID=your_spreadsheet_id
SHEETS_SHEET_NAME=Sheet1
SHEETS_CREDENTIALS_FILE=config/service_account.json

# ClickUp (optional)
CLICKUP_TOKEN=pk_xxxxx
CLICKUP_LIST_ID=123456789

# Central Dispatch (optional)
CD_ENABLED=false
CD_CLIENT_ID=your_client_id
CD_CLIENT_SECRET=your_client_secret
CD_MARKETPLACE_ID=your_marketplace_id

# Email (optional)
EMAIL_PROVIDER=imap
EMAIL_ADDRESS=your@email.com
EMAIL_PASSWORD=app_password
EMAIL_IMAP_SERVER=imap.gmail.com
```

---

## Troubleshooting

### Common Issues

1. **"Credentials file not found"**
   - Ensure `config/service_account.json` exists
   - Check path in `SHEETS_CREDENTIALS_FILE`

2. **"Permission denied" on Sheets**
   - Share spreadsheet with service account email
   - Grant "Editor" permissions

3. **"Module not found"**
   - Run `pip install -r requirements.txt`
   - Activate virtual environment

4. **Port already in use**
   - Kill existing process: `netstat -ano | findstr :8000`
   - Use different port: `--port 8001`

---

## Next Steps

1. [ ] Run `python main.py doctor` and verify all checks pass
2. [ ] Configure `.env` with your credentials
3. [ ] Run `python main.py test-sheets --write-test`
4. [ ] Start backend: `uvicorn api.main:app --reload`
5. [ ] Start web UI: `cd web && npm run dev`
6. [ ] Upload test PDF and verify extraction
7. [ ] Check Google Sheets for test row

---

*Report generated for Vehicle Transport Automation v1.0.0*
