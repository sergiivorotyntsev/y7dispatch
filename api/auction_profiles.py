"""
Auction Profiles - Auction-Specific Configuration

Provides JSON schema and storage for auction-specific field defaults,
patterns, and transformations. These are "Auction Constants" that apply
to all documents from a particular auction source.

Examples:
- Copart documents always have pickup_name = "Copart"
- IAA documents may have specific phone number formats
- Manheim documents have specific fee structures
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from api.database import get_connection


class FieldValueSource(str, Enum):
    """Source type for field values."""

    AUCTION_CONST = "auction_const"  # From auction profile
    WAREHOUSE_CONST = "warehouse_const"  # From warehouse override
    EXTRACTED = "extracted"  # Extracted from document
    USER_OVERRIDE = "user_override"  # Manual user correction
    DEFAULT = "default"  # Default value


@dataclass
class FieldDefault:
    """Default value for a field in an auction profile."""

    field_key: str
    value: Any
    is_required: bool = False
    apply_when: str = "always"  # always, if_empty, if_missing
    transform: Optional[str] = None  # Optional transformation rule

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FieldPattern:
    """Extraction pattern for a field in an auction profile."""

    field_key: str
    patterns: list[str]  # Regex patterns
    position_hint: str = "inline"  # inline, below, right
    max_lines: int = 3
    stop_patterns: list[str] = field(default_factory=list)  # Stop extraction at these

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FieldTransform:
    """Transformation rule for a field value."""

    field_key: str
    transform_type: str  # normalize, format, validate, map
    transform_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuctionProfile:
    """
    Complete profile for an auction source.

    Contains default values, extraction patterns, and transformations
    that apply to all documents from this auction.
    """

    id: Optional[int] = None
    auction_type_id: int = 0
    auction_code: str = ""  # COPART, IAA, MANHEIM
    name: str = ""
    description: str = ""

    # Field defaults (auction constants)
    field_defaults: dict[str, FieldDefault] = field(default_factory=dict)

    # Custom extraction patterns
    field_patterns: dict[str, FieldPattern] = field(default_factory=dict)

    # Field transformations
    field_transforms: dict[str, FieldTransform] = field(default_factory=dict)

    # Document classification patterns
    classification_patterns: list[str] = field(default_factory=list)

    # Metadata
    version: int = 1
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            "id": self.id,
            "auction_type_id": self.auction_type_id,
            "auction_code": self.auction_code,
            "name": self.name,
            "description": self.description,
            "field_defaults": {k: v.to_dict() for k, v in self.field_defaults.items()},
            "field_patterns": {k: v.to_dict() for k, v in self.field_patterns.items()},
            "field_transforms": {k: v.to_dict() for k, v in self.field_transforms.items()},
            "classification_patterns": self.classification_patterns,
            "version": self.version,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "AuctionProfile":
        """Create AuctionProfile from dictionary."""
        profile = AuctionProfile(
            id=data.get("id"),
            auction_type_id=data.get("auction_type_id", 0),
            auction_code=data.get("auction_code", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            classification_patterns=data.get("classification_patterns", []),
            version=data.get("version", 1),
            is_active=data.get("is_active", True),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

        # Parse field defaults
        for key, val in data.get("field_defaults", {}).items():
            if isinstance(val, dict):
                profile.field_defaults[key] = FieldDefault(**val)
            else:
                profile.field_defaults[key] = FieldDefault(field_key=key, value=val)

        # Parse field patterns
        for key, val in data.get("field_patterns", {}).items():
            if isinstance(val, dict):
                profile.field_patterns[key] = FieldPattern(**val)

        # Parse field transforms
        for key, val in data.get("field_transforms", {}).items():
            if isinstance(val, dict):
                profile.field_transforms[key] = FieldTransform(**val)

        return profile

    def get_default_value(self, field_key: str) -> Optional[Any]:
        """Get default value for a field."""
        field_def = self.field_defaults.get(field_key)
        if field_def:
            return field_def.value
        return None

    def should_apply_default(self, field_key: str, current_value: Any = None) -> bool:
        """Check if default should be applied based on apply_when rule."""
        field_def = self.field_defaults.get(field_key)
        if not field_def:
            return False

        if field_def.apply_when == "always":
            return True
        if field_def.apply_when == "if_empty" and not current_value:
            return True
        if field_def.apply_when == "if_missing" and current_value is None:
            return True

        return False


# =============================================================================
# DEFAULT AUCTION PROFILES
# =============================================================================


def get_default_copart_profile() -> AuctionProfile:
    """Get default Copart auction profile."""
    return AuctionProfile(
        auction_code="COPART",
        name="Copart",
        description="Default profile for Copart auction documents",
        field_defaults={
            "pickup_name": FieldDefault(
                field_key="pickup_name", value="Copart", apply_when="if_empty"
            ),
            "auction_source": FieldDefault(
                field_key="auction_source", value="COPART", apply_when="always"
            ),
        },
        field_patterns={
            "buyer_id": FieldPattern(
                field_key="buyer_id", patterns=[r"MEMBER\s*:\s*(\d{4,10})"], position_hint="inline"
            ),
            "vehicle_lot": FieldPattern(
                field_key="vehicle_lot",
                patterns=[r"LOT#?\s*:?\s*(\d{6,10})"],
                position_hint="inline",
            ),
        },
        classification_patterns=[
            "COPART",
            "SOLD THROUGH COPART",
            "Sales Receipt/Bill of Sale",
            "copart.com",
        ],
    )


def get_default_iaa_profile() -> AuctionProfile:
    """Get default IAA auction profile."""
    return AuctionProfile(
        auction_code="IAA",
        name="IAA (Insurance Auto Auctions)",
        description="Default profile for IAA auction documents",
        field_defaults={
            "pickup_name": FieldDefault(
                field_key="pickup_name", value="IAA", apply_when="if_empty"
            ),
            "auction_source": FieldDefault(
                field_key="auction_source", value="IAA", apply_when="always"
            ),
        },
        field_patterns={
            "buyer_id": FieldPattern(
                field_key="buyer_id", patterns=[r"BUYER\s*#?\s*:?\s*(\d+)"], position_hint="inline"
            ),
        },
        classification_patterns=[
            "IAA",
            "INSURANCE AUTO AUCTIONS",
            "iaai.com",
        ],
    )


def get_default_manheim_profile() -> AuctionProfile:
    """Get default Manheim auction profile."""
    return AuctionProfile(
        auction_code="MANHEIM",
        name="Manheim",
        description="Default profile for Manheim auction documents",
        field_defaults={
            "pickup_name": FieldDefault(
                field_key="pickup_name", value="Manheim", apply_when="if_empty"
            ),
            "auction_source": FieldDefault(
                field_key="auction_source", value="MANHEIM", apply_when="always"
            ),
        },
        field_patterns={
            "buyer_id": FieldPattern(
                field_key="buyer_id", patterns=[r"Buyer\s*#?\s*:?\s*(\d+)"], position_hint="inline"
            ),
        },
        classification_patterns=[
            "MANHEIM",
            "manheim.com",
            "BILL OF SALE",
            "YMMT",
        ],
    )


# =============================================================================
# DATABASE SCHEMA
# =============================================================================


def init_auction_profiles_schema():
    """Initialize auction profiles database schema."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auction_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                auction_type_id INTEGER NOT NULL,
                auction_code TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                profile_json TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (auction_type_id) REFERENCES auction_types(id),
                UNIQUE(auction_code)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_auction_profiles_code
            ON auction_profiles(auction_code)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_auction_profiles_active
            ON auction_profiles(is_active)
        """)
        conn.commit()


# =============================================================================
# REPOSITORY
# =============================================================================


class AuctionProfileRepository:
    """Repository for AuctionProfile operations."""

    @staticmethod
    def create(profile: AuctionProfile) -> int:
        """Create a new auction profile."""
        with get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO auction_profiles
                   (auction_type_id, auction_code, name, description,
                    profile_json, version, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    profile.auction_type_id,
                    profile.auction_code,
                    profile.name,
                    profile.description,
                    json.dumps(profile.to_dict()),
                    profile.version,
                    profile.is_active,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    @staticmethod
    def get_by_id(id: int) -> Optional[AuctionProfile]:
        """Get auction profile by ID."""
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM auction_profiles WHERE id = ?", (id,)).fetchone()
            if row:
                data = json.loads(row["profile_json"])
                data["id"] = row["id"]
                data["created_at"] = row["created_at"]
                data["updated_at"] = row["updated_at"]
                return AuctionProfile.from_dict(data)
            return None

    @staticmethod
    def get_by_code(auction_code: str) -> Optional[AuctionProfile]:
        """Get auction profile by auction code."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM auction_profiles WHERE auction_code = ? AND is_active = TRUE",
                (auction_code.upper(),),
            ).fetchone()
            if row:
                data = json.loads(row["profile_json"])
                data["id"] = row["id"]
                data["created_at"] = row["created_at"]
                data["updated_at"] = row["updated_at"]
                return AuctionProfile.from_dict(data)
            return None

    @staticmethod
    def list_all(include_inactive: bool = False) -> list[AuctionProfile]:
        """List all auction profiles."""
        sql = "SELECT * FROM auction_profiles"
        if not include_inactive:
            sql += " WHERE is_active = TRUE"
        sql += " ORDER BY auction_code"

        with get_connection() as conn:
            rows = conn.execute(sql).fetchall()
            profiles = []
            for row in rows:
                data = json.loads(row["profile_json"])
                data["id"] = row["id"]
                data["created_at"] = row["created_at"]
                data["updated_at"] = row["updated_at"]
                profiles.append(AuctionProfile.from_dict(data))
            return profiles

    @staticmethod
    def update(profile: AuctionProfile) -> bool:
        """Update an auction profile."""
        if not profile.id:
            return False

        profile.updated_at = datetime.utcnow().isoformat()
        profile.version += 1

        with get_connection() as conn:
            conn.execute(
                """UPDATE auction_profiles SET
                   name = ?, description = ?, profile_json = ?,
                   version = ?, is_active = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    profile.name,
                    profile.description,
                    json.dumps(profile.to_dict()),
                    profile.version,
                    profile.is_active,
                    profile.updated_at,
                    profile.id,
                ),
            )
            conn.commit()
            return True

    @staticmethod
    def delete(id: int) -> bool:
        """Soft delete (deactivate) auction profile."""
        with get_connection() as conn:
            conn.execute(
                "UPDATE auction_profiles SET is_active = FALSE, updated_at = ? WHERE id = ?",
                (datetime.utcnow().isoformat(), id),
            )
            conn.commit()
            return True

    @staticmethod
    def seed_defaults():
        """Seed default auction profiles if they don't exist."""
        defaults = [
            get_default_copart_profile(),
            get_default_iaa_profile(),
            get_default_manheim_profile(),
        ]

        # Get auction type IDs
        with get_connection() as conn:
            types = conn.execute(
                "SELECT id, code FROM auction_types WHERE is_base = TRUE"
            ).fetchall()
            type_map = {t["code"]: t["id"] for t in types}

        for profile in defaults:
            profile.auction_type_id = type_map.get(profile.auction_code, 0)

            existing = AuctionProfileRepository.get_by_code(profile.auction_code)
            if not existing:
                AuctionProfileRepository.create(profile)


# =============================================================================
# PROFILE SERVICE
# =============================================================================


class AuctionProfileService:
    """Service for working with auction profiles."""

    def __init__(self):
        self._profiles_cache: dict[str, AuctionProfile] = {}

    def get_profile(self, auction_code: str) -> Optional[AuctionProfile]:
        """Get auction profile by code (cached)."""
        code = auction_code.upper()
        if code not in self._profiles_cache:
            profile = AuctionProfileRepository.get_by_code(code)
            if profile:
                self._profiles_cache[code] = profile
        return self._profiles_cache.get(code)

    def apply_defaults(self, auction_code: str, extracted_fields: dict[str, Any]) -> dict[str, Any]:
        """
        Apply auction profile defaults to extracted fields.

        Returns new dict with defaults applied.
        """
        profile = self.get_profile(auction_code)
        if not profile:
            return extracted_fields

        result = dict(extracted_fields)

        for field_key, field_def in profile.field_defaults.items():
            current_value = result.get(field_key)
            if profile.should_apply_default(field_key, current_value):
                result[field_key] = field_def.value

        return result

    def get_field_patterns(self, auction_code: str, field_key: str) -> Optional[list[str]]:
        """Get custom extraction patterns for a field."""
        profile = self.get_profile(auction_code)
        if not profile:
            return None

        pattern = profile.field_patterns.get(field_key)
        if pattern:
            return pattern.patterns
        return None

    def clear_cache(self):
        """Clear the profile cache."""
        self._profiles_cache.clear()


# Singleton service instance
_profile_service = None


def get_profile_service() -> AuctionProfileService:
    """Get or create the profile service singleton."""
    global _profile_service
    if _profile_service is None:
        _profile_service = AuctionProfileService()
    return _profile_service
