"""
Central Dispatch API Client

Handles communication with Central Dispatch V2 API for listing management.
Implements OAuth2 Client Credentials flow, ETag-based optimistic concurrency,
rate limiting, and retries.
"""

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

MAX_RETRIES = 3
CD_SEMAPHORE_LIMIT = 5  # Max concurrent CD API calls
RETRY_BACKOFF_BASE = 2  # Exponential backoff base (seconds)
TOKEN_REFRESH_MARGIN = 60  # Refresh token 60s before expiry


# =============================================================================
# ENVIRONMENT URL RESOLUTION
# =============================================================================


def get_cd_urls(environment: str) -> dict[str, str]:
    """
    Resolve API base URL and token URL based on environment.

    Args:
        environment: "test" (sandbox) or "production"

    Returns:
        dict with api_base_url and token_url
    """
    # Single auth and API URL for all environments.
    # Test vs production differs only by marketplace_id in the payload.
    return {
        "api_base_url": "https://marketplace-api.centraldispatch.com",
        "token_url": "https://id.centraldispatch.com/connect/token",
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def generate_partner_reference_id(document_id: int, run_id: int) -> str:
    """
    Generate stable, unique partner reference ID for a document.

    Format: CD-{doc_id}-{run_id}-{hash[:8]}
    Limited to 50 characters for CD API compatibility.
    """
    # Create deterministic hash from doc_id and run_id
    hash_input = f"{document_id}-{run_id}"
    hash_suffix = hashlib.md5(hash_input.encode()).hexdigest()[:8]

    ref_id = f"CD-{document_id}-{run_id}-{hash_suffix}"

    # Ensure max length
    if len(ref_id) > 50:
        ref_id = ref_id[:50]

    return ref_id


def generate_idempotency_key(ref_id: str, operation: str) -> str:
    """Generate idempotency key for CD API requests."""
    timestamp = int(time.time() / 3600)  # Hour-based key
    return hashlib.sha256(f"{ref_id}-{operation}-{timestamp}".encode()).hexdigest()[:32]


# =============================================================================
# CD CLIENT
# =============================================================================


@dataclass
class CDResponse:
    """Response from CD API."""

    success: bool
    listing_id: Optional[str] = None
    etag: Optional[str] = None
    error: Optional[str] = None
    status_code: int = 0
    retries: int = 0


class CDClient:
    """
    Central Dispatch API Client with OAuth2 Client Credentials.

    Features:
    - OAuth2 client_credentials token acquisition + caching
    - Auto-refresh when token expires (with 60s safety margin)
    - ETag-based optimistic concurrency
    - Rate limit handling (429)
    - Automatic retries with exponential backoff
    - Idempotency for safe retries
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        token_url: Optional[str] = None,
        base_url: Optional[str] = None,
        scopes: Optional[str] = None,
        timeout: int = 30,
        # Legacy: still accept api_key for backward compat during migration
        api_key: Optional[str] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.scopes = scopes
        self.timeout = timeout

        # Token cache
        self._cached_token: Optional[str] = None
        self._token_expires_at: float = 0

        # Legacy api_key fallback
        self._legacy_api_key = api_key

        # Resolve from credential store if not provided explicitly
        if not self.client_id:
            self._load_from_credential_store()

        # Resolve URLs from environment if not provided
        if not self.token_url or not base_url:
            env = self._resolve_environment()
            urls = get_cd_urls(env)
            self.token_url = self.token_url or urls["token_url"]
            base_url = base_url or urls["api_base_url"]

        self.base_url = base_url or os.environ.get(
            "CD_API_URL", "https://api.sandbox.centraldispatch.com/v2"
        )
        self._semaphore = asyncio.Semaphore(CD_SEMAPHORE_LIMIT)

    def _load_from_credential_store(self):
        """Load OAuth2 credentials from the credential store."""
        try:
            from services.credential_store import get_credential_for_service

            cred = get_credential_for_service("cd_api")
            if cred:
                self.client_id = cred.get("client_id", "")
                self.client_secret = cred.get("client_secret", "")
                self.scopes = cred.get("scopes", "marketplace")
                env = cred.get("environment", "test")
                urls = get_cd_urls(env)
                self.token_url = cred.get("token_url") or urls["token_url"]
                self.base_url = cred.get("api_base_url") or urls["api_base_url"]
        except Exception:
            pass

        # Legacy fallback: env var
        if not self.client_id and not self._legacy_api_key:
            self._legacy_api_key = os.environ.get("CD_API_KEY", "")

    def _resolve_environment(self) -> str:
        """Resolve environment from credential store or default to test."""
        try:
            from services.credential_store import get_credential_for_service

            cred = get_credential_for_service("cd_api")
            if cred:
                return cred.get("environment", "test")
        except Exception:
            pass
        return "test"

    def _acquire_token(self) -> str:
        """
        Acquire OAuth2 token via client_credentials grant.

        Raises Exception if acquisition fails.
        """
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.scopes:
            data["scope"] = self.scopes

        response = requests.post(
            self.token_url,
            data=data,
            timeout=15,
        )

        if response.status_code != 200:
            raise Exception(
                f"OAuth2 token acquisition failed: {response.status_code} {response.text[:200]}"
            )

        token_data = response.json()
        access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)

        # Cache with safety margin
        self._cached_token = access_token
        self._token_expires_at = time.time() + expires_in - TOKEN_REFRESH_MARGIN

        logger.info("OAuth2 token acquired, expires in %ds", expires_in)
        return access_token

    def _get_bearer_token(self) -> str:
        """
        Get a valid Bearer token, using cache or acquiring a new one.

        Returns cached token if still valid, otherwise acquires fresh token.
        """
        if self._cached_token and time.time() < self._token_expires_at:
            return self._cached_token

        return self._acquire_token()

    def _get_headers(
        self, etag: Optional[str] = None, idempotency_key: Optional[str] = None
    ) -> dict[str, str]:
        """Build request headers with OAuth2 Bearer token."""
        # Use OAuth2 if client_id is configured, otherwise legacy api_key
        if self.client_id and self.client_secret:
            token = self._get_bearer_token()
        else:
            token = self._legacy_api_key or ""

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/vnd.coxauto.v2+json",
            "Accept": "application/vnd.coxauto.v2+json",
        }
        if etag:
            headers["If-Match"] = etag
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _handle_rate_limit(self, response: requests.Response) -> float:
        """Extract Retry-After and return wait time."""
        retry_after = response.headers.get("Retry-After", "5")
        try:
            return float(retry_after)
        except ValueError:
            return 5.0

    def create_listing(self, payload: dict[str, Any]) -> CDResponse:
        """
        Create a new listing on Central Dispatch.

        Uses idempotency key to prevent duplicates on retry.
        """
        ref_id = payload.get("partnerReferenceId", "unknown")
        idempotency_key = generate_idempotency_key(ref_id, "create")

        retries = 0
        last_error = None

        while retries <= MAX_RETRIES:
            try:
                response = requests.post(
                    f"{self.base_url}/listings",
                    json=payload,
                    headers=self._get_headers(idempotency_key=idempotency_key),
                    timeout=self.timeout,
                )

                if response.status_code == 201:
                    data = response.json()
                    return CDResponse(
                        success=True,
                        listing_id=data.get("id"),
                        etag=response.headers.get("ETag") or data.get("etag"),
                        status_code=201,
                        retries=retries,
                    )

                if response.status_code == 429:
                    # Rate limited
                    wait_time = self._handle_rate_limit(response)
                    logger.warning(f"Rate limited, waiting {wait_time}s")
                    time.sleep(wait_time)
                    retries += 1
                    continue

                if response.status_code == 409:
                    # Conflict - listing may already exist
                    # Try to find existing by reference ID
                    return self._find_existing_listing(ref_id)

                # Other error — capture full response for debugging
                body_text = response.text[:1000]
                logger.error(
                    "CD API create_listing failed: HTTP %d, url=%s/listings, body=%s",
                    response.status_code, self.base_url, body_text,
                )
                last_error = f"HTTP {response.status_code}: {body_text}"
                retries += 1

            except requests.RequestException as e:
                last_error = str(e)
                retries += 1
                time.sleep(RETRY_BACKOFF_BASE**retries)

        return CDResponse(
            success=False,
            error=last_error,
            retries=retries,
        )

    def update_listing(
        self,
        listing_id: str,
        payload: dict[str, Any],
        etag: str,
    ) -> CDResponse:
        """
        Update an existing listing.

        Requires ETag for optimistic concurrency via If-Match header.
        On 412, refreshes ETag and retries.
        """
        retries = 0
        current_etag = etag
        last_error = None

        while retries <= MAX_RETRIES:
            try:
                response = requests.put(
                    f"{self.base_url}/listings/{listing_id}",
                    json=payload,
                    headers=self._get_headers(etag=current_etag),
                    timeout=self.timeout,
                )

                if response.status_code == 200:
                    data = response.json()
                    return CDResponse(
                        success=True,
                        listing_id=listing_id,
                        etag=response.headers.get("ETag") or data.get("etag"),
                        status_code=200,
                        retries=retries,
                    )

                if response.status_code == 412:
                    # Precondition failed - ETag mismatch
                    logger.warning(f"ETag mismatch for {listing_id}, refreshing")
                    new_etag = self._fetch_current_etag(listing_id)
                    if new_etag:
                        current_etag = new_etag
                        retries += 1
                        continue
                    else:
                        last_error = "Failed to refresh ETag"
                        break

                if response.status_code == 429:
                    wait_time = self._handle_rate_limit(response)
                    logger.warning(f"Rate limited, waiting {wait_time}s")
                    time.sleep(wait_time)
                    retries += 1
                    continue

                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                retries += 1

            except requests.RequestException as e:
                last_error = str(e)
                retries += 1
                time.sleep(RETRY_BACKOFF_BASE**retries)

        return CDResponse(
            success=False,
            error=last_error,
            retries=retries,
        )

    def get_listing(self, listing_id: str) -> CDResponse:
        """Get listing details including current ETag."""
        try:
            response = requests.get(
                f"{self.base_url}/listings/{listing_id}",
                headers=self._get_headers(),
                timeout=self.timeout,
            )

            if response.status_code == 200:
                response.json()
                return CDResponse(
                    success=True,
                    listing_id=listing_id,
                    etag=response.headers.get("ETag"),
                    status_code=200,
                )

            return CDResponse(
                success=False,
                error=f"HTTP {response.status_code}",
                status_code=response.status_code,
            )

        except requests.RequestException as e:
            return CDResponse(success=False, error=str(e))

    def _fetch_current_etag(self, listing_id: str) -> Optional[str]:
        """Fetch current ETag for a listing."""
        result = self.get_listing(listing_id)
        return result.etag if result.success else None

    def _find_existing_listing(self, ref_id: str) -> CDResponse:
        """Find existing listing by partner reference ID."""
        try:
            response = requests.get(
                f"{self.base_url}/listings",
                params={"partnerReferenceId": ref_id},
                headers=self._get_headers(),
                timeout=self.timeout,
            )

            if response.status_code == 200:
                data = response.json()
                listings = data.get("listings", [])
                if listings:
                    listing = listings[0]
                    return CDResponse(
                        success=True,
                        listing_id=listing.get("id"),
                        etag=listing.get("etag"),
                        status_code=200,
                    )

            return CDResponse(
                success=False,
                error="Listing not found",
            )

        except requests.RequestException as e:
            return CDResponse(success=False, error=str(e))


# =============================================================================
# ASYNC CLIENT (for batch operations)
# =============================================================================


class AsyncCDClient:
    """Async version of CD client for batch operations."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        # Legacy
        api_key: Optional[str] = None,
    ):
        self.sync_client = CDClient(
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            api_key=api_key,
        )
        self._semaphore = asyncio.Semaphore(CD_SEMAPHORE_LIMIT)

    async def create_listing(self, payload: dict[str, Any]) -> CDResponse:
        """Create listing with semaphore limiting."""
        async with self._semaphore:
            # Run sync client in executor
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.sync_client.create_listing, payload)

    async def update_listing(
        self,
        listing_id: str,
        payload: dict[str, Any],
        etag: str,
    ) -> CDResponse:
        """Update listing with semaphore limiting."""
        async with self._semaphore:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None, self.sync_client.update_listing, listing_id, payload, etag
            )
