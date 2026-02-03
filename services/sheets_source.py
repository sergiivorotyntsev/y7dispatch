"""
Google Sheets Source - Read from Sheets for CD Export

The Pickups sheet is the Source of Truth. This service reads data
from the sheet (using *_final columns) for export to Central Dispatch.

Features:
1. List rows ready for CD export
2. Build PickupRecordFinal from *_final columns
3. Track payload changes via cd_payload_hash
4. Update export status after CD operations
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from core.config import SheetsConfig
from schemas.sheets_schema_v1 import (
    column_index_to_letter,
    compute_payload_hash,
    get_column_index,
    get_column_names,
)

logger = logging.getLogger(__name__)


@dataclass
class PickupRecordFinal:
    """
    Final pickup record built from *_final columns.
    This is what gets exported to Central Dispatch.
    """

    # Identification
    pickup_uid: str
    row_number: int

    # Vehicle
    vin: str = ""
    year: int = 0
    make: str = ""
    model: str = ""
    vehicle_type: str = ""
    running: str = "unknown"
    mileage: int = 0
    color: str = ""

    # Pickup location
    pickup_address1: str = ""
    pickup_city: str = ""
    pickup_state: str = ""
    pickup_zip: str = ""
    pickup_contact: str = ""
    pickup_phone: str = ""

    # Delivery location (from warehouse)
    warehouse_id: str = ""
    warehouse_name: str = ""
    delivery_address1: str = ""
    delivery_city: str = ""
    delivery_state: str = ""
    delivery_zip: str = ""
    delivery_contact: str = ""
    delivery_phone: str = ""

    # Pricing & scheduling
    price: float = 0.0
    trailer_type: str = "open"
    pickup_date: str = ""
    delivery_date: str = ""

    # Metadata
    auction: str = ""
    auction_ref: str = ""
    gate_pass: str = ""
    status: str = ""
    cd_export_status: str = ""
    cd_listing_id: str = ""
    cd_payload_hash: str = ""

    def to_cd_payload(self) -> dict[str, Any]:
        """Convert to Central Dispatch API payload format."""
        # Build CD payload based on cd_field_mapping.yaml
        payload = {
            "listing": {
                "vehicleInfo": {
                    "vin": self.vin,
                    "year": self.year,
                    "make": self.make,
                    "model": self.model,
                    "condition": "OPERABLE" if self.running == "yes" else "INOPERABLE",
                    "vehicleType": self._map_vehicle_type(),
                },
                "originInfo": {
                    "city": self.pickup_city,
                    "state": self.pickup_state,
                    "zip": self.pickup_zip,
                },
                "destinationInfo": {
                    "city": self.delivery_city,
                    "state": self.delivery_state,
                    "zip": self.delivery_zip,
                },
                "trailerType": self.trailer_type.upper() if self.trailer_type else "OPEN",
                "price": self.price,
            }
        }

        # Add optional fields
        if self.pickup_address1:
            payload["listing"]["originInfo"]["address"] = self.pickup_address1
        if self.pickup_contact:
            payload["listing"]["originInfo"]["contact"] = self.pickup_contact
        if self.pickup_phone:
            payload["listing"]["originInfo"]["phone"] = self.pickup_phone

        if self.delivery_address1:
            payload["listing"]["destinationInfo"]["address"] = self.delivery_address1
        if self.delivery_contact:
            payload["listing"]["destinationInfo"]["contact"] = self.delivery_contact
        if self.delivery_phone:
            payload["listing"]["destinationInfo"]["phone"] = self.delivery_phone

        if self.pickup_date:
            payload["listing"]["pickupDate"] = self.pickup_date

        if self.mileage:
            payload["listing"]["vehicleInfo"]["mileage"] = self.mileage
        if self.color:
            payload["listing"]["vehicleInfo"]["color"] = self.color

        # Add notes with lot/gate pass
        notes = []
        if self.auction_ref:
            notes.append(f"Lot #{self.auction_ref}")
        if self.gate_pass:
            notes.append(f"Gate Pass: {self.gate_pass}")
        if notes:
            payload["listing"]["notes"] = " | ".join(notes)

        return payload

    def _map_vehicle_type(self) -> str:
        """Map vehicle type to CD enum."""
        type_map = {
            "car": "CAR",
            "suv": "SUV",
            "truck": "TRUCK",
            "van": "VAN",
            "motorcycle": "MOTORCYCLE",
        }
        return type_map.get(self.vehicle_type.lower(), "CAR") if self.vehicle_type else "CAR"

    def compute_payload_hash(self) -> str:
        """Compute hash of fields that affect the CD payload."""
        final_fields = {
            "vin": self.vin,
            "year": self.year,
            "make": self.make,
            "model": self.model,
            "vehicle_type": self.vehicle_type,
            "running": self.running,
            "mileage": self.mileage,
            "pickup_city": self.pickup_city,
            "pickup_state": self.pickup_state,
            "pickup_zip": self.pickup_zip,
            "delivery_city": self.delivery_city,
            "delivery_state": self.delivery_state,
            "delivery_zip": self.delivery_zip,
            "price": self.price,
            "trailer_type": self.trailer_type,
            "pickup_date": self.pickup_date,
        }
        return compute_payload_hash(final_fields)


class SheetsSource:
    """
    Read pickup data from Google Sheets (Source of Truth).

    Used by CD exporter to get rows ready for export.
    """

    def __init__(self, config: SheetsConfig):
        self.config = config
        self.column_names = get_column_names()
        self._service = None

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

    def _read_all_rows(self) -> list[dict[str, Any]]:
        """Read all data rows from the sheet."""
        service = self._get_service()

        last_col = column_index_to_letter(len(self.column_names) - 1)
        range_name = f"{self.config.sheet_name}!A:{last_col}"

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

        # First row is header
        rows = []
        for i, row_values in enumerate(values[1:], start=2):  # Start at row 2
            row_dict = {"_row_number": i}
            for j, col_name in enumerate(self.column_names):
                row_dict[col_name] = row_values[j] if j < len(row_values) else ""
            rows.append(row_dict)

        return rows

    def _row_to_final_record(self, row: dict[str, Any]) -> PickupRecordFinal:
        """Convert a row dict to PickupRecordFinal using *_final columns."""
        return PickupRecordFinal(
            pickup_uid=row.get("pickup_uid", ""),
            row_number=row.get("_row_number", 0),
            # Vehicle (from *_final columns)
            vin=row.get("vin_final", ""),
            year=self._to_int(row.get("year_final", 0)),
            make=row.get("make_final", ""),
            model=row.get("model_final", ""),
            vehicle_type=row.get("vehicle_type_final", ""),
            running=row.get("running_final", "unknown"),
            mileage=self._to_int(row.get("mileage_final", 0)),
            color=row.get("color_final", ""),
            # Pickup location
            pickup_address1=row.get("pickup_address1_final", ""),
            pickup_city=row.get("pickup_city_final", ""),
            pickup_state=row.get("pickup_state_final", ""),
            pickup_zip=row.get("pickup_zip_final", ""),
            pickup_contact=row.get("pickup_contact_final", ""),
            pickup_phone=row.get("pickup_phone_final", ""),
            # Delivery location
            warehouse_id=row.get("warehouse_id_final", ""),
            warehouse_name=row.get("warehouse_name_final", ""),
            delivery_address1=row.get("delivery_address1_final", ""),
            delivery_city=row.get("delivery_city_final", ""),
            delivery_state=row.get("delivery_state_final", ""),
            delivery_zip=row.get("delivery_zip_final", ""),
            delivery_contact=row.get("delivery_contact_final", ""),
            delivery_phone=row.get("delivery_phone_final", ""),
            # Pricing & scheduling
            price=self._to_float(row.get("price_final", 0)),
            trailer_type=row.get("trailer_type_final", "open"),
            pickup_date=row.get("pickup_date_final", ""),
            delivery_date=row.get("delivery_date_final", ""),
            # Metadata
            auction=row.get("auction_detected", ""),
            auction_ref=row.get("auction_ref_base", ""),
            gate_pass=row.get("gate_pass_base", ""),
            status=row.get("status", ""),
            cd_export_status=row.get("cd_export_status", ""),
            cd_listing_id=row.get("cd_listing_id", ""),
            cd_payload_hash=row.get("cd_payload_hash", ""),
        )

    def _to_int(self, value) -> int:
        """Safely convert value to int."""
        if not value:
            return 0
        try:
            return int(float(str(value).replace(",", "")))
        except (ValueError, TypeError):
            return 0

    def _to_float(self, value) -> float:
        """Safely convert value to float."""
        if not value:
            return 0.0
        try:
            return float(str(value).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            return 0.0

    def list_ready_for_cd(self, include_changed: bool = True) -> list[PickupRecordFinal]:
        """
        List rows that are ready for CD export.

        Criteria:
        - cd_export_enabled = TRUE
        - status = READY_FOR_CD OR cd_export_status = READY
        - If include_changed: also include rows where payload hash changed

        Returns list of PickupRecordFinal objects.
        """
        rows = self._read_all_rows()
        ready = []

        for row in rows:
            # Skip if export disabled
            if str(row.get("cd_export_enabled", "")).upper() != "TRUE":
                continue

            status = row.get("status", "")
            cd_status = row.get("cd_export_status", "")

            # Check if ready for export
            is_ready = status == "READY_FOR_CD" or cd_status == "READY"

            # Check if payload changed (for re-export)
            has_changed = False
            if include_changed and row.get("cd_listing_id"):
                record = self._row_to_final_record(row)
                new_hash = record.compute_payload_hash()
                old_hash = row.get("cd_payload_hash", "")
                has_changed = new_hash != old_hash

            if is_ready or has_changed:
                ready.append(self._row_to_final_record(row))

        logger.info(f"Found {len(ready)} rows ready for CD export")
        return ready

    def list_by_status(self, status: str) -> list[PickupRecordFinal]:
        """List rows with a specific status."""
        rows = self._read_all_rows()
        return [self._row_to_final_record(row) for row in rows if row.get("status") == status]

    def list_by_cd_status(self, cd_status: str) -> list[PickupRecordFinal]:
        """List rows with a specific CD export status."""
        rows = self._read_all_rows()
        return [
            self._row_to_final_record(row)
            for row in rows
            if row.get("cd_export_status") == cd_status
        ]

    def get_by_uid(self, pickup_uid: str) -> Optional[PickupRecordFinal]:
        """Get a single record by pickup_uid."""
        rows = self._read_all_rows()
        for row in rows:
            if row.get("pickup_uid") == pickup_uid:
                return self._row_to_final_record(row)
        return None

    def get_by_row_number(self, row_number: int) -> Optional[PickupRecordFinal]:
        """Get a single record by row number."""
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
        if not values:
            return None

        row_dict = {"_row_number": row_number}
        for i, col_name in enumerate(self.column_names):
            row_dict[col_name] = values[i] if i < len(values) else ""

        return self._row_to_final_record(row_dict)

    def update_cd_export_result(
        self,
        pickup_uid: str,
        success: bool,
        listing_id: str = None,
        error: str = None,
        payload_json: str = None,
    ):
        """
        Update row with CD export result.

        Args:
            pickup_uid: Row identifier
            success: Whether export was successful
            listing_id: CD listing ID if successful
            error: Error message if failed
            payload_json: JSON snapshot of sent payload
        """
        # Find row number
        rows = self._read_all_rows()
        row_number = None
        for row in rows:
            if row.get("pickup_uid") == pickup_uid:
                row_number = row.get("_row_number")
                break

        if not row_number:
            logger.warning(f"Could not find row for pickup_uid={pickup_uid}")
            return

        service = self._get_service()
        now = datetime.now().isoformat()

        # Prepare updates
        updates = []

        # cd_export_status
        cd_status_idx = get_column_index("cd_export_status")
        if cd_status_idx >= 0:
            col_letter = column_index_to_letter(cd_status_idx)
            status_value = "SENT" if success else "ERROR"
            updates.append(
                {
                    "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                    "values": [[status_value]],
                }
            )

        # cd_last_export_at
        export_at_idx = get_column_index("cd_last_export_at")
        if export_at_idx >= 0:
            col_letter = column_index_to_letter(export_at_idx)
            updates.append(
                {
                    "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                    "values": [[now]],
                }
            )

        if success:
            # cd_listing_id
            if listing_id:
                listing_id_idx = get_column_index("cd_listing_id")
                if listing_id_idx >= 0:
                    col_letter = column_index_to_letter(listing_id_idx)
                    updates.append(
                        {
                            "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                            "values": [[listing_id]],
                        }
                    )

            # status -> EXPORTED_TO_CD
            status_idx = get_column_index("status")
            if status_idx >= 0:
                col_letter = column_index_to_letter(status_idx)
                updates.append(
                    {
                        "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                        "values": [["EXPORTED_TO_CD"]],
                    }
                )

            # Clear error
            error_idx = get_column_index("cd_last_error")
            if error_idx >= 0:
                col_letter = column_index_to_letter(error_idx)
                updates.append(
                    {
                        "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                        "values": [[""]],
                    }
                )
        else:
            # cd_last_error
            if error:
                error_idx = get_column_index("cd_last_error")
                if error_idx >= 0:
                    col_letter = column_index_to_letter(error_idx)
                    updates.append(
                        {
                            "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                            "values": [[error[:500]]],  # Truncate long errors
                        }
                    )

            # status -> FAILED
            status_idx = get_column_index("status")
            if status_idx >= 0:
                col_letter = column_index_to_letter(status_idx)
                updates.append(
                    {
                        "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                        "values": [["FAILED"]],
                    }
                )

        # cd_payload_json (snapshot)
        if payload_json:
            payload_idx = get_column_index("cd_payload_json")
            if payload_idx >= 0:
                col_letter = column_index_to_letter(payload_idx)
                updates.append(
                    {
                        "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                        "values": [[payload_json[:10000]]],  # Truncate if very long
                    }
                )

        # cd_payload_hash
        if payload_json:
            record = self.get_by_row_number(row_number)
            if record:
                hash_idx = get_column_index("cd_payload_hash")
                if hash_idx >= 0:
                    col_letter = column_index_to_letter(hash_idx)
                    updates.append(
                        {
                            "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                            "values": [[record.compute_payload_hash()]],
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

            logger.info(f"Updated CD export result for pickup_uid={pickup_uid}, success={success}")

    def mark_ready_for_cd(self, pickup_uid: str):
        """Mark a row as ready for CD export."""
        rows = self._read_all_rows()
        row_number = None
        for row in rows:
            if row.get("pickup_uid") == pickup_uid:
                row_number = row.get("_row_number")
                break

        if not row_number:
            logger.warning(f"Could not find row for pickup_uid={pickup_uid}")
            return

        service = self._get_service()
        updates = []

        # status -> READY_FOR_CD
        status_idx = get_column_index("status")
        if status_idx >= 0:
            col_letter = column_index_to_letter(status_idx)
            updates.append(
                {
                    "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                    "values": [["READY_FOR_CD"]],
                }
            )

        # cd_export_status -> READY
        cd_status_idx = get_column_index("cd_export_status")
        if cd_status_idx >= 0:
            col_letter = column_index_to_letter(cd_status_idx)
            updates.append(
                {
                    "range": f"{self.config.sheet_name}!{col_letter}{row_number}",
                    "values": [["READY"]],
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

            logger.info(f"Marked pickup_uid={pickup_uid} as ready for CD")

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about rows in the sheet."""
        rows = self._read_all_rows()

        stats = {
            "total": len(rows),
            "by_status": {},
            "by_cd_status": {},
            "by_auction": {},
            "ready_for_cd": 0,
            "exported_to_cd": 0,
            "locked": 0,
        }

        for row in rows:
            status = row.get("status", "UNKNOWN")
            cd_status = row.get("cd_export_status", "UNKNOWN")
            auction = row.get("auction_detected", "UNKNOWN")

            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
            stats["by_cd_status"][cd_status] = stats["by_cd_status"].get(cd_status, 0) + 1
            stats["by_auction"][auction] = stats["by_auction"].get(auction, 0) + 1

            if status == "READY_FOR_CD" or cd_status == "READY":
                stats["ready_for_cd"] += 1
            if status == "EXPORTED_TO_CD" or cd_status == "SENT":
                stats["exported_to_cd"] += 1
            if str(row.get("lock_import", "")).upper() == "TRUE":
                stats["locked"] += 1

        return stats
