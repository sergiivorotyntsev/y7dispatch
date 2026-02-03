"""ClickUp API client for creating vehicle pickup tasks."""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class ClickUpTask:
    name: str
    description: str
    priority: int = 3
    tags: Optional[list[str]] = None
    custom_fields: Optional[dict[str, Any]] = None


class ClickUpClient:
    API_BASE = "https://api.clickup.com/api/v2"

    def __init__(self, token: str, list_id: str, timeout: int = 30):
        self.token = token
        self.list_id = list_id
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Authorization": token, "Content-Type": "application/json"})

    def _make_request(
        self, method: str, endpoint: str, data: Optional[dict] = None, retries: int = 3
    ) -> requests.Response:
        url = f"{self.API_BASE}{endpoint}"
        for attempt in range(retries):
            try:
                response = self._session.request(
                    method=method, url=url, json=data, timeout=self.timeout
                )
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    time.sleep(retry_after)
                    continue
                return response
            except requests.RequestException:
                if attempt < retries - 1:
                    time.sleep(2**attempt)
                else:
                    raise
        raise ClickUpAPIError("Max retries exceeded")

    def create_task(self, task: ClickUpTask) -> dict[str, Any]:
        payload = {"name": task.name, "description": task.description, "priority": task.priority}
        if task.tags:
            payload["tags"] = task.tags

        response = self._make_request("POST", f"/list/{self.list_id}/task", data=payload)

        if response.status_code in (200, 201):
            data = response.json()
            return {
                "success": True,
                "task_id": data.get("id"),
                "url": data.get("url"),
                "response": data,
            }
        else:
            raise ClickUpAPIError(f"Failed to create task: {response.text}")

    def validate_credentials(self) -> bool:
        try:
            response = self._make_request("GET", "/user")
            return response.status_code == 200
        except Exception:
            return False


class ClickUpAPIError(Exception):
    pass


def create_client_from_env() -> ClickUpClient:
    token = os.environ.get("CLICKUP_TOKEN")
    list_id = os.environ.get("CLICKUP_LIST_ID")
    if not token:
        raise ValueError("CLICKUP_TOKEN environment variable required")
    if not list_id:
        raise ValueError("CLICKUP_LIST_ID environment variable required")
    return ClickUpClient(token=token, list_id=list_id)


def create_vehicle_pickup_task(
    client: ClickUpClient,
    vin: str,
    lot_number: str,
    vehicle_desc: str,
    pickup_address: str,
    gate_pass: Optional[str] = None,
    source: str = "UNKNOWN",
    additional_notes: Optional[str] = None,
) -> dict[str, Any]:
    name = f"Pickup: {vehicle_desc} | LOT {lot_number}"

    desc_parts = [
        f"**Source:** {source}",
        f"**VIN:** {vin}",
        f"**Lot #:** {lot_number}",
        f"**Vehicle:** {vehicle_desc}",
        "",
        "**Pickup Address:**",
        pickup_address,
    ]

    if gate_pass:
        desc_parts.insert(4, f"**Gate Pass:** {gate_pass}")

    if additional_notes:
        desc_parts.extend(["", "**Notes:**", additional_notes])

    task = ClickUpTask(
        name=name, description="\n".join(desc_parts), priority=3, tags=[source.lower()]
    )
    return client.create_task(task)
