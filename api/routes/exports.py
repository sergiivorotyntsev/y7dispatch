"""
Export API Routes

Export data to Central Dispatch API V2.
Includes:
- Field registry endpoint (single source of truth)
- Single and batch posting with ETag support
- Throttling with exponential backoff
- Production corrections → training ingestion
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Throttling configuration for CD API
CD_MAX_CONCURRENT_REQUESTS = 3  # Max concurrent requests to CD API
CD_RETRY_ATTEMPTS = 3  # Number of retry attempts on failure
CD_BACKOFF_BASE = 2.0  # Base for exponential backoff (seconds)
CD_BACKOFF_MAX = 30.0  # Maximum backoff time (seconds)

# Semaphore for rate limiting
_cd_semaphore: Optional[asyncio.Semaphore] = None


def get_cd_semaphore() -> asyncio.Semaphore:
    """Get or create the CD API rate limiting semaphore."""
    global _cd_semaphore
    if _cd_semaphore is None:
        _cd_semaphore = asyncio.Semaphore(CD_MAX_CONCURRENT_REQUESTS)
    return _cd_semaphore


from api.listing_fields import (
    get_registry,
)
from api.models import (
    AuctionTypeRepository,
    DocumentRepository,
    ExportJobRepository,
    ExtractionRunRepository,
    ReviewItemRepository,
)

router = APIRouter(prefix="/api/exports", tags=["Exports"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class CDExportRequest(BaseModel):
    """Request to export to Central Dispatch."""

    run_ids: list[int] = Field(..., description="Extraction run IDs to export")
    dry_run: bool = Field(True, description="Preview only, don't actually send")
    sandbox: bool = Field(True, description="Use CD sandbox environment")


class CDPayloadPreview(BaseModel):
    """Preview of a CD API V2 payload."""

    dispatch_id: str
    run_id: int
    document_filename: Optional[str] = None
    payload: dict
    validation_errors: list[str] = []
    is_valid: bool = True


class CDExportResponse(BaseModel):
    """Response after CD export."""

    job_id: Optional[int] = None
    status: str
    previews: list[CDPayloadPreview] = []
    exported_count: int = 0
    failed_count: int = 0
    message: str


class ExportJobResponse(BaseModel):
    """Export job status."""

    id: int
    status: str
    target: str = "central_dispatch"
    payload_json: Optional[dict] = None
    response_json: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None

    class Config:
        from_attributes = True


class ExportJobListResponse(BaseModel):
    """List of export jobs."""

    items: list[ExportJobResponse]
    total: int


# =============================================================================
# CD PAYLOAD BUILDER
# =============================================================================


def build_cd_payload(run_id: int, warehouse_code: str = None) -> tuple[dict, list[str]]:
    """
    Build Central Dispatch API V2 payload from extraction run.

    Uses FieldResolver (M3.P0.2) to apply precedence chain:
    USER_OVERRIDE > WAREHOUSE_CONST > AUCTION_CONST > EXTRACTED > DEFAULT

    Args:
        run_id: Extraction run ID
        warehouse_code: Optional warehouse code for constants

    Returns (payload, validation_errors).
    """
    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        return {}, ["Extraction run not found"]

    doc = DocumentRepository.get_by_id(run.document_id)
    if not doc:
        return {}, ["Document not found"]

    at = AuctionTypeRepository.get_by_id(run.auction_type_id)
    if not at:
        return {}, ["Auction type not found"]

    # Get review items (with corrections applied)
    items = ReviewItemRepository.get_by_run(run_id)
    user_overrides = {}  # User corrections from review
    extracted_values = {}  # Original extracted values

    for item in items:
        if not item.export_field:
            continue
        # Separate user corrections from extracted values
        if item.corrected_value:
            user_overrides[item.source_key] = item.corrected_value
        if item.predicted_value:
            extracted_values[item.source_key] = item.predicted_value

    # Also get extracted values from outputs_json
    if run.outputs_json:
        outputs = (
            run.outputs_json if isinstance(run.outputs_json, dict) else json.loads(run.outputs_json)
        )
        for key, value in outputs.items():
            if key not in extracted_values and value is not None:
                extracted_values[key] = value
        # Check for warehouse_id in outputs
        if not warehouse_code and outputs.get("warehouse_id"):
            # Try to get warehouse code from warehouse_id
            from api.database import get_connection

            with get_connection() as conn:
                wh_row = conn.execute(
                    "SELECT code FROM warehouses WHERE id = ?", (outputs.get("warehouse_id"),)
                ).fetchone()
                if wh_row:
                    warehouse_code = wh_row["code"]

    # =================================================================
    # M3.P0.2: FIELD RESOLUTION WITH PRECEDENCE
    # Use FieldResolver to combine values from multiple sources
    # =================================================================
    from extractors.field_resolver import FieldResolver, ResolutionContext

    resolver = FieldResolver()
    context = ResolutionContext(
        auction_code=at.code,
        warehouse_code=warehouse_code,
        user_overrides=user_overrides,
        default_values={
            # Defaults for CD payload fields
            "trailer_type": "OPEN",
            "dropoff_country": "US",
            "pickup_country": "US",
        },
    )

    # Resolve all fields with precedence
    resolved = resolver.resolve_all(extracted_values, context)

    # Build item_map from resolved values (for backward compatibility)
    item_map = {}
    field_sources_info = {}  # Track where each field value came from
    for field_key, resolved_field in resolved.items():
        if resolved_field.value is not None:
            item_map[field_key] = resolved_field.value
            field_sources_info[field_key] = resolved_field.source.value

    errors = []
    warnings = []

    # Build dispatch_id (externalId) - CD API limit: 50 characters
    dispatch_id = f"DC-{datetime.now().strftime('%Y%m%d')}-{at.code}-{run.uuid[:8].upper()}"
    if len(dispatch_id) > 50:
        original_len = len(dispatch_id)
        dispatch_id = dispatch_id[:50]
        warnings.append(f"externalId truncated from {original_len} to 50 characters")
        logger.warning(f"externalId truncated: {original_len} -> 50 chars for run {run_id}")

    # Build partnerReferenceId for retry-safe POST (CD API limit: 50 chars)
    partner_ref_id = f"CD-RUN-{run_id}"
    if len(partner_ref_id) > 50:
        partner_ref_id = partner_ref_id[:50]

    # Get field values with defaults
    def get_field(key: str, default=None):
        return item_map.get(key, default)

    # Validate required fields
    required = ["vehicle_vin", "pickup_address", "pickup_city", "pickup_state", "pickup_zip"]
    for field in required:
        if not get_field(field):
            errors.append(f"Missing required field: {field}")

    # Validate VIN
    vin = get_field("vehicle_vin", "")
    if vin and len(vin) != 17:
        errors.append(f"VIN must be 17 characters, got {len(vin)}")

    # Calculate dates
    available_date = datetime.now().strftime("%Y-%m-%d")
    expiration_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    # Determine trailer type
    is_inop = get_field("vehicle_is_inoperable", False)
    if isinstance(is_inop, str):
        is_inop = is_inop.lower() in ("true", "yes", "1", "inoperable")
    trailer_type = "OPEN"

    # Build stops
    pickup_stop = {
        "stopNumber": 1,
        "locationName": get_field("pickup_name") or f"{at.name} Pickup",
        "address": get_field("pickup_address", ""),
        "city": get_field("pickup_city", ""),
        "state": get_field("pickup_state", ""),
        "postalCode": get_field("pickup_zip", ""),
        "country": "US",
        "locationType": "AUCTION",
    }

    # Build delivery stop (M3.P0.2: uses resolved values from FieldResolver)
    # Delivery address is populated from warehouse constants when warehouse is selected
    dropoff_stop = {
        "stopNumber": 2,
        "locationName": get_field("delivery_name") or get_field("dropoff_name", "Warehouse"),
        "address": get_field("delivery_address") or get_field("dropoff_address", "TBD"),
        "city": get_field("delivery_city") or get_field("dropoff_city", "TBD"),
        "state": get_field("delivery_state") or get_field("dropoff_state", "TX"),
        "postalCode": get_field("delivery_zip") or get_field("dropoff_zip", "00000"),
        "country": "US",
        "locationType": "BUSINESS",
    }

    # Add delivery phone and contact if available
    delivery_phone = get_field("delivery_phone")
    if delivery_phone:
        dropoff_stop["phone"] = delivery_phone

    delivery_contact = get_field("delivery_contact")
    if delivery_contact:
        dropoff_stop["contactName"] = delivery_contact

    # Build vehicle
    vehicle = {
        "pickupStopNumber": 1,
        "dropoffStopNumber": 2,
        "vin": get_field("vehicle_vin", ""),
        "year": int(get_field("vehicle_year", 0) or 0),
        "make": get_field("vehicle_make", ""),
        "model": get_field("vehicle_model", ""),
        "isInoperable": is_inop,
    }

    if get_field("vehicle_lot"):
        vehicle["lotNumber"] = str(get_field("vehicle_lot"))

    # Build price
    total_amount = get_field("total_amount")
    try:
        price_total = float(total_amount) if total_amount else 0.0
    except (ValueError, TypeError):
        price_total = 0.0

    if price_total <= 0:
        price_total = 450.00  # Default price

    price = {
        "total": price_total,
        "cod": {
            "amount": price_total,
            "paymentMethod": "CASH",
            "paymentLocation": "DELIVERY",
        },
    }

    # Build notes
    notes_parts = []
    if get_field("reference_id"):
        notes_parts.append(f"Ref: {get_field('reference_id')}")
    if get_field("buyer_id"):
        notes_parts.append(f"Buyer: {get_field('buyer_id')}")
    notes = "; ".join(notes_parts) if notes_parts else ""

    # Add warehouse special instructions (from warehouse constants)
    transportation_notes = get_field("transportation_release_notes") or get_field(
        "special_instructions"
    )
    if transportation_notes:
        if notes:
            notes = f"{notes}; {transportation_notes}"
        else:
            notes = transportation_notes

    # Full payload (CD Listings API V2)
    payload = {
        "externalId": dispatch_id,
        "partnerReferenceId": partner_ref_id,  # For retry-safe POST (duplicate detection)
        "trailerType": trailer_type,
        "hasInOpVehicle": is_inop,
        "availableDate": available_date,
        "expirationDate": expiration_date,
        "transportationReleaseNotes": notes,
        "price": price,
        "stops": [pickup_stop, dropoff_stop],
        "vehicles": [vehicle],
        "marketplaces": [
            {
                "marketplaceId": 12345,  # Placeholder
                "digitalOffersEnabled": True,
                "searchable": True,
                "offersAutoAcceptEnabled": False,
            }
        ],
    }

    # Include warnings in errors (prefixed) for visibility
    for w in warnings:
        errors.append(f"[WARNING] {w}")

    return payload, errors


def _init_cd_listings_table():
    """Initialize the cd_listings table for tracking CD listing IDs and ETags."""
    from api.database import get_connection

    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cd_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL UNIQUE,
                cd_listing_id TEXT NOT NULL,
                etag TEXT,
                external_id TEXT,
                sandbox BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES extraction_runs(id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cd_listings_run_id ON cd_listings(run_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_cd_listings_cd_id ON cd_listings(cd_listing_id)
        """)
        conn.commit()


