"""
Credential Store — Encrypted credential management in SQLite.

Stores integration credentials (Email, CD API, Sheets, Anthropic) in the
`integration_credentials` table with Fernet encryption. Reuses encryption
utilities from api/routes/integrations/utils.py.

Services:
    email_imap, email_forwarding, email_oauth, cd_api, sheets, anthropic
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

from api.database import get_connection
from api.routes.integrations.utils import decrypt_secret, encrypt_secret, mask_secret

logger = logging.getLogger(__name__)

# Fields that should be masked when returning to the frontend
SECRET_FIELDS = {
    "password",
    "api_key",
    "client_secret",
    "secret_key",
    "refresh_token",
    "access_token",
}

VALID_SERVICES = {
    "email_imap",
    "email_forwarding",
    "email_oauth",
    "cd_api",
    "sheets",
    "anthropic",
}


def init_credentials_table():
    """Create the integration_credentials table if it doesn't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS integration_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL UNIQUE,
                config_json_encrypted TEXT NOT NULL,
                enabled BOOLEAN DEFAULT 0,
                last_tested_at TEXT,
                last_test_status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_creds_service "
            "ON integration_credentials(service)"
        )
        conn.commit()


def save_credential(service: str, config: dict, enabled: bool = False) -> None:
    """Save or update a credential. Config dict is encrypted as JSON."""
    if service not in VALID_SERVICES:
        raise ValueError(f"Invalid service: {service}. Must be one of {VALID_SERVICES}")

    init_credentials_table()
    now = datetime.utcnow().isoformat() + "Z"
    encrypted = encrypt_secret(json.dumps(config))

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM integration_credentials WHERE service = ?",
            (service,),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE integration_credentials
                   SET config_json_encrypted = ?, enabled = ?, updated_at = ?
                   WHERE service = ?""",
                (encrypted, enabled, now, service),
            )
        else:
            conn.execute(
                """INSERT INTO integration_credentials
                   (service, config_json_encrypted, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (service, encrypted, enabled, now, now),
            )
        conn.commit()

    logger.info(f"Credential saved for service: {service}")


def get_credential(service: str) -> Optional[dict]:
    """Get a credential with secrets masked (for API responses)."""
    raw = get_credential_raw(service)
    if raw is None:
        return None

    # Mask secret fields in the config
    masked_config = {}
    for key, value in raw["config"].items():
        if key in SECRET_FIELDS and value:
            masked_config[key] = mask_secret(str(value))
        else:
            masked_config[key] = value

    return {
        "service": raw["service"],
        "config": masked_config,
        "enabled": raw["enabled"],
        "last_tested_at": raw["last_tested_at"],
        "last_test_status": raw["last_test_status"],
    }


def get_credential_raw(service: str) -> Optional[dict]:
    """Get a credential with decrypted secrets (for internal use only)."""
    init_credentials_table()

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM integration_credentials WHERE service = ?",
            (service,),
        ).fetchone()

    if not row:
        return None

    config = json.loads(decrypt_secret(row["config_json_encrypted"]))

    return {
        "service": row["service"],
        "config": config,
        "enabled": bool(row["enabled"]),
        "last_tested_at": row["last_tested_at"],
        "last_test_status": row["last_test_status"],
    }


def get_credential_for_service(service: str) -> Optional[dict]:
    """
    Get decrypted config dict for a service.

    Returns just the config dict (not the wrapper), or None if not found/disabled.
    Used by services like HaikuExtractor, cd_client, sheets_exporter.
    """
    raw = get_credential_raw(service)
    if raw is None:
        return None
    if not raw["enabled"]:
        return None
    return raw["config"]


def delete_credential(service: str) -> bool:
    """Delete a credential. Returns True if deleted, False if not found."""
    init_credentials_table()

    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM integration_credentials WHERE service = ?",
            (service,),
        )
        conn.commit()

    deleted = result.rowcount > 0
    if deleted:
        logger.info(f"Credential deleted for service: {service}")
    return deleted


def list_credentials() -> list[dict]:
    """List all credentials with secrets masked."""
    init_credentials_table()

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM integration_credentials ORDER BY service"
        ).fetchall()

    results = []
    for row in rows:
        config = json.loads(decrypt_secret(row["config_json_encrypted"]))
        masked_config = {}
        for key, value in config.items():
            if key in SECRET_FIELDS and value:
                masked_config[key] = mask_secret(str(value))
            else:
                masked_config[key] = value

        results.append({
            "service": row["service"],
            "config": masked_config,
            "enabled": bool(row["enabled"]),
            "last_tested_at": row["last_tested_at"],
            "last_test_status": row["last_test_status"],
        })

    return results


def update_test_status(service: str, status: str) -> None:
    """Update the last test status for a service."""
    init_credentials_table()
    now = datetime.utcnow().isoformat() + "Z"

    with get_connection() as conn:
        conn.execute(
            """UPDATE integration_credentials
               SET last_tested_at = ?, last_test_status = ?, updated_at = ?
               WHERE service = ?""",
            (now, status, now, service),
        )
        conn.commit()
