"""
Auction Types API Routes

CRUD operations for AuctionType management.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.models import AuctionTypeRepository

router = APIRouter(prefix="/api/auction-types", tags=["Auction Types"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class AuctionTypeCreate(BaseModel):
    """Request model for creating an auction type."""

    name: str = Field(..., min_length=1, max_length=100)
    code: str = Field(..., min_length=1, max_length=20)
    parent_id: Optional[int] = None
    description: Optional[str] = None
    extractor_config: Optional[dict] = None


class AuctionTypeUpdate(BaseModel):
    """Request model for updating an auction type."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    extractor_config: Optional[dict] = None


class AuctionTypeResponse(BaseModel):
    """Response model for auction type."""

    id: int
    name: str
    code: str
    parent_id: Optional[int] = None
    is_base: bool = False
    is_custom: bool = False
    is_active: bool = True
    description: Optional[str] = None
    extractor_config: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class AuctionTypeListResponse(BaseModel):
    """Response model for list of auction types."""

    items: list[AuctionTypeResponse]
    total: int


# =============================================================================
# ROUTES
# =============================================================================


@router.get("/", response_model=AuctionTypeListResponse)
async def list_auction_types(
    include_inactive: bool = Query(False, description="Include inactive types"),
):
    """
    List all auction types.

    Returns base types (Copart, IAA, Manheim, Other) and custom types.
    """
    types = AuctionTypeRepository.list_all(include_inactive=include_inactive)
    return AuctionTypeListResponse(
        items=[AuctionTypeResponse(**t.__dict__) for t in types],
        total=len(types),
    )


@router.get("/{id}", response_model=AuctionTypeResponse)
async def get_auction_type(id: int):
    """Get a single auction type by ID."""
    auction_type = AuctionTypeRepository.get_by_id(id)
    if not auction_type:
        raise HTTPException(status_code=404, detail="Auction type not found")
    return AuctionTypeResponse(**auction_type.__dict__)


@router.get("/code/{code}", response_model=AuctionTypeResponse)
async def get_auction_type_by_code(code: str):
    """Get a single auction type by code."""
    auction_type = AuctionTypeRepository.get_by_code(code)
    if not auction_type:
        raise HTTPException(status_code=404, detail="Auction type not found")
    return AuctionTypeResponse(**auction_type.__dict__)


@router.post("/", response_model=AuctionTypeResponse, status_code=201)
async def create_auction_type(data: AuctionTypeCreate):
    """
    Create a new auction type.

    Custom types should have parent_id pointing to "Other" (id=4).
    Base types cannot be created via API.
    """
    # Check if code already exists
    existing = AuctionTypeRepository.get_by_code(data.code)
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Auction type with code '{data.code}' already exists"
        )

    # Validate parent_id if provided
    if data.parent_id:
        parent = AuctionTypeRepository.get_by_id(data.parent_id)
        if not parent:
            raise HTTPException(status_code=400, detail="Parent auction type not found")
        if not parent.is_base:
            raise HTTPException(status_code=400, detail="Parent must be a base type")

    type_id = AuctionTypeRepository.create(
        name=data.name,
        code=data.code.upper(),
        parent_id=data.parent_id,
        is_custom=True,
        description=data.description,
        extractor_config=data.extractor_config,
    )

    return AuctionTypeRepository.get_by_id(type_id)


@router.put("/{id}", response_model=AuctionTypeResponse)
async def update_auction_type(id: int, data: AuctionTypeUpdate):
    """
    Update an auction type.

    Note: Base types have limited updateable fields.
    """
    auction_type = AuctionTypeRepository.get_by_id(id)
    if not auction_type:
        raise HTTPException(status_code=404, detail="Auction type not found")

    # Base types: only description and extractor_config can be updated
    update_data = {}
    if data.name is not None:
        if auction_type.is_base:
            raise HTTPException(status_code=400, detail="Cannot change name of base type")
        update_data["name"] = data.name
    if data.description is not None:
        update_data["description"] = data.description
    if data.is_active is not None:
        if auction_type.is_base:
            raise HTTPException(status_code=400, detail="Cannot deactivate base type")
        update_data["is_active"] = data.is_active
    if data.extractor_config is not None:
        update_data["extractor_config"] = data.extractor_config

    if update_data:
        AuctionTypeRepository.update(id, **update_data)

    return AuctionTypeRepository.get_by_id(id)


@router.delete("/{id}", status_code=204)
async def delete_auction_type(id: int):
    """
    Delete (deactivate) an auction type.

    Base types cannot be deleted.
    """
    auction_type = AuctionTypeRepository.get_by_id(id)
    if not auction_type:
        raise HTTPException(status_code=404, detail="Auction type not found")

    if auction_type.is_base:
        raise HTTPException(status_code=400, detail="Cannot delete base type")

    success = AuctionTypeRepository.delete(id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete auction type")

    return None
