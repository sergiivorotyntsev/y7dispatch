"""
Central Dispatch Market Intelligence API Client

Provides recommended pricing for vehicle transport based on:
- Pickup and dropoff locations
- Vehicle details (year, make, model, type)
- Trailer type (open/enclosed)

API Requirements:
- POST /market-intelligence/list-prices
- Content-Type: application/vnd.coxauto.v1+json
- stops must contain 2 stops with sequential stopNumber (1, 2)
- vehicles must have pickupStopNumber and dropOffStopNumber
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


@dataclass
class MIStop:
    """Stop data for Market Intelligence request."""

    stop_number: int
    city: str
    state: str
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to MI API format."""
        result = {
            "stopNumber": self.stop_number,
            "city": self.city,
            "state": self.state,
        }
        if self.postal_code:
            result["postalCode"] = self.postal_code
        if self.latitude is not None and self.longitude is not None:
            result["latitude"] = self.latitude
            result["longitude"] = self.longitude
        return result


@dataclass
class MIVehicle:
    """Vehicle data for Market Intelligence request."""

    vin: Optional[str] = None
    year: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    vehicle_type: str = "SEDAN"  # SEDAN, SUV, TRUCK, VAN, etc.
    is_operable: bool = True
    pickup_stop_number: int = 1
    dropoff_stop_number: int = 2

    def to_dict(self) -> dict[str, Any]:
        """Convert to MI API format."""
        result = {
            "vehicleType": self.vehicle_type,
            "isOperable": self.is_operable,
            "pickupStopNumber": self.pickup_stop_number,
            "dropOffStopNumber": self.dropoff_stop_number,
        }
        if self.vin:
            result["vin"] = self.vin
        if self.year:
            result["year"] = self.year
        if self.make:
            result["make"] = self.make
        if self.model:
            result["model"] = self.model
        return result


@dataclass
class MIPriceQuote:
    """Price quote response from Market Intelligence."""

    suggested_price: float
    low_price: Optional[float] = None
    high_price: Optional[float] = None
    confidence: float = 0.0
    source: str = "MARKET_INTELLIGENCE"
    request_id: Optional[str] = None
    response_raw: Optional[dict] = None
    avg_dispatch: Optional[float] = None
    avg_listing: Optional[float] = None
    spread: Optional[float] = None
    distance_miles: Optional[float] = None
    data_points: int = 0
    raw_items: Optional[list] = None
    error: Optional[str] = None


@dataclass
class MIClientConfig:
    """Configuration for Market Intelligence client."""

    base_url: str = "https://api.centraldispatch.com"
    api_key: Optional[str] = None
    timeout_seconds: float = 15.0
    max_retries: int = 2


