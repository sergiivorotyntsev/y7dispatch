"""
Google Sheets Exporter v2 - Upsert by dispatch_id

Source of Truth architecture for CD Listings API V2 export.

Features:
1. Upsert by dispatch_id (primary key)
2. Protected fields (override_*) never overwritten
3. Lock flags (lock_delivery, lock_release_notes, lock_all)
4. State machine (row_status): NEW → READY → EXPORTED
5. Warehouse mode (AUTO/MANUAL) controls delivery updates

Usage:
    exporter = SheetsExporterV2(config)
    result = exporter.upsert_record(record)
    # result = {"action": "insert"|"update", "dispatch_id": "DC-...", "protected_fields": [...]}
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.config import SheetsConfig
from schemas.sheets_schema_v2 import (
    SCHEMA_VERSION,
    column_index_to_letter,
    generate_dispatch_id,
    get_column_index,
    get_column_letter,
    get_column_names,
    get_protected_columns,
    validate_row_for_ready,
)

logger = logging.getLogger(__name__)

AUTOMATION_VERSION = f"v{SCHEMA_VERSION}.0"


class SheetsExporterV2:
    """
    Google Sheets exporter with upsert by dispatch_id.

    The Pickups sheet is the source of truth:
    - All data comes from the sheet for CD export
    - Protected (override_*) fields are never overwritten
    - Lock flags control which field groups can be updated
    """

    def __init__(self, config: SheetsConfig, sheet_name: str = "Pickups"):
        self.config = config
        self.sheet_name = sheet_name
        self.column_names = get_column_names()
        self._service = None
        self._dispatch_id_cache: dict[str, int] = {}  # dispatch_id -> row_number
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

    # =========================================================================
    # Header Management
    # =========================================================================

    def ensure_headers(self) -> bool:
        """Ensure headers exist and match schema. Returns True if updated."""
        service = self._get_service()

        last_col = column_index_to_letter(len(self.column_names) - 1)
        range_name = f"{self.sheet_name}!A1:{last_col}1"

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
            return False

        # Write/update headers
        service.spreadsheets().values().update(
            spreadsheetId=self.config.spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body={"values": [self.column_names]},
        ).execute()

        logger.info(f"Headers updated for {self.sheet_name}")
        return True

    def schema_ensure(self) -> dict[str, Any]:
        """
        Ensure schema is up to date.
        Adds missing columns if needed (migration support).
        """
        service = self._get_service()

        # Get current headers
        range_name = f"{self.sheet_name}!1:1"
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=range_name,
            )
            .execute()
        )

        existing = result.get("values", [[]])[0]
        expected = self.column_names

        if existing == expected:
            return {"status": "ok", "action": "none", "columns": len(expected)}

        # Find missing columns
        missing = [col for col in expected if col not in existing]

        if missing:
            # Add missing columns to the end
            new_headers = existing + missing
            last_col = column_index_to_letter(len(new_headers) - 1)
            range_name = f"{self.sheet_name}!A1:{last_col}1"

            service.spreadsheets().values().update(
                spreadsheetId=self.config.spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [new_headers]},
            ).execute()

            logger.info(f"Added {len(missing)} columns: {missing}")
            return {
                "status": "ok",
                "action": "added_columns",
                "added": missing,
                "columns": len(new_headers),
            }

        # Headers exist but in wrong order - rewrite
        self.ensure_headers()
        return {"status": "ok", "action": "reordered", "columns": len(expected)}

    # =========================================================================
    # Dispatch ID Cache
    # =========================================================================

    def _refresh_dispatch_id_cache(self):
        """Refresh the dispatch_id -> row_number cache."""
        service = self._get_service()

        range_name = f"{self.sheet_name}!A:A"
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=range_name,
            )
            .execute()
        )

        self._dispatch_id_cache.clear()
        values = result.get("values", [])

        for i, row in enumerate(values):
            if i == 0:  # Skip header
                continue
            if row and row[0] and row[0].startswith("DC-"):
                self._dispatch_id_cache[row[0]] = i + 1

        self._cache_valid = True
        logger.debug(f"Dispatch ID cache: {len(self._dispatch_id_cache)} entries")

    def find_row_by_dispatch_id(self, dispatch_id: str) -> Optional[int]:
        """Find row number by dispatch_id. Returns 1-indexed row or None."""
        if not self._cache_valid:
            self._refresh_dispatch_id_cache()
        return self._dispatch_id_cache.get(dispatch_id)

    def _invalidate_cache(self):
        """Invalidate the cache."""
        self._cache_valid = False

    # =========================================================================
    # Row Operations
    # =========================================================================

    def _read_row(self, row_number: int) -> dict[str, Any]:
        """Read a full row. Returns dict of column_name -> value."""
        service = self._get_service()

        last_col = column_index_to_letter(len(self.column_names) - 1)
        range_name = f"{self.sheet_name}!A{row_number}:{last_col}{row_number}"

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

        row_dict = {"_row_number": row_number}
        for i, col_name in enumerate(self.column_names):
            row_dict[col_name] = values[i] if i < len(values) else ""

        return row_dict

    def _get_lock_flags(self, row: dict[str, Any]) -> dict[str, bool]:
        """Get lock flag values from a row."""
        return {
            "lock_all": str(row.get("lock_all", "")).upper() == "TRUE",
            "lock_delivery": str(row.get("lock_delivery", "")).upper() == "TRUE",
            "lock_release_notes": str(row.get("lock_release_notes", "")).upper() == "TRUE",
        }

    def _get_protected_with_values(self, row: dict[str, Any]) -> set[str]:
        """Get set of protected columns that have values."""
        protected = get_protected_columns()
        return {col for col in protected if row.get(col) and str(row.get(col)).strip()}

    def _is_warehouse_manual(self, row: dict[str, Any]) -> bool:
        """Check if warehouse selection is MANUAL."""
        return str(row.get("warehouse_selected_mode", "")).upper() == "MANUAL"

    # =========================================================================
    # Record Preparation
    # =========================================================================

    def _prepare_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Prepare a record for upsert.
        Generates dispatch_id if missing, sets timestamps.
        """
        prepared = dict(record)
        now = datetime.now()

        # Generate dispatch_id if not provided
        if not prepared.get("dispatch_id"):
            prepared["dispatch_id"] = generate_dispatch_id(
                auction_source=prepared.get("auction_source", "UNKNOWN"),
                gate_pass=prepared.get("gate_pass"),
                auction_reference=prepared.get("auction_reference"),
                vin=prepared.get("vin"),
                attachment_hash=prepared.get("attachment_hash"),
                date=now,
            )

        # Timestamps
        prepared.setdefault("ingested_at", now.isoformat())
        prepared["updated_at"] = now.isoformat()

        # Defaults
        prepared.setdefault("row_status", "NEW")
        prepared.setdefault("pickup_country", "US")
        prepared.setdefault("delivery_country", "US")
        prepared.setdefault("price_type", "TOTAL")
        prepared.setdefault("price_currency", "USD")
        prepared.setdefault("allow_full_load", "TRUE")
        prepared.setdefault("allow_ltl", "TRUE")
        prepared.setdefault("warehouse_selected_mode", "AUTO")

        # Normalize boolean fields
        for bool_field in ["operable", "allow_full_load", "allow_ltl"]:
            if bool_field in prepared:
                val = prepared[bool_field]
                if isinstance(val, bool):
                    prepared[bool_field] = "TRUE" if val else "FALSE"
                elif isinstance(val, str):
                    prepared[bool_field] = (
                        "TRUE" if val.lower() in ("true", "yes", "1") else "FALSE"
                    )

        return prepared

    def _row_to_values(self, row: dict[str, Any]) -> list[Any]:
        """Convert row dict to list of values."""
        values = []
        for col_name in self.column_names:
            value = row.get(col_name, "")

            if value is None:
                value = ""
            elif isinstance(value, bool):
                value = "TRUE" if value else "FALSE"
            elif isinstance(value, (list, dict)):
                value = json.dumps(value)
            elif isinstance(value, float):
                value = round(value, 2)

            values.append(value)

        return values

    # =========================================================================
    # Upsert Logic
    # =========================================================================

    def upsert_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Upsert a record by dispatch_id.

        Returns:
            {
                "action": "insert" | "update",
                "dispatch_id": str,
                "row_number": int,
                "protected_fields": list,  # Fields that were not overwritten
                "message": str,
            }
        """
        self.ensure_headers()

        prepared = self._prepare_record(record)
        dispatch_id = prepared["dispatch_id"]

        row_number = self.find_row_by_dispatch_id(dispatch_id)

        if row_number is None:
            return self._insert_new_row(prepared)
        else:
            return self._update_existing_row(prepared, row_number)

    def _insert_new_row(self, record: dict[str, Any]) -> dict[str, Any]:
        """Insert a new row."""
        service = self._get_service()

        values = self._row_to_values(record)

        range_name = f"{self.sheet_name}!A:A"
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
        self._invalidate_cache()

        # Get row number from response
        updated_range = result.get("updates", {}).get("updatedRange", "")
        row_number = None
        if updated_range:
            import re

            match = re.search(r"!A(\d+):", updated_range)
            if match:
                row_number = int(match.group(1))

        logger.info(f"Inserted new row: dispatch_id={record['dispatch_id']}")

        return {
            "action": "insert",
            "dispatch_id": record["dispatch_id"],
            "row_number": row_number,
            "protected_fields": [],
            "message": "New row inserted",
        }

    def _update_existing_row(self, record: dict[str, Any], row_number: int) -> dict[str, Any]:
        """
        Update an existing row, respecting protection rules.
        """
        service = self._get_service()

        # Read existing row
        existing = self._read_row(row_number)

        # Check lock flags
        locks = self._get_lock_flags(existing)

        # Check if row is EXPORTED and not RETRY
        status = existing.get("row_status", "")
        if status == "EXPORTED":
            # Don't update data, only audit fields
            self._update_audit_only(record, row_number, existing)
            return {
                "action": "update",
                "dispatch_id": record["dispatch_id"],
                "row_number": row_number,
                "protected_fields": ["all (status=EXPORTED)"],
                "message": "Only audit fields updated (status=EXPORTED)",
            }

        # Get protected columns that have values
        protected_with_values = self._get_protected_with_values(existing)

        # Check warehouse mode
        warehouse_manual = self._is_warehouse_manual(existing)

        # Apply protection rules
        protected_fields = list(protected_with_values)
        updates = []

        for col_name in self.column_names:
            col_idx = get_column_index(col_name)
            if col_idx < 0:
                continue

            new_value = record.get(col_name, "")
            old_value = existing.get(col_name, "")

            # Skip if no new value
            if new_value is None or (isinstance(new_value, str) and not new_value.strip()):
                continue

            should_update = True

            # Protection rule 1: lock_all
            if locks["lock_all"] and col_name not in ("updated_at", "cd_last_attempt_at"):
                should_update = False
                if col_name not in protected_fields:
                    protected_fields.append(col_name)

            # Protection rule 2: protected (override_*) columns
            elif col_name.startswith("override_"):
                if old_value and str(old_value).strip():
                    should_update = False
                    # Already in protected_fields

            # Protection rule 3: lock_delivery for delivery_* columns
            elif locks["lock_delivery"] and col_name.startswith("delivery_"):
                should_update = False
                if col_name not in protected_fields:
                    protected_fields.append(col_name)

            # Protection rule 4: warehouse_selected_mode=MANUAL
            elif warehouse_manual and col_name.startswith("delivery_"):
                should_update = False
                if col_name not in protected_fields:
                    protected_fields.append(col_name)

            # Protection rule 5: lock_release_notes
            elif locks["lock_release_notes"] and col_name == "release_notes":
                should_update = False
                if col_name not in protected_fields:
                    protected_fields.append(col_name)

            # Protection rule 6: Don't overwrite if override exists
            elif col_name in ("vin", "year", "make", "model", "operable"):
                override_col = f"override_{col_name}"
                override_val = existing.get(override_col, "")
                if override_val and str(override_val).strip():
                    should_update = False
                    if col_name not in protected_fields:
                        protected_fields.append(col_name)

            if should_update:
                # Format value
                if new_value is None:
                    new_value = ""
                elif isinstance(new_value, bool):
                    new_value = "TRUE" if new_value else "FALSE"
                elif isinstance(new_value, (list, dict)):
                    new_value = json.dumps(new_value)
                elif isinstance(new_value, float):
                    new_value = round(new_value, 2)

                col_letter = column_index_to_letter(col_idx)
                updates.append(
                    {
                        "range": f"{self.sheet_name}!{col_letter}{row_number}",
                        "values": [[new_value]],
                    }
                )

        # Execute updates
        if updates:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.config.spreadsheet_id,
                body={
                    "valueInputOption": "USER_ENTERED",
                    "data": updates,
                },
            ).execute()

        logger.info(
            f"Updated row {row_number}: dispatch_id={record['dispatch_id']}, {len(updates)} fields, {len(protected_fields)} protected"
        )

        return {
            "action": "update",
            "dispatch_id": record["dispatch_id"],
            "row_number": row_number,
            "protected_fields": protected_fields,
            "message": f"Updated {len(updates)} fields, {len(protected_fields)} protected",
        }

    def _update_audit_only(self, record: dict[str, Any], row_number: int, existing: dict[str, Any]):
        """Update only audit/tracking fields."""
        service = self._get_service()

        audit_fields = ["updated_at", "extraction_score", "attachment_hash", "email_message_id"]
        updates = []

        for field in audit_fields:
            if field in record:
                col_idx = get_column_index(field)
                if col_idx >= 0:
                    value = record[field]
                    if value is None:
                        value = ""
                    col_letter = column_index_to_letter(col_idx)
                    updates.append(
                        {
                            "range": f"{self.sheet_name}!{col_letter}{row_number}",
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

    # =========================================================================
    # Batch Operations
    # =========================================================================

    def upsert_batch(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Upsert multiple records.

        Returns summary with counts and individual results.
        """
        if not records:
            return {"inserted": 0, "updated": 0, "results": []}

        self.ensure_headers()
        self._refresh_dispatch_id_cache()

        inserted = 0
        updated = 0
        results = []

        for record in records:
            result = self.upsert_record(record)
            results.append(result)

            if result["action"] == "insert":
                inserted += 1
            else:
                updated += 1

        return {
            "inserted": inserted,
            "updated": updated,
            "results": results,
        }

    # =========================================================================
    # Status Management
    # =========================================================================

    def set_row_status(self, dispatch_id: str, status: str, error: str = None) -> bool:
        """
        Set row status by dispatch_id.

        Valid transitions:
        - NEW → READY (after validation)
        - READY → EXPORTED (after CD export)
        - READY → ERROR (on export error)
        - ERROR → READY (after fix)
        - EXPORTED → RETRY (manual retry)
        """
        row_number = self.find_row_by_dispatch_id(dispatch_id)
        if not row_number:
            logger.warning(f"Row not found: {dispatch_id}")
            return False

        service = self._get_service()
        updates = []

        # Update row_status
        status_idx = get_column_index("row_status")
        if status_idx >= 0:
            col_letter = column_index_to_letter(status_idx)
            updates.append(
                {
                    "range": f"{self.sheet_name}!{col_letter}{row_number}",
                    "values": [[status]],
                }
            )

        # Update cd_last_error if provided
        if error is not None:
            error_idx = get_column_index("cd_last_error")
            if error_idx >= 0:
                col_letter = column_index_to_letter(error_idx)
                updates.append(
                    {
                        "range": f"{self.sheet_name}!{col_letter}{row_number}",
                        "values": [[error[:500] if error else ""]],
                    }
                )

        # Update timestamp
        updates.append(
            {
                "range": f"{self.sheet_name}!{get_column_letter('updated_at')}{row_number}",
                "values": [[datetime.now().isoformat()]],
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

        logger.info(f"Set status {status} for {dispatch_id}")
        return True

    def validate_and_set_ready(self, dispatch_id: str) -> dict[str, Any]:
        """
        Validate a row and set status to READY if valid.

        Returns validation result with errors if any.
        """
        row_number = self.find_row_by_dispatch_id(dispatch_id)
        if not row_number:
            return {"valid": False, "errors": ["Row not found"]}

        row = self._read_row(row_number)
        errors = validate_row_for_ready(row)

        if errors:
            self.set_row_status(dispatch_id, "ERROR", "; ".join(errors))
            return {"valid": False, "errors": errors}
        else:
            self.set_row_status(dispatch_id, "READY")
            return {"valid": True, "errors": []}

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_row(self, dispatch_id: str) -> Optional[dict[str, Any]]:
        """Get a row by dispatch_id."""
        row_number = self.find_row_by_dispatch_id(dispatch_id)
        if row_number:
            return self._read_row(row_number)
        return None

    def list_by_status(self, status: str) -> list[dict[str, Any]]:
        """List all rows with a given status."""
        service = self._get_service()

        last_col = column_index_to_letter(len(self.column_names) - 1)
        range_name = f"{self.sheet_name}!A:{last_col}"

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
        if not values:
            return []

        rows = []
        status_idx = get_column_index("row_status")

        for i, row_values in enumerate(values[1:], start=2):
            if status_idx < len(row_values) and row_values[status_idx] == status:
                row_dict = {"_row_number": i}
                for j, col_name in enumerate(self.column_names):
                    row_dict[col_name] = row_values[j] if j < len(row_values) else ""
                rows.append(row_dict)

        return rows

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the sheet."""
        service = self._get_service()

        # Read status column
        status_idx = get_column_index("row_status")
        col_letter = column_index_to_letter(status_idx)
        range_name = f"{self.sheet_name}!{col_letter}:{col_letter}"

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

        stats = {
            "total": len(values) - 1 if values else 0,
            "by_status": {},
        }

        for row in values[1:]:
            status = row[0] if row else "UNKNOWN"
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

        return stats
