"""
Central Dispatch Sheet Exporter V2 - CD Listings API V2 Payload Builder

This module builds CD Listings API V2 payloads from Google Sheets data
using the Source of Truth pattern (Schema V3).

Key differences from V1:
- externalId (dispatch_id) instead of shipperReferenceNumber
- Flat stops[] structure (address, city, state, postalCode, country)
- vehicles[] with pickupStopNumber, dropoffStopNumber, isInoperable
- price.total, cod{}, balance{} structure
- marketplaces[] with marketplaceId (int) and boolean flags
- Date fields: availableDate, expirationDate, desiredDeliveryDate

Based on: CD Listings API V2 Create Listing endpoint
Schema Version: 3
"""

import json
import logging
from typing import Any, Optional

from schemas.sheets_schema_v3 import (
    OVERRIDE_MAPPINGS,
    RowStatus,
    apply_all_overrides,
    validate_row_for_ready,
)
from services.sheets_exporter_v3 import SheetsExporterV3

logger = logging.getLogger(__name__)


class CDSheetExporterV2:
    """
    Exports READY rows from Google Sheets to Central Dispatch Listings API V2.

    Workflow:
    1. Query sheet for READY/RETRY rows
    2. Validate each row
    3. Build CD V2 payload with override resolution
    4. Call CD API (or dry-run)
    5. Update sheet with results
    """

    def __init__(
        self,
        sheets_config,
        cd_config,
        sheet_name: str = "Pickups",
    ):
        """
        Initialize the exporter.

        Args:
            sheets_config: Sheets configuration
            cd_config: Central Dispatch configuration
            sheet_name: Name of the sheet tab
        """
        self.sheets_config = sheets_config
        self.cd_config = cd_config
        self.sheet_name = sheet_name
        self._sheets_exporter = None
        self._cd_client = None

    @property
    def sheets_exporter(self) -> SheetsExporterV3:
        """Get or create sheets exporter."""
        if self._sheets_exporter is None:
            self._sheets_exporter = SheetsExporterV3(
                self.sheets_config,
                sheet_name=self.sheet_name,
            )
        return self._sheets_exporter

    @property
    def cd_client(self):
        """Get or create CD client."""
        if self._cd_client is None and self.cd_config.enabled:
            from services.central_dispatch import CentralDispatchClient

            self._cd_client = CentralDispatchClient(
                client_id=self.cd_config.client_id,
                client_secret=self.cd_config.client_secret,
                marketplace_id=self.cd_config.marketplace_id,
            )
        return self._cd_client

    def _get_final_value(self, row: dict[str, Any], base_field: str) -> Any:
        """
        Get final value for a field, considering overrides.

        Order:
        1. Check _final_{field} (pre-computed by apply_all_overrides)
        2. Check override_{field}
        3. Check base field
        """
        # Pre-computed final
        final_key = f"_final_{base_field}"
        if final_key in row:
            return row[final_key]

        # Override field
        override_field = OVERRIDE_MAPPINGS.get(base_field)
        if override_field:
            override_val = row.get(override_field)
            if override_val and str(override_val).strip():
                return override_val

        # Base field
        return row.get(base_field)

    def _to_bool(self, value: Any, default: bool = False) -> bool:
        """Convert value to boolean."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        val_str = str(value).strip().upper()
        return val_str in ("TRUE", "1", "YES", "Y")

    def _to_int(self, value: Any, default: Optional[int] = None) -> Optional[int]:
        """Convert value to integer."""
        if value is None or str(value).strip() == "":
            return default
        try:
            return int(float(str(value).replace(",", "")))
        except (ValueError, TypeError):
            return default

    def _to_float(self, value: Any, default: Optional[float] = None) -> Optional[float]:
        """Convert value to float."""
        if value is None or str(value).strip() == "":
            return default
        try:
            return float(str(value).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            return default

    def _clean_string(self, value: Any) -> Optional[str]:
        """Clean string value, return None if empty."""
        if value is None:
            return None
        val_str = str(value).strip()
        return val_str if val_str else None

    def row_to_cd_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        """
        Convert a sheet row to CD Listings API V2 payload.

        Applies all overrides and builds the exact CD V2 structure.
        """
        # Apply overrides first
        row = apply_all_overrides(row)

        payload = {}

        # =================================================================
        # TOP-LEVEL FIELDS
        # =================================================================

        # externalId (dispatch_id)
        payload["externalId"] = self._clean_string(row.get("dispatch_id"))

        # Optional IDs
        shipper_order_id = self._clean_string(row.get("shipper_order_id"))
        if shipper_order_id:
            payload["shipperOrderId"] = shipper_order_id

        partner_ref_id = self._clean_string(row.get("partner_reference_id"))
        if partner_ref_id:
            payload["partnerReferenceId"] = partner_ref_id

        # Trailer type
        trailer_type = self._get_final_value(row, "trailer_type")
        if trailer_type:
            payload["trailerType"] = str(trailer_type).upper()

        # Flags
        has_inop = self._to_bool(row.get("has_inop_vehicle"), False)
        payload["hasInOpVehicle"] = has_inop

        load_terms = self._clean_string(row.get("load_specific_terms"))
        if load_terms:
            payload["loadSpecificTerms"] = load_terms

        # Dates (YYYY-MM-DD format)
        available_date = self._get_final_value(row, "available_date")
        if available_date:
            payload["availableDate"] = str(available_date)[:10]

        expiration_date = self._get_final_value(row, "expiration_date")
        if expiration_date:
            payload["expirationDate"] = str(expiration_date)[:10]

        desired_delivery_date = self._get_final_value(row, "desired_delivery_date")
        if desired_delivery_date:
            payload["desiredDeliveryDate"] = str(desired_delivery_date)[:10]

        # Transportation release notes
        release_notes = self._get_final_value(row, "transportation_release_notes")
        if release_notes:
            payload["transportationReleaseNotes"] = str(release_notes)

        # Tags
        tags_json = row.get("tags_json")
        if tags_json:
            try:
                if isinstance(tags_json, str):
                    tags = json.loads(tags_json)
                else:
                    tags = tags_json
                if tags:
                    payload["tags"] = tags
            except json.JSONDecodeError:
                pass

        # =================================================================
        # PRICE STRUCTURE
        # =================================================================

        price = {}

        price_total = self._get_final_value(row, "price_total")
        if price_total:
            price["total"] = self._to_float(price_total)

        # COD
        cod_amount = self._to_float(row.get("cod_amount"))
        if cod_amount:
            cod = {"amount": cod_amount}

            cod_method = self._clean_string(row.get("cod_payment_method"))
            if cod_method:
                cod["paymentMethod"] = cod_method.upper()

            cod_location = self._clean_string(row.get("cod_payment_location"))
            if cod_location:
                cod["paymentLocation"] = cod_location.upper()

            price["cod"] = cod

        # Balance
        balance_amount = self._to_float(row.get("balance_amount"))
        if balance_amount:
            balance = {"amount": balance_amount}

            balance_time = self._clean_string(row.get("balance_payment_time"))
            if balance_time:
                balance["paymentTime"] = balance_time.upper()

            balance_terms = self._clean_string(row.get("balance_terms_begin_on"))
            if balance_terms:
                balance["balancePaymentTermsBeginOn"] = balance_terms.upper()

            balance_method = self._clean_string(row.get("balance_payment_method"))
            if balance_method:
                balance["balancePaymentMethod"] = balance_method.upper()

            price["balance"] = balance

        if price:
            payload["price"] = price

        # =================================================================
        # SLA STRUCTURE
        # =================================================================

        sla = {}

        sla_duration = self._to_int(row.get("sla_duration"))
        if sla_duration:
            sla["duration"] = sla_duration

        sla_tz = self._clean_string(row.get("sla_time_zone_offset"))
        if sla_tz:
            sla["timeZoneOffset"] = sla_tz

        sla_rollover = self._clean_string(row.get("sla_rollover_time"))
        if sla_rollover:
            sla["rolloverTime"] = sla_rollover

        sla_include_day = row.get("sla_include_current_day_after_rollover")
        if sla_include_day:
            sla["includeCurrentDayAfterRollOver"] = self._to_bool(sla_include_day)

        if sla:
            payload["sla"] = sla

        # =================================================================
        # STOPS ARRAY (Flat structure per CD V2)
        # =================================================================

        stops = []

        # Pickup stop (stop 0, stopNumber=1)
        pickup_stop = {
            "stopNumber": self._to_int(row.get("pickup_stop_number"), 1),
        }

        pickup_name = self._clean_string(row.get("pickup_location_name"))
        if pickup_name:
            pickup_stop["locationName"] = pickup_name

        pickup_address = self._get_final_value(row, "pickup_address")
        if pickup_address:
            pickup_stop["address"] = str(pickup_address)

        pickup_city = self._get_final_value(row, "pickup_city")
        if pickup_city:
            pickup_stop["city"] = str(pickup_city)

        pickup_state = self._get_final_value(row, "pickup_state")
        if pickup_state:
            pickup_stop["state"] = str(pickup_state).upper()[:2]

        pickup_postal = self._get_final_value(row, "pickup_postal_code")
        if pickup_postal:
            pickup_stop["postalCode"] = str(pickup_postal)

        pickup_country = self._clean_string(row.get("pickup_country")) or "US"
        pickup_stop["country"] = pickup_country.upper()[:2]

        pickup_phone = self._clean_string(row.get("pickup_phone"))
        if pickup_phone:
            pickup_stop["phone"] = pickup_phone

        pickup_contact_name = self._clean_string(row.get("pickup_contact_name"))
        if pickup_contact_name:
            pickup_stop["contactName"] = pickup_contact_name

        pickup_contact_phone = self._clean_string(row.get("pickup_contact_phone"))
        if pickup_contact_phone:
            pickup_stop["contactPhone"] = pickup_contact_phone

        pickup_loc_type = self._clean_string(row.get("pickup_location_type"))
        if pickup_loc_type:
            pickup_stop["locationType"] = pickup_loc_type.upper()

        stops.append(pickup_stop)

        # Dropoff stop (stop 1, stopNumber=2)
        dropoff_stop = {
            "stopNumber": self._to_int(row.get("dropoff_stop_number"), 2),
        }

        dropoff_name = self._clean_string(row.get("dropoff_location_name"))
        if dropoff_name:
            dropoff_stop["locationName"] = dropoff_name

        dropoff_address = self._get_final_value(row, "dropoff_address")
        if dropoff_address:
            dropoff_stop["address"] = str(dropoff_address)

        dropoff_city = self._get_final_value(row, "dropoff_city")
        if dropoff_city:
            dropoff_stop["city"] = str(dropoff_city)

        dropoff_state = self._get_final_value(row, "dropoff_state")
        if dropoff_state:
            dropoff_stop["state"] = str(dropoff_state).upper()[:2]

        dropoff_postal = self._get_final_value(row, "dropoff_postal_code")
        if dropoff_postal:
            dropoff_stop["postalCode"] = str(dropoff_postal)

        dropoff_country = self._clean_string(row.get("dropoff_country")) or "US"
        dropoff_stop["country"] = dropoff_country.upper()[:2]

        dropoff_phone = self._clean_string(row.get("dropoff_phone"))
        if dropoff_phone:
            dropoff_stop["phone"] = dropoff_phone

        dropoff_contact_name = self._clean_string(row.get("dropoff_contact_name"))
        if dropoff_contact_name:
            dropoff_stop["contactName"] = dropoff_contact_name

        dropoff_contact_phone = self._clean_string(row.get("dropoff_contact_phone"))
        if dropoff_contact_phone:
            dropoff_stop["contactPhone"] = dropoff_contact_phone

        dropoff_loc_type = self._clean_string(row.get("dropoff_location_type"))
        if dropoff_loc_type:
            dropoff_stop["locationType"] = dropoff_loc_type.upper()

        stops.append(dropoff_stop)

        payload["stops"] = stops

        # =================================================================
        # VEHICLES ARRAY (Per CD V2 structure)
        # =================================================================

        vehicle = {
            "pickupStopNumber": self._to_int(row.get("pickup_stop_number"), 1),
            "dropoffStopNumber": self._to_int(row.get("dropoff_stop_number"), 2),
        }

        ext_vehicle_id = self._clean_string(row.get("vehicle_external_vehicle_id"))
        if ext_vehicle_id:
            vehicle["externalVehicleId"] = ext_vehicle_id

        vin = self._get_final_value(row, "vehicle_vin")
        if vin:
            vehicle["vin"] = str(vin).strip().upper()

        year = self._get_final_value(row, "vehicle_year")
        if year:
            vehicle["year"] = self._to_int(year)

        make = self._get_final_value(row, "vehicle_make")
        if make:
            vehicle["make"] = str(make)

        model = self._get_final_value(row, "vehicle_model")
        if model:
            vehicle["model"] = str(model)

        trim = self._clean_string(row.get("vehicle_trim"))
        if trim:
            vehicle["trim"] = trim

        vehicle_type = self._clean_string(row.get("vehicle_type"))
        if vehicle_type:
            vehicle["vehicleType"] = vehicle_type.upper()

        color = self._clean_string(row.get("vehicle_color"))
        if color:
            vehicle["color"] = color

        license_plate = self._clean_string(row.get("vehicle_license_plate"))
        if license_plate:
            vehicle["licensePlate"] = license_plate

        license_plate_state = self._clean_string(row.get("vehicle_license_plate_state"))
        if license_plate_state:
            vehicle["licensePlateState"] = license_plate_state.upper()[:2]

        lot_number = self._clean_string(row.get("vehicle_lot_number"))
        if lot_number:
            vehicle["lotNumber"] = lot_number

        # isInoperable (with override)
        is_inop = self._get_final_value(row, "vehicle_is_inoperable")
        vehicle["isInoperable"] = self._to_bool(is_inop, False)

        tariff = self._to_float(row.get("vehicle_tariff"))
        if tariff:
            vehicle["tariff"] = tariff

        additional_info = self._clean_string(row.get("vehicle_additional_info"))
        if additional_info:
            vehicle["additionalInfo"] = additional_info

        payload["vehicles"] = [vehicle]

        # =================================================================
        # MARKETPLACES ARRAY (Per CD V2 structure)
        # =================================================================

        marketplace = {}

        marketplace_id = self._to_int(row.get("marketplace_id"))
        if marketplace_id:
            marketplace["marketplaceId"] = marketplace_id

        digital_offers = row.get("digital_offers_enabled")
        if digital_offers is not None:
            marketplace["digitalOffersEnabled"] = self._to_bool(digital_offers, True)

        searchable = row.get("searchable")
        if searchable is not None:
            marketplace["searchable"] = self._to_bool(searchable, True)

        auto_accept = row.get("offers_auto_accept_enabled")
        if auto_accept is not None:
            marketplace["offersAutoAcceptEnabled"] = self._to_bool(auto_accept, False)

        auto_dispatch = row.get("auto_dispatch_on_offer_accepted")
        if auto_dispatch is not None:
            marketplace["autoDispatchOnOfferAccepted"] = self._to_bool(auto_dispatch, False)

        predispatch_notes = self._clean_string(row.get("predispatch_notes"))
        if predispatch_notes:
            marketplace["predispatchNotes"] = predispatch_notes

        excluded_json = row.get("customers_excluded_from_offers_json")
        if excluded_json:
            try:
                if isinstance(excluded_json, str):
                    excluded = json.loads(excluded_json)
                else:
                    excluded = excluded_json
                if excluded:
                    marketplace["customersExcludedFromOffers"] = excluded
            except json.JSONDecodeError:
                pass

        if marketplace:
            payload["marketplaces"] = [marketplace]

        return payload

    def preview_payload(self, dispatch_id: str) -> Optional[dict[str, Any]]:
        """
        Preview the CD payload for a specific row.

        Returns:
            The CD payload dict, or None if row not found.
        """
        row = self.sheets_exporter.get_row_by_dispatch_id(dispatch_id)
        if not row:
            return None
        return self.row_to_cd_payload(row)

    def export_ready_rows(
        self,
        dry_run: bool = False,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Export READY and RETRY rows to Central Dispatch.

        Args:
            dry_run: If True, don't actually call CD API
            limit: Maximum number of rows to export

        Returns:
            Dict with:
            - total: Total rows found
            - exported: Successfully exported count
            - failed: Failed count
            - results: List of per-row results
        """
        # Get READY and RETRY rows
        statuses = [RowStatus.READY, RowStatus.RETRY]
        rows = self.sheets_exporter.get_rows_by_status(statuses, limit=limit)

        results = {
            "total": len(rows),
            "exported": 0,
            "failed": 0,
            "results": [],
        }

        for row in rows:
            dispatch_id = row.get("dispatch_id")
            row_result = {
                "dispatch_id": dispatch_id,
                "success": False,
                "listing_id": None,
                "error": None,
            }

            try:
                # Validate
                errors = validate_row_for_ready(row)
                if errors:
                    row_result["error"] = f"Validation failed: {'; '.join(errors)}"
                    row_result["success"] = False
                    results["failed"] += 1

                    if not dry_run:
                        self.sheets_exporter.update_row_status(
                            dispatch_id,
                            RowStatus.ERROR,
                            error_message=row_result["error"],
                        )

                    results["results"].append(row_result)
                    continue

                # Build payload
                payload = self.row_to_cd_payload(row)

                # Save snapshot
                if not dry_run:
                    self.sheets_exporter.save_payload_snapshot(dispatch_id, payload)

                if dry_run:
                    # Dry run - simulate success
                    row_result["success"] = True
                    row_result["listing_id"] = f"DRY_RUN_{dispatch_id}"
                    results["exported"] += 1
                    logger.info(f"[DRY RUN] Would export: {dispatch_id}")
                else:
                    # Actually call CD API
                    if self.cd_client:
                        try:
                            response = self.cd_client.create_listing(payload)
                            listing_id = response.get("id") or response.get("listingId")

                            row_result["success"] = True
                            row_result["listing_id"] = listing_id
                            results["exported"] += 1

                            # Update status to EXPORTED
                            self.sheets_exporter.update_row_status(
                                dispatch_id,
                                RowStatus.EXPORTED,
                                cd_listing_id=listing_id,
                            )

                            logger.info(f"Exported: {dispatch_id} -> {listing_id}")

                        except Exception as e:
                            row_result["error"] = str(e)
                            row_result["success"] = False
                            results["failed"] += 1

                            # Update status to ERROR
                            self.sheets_exporter.update_row_status(
                                dispatch_id,
                                RowStatus.ERROR,
                                error_message=str(e),
                            )

                            logger.error(f"Export failed: {dispatch_id} - {e}")
                    else:
                        row_result["error"] = "CD client not configured"
                        row_result["success"] = False
                        results["failed"] += 1

            except Exception as e:
                row_result["error"] = str(e)
                row_result["success"] = False
                results["failed"] += 1
                logger.exception(f"Error exporting {dispatch_id}: {e}")

            results["results"].append(row_result)

        return results
