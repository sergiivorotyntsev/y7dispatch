#!/usr/bin/env python3
"""
Vehicle Transport Automation - Email to ClickUp Pipeline

CLI Commands:
    doctor             - Run preflight checks (Python, deps, configs)
    extract <pdf>      - Extract data from a single PDF file
    batch-extract      - Extract from multiple PDFs in a folder
    once               - Run single pass: fetch and process unseen emails
    daemon             - Run continuously, polling for new emails
    validate           - Validate all credentials (email, ClickUp, CD, Sheets)
    idempotency        - Manage idempotency database
    test-sheets        - Test Google Sheets connection
    sheets-upsert      - Upsert PDF extraction to sheet by dispatch_id
    cd-export          - Export READY rows from sheet to Central Dispatch

Usage:
    python main.py doctor
    python main.py extract invoice.pdf
    python main.py batch-extract ./invoices --write-sheet
    python main.py once --dry-run
    python main.py daemon --interval 60
    python main.py validate
    python main.py sheets-upsert invoice.pdf
    python main.py cd-export --from-sheet --dry-run
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def cmd_doctor(args):
    """Run preflight checks to ensure system is ready."""
    print("=" * 50)
    print(" Vehicle Transport Automation - System Check")
    print("=" * 50)
    print()

    all_ok = True
    warnings = []

    # Check 1: Python version
    print("[1/6] Python version...")
    py_version = sys.version_info
    if py_version.major >= 3 and py_version.minor >= 9:
        print(f"  OK: Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    else:
        print(f"  FAIL: Python 3.9+ required (found {py_version.major}.{py_version.minor})")
        all_ok = False

    # Check 2: Required dependencies
    print("[2/6] Core dependencies...")
    required_deps = [
        ("pdfplumber", "PDF extraction"),
        ("requests", "HTTP client"),
        ("dotenv", "Environment loading", "python-dotenv"),
        ("tenacity", "Retry logic"),
        ("yaml", "YAML parsing", "pyyaml"),
    ]
    for dep in required_deps:
        module_name = dep[0]
        description = dep[1]
        pip_name = dep[2] if len(dep) > 2 else module_name
        try:
            __import__(module_name)
            print(f"  OK: {pip_name} ({description})")
        except ImportError:
            print(f"  FAIL: {pip_name} not installed")
            all_ok = False

    # Check 3: Optional dependencies
    print("[3/6] Optional dependencies...")
    optional_deps = [
        ("google.oauth2", "Google Sheets", "google-auth"),
        ("googleapiclient", "Google Sheets API", "google-api-python-client"),
        ("streamlit", "Web UI", "streamlit"),
    ]
    for dep in optional_deps:
        module_name = dep[0]
        description = dep[1]
        pip_name = dep[2] if len(dep) > 2 else module_name
        try:
            __import__(module_name)
            print(f"  OK: {pip_name} ({description})")
        except ImportError:
            print(f"  SKIP: {pip_name} not installed (optional)")
            warnings.append(f"{pip_name} not installed - {description} unavailable")

    # Check 4: Configuration files
    print("[4/6] Configuration files...")
    config_files = [
        (".env", "Environment variables", True),
        (".env.example", "Example config", False),
        ("config/local_settings.json", "Local settings", False),
        ("cd_field_mapping.yaml", "CD field mapping", False),
        ("warehouses.yaml", "Warehouse locations", False),
    ]
    for filename, description, required in config_files:
        path = Path(PROJECT_ROOT) / filename
        if path.exists():
            print(f"  OK: {filename} ({description})")
        elif required:
            print(f"  FAIL: {filename} missing ({description})")
            all_ok = False
        else:
            print(f"  SKIP: {filename} missing (optional)")

    # Check 5: Directory structure
    print("[5/6] Directory structure...")
    directories = [
        "extractors",
        "services",
        "models",
        "core",
        "ingest",
        "tests",
    ]
    for dirname in directories:
        path = Path(PROJECT_ROOT) / dirname
        if path.is_dir():
            print(f"  OK: {dirname}/")
        else:
            print(f"  FAIL: {dirname}/ missing")
            all_ok = False

    # Check 6: Load and validate config (if .env exists)
    print("[6/6] Configuration validation...")
    if (Path(PROJECT_ROOT) / ".env").exists():
        try:
            from core.config import load_config_from_env, load_local_settings

            config = load_config_from_env()
            settings = load_local_settings()

            export_targets = settings.get("export_targets", ["sheets"])
            print(f"  Export targets: {', '.join(export_targets)}")

            # Check each target
            if "sheets" in export_targets:
                if config.sheets.enabled and config.sheets.spreadsheet_id:
                    print(f"  OK: Sheets configured (ID: {config.sheets.spreadsheet_id[:20]}...)")
                else:
                    print("  WARN: Sheets in targets but not configured")
                    warnings.append("Sheets export enabled but SHEETS_SPREADSHEET_ID not set")

            if "clickup" in export_targets:
                if config.clickup.token and config.clickup.list_id:
                    print(f"  OK: ClickUp configured (List: {config.clickup.list_id})")
                else:
                    print("  WARN: ClickUp in targets but not configured")
                    warnings.append("ClickUp export enabled but credentials not set")

            if "cd" in export_targets:
                if config.central_dispatch.enabled:
                    print("  OK: Central Dispatch configured")
                else:
                    print("  WARN: CD in targets but not configured")
                    warnings.append("Central Dispatch export enabled but credentials not set")

        except Exception as e:
            print(f"  WARN: Could not load config: {e}")
            warnings.append(f"Config load error: {e}")
    else:
        print("  SKIP: No .env file (run: cp .env.example .env)")
        warnings.append("No .env file - copy from .env.example")

    # Summary
    print()
    print("=" * 50)
    if all_ok and not warnings:
        print(" STATUS: ALL CHECKS PASSED")
    elif all_ok:
        print(f" STATUS: PASSED WITH {len(warnings)} WARNING(S)")
        for w in warnings:
            print(f"   - {w}")
    else:
        print(" STATUS: SOME CHECKS FAILED")
        print(" Fix the issues above before proceeding.")
    print("=" * 50)

    return 0 if all_ok else 1


def cmd_extract(args):
    """Extract data from a PDF file."""
    from core.logging_config import setup_logging
    from extractors import extract_from_pdf

    setup_logging(level="INFO", format_type="text")

    pdf_path = args.pdf
    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        return 1

    print(f"Extracting from: {pdf_path}")
    print("-" * 50)

    invoice = extract_from_pdf(pdf_path)

    if invoice:
        print(f"Source: {invoice.source.value}")
        print(f"Buyer ID: {invoice.buyer_id}")
        print(f"Buyer Name: {invoice.buyer_name}")
        print(f"Sale Date: {invoice.sale_date}")
        print(f"Reference ID: {invoice.reference_id}")
        print(
            f"Total Amount: ${invoice.total_amount:,.2f}"
            if invoice.total_amount
            else "Total Amount: N/A"
        )

        if invoice.pickup_address:
            addr = invoice.pickup_address
            print("\nPickup Address:")
            if addr.name:
                print(f"  Name: {addr.name}")
            if addr.street:
                print(f"  Street: {addr.street}")
            print(f"  City: {addr.city}, {addr.state} {addr.postal_code}")

        print(f"\nVehicles ({len(invoice.vehicles)}):")
        for i, v in enumerate(invoice.vehicles, 1):
            print(f"  {i}. {v.year} {v.make} {v.model}")
            print(f"     VIN: {v.vin}")
            if v.lot_number:
                print(f"     Lot #: {v.lot_number}")
            if v.color:
                print(f"     Color: {v.color}")
            if v.mileage:
                print(f"     Mileage: {v.mileage:,}")

        if args.json:
            print("\n--- JSON Output ---")
            output = {
                "source": invoice.source.value,
                "buyer_id": invoice.buyer_id,
                "buyer_name": invoice.buyer_name,
                "reference_id": invoice.reference_id,
                "vehicles": [
                    {
                        "vin": v.vin,
                        "year": v.year,
                        "make": v.make,
                        "model": v.model,
                        "lot_number": v.lot_number,
                        "color": v.color,
                        "mileage": v.mileage,
                    }
                    for v in invoice.vehicles
                ],
            }
            print(json.dumps(output, indent=2))

        return 0
    else:
        print("ERROR: Could not extract data from PDF")
        print("The document format may not be recognized (Copart/IAA/Manheim)")
        return 1


def cmd_batch_extract(args):
    """Extract data from multiple PDFs in a folder."""
    from core.config import load_config_from_env
    from core.logging_config import setup_logging
    from extractors import ExtractorManager

    setup_logging(level="INFO", format_type="text")

    folder_path = Path(args.folder)
    if not folder_path.is_dir():
        print(f"Error: Not a directory: {folder_path}")
        return 1

    # Find all PDFs
    pdf_files = list(folder_path.glob("**/*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {folder_path}")
        return 1

    print(f"Found {len(pdf_files)} PDF files")
    print("-" * 50)

    # Prepare output
    results = []
    errors = []
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create runs directory
    runs_dir = Path(PROJECT_ROOT) / "datasets" / "runs" / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)

    manager = ExtractorManager()

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] {pdf_path.name}...")

        try:
            # Calculate file hash for idempotency
            with open(pdf_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()[:16]

            # Extract text and classify
            classification = manager.classify_pdf(str(pdf_path))

            if classification and classification.extractor:
                # Run extraction
                result = classification.extractor.extract_with_result(
                    str(pdf_path), classification.text
                )

                # Calculate status/score
                score = result.score * 100
                status = "OK" if score >= 60 else ("NEEDS_REVIEW" if score >= 30 else "FAIL")

                record = {
                    "file": str(pdf_path),
                    "file_hash": file_hash,
                    "auction": result.source.value if result.source else "UNKNOWN",
                    "score": round(score, 1),
                    "status": status,
                    "matched_patterns": result.matched_patterns,
                    "needs_ocr": result.needs_ocr,
                    "extracted_at": datetime.now().isoformat(),
                }

                if result.invoice:
                    inv = result.invoice
                    record.update(
                        {
                            "buyer_id": inv.buyer_id,
                            "buyer_name": inv.buyer_name,
                            "reference_id": inv.reference_id,
                            "total_amount": inv.total_amount,
                            "vehicles": (
                                [
                                    {
                                        "vin": v.vin,
                                        "year": v.year,
                                        "make": v.make,
                                        "model": v.model,
                                        "lot_number": v.lot_number,
                                    }
                                    for v in inv.vehicles
                                ]
                                if inv.vehicles
                                else []
                            ),
                        }
                    )
                    # Extract first vehicle info for flat output
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
                print(f"       [{status}] {record.get('auction', 'UNKNOWN')} - Score: {score:.1f}%")

                if record.get("vin"):
                    print(f"       VIN: {record['vin']}")

            else:
                record = {
                    "file": str(pdf_path),
                    "file_hash": file_hash,
                    "auction": "UNKNOWN",
                    "score": 0,
                    "status": "FAIL",
                    "error": "No extractor matched",
                    "extracted_at": datetime.now().isoformat(),
                }
                results.append(record)
                errors.append(record)
                print("       [FAIL] No extractor matched")

        except Exception as e:
            record = {
                "file": str(pdf_path),
                "status": "ERROR",
                "error": str(e),
                "extracted_at": datetime.now().isoformat(),
            }
            results.append(record)
            errors.append(record)
            print(f"       [ERROR] {e}")

    # Save results
    print()
    print("-" * 50)

    # Save JSON
    results_file = runs_dir / "extracted.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved: {results_file}")

    if errors:
        errors_file = runs_dir / "errors.json"
        with open(errors_file, "w") as f:
            json.dump(errors, f, indent=2)
        print(f"Errors saved: {errors_file}")

    # Save CSV if requested
    if args.out_csv:
        import csv

        csv_file = Path(args.out_csv)
        fieldnames = [
            "file",
            "file_hash",
            "auction",
            "score",
            "status",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "lot_number",
            "pickup_city",
            "pickup_state",
            "pickup_zip",
            "buyer_id",
            "reference_id",
            "total_amount",
            "error",
        ]
        with open(csv_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
        print(f"CSV saved: {csv_file}")

    # Write to Google Sheets if requested
    if args.write_sheet:
        try:
            config = load_config_from_env()
            if config.sheets.enabled and config.sheets.spreadsheet_id:
                from services.sheets_exporter import SheetsExporter

                exporter = SheetsExporter(config.sheets)
                written = exporter.write_batch(results, run_id=run_id)
                print(f"Written to Google Sheets: {written} rows")
            else:
                print("WARN: Sheets not configured, skipping --write-sheet")
        except ImportError:
            print("WARN: Google Sheets dependencies not installed")
        except Exception as e:
            print(f"ERROR writing to Sheets: {e}")

    # Summary
    ok_count = sum(1 for r in results if r.get("status") == "OK")
    review_count = sum(1 for r in results if r.get("status") == "NEEDS_REVIEW")
    fail_count = sum(1 for r in results if r.get("status") in ("FAIL", "ERROR"))

    print()
    print(f"Summary: {ok_count} OK, {review_count} NEEDS_REVIEW, {fail_count} FAIL/ERROR")
    print(f"Run ID: {run_id}")

    return 0


def cmd_once(args):
    """Run a single pass of email processing."""
    from core.config import load_config_from_env
    from core.logging_config import setup_logging
    from services.orchestrator import Orchestrator

    config = load_config_from_env()
    config.dry_run = args.dry_run

    setup_logging(level=config.log_level, format_type=config.log_format)

    # Validate config
    try:
        config.validate(require_email=True, require_clickup=not args.dry_run)
    except Exception as e:
        print(f"Configuration error: {e}")
        return 1

    print("Running single pass...")
    if args.dry_run:
        print("(DRY RUN - no tasks will be created)")

    orchestrator = Orchestrator(config)
    results = orchestrator.run_once()

    # Print summary
    print(f"\nProcessed {len(results)} emails:")
    for result in results:
        status = "ERROR" if result.error else "OK"
        print(f"  [{status}] {result.subject}")
        if result.gate_pass:
            print(f"       Gate Pass: {result.gate_pass}")
        for att in result.attachment_results:
            att_status = "SKIP" if att.skipped_duplicate else ("OK" if att.success else "FAIL")
            print(f"       [{att_status}] {att.attachment_name}")
            if att.clickup_task_url:
                print(f"              Task: {att.clickup_task_url}")
            if att.error:
                print(f"              Error: {att.error}")

    return 0


def cmd_daemon(args):
    """Run in daemon mode."""
    from core.config import load_config_from_env
    from core.logging_config import setup_logging
    from services.orchestrator import run_daemon

    config = load_config_from_env()

    setup_logging(level=config.log_level, format_type=config.log_format)

    # Validate config
    try:
        config.validate()
    except Exception as e:
        print(f"Configuration error: {e}")
        return 1

    print(f"Starting daemon mode (interval: {args.interval or config.email.check_interval}s)")
    print("Press Ctrl+C to stop")

    run_daemon(config, interval=args.interval)
    return 0


def cmd_validate(args):
    """Validate all credentials."""
    from core.config import load_config_from_env
    from ingest.email_reader import create_email_reader
    from services.clickup import ClickUpClient

    print("Validating credentials...")
    print("-" * 50)

    config = load_config_from_env()
    all_ok = True

    # Validate Email
    print("\n[Email]")
    if config.email.address:
        print(f"  Provider: {config.email.provider}")
        print(f"  Address: {config.email.address}")
        if config.email.provider == "imap":
            print(f"  Server: {config.email.imap_server}")

        try:
            reader = create_email_reader(config.email)
            success, message = reader.validate_connection()
            if success:
                print(f"  Status: OK - {message}")
            else:
                print(f"  Status: FAILED - {message}")
                all_ok = False
        except Exception as e:
            print(f"  Status: ERROR - {e}")
            all_ok = False
    else:
        print("  Status: NOT CONFIGURED")
        if not args.skip_email:
            all_ok = False

    # Validate ClickUp
    print("\n[ClickUp]")
    if config.clickup.token and config.clickup.list_id:
        print(f"  List ID: {config.clickup.list_id}")

        try:
            client = ClickUpClient(
                token=config.clickup.token,
                list_id=config.clickup.list_id,
            )
            if client.validate_credentials():
                print("  Status: OK")
            else:
                print("  Status: FAILED - Invalid credentials")
                all_ok = False
        except Exception as e:
            print(f"  Status: ERROR - {e}")
            all_ok = False
    else:
        print("  Status: NOT CONFIGURED")
        if not args.skip_clickup:
            all_ok = False

    # Validate Central Dispatch (optional)
    print("\n[Central Dispatch]")
    if config.central_dispatch.enabled:
        print(f"  Marketplace ID: {config.central_dispatch.marketplace_id}")

        try:
            from services.central_dispatch import CentralDispatchClient

            cd_client = CentralDispatchClient(
                client_id=config.central_dispatch.client_id,
                client_secret=config.central_dispatch.client_secret,
                marketplace_id=config.central_dispatch.marketplace_id,
            )
            if cd_client.validate_credentials():
                print("  Status: OK")
            else:
                print("  Status: FAILED - Invalid credentials")
                # CD is optional, don't fail
        except Exception as e:
            print(f"  Status: ERROR - {e}")
    else:
        print("  Status: DISABLED (optional)")

    print("-" * 50)
    if all_ok:
        print("All required credentials validated successfully!")
        return 0
    else:
        print("Some credentials failed validation. Check configuration.")
        return 1


def cmd_test_sheets(args):
    """Test Google Sheets connection and optionally write a test row."""
    from pathlib import Path

    from core.config import load_config_from_env, load_local_settings

    print("Testing Google Sheets connection...")
    print("-" * 50)

    config = load_config_from_env()
    load_local_settings()

    if not config.sheets.enabled:
        print("ERROR: Google Sheets is not enabled")
        print("Set SHEETS_ENABLED=true and configure:")
        print("  - SHEETS_SPREADSHEET_ID")
        print("  - SHEETS_CREDENTIALS_FILE (path to service account JSON)")
        return 1

    print(f"Spreadsheet ID: {config.sheets.spreadsheet_id}")
    print(f"Sheet Name: {config.sheets.sheet_name}")
    print(f"Credentials: {config.sheets.credentials_file}")

    # Check credentials file
    creds_path = Path(config.sheets.credentials_file)
    if not creds_path.exists():
        print(f"\nERROR: Credentials file not found: {creds_path}")
        return 1
    print("Credentials file: EXISTS")

    # Try to connect
    try:
        from services.sheets_exporter import SheetsExporter

        exporter = SheetsExporter(config.sheets)

        # Test 1: Ensure headers
        print("\n[1/3] Testing connection (ensure_headers)...")
        headers_created = exporter.ensure_headers()
        if headers_created:
            print("  OK: Headers created/updated")
        else:
            print("  OK: Headers already exist")

        # Test 2: Check if we can read
        print("[2/3] Testing read access...")
        service = exporter._get_service()
        service.spreadsheets().values().get(
            spreadsheetId=config.sheets.spreadsheet_id, range=f"{config.sheets.sheet_name}!A1:A1"
        ).execute()
        print("  OK: Can read from sheet")

        # Test 3: Write test row (if requested)
        if args.write_test:
            print("[3/3] Writing test row...")
            from datetime import datetime

            test_record = {
                "run_id": "test_" + datetime.now().strftime("%H%M%S"),
                "source_type": "test",
                "auction": "TEST",
                "status": "OK",
                "vin": "TEST_VIN_12345678",
                "vehicle_year": 2024,
                "vehicle_make": "Test",
                "vehicle_model": "Connection",
                "extraction_score": 100.0,
                "attachment_name": "test_connection.pdf",
                "attachment_hash": "test_hash_" + datetime.now().strftime("%Y%m%d"),
            }
            exporter.append_record(test_record)
            print("  OK: Test row written successfully")
        else:
            print("[3/3] Skipping test write (use --write-test to enable)")

        print("\n" + "-" * 50)
        print("SUCCESS: Google Sheets connection is working!")
        print(f"Spreadsheet: https://docs.google.com/spreadsheets/d/{config.sheets.spreadsheet_id}")
        return 0

    except ImportError as e:
        print(f"\nERROR: Missing dependencies: {e}")
        print("Install with: pip install google-auth google-api-python-client")
        return 1
    except Exception as e:
        print(f"\nERROR: Connection failed: {e}")
        return 1


def cmd_sheets_upsert(args):
    """Upsert PDF extraction to Google Sheets by dispatch_id."""
    from pathlib import Path

    from core.config import load_config_from_env
    from core.logging_config import setup_logging
    from extractors import ExtractorManager
    from schemas.sheets_schema_v2 import RowStatus, generate_dispatch_id

    setup_logging(level="INFO", format_type="text")

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: File not found: {pdf_path}")
        return 1

    config = load_config_from_env()
    if not config.sheets.enabled:
        print("Error: Google Sheets not configured")
        return 1

    print(f"Processing: {pdf_path.name}")
    print("-" * 50)

    # Extract from PDF
    manager = ExtractorManager()
    classification = manager.classify_pdf(str(pdf_path))

    if not classification or not classification.extractor:
        print("Error: Could not classify PDF (no extractor matched)")
        return 1

    result = classification.extractor.extract_with_result(str(pdf_path), classification.text)

    if not result.invoice:
        print("Error: Could not extract invoice data from PDF")
        return 1

    inv = result.invoice
    auction = result.source.value if result.source else "UNKNOWN"

    # Calculate file hash
    with open(pdf_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()[:16]

    # Get gate pass or lot number for dispatch_id
    gate_pass = None
    auction_ref = None
    vin = None
    if inv.vehicles:
        v = inv.vehicles[0]
        gate_pass = v.lot_number
        vin = v.vin

    # Generate dispatch_id
    dispatch_id = generate_dispatch_id(
        auction_source=auction,
        gate_pass=gate_pass,
        auction_reference=auction_ref,
        vin=vin,
        attachment_hash=file_hash,
    )

    print(f"Auction: {auction}")
    print(f"Dispatch ID: {dispatch_id}")

    # Build record for sheets
    record = {
        "dispatch_id": dispatch_id,
        "row_status": RowStatus.NEW.value,
        "auction_source": auction,
        "attachment_name": pdf_path.name,
        "attachment_hash": file_hash,
        "extraction_score": round(result.score * 100, 1),
    }

    # Add vehicle info
    if inv.vehicles:
        v = inv.vehicles[0]
        record.update(
            {
                "vin": v.vin,
                "year": v.year,
                "make": v.make,
                "model": v.model,
                "gate_pass": v.lot_number,
                "color": v.color,
                "operable": "TRUE",
            }
        )
        if v.mileage:
            record["mileage"] = v.mileage

    # Add pickup address
    if inv.pickup_address:
        addr = inv.pickup_address
        record.update(
            {
                "pickup_city": addr.city,
                "pickup_state": addr.state,
                "pickup_postal_code": addr.postal_code,
                "pickup_street1": addr.street,
            }
        )

    # Add buyer info
    if inv.buyer_name:
        record["company_name"] = inv.buyer_name
    if inv.reference_id:
        record["auction_reference"] = inv.reference_id

    # Upsert to sheets
    try:
        from services.sheets_exporter_v2 import SheetsExporterV2

        exporter = SheetsExporterV2(config.sheets, sheet_name=args.sheet or "Pickups")
        result = exporter.upsert_record(record)

        print()
        print(f"Action: {result['action'].upper()}")
        print(f"Dispatch ID: {result['dispatch_id']}")
        if result.get("protected_fields"):
            print(f"Protected fields (not updated): {', '.join(result['protected_fields'])}")

        print()
        print("SUCCESS: Record upserted to Google Sheets")
        return 0

    except Exception as e:
        print(f"\nError: {e}")
        return 1


def cmd_cd_export(args):
    """Export READY rows from Google Sheets to Central Dispatch."""
    from core.config import load_config_from_env
    from core.logging_config import setup_logging

    setup_logging(level="INFO", format_type="text")

    config = load_config_from_env()

    if not config.sheets.enabled:
        print("Error: Google Sheets not configured")
        return 1

    if not args.from_sheet:
        print("Error: --from-sheet flag required")
        return 1

    print("CD Export from Google Sheets")
    print("-" * 50)

    try:
        from services.cd_sheet_exporter import CDSheetExporter

        exporter = CDSheetExporter(
            sheets_config=config.sheets,
            cd_config=config.central_dispatch,
            sheet_name=args.sheet or "Pickups",
        )

        # Preview mode
        if args.preview:
            if not args.dispatch_id:
                print("Error: --dispatch-id required for preview")
                return 1

            payload = exporter.preview_payload(args.dispatch_id)
            if payload:
                print(f"CD Payload for {args.dispatch_id}:")
                print(json.dumps(payload, indent=2))
            else:
                print(f"Error: Row not found: {args.dispatch_id}")
                return 1
            return 0

        # Export mode
        results = exporter.export_ready_rows(
            dry_run=args.dry_run,
            limit=args.limit,
        )

        print()
        print(f"Total rows: {results['total']}")
        print(f"Exported: {results['exported']}")
        print(f"Failed: {results['failed']}")
        if args.dry_run:
            print("(DRY RUN - no actual API calls made)")

        if results["results"]:
            print()
            print("Details:")
            for r in results["results"]:
                status = "OK" if r["success"] else "FAIL"
                print(f"  [{status}] {r['dispatch_id']}")
                if r.get("listing_id"):
                    print(f"         CD Listing: {r['listing_id']}")
                if r.get("error"):
                    print(f"         Error: {r['error']}")

        return 0 if results["failed"] == 0 else 1

    except Exception as e:
        print(f"\nError: {e}")
        return 1


def cmd_idempotency(args):
    """Manage idempotency database."""
    from core.config import load_config_from_env
    from services.idempotency import IdempotencyStore

    config = load_config_from_env()
    store = IdempotencyStore(db_path=config.storage.idempotency_db_path)

    if args.action == "stats":
        # Show stats
        with store._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM processed_items")
            total = cursor.fetchone()[0]

            cursor = conn.execute("""
                SELECT source_type, COUNT(*)
                FROM processed_items
                GROUP BY source_type
            """)
            by_source = cursor.fetchall()

            cursor = conn.execute("""
                SELECT date(processed_at), COUNT(*)
                FROM processed_items
                GROUP BY date(processed_at)
                ORDER BY date(processed_at) DESC
                LIMIT 7
            """)
            by_day = cursor.fetchall()

        print(f"Idempotency Database: {config.storage.idempotency_db_path}")
        print(f"Total records: {total}")
        print("\nBy source:")
        for source, count in by_source:
            print(f"  {source or 'UNKNOWN'}: {count}")
        print("\nLast 7 days:")
        for day, count in by_day:
            print(f"  {day}: {count}")

    elif args.action == "purge":
        if not args.days:
            print("Error: --days required for purge")
            return 1

        with store._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM processed_items WHERE processed_at < datetime('now', ?)",
                (f"-{args.days} days",),
            )
            deleted = cursor.rowcount
            conn.commit()

        print(f"Purged {deleted} records older than {args.days} days")

    elif args.action == "list":
        limit = args.limit or 20
        with store._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT idempotency_key, source_type, result_id, processed_at
                FROM processed_items
                ORDER BY processed_at DESC
                LIMIT ?
            """,
                (limit,),
            )
            rows = cursor.fetchall()

        print(f"Last {limit} processed items:")
        for row in rows:
            print(f"  {row['processed_at']} | {row['source_type']} | {row['result_id']}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Vehicle Transport Automation - Email to ClickUp Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python main.py doctor
    python main.py extract invoice.pdf --json
    python main.py batch-extract ./invoices --write-sheet
    python main.py once --dry-run
    python main.py daemon --interval 120
    python main.py validate
    python main.py idempotency stats
    python main.py sheets-upsert invoice.pdf
    python main.py cd-export --from-sheet --dry-run
    python main.py cd-export --from-sheet --preview --dispatch-id DC-20260130-COPART-ABC12345
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # doctor command
    subparsers.add_parser("doctor", help="Run preflight checks")

    # extract command
    extract_parser = subparsers.add_parser("extract", help="Extract data from a PDF file")
    extract_parser.add_argument("pdf", help="Path to PDF file")
    extract_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # batch-extract command
    batch_parser = subparsers.add_parser("batch-extract", help="Extract from multiple PDFs")
    batch_parser.add_argument("folder", help="Folder containing PDF files")
    batch_parser.add_argument(
        "--write-sheet", action="store_true", help="Write results to Google Sheets"
    )
    batch_parser.add_argument("--out-csv", help="Output CSV file path")

    # once command
    once_parser = subparsers.add_parser("once", help="Run single pass of email processing")
    once_parser.add_argument("--dry-run", action="store_true", help="Don't create ClickUp tasks")

    # daemon command
    daemon_parser = subparsers.add_parser("daemon", help="Run continuously")
    daemon_parser.add_argument("--interval", type=int, help="Check interval in seconds")

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate credentials")
    validate_parser.add_argument("--skip-email", action="store_true", help="Skip email validation")
    validate_parser.add_argument(
        "--skip-clickup", action="store_true", help="Skip ClickUp validation"
    )
    validate_parser.add_argument(
        "--mode",
        choices=["full", "local"],
        default="full",
        help="Validation mode (local=only enabled targets)",
    )

    # idempotency command
    idem_parser = subparsers.add_parser("idempotency", help="Manage idempotency database")
    idem_parser.add_argument("action", choices=["stats", "purge", "list"], help="Action to perform")
    idem_parser.add_argument("--days", type=int, help="Days for purge")
    idem_parser.add_argument("--limit", type=int, help="Limit for list")

    # test-sheets command
    sheets_parser = subparsers.add_parser("test-sheets", help="Test Google Sheets connection")
    sheets_parser.add_argument(
        "--write-test", action="store_true", help="Write a test row to verify write access"
    )

    # sheets-upsert command
    upsert_parser = subparsers.add_parser(
        "sheets-upsert", help="Upsert PDF extraction to sheet by dispatch_id"
    )
    upsert_parser.add_argument("pdf", help="Path to PDF file")
    upsert_parser.add_argument("--sheet", help="Sheet name (default: Pickups)")

    # cd-export command
    cd_export_parser = subparsers.add_parser(
        "cd-export", help="Export READY rows from sheet to Central Dispatch"
    )
    cd_export_parser.add_argument(
        "--from-sheet", action="store_true", help="Export from Google Sheets (required)"
    )
    cd_export_parser.add_argument("--sheet", help="Sheet name (default: Pickups)")
    cd_export_parser.add_argument(
        "--dry-run", action="store_true", help="Preview without calling CD API"
    )
    cd_export_parser.add_argument("--limit", type=int, help="Maximum rows to export")
    cd_export_parser.add_argument(
        "--preview", action="store_true", help="Preview payload for a single row"
    )
    cd_export_parser.add_argument("--dispatch-id", help="Dispatch ID for preview mode")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "doctor": cmd_doctor,
        "extract": cmd_extract,
        "batch-extract": cmd_batch_extract,
        "once": cmd_once,
        "daemon": cmd_daemon,
        "validate": cmd_validate,
        "idempotency": cmd_idempotency,
        "test-sheets": cmd_test_sheets,
        "sheets-upsert": cmd_sheets_upsert,
        "cd-export": cmd_cd_export,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
