"""
Weather Service — NWS route alerts for vehicle transport.

Queries the National Weather Service API for active alerts along a
transport route (pickup → warehouse). Interpolates waypoints along
the straight-line path, queries alerts at each point and for each
state the route traverses, then deduplicates and categorizes.

Cache: 1-hour TTL keyed on origin_zip + warehouse_id.
"""

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx

from api.database import get_connection

logger = logging.getLogger(__name__)

# Cache TTL
WEATHER_CACHE_TTL = 3600  # 1 hour

# NWS API config
NWS_BASE = "https://api.weather.gov"
NWS_USER_AGENT = "(Y7Dispatch, info@y7agency.com)"
NWS_TIMEOUT = 15  # seconds

# Alert types relevant to vehicle transport (road impact)
TRANSPORT_ALERT_TYPES = {
    # Winter
    "Blizzard Warning",
    "Winter Storm Warning",
    "Winter Storm Watch",
    "Ice Storm Warning",
    "Winter Weather Advisory",
    "Freeze Warning",
    "Wind Chill Warning",
    "Wind Chill Advisory",
    # Wind
    "High Wind Warning",
    "Wind Advisory",
    "Extreme Wind Warning",
    # Flood
    "Flash Flood Warning",
    "Flood Warning",
    "Flood Watch",
    # Tornado / Hurricane
    "Tornado Warning",
    "Tornado Watch",
    "Hurricane Warning",
    "Tropical Storm Warning",
    # Visibility
    "Dense Fog Advisory",
    "Dust Storm Warning",
    # Fire (road closures possible)
    "Red Flag Warning",
}

# NWS severity → our display level
SEVERITY_MAP = {
    "Extreme": "critical",
    "Severe": "warning",
    "Moderate": "advisory",
    "Minor": "info",
    "Unknown": "info",
}

# Approximate US state bounding boxes (lat_min, lat_max, lon_min, lon_max)
# Used to determine which states a route passes through.
_STATE_BOUNDS = {
    "AL": (30.2, 35.0, -88.5, -84.9),
    "AZ": (31.3, 37.0, -114.8, -109.0),
    "AR": (33.0, 36.5, -94.6, -89.6),
    "CA": (32.5, 42.0, -124.4, -114.1),
    "CO": (37.0, 41.0, -109.1, -102.0),
    "CT": (41.0, 42.1, -73.7, -71.8),
    "DE": (38.5, 39.8, -75.8, -75.0),
    "FL": (24.5, 31.0, -87.6, -80.0),
    "GA": (30.4, 35.0, -85.6, -80.8),
    "ID": (42.0, 49.0, -117.2, -111.0),
    "IL": (37.0, 42.5, -91.5, -87.5),
    "IN": (37.8, 41.8, -88.1, -84.8),
    "IA": (40.4, 43.5, -96.6, -90.1),
    "KS": (37.0, 40.0, -102.1, -94.6),
    "KY": (36.5, 39.1, -89.6, -81.9),
    "LA": (29.0, 33.0, -94.0, -89.0),
    "ME": (43.1, 47.5, -71.1, -67.0),
    "MD": (38.0, 39.7, -79.5, -75.0),
    "MA": (41.2, 42.9, -73.5, -69.9),
    "MI": (41.7, 48.3, -90.4, -82.4),
    "MN": (43.5, 49.4, -97.2, -89.5),
    "MS": (30.2, 35.0, -91.7, -88.1),
    "MO": (36.0, 40.6, -95.8, -89.1),
    "MT": (44.4, 49.0, -116.0, -104.0),
    "NE": (40.0, 43.0, -104.1, -95.3),
    "NV": (35.0, 42.0, -120.0, -114.0),
    "NH": (42.7, 45.3, -72.6, -70.7),
    "NJ": (38.9, 41.4, -75.6, -73.9),
    "NM": (31.3, 37.0, -109.1, -103.0),
    "NY": (40.5, 45.0, -79.8, -71.9),
    "NC": (33.8, 36.6, -84.3, -75.5),
    "ND": (45.9, 49.0, -104.0, -96.6),
    "OH": (38.4, 42.0, -84.8, -80.5),
    "OK": (33.6, 37.0, -103.0, -94.4),
    "OR": (42.0, 46.3, -124.6, -116.5),
    "PA": (39.7, 42.3, -80.5, -75.0),
    "RI": (41.1, 42.0, -71.9, -71.1),
    "SC": (32.0, 35.2, -83.4, -78.5),
    "SD": (42.5, 46.0, -104.1, -96.4),
    "TN": (35.0, 36.7, -90.3, -81.6),
    "TX": (25.8, 36.5, -106.6, -93.5),
    "UT": (37.0, 42.0, -114.1, -109.0),
    "VT": (42.7, 45.0, -73.4, -71.5),
    "VA": (36.5, 39.5, -83.7, -75.2),
    "WA": (45.5, 49.0, -124.8, -116.9),
    "WV": (37.2, 40.6, -82.6, -77.7),
    "WI": (42.5, 47.1, -92.9, -86.8),
    "WY": (41.0, 45.0, -111.1, -104.1),
    "DC": (38.8, 39.0, -77.1, -76.9),
}


