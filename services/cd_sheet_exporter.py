"""
Central Dispatch Sheet Exporter

Exports READY rows from Google Sheets to CD Listings API V2.

The Sheet is the Source of Truth - this exporter:
1. Reads READY rows from Pickups sheet
2. Builds ListingRequest payload from final values
3. Calls CD API to create listings
4. Updates sheet with results (cd_listing_id, status, etc.)

Usage:
    exporter = CDSheetExporter(sheets_config, cd_config)
    results = exporter.export_ready_rows()
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from core.config import CentralDispatchConfig, SheetsConfig
from schemas.sheets_schema_v2 import (
    column_index_to_letter,
    get_column_index,
    get_final_value,
)
from services.sheets_exporter_v2 import SheetsExporterV2

logger = logging.getLogger(__name__)


class CDSheetExporter:
    """
    Export READY rows from Google Sheets to Central Dispatch.
    """

    def __init__(
        self,
        sheets_config: SheetsConfig,
        cd_config: CentralDispatchConfig,
        sheet_name: str = "Pickups",
    ):
        self.sheets_config = sheets_config
        self.cd_config = cd_config
        self.sheet_name = sheet_name
        self.exporter = SheetsExporterV2(sheets_config, sheet_name)
        self._cd_client = None

    def _get_cd_client(self):
        """Get or create CD API client."""
        if self._cd_client is not None:
            return self._cd_client

        from services.central_dispatch import CentralDispatchClient

        self._cd_client = CentralDispatchClient(
            client_id=self.cd_config.client_id,
            client_secret=self.cd_config.client_secret,
            marketplace_id=self.cd_config.marketplace_id,
        )
        return self._cd_client

    def _row_to_listing_request(self, row: dict[str, Any]) -> dict[str, Any]:
        """
        Convert a sheet row to CD Listings API V2 ListingRequest.

        Uses get_final_value() to respect overrides.
        """

        # Helper to get final value
        def final(field: str, default=None):
            val = get_final_value(row, field)
            if val is None or (isinstance(val, str) and not val.strip()):
                return default
            return val

        # Build stops array
        stops = []

        # Stop 0: Pickup
        pickup_stop = {
            "type": "PICKUP",
            "location": {
                "street1": final("pickup_street1"),
                "city": final("pickup_city"),
                "state": final("pickup_state"),
                "postalCode": final("pickup_postal_code"),
                "country": final("pickup_country", "US"),
            },
        }

        # Optional pickup fields
        if final("pickup_street2"):
            pickup_stop["location"]["street2"] = final("pickup_street2")
        if final("pickup_phone"):
            pickup_stop["location"]["phone"] = final("pickup_phone")
        if final("pickup_phone2"):
            pickup_stop["location"]["phone2"] = final("pickup_phone2")
        if final("pickup_phone3"):
            pickup_stop["location"]["phone3"] = final("pickup_phone3")
        if final("pickup_site_id"):
            pickup_stop["siteId"] = final("pickup_site_id")

        # Pickup contact
        if final("pickup_contact_name") or final("pickup_contact_phone"):
            pickup_stop["contact"] = {}
            if final("pickup_contact_name"):
                pickup_stop["contact"]["name"] = final("pickup_contact_name")
            if final("pickup_contact_phone"):
                pickup_stop["contact"]["phone"] = final("pickup_contact_phone")
            if final("pickup_contact_cell"):
                pickup_stop["contact"]["cellPhone"] = final("pickup_contact_cell")

        if final("pickup_instructions"):
            pickup_stop["instructions"] = final("pickup_instructions")

        stops.append(pickup_stop)

        # Stop 1: Delivery
        delivery_stop = {
            "type": "DELIVERY",
            "location": {
                "street1": final("delivery_street1"),
                "city": final("delivery_city"),
                "state": final("delivery_state"),
                "postalCode": final("delivery_postal_code"),
                "country": final("delivery_country", "US"),
            },
        }

        if final("delivery_street2"):
            delivery_stop["location"]["street2"] = final("delivery_street2")
        if final("delivery_phone"):
            delivery_stop["location"]["phone"] = final("delivery_phone")

        if final("delivery_contact_name") or final("delivery_contact_phone"):
            delivery_stop["contact"] = {}
            if final("delivery_contact_name"):
                delivery_stop["contact"]["name"] = final("delivery_contact_name")
            if final("delivery_contact_phone"):
                delivery_stop["contact"]["phone"] = final("delivery_contact_phone")

        if final("delivery_instructions"):
            delivery_stop["instructions"] = final("delivery_instructions")

        stops.append(delivery_stop)

        # Build vehicles array (single vehicle)
        vehicle = {
            "vin": final("vin"),
        }

        if final("year"):
            try:
                vehicle["year"] = int(final("year"))
            except (ValueError, TypeError):
                pass
        if final("make"):
            vehicle["make"] = final("make")
        if final("model"):
            vehicle["model"] = final("model")
        if final("vehicle_type"):
            vehicle["vehicleType"] = final("vehicle_type").upper()

        # Operable
        operable = final("operable")
        if operable:
            vehicle["operable"] = str(operable).upper() == "TRUE"

        if final("notes_vehicle"):
            vehicle["notes"] = final("notes_vehicle")

        vehicles = [vehicle]

        # Build price
        price = {
            "type": final("price_type", "TOTAL"),
            "currency": final("price_currency", "USD"),
        }

        price_amount = final("price_amount")
        if price_amount:
            try:
                price["amount"] = float(str(price_amount).replace(",", "").replace("$", ""))
            except (ValueError, TypeError):
                price["amount"] = 0

        # COD (optional)
        if final("cod_type") and final("cod_amount"):
            price["cod"] = {
                "type": final("cod_type"),
                "amount": float(final("cod_amount")),
            }
            if final("cod_payment_method"):
                price["cod"]["paymentMethod"] = final("cod_payment_method")
            if final("cod_payment_note"):
                price["cod"]["paymentMethodNote"] = final("cod_payment_note")
            if final("cod_aux_payment_method"):
                price["cod"]["auxiliaryPaymentMethod"] = final("cod_aux_payment_method")
            if final("cod_aux_payment_note"):
                price["cod"]["auxiliaryPaymentMethodNote"] = final("cod_aux_payment_note")

        # Balance (optional)
        if final("balance_type") and final("balance_amount"):
            price["balance"] = {
                "type": final("balance_type"),
                "amount": float(final("balance_amount")),
            }
            if final("balance_payment_method"):
                price["balance"]["paymentMethod"] = final("balance_payment_method")
            if final("balance_payment_note"):
                price["balance"]["paymentMethodNote"] = final("balance_payment_note")

        # Build marketplaces array
        marketplace_ids = final("marketplace_ids", "")
        if isinstance(marketplace_ids, str):
            # Could be JSON array or comma-separated
            if marketplace_ids.startswith("["):
                try:
                    marketplaces = json.loads(marketplace_ids)
                except json.JSONDecodeError:
                    marketplaces = [marketplace_ids]
            else:
                marketplaces = [m.strip() for m in marketplace_ids.split(",") if m.strip()]
        else:
            marketplaces = [str(marketplace_ids)]

        # Format as CD expects: [{"id": "..."}, ...]
        marketplaces_list = [{"id": m} for m in marketplaces]

        # Build listing request
        listing_request = {
            "stops": stops,
            "vehicles": vehicles,
            "price": price,
            "marketplaces": marketplaces_list,
            "trailerType": final("trailer_type", "OPEN").upper(),
            "availableDateTime": final("available_datetime"),
            "expirationDateTime": final("expiration_datetime"),
            "companyName": final("company_name"),
            "shipperReferenceNumber": row.get("dispatch_id"),
        }

        # Optional flags
        allow_full = final("allow_full_load")
        if allow_full:
            listing_request["allowFullLoad"] = str(allow_full).upper() == "TRUE"

        allow_ltl = final("allow_ltl")
        if allow_ltl:
            listing_request["allowLtl"] = str(allow_ltl).upper() == "TRUE"

        # SLA (optional)
        if final("sla_duration"):
            listing_request["sla"] = {
                "duration": final("sla_duration"),
            }
            if final("sla_timezone_offset"):
                listing_request["sla"]["timeZoneOffset"] = final("sla_timezone_offset")
            if final("sla_rollover_time"):
                listing_request["sla"]["rolloverTime"] = final("sla_rollover_time")
            if final("sla_include_current_day"):
                listing_request["sla"]["includeCurrentDayAfterRollOver"] = (
                    str(final("sla_include_current_day")).upper() == "TRUE"
                )

        # Tags (optional)
        if final("tags_json"):
            tags_str = final("tags_json")
            try:
                listing_request["tags"] = json.loads(tags_str)
            except json.JSONDecodeError:
                pass

        # Notes (release notes)
        if final("release_notes"):
            listing_request["notes"] = final("release_notes")

        return listing_request

    def _update_export_result(
        self,
        row_number: int,
        success: bool,
        listing_id: str = None,
        error: str = None,
        payload: dict = None,
    ):
        """Update the sheet with export results."""
        from pathlib import Path

        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds_path = Path(self.sheets_config.credentials_file)
        creds = service_account.Credentials.from_service_account_file(
            str(creds_path),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=creds)

        now = datetime.now().isoformat()
        updates = []

        # row_status
        status_idx = get_column_index("row_status")
        if status_idx >= 0:
            col_letter = column_index_to_letter(status_idx)
            status_value = "EXPORTED" if success else "ERROR"
            updates.append(
                {
                    "range": f"{self.sheet_name}!{col_letter}{row_number}",
                    "values": [[status_value]],
                }
            )

        # cd_last_attempt_at
        attempt_idx = get_column_index("cd_last_attempt_at")
        if attempt_idx >= 0:
            col_letter = column_index_to_letter(attempt_idx)
            updates.append(
                {
                    "range": f"{self.sheet_name}!{col_letter}{row_number}",
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
                            "range": f"{self.sheet_name}!{col_letter}{row_number}",
                            "values": [[listing_id]],
                        }
                    )

            # cd_exported_at
            exported_idx = get_column_index("cd_exported_at")
            if exported_idx >= 0:
                col_letter = column_index_to_letter(exported_idx)
                updates.append(
                    {
                        "range": f"{self.sheet_name}!{col_letter}{row_number}",
                        "values": [[now]],
                    }
                )

            # Clear error
            error_idx = get_column_index("cd_last_error")
            if error_idx >= 0:
                col_letter = column_index_to_letter(error_idx)
                updates.append(
                    {
                        "range": f"{self.sheet_name}!{col_letter}{row_number}",
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
                            "range": f"{self.sheet_name}!{col_letter}{row_number}",
                            "values": [[error[:500]]],
                        }
                    )

        # cd_payload_snapshot
        if payload:
            payload_idx = get_column_index("cd_payload_snapshot")
            if payload_idx >= 0:
                col_letter = column_index_to_letter(payload_idx)
                updates.append(
                    {
                        "range": f"{self.sheet_name}!{col_letter}{row_number}",
                        "values": [[json.dumps(payload)[:10000]]],
                    }
                )

        if updates:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.sheets_config.spreadsheet_id,
                body={
                    "valueInputOption": "USER_ENTERED",
                    "data": updates,
                },
            ).execute()

    def export_row(self, row: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        """
        Export a single row to CD.

        Args:
            row: Row dict from sheet
            dry_run: If True, don't actually call CD API

        Returns:
            {
                "success": bool,
                "dispatch_id": str,
                "listing_id": str (if success),
                "error": str (if failure),
                "payload": dict (the listing request),
            }
        """
        dispatch_id = row.get("dispatch_id")
        row_number = row.get("_row_number")

        # Build payload
        payload = self._row_to_listing_request(row)

        result = {
            "dispatch_id": dispatch_id,
            "payload": payload,
        }

        if dry_run:
            result["success"] = True
            result["listing_id"] = f"DRY-RUN-{dispatch_id}"
            result["dry_run"] = True
            logger.info(f"[DRY RUN] Would export {dispatch_id}")
            return result

        # Call CD API
        try:
            cd_client = self._get_cd_client()
            response = cd_client.create_listing(payload)

            listing_id = response.get("id") or response.get("listingId")

            result["success"] = True
            result["listing_id"] = listing_id

            # Update sheet
            if row_number:
                self._update_export_result(
                    row_number,
                    success=True,
                    listing_id=listing_id,
                    payload=payload,
                )

            logger.info(f"Exported {dispatch_id} -> CD listing {listing_id}")

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)

            # Update sheet
            if row_number:
                self._update_export_result(
                    row_number,
                    success=False,
                    error=str(e),
                    payload=payload,
                )

            logger.error(f"Failed to export {dispatch_id}: {e}")

        return result

    def export_ready_rows(self, dry_run: bool = False, limit: int = None) -> dict[str, Any]:
        """
        Export all READY rows to CD.

        Args:
            dry_run: If True, don't actually call CD API
            limit: Maximum number of rows to export

        Returns:
            {
                "total": int,
                "exported": int,
                "failed": int,
                "results": list,
            }
        """
        # Get READY rows
        ready_rows = self.exporter.list_by_status("READY")

        # Also get RETRY rows
        retry_rows = self.exporter.list_by_status("RETRY")
        ready_rows.extend(retry_rows)

        if limit:
            ready_rows = ready_rows[:limit]

        logger.info(f"Found {len(ready_rows)} rows to export (READY + RETRY)")

        exported = 0
        failed = 0
        results = []

        for row in ready_rows:
            result = self.export_row(row, dry_run=dry_run)
            results.append(result)

            if result["success"]:
                exported += 1
            else:
                failed += 1

        return {
            "total": len(ready_rows),
            "exported": exported,
            "failed": failed,
            "dry_run": dry_run,
            "results": results,
        }

    def preview_payload(self, dispatch_id: str) -> Optional[dict[str, Any]]:
        """
        Preview the CD payload for a row without exporting.
        """
        row = self.exporter.get_row(dispatch_id)
        if not row:
            return None

        return self._row_to_listing_request(row)
