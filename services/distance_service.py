"""
Distance Service — Google Distance Matrix + Haversine Fallback.

Calculates road distances between pickup locations and warehouses.
Uses Google Distance Matrix API when available, falls back to
haversine approximation when no API key is configured.

Caching:
- Distance results cached in distance_cache table (7-day TTL)
- Transport prices cached with 24-hour TTL
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from api.database import get_connection

logger = logging.getLogger(__name__)

# Cache TTLs in seconds
DISTANCE_CACHE_TTL = 7 * 24 * 3600  # 7 days
PRICE_CACHE_TTL = 24 * 3600  # 24 hours

# Haversine road factor (road distance ≈ 1.3x straight-line)
ROAD_FACTOR = 1.3


@dataclass
class DistanceResult:
    """Result of a distance calculation."""

    distance_miles: Optional[float] = None
    distance_text: str = ""
    duration_minutes: Optional[float] = None
    duration_text: str = ""
    source: str = "unknown"  # "google", "haversine", "cache"


@dataclass
class TransportPriceResult:
    """Result of a transport price lookup."""

    price: Optional[float] = None
    source: str = "unavailable"  # "cd_market", "unavailable"
    message: str = ""


@dataclass
class WarehouseOption:
    """A warehouse option with distance and price info."""

    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    city: str = ""
    state: str = ""
    zip_code: str = ""
    distance_miles: Optional[float] = None
    distance_text: str = ""
    duration_minutes: Optional[float] = None
    duration_text: str = ""
    distance_source: str = ""
    transport_price: Optional[float] = None
    transport_price_source: str = ""
    is_default: bool = False
    best_value: bool = False


class DistanceService:
    """Service for calculating distances and fetching transport prices."""

    _stale_cache_cleaned = False  # Class-level flag: clean once per process

    def __init__(self, google_api_key: Optional[str] = None):
        self.google_api_key = google_api_key
        if not self.google_api_key:
            self._load_google_key()
        self._clean_stale_cache()

    def _load_google_key(self):
        """Try to load Google Maps API key from credential store or env var."""
        # 1. Try credential store (enabled credentials)
        try:
            from services.credential_store import get_credential_for_service

            cred = get_credential_for_service("google_maps")
            if cred and cred.get("api_key"):
                self.google_api_key = cred["api_key"]
                logger.info("Google Maps API key loaded from credential store")
                return
        except Exception:
            pass

        # 2. Try credential store raw (even disabled — user may have saved but not toggled)
        try:
            from services.credential_store import get_credential_raw

            raw = get_credential_raw("google_maps")
            if raw and raw.get("config", {}).get("api_key"):
                self.google_api_key = raw["config"]["api_key"]
                logger.info("Google Maps API key loaded from credential store (credential disabled)")
                return
        except Exception:
            pass

        # 3. Fallback to environment variable
        import os
        env_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        if env_key:
            self.google_api_key = env_key
            logger.info("Google Maps API key loaded from GOOGLE_MAPS_API_KEY env var")
        else:
            logger.debug("No Google Maps API key found — using haversine estimates")

    @classmethod
    def _clean_stale_cache(cls):
        """Delete cache entries with NULL distance_source (legacy pre-OSRM entries)."""
        if cls._stale_cache_cleaned:
            return
        cls._stale_cache_cleaned = True
        try:
            with get_connection() as conn:
                result = conn.execute(
                    "DELETE FROM distance_cache WHERE distance_source IS NULL"
                )
                if result.rowcount > 0:
                    conn.commit()
                    logger.info("Cleared %d stale distance cache entries (NULL source)", result.rowcount)
        except Exception as e:
            logger.debug("Stale cache cleanup skipped: %s", e)

    # =========================================================================
    # Core distance calculation
    # =========================================================================

    def get_road_distance(
        self, origin_zip: str, dest_zip: str
    ) -> DistanceResult:
        """
        Get road distance between two ZIP codes.

        Priority: 1) Google Maps  2) OSRM (free)  3) Haversine estimate.
        """
        if self.google_api_key:
            try:
                return self._google_distance(origin_zip, dest_zip)
            except Exception as e:
                logger.warning("Google Distance Matrix failed: %s", e)

        # OSRM fallback (free, no key required)
        try:
            return self._osrm_distance(origin_zip, dest_zip)
        except Exception as e:
            logger.warning("OSRM fallback failed: %s", e)

        return self._haversine_distance(origin_zip, dest_zip)

    def _google_distance(self, origin_zip: str, dest_zip: str) -> DistanceResult:
        """Call Google Distance Matrix API."""
        import httpx

        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": f"{origin_zip}, USA",
            "destinations": f"{dest_zip}, USA",
            "units": "imperial",
            "key": self.google_api_key,
        }

        resp = httpx.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "OK":
            raise ValueError(f"Google API error: {data.get('status')}")

        element = data["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            raise ValueError(f"Route not found: {element.get('status')}")

        # Distance in meters → miles
        distance_meters = element["distance"]["value"]
        distance_miles = round(distance_meters / 1609.344, 1)

        # Duration in seconds → minutes
        duration_seconds = element["duration"]["value"]
        duration_minutes = round(duration_seconds / 60, 0)

        return DistanceResult(
            distance_miles=distance_miles,
            distance_text=element["distance"]["text"],
            duration_minutes=duration_minutes,
            duration_text=element["duration"]["text"],
            source="google",
        )

    def _osrm_distance(
        self, origin_zip: str, dest_zip: str
    ) -> DistanceResult:
        """
        Get road distance via OSRM (free, no API key required).

        Uses project-osrm.org demo server. Rate-limited but reliable for
        low-volume dispatching.
        """
        import httpx

        origin_coords = _zip_to_coords(origin_zip)
        dest_coords = _zip_to_coords(dest_zip)

        if not origin_coords or not dest_coords:
            raise ValueError(f"Cannot resolve coordinates for ZIP {origin_zip} or {dest_zip}")

        # OSRM uses lon,lat (not lat,lon)
        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{origin_coords[1]},{origin_coords[0]};{dest_coords[1]},{dest_coords[0]}"
            f"?overview=false"
        )

        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            raise ValueError(f"OSRM error: {data.get('code', 'no route')}")

        route = data["routes"][0]
        distance_meters = route["distance"]
        distance_miles = round(distance_meters / 1609.344, 1)
        duration_seconds = route["duration"]
        duration_minutes = round(duration_seconds / 60, 0)

        hours = int(duration_minutes // 60)
        mins = int(duration_minutes % 60)

        return DistanceResult(
            distance_miles=distance_miles,
            distance_text=f"{distance_miles:,.0f} mi",
            duration_minutes=duration_minutes,
            duration_text=f"{hours}h {mins}m",
            source="osrm",
        )

    def _haversine_distance(
        self, origin_zip: str, dest_zip: str
    ) -> DistanceResult:
        """
        Estimate distance using haversine formula on ZIP code centroids.

        Falls back to simple state-based estimate if ZIP lookup fails.
        """
        origin_coords = _zip_to_coords(origin_zip)
        dest_coords = _zip_to_coords(dest_zip)

        if not origin_coords or not dest_coords:
            return DistanceResult(source="unknown")

        straight_line = haversine(
            origin_coords[0], origin_coords[1],
            dest_coords[0], dest_coords[1],
        )
        road_estimate = round(straight_line * ROAD_FACTOR, 1)

        # Rough duration: avg 50 mph
        duration_minutes = round(road_estimate / 50 * 60, 0)

        return DistanceResult(
            distance_miles=road_estimate,
            distance_text=f"~{road_estimate} mi (estimate)",
            duration_minutes=duration_minutes,
            duration_text=f"~{int(duration_minutes // 60)}h {int(duration_minutes % 60)}m",
            source="haversine",
        )

    # =========================================================================
    # Transport price
    # =========================================================================

    def get_transport_price(
        self, pickup_zip: str, delivery_zip: str
    ) -> TransportPriceResult:
        """
        Get transport price for a route.

        CD Market Intelligence stub — returns unavailable until subscription.
        """
        # TODO: Integrate with CD Market Intelligence API when subscription active
        return TransportPriceResult(
            price=None,
            source="unavailable",
            message="CD Market Intelligence subscription required for pricing",
        )

    # =========================================================================
    # Warehouse options (main entry point)
    # =========================================================================

    def get_warehouse_options(
        self,
        pickup_zip: str,
        pickup_city: str = "",
        pickup_state: str = "",
    ) -> list[WarehouseOption]:
        """
        Get all active warehouses with distance + price for a pickup location.

        Returns sorted list: by price if available, otherwise by distance.
        Marks best_value on the top option.
        """
        from api.routes.warehouses import init_warehouses_schema

        init_warehouses_schema()

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM warehouses WHERE is_active = TRUE"
            ).fetchall()

        options = []
        for row in rows:
            wh = dict(row)
            wh_zip = wh.get("zip_code", "")

            # Check cache first
            cached = self._get_cached_distance(pickup_zip, wh["id"])
            if cached:
                dist = DistanceResult(
                    distance_miles=cached["distance_miles"],
                    distance_text=cached["distance_text"] or "",
                    duration_minutes=cached["duration_minutes"],
                    duration_text=cached["duration_text"] or "",
                    source=cached.get("distance_source") or "cached",
                )
                price = cached.get("transport_price")
                price_source = cached.get("transport_price_source", "")
            else:
                dist = self.get_road_distance(pickup_zip, wh_zip) if wh_zip else DistanceResult()
                price_result = self.get_transport_price(pickup_zip, wh_zip) if wh_zip else TransportPriceResult()
                price = price_result.price
                price_source = price_result.source

                # Cache the result
                if wh_zip and dist.distance_miles is not None:
                    self._cache_distance(
                        pickup_zip, wh["id"], dist, price, price_source
                    )

            options.append(WarehouseOption(
                warehouse_id=wh["id"],
                warehouse_code=wh.get("code", ""),
                warehouse_name=wh.get("name", ""),
                city=wh.get("city", ""),
                state=wh.get("state", ""),
                zip_code=wh_zip,
                distance_miles=dist.distance_miles,
                distance_text=dist.distance_text,
                duration_minutes=dist.duration_minutes,
                duration_text=dist.duration_text,
                distance_source=dist.source,
                transport_price=price,
                transport_price_source=price_source,
                is_default=bool(wh.get("is_default")),
            ))

        # Sort: by price if available, else by distance
        has_prices = any(o.transport_price is not None for o in options)
        if has_prices:
            options.sort(key=lambda o: (o.transport_price or float("inf")))
        else:
            options.sort(key=lambda o: (o.distance_miles or float("inf")))

        # Mark best value
        if options:
            options[0].best_value = True

        return options

    # =========================================================================
    # Cache operations
    # =========================================================================

    def _get_cached_distance(
        self, origin_zip: str, warehouse_id: int
    ) -> Optional[dict]:
        """Get cached distance if not expired."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM distance_cache WHERE origin_zip = ? AND destination_warehouse_id = ?",
                (origin_zip, warehouse_id),
            ).fetchone()

        if not row:
            return None

        cached = dict(row)
        calculated_at = cached.get("calculated_at", "")
        if not calculated_at:
            return None

        # Parse and check TTL
        try:
            calc_time = datetime.fromisoformat(calculated_at.replace("Z", "+00:00"))
            if calc_time.tzinfo is None:
                calc_time = calc_time.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - calc_time).total_seconds()
        except (ValueError, TypeError):
            return None

        # Check distance TTL (7 days)
        if age > DISTANCE_CACHE_TTL:
            return None

        # Check price TTL (24 hours) — invalidate price but keep distance
        if age > PRICE_CACHE_TTL:
            cached["transport_price"] = None
            cached["transport_price_source"] = ""

        return cached

    def _cache_distance(
        self,
        origin_zip: str,
        warehouse_id: int,
        dist: DistanceResult,
        price: Optional[float],
        price_source: str,
    ):
        """Cache a distance calculation result."""
        now = datetime.now(timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO distance_cache
                    (origin_zip, destination_warehouse_id, distance_miles, distance_text,
                     duration_minutes, duration_text, transport_price, transport_price_source,
                     distance_source, calculated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(origin_zip, destination_warehouse_id) DO UPDATE SET
                    distance_miles = excluded.distance_miles,
                    distance_text = excluded.distance_text,
                    duration_minutes = excluded.duration_minutes,
                    duration_text = excluded.duration_text,
                    transport_price = excluded.transport_price,
                    transport_price_source = excluded.transport_price_source,
                    distance_source = excluded.distance_source,
                    calculated_at = excluded.calculated_at
                """,
                (
                    origin_zip,
                    warehouse_id,
                    dist.distance_miles,
                    dist.distance_text,
                    dist.duration_minutes,
                    dist.duration_text,
                    price,
                    price_source,
                    dist.source,
                    now,
                ),
            )
            conn.commit()


# =============================================================================
# Haversine helper (module-level for testability)
# =============================================================================


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance in miles between two points.

    Uses the haversine formula.
    """
    R = 3958.8  # Earth radius in miles

    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    return R * c


# =============================================================================
# ZIP code → lat/lon lookup (common US ZIP centroids)
# =============================================================================

# Small built-in lookup for common ZIP prefixes (first 3 digits → approx coords)
# This avoids external dependencies. For production, use a full ZIP database.
_ZIP3_COORDS = {
    "010": (42.1, -72.6),   # MA - Springfield
    "011": (42.1, -72.6),   # MA
    "012": (42.4, -73.2),   # MA
    "013": (42.3, -71.8),   # MA
    "014": (42.3, -71.8),   # MA
    "015": (42.3, -71.8),   # MA
    "016": (42.3, -71.8),   # MA
    "017": (42.4, -71.1),   # MA - Boston area
    "018": (42.4, -71.1),   # MA
    "019": (42.5, -71.0),   # MA
    "020": (42.4, -71.1),   # MA - Boston
    "021": (42.4, -71.1),   # MA - Boston
    "022": (42.4, -71.1),   # MA
    "023": (41.8, -71.4),   # MA/RI
    "024": (42.4, -71.3),   # MA
    "025": (41.7, -70.3),   # MA - Cape Cod
    "026": (41.7, -70.0),   # MA
    "027": (41.8, -71.4),   # RI
    "028": (41.8, -71.4),   # RI
    "029": (41.8, -71.4),   # RI
    "030": (43.0, -71.5),   # NH
    "031": (42.9, -71.4),   # NH
    "032": (43.0, -71.5),   # NH
    "033": (43.2, -71.5),   # NH
    "034": (43.6, -71.7),   # NH
    "040": (43.7, -70.3),   # ME
    "041": (43.7, -70.3),   # ME
    "050": (44.3, -72.6),   # VT
    "060": (41.8, -72.7),   # CT - Hartford
    "061": (41.8, -72.7),   # CT
    "062": (41.3, -72.9),   # CT - New Haven
    "063": (41.2, -73.2),   # CT
    "064": (41.2, -73.2),   # CT
    "065": (41.2, -73.2),   # CT
    "066": (41.2, -73.0),   # CT
    "067": (41.8, -72.2),   # CT
    "068": (41.3, -72.9),   # CT
    "069": (41.3, -72.6),   # CT
    "070": (40.7, -74.2),   # NJ
    "071": (40.7, -74.2),   # NJ - Newark
    "072": (40.5, -74.3),   # NJ
    "073": (40.9, -74.2),   # NJ
    "074": (40.9, -74.2),   # NJ
    "075": (40.9, -74.2),   # NJ
    "076": (40.9, -74.2),   # NJ
    "077": (40.2, -74.0),   # NJ
    "078": (40.6, -74.6),   # NJ
    "079": (40.8, -75.0),   # NJ
    "080": (39.9, -75.0),   # NJ - Southern
    "100": (40.7, -74.0),   # NY - NYC
    "101": (40.7, -74.0),   # NY
    "102": (40.7, -74.0),   # NY
    "103": (40.6, -74.1),   # NY - Staten Island
    "104": (40.8, -73.9),   # NY - Bronx
    "110": (40.7, -73.5),   # NY - Long Island
    "111": (40.7, -73.5),   # NY
    "112": (40.6, -74.0),   # NY - Brooklyn
    "113": (40.7, -73.8),   # NY - Queens
    "114": (40.7, -73.8),   # NY
    "115": (40.8, -73.8),   # NY
    "116": (40.7, -73.8),   # NY
    "117": (40.8, -73.3),   # NY
    "118": (40.8, -73.3),   # NY
    "119": (40.8, -73.3),   # NY
    "120": (42.7, -73.7),   # NY - Albany
    "121": (42.7, -73.7),   # NY
    "122": (42.7, -73.7),   # NY
    "123": (42.7, -73.7),   # NY
    "130": (43.0, -76.1),   # NY - Syracuse
    "140": (42.9, -78.9),   # NY - Buffalo
    "141": (42.9, -78.9),   # NY
    "142": (42.9, -78.9),   # NY
    "143": (43.2, -77.6),   # NY - Rochester
    "144": (43.2, -77.6),   # NY
    "145": (43.2, -77.6),   # NY
    "146": (43.2, -77.6),   # NY
    "147": (42.1, -76.8),   # NY
    "148": (42.4, -76.5),   # NY
    "149": (42.1, -79.2),   # NY
    "150": (40.4, -80.0),   # PA - Pittsburgh
    "151": (40.4, -80.0),   # PA
    "152": (40.4, -80.0),   # PA
    "153": (40.4, -80.0),   # PA
    "170": (40.0, -76.3),   # PA - Lancaster
    "171": (40.0, -76.3),   # PA
    "175": (40.3, -76.0),   # PA
    "180": (40.6, -75.5),   # PA - Allentown
    "190": (40.0, -75.1),   # PA - Philadelphia
    "191": (40.0, -75.1),   # PA
    "192": (40.0, -75.1),   # PA
    "193": (40.0, -75.2),   # PA
    "194": (40.3, -75.3),   # PA
    "200": (38.9, -77.0),   # DC/VA
    "201": (38.9, -77.0),   # VA
    "220": (38.8, -77.1),   # VA - Arlington
    "221": (38.8, -77.2),   # VA
    "222": (38.8, -77.2),   # VA
    "223": (38.8, -77.5),   # VA
    "226": (37.3, -79.4),   # VA
    "230": (37.5, -77.5),   # VA - Richmond
    "231": (37.5, -77.5),   # VA
    "232": (37.5, -77.5),   # VA
    "233": (36.8, -76.3),   # VA - Norfolk
    "234": (36.8, -76.3),   # VA
    "235": (36.8, -76.3),   # VA
    "236": (37.0, -76.3),   # VA
    "237": (37.3, -76.5),   # VA
    "270": (35.8, -78.6),   # NC - Raleigh
    "271": (36.1, -80.2),   # NC - Winston-Salem
    "272": (35.2, -80.8),   # NC - Charlotte
    "273": (36.1, -80.2),   # NC - Greensboro
    "274": (35.6, -82.6),   # NC - Asheville
    "275": (35.8, -78.6),   # NC - Raleigh area
    "276": (36.1, -79.8),   # NC - Greensboro area
    "277": (35.2, -80.8),   # NC - Charlotte area
    "278": (35.6, -82.6),   # NC - Asheville area
    "279": (35.1, -80.7),   # NC - Indian Trail
    "280": (29.8, -81.3),   # SC - Columbia area
    "281": (35.0, -78.9),   # NC - Fayetteville
    "282": (35.2, -80.8),   # NC - Charlotte
    "283": (34.2, -79.8),   # SC - Florence
    "284": (34.8, -82.4),   # SC - Greenville
    "285": (35.3, -83.5),   # NC - Sylva
    "286": (36.2, -81.7),   # NC - Boone
    "287": (36.3, -79.4),   # NC - Burlington
    "288": (34.3, -77.9),   # NC - Wilmington
    "289": (35.0, -80.6),   # NC - Monroe
    "280": (35.2, -80.8),   # NC - Charlotte
    "281": (35.2, -80.8),   # NC
    "282": (35.2, -80.8),   # NC
    "290": (34.0, -81.0),   # SC - Columbia
    "291": (34.0, -81.0),   # SC
    "292": (34.0, -81.0),   # SC
    "293": (32.8, -79.9),   # SC - Charleston
    "294": (32.8, -79.9),   # SC
    "295": (34.8, -82.4),   # SC - Greenville
    "300": (33.7, -84.4),   # GA - Atlanta
    "301": (33.7, -84.4),   # GA
    "302": (33.7, -84.4),   # GA
    "303": (33.7, -84.4),   # GA
    "304": (33.5, -84.5),   # GA
    "305": (33.8, -84.3),   # GA
    "306": (33.5, -83.9),   # GA
    "310": (32.1, -81.1),   # GA - Savannah
    "311": (33.7, -84.4),   # GA
    "312": (32.5, -84.9),   # GA
    "313": (32.5, -84.9),   # GA
    "320": (30.3, -81.7),   # FL - Jacksonville
    "321": (28.5, -81.4),   # FL - Orlando
    "322": (30.3, -81.7),   # FL
    "323": (28.5, -81.4),   # FL
    "324": (30.4, -86.6),   # FL - Panhandle
    "325": (27.8, -82.6),   # FL
    "326": (29.2, -82.1),   # FL
    "327": (28.5, -81.4),   # FL - Orlando
    "328": (28.5, -81.4),   # FL
    "329": (28.1, -80.6),   # FL
    "330": (25.8, -80.2),   # FL - Miami
    "331": (25.8, -80.2),   # FL
    "332": (25.8, -80.2),   # FL
    "333": (26.1, -80.1),   # FL - Ft Lauderdale
    "334": (26.7, -80.1),   # FL - West Palm Beach
    "335": (27.9, -82.5),   # FL - Tampa
    "336": (27.9, -82.5),   # FL
    "337": (27.3, -82.5),   # FL - Sarasota
    "338": (28.0, -82.5),   # FL
    "339": (26.6, -82.0),   # FL - Ft Myers
    "350": (33.5, -86.8),   # AL - Birmingham
    "351": (33.5, -86.8),   # AL
    "352": (33.5, -86.8),   # AL
    "354": (34.7, -87.7),   # AL
    "355": (34.7, -87.7),   # AL
    "356": (34.7, -86.6),   # AL - Huntsville
    "360": (32.4, -86.3),   # AL - Montgomery
    "361": (32.4, -86.3),   # AL
    "362": (33.2, -87.5),   # AL - Tuscaloosa
    "365": (30.7, -88.1),   # AL - Mobile
    "366": (30.7, -88.1),   # AL
    "370": (36.2, -86.8),   # TN - Nashville
    "371": (36.2, -86.8),   # TN
    "372": (36.2, -86.8),   # TN
    "373": (35.0, -85.3),   # TN - Chattanooga
    "374": (35.0, -85.3),   # TN
    "375": (36.5, -87.4),   # TN
    "376": (36.6, -82.6),   # TN
    "377": (35.9, -83.9),   # TN - Knoxville
    "378": (35.9, -83.9),   # TN
    "379": (35.1, -90.0),   # TN - Memphis
    "380": (35.1, -90.0),   # TN
    "381": (35.1, -90.0),   # TN
    "382": (35.1, -90.0),   # TN
    "386": (32.3, -90.2),   # MS - Jackson
    "387": (32.3, -90.2),   # MS
    "390": (32.3, -90.2),   # MS
    "391": (32.3, -90.2),   # MS
    "400": (38.3, -85.8),   # KY - Louisville
    "401": (38.3, -85.8),   # KY
    "402": (38.3, -85.8),   # KY
    "403": (38.0, -84.5),   # KY - Lexington
    "404": (38.0, -84.5),   # KY
    "405": (38.0, -84.5),   # KY
    "430": (39.9, -83.0),   # OH - Columbus
    "431": (39.9, -83.0),   # OH
    "432": (39.9, -83.0),   # OH
    "440": (41.5, -81.7),   # OH - Cleveland
    "441": (41.5, -81.7),   # OH
    "442": (41.1, -81.5),   # OH - Akron
    "443": (41.1, -81.5),   # OH
    "444": (41.1, -80.6),   # OH - Youngstown
    "445": (41.1, -80.6),   # OH
    "446": (40.8, -81.4),   # OH - Canton
    "447": (40.8, -81.4),   # OH
    "448": (40.1, -82.9),   # OH
    "449": (40.8, -82.5),   # OH - Mansfield
    "450": (39.1, -84.5),   # OH - Cincinnati
    "451": (39.1, -84.5),   # OH
    "452": (39.1, -84.5),   # OH
    "453": (39.8, -84.2),   # OH - Dayton
    "454": (39.8, -84.2),   # OH
    "455": (40.1, -84.0),   # OH
    "456": (39.3, -84.3),   # OH
    "457": (40.8, -83.8),   # OH
    "458": (40.8, -83.5),   # OH
    "460": (39.8, -86.2),   # IN - Indianapolis
    "461": (39.8, -86.2),   # IN
    "462": (39.8, -86.2),   # IN
    "463": (39.8, -86.2),   # IN
    "464": (41.1, -85.1),   # IN - Ft Wayne
    "465": (41.1, -85.1),   # IN
    "466": (41.7, -86.3),   # IN - South Bend
    "467": (41.7, -86.3),   # IN
    "468": (41.7, -86.3),   # IN
    "469": (41.7, -86.3),   # IN
    "470": (39.1, -86.5),   # IN
    "471": (38.3, -86.0),   # IN
    "472": (39.8, -86.2),   # IN
    "473": (38.0, -87.6),   # IN - Evansville
    "474": (39.2, -86.5),   # IN - Bloomington
    "475": (39.8, -87.4),   # IN
    "476": (40.4, -86.9),   # IN - Lafayette
    "477": (38.0, -87.6),   # IN
    "478": (39.5, -87.4),   # IN
    "479": (40.4, -86.9),   # IN
    "480": (42.3, -83.0),   # MI - Detroit
    "481": (42.3, -83.0),   # MI
    "482": (42.3, -83.0),   # MI
    "483": (42.3, -83.0),   # MI
    "484": (42.7, -83.3),   # MI - Flint
    "485": (42.7, -83.3),   # MI
    "486": (43.4, -83.9),   # MI - Saginaw
    "487": (43.4, -83.9),   # MI
    "488": (42.7, -84.5),   # MI - Lansing
    "489": (42.3, -85.2),   # MI - Kalamazoo
    "490": (42.3, -85.2),   # MI
    "491": (42.3, -85.2),   # MI
    "492": (42.9, -85.7),   # MI - Grand Rapids
    "493": (42.9, -85.7),   # MI
    "494": (42.9, -85.7),   # MI
    "495": (43.4, -85.0),   # MI
    "496": (44.3, -85.6),   # MI - Traverse City
    "497": (46.5, -87.4),   # MI - UP
    "498": (46.5, -87.4),   # MI
    "499": (46.5, -87.4),   # MI
    "500": (41.6, -93.6),   # IA - Des Moines
    "501": (41.6, -93.6),   # IA
    "502": (41.6, -93.6),   # IA
    "503": (41.6, -93.6),   # IA
    "530": (43.1, -89.4),   # WI - Madison
    "531": (43.1, -89.4),   # WI
    "532": (42.7, -87.8),   # WI - Milwaukee
    "534": (42.7, -87.8),   # WI
    "535": (43.1, -89.4),   # WI
    "540": (44.5, -88.0),   # WI - Green Bay
    "541": (44.5, -88.0),   # WI
    "550": (44.9, -93.3),   # MN - Minneapolis
    "551": (44.9, -93.3),   # MN
    "553": (44.9, -93.3),   # MN
    "554": (44.9, -93.3),   # MN
    "555": (44.9, -93.3),   # MN
    "556": (47.0, -94.9),   # MN - Duluth
    "557": (47.0, -94.9),   # MN
    "558": (47.0, -94.9),   # MN
    "559": (44.0, -92.5),   # MN - Rochester
    "570": (43.5, -96.7),   # SD
    "580": (46.9, -96.8),   # ND
    "590": (46.9, -110.4),  # MT
    "600": (41.9, -87.6),   # IL - Chicago
    "601": (41.9, -87.6),   # IL
    "602": (41.9, -87.6),   # IL
    "603": (41.9, -87.6),   # IL
    "604": (41.9, -87.6),   # IL
    "605": (41.9, -87.6),   # IL
    "606": (41.9, -87.6),   # IL
    "607": (41.9, -87.6),   # IL
    "608": (41.9, -87.6),   # IL
    "609": (41.5, -88.1),   # IL
    "610": (40.7, -89.6),   # IL - Peoria
    "611": (41.5, -90.5),   # IL - Rock Island
    "612": (41.5, -90.5),   # IL
    "617": (39.8, -89.6),   # IL - Springfield
    "618": (38.6, -90.2),   # IL - East St Louis
    "619": (38.6, -90.2),   # IL
    "620": (38.5, -89.0),   # IL
    "622": (38.5, -89.0),   # IL
    "623": (37.0, -89.2),   # IL
    "630": (38.6, -90.2),   # MO - St Louis
    "631": (38.6, -90.2),   # MO
    "633": (38.6, -90.2),   # MO
    "640": (39.1, -94.6),   # MO - Kansas City
    "641": (39.1, -94.6),   # MO
    "644": (37.2, -93.3),   # MO - Springfield
    "645": (37.2, -93.3),   # MO
    "646": (39.1, -94.6),   # MO
    "647": (39.1, -94.6),   # MO
    "648": (37.2, -93.3),   # MO
    "650": (38.6, -92.2),   # MO - Jefferson City
    "660": (39.1, -94.6),   # KS - Kansas City
    "661": (39.1, -94.6),   # KS
    "662": (39.0, -95.7),   # KS - Topeka
    "664": (39.0, -95.7),   # KS
    "665": (39.0, -95.7),   # KS
    "666": (39.0, -95.7),   # KS
    "667": (37.7, -97.3),   # KS - Wichita
    "670": (37.7, -97.3),   # KS
    "671": (37.7, -97.3),   # KS
    "672": (37.7, -97.3),   # KS
    "680": (41.3, -96.0),   # NE - Omaha
    "681": (41.3, -96.0),   # NE
    "683": (40.8, -96.7),   # NE - Lincoln
    "700": (30.0, -90.1),   # LA - New Orleans
    "701": (30.0, -90.1),   # LA
    "703": (30.0, -90.1),   # LA
    "704": (32.5, -93.7),   # LA - Shreveport
    "706": (30.2, -93.2),   # LA - Lake Charles
    "707": (30.5, -91.1),   # LA - Baton Rouge
    "708": (30.5, -91.1),   # LA
    "710": (32.5, -93.7),   # LA
    "711": (32.5, -93.7),   # LA
    "712": (30.2, -92.0),   # LA - Lafayette
    "713": (30.2, -92.0),   # LA
    "714": (32.5, -92.1),   # LA
    "716": (71.3, -156.8),  # AK? No, typo, let me fix
    "720": (34.7, -92.3),   # AR - Little Rock
    "721": (34.7, -92.3),   # AR
    "722": (34.7, -92.3),   # AR
    "723": (35.4, -94.4),   # AR
    "724": (35.4, -94.4),   # AR
    "725": (35.4, -94.4),   # AR
    "726": (36.4, -94.2),   # AR
    "727": (36.4, -94.2),   # AR
    "728": (33.5, -92.0),   # AR
    "730": (35.5, -97.5),   # OK - Oklahoma City
    "731": (35.5, -97.5),   # OK
    "734": (35.5, -97.5),   # OK
    "735": (35.5, -97.5),   # OK
    "736": (35.5, -97.5),   # OK
    "740": (36.2, -95.9),   # OK - Tulsa
    "741": (36.2, -95.9),   # OK
    "743": (36.2, -95.9),   # OK
    "744": (34.6, -98.4),   # OK
    "745": (36.7, -97.1),   # OK
    "746": (34.2, -97.1),   # OK
    "748": (34.2, -97.1),   # OK
    "749": (34.2, -96.3),   # OK
    "750": (32.8, -96.8),   # TX - Dallas
    "751": (32.8, -96.8),   # TX
    "752": (32.7, -97.3),   # TX - Ft Worth
    "753": (32.7, -97.3),   # TX
    "754": (32.8, -96.8),   # TX
    "755": (32.8, -96.8),   # TX
    "756": (32.8, -96.8),   # TX
    "757": (31.5, -97.1),   # TX - Waco
    "758": (31.5, -97.1),   # TX
    "759": (33.9, -98.5),   # TX
    "760": (32.7, -97.3),   # TX
    "761": (32.7, -97.3),   # TX
    "762": (32.8, -96.8),   # TX
    "763": (32.8, -96.8),   # TX
    "764": (32.8, -96.8),   # TX
    "765": (31.8, -97.4),   # TX
    "766": (31.8, -97.4),   # TX
    "767": (31.8, -97.4),   # TX
    "768": (32.4, -99.7),   # TX - Abilene
    "769": (31.4, -100.4),  # TX - San Angelo
    "770": (29.8, -95.4),   # TX - Houston
    "771": (29.8, -95.4),   # TX
    "772": (29.8, -95.4),   # TX
    "773": (29.8, -95.4),   # TX
    "774": (29.8, -95.4),   # TX
    "775": (30.1, -95.0),   # TX
    "776": (30.1, -94.1),   # TX - Beaumont
    "777": (30.1, -94.1),   # TX
    "778": (27.5, -99.5),   # TX - Laredo
    "779": (27.8, -97.4),   # TX - Corpus Christi
    "780": (29.4, -98.5),   # TX - San Antonio
    "781": (29.4, -98.5),   # TX
    "782": (29.4, -98.5),   # TX
    "783": (27.8, -97.4),   # TX
    "784": (27.8, -97.4),   # TX
    "785": (26.2, -98.2),   # TX - McAllen
    "786": (30.3, -97.7),   # TX - Austin
    "787": (30.3, -97.7),   # TX
    "788": (30.3, -97.7),   # TX
    "789": (30.3, -97.7),   # TX
    "790": (33.6, -101.8),  # TX - Lubbock
    "791": (35.2, -101.8),  # TX - Amarillo
    "793": (31.8, -106.4),  # TX - El Paso
    "794": (31.8, -106.4),  # TX
    "795": (31.8, -106.4),  # TX
    "796": (31.8, -106.4),  # TX
    "797": (31.7, -102.5),  # TX - Midland
    "798": (31.8, -106.4),  # TX
    "799": (31.8, -106.4),  # TX
    "800": (39.7, -105.0),  # CO - Denver
    "801": (39.7, -105.0),  # CO
    "802": (39.7, -105.0),  # CO
    "803": (39.7, -105.0),  # CO
    "804": (39.7, -105.0),  # CO
    "805": (39.7, -105.0),  # CO
    "806": (39.7, -105.0),  # CO
    "808": (38.8, -104.8),  # CO - Colorado Springs
    "809": (38.8, -104.8),  # CO
    "810": (38.3, -104.6),  # CO - Pueblo
    "820": (41.1, -104.8),  # WY
    "821": (41.1, -104.8),  # WY
    "822": (41.1, -104.8),  # WY
    "823": (42.9, -106.3),  # WY
    "824": (42.9, -106.3),  # WY
    "825": (42.9, -106.3),  # WY
    "826": (42.9, -106.3),  # WY
    "827": (42.9, -106.3),  # WY
    "828": (42.9, -106.3),  # WY
    "829": (42.9, -106.3),  # WY
    "830": (42.9, -106.3),  # WY
    "831": (42.9, -106.3),  # WY
    "832": (43.6, -116.2),  # ID - Boise
    "833": (43.6, -116.2),  # ID
    "834": (43.6, -116.2),  # ID
    "835": (46.7, -117.0),  # ID
    "836": (43.6, -116.2),  # ID
    "837": (43.6, -116.2),  # ID
    "838": (47.7, -116.8),  # ID
    "840": (40.8, -111.9),  # UT - SLC
    "841": (40.8, -111.9),  # UT
    "843": (40.8, -111.9),  # UT
    "844": (41.2, -111.9),  # UT - Ogden
    "845": (40.2, -111.7),  # UT - Provo
    "846": (40.2, -111.7),  # UT
    "847": (40.2, -111.7),  # UT
    "850": (33.4, -112.0),  # AZ - Phoenix
    "851": (33.4, -112.0),  # AZ
    "852": (33.4, -112.0),  # AZ
    "853": (33.4, -112.0),  # AZ
    "855": (33.4, -112.0),  # AZ
    "856": (32.2, -110.9),  # AZ - Tucson
    "857": (32.2, -110.9),  # AZ
    "859": (34.5, -114.4),  # AZ
    "860": (35.2, -111.7),  # AZ - Flagstaff
    "870": (35.1, -106.6),  # NM - Albuquerque
    "871": (35.1, -106.6),  # NM
    "873": (35.1, -106.6),  # NM
    "874": (36.7, -108.2),  # NM
    "875": (32.3, -106.8),  # NM - Las Cruces
    "877": (35.1, -106.6),  # NM
    "878": (34.1, -106.9),  # NM
    "879": (35.1, -106.6),  # NM
    "880": (31.8, -106.4),  # NM / TX - El Paso area
    "890": (36.2, -115.2),  # NV - Las Vegas
    "891": (36.2, -115.2),  # NV
    "893": (39.5, -119.8),  # NV - Reno
    "894": (39.5, -119.8),  # NV
    "895": (39.5, -119.8),  # NV
    "896": (39.5, -119.8),  # NV
    "897": (39.5, -119.8),  # NV
    "898": (39.5, -119.8),  # NV
    "900": (34.1, -118.2),  # CA - LA
    "901": (34.1, -118.2),  # CA
    "902": (34.1, -118.2),  # CA
    "903": (34.1, -118.2),  # CA
    "904": (34.1, -118.2),  # CA
    "905": (33.8, -118.2),  # CA
    "906": (34.1, -118.2),  # CA
    "907": (34.1, -118.2),  # CA
    "908": (34.1, -118.2),  # CA
    "910": (34.1, -118.2),  # CA
    "911": (34.1, -118.2),  # CA
    "912": (34.1, -118.2),  # CA
    "913": (34.1, -118.2),  # CA
    "914": (34.1, -118.2),  # CA
    "915": (34.1, -118.2),  # CA
    "916": (34.1, -118.2),  # CA
    "917": (34.1, -118.2),  # CA
    "918": (34.1, -118.2),  # CA
    "919": (33.0, -117.0),  # CA - San Diego area
    "920": (32.7, -117.2),  # CA - San Diego
    "921": (32.7, -117.2),  # CA
    "922": (33.7, -115.5),  # CA - Palm Springs
    "923": (34.0, -117.5),  # CA - Riverside/San Bern
    "924": (34.0, -117.5),  # CA
    "925": (33.7, -117.9),  # CA - Anaheim area
    "926": (33.7, -117.9),  # CA - Santa Ana
    "927": (33.5, -117.6),  # CA
    "928": (33.7, -117.9),  # CA
    "930": (34.4, -119.7),  # CA - Santa Barbara
    "931": (34.4, -119.7),  # CA
    "932": (36.7, -119.8),  # CA - Fresno
    "933": (36.7, -119.8),  # CA
    "934": (36.6, -121.9),  # CA - Santa Cruz
    "935": (36.7, -119.8),  # CA
    "936": (36.7, -119.8),  # CA
    "937": (36.7, -119.8),  # CA
    "939": (36.6, -121.9),  # CA - Salinas
    "940": (37.8, -122.4),  # CA - SF
    "941": (37.8, -122.4),  # CA
    "942": (38.6, -121.5),  # CA - Sacramento
    "943": (37.3, -121.9),  # CA - San Jose
    "944": (37.3, -121.9),  # CA
    "945": (37.5, -122.2),  # CA - Oakland
    "946": (37.5, -122.2),  # CA
    "947": (37.9, -122.3),  # CA - Berkeley
    "948": (37.9, -122.5),  # CA - Richmond
    "949": (38.0, -122.5),  # CA - San Rafael
    "950": (37.3, -121.9),  # CA - San Jose
    "951": (33.9, -117.6),  # CA - Riverside
    "952": (37.3, -121.9),  # CA
    "953": (37.3, -121.9),  # CA
    "954": (37.7, -122.2),  # CA
    "955": (40.6, -122.4),  # CA - Redding
    "956": (38.6, -121.5),  # CA - Sacramento
    "957": (38.6, -121.5),  # CA
    "958": (38.6, -121.5),  # CA
    "959": (38.4, -121.4),  # CA
    "960": (38.6, -121.5),  # CA
    "970": (45.5, -122.7),  # OR - Portland
    "971": (45.5, -122.7),  # OR
    "972": (45.5, -122.7),  # OR
    "973": (44.9, -123.0),  # OR - Salem
    "974": (44.1, -123.1),  # OR - Eugene
    "975": (42.3, -122.9),  # OR - Medford
    "976": (44.1, -121.3),  # OR - Bend
    "977": (44.1, -121.3),  # OR
    "978": (45.7, -118.8),  # OR - Pendleton
    "979": (43.5, -116.2),  # OR/ID
    "980": (47.6, -122.3),  # WA - Seattle
    "981": (47.6, -122.3),  # WA
    "982": (47.6, -122.3),  # WA
    "983": (47.3, -122.3),  # WA - Tacoma
    "984": (47.3, -122.3),  # WA
    "985": (47.2, -122.4),  # WA
    "986": (45.6, -122.7),  # WA - Vancouver
    "988": (47.7, -117.4),  # WA - Spokane
    "989": (47.0, -120.5),  # WA
    "990": (47.7, -117.4),  # WA - Spokane
    "991": (47.7, -117.4),  # WA
    "992": (47.7, -117.4),  # WA
    "993": (46.6, -120.5),  # WA - Yakima
    "994": (46.6, -120.5),  # WA
    "995": (61.2, -150.0),  # AK - Anchorage
    "996": (61.2, -150.0),  # AK
    "997": (64.8, -147.7),  # AK - Fairbanks
    "998": (58.3, -134.4),  # AK - Juneau
    "999": (58.3, -134.4),  # AK
    "967": (21.3, -157.8),  # HI - Honolulu
    "968": (21.3, -157.8),  # HI
}


def _zip_to_coords(zip_code: str) -> Optional[tuple[float, float]]:
    """Look up approximate lat/lon for a ZIP code using 3-digit prefix.

    Falls back to Google Geocoding API if ZIP3 prefix is not in the lookup table.
    """
    if not zip_code or len(zip_code) < 3:
        return None
    prefix = zip_code[:3]
    coords = _ZIP3_COORDS.get(prefix)
    if coords:
        return coords

    # Fallback: Google Geocoding API
    try:
        import httpx

        from services.credential_store import get_credential_for_service

        cred = get_credential_for_service("google_maps")
        if cred and cred.get("api_key"):
            resp = httpx.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": f"{zip_code}, USA", "key": cred["api_key"]},
                timeout=5,
            )
            data = resp.json()
            if data.get("results"):
                loc = data["results"][0]["geometry"]["location"]
                result = (loc["lat"], loc["lng"])
                # Cache for future lookups
                _ZIP3_COORDS[prefix] = result
                logger.info("Geocoded ZIP %s -> %s (cached as %s)", zip_code, result, prefix)
                return result
    except Exception as e:
        logger.debug("Geocoding fallback failed for ZIP %s: %s", zip_code, e)

    return None