def get_cd_listing_info(run_id: int) -> Optional[dict[str, Any]]:
    """Get stored CD listing info (listing_id, etag) for a run."""
    from api.database import get_connection

    _init_cd_listings_table()

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM cd_listings WHERE run_id = ?", (run_id,)).fetchone()

    return dict(row) if row else None


def save_cd_listing_info(
    run_id: int,
    cd_listing_id: str,
    etag: Optional[str] = None,
    external_id: Optional[str] = None,
    sandbox: bool = True,
):
    """Save or update CD listing info after successful POST/PUT."""
    from api.database import get_connection

    _init_cd_listings_table()

    with get_connection() as conn:
        # Upsert: update if exists, insert if not
        existing = conn.execute("SELECT id FROM cd_listings WHERE run_id = ?", (run_id,)).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE cd_listings
                SET cd_listing_id = ?, etag = ?, external_id = ?,
                    sandbox = ?, updated_at = CURRENT_TIMESTAMP
                WHERE run_id = ?
            """,
                (cd_listing_id, etag, external_id, sandbox, run_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO cd_listings (run_id, cd_listing_id, etag, external_id, sandbox)
                VALUES (?, ?, ?, ?, ?)
            """,
                (run_id, cd_listing_id, etag, external_id, sandbox),
            )

        conn.commit()


def get_cd_listing_etag(
    cd_listing_id: str, sandbox: bool = True
) -> tuple[bool, Optional[str], dict]:
    """
    GET a listing from CD to retrieve current ETag.

    CD API V2 endpoint: GET /listings/id/{id}

    Returns (success, etag, response_data).
    Required before PUT/update operations (If-Match header).
    """
    import requests

    if sandbox:
        base_url = "https://api.sandbox.centraldispatch.com"
    else:
        base_url = "https://api.centraldispatch.com"

    # CD API V2 uses /listings/id/{id} for GET by ID
    endpoint = f"{base_url}/listings/id/{cd_listing_id}"

    headers = {
        "Accept": "application/vnd.coxauto.v2+json",
        # Note: Real implementation would include auth
        # "Authorization": f"Bearer {token}"
    }

    try:
        logger.info(f"GET {endpoint} to retrieve ETag")
        response = requests.get(
            endpoint,
            headers=headers,
            timeout=30,
        )

        if response.status_code == 200:
            etag = response.headers.get("ETag")
            logger.info(f"GET success, ETag: {etag}")
            return True, etag, response.json()
        else:
            logger.warning(f"GET failed: {response.status_code} - {response.text[:200]}")
            return (
                False,
                None,
                {
                    "status_code": response.status_code,
                    "error": response.text,
                },
            )

    except requests.RequestException as e:
        logger.error(f"GET request error: {e}")
        return False, None, {"error": str(e)}


