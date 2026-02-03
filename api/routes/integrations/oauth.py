"""
OAuth2 Integration for Email Providers

Supports:
- Microsoft 365 / Outlook (MSAL)
- Gmail (Google OAuth2)
"""

from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.database import get_connection
from api.routes.integrations.utils import (
    decrypt_secret,
    encrypt_secret,
    log_integration_action,
)

router = APIRouter(prefix="/oauth", tags=["OAuth"])


# =============================================================================
# MODELS
# =============================================================================


class OAuthConfig(BaseModel):
    """OAuth configuration."""

    provider: str  # microsoft, google
    client_id: str
    client_secret: str
    tenant_id: Optional[str] = None  # Microsoft only
    redirect_uri: str = "http://localhost:8000/api/integrations/oauth/callback"


class OAuthToken(BaseModel):
    """OAuth token response."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None
    token_type: str = "Bearer"
    scope: Optional[str] = None


class OAuthInitResponse(BaseModel):
    """Response with authorization URL."""

    auth_url: str
    state: str


# =============================================================================
# TOKEN STORAGE
# =============================================================================


def init_oauth_table():
    """Initialize OAuth tokens table."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                email TEXT NOT NULL,
                access_token_encrypted TEXT NOT NULL,
                refresh_token_encrypted TEXT,
                expires_at TEXT,
                token_type TEXT DEFAULT 'Bearer',
                scope TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, email)
            )
        """)
        conn.commit()


def store_token(
    provider: str,
    email: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    expires_at: Optional[str] = None,
    scope: Optional[str] = None,
):
    """Store OAuth token securely."""
    init_oauth_table()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO oauth_tokens
            (provider, email, access_token_encrypted, refresh_token_encrypted, expires_at, scope, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                provider,
                email,
                encrypt_secret(access_token),
                encrypt_secret(refresh_token) if refresh_token else None,
                expires_at,
                scope,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()


def get_token(provider: str, email: str) -> Optional[dict[str, Any]]:
    """Get stored OAuth token."""
    init_oauth_table()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM oauth_tokens WHERE provider = ? AND email = ?", (provider, email)
        ).fetchone()

    if not row:
        return None

    return {
        "access_token": decrypt_secret(row["access_token_encrypted"]),
        "refresh_token": (
            decrypt_secret(row["refresh_token_encrypted"])
            if row["refresh_token_encrypted"]
            else None
        ),
        "expires_at": row["expires_at"],
        "scope": row["scope"],
    }


def is_token_expired(expires_at: Optional[str]) -> bool:
    """Check if token is expired."""
    if not expires_at:
        return True

    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        # Consider expired if less than 5 minutes left
        return expiry < datetime.utcnow() + timedelta(minutes=5)
    except Exception:
        return True


# =============================================================================
# MICROSOFT OAUTH2
# =============================================================================


def get_microsoft_auth_url(client_id: str, tenant_id: str, redirect_uri: str, state: str) -> str:
    """Generate Microsoft OAuth2 authorization URL."""
    from urllib.parse import urlencode

    # Use common if no tenant specified
    authority = f"https://login.microsoftonline.com/{tenant_id or 'common'}"

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": "https://outlook.office365.com/IMAP.AccessAsUser.All offline_access",
        "state": state,
    }

    return f"{authority}/oauth2/v2.0/authorize?{urlencode(params)}"


async def exchange_microsoft_code(
    code: str,
    client_id: str,
    client_secret: str,
    tenant_id: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange authorization code for tokens."""
    import httpx

    authority = f"https://login.microsoftonline.com/{tenant_id or 'common'}"
    token_url = f"{authority}/oauth2/v2.0/token"

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": "https://outlook.office365.com/IMAP.AccessAsUser.All offline_access",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data, timeout=30.0)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code, detail=f"Token exchange failed: {response.text}"
        )

    return response.json()


async def refresh_microsoft_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    tenant_id: str,
) -> dict[str, Any]:
    """Refresh Microsoft access token."""
    import httpx

    authority = f"https://login.microsoftonline.com/{tenant_id or 'common'}"
    token_url = f"{authority}/oauth2/v2.0/token"

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": "https://outlook.office365.com/IMAP.AccessAsUser.All offline_access",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data, timeout=30.0)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code, detail=f"Token refresh failed: {response.text}"
        )

    return response.json()


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/microsoft/init", response_model=OAuthInitResponse)
async def init_microsoft_oauth():
    """
    Initialize Microsoft OAuth2 flow.

    Returns the authorization URL to redirect the user to.
    """
    import uuid

    from api.routes.settings import load_settings

    settings = load_settings()
    email_config = settings.get("email", {})

    client_id = email_config.get("oauth_client_id")
    tenant_id = email_config.get("oauth_tenant_id", "common")
    redirect_uri = email_config.get(
        "oauth_redirect_uri", "http://localhost:8000/api/integrations/oauth/callback"
    )

    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="Microsoft OAuth not configured. Set oauth_client_id in email settings.",
        )

    state = str(uuid.uuid4())

    # Store state for verification
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "INSERT INTO oauth_states (state, provider) VALUES (?, ?)", (state, "microsoft")
        )
        conn.commit()

    auth_url = get_microsoft_auth_url(client_id, tenant_id, redirect_uri, state)

    log_integration_action(
        "oauth", "microsoft_init", "success", details={"redirect_uri": redirect_uri}
    )

    return OAuthInitResponse(auth_url=auth_url, state=state)


