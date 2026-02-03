"""Streamlit UI for Vehicle Transport Automation.

Run with: streamlit run ui/app.py

Pages:
1. Settings - Configure credentials and export targets
2. Upload & Extract - Upload PDFs and view extraction results
3. Batch - Process multiple PDFs from a folder
4. Runs/Logs - View recent runs and errors
"""

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

# Page config must be first Streamlit call
st.set_page_config(
    page_title="Vehicle Transport Automation",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded",
)


def load_settings():
    """Load settings from local_settings.json."""
    settings_path = PROJECT_ROOT / "config" / "local_settings.json"
    if settings_path.exists():
        with open(settings_path) as f:
            return json.load(f)
    return {
        "export_targets": ["sheets"],
        "enable_email_ingest": False,
        "schema_version": 1,
    }


def save_settings(settings):
    """Save settings to local_settings.json."""
    settings_path = PROJECT_ROOT / "config" / "local_settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)


def load_env_config():
    """Load configuration from .env file."""
    env_path = PROJECT_ROOT / ".env"
    config = {}
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()
    return config


def save_env_config(config):
    """Save configuration to .env file."""
    env_path = PROJECT_ROOT / ".env"
    lines = []

    # Read existing file to preserve comments and order
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#") or not stripped:
                    lines.append(line)
                elif "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in config:
                        lines.append(f"{key}={config[key]}\n")
                        del config[key]
                    else:
                        lines.append(line)

    # Add any new keys
    for key, value in config.items():
        lines.append(f"{key}={value}\n")

    with open(env_path, "w") as f:
        f.writelines(lines)


# ============================================================================
# Page: Settings
# ============================================================================
def page_settings():
    st.header("⚙️ Settings")

    settings = load_settings()
    env_config = load_env_config()

    # Export Targets
    st.subheader("Export Targets")
    st.write("Select where extracted data should be exported:")

    col1, col2, col3 = st.columns(3)
    with col1:
        sheets_enabled = st.checkbox(
            "Google Sheets",
            value="sheets" in settings.get("export_targets", []),
            help="Export to Google Sheets audit log",
        )
    with col2:
        clickup_enabled = st.checkbox(
            "ClickUp",
            value="clickup" in settings.get("export_targets", []),
            help="Create ClickUp tasks (Stage 2)",
            disabled=True,  # Disabled for Stage 1
        )
    with col3:
        cd_enabled = st.checkbox(
            "Central Dispatch",
            value="cd" in settings.get("export_targets", []),
            help="Create CD listings (Stage 2)",
            disabled=True,  # Disabled for Stage 1
        )

    st.divider()

    # Google Sheets Configuration
    st.subheader("Google Sheets Configuration")

    sheets_spreadsheet_id = st.text_input(
        "Spreadsheet ID",
        value=env_config.get("SHEETS_SPREADSHEET_ID", ""),
        help="The ID from the Google Sheets URL",
    )

    sheets_sheet_name = st.text_input(
        "Sheet Name",
        value=env_config.get("SHEETS_SHEET_NAME", "Pickups"),
        help="Name of the tab within the spreadsheet",
    )

    sheets_credentials = st.text_input(
        "Service Account JSON Path",
        value=env_config.get("SHEETS_CREDENTIALS_FILE", "credentials.json"),
        help="Path to the Google service account credentials file",
    )

    # Check if credentials file exists
    creds_path = PROJECT_ROOT / sheets_credentials
    if creds_path.exists():
        st.success(f"✅ Credentials file found: {sheets_credentials}")
    else:
        st.warning(f"⚠️ Credentials file not found: {sheets_credentials}")

    # Test Sheets Connection
    if st.button("🧪 Test Sheets Connection"):
        if not sheets_spreadsheet_id:
            st.error("Please enter a Spreadsheet ID")
        elif not creds_path.exists():
            st.error("Credentials file not found")
        else:
            try:
                from core.config import SheetsConfig
                from services.sheets_exporter import SheetsExporter

                config = SheetsConfig(
                    enabled=True,
                    spreadsheet_id=sheets_spreadsheet_id,
                    sheet_name=sheets_sheet_name,
                    credentials_file=str(creds_path),
                )
                exporter = SheetsExporter(config)
                exporter.ensure_headers()
                st.success("✅ Successfully connected to Google Sheets!")
            except Exception as e:
                st.error(f"❌ Connection failed: {e}")

    st.divider()

    # Email Configuration (informational for Stage 1)
    with st.expander("📧 Email Configuration (Stage 2)", expanded=False):
        st.info("Email ingestion is disabled in Stage 1. Configure for future use.")

        email_provider = st.selectbox(
            "Email Provider",
            options=["imap", "graph"],
            index=0 if env_config.get("EMAIL_PROVIDER", "imap") == "imap" else 1,
        )

        if email_provider == "imap":
            st.text_input(
                "IMAP Server",
                value=env_config.get("EMAIL_IMAP_SERVER", "outlook.office365.com"),
            )
            st.text_input(
                "Email Address",
                value=env_config.get("EMAIL_ADDRESS", ""),
            )
            st.text_input(
                "Password / App Password",
                value=env_config.get("EMAIL_PASSWORD", ""),
                type="password",
            )

    st.divider()

    # Save Button
    if st.button("💾 Save Settings", type="primary"):
        # Update export targets
        targets = []
        if sheets_enabled:
            targets.append("sheets")
        if clickup_enabled:
            targets.append("clickup")
        if cd_enabled:
            targets.append("cd")

        settings["export_targets"] = targets

        # Save local settings
        save_settings(settings)

        # Update .env
        env_updates = {
            "SHEETS_ENABLED": "true" if sheets_enabled else "false",
            "SHEETS_SPREADSHEET_ID": sheets_spreadsheet_id,
            "SHEETS_SHEET_NAME": sheets_sheet_name,
            "SHEETS_CREDENTIALS_FILE": sheets_credentials,
        }
        save_env_config(env_updates)

        st.success("✅ Settings saved!")
        st.balloons()