def find_listing_by_partner_ref(partner_ref_id: str, sandbox: bool = True) -> Optional[str]:
    """
    Search for existing listing by partnerReferenceId.

    Used for retry-safe POST to detect if listing was already created.

    Returns cd_listing_id if found, None otherwise.
    """
    import requests

    if sandbox:
        base_url = "https://api.sandbox.centraldispatch.com"
    else:
        base_url = "https://api.centraldispatch.com"

    # CD API V2: search listings by partnerReferenceId
    endpoint = f"{base_url}/listings"
    params = {"partnerReferenceId": partner_ref_id}

    headers = {
        "Accept": "application/vnd.coxauto.v2+json",
    }

    try:
        logger.info(f"Searching for listing with partnerReferenceId: {partner_ref_id}")
        response = requests.get(
            endpoint,
            params=params,
            headers=headers,
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            listings = data.get("listings") or data.get("items") or []
            if listings:
                listing_id = listings[0].get("id") or listings[0].get("listingId")
                logger.info(f"Found existing listing: {listing_id}")
                return listing_id
        return None

    except requests.RequestException as e:
        logger.warning(f"Search request error: {e}")
        return None


def send_to_cd(
    payload: dict,
    sandbox: bool = True,
    cd_listing_id: Optional[str] = None,
    etag: Optional[str] = None,
) -> tuple[bool, dict, Optional[str], Optional[str]]:
    """
    Send payload to Central Dispatch API V2.

    CD API V2 endpoints:
    - POST /listings (create) → returns Location header with new listing URL
    - PUT /listings/id/{id} (update) → requires If-Match header, returns 204

    Args:
        payload: The listing payload
        sandbox: Use sandbox environment
        cd_listing_id: Existing listing ID (for updates)
        etag: ETag for If-Match header (required for updates)

    Returns (success, response_data, new_etag, listing_id).
    """
    import requests

    if sandbox:
        base_url = "https://api.sandbox.centraldispatch.com"
    else:
        base_url = "https://api.centraldispatch.com"

    # CD V2 uses Content-Type versioning
    headers = {
        "Content-Type": "application/vnd.coxauto.v2+json",
        "Accept": "application/vnd.coxauto.v2+json",
        # Note: Real implementation would include auth
        # "Authorization": f"Bearer {token}"
    }

    try:
        if cd_listing_id and etag:
            # UPDATE existing listing with If-Match
            # CD API V2 uses /listings/id/{id} for PUT
            endpoint = f"{base_url}/listings/id/{cd_listing_id}"
            headers["If-Match"] = etag
            logger.info(f"PUT {endpoint} with If-Match: {etag}")

            response = requests.put(
                endpoint,
                json=payload,
                headers=headers,
                timeout=30,
            )

            # CD API returns 204 No Content for successful PUT
            if response.status_code == 204:
                logger.info(f"PUT success (204 No Content) for listing {cd_listing_id}")
                # Need to GET the listing to retrieve new ETag
                success, new_etag, _ = get_cd_listing_etag(cd_listing_id, sandbox=sandbox)
                return True, {"id": cd_listing_id, "updated": True}, new_etag, cd_listing_id

        else:
            # CREATE new listing
            endpoint = f"{base_url}/listings"
            logger.info(f"POST {endpoint}")
            logger.debug(f"Payload partnerReferenceId: {payload.get('partnerReferenceId')}")

            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=30,
            )

        # Handle response
        new_etag = response.headers.get("ETag")
        location = response.headers.get("Location")
        listing_id = None

        if response.status_code == 201:
            # POST success - extract listing ID from Location header
            # Location format: /listings/id/{id}
            if location:
                listing_id = location.rstrip("/").split("/")[-1]
                logger.info(f"POST success, Location: {location}, listing_id: {listing_id}")
            else:
                # Fallback to response body if Location not present
                try:
                    resp_data = response.json()
                    listing_id = resp_data.get("id") or resp_data.get("listingId")
                except Exception:
                    pass
                logger.warning("POST success but no Location header")

            # If no ETag in response, fetch it
            if listing_id and not new_etag:
                logger.info("No ETag in POST response, fetching via GET")
                success, new_etag, _ = get_cd_listing_etag(listing_id, sandbox=sandbox)

            try:
                return True, response.json(), new_etag, listing_id
            except Exception:
                return True, {"id": listing_id}, new_etag, listing_id

        elif response.status_code == 200:
            # Some CD endpoints may return 200 for updates
            try:
                resp_data = response.json()
                listing_id = resp_data.get("id") or resp_data.get("listingId") or cd_listing_id
                return True, resp_data, new_etag, listing_id
            except Exception:
                return True, {"id": cd_listing_id}, new_etag, cd_listing_id

        elif response.status_code == 412:
            # Precondition Failed - ETag mismatch (concurrent modification)
            logger.warning(f"412 Precondition Failed - ETag mismatch for {cd_listing_id}")
            return (
                False,
                {
                    "status_code": 412,
                    "error": "ETag mismatch - listing was modified. Please refresh and retry.",
                    "error_code": "ETAG_MISMATCH",
                },
                None,
                None,
            )

        elif response.status_code == 429:
            # Rate limited
            retry_after = response.headers.get("Retry-After", "60")
            logger.warning(f"429 Rate Limited, Retry-After: {retry_after}")
            return (
                False,
                {
                    "status_code": 429,
                    "error": "Rate limited by CD API. Please wait and retry.",
                    "error_code": "RATE_LIMITED",
                    "retry_after": retry_after,
                },
                None,
                None,
            )

        else:
            logger.error(f"CD API error {response.status_code}: {response.text[:500]}")
            return (
                False,
                {
                    "status_code": response.status_code,
                    "error": response.text,
                },
                None,
                None,
            )

    except requests.RequestException as e:
        logger.error(f"Request exception: {e}")
        return False, {"error": str(e)}, None, None


