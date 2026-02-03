"""
Google Sheets Integration

Endpoints for testing and managing Google Sheets connection.
"""

import time

from fastapi import APIRouter

from api.routes.integrations.utils import (
    TestConnectionResponse,
    log_integration_action,
)

router = APIRouter(prefix="/sheets", tags=["Google Sheets"])


@router.post("/test", response_model=TestConnectionResponse)
async def test_sheets_connection():
    """
    Test Google Sheets connection.

    Verifies service account credentials and spreadsheet access.
    Tests both read and write permissions.
    """
    from api.routes.settings import load_settings

    start_time = time.time()
    settings = load_settings()
    sheets = settings.get("sheets", {})

    spreadsheet_id = sheets.get("spreadsheet_id")
    credentials_json = sheets.get("credentials_json")
    sheet_name = sheets.get("sheet_name", "Sheet1")

    if not spreadsheet_id:
        log_integration_action("sheets", "test", "failed", error="Spreadsheet ID not configured")
        return TestConnectionResponse(
            status="error",
            message="Google Sheets not configured. Set spreadsheet ID in settings.",
        )

    if not credentials_json:
        log_integration_action(
            "sheets", "test", "failed", error="Service account credentials not configured"
        )
        return TestConnectionResponse(
            status="error",
            message="Service account credentials not configured.",
        )

    try:
        import json

        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds_dict = (
            json.loads(credentials_json) if isinstance(credentials_json, str) else credentials_json
        )
        creds = Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build("sheets", "v4", credentials=creds)

        result = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        title = result.get("properties", {}).get("title", "Unknown")

        sheet_exists = any(
            s.get("properties", {}).get("title") == sheet_name for s in result.get("sheets", [])
        )

        write_ok = False
        try:
            test_range = f"{sheet_name}!ZZ1"
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=test_range,
                valueInputOption="RAW",
                body={"values": [["test"]]},
            ).execute()

            service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=test_range,
            ).execute()
            write_ok = True
        except Exception:
            pass

        duration_ms = int((time.time() - start_time) * 1000)

        log_integration_action(
            "sheets",
            "test",
            "success",
            details={"title": title, "write_ok": write_ok},
            duration_ms=duration_ms,
        )

        return TestConnectionResponse(
            status="ok",
            message=f"Connected to spreadsheet: {title}",
            details={
                "spreadsheet_id": spreadsheet_id,
                "title": title,
                "sheet_exists": sheet_exists,
                "sheet_name": sheet_name,
                "write_access": write_ok,
            },
            duration_ms=duration_ms,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        error_str = str(e)

        if "403" in error_str or "permission" in error_str.lower():
            message = "Permission denied. Share the spreadsheet with the service account email."
        elif "404" in error_str:
            message = "Spreadsheet not found. Check the spreadsheet ID."
        else:
            message = f"Connection failed: {error_str}"

        log_integration_action(
            "sheets", "test", "failed", error=error_str[:200], duration_ms=duration_ms
        )

        return TestConnectionResponse(
            status="error",
            message=message,
            duration_ms=duration_ms,
        )
