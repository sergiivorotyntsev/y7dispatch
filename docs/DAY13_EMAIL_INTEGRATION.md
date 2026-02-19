# Day 13: Email Integration — IMAP Polling + Auto-Processing Pipeline

## Context

Read CLAUDE.md for team workflow rules.
Read docs/DEVELOPMENT_JOURNAL.md for project context.
Read docs/CD_FIELD_CONFIG_FINAL-COMPLETED.csv for business rules.

## Business Requirements

### Email Setup
- **Inbox to monitor**: info@y7agency.com (GoDaddy Microsoft 365, IMAP)
- **Dispatch outbox**: dispatch@y7agency.com (for sending docs to carriers — FUTURE)
- **Current sender**: autausapl@gmail.com (will add more senders later)
- **Protocol**: IMAP over SSL (outlook.office365.com:993, App Password for auth)

### What arrives in email
1. **PDF attachments** — auction invoices (Copart, IAA, Manheim) — main documents for extraction
2. **Gate Pass PIN** — in email BODY text (not attachment). Pattern: "Gate Pass PIN: XXXXX" or similar
3. **Manheim Vehicle Release document** — PDF attachment alongside the invoice. This document:
   - Contains Vehicle Release ID needed by carrier
   - Must be SAVED and accessible via shareable link
   - Carrier needs to open it from phone or email
   - Can be sent to carrier via dispatch@y7agency.com
4. **Multiple PDFs per email** — common: invoice PDF + condition report PDF + Manheim release PDF

### Processing Flow
```
Email arrives at info@y7agency.com
  → IMAP poll picks it up
  → Parse: sender, subject, body, attachments
  → Extract Gate Pass PIN from body (if present)
  → For EACH PDF attachment:
      → Classify: invoice / condition report / vehicle release / other
      → Invoice PDFs → HaikuExtractor → create extraction_run
      → Vehicle Release PDFs → save as downloadable file, link to run
      → Condition report → check for "RUN AND DRIVE" / "INOP" in filename
  → Link all data to single extraction_run:
      - Extracted fields from invoice
      - Gate Pass PIN from body
      - Vehicle Release document (downloadable link)
      - Inoperable status from condition report filename
  → Mark email as READ in IMAP
  → Document appears in Documents page with status "NEW"
```

## Implementation Plan

### Step 1: ARCHITECT — Audit existing email code

```bash
grep -rn "email\|imap\|smtp\|mail\|inbox\|polling" api/ services/ workers/ --include="*.py" -l
grep -rn "email\|Email\|EmailTab\|imap" web/src/ --include="*.jsx" --include="*.js" -l
```

Check what already exists:
- services/email_providers/imap_provider.py — does it work?
- api/workers/email_worker.py — does it exist?
- api/routes/email_inbound.py — webhook receiver?
- Settings Email tab — what fields does it have?

Report findings before coding.

### Step 2: BACKEND — Email Service

#### 2a. Email Poller Service (services/email_poller.py)

```python
class EmailPoller:
    """
    Polls IMAP inbox for new emails with PDF attachments.
    Runs on a configurable interval (default: 60 seconds).
    """
    
    def __init__(self, imap_config: dict):
        """
        imap_config from credential_store('email_imap'):
        {
            "server": "outlook.office365.com",
            "port": 993,
            "email": "info@y7agency.com", 
            "password": "app-password-here",
            "folder": "INBOX",
            "poll_interval_seconds": 60,
            "allowed_senders": ["autausapl@gmail.com"],  # filter by sender
            "process_all_senders": false  # if true, process all emails with PDF attachments
        }
        """
    
    def poll_once(self) -> list[EmailMessage]:
        """
        Connect to IMAP, fetch UNSEEN emails, return parsed messages.
        Each EmailMessage contains:
        - message_id, subject, sender, date, body_text, body_html
        - attachments: list of {filename, content_type, bytes, size}
        - Only returns emails that have PDF attachments
        - If allowed_senders is set, filter by sender
        """
    
    def _classify_attachment(self, filename: str, pdf_bytes: bytes) -> str:
        """
        Classify PDF attachment type:
        - "invoice" — main auction document (Copart Bill of Sale, IAA invoice, Manheim receipt)
        - "vehicle_release" — Manheim Vehicle Release / ONSITE VEHICLE RELEASE
        - "condition_report" — vehicle condition report (often has RUN_AND_DRIVE in filename)
        - "other" — unknown type
        
        Classification logic:
        1. Filename contains "release" or "vehicle release" → vehicle_release
        2. Filename contains "condition" or "inspection" → condition_report
        3. Filename contains "invoice" or "bill" or "receipt" or "sale" → invoice
        4. If only one PDF → assume invoice
        5. Otherwise → other
        """
    
    def _extract_gate_pass(self, body_text: str) -> str | None:
        """
        Extract Gate Pass PIN from email body.
        Patterns to match:
        - "Gate Pass PIN: XXXXX"
        - "Gate Pass: XXXXX"  
        - "PIN: XXXXX"
        - "Your gate pass pin is XXXXX"
        Returns PIN string or None.
        """
    
    def _extract_inoperable_from_filename(self, filename: str) -> bool | None:
        """
        Check condition report filename for operability hints:
        - "RUN_AND_DRIVE" or "RUNS_AND_DRIVES" → False (operable)
        - "INOP" or "NON_RUN" → True (inoperable)
        - No match → None (unknown)
        """
```