async def send_to_cd_with_retry(
    payload: dict,
    sandbox: bool = True,
    run_id: Optional[int] = None,
    force_create: bool = False,
) -> tuple[bool, dict, Optional[str]]:
    """
    Send to CD with rate limiting and retry logic (M3.Export).

    Handles:
    - Concurrent request throttling (max 3 concurrent)
    - Exponential backoff on 429/5xx errors
    - ETag-based updates for existing listings
    - Retry-safe POST using partnerReferenceId to detect duplicates
    - Full audit trail logging

    Args:
        payload: The listing payload
        sandbox: Use sandbox environment
        run_id: Extraction run ID (for ETag tracking)
        force_create: Force POST even if listing exists

    Returns (success, response_data, cd_listing_id).
    """
    # Import audit logging (M3.Export)
    from api.audit_log import (
        generate_request_id,
        log_duplicate_detected,
        log_etag_conflict,
        log_etag_refresh,
        log_post_create,
        log_post_fail,
        log_post_update,
    )

    request_id = generate_request_id()
    semaphore = get_cd_semaphore()

    # Check for existing CD listing (for update with ETag)
    # Note: Local DB check doesn't require semaphore
    cd_listing_id = None
    etag = None
    is_update = False

    if run_id and not force_create:
        existing = get_cd_listing_info(run_id)  # Local DB lookup, no semaphore needed
        if existing:
            cd_listing_id = existing.get("cd_listing_id")

    last_error = None
    partner_ref_id = payload.get("partnerReferenceId")

    for attempt in range(CD_RETRY_ATTEMPTS):
        # All CD API calls go through the semaphore to respect rate limits
        async with semaphore:
            loop = asyncio.get_event_loop()

            # If we have existing listing ID, fetch fresh ETag (inside semaphore)
            if cd_listing_id and not etag:
                logger.info(f"Found existing CD listing {cd_listing_id}, fetching ETag...")
                success, fresh_etag, _ = await loop.run_in_executor(
                    None, lambda lid=cd_listing_id: get_cd_listing_etag(lid, sandbox=sandbox)
                )
                if success and fresh_etag:
                    etag = fresh_etag
                    is_update = True
                    logger.info(f"Got fresh ETag: {etag}")
                else:
                    # Listing may have been deleted, force create
                    logger.warning(
                        f"Could not fetch ETag for {cd_listing_id}, creating new listing"
                    )
                    cd_listing_id = None
                    is_update = False

            # For POST retries: check if listing was created on previous attempt
            # (handles network errors where CD created listing but response was lost)
            if attempt > 0 and not is_update and partner_ref_id:
                logger.info(
                    f"Retry attempt {attempt + 1}: checking for existing listing by partnerReferenceId"
                )
                existing_id = await loop.run_in_executor(
                    None,
                    lambda pref=partner_ref_id: find_listing_by_partner_ref(pref, sandbox=sandbox),
                )
                if existing_id:
                    logger.info(
                        f"Found existing listing {existing_id} from previous attempt, treating as success"
                    )
                    # Audit: Duplicate detected during retry
                    if run_id:
                        log_duplicate_detected(
                            run_id=run_id,
                            external_id=payload.get("externalId"),
                            existing_listing_id=existing_id,
                            request_id=request_id,
                        )
                    # Fetch ETag for the found listing
                    success, found_etag, resp_data = await loop.run_in_executor(
                        None, lambda eid=existing_id: get_cd_listing_etag(eid, sandbox=sandbox)
                    )
                    if run_id:
                        save_cd_listing_info(
                            run_id=run_id,
                            cd_listing_id=existing_id,
                            etag=found_etag,
                            external_id=payload.get("externalId"),
                            sandbox=sandbox,
                        )
                    return True, {"id": existing_id, "recovered_from_retry": True}, existing_id

            # Send to CD (POST or PUT)
            # Note: send_to_cd returns 4 values: (success, response, new_etag, listing_id)
            result = await loop.run_in_executor(
                None,
                lambda lid=cd_listing_id, et=etag: send_to_cd(
                    payload, sandbox, lid if is_update else None, et if is_update else None
                ),
            )
            success, response, new_etag, result_listing_id = result

            if success:
                # Save listing info with new ETag
                if run_id and result_listing_id:
                    save_cd_listing_info(
                        run_id=run_id,
                        cd_listing_id=result_listing_id,
                        etag=new_etag,
                        external_id=payload.get("externalId"),
                        sandbox=sandbox,
                    )

                    # Audit: Log successful create or update
                    if is_update:
                        log_post_update(
                            run_id=run_id,
                            payload=payload,
                            response_status=200,
                            response_body=response,
                            cd_listing_id=result_listing_id,
                            etag_before=etag,
                            etag_after=new_etag,
                            request_id=request_id,
                        )
                    else:
                        log_post_create(
                            run_id=run_id,
                            payload=payload,
                            response_status=201,
                            response_body=response,
                            cd_listing_id=result_listing_id,
                            etag=new_etag,
                            request_id=request_id,
                        )

                return True, response, result_listing_id

            # Handle specific error codes
            error_code = response.get("error_code")
            status_code = response.get("status_code")

            if error_code == "ETAG_MISMATCH":
                # Audit: Log ETag conflict
                if run_id and cd_listing_id:
                    log_etag_conflict(
                        run_id=run_id,
                        cd_listing_id=cd_listing_id,
                        etag_used=etag,
                        request_id=request_id,
                    )

                # Refresh ETag and retry immediately (already inside semaphore)
                if cd_listing_id:
                    old_etag = etag
                    success, fresh_etag, _ = await loop.run_in_executor(
                        None, lambda lid=cd_listing_id: get_cd_listing_etag(lid, sandbox=sandbox)
                    )
                    if success and fresh_etag:
                        etag = fresh_etag
                        logger.info(f"Refreshed ETag after 412: {etag}")

                        # Audit: Log ETag refresh
                        if run_id:
                            log_etag_refresh(
                                run_id=run_id,
                                cd_listing_id=cd_listing_id,
                                old_etag=old_etag,
                                new_etag=fresh_etag,
                                request_id=request_id,
                            )
                        continue

            if status_code in (429, 500, 502, 503, 504):
                # Retry with exponential backoff
                backoff = min(CD_BACKOFF_BASE**attempt, CD_BACKOFF_MAX)
                if status_code == 429:
                    # Use Retry-After if provided
                    retry_after = response.get("retry_after")
                    if retry_after:
                        try:
                            backoff = min(float(retry_after), CD_BACKOFF_MAX)
                        except ValueError:
                            pass

                logger.warning(
                    f"CD API error {status_code}, retrying in {backoff}s (attempt {attempt + 1}/{CD_RETRY_ATTEMPTS})"
                )
                await asyncio.sleep(backoff)
                last_error = response
                continue

            # Non-retryable error
            if run_id:
                log_post_fail(
                    run_id=run_id,
                    payload=payload,
                    response_status=status_code or 0,
                    error_message=response.get("error", "Unknown error"),
                    cd_listing_id=cd_listing_id,
                    request_id=request_id,
                )
            return False, response, None

    # All retries exhausted
    if run_id:
        log_post_fail(
            run_id=run_id,
            payload=payload,
            response_status=0,
            error_message="Max retries exceeded",
            cd_listing_id=cd_listing_id,
            request_id=request_id,
        )
    return False, last_error or {"error": "Max retries exceeded"}, None


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/central-dispatch", response_model=CDExportResponse)
async def export_to_cd(
    data: CDExportRequest,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Force re-export even if already exported"),
):
    """
    Export extraction runs to Central Dispatch API V2.

    Set dry_run=true to preview payloads without sending.
    Set sandbox=true to use CD sandbox environment.
    Set force=true to re-export already exported runs (creates new attempt).

    IDEMPOTENCY: By default, already exported runs are skipped.
    """
    from api.database import get_connection

    previews = []
    exported_count = 0
    failed_count = 0
    skipped_count = 0

    for run_id in data.run_ids:
        run = ExtractionRunRepository.get_by_id(run_id)
        if not run:
            previews.append(
                CDPayloadPreview(
                    dispatch_id="",
                    run_id=run_id,
                    payload={},
                    validation_errors=["Run not found"],
                    is_valid=False,
                )
            )
            failed_count += 1
            continue

        # IDEMPOTENCY CHECK: Skip if already exported (unless force=True)
        if run.status == "exported" and not force:
            # Check for successful export job
            with get_connection() as conn:
                existing_job = conn.execute(
                    """SELECT id, status, created_at FROM export_jobs
                       WHERE run_id = ? AND status = 'completed'
                       ORDER BY created_at DESC LIMIT 1""",
                    (run_id,),
                ).fetchone()

            if existing_job:
                previews.append(
                    CDPayloadPreview(
                        dispatch_id="",
                        run_id=run_id,
                        payload={},
                        validation_errors=[
                            f"Already exported (job #{existing_job['id']} on {existing_job['created_at']}). "
                            "Use force=true to re-export."
                        ],
                        is_valid=False,
                    )
                )
                skipped_count += 1
                continue

        doc = DocumentRepository.get_by_id(run.document_id)

        # TEST DOCUMENT CHECK: Block export for test documents
        if doc:
            with get_connection() as conn:
                is_test = conn.execute(
                    "SELECT is_test FROM documents WHERE id = ?", (doc.id,)
                ).fetchone()
                if is_test and is_test[0]:
                    previews.append(
                        CDPayloadPreview(
                            dispatch_id="",
                            run_id=run_id,
                            payload={},
                            validation_errors=[
                                "Test document - export to Central Dispatch is blocked. "
                                "Use production documents for real exports."
                            ],
                            is_valid=False,
                        )
                    )
                    skipped_count += 1
                    continue

        # Build payload
        payload, errors = build_cd_payload(run_id)
        is_valid = len(errors) == 0

        preview = CDPayloadPreview(
            dispatch_id=payload.get("externalId", ""),
            run_id=run_id,
            document_filename=doc.filename if doc else None,
            payload=payload,
            validation_errors=errors,
            is_valid=is_valid,
        )
        previews.append(preview)

        if not data.dry_run and is_valid:
            # Actually send to CD with throttling and retry
            success, response, cd_listing_id = await send_to_cd_with_retry(
                payload,
                sandbox=data.sandbox,
                run_id=run_id,
                force_create=force,
            )

            # Create export job record (always creates new record for audit trail)
            job_id = ExportJobRepository.create(
                run_id=run_id,
                target="central_dispatch",
                payload_json=payload,
            )

            if success:
                ExportJobRepository.update(
                    job_id,
                    status="completed",
                    response_json=response,
                    cd_listing_id=cd_listing_id,
                )
                exported_count += 1

                # Update run status
                ExtractionRunRepository.update(run_id, status="exported")
            else:
                error_msg = response.get("error", "Unknown error")
                if response.get("error_code") == "ETAG_MISMATCH":
                    error_msg = "Listing was modified externally. Please refresh and retry."
                elif response.get("error_code") == "RATE_LIMITED":
                    error_msg = "Rate limited by CD API after retries."

                ExportJobRepository.update(
                    job_id,
                    status="failed",
                    response_json=response,
                    error_message=error_msg,
                )
                failed_count += 1

    if data.dry_run:
        message = f"Dry run: {len(previews)} payloads generated. Set dry_run=false to export."
        status = "preview"
    else:
        parts = [f"Exported {exported_count}"]
        if failed_count > 0:
            parts.append(f"failed {failed_count}")
        if skipped_count > 0:
            parts.append(f"skipped {skipped_count} (already exported)")
        message = ", ".join(parts) + "."
        status = "completed" if failed_count == 0 and skipped_count == 0 else "partial"

    return CDExportResponse(
        status=status,
        previews=previews,
        exported_count=exported_count,
        failed_count=failed_count,
        message=message,
    )


