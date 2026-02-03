"""Central Dispatch API client service."""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

from models.vehicle import TransportListing

logger = logging.getLogger(__name__)


@dataclass
class TokenInfo:
    access_token: str
    expires_at: datetime
    refresh_token: Optional[str] = None

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() >= (self.expires_at - timedelta(minutes=5))


class CentralDispatchClient:
    PROD_TOKEN_URL = "https://id.centraldispatch.com/connect/token"
    PROD_API_BASE = "https://marketplace-api.centraldispatch.com"
    PROD_MARKETPLACE_ID = 10000
    API_VERSION_HEADER = "application/vnd.coxauto.v2+json"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        marketplace_id: Optional[int] = None,
        is_test: bool = False,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.marketplace_id = marketplace_id or self.PROD_MARKETPLACE_ID
        self.token_url = self.PROD_TOKEN_URL
        self.api_base = self.PROD_API_BASE
        self._token_info: Optional[TokenInfo] = None
        self._session = requests.Session()

    def _get_access_token(self) -> str:
        if self._token_info and not self._token_info.is_expired:
            return self._token_info.access_token

        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "marketplace",
        }
        response = self._session.post(
            self.token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        response.raise_for_status()

        token_data = response.json()
        self._token_info = TokenInfo(
            access_token=token_data["access_token"],
            expires_at=datetime.utcnow() + timedelta(seconds=token_data.get("expires_in", 3600)),
        )
        return self._token_info.access_token

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        extra_headers: Optional[dict[str, str]] = None,
        retries: int = 3,
    ) -> requests.Response:
        url = f"{self.api_base}{endpoint}"
        for attempt in range(retries):
            try:
                token = self._get_access_token()
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": self.API_VERSION_HEADER,
                    "Accept": "application/json",
                }
                if extra_headers:
                    headers.update(extra_headers)
                response = self._session.request(
                    method=method, url=url, headers=headers, json=data, params=params, timeout=60
                )
                if response.status_code == 401:
                    self._token_info = None
                    continue
                return response
            except requests.RequestException:
                if attempt < retries - 1:
                    time.sleep(2**attempt)
                else:
                    raise
        raise APIError("Max retries exceeded")

    def create_listing(self, listing: TransportListing) -> dict[str, Any]:
        listing_data = listing.to_cd_listing(self.marketplace_id)
        response = self._make_request("POST", "/listings", data=listing_data)
        if response.status_code == 201:
            location = response.headers.get("Location", "")
            listing_id = location.split("/")[-1] if location else None
            return {
                "success": True,
                "listing_id": listing_id,
                "etag": response.headers.get("ETag"),
                "location": location,
            }
        else:
            raise APIError(f"Failed to create listing: {response.text}")

    def validate_credentials(self) -> bool:
        try:
            self._get_access_token()
            return True
        except Exception:
            return False


class AuthenticationError(Exception):
    pass


class APIError(Exception):
    pass


def create_client_from_env() -> CentralDispatchClient:
    client_id = os.environ.get("CD_CLIENT_ID")
    client_secret = os.environ.get("CD_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("CD_CLIENT_ID and CD_CLIENT_SECRET environment variables must be set")
    marketplace_id = os.environ.get("CD_MARKETPLACE_ID")
    return CentralDispatchClient(
        client_id=client_id,
        client_secret=client_secret,
        marketplace_id=int(marketplace_id) if marketplace_id else None,
    )
