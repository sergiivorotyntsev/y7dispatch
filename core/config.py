"""Centralized configuration management with validation."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing."""

    pass


def _mask_secret(value: str, visible_chars: int = 4) -> str:
    """Mask a secret value for logging, showing only first few chars."""
    if not value:
        return "<empty>"
    if len(value) <= visible_chars:
        return "*" * len(value)
    return value[:visible_chars] + "*" * (len(value) - visible_chars)


@dataclass
class EmailConfig:
    """Email/IMAP configuration."""

    provider: str = "imap"  # "imap" or "graph"
    imap_server: str = ""
    imap_port: int = 993
    address: str = ""
    password: str = ""
    folder: str = "INBOX"
    check_interval: int = 60
    from_filter: Optional[str] = None
    subject_filter: Optional[str] = None

    # OAuth2/Graph settings (for M365)
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None

    def validate(self) -> list[str]:
        """Validate email configuration, return list of errors."""
        errors = []

        if self.provider == "imap":
            if not self.imap_server:
                errors.append("EMAIL_IMAP_SERVER is required for IMAP provider")
            if not self.address:
                errors.append("EMAIL_ADDRESS is required")
            if not self.password and not (self.client_id and self.client_secret):
                errors.append("EMAIL_PASSWORD or OAuth2 credentials required")
        elif self.provider == "graph":
            if not self.tenant_id:
                errors.append("EMAIL_TENANT_ID is required for Graph provider")
            if not self.client_id:
                errors.append("EMAIL_CLIENT_ID is required for Graph provider")
            if not self.client_secret:
                errors.append("EMAIL_CLIENT_SECRET is required for Graph provider")
            if not self.address:
                errors.append("EMAIL_ADDRESS is required")
        else:
            errors.append(f"Unknown EMAIL_PROVIDER: {self.provider}")

        return errors

    def __repr__(self) -> str:
        return (
            f"EmailConfig(provider={self.provider}, server={self.imap_server}, "
            f"address={self.address}, password={_mask_secret(self.password)})"
        )


@dataclass
class ClickUpConfig:
    """ClickUp API configuration."""

    token: str = ""
    list_id: str = ""

    # Custom field IDs (optional, for stable field binding)
    field_id_vin: Optional[str] = None
    field_id_lot: Optional[str] = None
    field_id_gate_pass: Optional[str] = None
    field_id_auction: Optional[str] = None
    field_id_pickup_address: Optional[str] = None

    def validate(self) -> list[str]:
        """Validate ClickUp configuration, return list of errors."""
        errors = []
        if not self.token:
            errors.append("CLICKUP_TOKEN is required")
        if not self.list_id:
            errors.append("CLICKUP_LIST_ID is required")
        return errors

    def __repr__(self) -> str:
        return f"ClickUpConfig(token={_mask_secret(self.token)}, list_id={self.list_id})"


@dataclass
class CentralDispatchConfig:
    """Central Dispatch API configuration."""

    enabled: bool = False
    client_id: str = ""
    client_secret: str = ""
    marketplace_id: int = 10000

    def validate(self) -> list[str]:
        """Validate CD configuration, return list of errors."""
        errors = []
        if self.enabled:
            if not self.client_id:
                errors.append("CD_CLIENT_ID is required when CD is enabled")
            if not self.client_secret:
                errors.append("CD_CLIENT_SECRET is required when CD is enabled")
        return errors

    def __repr__(self) -> str:
        return (
            f"CentralDispatchConfig(enabled={self.enabled}, "
            f"client_id={_mask_secret(self.client_id)}, marketplace_id={self.marketplace_id})"
        )


@dataclass
class StorageConfig:
    """Storage/persistence configuration."""

    idempotency_db_path: str = "processed_emails.db"
    temp_dir: str = "/tmp/dispatch"

    def validate(self) -> list[str]:
        """Validate storage configuration, return list of errors."""
        errors = []
        # Ensure parent directory exists or can be created
        db_parent = Path(self.idempotency_db_path).parent
        if str(db_parent) != "." and not db_parent.exists():
            try:
                db_parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Cannot create idempotency DB directory: {e}")
        return errors