@dataclass
class RouteAlert:
    """A single weather alert relevant to the transport route."""

    alert_id: str = ""
    severity: str = "info"  # critical, warning, advisory, info
    nws_severity: str = ""
    event: str = ""
    headline: str = ""
    description: str = ""
    area: str = ""
    onset: str = ""
    expires: str = ""
    urgency: str = ""
    waypoint_lat: Optional[float] = None
    waypoint_lon: Optional[float] = None
    source: str = "point"  # "point" or "state"


@dataclass
class RouteAlertsResult:
    """Aggregated weather alerts for a transport route."""

    alerts: list = field(default_factory=list)
    route_states: list = field(default_factory=list)
    clear_states: list = field(default_factory=list)
    alert_states: list = field(default_factory=list)
    waypoints_checked: int = 0
    cached: bool = False
    checked_at: str = ""
    ai_summary: Optional[str] = None
    risk_level: str = "low"  # low, medium, high
    optimal_pickup_suggestion: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "alerts": [asdict(a) if isinstance(a, RouteAlert) else a for a in self.alerts],
            "route_states": self.route_states,
            "clear_states": self.clear_states,
            "alert_states": self.alert_states,
            "waypoints_checked": self.waypoints_checked,
            "cached": self.cached,
            "checked_at": self.checked_at,
            "ai_summary": self.ai_summary,
            "risk_level": self.risk_level,
            "optimal_pickup_suggestion": self.optimal_pickup_suggestion,
        }


# =============================================================================
# Schema
# =============================================================================

def init_weather_schema():
    """Create weather_cache table if not exists."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS weather_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT UNIQUE NOT NULL,
                alerts_json TEXT,
                route_states TEXT,
                checked_at TIMESTAMP DEFAULT (datetime('now')),
                expires_at TIMESTAMP
            )
        """)
        conn.commit()


# =============================================================================
# Service
# =============================================================================