@router.get("/central-dispatch/preview/{run_id}", response_model=CDPayloadPreview)
async def preview_cd_payload(run_id: int):
    """
    Preview the CD API V2 payload for a single run.

    Useful for debugging before export.
    """
    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    doc = DocumentRepository.get_by_id(run.document_id)

    payload, errors = build_cd_payload(run_id)

    return CDPayloadPreview(
        dispatch_id=payload.get("externalId", ""),
        run_id=run_id,
        document_filename=doc.filename if doc else None,
        payload=payload,
        validation_errors=errors,
        is_valid=len(errors) == 0,
    )


@router.get("/jobs", response_model=ExportJobListResponse)
async def list_export_jobs(
    status: Optional[str] = Query(None),
    target: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List export jobs with optional filtering."""
    from api.database import get_connection

    sql = "SELECT * FROM export_jobs WHERE 1=1"
    params = []

    if status:
        sql += " AND status = ?"
        params.append(status)
    if target:
        sql += " AND target = ?"
        params.append(target)

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM export_jobs WHERE 1=1").fetchone()[0]

    items = []
    for row in rows:
        data = dict(row)
        if data.get("payload_json"):
            data["payload_json"] = json.loads(data["payload_json"])
        if data.get("response_json"):
            data["response_json"] = json.loads(data["response_json"])

        items.append(
            ExportJobResponse(
                id=data["id"],
                status=data["status"],
                target=data["target"],
                payload_json=data.get("payload_json"),
                response_json=data.get("response_json"),
                error_message=data.get("error_message"),
                created_at=data.get("created_at"),
                completed_at=data.get("completed_at"),
            )
        )

    return ExportJobListResponse(items=items, total=total)


@router.get("/jobs/{job_id}", response_model=ExportJobResponse)
async def get_export_job(job_id: int):
    """Get details of an export job."""
    job = ExportJobRepository.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")

    return ExportJobResponse(
        id=job.id,
        status=job.status,
        target=job.target,
        payload_json=job.payload_json,
        response_json=job.response_json,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.post("/jobs/{job_id}/retry", response_model=ExportJobResponse)
async def retry_export_job(job_id: int, sandbox: bool = Query(True)):
    """
    Retry a failed export job.
    """
    job = ExportJobRepository.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")

    if job.status != "failed":
        raise HTTPException(status_code=400, detail="Can only retry failed jobs")

    # Resend
    success, response = send_to_cd(job.payload_json, sandbox=sandbox)

    if success:
        ExportJobRepository.update(
            job_id,
            status="completed",
            response_json=response,
            error_message=None,
        )
    else:
        ExportJobRepository.update(
            job_id,
            status="failed",
            response_json=response,
            error_message=response.get("error", "Unknown error"),
        )

    job = ExportJobRepository.get_by_id(job_id)

    return ExportJobResponse(
        id=job.id,
        status=job.status,
        target=job.target,
        payload_json=job.payload_json,
        response_json=job.response_json,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


# =============================================================================
# FIELD REGISTRY ENDPOINT (Single Source of Truth)
# =============================================================================


@router.get("/cd-listing/{run_id}")
async def get_cd_listing(run_id: int):
    """
    Get CD listing info for a run.

    Returns stored cd_listing_id, etag, and other tracking info.
    Useful for checking if a listing exists and needs update vs. create.
    """
    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    listing_info = get_cd_listing_info(run_id)

    if not listing_info:
        return {
            "run_id": run_id,
            "has_listing": False,
            "cd_listing_id": None,
            "etag": None,
            "external_id": None,
            "sandbox": None,
        }

    return {
        "run_id": run_id,
        "has_listing": True,
        "cd_listing_id": listing_info.get("cd_listing_id"),
        "etag": listing_info.get("etag"),
        "external_id": listing_info.get("external_id"),
        "sandbox": listing_info.get("sandbox"),
        "created_at": listing_info.get("created_at"),
        "updated_at": listing_info.get("updated_at"),
    }


@router.get("/field-registry")
async def get_field_registry():
    """
    Get the listing field registry.

    This is the single source of truth for all CD listing fields.
    Used by frontend for form rendering and validation.
    """
    registry = get_registry()
    return registry.to_json_schema()


@router.get("/field-registry/blocking-issues/{run_id}")
async def get_blocking_issues(run_id: int):
    """
    Get blocking issues for a specific extraction run.

    Returns list of issues that prevent posting.
    """
    run = ExtractionRunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    # Get field values
    items = ReviewItemRepository.get_by_run(run_id)
    data = {}
    for item in items:
        value = item.corrected_value if item.corrected_value else item.predicted_value
        data[item.source_key] = value

    # Check if outputs_json has more data
    if run.outputs_json:
        outputs = (
            run.outputs_json if isinstance(run.outputs_json, dict) else json.loads(run.outputs_json)
        )
        for key, value in outputs.items():
            if key not in data:
                data[key] = value

    # Check warehouse selection
    warehouse_selected = bool(data.get("warehouse_id") or data.get("delivery_address"))

    registry = get_registry()
    issues = registry.get_blocking_issues(data, warehouse_selected=warehouse_selected)

    return {
        "run_id": run_id,
        "is_ready": len(issues) == 0,
        "issues": issues,
    }


# =============================================================================
# BATCH POSTING
# =============================================================================


class BatchPostRequest(BaseModel):
    """Batch posting request."""

    run_ids: list[int] = Field(..., description="Extraction run IDs to post")
    post_only_ready: bool = Field(True, description="Only post runs without blocking issues")
    sandbox: bool = Field(True, description="Use CD sandbox environment")


class BatchPostResult(BaseModel):
    """Result for a single run in batch."""

    run_id: int
    document_filename: Optional[str] = None
    status: str  # "success", "failed", "skipped", "blocked"
    message: str
    cd_listing_id: Optional[str] = None
    blocking_issues: list[str] = []


class BatchPostResponse(BaseModel):
    """Batch posting response."""

    total: int
    ready: int
    not_ready: int
    posted: int
    failed: int
    skipped: int
    results: list[BatchPostResult]


@router.post("/batch-post", response_model=BatchPostResponse)
async def batch_post(request: BatchPostRequest):
    """
    Batch post multiple extraction runs to Central Dispatch.

    Features:
    - Preflight check showing ready/not-ready counts
    - Throttling: max 3 concurrent requests to CD API
    - Exponential backoff on 429/5xx errors
    - ETag-based updates for re-posts
    - Option to post only ready runs
    """
    from api.database import get_connection

    registry = get_registry()
    results = []
    ready_count = 0
    not_ready_count = 0
    posted_count = 0
    failed_count = 0
    skipped_count = 0

    # Prepare tasks for async processing
    async def process_run(run_id: int) -> BatchPostResult:
        nonlocal ready_count, not_ready_count, posted_count, failed_count, skipped_count

        run = ExtractionRunRepository.get_by_id(run_id)
        if not run:
            failed_count += 1
            return BatchPostResult(
                run_id=run_id,
                status="failed",
                message="Extraction run not found",
            )

        doc = DocumentRepository.get_by_id(run.document_id)

        # Check if test document
        if doc:
            with get_connection() as conn:
                is_test = conn.execute(
                    "SELECT is_test FROM documents WHERE id = ?", (doc.id,)
                ).fetchone()
                if is_test and is_test[0]:
                    skipped_count += 1
                    return BatchPostResult(
                        run_id=run_id,
                        document_filename=doc.filename,
                        status="skipped",
                        message="Test document - cannot export to Central Dispatch",
                    )

        # Check if already exported (allow re-post with ETag)
        existing_listing = get_cd_listing_info(run_id)
        is_repost = existing_listing is not None

        if run.status == "exported" and not is_repost:
            skipped_count += 1
            return BatchPostResult(
                run_id=run_id,
                document_filename=doc.filename if doc else None,
                status="skipped",
                message="Already exported",
            )

        # Get field data
        items = ReviewItemRepository.get_by_run(run_id)
        data = {}
        for item in items:
            value = item.corrected_value if item.corrected_value else item.predicted_value
            data[item.source_key] = value

        if run.outputs_json:
            outputs = (
                run.outputs_json
                if isinstance(run.outputs_json, dict)
                else json.loads(run.outputs_json)
            )
            for key, value in outputs.items():
                if key not in data:
                    data[key] = value

        # Check blocking issues
        warehouse_selected = bool(data.get("warehouse_id") or data.get("delivery_address"))
        issues = registry.get_blocking_issues(data, warehouse_selected=warehouse_selected)

        if issues:
            not_ready_count += 1
            if request.post_only_ready:
                return BatchPostResult(
                    run_id=run_id,
                    document_filename=doc.filename if doc else None,
                    status="blocked",
                    message="Has blocking issues",
                    blocking_issues=[i["issue"] for i in issues],
                )
        else:
            ready_count += 1

        # Build payload
        payload, errors = build_cd_payload(run_id)

        if errors:
            failed_count += 1
            return BatchPostResult(
                run_id=run_id,
                document_filename=doc.filename if doc else None,
                status="failed",
                message="; ".join(errors),
                blocking_issues=errors,
            )

        # Send to CD with throttling and retry
        success, response, cd_listing_id = await send_to_cd_with_retry(
            payload,
            sandbox=request.sandbox,
            run_id=run_id,
        )

        # Create export job
        job_id = ExportJobRepository.create(
            run_id=run_id,
            target="central_dispatch",
            payload_json=payload,
        )

        if success:
            ExportJobRepository.update(
                job_id,
                status="completed",
                response_json=response,
                cd_listing_id=cd_listing_id,
            )
            ExtractionRunRepository.update(run_id, status="exported")
            posted_count += 1
            action = "Updated" if is_repost else "Posted"
            return BatchPostResult(
                run_id=run_id,
                document_filename=doc.filename if doc else None,
                status="success",
                message=f"{action} successfully",
                cd_listing_id=cd_listing_id,
            )
        else:
            error_msg = response.get("error", "Export failed")
            if response.get("error_code") == "ETAG_MISMATCH":
                error_msg = "Listing was modified externally. Please refresh and retry."
            elif response.get("error_code") == "RATE_LIMITED":
                error_msg = "Rate limited by CD API after retries."

            ExportJobRepository.update(
                job_id,
                status="failed",
                response_json=response,
                error_message=error_msg,
            )
            failed_count += 1
            return BatchPostResult(
                run_id=run_id,
                document_filename=doc.filename if doc else None,
                status="failed",
                message=error_msg,
            )

    # Process all runs with throttling
    # Note: The semaphore inside send_to_cd_with_retry handles concurrent request limiting
    tasks = [process_run(run_id) for run_id in request.run_ids]
    results = await asyncio.gather(*tasks)

    return BatchPostResponse(
        total=len(request.run_ids),
        ready=ready_count,
        not_ready=not_ready_count,
        posted=posted_count,
        failed=failed_count,
        skipped=skipped_count,
        results=list(results),
    )


@router.post("/batch-post/preflight")
async def batch_post_preflight(run_ids: list[int]):
    """
    Preflight check for batch posting.

    Returns summary of which runs are ready and which have issues.
    Does NOT actually post anything.
    """
    from api.database import get_connection

    registry = get_registry()
    ready = []
    not_ready = []

    for run_id in run_ids:
        run = ExtractionRunRepository.get_by_id(run_id)
        if not run:
            not_ready.append(
                {
                    "run_id": run_id,
                    "reason": "Run not found",
                }
            )
            continue

        doc = DocumentRepository.get_by_id(run.document_id)

        # Check test document
        if doc:
            with get_connection() as conn:
                is_test = conn.execute(
                    "SELECT is_test FROM documents WHERE id = ?", (doc.id,)
                ).fetchone()
                if is_test and is_test[0]:
                    not_ready.append(
                        {
                            "run_id": run_id,
                            "document_filename": doc.filename,
                            "reason": "Test document",
                        }
                    )
                    continue

        # Check if already exported
        if run.status == "exported":
            not_ready.append(
                {
                    "run_id": run_id,
                    "document_filename": doc.filename if doc else None,
                    "reason": "Already exported",
                }
            )
            continue

        # Get field data
        items = ReviewItemRepository.get_by_run(run_id)
        data = {}
        for item in items:
            value = item.corrected_value if item.corrected_value else item.predicted_value
            data[item.source_key] = value

        if run.outputs_json:
            outputs = (
                run.outputs_json
                if isinstance(run.outputs_json, dict)
                else json.loads(run.outputs_json)
            )
            for key, value in outputs.items():
                if key not in data:
                    data[key] = value

        # Check blocking issues
        warehouse_selected = bool(data.get("warehouse_id") or data.get("delivery_address"))
        issues = registry.get_blocking_issues(data, warehouse_selected=warehouse_selected)

        if issues:
            not_ready.append(
                {
                    "run_id": run_id,
                    "document_filename": doc.filename if doc else None,
                    "issues": [i["issue"] for i in issues],
                }
            )
        else:
            ready.append(
                {
                    "run_id": run_id,
                    "document_filename": doc.filename if doc else None,
                }
            )

    return {
        "total": len(run_ids),
        "ready_count": len(ready),
        "not_ready_count": len(not_ready),
        "ready": ready,
        "not_ready": not_ready,
    }


# =============================================================================
# PRODUCTION CORRECTIONS → TRAINING
# =============================================================================


class ProductionCorrectionItem(BaseModel):
    """Single field correction from production."""

    field_key: str
    old_value: Optional[str] = None
    new_value: str
    context_snippet: Optional[str] = None


class ProductionCorrectionsRequest(BaseModel):
    """Submit production corrections for training."""

    run_id: int
    corrections: list[ProductionCorrectionItem]
    save_to_extraction: bool = Field(True, description="Update extraction outputs_json")


class ProductionCorrectionsResponse(BaseModel):
    """Response after saving production corrections."""

    success: bool
    corrections_saved: int
    training_events_created: int
    message: str


@router.post("/production-corrections", response_model=ProductionCorrectionsResponse)
async def submit_production_corrections(request: ProductionCorrectionsRequest):
    """
    Submit production corrections for training.

    This is the SECOND training channel (primary is Test Lab).
    Production corrections:
    1. Update extraction outputs_json (if save_to_extraction=true)
    2. Create CorrectionEvent records for training
    3. Events are visible in Test Lab training dashboard

    Different from Test Lab corrections:
    - Comes from production workflow (Review & Posting)
    - Source is marked as 'production'
    - Can be toggled on/off for training
    """
    from api.database import get_connection

    run = ExtractionRunRepository.get_by_id(request.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Extraction run not found")

    doc = DocumentRepository.get_by_id(run.document_id)
    at = AuctionTypeRepository.get_by_id(run.auction_type_id)

    corrections_saved = 0
    training_events_created = 0

    # Update extraction outputs_json
    if request.save_to_extraction:
        outputs = run.outputs_json if isinstance(run.outputs_json, dict) else {}
        if isinstance(run.outputs_json, str):
            outputs = json.loads(run.outputs_json)

        for correction in request.corrections:
            outputs[correction.field_key] = correction.new_value
            corrections_saved += 1

        ExtractionRunRepository.update(request.run_id, outputs_json=outputs)

    # Create production correction events in training database
    with get_connection() as conn:
        # Ensure production_corrections table exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS production_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                document_id INTEGER,
                auction_type_id INTEGER,
                auction_type_code TEXT,
                field_key TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT NOT NULL,
                context_snippet TEXT,
                source TEXT DEFAULT 'production',
                applied_to_training BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT,
                FOREIGN KEY (run_id) REFERENCES extraction_runs(id),
                FOREIGN KEY (document_id) REFERENCES documents(id)
            )
        """)

        for correction in request.corrections:
            conn.execute(
                """
                INSERT INTO production_corrections
                (run_id, document_id, auction_type_id, auction_type_code,
                 field_key, old_value, new_value, context_snippet)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    request.run_id,
                    doc.id if doc else None,
                    at.id if at else None,
                    at.code if at else None,
                    correction.field_key,
                    correction.old_value,
                    correction.new_value,
                    correction.context_snippet,
                ),
            )
            training_events_created += 1

        conn.commit()

    return ProductionCorrectionsResponse(
        success=True,
        corrections_saved=corrections_saved,
        training_events_created=training_events_created,
        message=f"Saved {corrections_saved} corrections, created {training_events_created} training events",
    )


@router.get("/production-corrections")
async def list_production_corrections(
    auction_type_code: Optional[str] = None,
    applied: Optional[bool] = None,
    limit: int = Query(100, ge=1, le=1000),
):
    """
    List production corrections (for Test Lab dashboard).

    Shows corrections from production workflow that can be used for training.
    """
    from api.database import get_connection

    with get_connection() as conn:
        # Check if table exists
        table_exists = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='production_corrections'
        """).fetchone()

        if not table_exists:
            return {
                "items": [],
                "total": 0,
                "applied_count": 0,
                "pending_count": 0,
            }

        sql = "SELECT * FROM production_corrections WHERE 1=1"
        params = []

        if auction_type_code:
            sql += " AND auction_type_code = ?"
            params.append(auction_type_code)

        if applied is not None:
            sql += " AND applied_to_training = ?"
            params.append(applied)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()

        # Get counts
        total = conn.execute("SELECT COUNT(*) FROM production_corrections").fetchone()[0]
        applied_count = conn.execute(
            "SELECT COUNT(*) FROM production_corrections WHERE applied_to_training = TRUE"
        ).fetchone()[0]
        pending_count = total - applied_count

    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "applied_count": applied_count,
        "pending_count": pending_count,
    }


