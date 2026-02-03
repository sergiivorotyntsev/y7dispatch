"""Google Sheets integration for audit log and CD export queue.

This module provides:
1. Append new pickup records to the sheet
2. Update existing records by idempotency key
3. Query records by status for CD export
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class PickupStatus(Enum):
    """Status of a pickup record in the pipeline."""

    RECEIVED = "RECEIVED"  # Email received, not yet parsed
    PARSED = "PARSED"  # PDF parsed successfully
    PARSE_FAILED = "PARSE_FAILED"  # PDF parsing failed
    ROUTED = "ROUTED"  # Warehouse assigned
    CLICKUP_CREATED = "CLICKUP_CREATED"  # ClickUp task created
    READY_FOR_CD = "READY_FOR_CD"  # Ready for Central Dispatch export
    CD_CREATED = "CD_CREATED"  # CD listing created
    ERROR = "ERROR"  # Error occurred


@dataclass
class PickupRecord:
    """Canonical record for a pickup - one per PDF attachment."""

    # Email metadata
    received_at: str = ""
    email_from: str = ""
    email_subject: str = ""
    message_id: str = ""
    thread_root_id: str = ""

    # Auction info
    auction_source: str = ""  # COPART/IAA/MANHEIM/UNKNOWN
    member_id: str = ""

    # Pickup location
    pickup_address_raw: str = ""
    pickup_name: str = ""
    pickup_city: str = ""
    pickup_state: str = ""
    pickup_zip: str = ""

    # Vehicle info
    lot_number: str = ""
    vin: str = ""
    vehicle_year: str = ""
    vehicle_make: str = ""
    vehicle_model: str = ""
    vehicle_color: str = ""

    # Gate pass
    gate_pass: str = ""

    # Warehouse routing
    suggested_warehouse_id: str = ""
    suggested_warehouse_state: str = ""
    suggested_warehouse_address: str = ""
    distance_miles: str = ""
    distance_mode: str = ""  # driving/haversine

    # Integration IDs
    clickup_task_id: str = ""
    clickup_task_url: str = ""
    cd_listing_id: str = ""

    # Status tracking
    status: str = PickupStatus.RECEIVED.value
    error_message: str = ""
    attachment_hash: str = ""
    attachment_name: str = ""

    # Timestamps
    created_at: str = ""
    updated_at: str = ""

    @property
    def idempotency_key(self) -> str:
        """Unique key for deduplication."""
        return f"{self.thread_root_id}:{self.attachment_hash}"

    def to_row(self) -> list[str]:
        """Convert to sheet row (list of strings)."""
        return [
            self.received_at,
            self.email_from,
            self.email_subject,
            self.message_id,
            self.thread_root_id,
            self.auction_source,
            self.member_id,
            self.pickup_address_raw,
            self.pickup_name,
            self.pickup_city,
            self.pickup_state,
            self.pickup_zip,
            self.lot_number,
            self.vin,
            self.vehicle_year,
            self.vehicle_make,
            self.vehicle_model,
            self.vehicle_color,
            self.gate_pass,
            self.suggested_warehouse_id,
            self.suggested_warehouse_state,
            self.suggested_warehouse_address,
            self.distance_miles,
            self.distance_mode,
            self.clickup_task_id,
            self.clickup_task_url,
            self.cd_listing_id,
            self.status,
            self.error_message,
            self.attachment_hash,
            self.attachment_name,
            self.created_at,
            self.updated_at,
        ]

    @classmethod
    def from_row(cls, row: list[str]) -> "PickupRecord":
        """Create from sheet row."""
        # Pad row if needed
        while len(row) < 33:
            row.append("")

        return cls(
            received_at=row[0],
            email_from=row[1],
            email_subject=row[2],
            message_id=row[3],
            thread_root_id=row[4],
            auction_source=row[5],
            member_id=row[6],
            pickup_address_raw=row[7],
            pickup_name=row[8],
            pickup_city=row[9],
            pickup_state=row[10],
            pickup_zip=row[11],
            lot_number=row[12],
            vin=row[13],
            vehicle_year=row[14],
            vehicle_make=row[15],
            vehicle_model=row[16],
            vehicle_color=row[17],
            gate_pass=row[18],
            suggested_warehouse_id=row[19],
            suggested_warehouse_state=row[20],
            suggested_warehouse_address=row[21],
            distance_miles=row[22],
            distance_mode=row[23],
            clickup_task_id=row[24],
            clickup_task_url=row[25],
            cd_listing_id=row[26],
            status=row[27],
            error_message=row[28],
            attachment_hash=row[29],
            attachment_name=row[30],
            created_at=row[31],
            updated_at=row[32],
        )

    @classmethod
    def get_headers(cls) -> list[str]:
        """Get column headers."""
        return [
            "received_at",
            "email_from",
            "email_subject",
            "message_id",
            "thread_root_id",
            "auction_source",
            "member_id",
            "pickup_address_raw",
            "pickup_name",
            "pickup_city",
            "pickup_state",
            "pickup_zip",
            "lot_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "vehicle_color",
            "gate_pass",
            "suggested_warehouse_id",
            "suggested_warehouse_state",
            "suggested_warehouse_address",
            "distance_miles",
            "distance_mode",
            "clickup_task_id",
            "clickup_task_url",
            "cd_listing_id",
            "status",
            "error_message",
            "attachment_hash",
            "attachment_name",
            "created_at",
            "updated_at",
        ]


class SheetsClient:
    """Google Sheets API client for pickup records."""

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(
        self,
        spreadsheet_id: str,
        sheet_name: str = "Pickups",
        credentials_file: str = "credentials.json",
        token_file: str = "token.json",
    ):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = sheet_name
        self.credentials_file = credentials_file
        self.token_file = token_file
        self._service = None
        self._row_cache: dict[str, int] = {}  # idempotency_key -> row_number

    def _get_service(self):
        """Get or create the Sheets API service."""
        if self._service is not None:
            return self._service

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None

        # Load existing token
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, self.SCOPES)

        # Refresh or create new token
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, self.SCOPES)
                creds = flow.run_local_server(port=0)

            # Save token
            with open(self.token_file, "w") as token:
                token.write(creds.to_json())

        self._service = build("sheets", "v4", credentials=creds)
        return self._service

    def _get_range(self, range_notation: str = "") -> str:
        """Get full range notation with sheet name."""
        if range_notation:
            return f"'{self.sheet_name}'!{range_notation}"
        return f"'{self.sheet_name}'"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def ensure_headers(self) -> None:
        """Ensure the sheet has headers in the first row."""
        service = self._get_service()

        # Check if headers exist
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=self._get_range("A1:AG1"),
            )
            .execute()
        )

        values = result.get("values", [])
        if not values or values[0] != PickupRecord.get_headers():
            # Set headers
            service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=self._get_range("A1"),
                valueInputOption="RAW",
                body={"values": [PickupRecord.get_headers()]},
            ).execute()
            logger.info("Created headers in sheet")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def append_record(self, record: PickupRecord) -> int:
        """Append a new record to the sheet. Returns row number."""
        service = self._get_service()

        # Set timestamps
        now = datetime.utcnow().isoformat() + "Z"
        record.created_at = now
        record.updated_at = now

        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.spreadsheet_id,
                range=self._get_range("A:AG"),
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [record.to_row()]},
            )
            .execute()
        )

        # Parse the updated range to get row number
        updated_range = result.get("updates", {}).get("updatedRange", "")
        # Format: 'Sheet'!A5:AG5
        if "!" in updated_range:
            range_part = updated_range.split("!")[-1]
            row_num = int("".join(filter(str.isdigit, range_part.split(":")[0])))
            self._row_cache[record.idempotency_key] = row_num
            logger.info(f"Appended record to row {row_num}")
            return row_num

        return -1

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def update_record(self, record: PickupRecord, row_number: int) -> bool:
        """Update an existing record at the specified row."""
        service = self._get_service()

        record.updated_at = datetime.utcnow().isoformat() + "Z"

        service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=self._get_range(f"A{row_number}:AG{row_number}"),
            valueInputOption="RAW",
            body={"values": [record.to_row()]},
        ).execute()

        logger.info(f"Updated record at row {row_number}")
        return True

    def find_row_by_key(self, idempotency_key: str) -> Optional[int]:
        """Find row number by idempotency key (thread_root_id:attachment_hash)."""
        # Check cache first
        if idempotency_key in self._row_cache:
            return self._row_cache[idempotency_key]

        # Search in sheet
        service = self._get_service()

        # Get all idempotency keys (columns E and AD)
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=self._get_range("E:E"),  # thread_root_id column
            )
            .execute()
        )

        thread_ids = result.get("values", [])

        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=self._get_range("AD:AD"),  # attachment_hash column
            )
            .execute()
        )

        hashes = result.get("values", [])

        # Build index
        for i, (tid_row, hash_row) in enumerate(zip(thread_ids, hashes), start=1):
            tid = tid_row[0] if tid_row else ""
            h = hash_row[0] if hash_row else ""
            key = f"{tid}:{h}"
            self._row_cache[key] = i

        return self._row_cache.get(idempotency_key)

    def upsert_record(self, record: PickupRecord) -> tuple[int, bool]:
        """Insert or update a record. Returns (row_number, was_insert)."""
        existing_row = self.find_row_by_key(record.idempotency_key)

        if existing_row:
            self.update_record(record, existing_row)
            return existing_row, False
        else:
            row_num = self.append_record(record)
            return row_num, True

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_records_by_status(self, status: PickupStatus) -> list[tuple[int, PickupRecord]]:
        """Get all records with the specified status. Returns list of (row_num, record)."""
        service = self._get_service()

        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=self._get_range("A:AG"),
            )
            .execute()
        )

        rows = result.get("values", [])
        records = []

        for i, row in enumerate(rows[1:], start=2):  # Skip header, 1-indexed
            record = PickupRecord.from_row(row)
            if record.status == status.value:
                records.append((i, record))
                self._row_cache[record.idempotency_key] = i

        return records

    def update_status(
        self,
        row_number: int,
        status: PickupStatus,
        error_message: str = "",
        clickup_task_id: str = "",
        clickup_task_url: str = "",
        cd_listing_id: str = "",
    ) -> bool:
        """Update specific fields for a record."""
        service = self._get_service()

        # Get current record
        result = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.spreadsheet_id,
                range=self._get_range(f"A{row_number}:AG{row_number}"),
            )
            .execute()
        )

        rows = result.get("values", [])
        if not rows:
            return False

        record = PickupRecord.from_row(rows[0])
        record.status = status.value
        record.updated_at = datetime.utcnow().isoformat() + "Z"

        if error_message:
            record.error_message = error_message
        if clickup_task_id:
            record.clickup_task_id = clickup_task_id
        if clickup_task_url:
            record.clickup_task_url = clickup_task_url
        if cd_listing_id:
            record.cd_listing_id = cd_listing_id

        return self.update_record(record, row_number)


def create_client_from_config(config) -> Optional[SheetsClient]:
    """Create SheetsClient from config if enabled."""
    if not config.sheets.enabled:
        return None

    return SheetsClient(
        spreadsheet_id=config.sheets.spreadsheet_id,
        sheet_name=config.sheets.sheet_name,
        credentials_file=config.sheets.credentials_file,
        token_file=config.sheets.token_file,
    )