@router.get("/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
):
    """
    OAuth2 callback handler.

    Exchanges authorization code for tokens and stores them.
    """
    if error:
        log_integration_action("oauth", "callback", "failed", error=f"{error}: {error_description}")
        raise HTTPException(status_code=400, detail=f"OAuth error: {error_description}")

    # Verify state
    with get_connection() as conn:
        state_row = conn.execute(
            "SELECT provider FROM oauth_states WHERE state = ?", (state,)
        ).fetchone()
        if not state_row:
            raise HTTPException(status_code=400, detail="Invalid state parameter")

        provider = state_row["provider"]

        # Delete used state
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        conn.commit()

    from api.routes.settings import load_settings

    settings = load_settings()
    email_config = settings.get("email", {})

    if provider == "microsoft":
        client_id = email_config.get("oauth_client_id")
        client_secret = email_config.get("oauth_client_secret")
        tenant_id = email_config.get("oauth_tenant_id", "common")
        redirect_uri = email_config.get(
            "oauth_redirect_uri", "http://localhost:8000/api/integrations/oauth/callback"
        )

        # Exchange code for tokens
        tokens = await exchange_microsoft_code(
            code, client_id, client_secret, tenant_id, redirect_uri
        )

        # Calculate expiry
        expires_in = tokens.get("expires_in", 3600)
        expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat() + "Z"

        # Get user email from token
        email = email_config.get("email_address", "user@unknown.com")

        # Store tokens
        store_token(
            provider="microsoft",
            email=email,
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            expires_at=expires_at,
            scope=tokens.get("scope"),
        )

        log_integration_action("oauth", "microsoft_callback", "success", details={"email": email})

        return {"status": "ok", "message": "Microsoft OAuth completed successfully", "email": email}

    raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")


@router.get("/token/microsoft")
async def get_microsoft_token():
    """
    Get current Microsoft OAuth token (refreshes if expired).

    Returns the access token for IMAP XOAUTH2 authentication.
    """
    from api.routes.settings import load_settings

    settings = load_settings()
    email_config = settings.get("email", {})
    email = email_config.get("email_address")

    if not email:
        raise HTTPException(status_code=400, detail="Email address not configured")

    token_data = get_token("microsoft", email)

    if not token_data:
        raise HTTPException(
            status_code=401, detail="No OAuth token found. Please complete the OAuth flow first."
        )

    # Check if token needs refresh
    if is_token_expired(token_data.get("expires_at")) and token_data.get("refresh_token"):
        # Refresh the token
        client_id = email_config.get("oauth_client_id")
        client_secret = email_config.get("oauth_client_secret")
        tenant_id = email_config.get("oauth_tenant_id", "common")

        try:
            new_tokens = await refresh_microsoft_token(
                token_data["refresh_token"],
                client_id,
                client_secret,
                tenant_id,
            )

            expires_in = new_tokens.get("expires_in", 3600)
            expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat() + "Z"

            store_token(
                provider="microsoft",
                email=email,
                access_token=new_tokens["access_token"],
                refresh_token=new_tokens.get("refresh_token", token_data["refresh_token"]),
                expires_at=expires_at,
            )

            log_integration_action("oauth", "microsoft_refresh", "success")

            return {
                "access_token": new_tokens["access_token"],
                "expires_at": expires_at,
            }
        except Exception as e:
            log_integration_action("oauth", "microsoft_refresh", "failed", error=str(e))
            raise HTTPException(status_code=401, detail=f"Token refresh failed: {str(e)}")

    return {
        "access_token": token_data["access_token"],
        "expires_at": token_data.get("expires_at"),
    }


@router.delete("/token/microsoft")
async def revoke_microsoft_token():
    """Revoke and delete stored Microsoft OAuth token."""
    from api.routes.settings import load_settings

    settings = load_settings()
    email = settings.get("email", {}).get("email_address")

    if not email:
        raise HTTPException(status_code=400, detail="Email address not configured")

    init_oauth_table()

    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM oauth_tokens WHERE provider = ? AND email = ?", ("microsoft", email)
        )
        conn.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="No token found")

    log_integration_action("oauth", "microsoft_revoke", "success")

    return {"status": "ok", "message": "Token revoked"}