@router.post("/production-corrections/apply-to-training")
async def apply_production_corrections_to_training(
    correction_ids: list[int] = None,
    apply_all_pending: bool = False,
):
    """
    Apply production corrections to training rules.

    This integrates production corrections into the training system.
    """
    from api.database import get_connection
    from api.training_db import get_session
    from services.training_service import TrainingService

    if not correction_ids and not apply_all_pending:
        raise HTTPException(
            status_code=400, detail="Either provide correction_ids or set apply_all_pending=true"
        )

    with get_connection() as conn:
        if apply_all_pending:
            rows = conn.execute("""
                SELECT * FROM production_corrections
                WHERE applied_to_training = FALSE
            """).fetchall()
        else:
            placeholders = ",".join("?" * len(correction_ids))
            rows = conn.execute(
                f"""
                SELECT * FROM production_corrections
                WHERE id IN ({placeholders}) AND applied_to_training = FALSE
            """,
                correction_ids,
            ).fetchall()

        if not rows:
            return {
                "success": True,
                "applied_count": 0,
                "message": "No corrections to apply",
            }

        # Group by auction type for training
        by_auction = {}
        for row in rows:
            at_code = row["auction_type_code"]
            if at_code not in by_auction:
                by_auction[at_code] = []
            by_auction[at_code].append(dict(row))

        applied_count = 0

        # Apply to training service
        session = next(get_session())
        try:
            service = TrainingService(session)

            for _at_code, corrections in by_auction.items():
                for corr in corrections:
                    # Create training example from production correction
                    service.save_corrections(
                        run_id=corr["run_id"],
                        corrections=[
                            {
                                "field_key": corr["field_key"],
                                "predicted_value": corr["old_value"],
                                "corrected_value": corr["new_value"],
                                "was_correct": False,
                            }
                        ],
                        mark_validated=True,
                        source="production",
                    )
                    applied_count += 1

            # Mark as applied
            for row in rows:
                conn.execute(
                    "UPDATE production_corrections SET applied_to_training = TRUE WHERE id = ?",
                    (row["id"],),
                )
            conn.commit()

        finally:
            session.close()

    return {
        "success": True,
        "applied_count": applied_count,
        "message": f"Applied {applied_count} production corrections to training",
    }