# ============================================================================
# Page: Upload & Extract
# ============================================================================
def page_upload():
    st.header("📤 Upload & Extract")

    # File uploader
    uploaded_files = st.file_uploader(
        "Upload PDF files",
        type=["pdf"],
        accept_multiple_files=True,
        help="Upload one or more auction invoice PDFs",
    )

    if not uploaded_files:
        st.info("👆 Upload PDF files to begin extraction")
        return

    # Auction override
    col1, col2 = st.columns([2, 1])
    with col1:
        st.selectbox(
            "Auction Source",
            options=["Auto-detect", "Copart", "IAA", "Manheim"],
            help="Override automatic auction detection",
        )
    with col2:
        st.checkbox(
            "Auto-export to Sheets",
            value=False,
            help="Automatically export successful extractions",
        )

    if st.button("🔍 Extract Data", type="primary"):
        from extractors import ExtractorManager

        manager = ExtractorManager()
        results = []

        progress = st.progress(0)
        status = st.empty()

        for i, uploaded_file in enumerate(uploaded_files):
            status.text(f"Processing: {uploaded_file.name}")
            progress.progress((i + 1) / len(uploaded_files))

            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(uploaded_file.read())
                tmp_path = tmp.name

            try:
                # Calculate hash
                uploaded_file.seek(0)
                file_hash = hashlib.sha256(uploaded_file.read()).hexdigest()[:16]

                # Classify and extract
                classification = manager.classify_pdf(tmp_path)

                if classification and classification.extractor:
                    result = classification.extractor.extract_with_result(
                        tmp_path, classification.text
                    )

                    score = result.score * 100
                    status_val = (
                        "OK" if score >= 60 else ("NEEDS_REVIEW" if score >= 30 else "FAIL")
                    )

                    record = {
                        "file": uploaded_file.name,
                        "file_hash": file_hash,
                        "auction": result.source.value if result.source else "UNKNOWN",
                        "score": round(score, 1),
                        "status": status_val,
                        "matched_patterns": ", ".join(result.matched_patterns),
                    }

                    if result.invoice:
                        inv = result.invoice
                        record.update(
                            {
                                "buyer_id": inv.buyer_id,
                                "buyer_name": inv.buyer_name,
                                "reference_id": inv.reference_id,
                                "total_amount": inv.total_amount,
                            }
                        )

                        if inv.vehicles:
                            v = inv.vehicles[0]
                            record["vin"] = v.vin
                            record["vehicle_year"] = v.year
                            record["vehicle_make"] = v.make
                            record["vehicle_model"] = v.model
                            record["lot_number"] = v.lot_number

                        if inv.pickup_address:
                            addr = inv.pickup_address
                            record["pickup_city"] = addr.city
                            record["pickup_state"] = addr.state
                            record["pickup_zip"] = addr.postal_code

                    results.append(record)
                else:
                    results.append(
                        {
                            "file": uploaded_file.name,
                            "file_hash": file_hash,
                            "auction": "UNKNOWN",
                            "score": 0,
                            "status": "FAIL",
                            "error": "No extractor matched",
                        }
                    )

            except Exception as e:
                results.append(
                    {
                        "file": uploaded_file.name,
                        "status": "ERROR",
                        "error": str(e),
                    }
                )

            finally:
                os.unlink(tmp_path)

        progress.empty()
        status.empty()

        # Store results in session state
        st.session_state["extraction_results"] = results

    # Display results
    if "extraction_results" in st.session_state:
        results = st.session_state["extraction_results"]

        st.subheader("Extraction Results")

        # Summary metrics
        ok_count = sum(1 for r in results if r.get("status") == "OK")
        review_count = sum(1 for r in results if r.get("status") == "NEEDS_REVIEW")
        fail_count = sum(1 for r in results if r.get("status") in ("FAIL", "ERROR"))

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total", len(results))
        col2.metric("OK", ok_count)
        col3.metric("Review", review_count)
        col4.metric("Failed", fail_count)

        # Results table
        for r in results:
            status = r.get("status", "UNKNOWN")
            icon = "✅" if status == "OK" else ("⚠️" if status == "NEEDS_REVIEW" else "❌")

            with st.expander(
                f"{icon} {r.get('file', 'Unknown')} - {r.get('auction', 'UNKNOWN')} ({r.get('score', 0):.0f}%)"
            ):
                if r.get("vin"):
                    st.write(f"**VIN:** {r['vin']}")
                if r.get("vehicle_year"):
                    st.write(
                        f"**Vehicle:** {r.get('vehicle_year')} {r.get('vehicle_make', '')} {r.get('vehicle_model', '')}"
                    )
                if r.get("lot_number"):
                    st.write(f"**Lot #:** {r['lot_number']}")
                if r.get("pickup_city"):
                    st.write(
                        f"**Pickup:** {r['pickup_city']}, {r.get('pickup_state', '')} {r.get('pickup_zip', '')}"
                    )
                if r.get("matched_patterns"):
                    st.write(f"**Matched:** {r['matched_patterns']}")
                if r.get("error"):
                    st.error(f"**Error:** {r['error']}")

        # Export button
        if st.button("📤 Export to Google Sheets"):
            try:
                from core.config import load_config_from_env
                from services.sheets_exporter import SheetsExporter

                config = load_config_from_env()
                if config.sheets.enabled and config.sheets.spreadsheet_id:
                    exporter = SheetsExporter(config.sheets)
                    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                    count = exporter.write_batch(results, run_id=run_id)
                    st.success(f"✅ Exported {count} rows to Google Sheets")
                else:
                    st.error("Google Sheets not configured. Check Settings.")
            except Exception as e:
                st.error(f"Export failed: {e}")


