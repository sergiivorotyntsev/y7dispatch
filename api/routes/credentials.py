"""
Credential Management API Endpoints.

CRUD + connection testing for integration credentials:
- email_imap, email_forwarding, email_oauth
- cd_api, sheets, anthropic
"""

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.credential_store import (
    VALID_SERVICES,
    delete_credential,
    get_credential,
    get_credential_raw,
    list_credentials,
    save_credential,
    update_test_status,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# MODELS
# =============================================================================


class CredentialSaveRequest(BaseModel):
    """Request to save a credential."""

    config: dict[str, Any]
    enabled: bool = False


class CredentialResponse(BaseModel):
    """Credential data (secrets masked)."""

    service: str
    config: dict[str, Any]
    enabled: bool
    last_tested_at: Optional[str] = None
    last_test_status: Optional[str] = None


class CredentialTestResponse(BaseModel):
    """Connection test result."""

    status: str  # 'ok' or 'failed'
    message: str
    details: Optional[dict[str, Any]] = None
    duration_ms: Optional[int] = None


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/", response_model=list[CredentialResponse])
async def get_all_credentials():
    """List all stored credentials (secrets masked)."""
    return list_credentials()


@router.get("/{service}", response_model=CredentialResponse)
async def get_service_credential(service: str):
    """Get credential for a specific service (secrets masked)."""
    _validate_service(service)
    cred = get_credential(service)
    if not cred:
        raise HTTPException(status_code=404, detail=f"No credential found for {service}")
    return cred


@router.put("/{service}")
async def save_service_credential(service: str, data: CredentialSaveRequest):
    """Save or update credential for a service."""
    _validate_service(service)

    # If masked values are sent back, merge with existing raw values
    existing_raw = get_credential_raw(service)
    if existing_raw:
        merged_config = _merge_with_existing(data.config, existing_raw["config"])
    else:
        merged_config = data.config

    save_credential(service, merged_config, data.enabled)
    return {"status": "ok", "service": service}


@router.delete("/{service}")
async def delete_service_credential(service: str):
    """Delete credential for a service."""
    _validate_service(service)
    deleted = delete_credential(service)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No credential found for {service}")
    return {"status": "ok", "deleted": service}


@router.post("/{service}/test", response_model=CredentialTestResponse)
async def test_service_credential(service: str):
    """Test connection for a service using stored credentials."""
    _validate_service(service)

    raw = get_credential_raw(service)
    if not raw:
        raise HTTPException(status_code=404, detail=f"No credential found for {service}")

    config = raw["config"]
    start = time.time()

    try:
        result = await _test_service(service, config)
        duration_ms = int((time.time() - start) * 1000)

        status = result.get("status", "ok")
        update_test_status(service, status)

        return CredentialTestResponse(
            status=status,
            message=result.get("message", "Connection successful"),
            details=result.get("details"),
            duration_ms=duration_ms,
        )
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        update_test_status(service, "failed")
        return CredentialTestResponse(
            status="failed",
            message=str(e),
            duration_ms=duration_ms,
        )


# =============================================================================
# HELPERS
# =============================================================================


def _validate_service(service: str):
    """Validate service name."""
    if service not in VALID_SERVICES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid service: {service}. Must be one of: {sorted(VALID_SERVICES)}",
        )


def _merge_with_existing(new_config: dict, existing_config: dict) -> dict:
    """Merge new config with existing, preserving unchanged masked secrets."""
    merged = {**existing_config}
    for key, value in new_config.items():
        if isinstance(value, str) and "●" in value:
            # Masked value — keep existing
            continue
        if isinstance(value, str) and "****" in value:
            # Alternative mask — keep existing
            continue
        merged[key] = value
    return merged


async def _test_service(service: str, config: dict) -> dict:
    """Test connection for a specific service."""
    if service == "email_imap":
        return await _test_email_imap(config)
    elif service == "email_forwarding":
        return _test_email_forwarding(config)
    elif service == "email_oauth":
        return await _test_email_oauth(config)
    elif service == "cd_api":
        return await _test_cd_api(config)
    elif service == "sheets":
        return await _test_sheets(config)
    elif service == "anthropic":
        return await _test_anthropic(config)
    else:
        return {"status": "failed", "message": f"No test available for {service}"}


async def _test_email_imap(config: dict) -> dict:
    """Test IMAP connection."""
    import imaplib
    import ssl

    server = config.get("imap_server", "")
    port = int(config.get("imap_port", 993))
    email_addr = config.get("email_address", "")
    password = config.get("password", "")

    if not all([server, email_addr, password]):
        return {"status": "failed", "message": "Missing required fields: imap_server, email_address, password"}

    ctx = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(server, port, ssl_context=ctx)
    try:
        imap.login(email_addr, password)
        status, data = imap.select("INBOX", readonly=True)
        msg_count = int(data[0]) if status == "OK" else 0
        imap.logout()
        return {
            "status": "ok",
            "message": f"Connected to {server}:{port}",
            "details": {"messages_in_inbox": msg_count},
        }
    except imaplib.IMAP4.error as e:
        return {"status": "failed", "message": f"IMAP login failed: {e}"}
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def _test_email_forwarding(config: dict) -> dict:
    """Test email forwarding config (just validates webhook URL is set)."""
    webhook_url = config.get("webhook_url", "")
    secret_key = config.get("secret_key", "")

    if not webhook_url:
        return {"status": "failed", "message": "No webhook_url configured"}

    return {
        "status": "ok",
        "message": f"Forwarding configured to {webhook_url}",
        "details": {"has_secret_key": bool(secret_key)},
    }


