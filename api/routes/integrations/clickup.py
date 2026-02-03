"""
ClickUp Integration

Endpoints for testing and managing ClickUp connection.
"""

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.routes.integrations.utils import (
    TestConnectionResponse,
    log_integration_action,
)

router = APIRouter(prefix="/clickup", tags=["ClickUp"])


class ClickUpCustomField(BaseModel):
    """ClickUp custom field."""

    id: str
    name: str
    type: str
    required: bool = False


class ClickUpCustomFieldsResponse(BaseModel):
    """Response with custom fields."""

    list_id: str
    fields: list[ClickUpCustomField]


@router.post("/test", response_model=TestConnectionResponse)
async def test_clickup_connection():
    """
    Test ClickUp API connection.

    Verifies API key is valid and can access the configured list.
    """
    from api.routes.settings import load_settings

    start_time = time.time()
    settings = load_settings()
    clickup = settings.get("clickup", {})

    api_key = clickup.get("api_key")
    list_id = clickup.get("list_id")

    if not api_key or not list_id:
        log_integration_action("clickup", "test", "failed", error="ClickUp not configured")
        return TestConnectionResponse(
            status="error",
            message="ClickUp not configured. Set API key and list ID in settings.",
        )

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.clickup.com/api/v2/list/{list_id}",
                headers={"Authorization": api_key},
                timeout=10.0,
            )

        duration_ms = int((time.time() - start_time) * 1000)

        if response.status_code == 200:
            data = response.json()
            log_integration_action(
                "clickup",
                "test",
                "success",
                details={"list_name": data.get("name")},
                duration_ms=duration_ms,
            )
            return TestConnectionResponse(
                status="ok",
                message=f"Connected to list: {data.get('name')}",
                details={
                    "list_id": list_id,
                    "list_name": data.get("name"),
                    "folder": data.get("folder", {}).get("name"),
                    "space": data.get("space", {}).get("name"),
                },
                duration_ms=duration_ms,
            )
        else:
            error_msg = response.text[:200]
            log_integration_action(
                "clickup", "test", "failed", error=error_msg, duration_ms=duration_ms
            )
            return TestConnectionResponse(
                status="error",
                message=f"ClickUp API error: {response.status_code}",
                details={"error": error_msg},
                duration_ms=duration_ms,
            )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        log_integration_action("clickup", "test", "failed", error=str(e), duration_ms=duration_ms)
        return TestConnectionResponse(
            status="error",
            message=f"Connection failed: {str(e)}",
            duration_ms=duration_ms,
        )


@router.get("/custom-fields/{list_id}", response_model=ClickUpCustomFieldsResponse)
async def get_clickup_custom_fields(list_id: str):
    """
    Get custom fields for a ClickUp list.

    Useful for setting up field mappings.
    """
    from api.routes.settings import load_settings

    settings = load_settings()
    clickup = settings.get("clickup", {})
    api_key = clickup.get("api_key")

    if not api_key:
        raise HTTPException(status_code=400, detail="ClickUp API key not configured")

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.clickup.com/api/v2/list/{list_id}/field",
                headers={"Authorization": api_key},
                timeout=10.0,
            )

        if response.status_code == 200:
            data = response.json()
            fields = [
                ClickUpCustomField(
                    id=f["id"],
                    name=f["name"],
                    type=f["type"],
                    required=f.get("required", False),
                )
                for f in data.get("fields", [])
            ]

            log_integration_action(
                "clickup",
                "get_custom_fields",
                "success",
                details={"list_id": list_id, "field_count": len(fields)},
            )

            return ClickUpCustomFieldsResponse(
                list_id=list_id,
                fields=fields,
            )
        else:
            raise HTTPException(
                status_code=response.status_code, detail=f"ClickUp API error: {response.text[:200]}"
            )

    except HTTPException:
        raise
    except Exception as e:
        log_integration_action("clickup", "get_custom_fields", "failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