# =============================================================================
# BATCH JOB ENDPOINTS (M3.BatchQueue)
# =============================================================================


@router.post("/batch-jobs")
async def create_batch_export_job(
    run_ids: list[int],
    sandbox: bool = True,
    post_only_ready: bool = True,
    background_tasks: BackgroundTasks = None,
):
    """
    Create a batch export job for multiple extraction runs.

    The job will be processed asynchronously. Use the returned job_id
    to check progress via GET /batch-jobs/{job_id}.

    Args:
        run_ids: List of extraction run IDs to export
        sandbox: Use CD sandbox environment
        post_only_ready: Only post runs without blocking issues

    Returns:
        Job ID and initial status
    """
    from api.batch_jobs import create_batch_job

    if not run_ids:
        raise HTTPException(status_code=400, detail="No run IDs provided")

    # Create job
    job_id = create_batch_job(
        run_ids=run_ids,
        options={
            "sandbox": sandbox,
            "post_only_ready": post_only_ready,
        },
    )

    # Start processing in background
    if background_tasks:
        background_tasks.add_task(
            _run_batch_job_sync,
            job_id=job_id,
            sandbox=sandbox,
        )

    return {
        "job_id": job_id,
        "status": "pending",
        "total_runs": len(run_ids),
        "message": "Batch job created. Poll GET /batch-jobs/{job_id} for progress.",
    }


