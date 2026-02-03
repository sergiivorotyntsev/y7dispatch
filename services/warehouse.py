"""Warehouse routing module - finds nearest warehouse by driving distance.

Features:
1. Load warehouse data from YAML/JSON
2. Geocode addresses (Google Maps or Nominatim fallback)
3. Calculate driving distance (Distance Matrix API or Haversine fallback)
4. Cache geocoding results in SQLite
"""

import hashlib
import json
import logging
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


@dataclass
class Warehouse:
    """Warehouse data."""

    id: str
    name: str
    state: str
    address: str
    city: str
    zip_code: str
    phone: Optional[str] = None
    email: Optional[str] = None
    hours: Optional[str] = None
    contact: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def full_address(self) -> str:
        """Full formatted address."""
        return f"{self.address}, {self.city}, {self.state} {self.zip_code}"


@dataclass
class RoutingResult:
    """Result of warehouse routing."""

    warehouse: Warehouse
    distance_miles: float
    distance_mode: str  # "driving" or "haversine"
    duration_minutes: Optional[float] = None


class GeocodeCache:
    """SQLite cache for geocoding results."""

    def __init__(self, db_path: str = "geocode_cache.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS geocode_cache (
                    address_hash TEXT PRIMARY KEY,
                    address TEXT,
                    latitude REAL,
                    longitude REAL,
                    provider TEXT,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS distance_cache (
                    route_hash TEXT PRIMARY KEY,
                    origin_hash TEXT,
                    dest_hash TEXT,
                    distance_meters REAL,
                    duration_seconds REAL,
                    mode TEXT,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @staticmethod
    def _hash_address(address: str) -> str:
        normalized = address.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    def get_geocode(self, address: str) -> Optional[tuple[float, float]]:
        """Get cached geocode result."""
        addr_hash = self._hash_address(address)
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT latitude, longitude FROM geocode_cache WHERE address_hash = ?", (addr_hash,)
            )
            row = cursor.fetchone()
            if row:
                return row["latitude"], row["longitude"]
        return None

    def set_geocode(self, address: str, lat: float, lng: float, provider: str):
        """Cache geocode result."""
        addr_hash = self._hash_address(address)
        with self._get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO geocode_cache
                   (address_hash, address, latitude, longitude, provider)
                   VALUES (?, ?, ?, ?, ?)""",
                (addr_hash, address, lat, lng, provider),
            )
            conn.commit()

    def get_distance(self, origin: str, dest: str) -> Optional[tuple[float, float, str]]:
        """Get cached distance result. Returns (distance_meters, duration_seconds, mode)."""
        origin_hash = self._hash_address(origin)
        dest_hash = self._hash_address(dest)
        route_hash = f"{origin_hash}:{dest_hash}"

        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT distance_meters, duration_seconds, mode FROM distance_cache WHERE route_hash = ?",
                (route_hash,),
            )
            row = cursor.fetchone()
            if row:
                return row["distance_meters"], row["duration_seconds"], row["mode"]
        return None

    def set_distance(
        self, origin: str, dest: str, distance_meters: float, duration_seconds: float, mode: str
    ):
        """Cache distance result."""
        origin_hash = self._hash_address(origin)
        dest_hash = self._hash_address(dest)
        route_hash = f"{origin_hash}:{dest_hash}"

        with self._get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO distance_cache
                   (route_hash, origin_hash, dest_hash, distance_meters, duration_seconds, mode)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (route_hash, origin_hash, dest_hash, distance_meters, duration_seconds, mode),
            )
            conn.commit()


class WarehouseRouter:
    """Routes pickups to nearest warehouse."""

    # Hardcoded warehouses from your Excel (can be overridden by data file)
    DEFAULT_WAREHOUSES = [
        {
            "id": "NJ",
            "name": "New Jersey Warehouse",
            "state": "NJ",
            "address": "123 Industrial Blvd",
            "city": "Newark",
            "zip_code": "07102",
        },
        {
            "id": "GA",
            "name": "Georgia Warehouse",
            "state": "GA",
            "address": "456 Logistics Way",
            "city": "Atlanta",
            "zip_code": "30301",
        },
        {
            "id": "CA",
            "name": "California Warehouse",
            "state": "CA",
            "address": "789 Transport Dr",
            "city": "Los Angeles",
            "zip_code": "90001",
        },
        {
            "id": "TX",
            "name": "Texas Warehouse",
            "state": "TX",
            "address": "321 Freight Ln",
            "city": "Houston",
            "zip_code": "77001",
        },
    ]

    def __init__(
        self,
        data_file: Optional[str] = None,
        geocode_provider: str = "google",
        geocode_api_key: Optional[str] = None,
        distance_mode: str = "driving",
        cache_db_path: str = "geocode_cache.db",
    ):
        self.geocode_provider = geocode_provider
        self.geocode_api_key = geocode_api_key
        self.distance_mode = distance_mode
        self.cache = GeocodeCache(cache_db_path)
        self.warehouses = self._load_warehouses(data_file)

    def _load_warehouses(self, data_file: Optional[str]) -> list[Warehouse]:
        """Load warehouses from file or use defaults."""
        warehouses = []

        if data_file and Path(data_file).exists():
            path = Path(data_file)
            try:
                if path.suffix == ".yaml" or path.suffix == ".yml":
                    import yaml

                    with open(path) as f:
                        data = yaml.safe_load(f)
                else:
                    with open(path) as f:
                        data = json.load(f)

                for item in data.get("warehouses", data):
                    warehouses.append(Warehouse(**item))

                logger.info(f"Loaded {len(warehouses)} warehouses from {data_file}")
                return warehouses
            except Exception as e:
                logger.warning(f"Failed to load warehouses from {data_file}: {e}")

        # Use defaults
        for item in self.DEFAULT_WAREHOUSES:
            warehouses.append(Warehouse(**item))
        logger.info(f"Using {len(warehouses)} default warehouses")
        return warehouses

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def geocode(self, address: str) -> Optional[tuple[float, float]]:
        """Geocode an address to lat/lng coordinates."""
        # Check cache
        cached = self.cache.get_geocode(address)
        if cached:
            logger.debug(f"Geocode cache hit for: {address[:50]}...")
            return cached

        coords = None

        if self.geocode_provider == "google" and self.geocode_api_key:
            coords = self._geocode_google(address)
        else:
            coords = self._geocode_nominatim(address)

        if coords:
            provider = self.geocode_provider if self.geocode_api_key else "nominatim"
            self.cache.set_geocode(address, coords[0], coords[1], provider)

        return coords

    def _geocode_google(self, address: str) -> Optional[tuple[float, float]]:
        """Geocode using Google Maps API."""
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"address": address, "key": self.geocode_api_key}

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        if data["status"] == "OK" and data["results"]:
            location = data["results"][0]["geometry"]["location"]
            return location["lat"], location["lng"]

        logger.warning(f"Google geocode failed for {address}: {data.get('status')}")
        return None

    def _geocode_nominatim(self, address: str) -> Optional[tuple[float, float]]:
        """Geocode using OpenStreetMap Nominatim (free, rate-limited)."""
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address, "format": "json", "limit": 1}
        headers = {"User-Agent": "VehicleTransportAutomation/1.0"}

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])

        logger.warning(f"Nominatim geocode failed for {address}")
        return None

    def get_distance(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        origin_addr: str,
        dest_addr: str,
    ) -> tuple[float, float, str]:
        """
        Get distance between two points.
        Returns (distance_miles, duration_minutes, mode).
        """
        # Check cache
        cached = self.cache.get_distance(origin_addr, dest_addr)
        if cached:
            distance_meters, duration_seconds, mode = cached
            return distance_meters / 1609.34, duration_seconds / 60, mode

        # Try driving distance
        if self.distance_mode == "driving" and self.geocode_api_key:
            result = self._get_driving_distance(origin, dest)
            if result:
                distance_meters, duration_seconds = result
                self.cache.set_distance(
                    origin_addr, dest_addr, distance_meters, duration_seconds, "driving"
                )
                return distance_meters / 1609.34, duration_seconds / 60, "driving"

        # Fallback to Haversine
        distance_miles = self._haversine_distance(origin, dest)
        # Estimate duration at 50 mph average
        duration_minutes = (distance_miles / 50) * 60
        self.cache.set_distance(
            origin_addr, dest_addr, distance_miles * 1609.34, duration_minutes * 60, "haversine"
        )
        return distance_miles, duration_minutes, "haversine"

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
    def _get_driving_distance(
        self, origin: tuple[float, float], dest: tuple[float, float]
    ) -> Optional[tuple[float, float]]:
        """Get driving distance using Google Distance Matrix API."""
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": f"{origin[0]},{origin[1]}",
            "destinations": f"{dest[0]},{dest[1]}",
            "mode": "driving",
            "key": self.geocode_api_key,
        }

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        if data["status"] == "OK":
            element = data["rows"][0]["elements"][0]
            if element["status"] == "OK":
                distance = element["distance"]["value"]  # meters
                duration = element["duration"]["value"]  # seconds
                return distance, duration

        return None

    @staticmethod
    def _haversine_distance(origin: tuple[float, float], dest: tuple[float, float]) -> float:
        """Calculate distance in miles using Haversine formula."""
        lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
        lat2, lon2 = math.radians(dest[0]), math.radians(dest[1])

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))

        # Earth radius in miles
        r = 3956
        return c * r

    def find_nearest_warehouse(self, pickup_address: str) -> Optional[RoutingResult]:
        """Find the nearest warehouse to a pickup address."""
        # Geocode pickup address
        pickup_coords = self.geocode(pickup_address)
        if not pickup_coords:
            logger.error(f"Could not geocode pickup address: {pickup_address}")
            return None

        best_result: Optional[RoutingResult] = None
        min_distance = float("inf")

        for warehouse in self.warehouses:
            # Get warehouse coordinates
            if warehouse.latitude and warehouse.longitude:
                wh_coords = (warehouse.latitude, warehouse.longitude)
            else:
                wh_coords = self.geocode(warehouse.full_address)
                if wh_coords:
                    warehouse.latitude, warehouse.longitude = wh_coords

            if not wh_coords:
                logger.warning(f"Could not geocode warehouse: {warehouse.name}")
                continue

            # Calculate distance
            distance, duration, mode = self.get_distance(
                pickup_coords, wh_coords, pickup_address, warehouse.full_address
            )

            if distance < min_distance:
                min_distance = distance
                best_result = RoutingResult(
                    warehouse=warehouse,
                    distance_miles=round(distance, 1),
                    distance_mode=mode,
                    duration_minutes=round(duration, 0) if duration else None,
                )

        if best_result:
            logger.info(
                f"Nearest warehouse: {best_result.warehouse.name} "
                f"({best_result.distance_miles} miles, {best_result.distance_mode})"
            )

        return best_result

    def get_all_distances(self, pickup_address: str) -> list[RoutingResult]:
        """Get distances to all warehouses, sorted by distance."""
        pickup_coords = self.geocode(pickup_address)
        if not pickup_coords:
            return []

        results = []

        for warehouse in self.warehouses:
            if warehouse.latitude and warehouse.longitude:
                wh_coords = (warehouse.latitude, warehouse.longitude)
            else:
                wh_coords = self.geocode(warehouse.full_address)
                if wh_coords:
                    warehouse.latitude, warehouse.longitude = wh_coords

            if not wh_coords:
                continue

            distance, duration, mode = self.get_distance(
                pickup_coords, wh_coords, pickup_address, warehouse.full_address
            )

            results.append(
                RoutingResult(
                    warehouse=warehouse,
                    distance_miles=round(distance, 1),
                    distance_mode=mode,
                    duration_minutes=round(duration, 0) if duration else None,
                )
            )

        return sorted(results, key=lambda r: r.distance_miles)


def create_router_from_config(config) -> WarehouseRouter:
    """Create WarehouseRouter from config."""
    return WarehouseRouter(
        data_file=config.warehouse.data_file,
        geocode_provider=config.warehouse.geocode_provider,
        geocode_api_key=config.warehouse.geocode_api_key,
        distance_mode=config.warehouse.distance_mode,
        cache_db_path=config.warehouse.cache_db_path,
    )
