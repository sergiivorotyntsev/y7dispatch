"""
Google Sheets Exporter with Upsert Mode (Schema v1)

The Pickups sheet is the Source of Truth for all pickup data.

Features:
1. Upsert mode with pickup_uid as primary key
2. Column class handling (immutable, system, user-owned)
3. Final value computation (base/override/final)
4. Batch updates via batchUpdate API
5. Lock import protection
6. Change detection via payload hash

Usage:
    exporter = SheetsExporter(config)
    exporter.upsert_record(record)
    exporter.upsert_batch(records)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.config import SheetsConfig
from schemas.sheets_schema_v1 import (
    SCHEMA_VERSION,
    column_index_to_letter,
    compute_final_value,
    compute_pickup_uid,
    get_column_index,
    get_column_letter,
    get_column_names,
    get_updatable_columns_on_ingest,
)

logger = logging.getLogger(__name__)

# Automation version tag
AUTOMATION_VERSION = f"v{SCHEMA_VERSION}.0"


class SheetsExporter:
    """
    Exports extraction results to Google Sheets with upsert support.

    The Pickups sheet is the source of truth:
    - Import creates/updates system fields only
    - User override fields are never touched by import
    - lock_import=TRUE prevents all updates except last_ingested_at
    """

    def __init__(self, config: SheetsConfig):
        self.config = config
        self.column_names = get_column_names()
        self._service = None
        self._sheet_id = None
        self._uid_cache: dict[str, int] = {}  # pickup_uid -> row_number cache
        self._cache_valid = False

    # =========================================================================
    # API Service
    # =========================================================================

    def _get_service(self):
        """Get or create Google Sheets API service."""
        if self._service is not None:
            return self._service

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds_path = Path(self.config.credentials_file)
            if creds_path.exists():
                creds = service_account.Credentials.from_service_account_file(
                    str(creds_path),
                    scopes=["https://www.googleapis.com/auth/spreadsheets"],
                )
                self._service = build("sheets", "v4", credentials=creds)
                return self._service
            else:
                raise FileNotFoundError(f"Credentials file not found: {creds_path}")

        except ImportError:
            raise ImportError(
                "Google Sheets dependencies not installed. "
                "Run: pip install google-auth google-api-python-client"
            )

    def _get_sheet_id(self) -> int:
        """Get the sheet ID for the configured sheet name."""
        if self._sheet_id is not None:
            return self._sheet_id

        service = self._get_service()
        spreadsheet = service.spreadsheets().get(spreadsheetId=self.config.spreadsheet_id).execute()

        for sheet in spreadsheet.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == self.config.sheet_name:
                self._sheet_id = props.get("sheetId")
                return self._sheet_id

        # Sheet not found, create it
        logger.info(f"Creating sheet: {self.config.sheet_name}")
        self._create_sheet()
        return self._sheet_id

    def _create_sheet(self):
        """Create a new sheet with headers."""
        service = self._get_service()

        request = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": self.config.sheet_name,
                        }
                    }
                }
            ]
        }
        result = (
            service.spreadsheets()
            .batchUpdate(
                spreadsheetId=self.config.spreadsheet_id,
                body=request,
            )
            .execute()
        )

        self._sheet_id = result["replies"][0]["addSheet"]["properties"]["sheetId"]
        self.ensure_headers()

    # =========================================================================
    # Header Management
    # =========================================================================

    def ensure_headers(self) -> bool:
        """Ensure headers exist in the sheet. Returns True if headers were created/updated."""
        service = self._get_service()

        # Use column letter for last column
        last_col = column_index_to_letter(len(self.column_names) - 1)
        range_name = f"{self.config.sheet_name}!A1:{last_col}1"

        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=range_name,
            )
            .execute()
        )

        values = result.get("values", [])
        if values and values[0] == self.column_names:
            return False  # Headers already correct

        # Write headers
        service.spreadsheets().values().update(
            spreadsheetId=self.config.spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body={"values": [self.column_names]},
        ).execute()

        # Format headers
        try:
            self._format_headers()
        except Exception as e:
            logger.warning(f"Could not format headers: {e}")

        return True

    def _format_headers(self):
        """Apply formatting to header row."""
        service = self._get_service()
        sheet_id = self._get_sheet_id()

        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor)",
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
        ]

        service.spreadsheets().batchUpdate(
            spreadsheetId=self.config.spreadsheet_id,
            body={"requests": requests},
        ).execute()

    # =========================================================================
    # UID Cache Management
    # =========================================================================

    def _refresh_uid_cache(self):
        """Refresh the pickup_uid -> row_number cache from sheet."""
        service = self._get_service()

        # Read column A (pickup_uid)
        range_name = f"{self.config.sheet_name}!A:A"
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=range_name,
            )
            .execute()
        )

        self._uid_cache.clear()
        values = result.get("values", [])

        for i, row in enumerate(values):
            if i == 0:  # Skip header
                continue
            if row and row[0]:
                self._uid_cache[row[0]] = i + 1  # 1-indexed row number

        self._cache_valid = True
        logger.debug(f"UID cache refreshed: {len(self._uid_cache)} entries")

    def _find_row_by_uid(self, pickup_uid: str) -> Optional[int]:
        """
        Find row number by pickup_uid.
        Returns 1-indexed row number or None if not found.
        """
        if not self._cache_valid:
            self._refresh_uid_cache()

        return self._uid_cache.get(pickup_uid)

    def _invalidate_cache(self):
        """Invalidate the UID cache."""
        self._cache_valid = False

    # =========================================================================
    # Row Reading
    # =========================================================================

    def _read_row(self, row_number: int) -> dict[str, Any]:
        """Read a full row by row number. Returns dict of column_name -> value."""
        service = self._get_service()

        last_col = column_index_to_letter(len(self.column_names) - 1)
        range_name = f"{self.config.sheet_name}!A{row_number}:{last_col}{row_number}"

        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=range_name,
            )
            .execute()
        )

        values = result.get("values", [[]])[0]

        row_dict = {}
        for i, col_name in enumerate(self.column_names):
            row_dict[col_name] = values[i] if i < len(values) else ""

        return row_dict

    def _is_row_locked(self, row_number: int) -> bool:
        """Check if a row has lock_import=TRUE."""
        lock_col_idx = get_column_index("lock_import")
        if lock_col_idx < 0:
            return False

        service = self._get_service()
        col_letter = column_index_to_letter(lock_col_idx)
        range_name = f"{self.config.sheet_name}!{col_letter}{row_number}"

        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=range_name,
            )
            .execute()
        )

        values = result.get("values", [[]])
        if values and values[0]:
            return str(values[0][0]).upper() == "TRUE"
        return False

    # =========================================================================
    # Record to Row Conversion
    # =========================================================================

    def _prepare_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Prepare a record dict for writing.
        Computes pickup_uid and final values.
        """
        prepared = dict(record)
        now = datetime.now().isoformat()

        # Compute pickup_uid if not provided
        if not prepared.get("pickup_uid"):
            prepared["pickup_uid"] = compute_pickup_uid(
                auction=prepared.get("auction_detected", prepared.get("auction", "UNKNOWN")),
                gate_pass=prepared.get("gate_pass_base", prepared.get("gate_pass")),
                lot_number=prepared.get("auction_ref_base", prepared.get("lot_number")),
                stock_number=prepared.get("stock_number"),
                vin=prepared.get("vin_base", prepared.get("vin")),
                attachment_hash=prepared.get("attachment_hash"),
            )

        # Set timestamps
        prepared.setdefault("created_at", now)
        prepared["last_ingested_at"] = now
        prepared["automation_version"] = AUTOMATION_VERSION

        # Map legacy field names to schema v1 names
        field_mappings = {
            "auction": "auction_detected",
            "vin": "vin_base",
            "vehicle_year": "year_base",
            "vehicle_make": "make_base",
            "vehicle_model": "model_base",
            "lot_number": "auction_ref_base",
            "gate_pass": "gate_pass_base",
            "pickup_city": "pickup_city_base",
            "pickup_state": "pickup_state_base",
            "pickup_zip": "pickup_zip_base",
            "mileage": "mileage_base",
            "color": "color_base",
            "score": "extraction_score",
        }
        for old_name, new_name in field_mappings.items():
            if old_name in prepared and new_name not in prepared:
                prepared[new_name] = prepared[old_name]

        # Normalize extraction_score to 0-1 range
        if "extraction_score" in prepared:
            score = prepared["extraction_score"]
            if score is not None and score > 1:
                prepared["extraction_score"] = score / 100.0

        return prepared

    def _compute_final_values(
        self, base_row: dict[str, Any], existing_row: dict[str, Any] = None
    ) -> dict[str, Any]:
        """
        Compute all *_final values based on base and override.
        If existing_row is provided, use its override values.
        """
        row = dict(base_row)

        # Fields that have base/override/final triplets
        triplet_fields = [
            "vin",
            "year",
            "make",
            "model",
            "vehicle_type",
            "running",
            "mileage",
            "color",
            "pickup_address1",
            "pickup_city",
            "pickup_state",
            "pickup_zip",
            "pickup_contact",
            "pickup_phone",
            "warehouse_id",
            "price",
            "trailer_type",
            "pickup_date",
            "delivery_date",
        ]

        for field in triplet_fields:
            base_key = f"{field}_base"
            override_key = f"{field}_override"
            final_key = f"{field}_final"

            base_value = row.get(base_key, "")

            # Get override from existing row if available
            override_value = ""
            if existing_row:
                override_value = existing_row.get(override_key, "")

            # Compute final
            row[final_key] = compute_final_value(base_value, override_value)

        return row

    def _row_to_values(self, row: dict[str, Any]) -> list[Any]:
        """Convert row dict to list of values matching column order."""
        values = []
        for col_name in self.column_names:
            value = row.get(col_name, "")

            # Handle special types
            if value is None:
                value = ""
            elif isinstance(value, bool):
                value = "TRUE" if value else "FALSE"
            elif isinstance(value, (list, dict)):
                value = json.dumps(value)
            elif isinstance(value, float):
                value = round(value, 4)

            values.append(value)

        return values

    # =========================================================================
    # Upsert Operations
    # =========================================================================

    def upsert_record(self, record: dict[str, Any], mode: str = "ingest") -> dict[str, Any]:
        """
        Upsert a single record to the Pickups sheet.

        Args:
            record: Record data with extraction results
            mode: "ingest" (normal) or "force" (override lock)

        Returns:
            Dict with:
                - action: "created" | "updated" | "skipped"
                - pickup_uid: the record's UID
                - row_number: 1-indexed row number
                - message: description of what happened
        """
        self.ensure_headers()

        # Prepare record (compute UID, timestamps, etc.)
        prepared = self._prepare_record(record)
        pickup_uid = prepared["pickup_uid"]

        # Find existing row
        row_number = self._find_row_by_uid(pickup_uid)

        if row_number is None:
            # New record - append
            return self._append_new_record(prepared)
        else:
            # Existing record - update
            return self._update_existing_record(prepared, row_number, mode)

    def _append_new_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Append a new record to the sheet."""
        service = self._get_service()

        # Set defaults for new records
        record.setdefault("status", "NEW")
        record.setdefault("cd_export_enabled", "TRUE")
        record.setdefault("cd_export_status", "NOT_READY")
        record.setdefault("lock_import", "FALSE")

        # Compute final values (no existing overrides)
        row = self._compute_final_values(record)
        values = self._row_to_values(row)

        # Append
        range_name = f"{self.config.sheet_name}!A:A"
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.config.spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [values]},
            )
            .execute()
        )

        # Update cache
        updated_range = result.get("updates", {}).get("updatedRange", "")
        # Extract row number from range like "Pickups!A5:BZ5"
        row_number = None
        if updated_range:
            import re

            match = re.search(r"!A(\d+):", updated_range)
            if match:
                row_number = int(match.group(1))
                self._uid_cache[record["pickup_uid"]] = row_number

        logger.info(f"Created new row for pickup_uid={record['pickup_uid']}")

        return {
            "action": "created",
            "pickup_uid": record["pickup_uid"],
            "row_number": row_number,
            "message": "New record appended",
        }

    def _update_existing_record(
        self,
        record: dict[str, Any],
        row_number: int,
        mode: str,
    ) -> dict[str, Any]:
        """Update an existing record, respecting column classes and lock_import."""
        service = self._get_service()

        # Check lock
        if mode != "force" and self._is_row_locked(row_number):
            # Only update last_ingested_at
            timestamp_col = get_column_letter("last_ingested_at")
            range_name = f"{self.config.sheet_name}!{timestamp_col}{row_number}"
            service.spreadsheets().values().update(
                spreadsheetId=self.config.spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body={"values": [[datetime.now().isoformat()]]},
            ).execute()

            logger.info(f"Skipped locked row {row_number} for pickup_uid={record['pickup_uid']}")
            return {
                "action": "skipped",
                "pickup_uid": record["pickup_uid"],
                "row_number": row_number,
                "message": "Row locked (lock_import=TRUE)",
            }

        # Read existing row to preserve user-owned columns
        existing = self._read_row(row_number)

        # Compute final values using existing overrides
        row = self._compute_final_values(record, existing)

        # Only update system columns (not immutable, not user-owned)
        updatable_cols = get_updatable_columns_on_ingest()

        # Also update computed *_final columns
        final_cols = [col for col in self.column_names if col.endswith("_final")]
        all_update_cols = set(updatable_cols) | set(final_cols)

        # Build update data - only the columns we're allowed to change
        updates = []
        for col_name in all_update_cols:
            col_idx = get_column_index(col_name)
            if col_idx >= 0:
                col_letter = column_index_to_letter(col_idx)
                value = row.get(col_name, "")

                # Handle types
                if value is None:
                    value = ""
                elif isinstance(value, bool):
                    value = "TRUE" if value else "FALSE"
                elif isinstance(value, (list, dict)):
                    value = json.dumps(value)
                elif isinstance(value, float):
                    value = round(value, 4)

                updates.append(
                    {
                        "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                        "values": [[value]],
                    }
                )

        if updates:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.config.spreadsheet_id,
                body={
                    "valueInputOption": "USER_ENTERED",
                    "data": updates,
                },
            ).execute()

        logger.info(f"Updated row {row_number} for pickup_uid={record['pickup_uid']}")

        return {
            "action": "updated",
            "pickup_uid": record["pickup_uid"],
            "row_number": row_number,
            "message": f"Updated {len(updates)} columns",
        }

    def upsert_batch(
        self,
        records: list[dict[str, Any]],
        mode: str = "ingest",
    ) -> dict[str, Any]:
        """
        Upsert multiple records using batch operations.

        Returns:
            Dict with:
                - created: count of new records
                - updated: count of updated records
                - skipped: count of skipped (locked) records
                - results: list of individual results
        """
        if not records:
            return {"created": 0, "updated": 0, "skipped": 0, "results": []}

        self.ensure_headers()
        self._refresh_uid_cache()  # Ensure cache is fresh for batch

        created = 0
        updated = 0
        skipped = 0
        results = []

        # Separate new vs existing records
        to_append = []
        to_update = []

        for record in records:
            prepared = self._prepare_record(record)
            pickup_uid = prepared["pickup_uid"]
            row_number = self._uid_cache.get(pickup_uid)

            if row_number is None:
                to_append.append(prepared)
            else:
                to_update.append((prepared, row_number))

        # Batch append new records
        if to_append:
            append_results = self._batch_append(to_append)
            created = len(append_results)
            results.extend(append_results)

        # Batch update existing records
        if to_update:
            update_results = self._batch_update(to_update, mode)
            for r in update_results:
                if r["action"] == "updated":
                    updated += 1
                elif r["action"] == "skipped":
                    skipped += 1
            results.extend(update_results)

        logger.info(
            f"Batch upsert complete: {created} created, {updated} updated, {skipped} skipped"
        )

        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "results": results,
        }

    def _batch_append(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Append multiple new records in a single API call."""
        service = self._get_service()

        rows = []
        for record in records:
            record.setdefault("status", "NEW")
            record.setdefault("cd_export_enabled", "TRUE")
            record.setdefault("cd_export_status", "NOT_READY")
            record.setdefault("lock_import", "FALSE")
            row = self._compute_final_values(record)
            rows.append(self._row_to_values(row))

        range_name = f"{self.config.sheet_name}!A:A"
        service.spreadsheets().values().append(
            spreadsheetId=self.config.spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()

        # Invalidate cache after append
        self._invalidate_cache()

        return [
            {
                "action": "created",
                "pickup_uid": r["pickup_uid"],
                "message": "Batch appended",
            }
            for r in records
        ]

    def _batch_update(
        self,
        records_with_rows: list[tuple[dict[str, Any], int]],
        mode: str,
    ) -> list[dict[str, Any]]:
        """Update multiple existing records using batchUpdate."""
        service = self._get_service()
        results = []

        # First, read all existing rows to get overrides
        # This is done row by row for accuracy (could be optimized with batch read)
        existing_rows = {}
        locked_rows = set()

        for record, row_number in records_with_rows:
            existing = self._read_row(row_number)
            existing_rows[row_number] = existing

            if mode != "force" and str(existing.get("lock_import", "")).upper() == "TRUE":
                locked_rows.add(row_number)

        # Build batch update data
        all_updates = []

        updatable_cols = get_updatable_columns_on_ingest()
        final_cols = [col for col in self.column_names if col.endswith("_final")]
        all_update_cols = set(updatable_cols) | set(final_cols)

        for record, row_number in records_with_rows:
            if row_number in locked_rows:
                # Only update timestamp for locked rows
                timestamp_col = get_column_letter("last_ingested_at")
                all_updates.append(
                    {
                        "range": f"{self.config.sheet_name}!{timestamp_col}{row_number}",
                        "values": [[datetime.now().isoformat()]],
                    }
                )
                results.append(
                    {
                        "action": "skipped",
                        "pickup_uid": record["pickup_uid"],
                        "row_number": row_number,
                        "message": "Row locked",
                    }
                )
                continue

            # Compute final values with existing overrides
            existing = existing_rows[row_number]
            row = self._compute_final_values(record, existing)

            # Build updates for this row
            for col_name in all_update_cols:
                col_idx = get_column_index(col_name)
                if col_idx >= 0:
                    col_letter = column_index_to_letter(col_idx)
                    value = row.get(col_name, "")

                    if value is None:
                        value = ""
                    elif isinstance(value, bool):
                        value = "TRUE" if value else "FALSE"
                    elif isinstance(value, (list, dict)):
                        value = json.dumps(value)
                    elif isinstance(value, float):
                        value = round(value, 4)

                    all_updates.append(
                        {
                            "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                            "values": [[value]],
                        }
                    )

            results.append(
                {
                    "action": "updated",
                    "pickup_uid": record["pickup_uid"],
                    "row_number": row_number,
                    "message": "Batch updated",
                }
            )

        # Execute batch update
        if all_updates:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.config.spreadsheet_id,
                body={
                    "valueInputOption": "USER_ENTERED",
                    "data": all_updates,
                },
            ).execute()

        return results

    # =========================================================================
    # Legacy Compatibility Methods
    # =========================================================================

    def append_record(self, record: dict[str, Any], run_id: str = None) -> bool:
        """
        Legacy method - now uses upsert internally.
        """
        if run_id:
            record["run_id"] = run_id
        result = self.upsert_record(record)
        return result["action"] in ("created", "updated")

    def write_batch(self, records: list[dict[str, Any]], run_id: str = None) -> int:
        """
        Legacy method - now uses upsert_batch internally.
        Returns count of rows created/updated.
        """
        if run_id:
            for record in records:
                record["run_id"] = run_id
        result = self.upsert_batch(records)
        return result["created"] + result["updated"]

    def find_by_hash(self, attachment_hash: str) -> Optional[int]:
        """Find a row by attachment hash. Returns row number or None."""
        service = self._get_service()

        hash_col_idx = get_column_index("attachment_hash")
        if hash_col_idx < 0:
            return None

        col_letter = column_index_to_letter(hash_col_idx)
        range_name = f"{self.config.sheet_name}!{col_letter}:{col_letter}"

        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=range_name,
            )
            .execute()
        )

        values = result.get("values", [])
        for i, row in enumerate(values):
            if row and row[0] == attachment_hash:
                return i + 1  # 1-indexed

        return None

    def find_by_uid(self, pickup_uid: str) -> Optional[int]:
        """Find a row by pickup_uid. Returns row number or None."""
        return self._find_row_by_uid(pickup_uid)

    def is_duplicate(self, attachment_hash: str) -> bool:
        """Check if a record with this hash already exists."""
        return self.find_by_hash(attachment_hash) is not None

    def get_row(self, pickup_uid: str) -> Optional[dict[str, Any]]:
        """Get a full row by pickup_uid."""
        row_number = self._find_row_by_uid(pickup_uid)
        if row_number:
            return self._read_row(row_number)
        return None
