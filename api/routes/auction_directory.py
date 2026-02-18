"""
Auction Directory API — lookup Copart/IAA/Manheim location phone numbers.

Used by Review page to auto-fill pickup_phone when extraction misses it.
"""

from fastapi import APIRouter, Query

from services.auction_directory import lookup_auction_location

router = APIRouter(prefix="/api/auction-directory", tags=["Auction Directory"])


@router.get("/lookup")
async def lookup_location(name: str = Query(..., description="Auction location name")):
    """Look up auction location by name.

    Returns phone, address, city, state, zip if found.
    """
    result = lookup_auction_location(name)
    if result:
        return {"found": True, "location": result, "name": name}
    return {"found": False, "location": None, "name": name}