def _run_batch_job_sync(job_id: int, sandbox: bool):
    """Synchronous wrapper for async batch job processing."""
    import asyncio

    from api.batch_jobs import run_batch_job

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_batch_job(job_id, sandbox=sandbox))
    except Exception as e:
        import logging

        logging.getLogger(__name__).error(f"Batch job {job_id} error: {e}")
    finally:
        loop.close()


@router.get("/batch-jobs/{job_id}")
async def get_batch_job(job_id: int):
    """
    Get batch job status and progress.

    Returns current status, progress (percent complete, counts),
    and results (if completed).
    """
    from api.batch_jobs import get_batch_job_status

    status = get_batch_job_status(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return status


@router.get("/batch-jobs")
async def list_batch_jobs(
    status: str = None,
    limit: int = 20,
):
    """
    List recent batch jobs.

    Args:
        status: Filter by status (pending, running, completed, failed)
        limit: Maximum number of jobs to return
    """
    from api.batch_jobs import BatchJobRepository

    jobs = BatchJobRepository.list_recent(limit=limit, status=status)
    return {"jobs": jobs}


# =============================================================================
# AUDIT TRAIL ENDPOINTS (M3.Export)
# =============================================================================


@router.get("/audit-trail/{run_id}")
async def get_run_audit_trail(run_id: int):
    """
    Get complete audit trail for an extraction run.

    Returns all audit events (export attempts, ETag operations, etc.)
    in chronological order.
    """
    from api.audit_log import get_audit_trail

    events = get_audit_trail(run_id)
    return {
        "run_id": run_id,
        "events_count": len(events),
        "events": events,
    }


@router.get("/audit-trail/listing/{cd_listing_id}")
async def get_listing_audit_trail(cd_listing_id: str):
    """
    Get audit trail for a specific CD listing.

    Returns all audit events related to this listing ID.
    """
    from api.audit_log import AuditLogRepository

    events = AuditLogRepository.get_by_listing(cd_listing_id)
    return {
        "cd_listing_id": cd_listing_id,
        "events_count": len(events),
        "events": [e.to_dict() for e in events],
    }


@router.post("/batch-jobs/{job_id}/cancel")
async def cancel_batch_job(job_id: int):
    """
    Cancel a running batch job.

    Note: Items already processed will not be rolled back.
    """
    from api.batch_jobs import BatchJobRepository, BatchJobStatus

    job = BatchJobRepository.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job["status"] not in (BatchJobStatus.PENDING.value, BatchJobStatus.RUNNING.value):
        raise HTTPException(
            status_code=400, detail=f"Cannot cancel job with status: {job['status']}"
        )

    BatchJobRepository.update(
        job_id,
        status=BatchJobStatus.CANCELLED.value,
        completed_at=datetime.utcnow().isoformat(),
    )

    return {
        "job_id": job_id,
        "status": "cancelled",
        "message": "Job cancelled. Items already processed are not affected.",
    }