# ============================================================================
# Page: Batch
# ============================================================================
def page_batch():
    st.header("📁 Batch Processing")

    st.write("Process multiple PDF files from a folder.")

    # Folder input
    folder_path = st.text_input(
        "Folder Path",
        placeholder="/path/to/invoices",
        help="Enter the full path to a folder containing PDF files",
    )

    col1, col2 = st.columns(2)
    with col1:
        recursive = st.checkbox("Include subfolders", value=True)
    with col2:
        write_sheet = st.checkbox("Write to Google Sheets", value=True)

    if st.button("🚀 Start Batch Processing", type="primary"):
        if not folder_path:
            st.error("Please enter a folder path")
            return

        folder = Path(folder_path)
        if not folder.is_dir():
            st.error(f"Not a valid folder: {folder_path}")
            return

        # Find PDFs
        pattern = "**/*.pdf" if recursive else "*.pdf"
        pdf_files = list(folder.glob(pattern))

        if not pdf_files:
            st.warning(f"No PDF files found in {folder_path}")
            return

        st.info(f"Found {len(pdf_files)} PDF files")

        # Process
        from extractors import ExtractorManager

        manager = ExtractorManager()
        results = []
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        progress = st.progress(0)
        status = st.empty()

        for i, pdf_path in enumerate(pdf_files):
            status.text(f"[{i + 1}/{len(pdf_files)}] {pdf_path.name}")
            progress.progress((i + 1) / len(pdf_files))

            try:
                with open(pdf_path, "rb") as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()[:16]

                classification = manager.classify_pdf(str(pdf_path))

                if classification and classification.extractor:
                    result = classification.extractor.extract_with_result(
                        str(pdf_path), classification.text
                    )

                    score = result.score * 100
                    status_val = (
                        "OK" if score >= 60 else ("NEEDS_REVIEW" if score >= 30 else "FAIL")
                    )

                    record = {
                        "file": str(pdf_path),
                        "attachment_name": pdf_path.name,
                        "file_hash": file_hash,
                        "attachment_hash": file_hash,
                        "auction": result.source.value if result.source else "UNKNOWN",
                        "extraction_score": round(score, 1),
                        "score": round(score, 1),
                        "status": status_val,
                        "source_type": "batch",
                        "run_id": run_id,
                        "processed_at": datetime.now().isoformat(),
                    }

                    if result.invoice:
                        inv = result.invoice
                        record.update(
                            {
                                "buyer_id": inv.buyer_id or "",
                                "buyer_name": inv.buyer_name or "",
                                "reference_id": inv.reference_id or "",
                                "total_amount": inv.total_amount or 0,
                            }
                        )

                        if inv.vehicles:
                            v = inv.vehicles[0]
                            record["vin"] = v.vin or ""
                            record["vehicle_year"] = v.year or ""
                            record["vehicle_make"] = v.make or ""
                            record["vehicle_model"] = v.model or ""
                            record["lot_number"] = v.lot_number or ""

                        if inv.pickup_address:
                            addr = inv.pickup_address
                            record["pickup_city"] = addr.city or ""
                            record["pickup_state"] = addr.state or ""
                            record["pickup_zip"] = addr.postal_code or ""

                    results.append(record)
                else:
                    results.append(
                        {
                            "file": str(pdf_path),
                            "attachment_name": pdf_path.name,
                            "file_hash": file_hash,
                            "auction": "UNKNOWN",
                            "score": 0,
                            "status": "FAIL",
                            "error": "No extractor matched",
                            "source_type": "batch",
                            "run_id": run_id,
                        }
                    )

            except Exception as e:
                results.append(
                    {
                        "file": str(pdf_path),
                        "attachment_name": pdf_path.name,
                        "status": "ERROR",
                        "error": str(e),
                        "source_type": "batch",
                        "run_id": run_id,
                    }
                )

        progress.empty()
        status.empty()

        # Summary
        ok_count = sum(1 for r in results if r.get("status") == "OK")
        review_count = sum(1 for r in results if r.get("status") == "NEEDS_REVIEW")
        fail_count = sum(1 for r in results if r.get("status") in ("FAIL", "ERROR"))

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total", len(results))
        col2.metric("OK", ok_count)
        col3.metric("Review", review_count)
        col4.metric("Failed", fail_count)

        # Save results
        runs_dir = PROJECT_ROOT / "datasets" / "runs" / run_id
        runs_dir.mkdir(parents=True, exist_ok=True)

        results_file = runs_dir / "extracted.json"
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)

        st.success(f"Results saved to: {results_file}")

        # Write to Sheets
        if write_sheet:
            try:
                from core.config import load_config_from_env
                from services.sheets_exporter import SheetsExporter

                config = load_config_from_env()
                if config.sheets.enabled and config.sheets.spreadsheet_id:
                    exporter = SheetsExporter(config.sheets)
                    count = exporter.write_batch(results, run_id=run_id)
                    st.success(f"✅ Exported {count} rows to Google Sheets")
                else:
                    st.warning("Google Sheets not configured")
            except Exception as e:
                st.error(f"Sheets export failed: {e}")

        # Store for display
        st.session_state["batch_results"] = results
        st.session_state["batch_run_id"] = run_id