class MarketIntelligenceClient:
    """
    Client for Central Dispatch Market Intelligence API.

    Usage:
        client = MarketIntelligenceClient(config)
        quote = client.get_list_prices(
            stops=[pickup_stop, dropoff_stop],
            vehicles=[vehicle],
            is_enclosed=False,
        )
    """

    def __init__(self, config: MIClientConfig = None, bearer_token: Optional[str] = None):
        self.config = config or MIClientConfig()
        self._bearer_token = bearer_token
        self._client = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
                headers=self._get_headers(),
            )
        return self._client

    def _get_headers(self) -> dict[str, str]:
        """Get request headers including auth."""
        headers = {
            "Content-Type": "application/vnd.coxauto.v1+json",
            "Accept": "application/vnd.coxauto.v1+json",
        }
        token = self._bearer_token or self.config.api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _compute_payload_hash(self, payload: dict) -> str:
        """Compute hash of payload for logging/caching."""
        payload_str = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(payload_str.encode()).hexdigest()[:16]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(httpx.HTTPStatusError),
    )
    def get_list_prices(
        self,
        stops: list[MIStop],
        vehicles: list[MIVehicle],
        is_enclosed: bool = False,
        limit: int = 1,
    ) -> Optional[MIPriceQuote]:
        """
        Get recommended list prices from Market Intelligence.

        Args:
            stops: List of stops (must have exactly 2 with stopNumber 1 and 2)
            vehicles: List of vehicles (at least 1)
            is_enclosed: Whether enclosed trailer is required
            limit: Number of price suggestions to return

        Returns:
            MIPriceQuote with suggested price, or None on error

        Raises:
            ValueError: If stops/vehicles don't meet requirements
        """
        # Validate inputs
        if len(stops) != 2:
            raise ValueError(f"Exactly 2 stops required, got {len(stops)}")

        stop_numbers = {s.stop_number for s in stops}
        if stop_numbers != {1, 2}:
            raise ValueError(f"Stops must have stopNumber 1 and 2, got {stop_numbers}")

        if not vehicles:
            raise ValueError("At least 1 vehicle required")

        for v in vehicles:
            if v.pickup_stop_number not in stop_numbers:
                raise ValueError(f"Vehicle pickupStopNumber {v.pickup_stop_number} not in stops")
            if v.dropoff_stop_number not in stop_numbers:
                raise ValueError(f"Vehicle dropOffStopNumber {v.dropoff_stop_number} not in stops")

        # Build request payload
        payload = {
            "stops": [s.to_dict() for s in stops],
            "vehicles": [v.to_dict() for v in vehicles],
            "isEnclosed": is_enclosed,
            "limit": limit,
        }

        payload_hash = self._compute_payload_hash(payload)
        request_id = f"mi-{int(time.time())}-{payload_hash}"

        logger.info(
            f"MI API request: {request_id}, "
            f"pickup={stops[0].city},{stops[0].state}, "
            f"dropoff={stops[1].city},{stops[1].state}"
        )

        try:
            response = self.client.post(
                "/market-intelligence/list-prices",
                json=payload,
            )

            logger.info(f"MI API response: {request_id}, status={response.status_code}")

            if response.status_code == 200:
                data = response.json()
                return self._parse_response(data, request_id)

            elif response.status_code == 403:
                logger.warning(f"MI API 403 (no subscription): {request_id}")
                return MIPriceQuote(
                    suggested_price=0,
                    source="CD_MARKET_INTELLIGENCE",
                    error="Market Intelligence API not available — requires Price Check Plus subscription",
                    request_id=request_id,
                )

            elif response.status_code == 429:
                # Rate limited - let retry handle it
                logger.warning(f"MI API rate limited: {request_id}")
                raise httpx.HTTPStatusError(
                    "Rate limited",
                    request=response.request,
                    response=response,
                )

            else:
                body_text = response.text[:1000]
                logger.error(
                    f"MI API error: {request_id}, "
                    f"status={response.status_code}, "
                    f"body={body_text}"
                )
                return MIPriceQuote(
                    suggested_price=0,
                    source="CD_MARKET_INTELLIGENCE",
                    error=f"CD MI API returned HTTP {response.status_code}: {body_text}",
                    request_id=request_id,
                )

        except httpx.TimeoutException:
            logger.error(f"MI API timeout: {request_id}")
            return MIPriceQuote(
                suggested_price=0,
                source="CD_MARKET_INTELLIGENCE",
                error=f"CD MI API timeout after {self.config.timeout_seconds}s",
                request_id=request_id,
            )
        except httpx.RequestError as e:
            logger.error(f"MI API request error: {request_id}, {e}")
            return MIPriceQuote(
                suggested_price=0,
                source="CD_MARKET_INTELLIGENCE",
                error=f"CD MI API request error: {e}",
                request_id=request_id,
            )

    def _parse_response(self, data: dict, request_id: str) -> Optional[MIPriceQuote]:
        """Parse MI API response into MIPriceQuote.

        Handles the CD Price Check Plus response format:
        {
            "items": [
                {
                    "listingPrice": 750.00, "dispatchPrice": 700.00,
                    "listingDistance": 882, "dispatchDistance": 882, ...
                }
            ],
            "count": 5
        }

        Also handles legacy format: {"prices": [{"price": 450}]}
        """
        try:
            # CD Price Check Plus format: items array
            items = data.get("items", [])

            # Legacy fallback: prices array
            if not items:
                prices = data.get("prices", [])
                if prices:
                    price_data = prices[0]
                    suggested = price_data.get("price") or price_data.get("suggestedPrice")
                    if suggested is not None:
                        return MIPriceQuote(
                            suggested_price=float(suggested),
                            low_price=price_data.get("lowPrice"),
                            high_price=price_data.get("highPrice"),
                            confidence=price_data.get("confidence", 0.8),
                            source="CD_MARKET_INTELLIGENCE",
                            request_id=request_id,
                            response_raw=data,
                            data_points=len(prices),
                            raw_items=prices,
                        )

            if not items:
                # Log the actual response so we can see what CD returned
                logger.warning(f"MI API returned no items: {request_id}, keys={list(data.keys())}, data={json.dumps(data)[:500]}")
                return MIPriceQuote(
                    suggested_price=0,
                    source="CD_MARKET_INTELLIGENCE",
                    error=f"CD MI API returned 200 but no pricing items. Response keys: {list(data.keys())}",
                    request_id=request_id,
                    response_raw=data,
                )

            # Calculate averages from items
            dispatch_prices = [i["dispatchPrice"] for i in items if i.get("dispatchPrice")]
            listing_prices = [i["listingPrice"] for i in items if i.get("listingPrice")]
            distances = [i.get("listingDistance") or i.get("dispatchDistance") for i in items
                         if i.get("listingDistance") or i.get("dispatchDistance")]

            avg_dispatch = sum(dispatch_prices) / len(dispatch_prices) if dispatch_prices else None
            avg_listing = sum(listing_prices) / len(listing_prices) if listing_prices else None
            avg_distance = sum(distances) / len(distances) if distances else None

            spread = (avg_listing - avg_dispatch) if avg_listing and avg_dispatch else None

            # Suggested price = midpoint of dispatch and listing averages
            if avg_dispatch and avg_listing:
                suggested_price = avg_dispatch + (spread * 0.5)
            elif avg_dispatch:
                suggested_price = avg_dispatch
            elif avg_listing:
                suggested_price = avg_listing
            else:
                logger.warning(f"MI API no usable prices: {request_id}, items={items}")
                return MIPriceQuote(
                    suggested_price=0,
                    source="CD_MARKET_INTELLIGENCE",
                    error=f"CD MI API returned {len(items)} items but no dispatch or listing prices",
                    request_id=request_id,
                    response_raw=data,
                )

            low_price = min(dispatch_prices) if dispatch_prices else None
            high_price = max(listing_prices) if listing_prices else None

            return MIPriceQuote(
                suggested_price=round(suggested_price, 2),
                low_price=low_price,
                high_price=high_price,
                confidence=min(1.0, len(items) / 5.0),
                source="CD_MARKET_INTELLIGENCE",
                request_id=request_id,
                response_raw=data,
                avg_dispatch=round(avg_dispatch, 2) if avg_dispatch else None,
                avg_listing=round(avg_listing, 2) if avg_listing else None,
                spread=round(spread, 2) if spread else None,
                distance_miles=round(avg_distance, 1) if avg_distance else None,
                data_points=len(items),
                raw_items=items,
            )

        except (KeyError, TypeError, ValueError) as e:
            logger.error(f"MI API parse error: {request_id}, {e}, data={data}")
            return MIPriceQuote(
                suggested_price=0,
                source="CD_MARKET_INTELLIGENCE",
                error=f"Failed to parse CD MI response: {type(e).__name__}: {e}",
                request_id=request_id,
                response_raw=data,
            )

    def close(self):
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None


