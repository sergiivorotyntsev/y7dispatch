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
                result = self._google_distance(origin_zip, dest_zip)
                logger.info("[DistanceService] %s → %s: %.1f mi via google", origin_zip, dest_zip, result.distance_miles or 0)
                return result
            except Exception as e:
                logger.warning("Google Distance Matrix failed for %s → %s: %s", origin_zip, dest_zip, e)
        else:
            logger.info("[DistanceService] No Google API key — skipping Google for %s → %s", origin_zip, dest_zip)

        # OSRM fallback (free, no key required)
        try:
            result = self._osrm_distance(origin_zip, dest_zip)
            logger.info("[DistanceService] %s → %s: %.1f mi via osrm (fallback)", origin_zip, dest_zip, result.distance_miles or 0)
            return result
        except Exception as e:
            logger.warning("OSRM fallback failed for %s → %s: %s", origin_zip, dest_zip, e)

        result = self._haversine_distance(origin_zip, dest_zip)
        logger.info("[DistanceService] %s → %s: %.1f mi via haversine (last resort)", origin_zip, dest_zip, result.distance_miles or 0)
        return result

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
                source = cached.get("distance_source") or "cached"
                dist = DistanceResult(
                    distance_miles=cached["distance_miles"],
                    distance_text=cached["distance_text"] or "",
                    duration_minutes=cached["duration_minutes"],
                    duration_text=cached["duration_text"] or "",
                    source=source,
                )
                logger.info("[DistanceService] %s → %s (wh %s): %.1f mi via %s (cached)",
                            pickup_zip, wh_zip, wh.get("code", "?"),
                            cached["distance_miles"] or 0, source)
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
    "005": (18.2, -66.5),  # PR
    "006": (18.2, -66.5),  # PR
    "007": (18.2, -66.5),  # PR
    "008": (18.2, -66.5),  # PR
    "009": (18.2, -66.5),  # PR
    "010": (42.1, -72.6),  # MA
    "011": (42.1, -72.6),  # MA
    "012": (42.4, -73.2),  # MA
    "013": (42.3, -71.8),  # MA
    "014": (42.3, -71.8),  # MA
    "015": (42.3, -71.8),  # MA
    "016": (42.3, -71.8),  # MA
    "017": (42.4, -71.1),  # MA
    "018": (42.4, -71.1),  # MA
    "019": (42.5, -71.0),  # MA
    "020": (42.4, -71.1),  # MA
    "021": (42.4, -71.1),  # MA
    "022": (42.4, -71.1),  # MA
    "023": (41.8, -71.4),  # MA
    "024": (42.4, -71.3),  # MA
    "025": (41.7, -70.3),  # MA
    "026": (41.7, -70.0),  # MA
    "027": (41.8, -71.4),  # MA
    "028": (41.8, -71.4),  # RI
    "029": (41.8, -71.4),  # RI
    "030": (43.0, -71.5),  # NH
    "031": (42.9, -71.4),  # NH
    "032": (43.0, -71.5),  # NH
    "033": (43.2, -71.5),  # NH
    "034": (43.6, -71.7),  # NH
    "035": (44.0, -72.7),  # VT
    "036": (44.0, -72.7),  # VT
    "037": (44.0, -72.7),  # VT
    "038": (44.0, -72.7),  # VT
    "039": (44.0, -72.7),  # VT
    "040": (43.7, -70.3),  # MA
    "041": (43.7, -70.3),  # MA
    "042": (44.0, -70.3),  # MA
    "043": (44.0, -70.3),  # MA
    "044": (44.0, -70.3),  # MA
    "045": (44.0, -70.3),  # MA
    "046": (44.0, -72.6),  # MA
    "047": (44.0, -72.6),  # MA
    "048": (44.0, -72.6),  # MA
    "049": (44.0, -72.6),  # MA
    "050": (44.3, -72.6),  # MA
    "051": (44.6, -72.6),  # MA
    "052": (44.6, -72.6),  # MA
    "053": (44.6, -72.6),  # MA
    "054": (44.6, -72.6),  # MA
    "055": (41.5, -72.7),  # CT
    "056": (41.5, -72.7),  # CT
    "057": (41.5, -72.7),  # CT
    "058": (41.5, -72.7),  # CT
    "059": (41.5, -72.7),  # CT
    "060": (41.8, -72.7),  # CT
    "061": (41.8, -72.7),  # CT
    "062": (41.3, -72.9),  # CT
    "063": (41.2, -73.2),  # CT
    "064": (41.2, -73.2),  # CT
    "065": (41.2, -73.2),  # CT
    "066": (41.2, -73.0),  # CT
    "067": (41.8, -72.2),  # CT
    "068": (41.3, -72.9),  # CT
    "069": (41.3, -72.6),  # CT
    "070": (40.7, -74.2),  # NJ
    "071": (40.7, -74.2),  # NJ
    "072": (40.5, -74.3),  # NJ
    "073": (40.9, -74.2),  # NJ
    "074": (40.9, -74.2),  # NJ
    "075": (40.9, -74.2),  # NJ
    "076": (40.9, -74.2),  # NJ
    "077": (40.2, -74.0),  # NJ
    "078": (40.6, -74.6),  # NJ
    "079": (40.8, -75.0),  # NJ
    "080": (39.9, -75.0),  # NJ
    "081": (40.2, -75.0),  # NJ
    "082": (40.2, -75.0),  # NJ
    "083": (40.2, -75.0),  # NJ
    "084": (40.2, -75.0),  # NJ
    "085": (40.2, -75.0),  # NJ
    "086": (40.2, -75.0),  # NJ
    "087": (40.2, -75.0),  # NJ
    "088": (40.2, -75.0),  # NJ
    "089": (40.2, -75.0),  # NJ
    "100": (40.7, -74.0),  # NY
    "101": (40.7, -74.0),  # NY
    "102": (40.7, -74.0),  # NY
    "103": (40.6, -74.1),  # NY
    "104": (40.8, -73.9),  # NY
    "105": (41.1, -73.9),  # NY
    "106": (41.1, -73.9),  # NY
    "107": (41.1, -73.9),  # NY
    "108": (40.4, -73.5),  # NY
    "109": (40.4, -73.5),  # NY
    "110": (40.7, -73.5),  # NY
    "111": (40.7, -73.5),  # NY
    "112": (40.6, -74.0),  # NY
    "113": (40.7, -73.8),  # NY
    "114": (40.7, -73.8),  # NY
    "115": (40.8, -73.8),  # NY
    "116": (40.7, -73.8),  # NY
    "117": (40.8, -73.3),  # NY
    "118": (40.8, -73.3),  # NY
    "119": (40.8, -73.3),  # NY
    "120": (42.7, -73.7),  # NY
    "121": (42.7, -73.7),  # NY
    "122": (42.7, -73.7),  # NY
    "123": (42.7, -73.7),  # NY
    "124": (43.0, -73.7),  # NY
    "125": (43.0, -73.7),  # NY
    "126": (43.0, -73.7),  # NY
    "127": (42.7, -76.1),  # NY
    "128": (42.7, -76.1),  # NY
    "129": (42.7, -76.1),  # NY
    "130": (43.0, -76.1),  # NY
    "131": (43.3, -76.1),  # NY
    "132": (43.3, -76.1),  # NY
    "133": (43.3, -76.1),  # NY
    "134": (43.3, -76.1),  # NY
    "135": (43.3, -76.1),  # NY
    "136": (42.6, -78.9),  # NY
    "137": (42.6, -78.9),  # NY
    "138": (42.6, -78.9),  # NY
    "139": (42.6, -78.9),  # NY
    "140": (42.9, -78.9),  # NY
    "141": (42.9, -78.9),  # NY
    "142": (42.9, -78.9),  # NY
    "143": (43.2, -77.6),  # NY
    "144": (43.2, -77.6),  # NY
    "145": (43.2, -77.6),  # NY
    "146": (43.2, -77.6),  # NY
    "147": (42.1, -76.8),  # NY
    "148": (42.4, -76.5),  # NY
    "149": (42.1, -79.2),  # NY
    "150": (40.4, -80.0),  # PA
    "151": (40.4, -80.0),  # PA
    "152": (40.4, -80.0),  # PA
    "153": (40.4, -80.0),  # PA
    "154": (40.7, -80.0),  # PA
    "155": (40.7, -80.0),  # PA
    "156": (40.7, -80.0),  # PA
    "157": (40.7, -80.0),  # PA
    "158": (40.7, -80.0),  # PA
    "159": (40.7, -80.0),  # PA
    "160": (40.7, -80.0),  # PA
    "161": (40.7, -80.0),  # PA
    "162": (39.7, -76.3),  # PA
    "163": (39.7, -76.3),  # PA
    "164": (39.7, -76.3),  # PA
    "165": (39.7, -76.3),  # PA
    "166": (39.7, -76.3),  # PA
    "167": (39.7, -76.3),  # PA
    "168": (39.7, -76.3),  # PA
    "169": (39.7, -76.3),  # PA
    "170": (40.0, -76.3),  # PA
    "171": (40.0, -76.3),  # PA
    "172": (40.3, -76.3),  # PA
    "173": (40.3, -76.3),  # PA
    "174": (40.0, -76.0),  # PA
    "175": (40.3, -76.0),  # PA
    "176": (40.6, -76.0),  # PA
    "177": (40.6, -76.0),  # PA
    "178": (40.3, -75.5),  # PA
    "179": (40.3, -75.5),  # PA
    "180": (40.6, -75.5),  # PA
    "181": (40.9, -75.5),  # PA
    "182": (40.9, -75.5),  # PA
    "183": (40.9, -75.5),  # PA
    "184": (40.9, -75.5),  # PA
    "185": (40.9, -75.5),  # PA
    "186": (39.7, -75.1),  # PA
    "187": (39.7, -75.1),  # PA
    "188": (39.7, -75.1),  # PA
    "189": (39.7, -75.1),  # PA
    "190": (40.0, -75.1),  # PA
    "191": (40.0, -75.1),  # PA
    "192": (40.0, -75.1),  # PA
    "193": (40.0, -75.2),  # PA
    "194": (40.3, -75.3),  # PA
    "195": (40.6, -75.3),  # PA
    "196": (40.6, -75.3),  # PA
    "197": (39.2, -75.5),  # DE
    "198": (39.2, -75.5),  # DE
    "199": (39.2, -75.5),  # DE
    "200": (38.9, -77.0),  # DC
    "201": (38.9, -77.0),  # DC
    "202": (39.2, -77.0),  # DC
    "203": (39.2, -77.0),  # DC
    "204": (39.2, -77.0),  # DC
    "205": (39.2, -77.0),  # DC
    "206": (39.0, -76.6),  # MD
    "207": (39.0, -76.6),  # MD
    "208": (39.0, -76.6),  # MD
    "209": (39.0, -76.6),  # MD
    "210": (39.0, -76.6),  # MD
    "211": (39.0, -76.6),  # MD
    "212": (39.0, -76.6),  # MD
    "213": (39.0, -76.6),  # MD
    "214": (39.0, -76.6),  # MD
    "215": (39.0, -76.6),  # MD
    "216": (39.0, -76.6),  # MD
    "217": (39.0, -76.6),  # MD
    "218": (39.0, -76.6),  # MD
    "219": (39.0, -76.6),  # MD
    "220": (38.8, -77.1),  # VA
    "221": (38.8, -77.2),  # VA
    "222": (38.8, -77.2),  # VA
    "223": (38.8, -77.5),  # VA
    "224": (39.1, -77.5),  # VA
    "225": (37.0, -79.4),  # VA
    "226": (37.3, -79.4),  # VA
    "227": (37.6, -79.4),  # VA
    "228": (37.6, -79.4),  # VA
    "229": (37.2, -77.5),  # VA
    "230": (37.5, -77.5),  # VA
    "231": (37.5, -77.5),  # VA
    "232": (37.5, -77.5),  # VA
    "233": (36.8, -76.3),  # VA
    "234": (36.8, -76.3),  # VA
    "235": (36.8, -76.3),  # VA
    "236": (37.0, -76.3),  # VA
    "237": (37.3, -76.5),  # VA
    "238": (37.6, -76.5),  # VA
    "239": (37.6, -76.5),  # VA
    "240": (37.6, -76.5),  # VA
    "241": (37.6, -76.5),  # VA
    "242": (37.6, -76.5),  # VA
    "243": (37.6, -76.5),  # VA
    "244": (37.6, -76.5),  # VA
    "245": (37.6, -76.5),  # VA
    "246": (37.6, -76.5),  # VA
    "247": (38.6, -80.5),  # WV
    "248": (38.6, -80.5),  # WV
    "249": (38.6, -80.5),  # WV
    "250": (38.6, -80.5),  # WV
    "251": (38.6, -80.5),  # WV
    "252": (38.6, -80.5),  # WV
    "253": (38.6, -80.5),  # WV
    "254": (38.6, -80.5),  # WV
    "255": (38.6, -80.5),  # WV
    "256": (38.6, -80.5),  # WV
    "257": (38.6, -80.5),  # WV
    "258": (38.6, -80.5),  # WV
    "259": (38.6, -80.5),  # WV
    "260": (38.6, -80.5),  # WV
    "261": (38.6, -80.5),  # WV
    "262": (38.6, -80.5),  # WV
    "263": (38.6, -80.5),  # WV
    "264": (38.6, -80.5),  # WV
    "265": (38.6, -80.5),  # WV
    "266": (38.6, -80.5),  # WV
    "267": (38.6, -80.5),  # WV
    "268": (38.6, -80.5),  # WV
    "269": (35.5, -78.6),  # UNKNOWN
    "270": (35.8, -78.6),  # NC
    "271": (36.1, -80.2),  # NC
    "272": (35.2, -80.8),  # NC
    "273": (36.1, -80.2),  # NC
    "274": (35.6, -82.6),  # NC
    "275": (35.8, -78.6),  # NC
    "276": (36.1, -79.8),  # NC
    "277": (35.2, -80.8),  # NC
    "278": (35.6, -82.6),  # NC
    "279": (35.1, -80.7),  # NC
    "280": (33.9, -81.0),  # NC
    "281": (35.0, -78.9),  # NC
    "282": (35.2, -80.8),  # NC
    "283": (34.2, -79.8),  # NC
    "284": (34.8, -82.4),  # NC
    "285": (35.3, -83.5),  # NC
    "286": (36.2, -81.7),  # NC
    "287": (36.3, -79.4),  # NC
    "288": (34.3, -77.9),  # NC
    "289": (35.0, -80.6),  # NC
    "290": (34.0, -81.0),  # SC
    "291": (34.0, -81.0),  # SC
    "292": (34.0, -81.0),  # SC
    "293": (32.8, -79.9),  # SC
    "294": (32.8, -79.9),  # SC
    "295": (34.8, -82.4),  # SC
    "296": (35.1, -82.4),  # SC
    "297": (35.1, -82.4),  # SC
    "298": (35.1, -82.4),  # SC
    "299": (35.1, -82.4),  # SC
    "300": (33.7, -84.4),  # GA
    "301": (33.7, -84.4),  # GA
    "302": (33.7, -84.4),  # GA
    "303": (33.7, -84.4),  # GA
    "304": (33.5, -84.5),  # GA
    "305": (33.8, -84.3),  # GA
    "306": (33.5, -83.9),  # GA
    "307": (33.8, -83.9),  # GA
    "308": (33.8, -83.9),  # GA
    "309": (31.8, -81.1),  # GA
    "310": (32.1, -81.1),  # GA
    "311": (33.7, -84.4),  # GA
    "312": (32.5, -84.9),  # GA
    "313": (32.5, -84.9),  # GA
    "314": (32.8, -84.9),  # GA
    "315": (32.8, -84.9),  # GA
    "316": (32.8, -84.9),  # GA
    "317": (32.8, -84.9),  # GA
    "318": (32.8, -84.9),  # GA
    "319": (32.8, -84.9),  # GA
    "320": (30.3, -81.7),  # FL
    "321": (28.5, -81.4),  # FL
    "322": (30.3, -81.7),  # FL
    "323": (28.5, -81.4),  # FL
    "324": (30.4, -86.6),  # FL
    "325": (27.8, -82.6),  # FL
    "326": (29.2, -82.1),  # FL
    "327": (28.5, -81.4),  # FL
    "328": (28.5, -81.4),  # FL
    "329": (28.1, -80.6),  # FL
    "330": (25.8, -80.2),  # FL
    "331": (25.8, -80.2),  # FL
    "332": (25.8, -80.2),  # FL
    "333": (26.1, -80.1),  # FL
    "334": (26.7, -80.1),  # FL
    "335": (27.9, -82.5),  # FL
    "336": (27.9, -82.5),  # FL
    "337": (27.3, -82.5),  # FL
    "338": (28.0, -82.5),  # FL
    "339": (26.6, -82.0),  # FL
    "343": (26.9, -82.0),  # FL
    "344": (26.9, -82.0),  # FL
    "345": (26.9, -82.0),  # FL
    "346": (26.9, -82.0),  # FL
    "347": (26.9, -82.0),  # FL
    "348": (26.9, -82.0),  # FL
    "349": (26.9, -82.0),  # FL
    "350": (33.5, -86.8),  # AL
    "351": (33.5, -86.8),  # AL
    "352": (33.5, -86.8),  # AL
    "353": (33.8, -86.8),  # AL
    "354": (34.7, -87.7),  # AL
    "355": (34.7, -87.7),  # AL
    "356": (34.7, -86.6),  # AL
    "357": (35.0, -86.6),  # AL
    "358": (35.0, -86.6),  # AL
    "359": (32.1, -86.3),  # AL
    "360": (32.4, -86.3),  # AL
    "361": (32.4, -86.3),  # AL
    "362": (33.2, -87.5),  # AL
    "363": (33.5, -87.5),  # AL
    "364": (30.4, -88.1),  # AL
    "365": (30.7, -88.1),  # AL
    "366": (30.7, -88.1),  # AL
    "367": (31.0, -88.1),  # AL
    "368": (31.0, -88.1),  # AL
    "369": (31.0, -88.1),  # AL
    "370": (36.2, -86.8),  # TN
    "371": (36.2, -86.8),  # TN
    "372": (36.2, -86.8),  # TN
    "373": (35.0, -85.3),  # TN
    "374": (35.0, -85.3),  # TN
    "375": (36.5, -87.4),  # TN
    "376": (36.6, -82.6),  # TN
    "377": (35.9, -83.9),  # TN
    "378": (35.9, -83.9),  # TN
    "379": (35.1, -90.0),  # TN
    "380": (35.1, -90.0),  # TN
    "381": (35.1, -90.0),  # TN
    "382": (35.1, -90.0),  # TN
    "383": (35.4, -90.0),  # TN
    "384": (35.4, -90.0),  # TN
    "385": (35.4, -90.0),  # TN
    "386": (32.3, -90.2),  # MS
    "387": (32.3, -90.2),  # MS
    "388": (32.6, -90.2),  # MS
    "389": (32.0, -90.2),  # MS
    "390": (32.3, -90.2),  # MS
    "391": (32.3, -90.2),  # MS
    "392": (32.6, -90.2),  # MS
    "393": (32.6, -90.2),  # MS
    "394": (32.6, -90.2),  # MS
    "395": (32.6, -90.2),  # MS
    "396": (32.6, -90.2),  # MS
    "397": (32.6, -90.2),  # MS
    "398": (32.7, -83.5),  # GA
    "399": (32.7, -83.5),  # GA
    "400": (38.3, -85.8),  # KY
    "401": (38.3, -85.8),  # KY
    "402": (38.3, -85.8),  # KY
    "403": (38.0, -84.5),  # KY
    "404": (38.0, -84.5),  # KY
    "405": (38.0, -84.5),  # KY
    "406": (38.3, -84.5),  # KY
    "407": (38.3, -84.5),  # KY
    "408": (38.3, -84.5),  # KY
    "409": (38.3, -84.5),  # KY
    "410": (38.3, -84.5),  # KY
    "411": (38.3, -84.5),  # KY
    "412": (38.3, -84.5),  # KY
    "413": (38.3, -84.5),  # KY
    "414": (38.3, -84.5),  # KY
    "415": (38.3, -84.5),  # KY
    "416": (37.8, -84.3),  # KY
    "417": (37.8, -84.3),  # KY
    "418": (37.8, -84.3),  # KY
    "419": (37.8, -84.3),  # KY
    "420": (37.8, -84.3),  # KY
    "421": (37.8, -84.3),  # KY
    "422": (37.8, -84.3),  # KY
    "423": (37.8, -84.3),  # KY
    "424": (37.8, -84.3),  # KY
    "425": (37.8, -84.3),  # KY
    "426": (37.8, -84.3),  # KY
    "427": (37.8, -84.3),  # KY
    "428": (39.6, -83.0),  # UNKNOWN
    "429": (39.6, -83.0),  # UNKNOWN
    "430": (39.9, -83.0),  # OH
    "431": (39.9, -83.0),  # OH
    "432": (39.9, -83.0),  # OH
    "433": (40.2, -83.0),  # OH
    "434": (40.2, -83.0),  # OH
    "435": (40.2, -83.0),  # OH
    "436": (40.2, -83.0),  # OH
    "437": (41.2, -81.7),  # OH
    "438": (41.2, -81.7),  # OH
    "439": (41.2, -81.7),  # OH
    "440": (41.5, -81.7),  # OH
    "441": (41.5, -81.7),  # OH
    "442": (41.1, -81.5),  # OH
    "443": (41.1, -81.5),  # OH
    "444": (41.1, -80.6),  # OH
    "445": (41.1, -80.6),  # OH
    "446": (40.8, -81.4),  # OH
    "447": (40.8, -81.4),  # OH
    "448": (40.1, -82.9),  # OH
    "449": (40.8, -82.5),  # OH
    "450": (39.1, -84.5),  # OH
    "451": (39.1, -84.5),  # OH
    "452": (39.1, -84.5),  # OH
    "453": (39.8, -84.2),  # OH
    "454": (39.8, -84.2),  # OH
    "455": (40.1, -84.0),  # OH
    "456": (39.3, -84.3),  # OH
    "457": (40.8, -83.8),  # OH
    "458": (40.8, -83.5),  # OH
    "459": (41.1, -83.5),  # UNKNOWN
    "460": (39.8, -86.2),  # IN
    "461": (39.8, -86.2),  # IN
    "462": (39.8, -86.2),  # IN
    "463": (39.8, -86.2),  # IN
    "464": (41.1, -85.1),  # IN
    "465": (41.1, -85.1),  # IN
    "466": (41.7, -86.3),  # IN
    "467": (41.7, -86.3),  # IN
    "468": (41.7, -86.3),  # IN
    "469": (41.7, -86.3),  # IN
    "470": (39.1, -86.5),  # IN
    "471": (38.3, -86.0),  # IN
    "472": (39.8, -86.2),  # IN
    "473": (38.0, -87.6),  # IN
    "474": (39.2, -86.5),  # IN
    "475": (39.8, -87.4),  # IN
    "476": (40.4, -86.9),  # IN
    "477": (38.0, -87.6),  # IN
    "478": (39.5, -87.4),  # IN
    "479": (40.4, -86.9),  # IN
    "480": (42.3, -83.0),  # MI
    "481": (42.3, -83.0),  # MI
    "482": (42.3, -83.0),  # MI
    "483": (42.3, -83.0),  # MI
    "484": (42.7, -83.3),  # MI
    "485": (42.7, -83.3),  # MI
    "486": (43.4, -83.9),  # MI
    "487": (43.4, -83.9),  # MI
    "488": (42.7, -84.5),  # MI
    "489": (42.3, -85.2),  # MI
    "490": (42.3, -85.2),  # MI
    "491": (42.3, -85.2),  # MI
    "492": (42.9, -85.7),  # MI
    "493": (42.9, -85.7),  # MI
    "494": (42.9, -85.7),  # MI
    "495": (43.4, -85.0),  # MI
    "496": (44.3, -85.6),  # MI
    "497": (46.5, -87.4),  # MI
    "498": (46.5, -87.4),  # MI
    "499": (46.5, -87.4),  # MI
    "500": (41.6, -93.6),  # IA
    "501": (41.6, -93.6),  # IA
    "502": (41.6, -93.6),  # IA
    "503": (41.6, -93.6),  # IA
    "504": (41.9, -93.6),  # IA
    "505": (41.9, -93.6),  # IA
    "506": (41.9, -93.6),  # IA
    "507": (41.9, -93.6),  # IA
    "508": (41.9, -93.6),  # IA
    "509": (41.9, -93.6),  # IA
    "510": (41.9, -93.6),  # IA
    "511": (41.9, -93.6),  # IA
    "512": (41.9, -93.6),  # IA
    "513": (41.9, -93.6),  # IA
    "514": (42.0, -93.2),  # IA
    "515": (42.0, -93.2),  # IA
    "516": (42.0, -93.2),  # IA
    "517": (42.0, -93.2),  # IA
    "518": (42.0, -93.2),  # IA
    "519": (42.0, -93.2),  # IA
    "520": (42.0, -93.2),  # IA
    "521": (42.0, -93.2),  # IA
    "522": (42.0, -93.2),  # IA
    "523": (42.0, -93.2),  # IA
    "524": (42.0, -93.2),  # IA
    "525": (42.0, -93.2),  # IA
    "526": (42.0, -93.2),  # IA
    "527": (42.0, -93.2),  # IA
    "528": (42.0, -93.2),  # IA
    "529": (42.8, -89.4),  # UNKNOWN
    "530": (43.1, -89.4),  # WI
    "531": (43.1, -89.4),  # WI
    "532": (42.7, -87.8),  # WI
    "533": (43.0, -87.8),  # WI
    "534": (42.7, -87.8),  # WI
    "535": (43.1, -89.4),  # WI
    "536": (43.4, -89.4),  # WI
    "537": (43.4, -89.4),  # WI
    "538": (44.2, -88.0),  # WI
    "539": (44.2, -88.0),  # WI
    "540": (44.5, -88.0),  # WI
    "541": (44.5, -88.0),  # WI
    "542": (44.8, -88.0),  # WI
    "543": (44.8, -88.0),  # WI
    "544": (44.8, -88.0),  # WI
    "545": (44.8, -88.0),  # WI
    "546": (44.8, -88.0),  # WI
    "547": (44.8, -88.0),  # WI
    "548": (44.8, -88.0),  # WI
    "549": (44.8, -88.0),  # WI
    "550": (44.9, -93.3),  # MN
    "551": (44.9, -93.3),  # MN
    "552": (45.2, -93.3),  # MN
    "553": (44.9, -93.3),  # MN
    "554": (44.9, -93.3),  # MN
    "555": (44.9, -93.3),  # MN
    "556": (47.0, -94.9),  # MN
    "557": (47.0, -94.9),  # MN
    "558": (47.0, -94.9),  # MN
    "559": (44.0, -92.5),  # MN
    "560": (44.3, -92.5),  # MN
    "561": (44.3, -92.5),  # MN
    "562": (44.3, -92.5),  # MN
    "563": (44.3, -92.5),  # MN
    "564": (44.3, -92.5),  # MN
    "565": (44.3, -92.5),  # MN
    "566": (44.3, -92.5),  # MN
    "567": (44.3, -92.5),  # MN
    "568": (43.2, -96.7),  # UNKNOWN
    "569": (43.2, -96.7),  # UNKNOWN
    "570": (43.5, -96.7),  # SD
    "571": (43.8, -96.7),  # SD
    "572": (43.8, -96.7),  # SD
    "573": (43.8, -96.7),  # SD
    "574": (43.8, -96.7),  # SD
    "575": (43.8, -96.7),  # SD
    "576": (43.8, -96.7),  # SD
    "577": (43.8, -96.7),  # SD
    "578": (46.6, -96.8),  # UNKNOWN
    "579": (46.6, -96.8),  # UNKNOWN
    "580": (46.9, -96.8),  # ND
    "581": (47.2, -96.8),  # ND
    "582": (47.2, -96.8),  # ND
    "583": (47.2, -96.8),  # ND
    "584": (47.2, -96.8),  # ND
    "585": (47.2, -96.8),  # ND
    "586": (47.2, -96.8),  # ND
    "587": (47.2, -96.8),  # ND
    "588": (47.2, -96.8),  # ND
    "589": (46.6, -110.4),  # UNKNOWN
    "590": (46.9, -110.4),  # MT
    "591": (47.2, -110.4),  # MT
    "592": (47.2, -110.4),  # MT
    "593": (47.2, -110.4),  # MT
    "594": (47.2, -110.4),  # MT
    "595": (47.2, -110.4),  # MT
    "596": (47.2, -110.4),  # MT
    "597": (47.2, -110.4),  # MT
    "598": (47.2, -110.4),  # MT
    "599": (47.2, -110.4),  # MT
    "600": (41.9, -87.6),  # IL
    "601": (41.9, -87.6),  # IL
    "602": (41.9, -87.6),  # IL
    "603": (41.9, -87.6),  # IL
    "604": (41.9, -87.6),  # IL
    "605": (41.9, -87.6),  # IL
    "606": (41.9, -87.6),  # IL
    "607": (41.9, -87.6),  # IL
    "608": (41.9, -87.6),  # IL
    "609": (41.5, -88.1),  # IL
    "610": (40.7, -89.6),  # IL
    "611": (41.5, -90.5),  # IL
    "612": (41.5, -90.5),  # IL
    "613": (41.8, -90.5),  # IL
    "614": (41.8, -90.5),  # IL
    "615": (39.5, -89.6),  # IL
    "616": (39.5, -89.6),  # IL
    "617": (39.8, -89.6),  # IL
    "618": (38.6, -90.2),  # IL
    "619": (38.6, -90.2),  # IL
    "620": (38.5, -89.0),  # IL
    "621": (38.8, -89.0),  # IL
    "622": (38.5, -89.0),  # IL
    "623": (37.0, -89.2),  # IL
    "624": (37.3, -89.2),  # IL
    "625": (37.3, -89.2),  # IL
    "626": (37.3, -89.2),  # IL
    "627": (37.3, -89.2),  # IL
    "628": (37.3, -89.2),  # IL
    "629": (37.3, -89.2),  # IL
    "630": (38.6, -90.2),  # MO
    "631": (38.6, -90.2),  # MO
    "632": (38.9, -90.2),  # MO
    "633": (38.6, -90.2),  # MO
    "634": (38.9, -90.2),  # MO
    "635": (38.9, -90.2),  # MO
    "636": (38.9, -90.2),  # MO
    "637": (38.8, -94.6),  # MO
    "638": (38.8, -94.6),  # MO
    "639": (38.8, -94.6),  # MO
    "640": (39.1, -94.6),  # MO
    "641": (39.1, -94.6),  # MO
    "642": (39.4, -94.6),  # MO
    "643": (36.9, -93.3),  # MO
    "644": (37.2, -93.3),  # MO
    "645": (37.2, -93.3),  # MO
    "646": (39.1, -94.6),  # MO
    "647": (39.1, -94.6),  # MO
    "648": (37.2, -93.3),  # MO
    "649": (37.5, -93.3),  # MO
    "650": (38.6, -92.2),  # MO
    "651": (38.9, -92.2),  # MO
    "652": (38.9, -92.2),  # MO
    "653": (38.9, -92.2),  # MO
    "654": (38.9, -92.2),  # MO
    "655": (38.9, -92.2),  # MO
    "656": (38.9, -92.2),  # MO
    "657": (38.9, -92.2),  # MO
    "658": (38.9, -92.2),  # MO
    "659": (38.8, -94.6),  # UNKNOWN
    "660": (39.1, -94.6),  # KS
    "661": (39.1, -94.6),  # KS
    "662": (39.0, -95.7),  # KS
    "663": (39.3, -95.7),  # KS
    "664": (39.0, -95.7),  # KS
    "665": (39.0, -95.7),  # KS
    "666": (39.0, -95.7),  # KS
    "667": (37.7, -97.3),  # KS
    "668": (38.0, -97.3),  # KS
    "669": (37.4, -97.3),  # KS
    "670": (37.7, -97.3),  # KS
    "671": (37.7, -97.3),  # KS
    "672": (37.7, -97.3),  # KS
    "673": (38.0, -97.3),  # KS
    "674": (38.0, -97.3),  # KS
    "675": (38.0, -97.3),  # KS
    "676": (38.0, -97.3),  # KS
    "677": (38.0, -97.3),  # KS
    "678": (38.0, -97.3),  # KS
    "679": (38.0, -97.3),  # KS
    "680": (41.3, -96.0),  # NE
    "681": (41.3, -96.0),  # NE
    "682": (41.6, -96.0),  # NE
    "683": (40.8, -96.7),  # NE
    "684": (41.1, -96.7),  # NE
    "685": (41.1, -96.7),  # NE
    "686": (41.1, -96.7),  # NE
    "687": (41.1, -96.7),  # NE
    "688": (41.1, -96.7),  # NE
    "689": (41.1, -96.7),  # NE
    "690": (41.1, -96.7),  # NE
    "691": (41.1, -96.7),  # NE
    "692": (41.1, -96.7),  # NE
    "693": (41.1, -96.7),  # NE
    "694": (29.7, -90.1),  # UNKNOWN
    "695": (29.7, -90.1),  # UNKNOWN
    "696": (29.7, -90.1),  # UNKNOWN
    "697": (29.7, -90.1),  # UNKNOWN
    "698": (29.7, -90.1),  # UNKNOWN
    "699": (29.7, -90.1),  # UNKNOWN
    "700": (30.0, -90.1),  # LA
    "701": (30.0, -90.1),  # LA
    "702": (30.3, -90.1),  # LA
    "703": (30.0, -90.1),  # LA
    "704": (32.5, -93.7),  # LA
    "705": (32.8, -93.7),  # LA
    "706": (30.2, -93.2),  # LA
    "707": (30.5, -91.1),  # LA
    "708": (30.5, -91.1),  # LA
    "709": (30.8, -91.1),  # LA
    "710": (32.5, -93.7),  # LA
    "711": (32.5, -93.7),  # LA
    "712": (30.2, -92.0),  # LA
    "713": (30.2, -92.0),  # LA
    "714": (32.5, -92.1),  # LA
    "715": (32.8, -92.1),  # UNKNOWN
    "716": (34.5, -92.3),  # AR
    "717": (34.8, -92.3),  # AR
    "718": (34.8, -92.3),  # AR
    "719": (34.4, -92.3),  # AR
    "720": (34.7, -92.3),  # AR
    "721": (34.7, -92.3),  # AR
    "722": (34.7, -92.3),  # AR
    "723": (35.4, -94.4),  # AR
    "724": (35.4, -94.4),  # AR
    "725": (35.4, -94.4),  # AR
    "726": (36.4, -94.2),  # AR
    "727": (36.4, -94.2),  # AR
    "728": (33.5, -92.0),  # AR
    "729": (33.8, -92.0),  # AR
    "730": (35.5, -97.5),  # OK
    "731": (35.5, -97.5),  # OK
    "732": (35.8, -97.5),  # OK
    "733": (35.2, -97.5),  # OK
    "734": (35.5, -97.5),  # OK
    "735": (35.5, -97.5),  # OK
    "736": (35.5, -97.5),  # OK
    "737": (35.8, -97.5),  # OK
    "738": (35.8, -97.5),  # OK
    "739": (35.9, -95.9),  # OK
    "740": (36.2, -95.9),  # OK
    "741": (36.2, -95.9),  # OK
    "742": (36.5, -95.9),  # OK
    "743": (36.2, -95.9),  # OK
    "744": (34.6, -98.4),  # OK
    "745": (36.7, -97.1),  # OK
    "746": (34.2, -97.1),  # OK
    "747": (34.5, -97.1),  # OK
    "748": (34.2, -97.1),  # OK
    "749": (34.2, -96.3),  # OK
    "750": (32.8, -96.8),  # TX
    "751": (32.8, -96.8),  # TX
    "752": (32.7, -97.3),  # TX
    "753": (32.7, -97.3),  # TX
    "754": (32.8, -96.8),  # TX
    "755": (32.8, -96.8),  # TX
    "756": (32.8, -96.8),  # TX
    "757": (31.5, -97.1),  # TX
    "758": (31.5, -97.1),  # TX
    "759": (33.9, -98.5),  # TX
    "760": (32.7, -97.3),  # TX
    "761": (32.7, -97.3),  # TX
    "762": (32.8, -96.8),  # TX
    "763": (32.8, -96.8),  # TX
    "764": (32.8, -96.8),  # TX
    "765": (31.8, -97.4),  # TX
    "766": (31.8, -97.4),  # TX
    "767": (31.8, -97.4),  # TX
    "768": (32.4, -99.7),  # TX
    "769": (31.4, -100.4),  # TX
    "770": (29.8, -95.4),  # TX
    "771": (29.8, -95.4),  # TX
    "772": (29.8, -95.4),  # TX
    "773": (29.8, -95.4),  # TX
    "774": (29.8, -95.4),  # TX
    "775": (30.1, -95.0),  # TX
    "776": (30.1, -94.1),  # TX
    "777": (30.1, -94.1),  # TX
    "778": (27.5, -99.5),  # TX
    "779": (27.8, -97.4),  # TX
    "780": (29.4, -98.5),  # TX
    "781": (29.4, -98.5),  # TX
    "782": (29.4, -98.5),  # TX
    "783": (27.8, -97.4),  # TX
    "784": (27.8, -97.4),  # TX
    "785": (26.2, -98.2),  # TX
    "786": (30.3, -97.7),  # TX
    "787": (30.3, -97.7),  # TX
    "788": (30.3, -97.7),  # TX
    "789": (30.3, -97.7),  # TX
    "790": (33.6, -101.8),  # TX
    "791": (35.2, -101.8),  # TX
    "792": (35.5, -101.8),  # TX
    "793": (31.8, -106.4),  # TX
    "794": (31.8, -106.4),  # TX
    "795": (31.8, -106.4),  # TX
    "796": (31.8, -106.4),  # TX
    "797": (31.7, -102.5),  # TX
    "798": (31.8, -106.4),  # TX
    "799": (31.8, -106.4),  # TX
    "800": (39.7, -105.0),  # CO
    "801": (39.7, -105.0),  # CO
    "802": (39.7, -105.0),  # CO
    "803": (39.7, -105.0),  # CO
    "804": (39.7, -105.0),  # CO
    "805": (39.7, -105.0),  # CO
    "806": (39.7, -105.0),  # CO
    "807": (40.0, -105.0),  # CO
    "808": (38.8, -104.8),  # CO
    "809": (38.8, -104.8),  # CO
    "810": (38.3, -104.6),  # CO
    "811": (38.6, -104.6),  # CO
    "812": (38.6, -104.6),  # CO
    "813": (38.6, -104.6),  # CO
    "814": (38.6, -104.6),  # CO
    "815": (38.6, -104.6),  # CO
    "816": (38.6, -104.6),  # CO
    "817": (40.8, -104.8),  # UNKNOWN
    "818": (40.8, -104.8),  # UNKNOWN
    "819": (40.8, -104.8),  # UNKNOWN
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
    "832": (43.6, -116.2),  # ID
    "833": (43.6, -116.2),  # ID
    "834": (43.6, -116.2),  # ID
    "835": (46.7, -117.0),  # ID
    "836": (43.6, -116.2),  # ID
    "837": (43.6, -116.2),  # ID
    "838": (47.7, -116.8),  # ID
    "839": (48.0, -116.8),  # UNKNOWN
    "840": (40.8, -111.9),  # UT
    "841": (40.8, -111.9),  # UT
    "842": (41.1, -111.9),  # UT
    "843": (40.8, -111.9),  # UT
    "844": (41.2, -111.9),  # UT
    "845": (40.2, -111.7),  # UT
    "846": (40.2, -111.7),  # UT
    "847": (40.2, -111.7),  # UT
    "848": (40.5, -111.7),  # UNKNOWN
    "849": (33.1, -112.0),  # UNKNOWN
    "850": (33.4, -112.0),  # AZ
    "851": (33.4, -112.0),  # AZ
    "852": (33.4, -112.0),  # AZ
    "853": (33.4, -112.0),  # AZ
    "854": (33.7, -112.0),  # AZ
    "855": (33.4, -112.0),  # AZ
    "856": (32.2, -110.9),  # AZ
    "857": (32.2, -110.9),  # AZ
    "858": (32.5, -110.9),  # AZ
    "859": (34.5, -114.4),  # AZ
    "860": (35.2, -111.7),  # AZ
    "861": (35.5, -111.7),  # AZ
    "862": (35.5, -111.7),  # AZ
    "863": (35.5, -111.7),  # AZ
    "864": (35.5, -111.7),  # AZ
    "865": (35.5, -111.7),  # AZ
    "866": (34.8, -106.6),  # UNKNOWN
    "867": (34.8, -106.6),  # UNKNOWN
    "868": (34.8, -106.6),  # UNKNOWN
    "869": (34.8, -106.6),  # UNKNOWN
    "870": (35.1, -106.6),  # NM
    "871": (35.1, -106.6),  # NM
    "872": (35.4, -106.6),  # NM
    "873": (35.1, -106.6),  # NM
    "874": (36.7, -108.2),  # NM
    "875": (32.3, -106.8),  # NM
    "876": (32.6, -106.8),  # NM
    "877": (35.1, -106.6),  # NM
    "878": (34.1, -106.9),  # NM
    "879": (35.1, -106.6),  # NM
    "880": (31.8, -106.4),  # NM
    "881": (32.1, -106.4),  # NM
    "882": (32.1, -106.4),  # NM
    "883": (32.1, -106.4),  # NM
    "884": (32.1, -106.4),  # NM
    "885": (32.1, -106.4),  # UNKNOWN
    "886": (35.9, -115.2),  # UNKNOWN
    "887": (35.9, -115.2),  # UNKNOWN
    "888": (35.9, -115.2),  # UNKNOWN
    "889": (35.9, -115.2),  # NV
    "890": (36.2, -115.2),  # NV
    "891": (36.2, -115.2),  # NV
    "892": (36.5, -115.2),  # NV
    "893": (39.5, -119.8),  # NV
    "894": (39.5, -119.8),  # NV
    "895": (39.5, -119.8),  # NV
    "896": (39.5, -119.8),  # NV
    "897": (39.5, -119.8),  # NV
    "898": (39.5, -119.8),  # NV
    "899": (39.8, -119.8),  # UNKNOWN
    "900": (34.1, -118.2),  # CA
    "901": (34.1, -118.2),  # CA
    "902": (34.1, -118.2),  # CA
    "903": (34.1, -118.2),  # CA
    "904": (34.1, -118.2),  # CA
    "905": (33.8, -118.2),  # CA
    "906": (34.1, -118.2),  # CA
    "907": (34.1, -118.2),  # CA
    "908": (34.1, -118.2),  # CA
    "909": (34.4, -118.2),  # CA
    "910": (34.1, -118.2),  # CA
    "911": (34.1, -118.2),  # CA
    "912": (34.1, -118.2),  # CA
    "913": (34.1, -118.2),  # CA
    "914": (34.1, -118.2),  # CA
    "915": (34.1, -118.2),  # CA
    "916": (34.1, -118.2),  # CA
    "917": (34.1, -118.2),  # CA
    "918": (34.1, -118.2),  # CA
    "919": (33.0, -117.0),  # CA
    "920": (32.7, -117.2),  # CA
    "921": (32.7, -117.2),  # CA
    "922": (33.7, -115.5),  # CA
    "923": (34.0, -117.5),  # CA
    "924": (34.0, -117.5),  # CA
    "925": (33.7, -117.9),  # CA
    "926": (33.7, -117.9),  # CA
    "927": (33.5, -117.6),  # CA
    "928": (33.7, -117.9),  # CA
    "929": (34.0, -117.9),  # CA
    "930": (34.4, -119.7),  # CA
    "931": (34.4, -119.7),  # CA
    "932": (36.7, -119.8),  # CA
    "933": (36.7, -119.8),  # CA
    "934": (36.6, -121.9),  # CA
    "935": (36.7, -119.8),  # CA
    "936": (36.7, -119.8),  # CA
    "937": (36.7, -119.8),  # CA
    "938": (37.0, -119.8),  # CA
    "939": (36.6, -121.9),  # CA
    "940": (37.8, -122.4),  # CA
    "941": (37.8, -122.4),  # CA
    "942": (38.6, -121.5),  # CA
    "943": (37.3, -121.9),  # CA
    "944": (37.3, -121.9),  # CA
    "945": (37.5, -122.2),  # CA
    "946": (37.5, -122.2),  # CA
    "947": (37.9, -122.3),  # CA
    "948": (37.9, -122.5),  # CA
    "949": (38.0, -122.5),  # CA
    "950": (37.3, -121.9),  # CA
    "951": (33.9, -117.6),  # CA
    "952": (37.3, -121.9),  # CA
    "953": (37.3, -121.9),  # CA
    "954": (37.7, -122.2),  # CA
    "955": (40.6, -122.4),  # CA
    "956": (38.6, -121.5),  # CA
    "957": (38.6, -121.5),  # CA
    "958": (38.6, -121.5),  # CA
    "959": (38.4, -121.4),  # CA
    "960": (38.6, -121.5),  # CA
    "961": (38.9, -121.5),  # CA
    "962": (38.9, -121.5),  # CA
    "963": (38.9, -121.5),  # CA
    "964": (38.9, -121.5),  # CA
    "965": (38.9, -121.5),  # CA
    "966": (38.9, -121.5),  # CA
    "967": (21.3, -157.8),  # HI
    "968": (21.3, -157.8),  # HI
    "969": (21.6, -157.8),  # UNKNOWN
    "970": (45.5, -122.7),  # OR
    "971": (45.5, -122.7),  # OR
    "972": (45.5, -122.7),  # OR
    "973": (44.9, -123.0),  # OR
    "974": (44.1, -123.1),  # OR
    "975": (42.3, -122.9),  # OR
    "976": (44.1, -121.3),  # OR
    "977": (44.1, -121.3),  # OR
    "978": (45.7, -118.8),  # OR
    "979": (43.5, -116.2),  # OR
    "980": (47.6, -122.3),  # WA
    "981": (47.6, -122.3),  # WA
    "982": (47.6, -122.3),  # WA
    "983": (47.3, -122.3),  # WA
    "984": (47.3, -122.3),  # WA
    "985": (47.2, -122.4),  # WA
    "986": (45.6, -122.7),  # WA
    "987": (45.9, -122.7),  # WA
    "988": (47.7, -117.4),  # WA
    "989": (47.0, -120.5),  # WA
    "990": (47.7, -117.4),  # WA
    "991": (47.7, -117.4),  # WA
    "992": (47.7, -117.4),  # WA
    "993": (46.6, -120.5),  # WA
    "994": (46.6, -120.5),  # WA
    "995": (61.2, -150.0),  # AK
    "996": (61.2, -150.0),  # AK
    "997": (64.8, -147.7),  # AK
    "998": (58.3, -134.4),  # AK
    "999": (58.3, -134.4),  # AK
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