class WeatherService:
    """NWS weather alerts along transport route."""

    def __init__(self, http_client: Optional[httpx.Client] = None):
        self._client = http_client

    def _get_client(self) -> httpx.Client:
        if self._client:
            return self._client
        return httpx.Client(
            headers={"User-Agent": NWS_USER_AGENT},
            timeout=NWS_TIMEOUT,
        )

    # -------------------------------------------------------------------------
    # Main entry point
    # -------------------------------------------------------------------------

    def get_route_alerts(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        origin_state: str = "",
        dest_state: str = "",
        cache_key: Optional[str] = None,
    ) -> RouteAlertsResult:
        """Get weather alerts along a transport route.

        Args:
            origin_lat/lon: Pickup location coordinates.
            dest_lat/lon: Warehouse coordinates.
            origin_state/dest_state: Pickup and delivery states (for state-level queries).
            cache_key: Optional cache key (e.g., "route:75201:1"). If provided, checks cache first.

        Returns:
            RouteAlertsResult with deduplicated, categorized alerts.
        """
        # Check cache
        if cache_key:
            cached = self._get_cached(cache_key)
            if cached:
                return cached

        # Interpolate waypoints
        waypoints = self._interpolate_waypoints(origin_lat, origin_lon, dest_lat, dest_lon)

        # Determine route states
        route_states = self._get_route_states(waypoints, origin_state, dest_state)

        # Collect alerts from waypoints and states
        all_alerts = []
        client = self._get_client()
        owns_client = self._client is None

        try:
            # Query each waypoint
            for lat, lon in waypoints:
                point_alerts = self._fetch_point_alerts(client, lat, lon)
                all_alerts.extend(point_alerts)

            # Query each state along route
            for state in route_states:
                state_alerts = self._fetch_state_alerts(client, state)
                all_alerts.extend(state_alerts)
        finally:
            if owns_client:
                client.close()

        # Deduplicate and categorize
        unique_alerts = self._deduplicate_alerts(all_alerts)

        # Sort by severity (critical first)
        severity_order = {"critical": 0, "warning": 1, "advisory": 2, "info": 3}
        unique_alerts.sort(key=lambda a: severity_order.get(a.severity, 4))

        # Determine clear vs alert states
        alert_state_set = set()
        for a in unique_alerts:
            for s in route_states:
                if s in a.area:
                    alert_state_set.add(s)
        alert_states = sorted(alert_state_set)
        clear_states = sorted(set(route_states) - alert_state_set)

        now = datetime.now(timezone.utc).isoformat()

        # Generate AI summary if there are alerts
        ai_summary = None
        risk_level = "low"
        optimal_pickup = None
        if unique_alerts:
            ai_summary, risk_level, optimal_pickup = self._generate_ai_summary(
                unique_alerts, route_states, origin_state, dest_state
            )

        result = RouteAlertsResult(
            alerts=unique_alerts,
            route_states=route_states,
            clear_states=clear_states,
            alert_states=alert_states,
            waypoints_checked=len(waypoints),
            cached=False,
            checked_at=now,
            ai_summary=ai_summary,
            risk_level=risk_level,
            optimal_pickup_suggestion=optimal_pickup,
        )

        # Cache result
        if cache_key:
            self._cache_result(cache_key, result)

        return result

    # -------------------------------------------------------------------------
    # AI Summary
    # -------------------------------------------------------------------------

    def _generate_ai_summary(
        self,
        alerts: list[RouteAlert],
        route_states: list[str],
        origin_state: str = "",
        dest_state: str = "",
    ) -> tuple[Optional[str], str, Optional[str]]:
        """Generate AI-powered summary of weather alerts for transport route.

        Returns (summary_text, risk_level, optimal_pickup_suggestion).
        """
        # Determine risk level from alert severities
        severities = [a.severity for a in alerts]
        if "critical" in severities:
            risk_level = "high"
        elif "warning" in severities:
            risk_level = "medium"
        else:
            risk_level = "low"

        # Build alert summary for AI prompt
        alert_lines = []
        for a in alerts[:10]:  # Limit to 10 for token efficiency
            expires_info = f", expires {a.expires}" if a.expires else ""
            alert_lines.append(f"- {a.event} ({a.severity}): {a.headline}{expires_info}")
        alert_text = "\n".join(alert_lines)

        route_desc = " → ".join(route_states) if route_states else f"{origin_state} → {dest_state}"

        prompt = (
            f"You are a vehicle transport dispatcher assistant. Summarize these weather alerts "
            f"for a car carrier route ({route_desc}) in 2-3 concise sentences.\n\n"
            f"Alerts:\n{alert_text}\n\n"
            f"Include: (1) what conditions to expect, (2) impact on transport timing, "
            f"(3) if delay is recommended, suggest waiting until alerts expire.\n"
            f"Keep it practical for a truck driver. No markdown."
        )

        try:
            import os

            # Get API key from credential store or env var
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            try:
                from api.credential_store import get_credential_for_service
                cred = get_credential_for_service("anthropic")
                if cred and cred.get("api_key"):
                    api_key = cred["api_key"]
            except Exception:
                pass

            if not api_key:
                logger.debug("No Anthropic API key available for weather summary")
                return self._fallback_summary(alerts, risk_level), risk_level, None

            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = response.content[0].text.strip()

            # Determine optimal pickup suggestion from alert expiry times
            optimal_pickup = self._suggest_optimal_pickup(alerts)

            return summary, risk_level, optimal_pickup

        except Exception as e:
            logger.warning("AI weather summary failed: %s", e)
            return self._fallback_summary(alerts, risk_level), risk_level, None

    def _fallback_summary(self, alerts: list[RouteAlert], risk_level: str) -> str:
        """Generate a simple summary without AI when Anthropic is unavailable."""
        events = sorted(set(a.event for a in alerts))
        count = len(alerts)
        if risk_level == "high":
            return f"{count} active alert(s) including {', '.join(events[:3])}. Consider delaying pickup until conditions improve."
        elif risk_level == "medium":
            return f"{count} active alert(s): {', '.join(events[:3])}. Monitor conditions before dispatching."
        else:
            return f"{count} advisory alert(s): {', '.join(events[:3])}. Proceed with caution."

    def _suggest_optimal_pickup(self, alerts: list[RouteAlert]) -> Optional[str]:
        """Suggest when to pick up based on alert expiry times."""
        expiry_times = []
        for a in alerts:
            if a.expires and a.severity in ("critical", "warning"):
                try:
                    exp = datetime.fromisoformat(a.expires.replace("Z", "+00:00"))
                    expiry_times.append(exp)
                except (ValueError, TypeError):
                    pass

        if not expiry_times:
            return None

        latest_expiry = max(expiry_times)
        # Add 2-hour buffer after alerts expire
        suggested = latest_expiry + timedelta(hours=2)
        return suggested.strftime("%Y-%m-%d %H:%M UTC")

    # -------------------------------------------------------------------------
    # Waypoint interpolation
    # -------------------------------------------------------------------------

    def _interpolate_waypoints(
        self, lat1: float, lon1: float, lat2: float, lon2: float, n: int = 5
    ) -> list[tuple[float, float]]:
        """Create N evenly-spaced points along great circle route.

        Includes origin and destination as first and last points.
        Returns list of (lat, lon) tuples.
        """
        if n < 2:
            n = 2

        waypoints = []
        for i in range(n):
            t = i / (n - 1)
            lat = lat1 + t * (lat2 - lat1)
            lon = lon1 + t * (lon2 - lon1)
            waypoints.append((round(lat, 4), round(lon, 4)))

        return waypoints

    # -------------------------------------------------------------------------
    # State estimation from coordinates
    # -------------------------------------------------------------------------

    def _get_route_states(
        self,
        waypoints: list[tuple[float, float]],
        origin_state: str = "",
        dest_state: str = "",
    ) -> list[str]:
        """Determine which US states the route passes through.

        Uses approximate bounding boxes. Always includes origin and dest states.
        """
        states = set()

        # Always include known states
        if origin_state:
            states.add(origin_state.upper())
        if dest_state:
            states.add(dest_state.upper())

        # Check each waypoint against state bounding boxes
        for lat, lon in waypoints:
            for state, (lat_min, lat_max, lon_min, lon_max) in _STATE_BOUNDS.items():
                if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                    states.add(state)

        return sorted(states)

    # -------------------------------------------------------------------------
    # NWS API calls
    # -------------------------------------------------------------------------

    def _fetch_point_alerts(
        self, client: httpx.Client, lat: float, lon: float
    ) -> list[RouteAlert]:
        """GET /alerts/active?point={lat},{lon} — alerts near a specific point."""
        try:
            resp = client.get(
                f"{NWS_BASE}/alerts/active",
                params={"point": f"{lat},{lon}"},
            )
            if resp.status_code != 200:
                logger.warning("NWS point alert query failed: %s %s", resp.status_code, resp.text[:200])
                return []

            features = resp.json().get("features", [])
            alerts = []
            for f in features:
                alert = self._parse_alert(f, lat, lon, source="point")
                if alert:
                    alerts.append(alert)
            return alerts

        except Exception as e:
            logger.warning("NWS point alert error at (%s, %s): %s", lat, lon, e)
            return []

    def _fetch_state_alerts(
        self, client: httpx.Client, state_code: str
    ) -> list[RouteAlert]:
        """GET /alerts/active?area={state} — active alerts for an entire state.

        Filters to transport-relevant alert types only.
        """
        try:
            resp = client.get(
                f"{NWS_BASE}/alerts/active",
                params={"area": state_code},
            )
            if resp.status_code != 200:
                logger.warning("NWS state alert query failed for %s: %s", state_code, resp.status_code)
                return []

            features = resp.json().get("features", [])
            alerts = []
            for f in features:
                alert = self._parse_alert(f, source="state")
                if alert:
                    alerts.append(alert)
            return alerts

        except Exception as e:
            logger.warning("NWS state alert error for %s: %s", state_code, e)
            return []

    def _parse_alert(
        self,
        feature: dict,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        source: str = "point",
    ) -> Optional[RouteAlert]:
        """Parse a GeoJSON feature into a RouteAlert.

        Filters out non-transport-relevant alert types.
        """
        props = feature.get("properties", {})
        event = props.get("event", "")

        # Filter: only transport-relevant alerts
        if event not in TRANSPORT_ALERT_TYPES:
            return None

        nws_severity = props.get("severity", "Unknown")

        return RouteAlert(
            alert_id=props.get("id", ""),
            severity=SEVERITY_MAP.get(nws_severity, "info"),
            nws_severity=nws_severity,
            event=event,
            headline=props.get("headline", ""),
            description=props.get("description", "")[:500],
            area=props.get("areaDesc", ""),
            onset=props.get("onset", ""),
            expires=props.get("expires", ""),
            urgency=props.get("urgency", ""),
            waypoint_lat=lat,
            waypoint_lon=lon,
            source=source,
        )

    # -------------------------------------------------------------------------
    # Deduplication
    # -------------------------------------------------------------------------

    def _deduplicate_alerts(self, alerts: list[RouteAlert]) -> list[RouteAlert]:
        """Remove duplicate alerts (same NWS alert ID seen at multiple waypoints)."""
        seen = {}
        for alert in alerts:
            if alert.alert_id not in seen:
                seen[alert.alert_id] = alert
        return list(seen.values())

    # -------------------------------------------------------------------------
    # Cache
    # -------------------------------------------------------------------------

    def _get_cached(self, cache_key: str) -> Optional[RouteAlertsResult]:
        """Check cache for unexpired result."""
        try:
            with get_connection() as conn:
                row = conn.execute(
                    "SELECT alerts_json, route_states, checked_at, expires_at FROM weather_cache "
                    "WHERE cache_key = ? AND expires_at > datetime('now')",
                    (cache_key,),
                ).fetchone()

            if not row:
                return None

            alerts_data = json.loads(row[0]) if row[0] else []
            route_states = json.loads(row[1]) if row[1] else []
            checked_at = row[2] or ""

            alerts = [RouteAlert(**a) for a in alerts_data]

            # Determine alert/clear states from cached data
            alert_state_set = set()
            for a in alerts:
                for s in route_states:
                    if s in a.area:
                        alert_state_set.add(s)

            return RouteAlertsResult(
                alerts=alerts,
                route_states=route_states,
                clear_states=sorted(set(route_states) - alert_state_set),
                alert_states=sorted(alert_state_set),
                waypoints_checked=0,
                cached=True,
                checked_at=checked_at,
            )
        except Exception as e:
            logger.warning("Weather cache read error: %s", e)
            return None

    def _cache_result(self, cache_key: str, result: RouteAlertsResult):
        """Store result in cache with 1-hour TTL."""
        try:
            alerts_json = json.dumps(
                [asdict(a) for a in result.alerts]
            )
            route_states_json = json.dumps(result.route_states)
            now = datetime.now(timezone.utc)
            expires = now + timedelta(seconds=WEATHER_CACHE_TTL)

            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO weather_cache (cache_key, alerts_json, route_states, checked_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(cache_key) DO UPDATE SET "
                    "alerts_json=excluded.alerts_json, route_states=excluded.route_states, "
                    "checked_at=excluded.checked_at, expires_at=excluded.expires_at",
                    (cache_key, alerts_json, route_states_json,
                     now.strftime("%Y-%m-%d %H:%M:%S"), expires.strftime("%Y-%m-%d %H:%M:%S")),
                )
                conn.commit()
        except Exception as e:
            logger.warning("Weather cache write error: %s", e)