# =============================================================================
# PRICING SERVICE
# =============================================================================


@dataclass
class PricingRequest:
    """Request for price recommendation."""

    pickup_city: str
    pickup_state: str
    pickup_postal_code: Optional[str] = None
    delivery_city: str = ""
    delivery_state: str = ""
    delivery_postal_code: Optional[str] = None
    vehicle_vin: Optional[str] = None
    vehicle_year: Optional[int] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_type: str = "SEDAN"
    is_operable: bool = True
    is_enclosed: bool = False


class PricingService:
    """
    Service for getting recommended transport prices.

    Uses Market Intelligence API when data is available,
    with fallback to auction profile defaults.
    """

    def __init__(self, mi_client: MarketIntelligenceClient = None):
        self.mi_client = mi_client or MarketIntelligenceClient()

    def get_recommended_price(
        self,
        request: PricingRequest,
    ) -> Optional[MIPriceQuote]:
        """
        Get recommended price for a transport.

        Args:
            request: Pricing request with locations and vehicle info

        Returns:
            MIPriceQuote or None if unavailable
        """
        # Check minimum requirements
        if not request.pickup_city or not request.pickup_state:
            logger.warning("Pricing requires pickup city and state")
            return None

        if not request.delivery_city or not request.delivery_state:
            logger.warning("Pricing requires delivery city and state")
            return None

        # Build MI request
        pickup_stop = MIStop(
            stop_number=1,
            city=request.pickup_city,
            state=request.pickup_state,
            postal_code=request.pickup_postal_code,
        )

        dropoff_stop = MIStop(
            stop_number=2,
            city=request.delivery_city,
            state=request.delivery_state,
            postal_code=request.delivery_postal_code,
        )

        vehicle = MIVehicle(
            vin=request.vehicle_vin,
            year=request.vehicle_year,
            make=request.vehicle_make,
            model=request.vehicle_model,
            vehicle_type=request.vehicle_type,
            is_operable=request.is_operable,
        )

        try:
            return self.mi_client.get_list_prices(
                stops=[pickup_stop, dropoff_stop],
                vehicles=[vehicle],
                is_enclosed=request.is_enclosed,
            )
        except Exception as e:
            logger.error(f"Pricing service error: {e}")
            return None


# Module-level singleton
_pricing_service: Optional[PricingService] = None


def get_pricing_service() -> PricingService:
    """Get the pricing service singleton."""
    global _pricing_service
    if _pricing_service is None:
        _pricing_service = PricingService()
    return _pricing_service


def create_authenticated_mi_client() -> MarketIntelligenceClient:
    """Create an MI client with OAuth2 Bearer token from credential store.

    Gets a fresh token from the CDClient's OAuth2 flow using the same
    credentials stored in the credential store.

    Raises Exception if token acquisition fails so the caller can surface it.
    """
    from api.cd_client import CDClient

    cd = CDClient()
    if not cd.client_id or not cd.client_secret:
        raise ValueError(
            "CD API credentials not configured. Go to Settings > Central Dispatch and enter client_id/client_secret. "
            "Ensure 'market_intelligence_api' scope is included."
        )

    token = cd._get_bearer_token()
    logger.info("MI client created with OAuth2 Bearer token (token=%s...)", token[:20] if token else "None")
    return MarketIntelligenceClient(bearer_token=token)