# ============================================================================
# Page: Runs/Logs
# ============================================================================
def page_runs():
    st.header("📊 Runs & Logs")

    runs_dir = PROJECT_ROOT / "datasets" / "runs"

    if not runs_dir.exists():
        st.info("No batch runs found yet")
        return

    # List runs
    runs = sorted(runs_dir.iterdir(), reverse=True)[:20]

    if not runs:
        st.info("No batch runs found")
        return

    st.write(f"Found {len(runs)} recent runs")

    for run_path in runs:
        run_id = run_path.name
        results_file = run_path / "extracted.json"
        errors_file = run_path / "errors.json"

        if not results_file.exists():
            continue

        with open(results_file) as f:
            results = json.load(f)

        ok_count = sum(1 for r in results if r.get("status") == "OK")
        fail_count = sum(1 for r in results if r.get("status") in ("FAIL", "ERROR"))

        with st.expander(f"🗂️ {run_id} - {len(results)} files ({ok_count} OK, {fail_count} FAIL)"):
            st.write(f"**Path:** {run_path}")

            if errors_file.exists():
                with open(errors_file) as f:
                    errors = json.load(f)
                if errors:
                    st.error(f"**{len(errors)} Errors:**")
                    for err in errors[:5]:
                        st.write(
                            f"- {err.get('file', 'Unknown')}: {err.get('error', 'Unknown error')}"
                        )

            # Show sample results
            st.write("**Sample Results:**")
            for r in results[:5]:
                st.write(
                    f"- {r.get('attachment_name', r.get('file', 'Unknown'))}: {r.get('status', 'UNKNOWN')} ({r.get('score', 0):.0f}%)"
                )


# ============================================================================
# Main App
# ============================================================================
def main():
    st.sidebar.title("🚗 Vehicle Transport")
    st.sidebar.write("Automation Pipeline")

    # Navigation
    page = st.sidebar.radio(
        "Navigate",
        options=["Settings", "Upload & Extract", "Batch", "Runs/Logs"],
        index=1,  # Default to Upload
    )

    st.sidebar.divider()

    # Quick status
    settings = load_settings()
    targets = settings.get("export_targets", [])
    st.sidebar.write("**Export Targets:**")
    st.sidebar.write(", ".join(targets) if targets else "None configured")

    # Run selected page
    if page == "Settings":
        page_settings()
    elif page == "Upload & Extract":
        page_upload()
    elif page == "Batch":
        page_batch()
    elif page == "Runs/Logs":
        page_runs()


if __name__ == "__main__":
    main()
