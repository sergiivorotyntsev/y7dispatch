"""
Broker Management API Routes

Provides CRUD operations for brokers (transport companies with multiple warehouses).
"""

from fastapi import APIRouter, HTTPException, Query

from api.brokers import (
    BrokerCreate,
    BrokerListResponse,
    BrokerRepository,
    BrokerResponse,
    BrokerUpdate,
    init_brokers_schema,
)

router = APIRouter(prefix="/api/brokers", tags=["Brokers"])


@router.post("/", response_model=BrokerResponse, status_code=201)
async def create_broker(data: BrokerCreate):
    """Create a new broker."""
    init_brokers_schema()

    existing = BrokerRepository.get_by_code(data.code)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Broker with code '{data.code}' already exists",
        )

    broker_id = BrokerRepository.create(data)
    broker = BrokerRepository.get_by_id(broker_id)

    if not broker:
        raise HTTPException(status_code=500, detail="Failed to create broker")

    return broker


@router.get("/", response_model=BrokerListResponse)
async def list_brokers(
    active_only: bool = Query(True, description="Only return active brokers"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all brokers."""
    init_brokers_schema()
    return BrokerRepository.list_all(active_only=active_only, limit=limit, offset=offset)


@router.get("/{id}", response_model=BrokerResponse)
async def get_broker(id: int):
    """Get a broker by ID."""
    init_brokers_schema()

    broker = BrokerRepository.get_by_id(id)
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")

    return broker


@router.get("/code/{code}", response_model=BrokerResponse)
async def get_broker_by_code(code: str):
    """Get a broker by code."""
    init_brokers_schema()

    broker = BrokerRepository.get_by_code(code)
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")

    return broker


@router.put("/{id}", response_model=BrokerResponse)
async def update_broker(id: int, data: BrokerUpdate):
    """Update a broker."""
    init_brokers_schema()

    broker = BrokerRepository.update(id, data)
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")

    return broker


@router.delete("/{id}")
async def delete_broker(
    id: int,
    hard: bool = Query(False, description="Hard delete (permanent)"),
):
    """Delete a broker (soft delete by default)."""
    init_brokers_schema()

    deleted = BrokerRepository.delete(id, hard=hard)
    if not deleted:
        raise HTTPException(status_code=404, detail="Broker not found")

    return {"status": "ok", "deleted": id}
