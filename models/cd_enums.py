"""Central Dispatch API v2 enum types and reference data."""

from enum import Enum


class TrailerType(str, Enum):
    OPEN = "OPEN"
    ENCLOSED = "ENCLOSED"
    DRIVEAWAY = "DRIVEAWAY"


class VehicleType(str, Enum):
    AUTO = "AUTO"
    SUV = "SUV"
    PICKUP = "PICKUP"
    VAN = "VAN"
    MOTORCYCLE = "MOTORCYCLE"
    BOAT = "BOAT"
    RV = "RV"
    ATV = "ATV"
    HEAVY_EQUIPMENT = "HEAVY_EQUIPMENT"
    FREIGHT = "FREIGHT"
    OTHER = "OTHER"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CASH_CERTIFIED_FUNDS = "CASH_CERTIFIED_FUNDS"
    CHECK = "CHECK"
    COMPANY_CHECK = "COMPANY_CHECK"
    CASHIERS_CHECK = "CASHIERS_CHECK"
    COMCHECK = "COMCHECK"
    MONEY_ORDER = "MONEY_ORDER"
    WIRE_TRANSFER = "WIRE_TRANSFER"
    ACH = "ACH"


class PaymentLocation(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"
    COD = "COD"


class LocationType(str, Enum):
    """CD API V2 valid locationType values (verified against live API)."""
    AUCTION = "Auction"
    DEALERSHIP = "Dealership"
    WAREHOUSE = "Warehouse"
    RESIDENCE = "Residence"
    PORT = "Port"
    TERMINAL = "Terminal"
    OTHER = "Other"


class SLAType(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"
    GUARANTEED = "GUARANTEED"


# Luxury makes that trigger ENCLOSED trailer type
LUXURY_MAKES = frozenset(
    {
        "BMW",
        "MERCEDES",
        "MERCEDES-BENZ",
        "PORSCHE",
        "AUDI",
        "LEXUS",
        "TESLA",
        "BENTLEY",
        "ROLLS-ROYCE",
        "FERRARI",
        "LAMBORGHINI",
        "MASERATI",
        "ASTON MARTIN",
        "MCLAREN",
        "BUGATTI",
        "LOTUS",
    }
)

# Default marketplace configuration
DEFAULT_MARKETPLACE_ID = 10000
