"""
Single-user JWT authentication.

- Username/password validated against env vars (hashed)
- JWT token in httpOnly cookie (not localStorage — XSS safe)
- 24h expiry, re-login required after
- All /api/* routes protected except /api/auth/login, /health, /api/auth/me

ENV VARS:
  AUTH_USERNAME=sergii
  AUTH_PASSWORD_HASH=<bcrypt hash>  — generate with: python scripts/setup_auth.py
  JWT_SECRET=<random 64 char string>
  JWT_EXPIRE_HOURS=24
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
import bcrypt as _bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

def _get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        logger.warning("JWT_SECRET not set — using insecure default (dev only)")
        return "dev-insecure-secret-change-me-in-production"
    return secret


def _get_auth_username() -> str:
    return os.getenv("AUTH_USERNAME", "sergii")


def _get_password_hash() -> str:
    return os.getenv("AUTH_PASSWORD_HASH", "")


JWT_ALGORITHM = "HS256"
COOKIE_NAME = "access_token"

# Paths that skip auth (exact match)
PUBLIC_PATHS = {
    "/api/auth/login",
    "/api/auth/me",
    "/health",
    "/api/health",
    "/api/ready",
}


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(username: str) -> str:
    expire_hours = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
    expire = datetime.now(timezone.utc) + timedelta(hours=expire_hours)
    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict | None:
    """Decode and verify JWT. Returns payload dict or None if invalid/expired."""
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


def verify_password(plain_password: str) -> bool:
    """Verify password against stored bcrypt hash."""
    stored_hash = _get_password_hash()
    if not stored_hash:
        logger.error("AUTH_PASSWORD_HASH not configured — login disabled")
        return False
    try:
        return _bcrypt.checkpw(
            plain_password.encode("utf-8"),
            stored_hash.encode("utf-8"),
        )
    except Exception as e:
        logger.error("Password verification error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

async def auth_middleware(request: Request, call_next):
    """
    Middleware that protects /api/* routes with JWT cookie auth.
    Skips: static files, public paths, non-API paths.
    """
    path = request.url.path

    # Skip auth for non-API paths (frontend static files, root, etc.)
    if not path.startswith("/api/"):
        return await call_next(request)

    # Skip auth for public API paths
    if path in PUBLIC_PATHS:
        return await call_next(request)

    # Skip auth for Swagger docs
    if path in ("/api/docs", "/api/redoc", "/api/openapi.json"):
        return await call_next(request)

    # Skip auth entirely if AUTH_PASSWORD_HASH is not configured (dev mode)
    if not _get_password_hash():
        return await call_next(request)

    # Check JWT cookie
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
        )

    payload = verify_token(token)
    if not payload:
        return JSONResponse(
            status_code=401,
            content={"detail": "Token expired or invalid"},
        )

    # Token valid — attach username to request state
    request.state.username = payload.get("sub", "")
    return await call_next(request)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginRequest):
    """Authenticate and set httpOnly JWT cookie."""
    expected_username = _get_auth_username()

    if body.username != expected_username:
        logger.warning("Login attempt with wrong username: %s", body.username)
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials"},
        )

    if not verify_password(body.password):
        logger.warning("Login attempt with wrong password for user: %s", body.username)
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid credentials"},
        )

    # Create JWT token
    token = create_access_token(body.username)

    # Set httpOnly cookie
    expire_hours = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
    response = JSONResponse(content={
        "status": "ok",
        "username": body.username,
    })
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "true").lower() == "true",
        samesite="lax",
        max_age=expire_hours * 3600,
        path="/",
    )

    logger.info("User '%s' logged in successfully", body.username)
    return response


@router.post("/logout")
async def logout():
    """Clear the auth cookie."""
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return response


@router.get("/me")
async def get_current_user(request: Request):
    """Check if the current session is authenticated."""
    # If no password hash configured, treat as authenticated (dev mode)
    if not _get_password_hash():
        return {"authenticated": True, "username": _get_auth_username(), "dev_mode": True}

    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
        )

    payload = verify_token(token)
    if not payload:
        return JSONResponse(
            status_code=401,
            content={"detail": "Token expired or invalid"},
        )

    return {
        "authenticated": True,
        "username": payload.get("sub", ""),
    }