@dataclass
class SheetsConfig:
    """Google Sheets configuration."""

    enabled: bool = False
    spreadsheet_id: str = ""
    sheet_name: str = "Pickups"
    credentials_file: str = "credentials.json"
    token_file: str = "token.json"

    def validate(self) -> list[str]:
        """Validate Sheets configuration, return list of errors."""
        errors = []
        if self.enabled:
            if not self.spreadsheet_id:
                errors.append("SHEETS_SPREADSHEET_ID is required when Sheets is enabled")
            if not Path(self.credentials_file).exists():
                errors.append(f"Sheets credentials file not found: {self.credentials_file}")
        return errors

    def __repr__(self) -> str:
        return f"SheetsConfig(enabled={self.enabled}, spreadsheet_id={self.spreadsheet_id[:8]}...)"


@dataclass
class WarehouseConfig:
    """Warehouse routing configuration."""

    enabled: bool = True
    data_file: str = "warehouses.yaml"
    geocode_provider: str = "google"  # "google" or "nominatim"
    geocode_api_key: Optional[str] = None
    distance_mode: str = "driving"  # "driving" or "haversine"
    cache_db_path: str = "geocode_cache.db"

    def validate(self) -> list[str]:
        """Validate warehouse configuration, return list of errors."""
        errors = []
        if self.enabled:
            if self.geocode_provider == "google" and not self.geocode_api_key:
                # Warning but not error - will fall back to haversine
                pass
        return errors

    def __repr__(self) -> str:
        return f"WarehouseConfig(enabled={self.enabled}, provider={self.geocode_provider})"


