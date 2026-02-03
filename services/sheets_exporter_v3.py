"""
Google Sheets Exporter V3 - Source of Truth Implementation

This module implements the "Source of Truth" upsert logic for Google Sheets
as specified in the CD Listings API V2 integration.

Key behaviors:
1. Sheet is the ONLY source of data for CD export
2. Ingestion does upsert but cannot break manual edits
3. Non-destructive upsert (fill-only when row_status != NEW)
4. Lock flags protect groups of fields
5. Override fields are NEVER written by ingestion

Schema Version: 3
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from schemas.sheets_schema_v3 import (
    COLUMNS,
    ColumnClass,
    RowStatus,
    WarehouseMode,
    generate_dispatch_id,
    get_column_index,
    get_column_names,
    get_delivery_columns,
    get_release_notes_columns,
    get_system_audit_columns,
)

logger = logging.getLogger(__name__)


class SheetsExporterV3:
    """
    Google Sheets exporter with Source of Truth semantics.

    Implements non-destructive upsert:
    - INSERT: Creates new row with all extracted data, row_status=NEW
    - UPDATE: Respects locks, override pattern, fill-only mode
    """

    def __init__(self, sheets_config, sheet_name: str = "Pickups"):
        """
        Initialize the exporter.

        Args:
            sheets_config: Sheets configuration with credentials and spreadsheet_id
            sheet_name: Name of the sheet tab to use
        """
        self.config = sheets_config
        self.sheet_name = sheet_name
        self._service = None
        self._headers_cache: Optional[list[str]] = None

    def _get_service(self):
        """Get or create Google Sheets API service."""
        if self._service is None:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            credentials = service_account.Credentials.from_service_account_file(
                self.config.credentials_file,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            self._service = build("sheets", "v4", credentials=credentials)
        return self._service

    def _get_headers(self) -> list[str]:
        """Get current headers from the sheet."""
        if self._headers_cache is not None:
            return self._headers_cache

        service = self._get_service()
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"{self.sheet_name}!1:1",
            )
            .execute()
        )

        values = result.get("values", [])
        self._headers_cache = values[0] if values else []
        return self._headers_cache

    def ensure_headers(self) -> bool:
        """
        Ensure sheet has correct headers.
        Returns True if headers were created/updated.
        """
        service = self._get_service()
        expected_headers = get_column_names()

        # Get current headers
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"{self.sheet_name}!1:1",
            )
            .execute()
        )

        current_headers = result.get("values", [[]])[0]

        if current_headers == expected_headers:
            return False

        # Update headers
        service.spreadsheets().values().update(
            spreadsheetId=self.config.spreadsheet_id,
            range=f"{self.sheet_name}!A1",
            valueInputOption="RAW",
            body={"values": [expected_headers]},
        ).execute()

        self._headers_cache = expected_headers
        return True

    def _find_row_by_dispatch_id(self, dispatch_id: str) -> Optional[tuple[int, dict[str, Any]]]:
        """
        Find row by dispatch_id.

        Returns:
            Tuple of (row_number, row_data) or None if not found.
            row_number is 1-based (for Sheets API).
        """
        service = self._get_service()
        headers = self._get_headers()

        if "dispatch_id" not in headers:
            return None

        dispatch_id_col = headers.index("dispatch_id")

        # Get all rows
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"{self.sheet_name}!A:ZZ",
            )
            .execute()
        )

        rows = result.get("values", [])
        if len(rows) <= 1:
            return None

        # Search for dispatch_id
        for row_idx, row in enumerate(rows[1:], start=2):  # Skip header, 1-based
            if len(row) > dispatch_id_col and row[dispatch_id_col] == dispatch_id:
                # Convert to dict
                row_dict = {}
                for i, header in enumerate(headers):
                    if i < len(row):
                        row_dict[header] = row[i]
                    else:
                        row_dict[header] = ""
                return (row_idx, row_dict)

        return None

    def _fallback_find_row(
        self,
        auction_source: str,
        gate_pass: Optional[str] = None,
        auction_reference: Optional[str] = None,
        vin: Optional[str] = None,
        attachment_hash: Optional[str] = None,
    ) -> Optional[tuple[int, dict[str, Any]]]:
        """
        Fallback matching when dispatch_id is not available.

        Match priority:
        1. (auction_source, gate_pass) if gate_pass exists
        2. (auction_source, auction_reference) if auction_reference exists
        3. (vin) if vin exists
        4. (attachment_hash) if attachment_hash exists

        Returns:
            Tuple of (row_number, row_data) or None if not found.
        """
        service = self._get_service()
        headers = self._get_headers()

        # Get all rows
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"{self.sheet_name}!A:ZZ",
            )
            .execute()
        )

        rows = result.get("values", [])
        if len(rows) <= 1:
            return None

        # Get column indices
        def get_col_idx(name: str) -> int:
            return headers.index(name) if name in headers else -1

        auction_idx = get_col_idx("auction_source")
        gp_idx = get_col_idx("gate_pass")
        ref_idx = get_col_idx("auction_reference")
        vin_idx = get_col_idx("vehicle_vin")
        hash_idx = get_col_idx("attachment_hash")

        def get_cell(row: list[str], idx: int) -> str:
            if idx < 0 or idx >= len(row):
                return ""
            return str(row[idx]).strip()

        for row_idx, row in enumerate(rows[1:], start=2):
            row_auction = get_cell(row, auction_idx)
            row_gp = get_cell(row, gp_idx)
            row_ref = get_cell(row, ref_idx)
            row_vin = get_cell(row, vin_idx)
            row_hash = get_cell(row, hash_idx)

            matched = False

            # Priority 1: auction_source + gate_pass
            if gate_pass and gate_pass.strip():
                if row_auction == auction_source and row_gp.lower() == gate_pass.strip().lower():
                    matched = True

            # Priority 2: auction_source + auction_reference
            elif auction_reference and auction_reference.strip():
                if (
                    row_auction == auction_source
                    and row_ref.lower() == auction_reference.strip().lower()
                ):
                    matched = True

            # Priority 3: vin
            elif vin and vin.strip():
                if row_vin.upper() == vin.strip().upper():
                    matched = True

            # Priority 4: attachment_hash
            elif attachment_hash and attachment_hash.strip():
                if row_hash.lower() == attachment_hash.strip().lower():
                    matched = True

            if matched:
                row_dict = {}
                for i, header in enumerate(headers):
                    if i < len(row):
                        row_dict[header] = row[i]
                    else:
                        row_dict[header] = ""
                return (row_idx, row_dict)

        return None

    def upsert_record(
        self,
        extracted_record: dict[str, Any],
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """
        Upsert a record using Source of Truth semantics.

        Args:
            extracted_record: Data extracted from PDF/email
            force_refresh: If True, overwrite even non-empty fields (dangerous, default OFF)

        Returns:
            Dict with:
            - action: "insert" | "update"
            - dispatch_id: The dispatch_id of the row
            - updated_fields: List of fields that were updated
            - skipped_fields: List of {field, reason} for fields not updated
            - protection_snapshot: {row_status, locks, warehouse_mode}
        """
        self.ensure_headers()

        # Extract key fields for matching
        dispatch_id = extracted_record.get("dispatch_id")
        auction_source = extracted_record.get("auction_source", "UNKNOWN")
        gate_pass = extracted_record.get("gate_pass")
        auction_reference = extracted_record.get("auction_reference")
        vin = extracted_record.get("vehicle_vin")
        attachment_hash = extracted_record.get("attachment_hash")

        # Try to find existing row
        existing = None

        if dispatch_id:
            existing = self._find_row_by_dispatch_id(dispatch_id)

        if not existing:
            # Fallback matching
            existing = self._fallback_find_row(
                auction_source=auction_source,
                gate_pass=gate_pass,
                auction_reference=auction_reference,
                vin=vin,
                attachment_hash=attachment_hash,
            )

        if existing:
            # UPDATE
            row_number, existing_data = existing
            # Use existing dispatch_id if we found via fallback
            if not dispatch_id:
                dispatch_id = existing_data.get("dispatch_id")
                extracted_record["dispatch_id"] = dispatch_id
            return self._update_existing_row(
                extracted_record,
                row_number,
                existing_data,
                force_refresh,
            )
        else:
            # INSERT
            if not dispatch_id:
                dispatch_id = generate_dispatch_id(
                    auction_source=auction_source,
                    gate_pass=gate_pass,
                    auction_reference=auction_reference,
                    vin=vin,
                    attachment_hash=attachment_hash,
                )
                extracted_record["dispatch_id"] = dispatch_id
            return self._insert_new_row(extracted_record)

    def _insert_new_row(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Insert a new row with all extracted data.

        Sets:
        - row_status = NEW
        - warehouse_selected_mode = AUTO (default)
        - lock_* = FALSE (default)
        - ingested_at = now
        - updated_at = now
        """
        headers = self._get_headers()
        now = datetime.utcnow().isoformat() + "Z"

        # Build row with defaults
        row_data = {}
        for col in COLUMNS:
            if col.default is not None:
                row_data[col.name] = col.default

        # Apply extracted data (skip override columns)
        for key, value in record.items():
            if key in headers:
                col = next((c for c in COLUMNS if c.name == key), None)
                # Never write to OVERRIDE columns
                if col and col.col_class == ColumnClass.OVERRIDE:
                    continue
                row_data[key] = value

        # Set system fields
        row_data["row_status"] = RowStatus.NEW.value
        row_data["ingested_at"] = now
        row_data["updated_at"] = now

        # Ensure defaults
        if not row_data.get("warehouse_selected_mode"):
            row_data["warehouse_selected_mode"] = WarehouseMode.AUTO.value
        if not row_data.get("pickup_stop_number"):
            row_data["pickup_stop_number"] = "1"
        if not row_data.get("dropoff_stop_number"):
            row_data["dropoff_stop_number"] = "2"

        # Convert to row array
        row_values = []
        for header in headers:
            row_values.append(str(row_data.get(header, "") or ""))

        # Append to sheet
        service = self._get_service()
        service.spreadsheets().values().append(
            spreadsheetId=self.config.spreadsheet_id,
            range=f"{self.sheet_name}!A:A",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row_values]},
        ).execute()

        logger.info(f"Inserted new row: dispatch_id={row_data.get('dispatch_id')}")

        return {
            "action": "insert",
            "dispatch_id": row_data.get("dispatch_id"),
            "updated_fields": list(row_data.keys()),
            "skipped_fields": [],
            "protection_snapshot": {
                "row_status": RowStatus.NEW.value,
                "lock_all": False,
                "lock_delivery": False,
                "lock_release_notes": False,
                "warehouse_selected_mode": row_data.get("warehouse_selected_mode"),
            },
        }

    def _update_existing_row(
        self,
        record: dict[str, Any],
        row_number: int,
        existing_data: dict[str, Any],
        force_refresh: bool,
    ) -> dict[str, Any]:
        """
        Update existing row with Source of Truth rules.

        Rules:
        1. lock_all=TRUE -> only update SYSTEM/AUDIT fields
        2. row_status != NEW -> fill-only mode (only fill empty fields)
        3. warehouse_selected_mode=MANUAL or lock_delivery=TRUE -> don't touch delivery
        4. lock_release_notes=TRUE -> don't touch release notes fields
        5. OVERRIDE columns -> NEVER write
        6. force_refresh=TRUE -> overwrite even non-empty (dangerous)
        """
        headers = self._get_headers()
        now = datetime.utcnow().isoformat() + "Z"

        # Read protection flags
        row_status = existing_data.get("row_status", RowStatus.NEW.value)
        lock_all = str(existing_data.get("lock_all", "FALSE")).upper() == "TRUE"
        lock_delivery = str(existing_data.get("lock_delivery", "FALSE")).upper() == "TRUE"
        lock_release_notes = str(existing_data.get("lock_release_notes", "FALSE")).upper() == "TRUE"
        warehouse_mode = existing_data.get("warehouse_selected_mode", WarehouseMode.AUTO.value)

        # Determine update mode
        is_fill_only = row_status != RowStatus.NEW.value and not force_refresh

        # System/audit columns that are always updatable
        system_audit_cols = set(get_system_audit_columns())

        # Delivery columns (protected by lock_delivery or MANUAL mode)
        delivery_cols = set(get_delivery_columns())
        delivery_cols.add("delivery_warehouse_id")
        delivery_cols.add("warehouse_recommended_id")

        # Release notes columns (protected by lock_release_notes)
        release_notes_cols = set(get_release_notes_columns())

        updated_fields = []
        skipped_fields = []

        # Build updates
        updates = {}

        for key, new_value in record.items():
            if key not in headers:
                continue

            col = next((c for c in COLUMNS if c.name == key), None)
            if not col:
                continue

            old_value = existing_data.get(key, "")
            old_value_str = str(old_value).strip() if old_value else ""
            new_value_str = str(new_value).strip() if new_value else ""

            # Rule 5: Never write to OVERRIDE columns
            if col.col_class == ColumnClass.OVERRIDE:
                if new_value_str:
                    skipped_fields.append({"field": key, "reason": "override_column"})
                continue

            # Rule 1: lock_all blocks everything except SYSTEM/AUDIT
            if lock_all and key not in system_audit_cols:
                if new_value_str and new_value_str != old_value_str:
                    skipped_fields.append({"field": key, "reason": "lock_all"})
                continue

            # Rule 3: lock_delivery or MANUAL mode blocks delivery fields
            if key in delivery_cols:
                if lock_delivery:
                    if new_value_str and new_value_str != old_value_str:
                        skipped_fields.append({"field": key, "reason": "lock_delivery"})
                    continue
                if warehouse_mode == WarehouseMode.MANUAL.value:
                    if new_value_str and new_value_str != old_value_str:
                        skipped_fields.append({"field": key, "reason": "warehouse_manual"})
                    continue

            # Rule 4: lock_release_notes blocks release notes fields
            if key in release_notes_cols and lock_release_notes:
                if new_value_str and new_value_str != old_value_str:
                    skipped_fields.append({"field": key, "reason": "lock_release_notes"})
                continue

            # Rule 2: fill-only mode (only fill empty fields)
            if is_fill_only:
                if old_value_str:
                    # Field has value, don't overwrite
                    if new_value_str and new_value_str != old_value_str:
                        skipped_fields.append({"field": key, "reason": "fill_only_mode"})
                    continue

            # Apply update
            if new_value_str != old_value_str:
                updates[key] = new_value
                updated_fields.append(key)

        # Always update updated_at
        updates["updated_at"] = now
        if "updated_at" not in updated_fields:
            updated_fields.append("updated_at")

        # Write updates to sheet
        if updates:
            row_values = []
            for header in headers:
                if header in updates:
                    row_values.append(str(updates[header]) if updates[header] else "")
                else:
                    row_values.append(str(existing_data.get(header, "") or ""))

            service = self._get_service()
            service.spreadsheets().values().update(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"{self.sheet_name}!A{row_number}",
                valueInputOption="RAW",
                body={"values": [row_values]},
            ).execute()

        logger.info(
            f"Updated row {row_number}: dispatch_id={record.get('dispatch_id')}, "
            f"updated={len(updated_fields)}, skipped={len(skipped_fields)}"
        )

        return {
            "action": "update",
            "dispatch_id": record.get("dispatch_id"),
            "updated_fields": updated_fields,
            "skipped_fields": skipped_fields,
            "protection_snapshot": {
                "row_status": row_status,
                "lock_all": lock_all,
                "lock_delivery": lock_delivery,
                "lock_release_notes": lock_release_notes,
                "warehouse_selected_mode": warehouse_mode,
            },
        }

    def get_row_by_dispatch_id(self, dispatch_id: str) -> Optional[dict[str, Any]]:
        """
        Get a single row by dispatch_id.

        Returns:
            Row data as dict, or None if not found.
        """
        result = self._find_row_by_dispatch_id(dispatch_id)
        if result:
            return result[1]
        return None

    def get_rows_by_status(
        self,
        statuses: list[RowStatus],
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Get rows with specific status(es).

        Args:
            statuses: List of RowStatus values to filter by
            limit: Maximum number of rows to return

        Returns:
            List of row data dicts
        """
        service = self._get_service()
        headers = self._get_headers()

        status_idx = get_column_index("row_status")
        if status_idx < 0:
            return []

        # Get all rows
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.config.spreadsheet_id,
                range=f"{self.sheet_name}!A:ZZ",
            )
            .execute()
        )

        rows = result.get("values", [])
        if len(rows) <= 1:
            return []

        status_values = {s.value for s in statuses}
        matching_rows = []

        for row in rows[1:]:
            if status_idx >= len(row):
                continue

            row_status = row[status_idx]
            if row_status in status_values:
                row_dict = {}
                for i, header in enumerate(headers):
                    if i < len(row):
                        row_dict[header] = row[i]
                    else:
                        row_dict[header] = ""
                matching_rows.append(row_dict)

                if limit and len(matching_rows) >= limit:
                    break

        return matching_rows

    def update_row_status(
        self,
        dispatch_id: str,
        new_status: RowStatus,
        error_message: Optional[str] = None,
        cd_listing_id: Optional[str] = None,
    ) -> bool:
        """
        Update row status and related audit fields.

        Args:
            dispatch_id: Row identifier
            new_status: New status to set
            error_message: Error message (for ERROR status)
            cd_listing_id: CD listing ID (for EXPORTED status)

        Returns:
            True if update succeeded
        """
        result = self._find_row_by_dispatch_id(dispatch_id)
        if not result:
            logger.warning(f"Row not found for status update: {dispatch_id}")
            return False

        row_number, existing_data = result
        headers = self._get_headers()
        now = datetime.utcnow().isoformat() + "Z"

        # Build updates
        updates = {
            "row_status": new_status.value,
            "updated_at": now,
        }

        if new_status == RowStatus.EXPORTED:
            updates["cd_exported_at"] = now
            if cd_listing_id:
                updates["cd_listing_id"] = cd_listing_id

        if new_status == RowStatus.ERROR:
            updates["cd_last_error"] = error_message or "Unknown error"
            updates["cd_last_attempt_at"] = now

        if new_status == RowStatus.RETRY:
            updates["cd_last_attempt_at"] = now

        # Build row values
        row_values = []
        for header in headers:
            if header in updates:
                row_values.append(str(updates[header]) if updates[header] else "")
            else:
                row_values.append(str(existing_data.get(header, "") or ""))

        # Write to sheet
        service = self._get_service()
        service.spreadsheets().values().update(
            spreadsheetId=self.config.spreadsheet_id,
            range=f"{self.sheet_name}!A{row_number}",
            valueInputOption="RAW",
            body={"values": [row_values]},
        ).execute()

        logger.info(f"Updated status: dispatch_id={dispatch_id}, status={new_status.value}")
        return True

    def save_payload_snapshot(
        self,
        dispatch_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """
        Save CD payload snapshot for debugging.

        Args:
            dispatch_id: Row identifier
            payload: The CD API payload that was/will be sent

        Returns:
            True if save succeeded
        """
        result = self._find_row_by_dispatch_id(dispatch_id)
        if not result:
            return False

        row_number, existing_data = result
        headers = self._get_headers()

        # Build updates
        updates = {
            "cd_payload_snapshot": json.dumps(payload, default=str),
            "cd_last_attempt_at": datetime.utcnow().isoformat() + "Z",
        }

        # Build row values
        row_values = []
        for header in headers:
            if header in updates:
                row_values.append(str(updates[header]) if updates[header] else "")
            else:
                row_values.append(str(existing_data.get(header, "") or ""))

        # Write to sheet
        service = self._get_service()
        service.spreadsheets().values().update(
            spreadsheetId=self.config.spreadsheet_id,
            range=f"{self.sheet_name}!A{row_number}",
            valueInputOption="RAW",
            body={"values": [row_values]},
        ).execute()

        return True