async def _test_email_oauth(config: dict) -> dict:
    """Test OAuth2 email: acquire token via client_credentials, connect IMAP with XOAUTH2."""
    import base64
    import imaplib
    import ssl

    import httpx

    tenant_id = config.get("tenant_id", "")
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")
    email_addr = config.get("email_address", "")

    if not all([tenant_id, client_id, client_secret, email_addr]):
        missing = []
        if not tenant_id: missing.append("tenant_id")
        if not client_id: missing.append("client_id")
        if not client_secret: missing.append("client_secret")
        if not email_addr: missing.append("email_address")
        return {"status": "failed", "message": f"Missing required fields: {', '.join(missing)}"}

    # Step 1: Acquire access_token via client_credentials grant
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    token_data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://outlook.office365.com/.default",
        "grant_type": "client_credentials",
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(token_url, data=token_data, timeout=15.0)

        if resp.status_code != 200:
            error_detail = resp.json().get("error_description", resp.text)
            return {"status": "failed", "message": f"Token request failed: {error_detail}"}

        access_token = resp.json()["access_token"]
        expires_in = resp.json().get("expires_in", 3600)
    except Exception as e:
        return {"status": "failed", "message": f"Token request error: {e}"}

    # Step 2: Connect IMAP with XOAUTH2
    try:
        ctx = ssl.create_default_context()
        imap = imaplib.IMAP4_SSL("outlook.office365.com", 993, ssl_context=ctx)

        auth_string = f"user={email_addr}\x01auth=Bearer {access_token}\x01\x01"
        imap.authenticate("XOAUTH2", lambda x: auth_string.encode())

        status, data = imap.select("INBOX", readonly=True)
        msg_count = int(data[0]) if status == "OK" else 0

        # Count unread
        _, unseen = imap.search(None, "UNSEEN")
        unseen_count = len(unseen[0].split()) if unseen[0] else 0

        imap.logout()

        return {
            "status": "ok",
            "message": f"Connected to outlook.office365.com as {email_addr}",
            "details": {
                "server": "outlook.office365.com",
                "auth": "OAuth2 XOAUTH2",
                "messages_in_inbox": msg_count,
                "unread_messages": unseen_count,
                "token_expires_in": expires_in,
            },
        }
    except imaplib.IMAP4.error as e:
        return {"status": "failed", "message": f"IMAP XOAUTH2 auth failed: {e}"}
    except Exception as e:
        return {"status": "failed", "message": f"IMAP connection failed: {e}"}


async def _test_cd_api(config: dict) -> dict:
    """Test Central Dispatch API connection via OAuth2 client_credentials."""
    client_id = config.get("client_id", "")
    client_secret = config.get("client_secret", "")

    if not client_id:
        return {"status": "failed", "message": "Missing client_id"}
    if not client_secret:
        return {"status": "failed", "message": "Missing client_secret"}

    from api.cd_client import get_cd_urls

    environment = config.get("environment", "test")
    urls = get_cd_urls(environment)
    token_url = config.get("token_url") or urls["token_url"]
    api_base_url = config.get("api_base_url") or urls["api_base_url"]
    scopes = config.get("scopes", "marketplace")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            logger.info("[CD Test] POST %s", token_url)
            token_resp = await client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": scopes,
                },
            )
            logger.info("[CD Test] Token response: %d", token_resp.status_code)

            if token_resp.status_code != 200:
                return {
                    "status": "failed",
                    "message": f"Token request to {token_url} returned {token_resp.status_code}: {token_resp.text[:300]}",
                    "details": {
                        "url": token_url,
                        "status_code": token_resp.status_code,
                        "response_body": token_resp.text[:500],
                    },
                }

            token_data = token_resp.json()
            expires_in = token_data.get("expires_in", 0)

            # Token acquired = credentials valid
            return {
                "status": "ok",
                "message": f"Connected. Bearer token obtained, expires in {expires_in}s",
                "details": {
                    "environment": environment,
                    "marketplace_id": config.get("marketplace_id", ""),
                    "token_url": token_url,
                    "expires_in": expires_in,
                },
            }
    except Exception as e:
        return {
            "status": "failed",
            "message": f"CD API connection failed: {e}",
            "details": {"token_url": token_url, "error_type": type(e).__name__},
        }


async def _test_sheets(config: dict) -> dict:
    """Test Google Sheets connection."""
    from pathlib import Path

    spreadsheet_id = config.get("spreadsheet_id", "")
    creds_file = config.get("credentials_file", "config/sheets_credentials.json")

    if not spreadsheet_id:
        return {"status": "failed", "message": "No spreadsheet_id configured"}

    if not Path(creds_file).exists():
        return {"status": "failed", "message": f"Credentials file not found: {creds_file}"}

    try:
        from core.config import SheetsConfig
        from services.sheets_exporter import SheetsExporter

        sheets_config = SheetsConfig(
            spreadsheet_id=spreadsheet_id,
            sheet_name=config.get("sheet_name", "Pickups"),
            credentials_file=creds_file,
        )
        exporter = SheetsExporter(sheets_config)
        exporter.ensure_headers()
        return {
            "status": "ok",
            "message": f"Connected to spreadsheet {spreadsheet_id}",
        }
    except Exception as e:
        return {"status": "failed", "message": f"Sheets connection failed: {e}"}


async def _test_anthropic(config: dict) -> dict:
    """Test Anthropic API key by making a minimal API call."""
    api_key = config.get("api_key", "")

    if not api_key:
        return {"status": "failed", "message": "No api_key configured"}

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say OK"}],
        )
        return {
            "status": "ok",
            "message": "Anthropic API key is valid",
            "details": {
                "model": "claude-haiku-4-5-20251001",
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }
    except Exception as e:
        return {"status": "failed", "message": f"Anthropic API test failed: {e}"}