@dataclass
class AppConfig:
    """Main application configuration."""

    email: EmailConfig = field(default_factory=EmailConfig)
    clickup: ClickUpConfig = field(default_factory=ClickUpConfig)
    central_dispatch: CentralDispatchConfig = field(default_factory=CentralDispatchConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    sheets: SheetsConfig = field(default_factory=SheetsConfig)
    warehouse: WarehouseConfig = field(default_factory=WarehouseConfig)

    # Runtime settings
    dry_run: bool = False
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "text"

    def validate(self, require_email: bool = True, require_clickup: bool = True) -> None:
        """Validate all configuration, raise ConfigurationError if invalid."""
        errors = []

        if require_email:
            errors.extend(self.email.validate())
        if require_clickup:
            errors.extend(self.clickup.validate())

        errors.extend(self.central_dispatch.validate())
        errors.extend(self.storage.validate())
        errors.extend(self.sheets.validate())
        errors.extend(self.warehouse.validate())

        if errors:
            raise ConfigurationError("Configuration errors:\n  - " + "\n  - ".join(errors))

    def __repr__(self) -> str:
        return (
            f"AppConfig(\n  email={self.email},\n  clickup={self.clickup},\n  "
            f"central_dispatch={self.central_dispatch},\n  storage={self.storage},\n  "
            f"sheets={self.sheets},\n  warehouse={self.warehouse},\n  "
            f"dry_run={self.dry_run}, log_level={self.log_level}\n)"
        )


def load_config_from_env() -> AppConfig:
    """Load configuration from environment variables."""

    # Load .env file if present (optional dependency)
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    config = AppConfig(
        email=EmailConfig(
            provider=os.getenv("EMAIL_PROVIDER", "imap"),
            imap_server=os.getenv("EMAIL_IMAP_SERVER", ""),
            imap_port=int(os.getenv("EMAIL_IMAP_PORT", "993")),
            address=os.getenv("EMAIL_ADDRESS", ""),
            password=os.getenv("EMAIL_PASSWORD", ""),
            folder=os.getenv("EMAIL_FOLDER", "INBOX"),
            check_interval=int(os.getenv("EMAIL_CHECK_INTERVAL", "60")),
            from_filter=os.getenv("EMAIL_FROM_FILTER"),
            subject_filter=os.getenv("EMAIL_SUBJECT_FILTER"),
            tenant_id=os.getenv("EMAIL_TENANT_ID"),
            client_id=os.getenv("EMAIL_CLIENT_ID"),
            client_secret=os.getenv("EMAIL_CLIENT_SECRET"),
        ),
        clickup=ClickUpConfig(
            token=os.getenv("CLICKUP_TOKEN", ""),
            list_id=os.getenv("CLICKUP_LIST_ID", ""),
            field_id_vin=os.getenv("CLICKUP_FIELD_ID_VIN"),
            field_id_lot=os.getenv("CLICKUP_FIELD_ID_LOT"),
            field_id_gate_pass=os.getenv("CLICKUP_FIELD_ID_GATE_PASS"),
            field_id_auction=os.getenv("CLICKUP_FIELD_ID_AUCTION"),
            field_id_pickup_address=os.getenv("CLICKUP_FIELD_ID_PICKUP_ADDRESS"),
        ),
        central_dispatch=CentralDispatchConfig(
            enabled=os.getenv("CD_ENABLED", "false").lower() in ("true", "1", "yes"),
            client_id=os.getenv("CD_CLIENT_ID", ""),
            client_secret=os.getenv("CD_CLIENT_SECRET", ""),
            marketplace_id=int(os.getenv("CD_MARKETPLACE_ID", "10000")),
        ),
        storage=StorageConfig(
            idempotency_db_path=os.getenv("IDEMPOTENCY_DB_PATH", "processed_emails.db"),
            temp_dir=os.getenv("TEMP_DIR", "/tmp/dispatch"),
        ),
        sheets=SheetsConfig(
            enabled=os.getenv("SHEETS_ENABLED", "false").lower() in ("true", "1", "yes"),
            spreadsheet_id=os.getenv("SHEETS_SPREADSHEET_ID", ""),
            sheet_name=os.getenv("SHEETS_SHEET_NAME", "Pickups"),
            credentials_file=os.getenv("SHEETS_CREDENTIALS_FILE", "credentials.json"),
            token_file=os.getenv("SHEETS_TOKEN_FILE", "token.json"),
        ),
        warehouse=WarehouseConfig(
            enabled=os.getenv("WAREHOUSE_ENABLED", "true").lower() in ("true", "1", "yes"),
            data_file=os.getenv("WAREHOUSE_DATA_FILE", "warehouses.yaml"),
            geocode_provider=os.getenv("GEOCODE_PROVIDER", "google"),
            geocode_api_key=os.getenv("GEOCODE_API_KEY"),
            distance_mode=os.getenv("DISTANCE_MODE", "driving"),
            cache_db_path=os.getenv("GEOCODE_CACHE_DB", "geocode_cache.db"),
        ),
        dry_run=os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_format=os.getenv("LOG_FORMAT", "text"),
    )

    return config


# Singleton config instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config_from_env()
    return _config


def reset_config() -> None:
    """Reset the global configuration (for testing)."""
    global _config
    _config = None


# Local settings path
LOCAL_SETTINGS_FILE = "config/local_settings.json"


def load_local_settings() -> dict:
    """Load local settings from JSON file.

    Priority:
    1. config/local_settings.json
    2. Environment variables (EXPORT_TARGETS, ENABLE_EMAIL_INGEST)
    3. Defaults

    Returns dict with:
    - export_targets: List[str] (e.g., ["sheets", "clickup", "cd"])
    - enable_email_ingest: bool
    - schema_version: int
    """
    import json

    defaults = {
        "export_targets": ["sheets"],  # Stage 1: only sheets
        "enable_email_ingest": False,
        "schema_version": 1,
    }

    # Try loading from file
    settings_path = Path(LOCAL_SETTINGS_FILE)
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                file_settings = json.load(f)
                defaults.update(file_settings)
        except Exception:
            pass  # Use defaults on error

    # Override with environment variables if present
    env_targets = os.getenv("EXPORT_TARGETS")
    if env_targets:
        defaults["export_targets"] = [t.strip() for t in env_targets.split(",")]

    env_ingest = os.getenv("ENABLE_EMAIL_INGEST")
    if env_ingest is not None:
        defaults["enable_email_ingest"] = env_ingest.lower() in ("true", "1", "yes")

    return defaults


def save_local_settings(settings: dict) -> None:
    """Save local settings to JSON file."""
    import json

    settings_path = Path(LOCAL_SETTINGS_FILE)
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)


def get_enabled_exporters() -> list:
    """Get list of enabled export targets based on config and local settings.

    Returns list of valid exporter names that are both:
    1. In export_targets setting
    2. Have valid credentials configured
    """
    settings = load_local_settings()
    config = get_config()

    enabled = []
    targets = settings.get("export_targets", [])

    if "sheets" in targets and config.sheets.enabled:
        enabled.append("sheets")

    if "clickup" in targets and config.clickup.token and config.clickup.list_id:
        enabled.append("clickup")

    if "cd" in targets and config.central_dispatch.enabled:
        enabled.append("cd")

    return enabled