#### 2b. Email Processing Pipeline (services/email_processor.py)

```python
class EmailProcessor:
    """
    Processes parsed email into extraction runs.
    """
    
    def process_email(self, email_msg: EmailMessage) -> ProcessingResult:
        """
        1. Classify all PDF attachments
        2. For each "invoice" PDF:
           a. Run HaikuExtractor → create extraction_run in DB
           b. Attach gate_pass from email body to the run
           c. Link vehicle_release document to the run
           d. Set inoperable status from condition report filename
        3. Save vehicle_release PDFs as downloadable files
        4. Return ProcessingResult with run_ids and any errors
        """
    
    def _save_attachment(self, filename: str, pdf_bytes: bytes, run_id: int) -> str:
        """
        Save PDF to uploads directory.
        Return URL path for download: /api/documents/{run_id}/attachments/{filename}
        This URL can be shared with carriers.
        """
```

#### 2c. Attachment Storage + Download Endpoint

```python
# api/routes/attachments.py

# Save attachments to: data/attachments/{run_id}/{filename}
# Serve via: GET /api/documents/{run_id}/attachments/{filename}
# This creates a shareable link for carriers

@router.get("/documents/{run_id}/attachments/{filename}")
async def download_attachment(run_id: int, filename: str):
    """Public download endpoint for carrier access."""
    file_path = Path(f"data/attachments/{run_id}/{filename}")
    if not file_path.exists():
        raise HTTPException(404)
    return FileResponse(file_path, media_type="application/pdf")
```

#### 2d. Email Worker (background polling)

```python
# api/workers/email_worker.py

import threading
import time
import logging

logger = logging.getLogger(__name__)

class EmailWorker:
    """Background thread that polls IMAP inbox."""
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.poll_interval = 60  # seconds
    
    def start(self):
        """Start polling in background thread."""
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()
        logger.info("Email worker started")
    
    def stop(self):
        self.running = False
        logger.info("Email worker stopped")
    
    def _poll_loop(self):
        while self.running:
            try:
                self._poll_once()
            except Exception as e:
                logger.error(f"Email poll error: {e}")
            time.sleep(self.poll_interval)
    
    def _poll_once(self):
        """Single poll cycle."""
        from services.credential_store import get_credential_for_service
        creds = get_credential_for_service("email_imap")
        if not creds:
            return  # Email not configured
        
        poller = EmailPoller(creds)
        messages = poller.poll_once()
        
        processor = EmailProcessor()
        for msg in messages:
            result = processor.process_email(msg)
            logger.info(f"Processed email: {msg.subject} → {len(result.run_ids)} runs created")
```

#### 2e. Email Management API

```python
# api/routes/email.py

@router.get("/api/email/status")
# Returns: polling active/inactive, last poll time, emails processed today, errors

@router.post("/api/email/poll-now")  
# Trigger immediate poll (for testing)

@router.get("/api/email/history")
# Returns list of processed emails: sender, subject, date, attachments count, runs created

@router.post("/api/email/start")
# Start background polling

@router.post("/api/email/stop")
# Stop background polling
```

#### 2f. Register Routes + Start Worker

In api/main.py:
- Register email router and attachments router
- On startup: if email credentials configured, start EmailWorker
- On shutdown: stop EmailWorker

### Step 3: FRONTEND

#### 3a. Email Settings (update existing EmailTab in Settings)

Fields:
```
Email Integration (IMAP)

IMAP Server:     [outlook.office365.com]  (default, editable)
Port:            [993]                     (default, editable)
Email Address:   [info@y7agency.com]       (required)
App Password:    [****************]        (required, masked)
Folder:          [INBOX]                   (default, editable)
Poll Interval:   [60] seconds              (default, editable)

Sender Filter:
  [x] Process only from specific senders
  Allowed Senders: [autausapl@gmail.com    ]  [+ Add]
  
  [ ] Process all emails with PDF attachments

[Save]  [Test Connection]  [Poll Now]

Status: 🟢 Connected | Last poll: 2 min ago | Today: 5 emails, 8 documents
```

Help text: "Using Microsoft 365 via GoDaddy? Create an App Password at https://mysignins.microsoft.com/security-info → Add method → App password."

#### 3b. Email Status Widget on Dashboard (optional)

Small status card showing:
- Polling: Active/Stopped
- Last poll: X minutes ago
- Today: N emails processed, M documents created
- Errors: 0

#### 3c. Documents Page — Email Source Column

Add "Source" column to Documents table:
- "Email" (with sender icon) for auto-processed documents
- "Upload" for manually uploaded documents
- Show email subject as tooltip

#### 3d. Review Page — Attachments Section

In DocumentDetails (collapsible section):
- Show all email attachments associated with this run
- Vehicle Release PDF → "Download" button + "Copy Link" button (shareable URL)
- Gate Pass PIN → displayed prominently
- Condition report → indicator if RUN AND DRIVE or INOP

### Step 4: TESTS

```python
# tests/e2e/test_email_integration.py

class TestGatePassExtraction:
    # test various gate pass patterns in email body
    # "Gate Pass PIN: ABC123" → "ABC123"
    # "Your gate pass pin is 12345" → "12345"
    # No gate pass → None

class TestAttachmentClassification:
    # "Copart_Invoice_91708175.pdf" → "invoice"
    # "Vehicle_Release_Document.pdf" → "vehicle_release"
    # "Condition_Report_RUN_AND_DRIVE.pdf" → "condition_report"
    # "random.pdf" (single attachment) → "invoice"

class TestEmailProcessing:
    # Mock IMAP connection
    # Create fake email with 2 PDFs + gate pass in body
    # Verify: extraction_run created, gate_pass saved, attachments stored

class TestAttachmentDownload:
    # Save attachment → GET download URL → file returned correctly

class TestEmailPollerConfig:
    # Allowed senders filter works
    # Poll interval respected
    # Credentials from credential store
```

### Step 5: Commit

```
git add -A
python -m pytest tests/ -q
git commit -m "feat: email integration — IMAP polling, auto-processing, attachment storage, gate pass extraction"
git push origin claude/create-claude-md-OomNZ
```

## Key Business Rules

1. **One email can create MULTIPLE extraction runs** (if multiple invoice PDFs attached)
2. **Gate Pass PIN** extracted from email body, stored with the run, goes to CD additionalInfo
3. **Vehicle Release PDF** saved to disk, accessible via shareable URL for carriers
4. **Condition report filename** can indicate RUN AND DRIVE or INOP status
5. **Sender filtering** — initially only process emails from allowed senders
6. **Mark as READ** after processing — don't reprocess same email
7. **Error handling** — if extraction fails, save email to DLQ for retry
8. **Multiple senders** — support adding more sender emails later via Settings

## Architecture Notes

- EmailWorker runs as daemon thread (not separate process) — simple for MVP
- Attachments stored on local filesystem (data/attachments/{run_id}/)
- Shareable links: /api/documents/{run_id}/attachments/{filename}
- IMAP credentials encrypted in credential_store (same as other integrations)
- If IMAP fails, worker retries on next poll cycle
- Poll Now button in Settings for manual testing
