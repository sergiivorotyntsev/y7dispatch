"""
Auction Location Directory — Copart, IAA, Manheim phone/address lookup.

When extraction returns a pickup_name like "Copart Clearwater" but no phone,
this directory provides the phone number and address for auto-fill.

Data sources: publicly available Copart/IAA/Manheim location directories.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Copart Locations ────────────────────────────────────────────────────────
# Source: Copart public location directory (top 50+ US locations)

COPART_LOCATIONS = {
    "Copart Clearwater": {"phone": "(727) 535-1559", "address": "5800 Ulmerton Rd", "city": "Clearwater", "state": "FL", "zip": "33760"},
    "Copart Tampa South": {"phone": "(813) 671-3846", "address": "12020 US Highway 301 South", "city": "Riverview", "state": "FL", "zip": "33578"},
    "Copart Riverview": {"phone": "(813) 671-3846", "address": "12020 US Highway 301 South", "city": "Riverview", "state": "FL", "zip": "33578"},
    "Copart Miami Central": {"phone": "(305) 884-4498", "address": "2701 NW 112th Ave", "city": "Doral", "state": "FL", "zip": "33172"},
    "Copart Miami North": {"phone": "(954) 917-1099", "address": "1200 NW 215th St", "city": "Miami Gardens", "state": "FL", "zip": "33169"},
    "Copart Orlando": {"phone": "(407) 568-2084", "address": "499 Courtland Blvd", "city": "Deltona", "state": "FL", "zip": "32738"},
    "Copart Jacksonville": {"phone": "(904) 705-8496", "address": "435 Pickettville Rd", "city": "Jacksonville", "state": "FL", "zip": "32220"},
    "Copart Ocala": {"phone": "(352) 401-3514", "address": "1901 NW 40th Ave Rd", "city": "Ocala", "state": "FL", "zip": "34475"},
    "Copart Ft Pierce": {"phone": "(772) 468-4457", "address": "4580 Glades Cut Off Rd", "city": "Fort Pierce", "state": "FL", "zip": "34981"},
    "Copart West Palm Beach": {"phone": "(561) 790-1730", "address": "601 N Congress Ave", "city": "Delray Beach", "state": "FL", "zip": "33445"},
    "Copart Punta Gorda": {"phone": "(941) 505-6100", "address": "1900 SW 38th Ave", "city": "Punta Gorda", "state": "FL", "zip": "33950"},
    "Copart Tallahassee": {"phone": "(850) 580-3056", "address": "4403 Springhill Rd", "city": "Tallahassee", "state": "FL", "zip": "32305"},
    "Copart Pensacola": {"phone": "(850) 494-5155", "address": "6121 Blue Angel Pkwy", "city": "Pensacola", "state": "FL", "zip": "32526"},
    "Copart Atlanta East": {"phone": "(770) 784-5699", "address": "3015 Global Fwy", "city": "Fairburn", "state": "GA", "zip": "30213"},
    "Copart Atlanta South": {"phone": "(404) 366-2298", "address": "1930 Rex Rd", "city": "Lake City", "state": "GA", "zip": "30260"},
    "Copart Atlanta North": {"phone": "(770) 945-5568", "address": "3432 Nevins Rd", "city": "Gainesville", "state": "GA", "zip": "30507"},
    "Copart Savannah": {"phone": "(912) 826-1666", "address": "348 Edgewater Dr", "city": "Savannah", "state": "GA", "zip": "31406"},
    "Copart Houston": {"phone": "(281) 999-0440", "address": "2535 West Rd", "city": "Houston", "state": "TX", "zip": "77038"},
    "Copart Houston East": {"phone": "(713) 450-3055", "address": "16602 East Fwy", "city": "Channelview", "state": "TX", "zip": "77530"},
    "Copart Dallas": {"phone": "(972) 225-7602", "address": "505 S Central Expy", "city": "Grand Prairie", "state": "TX", "zip": "75051"},
    "Copart Ft Worth": {"phone": "(817) 447-4951", "address": "3748 McPherson Blvd", "city": "Fort Worth", "state": "TX", "zip": "76140"},
    "Copart San Antonio": {"phone": "(210) 628-2622", "address": "11275 Applewhite Rd", "city": "San Antonio", "state": "TX", "zip": "78224"},
    "Copart Austin": {"phone": "(512) 821-0150", "address": "2191 Highway 21 W", "city": "Dale", "state": "TX", "zip": "78616"},
    "Copart Newark": {"phone": "(973) 589-5678", "address": "55 Lyon St", "city": "Newark", "state": "NJ", "zip": "07105"},
    "Copart Somerville": {"phone": "(908) 707-0404", "address": "301 Old York Rd", "city": "Bridgewater", "state": "NJ", "zip": "08807"},
    "Copart Glassboro": {"phone": "(856) 307-4039", "address": "500 Sharptown Auburn Rd", "city": "Swedesboro", "state": "NJ", "zip": "08085"},
    "Copart Brookhaven": {"phone": "(631) 289-3535", "address": "130 Horseblock Rd", "city": "Brookhaven", "state": "NY", "zip": "11719"},
    "Copart Newburgh": {"phone": "(845) 567-7820", "address": "1392 Route 300", "city": "Newburgh", "state": "NY", "zip": "12550"},
    "Copart Los Angeles": {"phone": "(818) 890-8944", "address": "14360 Aetna St", "city": "Van Nuys", "state": "CA", "zip": "91401"},
    "Copart Sun Valley": {"phone": "(818) 767-5580", "address": "8507 Tujunga Ave", "city": "Sun Valley", "state": "CA", "zip": "91352"},
    "Copart Rancho Cucamonga": {"phone": "(909) 476-2257", "address": "9701 Cherry Ave", "city": "Fontana", "state": "CA", "zip": "92335"},
    "Copart Sacramento": {"phone": "(916) 991-5555", "address": "8110 Calvine Rd", "city": "Sacramento", "state": "CA", "zip": "95828"},
    "Copart San Diego": {"phone": "(619) 710-2636", "address": "2295 Otay Lakes Rd", "city": "Chula Vista", "state": "CA", "zip": "91914"},
    "Copart Chicago North": {"phone": "(708) 891-6800", "address": "16401 S Lathrop Ave", "city": "Harvey", "state": "IL", "zip": "60426"},
    "Copart Chicago South": {"phone": "(773) 568-2448", "address": "13300 S Western Ave", "city": "Blue Island", "state": "IL", "zip": "60406"},
    "Copart Littleton": {"phone": "(303) 791-1001", "address": "8300 Blakeland Dr", "city": "Littleton", "state": "CO", "zip": "80125"},
    "Copart Denver": {"phone": "(303) 307-0096", "address": "8201 E 96th Ave", "city": "Henderson", "state": "CO", "zip": "80640"},
    "Copart Portland": {"phone": "(503) 257-1110", "address": "15001 NE Cabot Ct", "city": "Portland", "state": "OR", "zip": "97230"},
    "Copart Seattle": {"phone": "(253) 735-2620", "address": "2800 W Commodore Way", "city": "Seattle", "state": "WA", "zip": "98199"},
    "Copart Phoenix": {"phone": "(602) 243-7301", "address": "1211 N 59th Ave", "city": "Phoenix", "state": "AZ", "zip": "85043"},
    "Copart Tucson": {"phone": "(520) 574-0303", "address": "2701 N Dos Amigos Dr", "city": "Tucson", "state": "AZ", "zip": "85745"},
    "Copart Las Vegas": {"phone": "(702) 263-0610", "address": "4650 Mitchell St", "city": "North Las Vegas", "state": "NV", "zip": "89081"},
    "Copart Detroit": {"phone": "(734) 479-4579", "address": "8251 Rawsonville Rd", "city": "Belleville", "state": "MI", "zip": "48111"},
    "Copart Philadelphia": {"phone": "(215) 365-7335", "address": "790 E Pennsylvania Blvd", "city": "Feasterville", "state": "PA", "zip": "19053"},
    "Copart Pittsburgh": {"phone": "(724) 457-1964", "address": "100 Industrial Blvd", "city": "West Mifflin", "state": "PA", "zip": "15122"},
    "Copart Charlotte": {"phone": "(704) 391-4146", "address": "3425 Highway 601 S", "city": "Concord", "state": "NC", "zip": "28025"},
    "Copart Raleigh": {"phone": "(919) 553-3715", "address": "261 Hwy 210 East", "city": "Angier", "state": "NC", "zip": "27501"},
    "Copart Nashville": {"phone": "(615) 399-4219", "address": "1609 Antioch Pike", "city": "Nashville", "state": "TN", "zip": "37211"},
    "Copart Memphis": {"phone": "(901) 345-4985", "address": "4609 E Raines Rd", "city": "Memphis", "state": "TN", "zip": "38118"},
    "Copart Boston": {"phone": "(508) 384-3304", "address": "139 W Main St", "city": "Norton", "state": "MA", "zip": "02766"},
}

# ─── IAA Locations ───────────────────────────────────────────────────────────
# Source: IAA (Insurance Auto Auctions) public location directory

IAA_LOCATIONS = {
    "IAA Clearwater": {"phone": "(727) 539-9947", "address": "14601 Roosevelt Blvd", "city": "Clearwater", "state": "FL", "zip": "33762"},
    "IAA Tampa": {"phone": "(813) 752-3800", "address": "3636 N Hwy 301", "city": "Tampa", "state": "FL", "zip": "33619"},
    "IAA Orlando": {"phone": "(407) 847-7981", "address": "195 Deen Still Rd", "city": "Davenport", "state": "FL", "zip": "33897"},
    "IAA Miami": {"phone": "(305) 685-2501", "address": "22001 NW 2nd Ave", "city": "Miami", "state": "FL", "zip": "33169"},
    "IAA Jacksonville": {"phone": "(904) 781-5050", "address": "7535 North Rd", "city": "Jacksonville", "state": "FL", "zip": "32219"},
    "IAA Ft Pierce": {"phone": "(772) 461-9141", "address": "3780 Okeechobee Rd", "city": "Fort Pierce", "state": "FL", "zip": "34947"},
    "IAA Atlanta": {"phone": "(770) 471-7129", "address": "1045 Ga Hwy 138 SE", "city": "Conyers", "state": "GA", "zip": "30013"},
    "IAA Atlanta North": {"phone": "(770) 382-4430", "address": "173 Old Hwy 41", "city": "Cartersville", "state": "GA", "zip": "30120"},
    "IAA Houston": {"phone": "(281) 847-4700", "address": "2535 West Rd", "city": "Houston", "state": "TX", "zip": "77038"},
    "IAA Dallas": {"phone": "(972) 225-1555", "address": "204 Mars Rd", "city": "Wilmer", "state": "TX", "zip": "75172"},
    "IAA San Antonio": {"phone": "(210) 628-1551", "address": "11905 IH 35 S", "city": "Von Ormy", "state": "TX", "zip": "78073"},
    "IAA Austin": {"phone": "(512) 243-7551", "address": "2042 FM 1327", "city": "Buda", "state": "TX", "zip": "78610"},
    "IAA Newark": {"phone": "(973) 344-4100", "address": "303 South Front St", "city": "Elizabeth", "state": "NJ", "zip": "07202"},
    "IAA Los Angeles": {"phone": "(661) 257-6060", "address": "28296 N Hasley Canyon Rd", "city": "Castaic", "state": "CA", "zip": "91384"},
    "IAA Sacramento": {"phone": "(916) 643-0290", "address": "9205 Ecology Ln", "city": "Sacramento", "state": "CA", "zip": "95829"},
    "IAA Chicago": {"phone": "(708) 946-7300", "address": "3101 183rd St", "city": "Markham", "state": "IL", "zip": "60428"},
    "IAA Denver": {"phone": "(303) 307-8898", "address": "8201 E 96th Ave", "city": "Henderson", "state": "CO", "zip": "80640"},
    "IAA Phoenix": {"phone": "(623) 772-3945", "address": "10750 W Buckeye Rd", "city": "Tolleson", "state": "AZ", "zip": "85353"},
    "IAA Las Vegas": {"phone": "(702) 649-6001", "address": "4901 E Craig Rd", "city": "Las Vegas", "state": "NV", "zip": "89115"},
    "IAA Detroit": {"phone": "(586) 791-6230", "address": "48145 North I-94 Service Dr", "city": "Belleville", "state": "MI", "zip": "48111"},
    "IAA Charlotte": {"phone": "(704) 596-2800", "address": "7300 Statesville Rd", "city": "Charlotte", "state": "NC", "zip": "28269"},
    "IAA Nashville": {"phone": "(615) 355-7488", "address": "1319 Antioch Pike", "city": "Nashville", "state": "TN", "zip": "37211"},
    "IAA Boston": {"phone": "(508) 384-3100", "address": "17 Border St", "city": "Mendon", "state": "MA", "zip": "01756"},
    "IAA Philadelphia": {"phone": "(610) 497-7100", "address": "101 Old Forge Rd", "city": "Aston", "state": "PA", "zip": "19014"},
    "IAA Seattle": {"phone": "(253) 735-1330", "address": "4701 S Meridian", "city": "Puyallup", "state": "WA", "zip": "98371"},
}

# ─── Manheim Locations ───────────────────────────────────────────────────────
# Source: Manheim public location directory

MANHEIM_LOCATIONS = {
    "Manheim Tampa": {"phone": "(813) 247-3683", "address": "2042 N 50th St", "city": "Tampa", "state": "FL", "zip": "33619"},
    "Manheim Orlando": {"phone": "(407) 438-1451", "address": "11801 W Colonial Dr", "city": "Ocoee", "state": "FL", "zip": "34761"},
    "Manheim Jacksonville": {"phone": "(904) 768-9981", "address": "10817 New Kings Rd", "city": "Jacksonville", "state": "FL", "zip": "32219"},
    "Manheim Central Florida": {"phone": "(863) 665-9511", "address": "4805 N Frontage Rd", "city": "Lakeland", "state": "FL", "zip": "33810"},
    "Manheim Fort Lauderdale": {"phone": "(954) 791-3520", "address": "5353 S State Rd 7", "city": "Davie", "state": "FL", "zip": "33314"},
    "Manheim Atlanta": {"phone": "(404) 349-5555", "address": "5180 Campbellton Fairburn Rd", "city": "Union City", "state": "GA", "zip": "30291"},
    "Manheim Georgia": {"phone": "(770) 918-2600", "address": "7205 Campbellton Rd SW", "city": "Atlanta", "state": "GA", "zip": "30331"},
    "Manheim Houston": {"phone": "(281) 819-3600", "address": "14450 West Rd", "city": "Houston", "state": "TX", "zip": "77041"},
    "Manheim Dallas": {"phone": "(214) 330-1818", "address": "5333 W Kiest Blvd", "city": "Dallas", "state": "TX", "zip": "75236"},
    "Manheim New Jersey": {"phone": "(856) 299-6200", "address": "730 Harding Hwy", "city": "Carneys Point", "state": "NJ", "zip": "08069"},
    "Manheim New York": {"phone": "(845) 567-8550", "address": "77 Cronomer Valley Rd", "city": "Newburgh", "state": "NY", "zip": "12550"},
    "Manheim Pennsylvania": {"phone": "(717) 665-3571", "address": "1190 Lancaster Rd", "city": "Manheim", "state": "PA", "zip": "17545"},
    "Manheim Los Angeles": {"phone": "(909) 822-2261", "address": "14342 Valley Blvd", "city": "Fontana", "state": "CA", "zip": "92335"},
    "Manheim Chicago": {"phone": "(708) 389-6200", "address": "20401 Cox Ave", "city": "Matteson", "state": "IL", "zip": "60443"},
    "Manheim Denver": {"phone": "(303) 289-7550", "address": "10701 E 104th Ave", "city": "Henderson", "state": "CO", "zip": "80640"},
    "Manheim Phoenix": {"phone": "(480) 804-2300", "address": "1202 S 51st Ave", "city": "Phoenix", "state": "AZ", "zip": "85043"},
    "Manheim Detroit": {"phone": "(734) 654-8800", "address": "47884 N I-94 Service Dr", "city": "Belleville", "state": "MI", "zip": "48111"},
    "Manheim Nashville": {"phone": "(615) 244-8890", "address": "7801 Centennial Blvd", "city": "Nashville", "state": "TN", "zip": "37209"},
    "Manheim Boston": {"phone": "(508) 270-1800", "address": "276 Mendon St", "city": "Uxbridge", "state": "MA", "zip": "01569"},
    "Manheim Charlotte": {"phone": "(704) 529-5100", "address": "7601 Statesville Rd", "city": "Charlotte", "state": "NC", "zip": "28269"},
}

# ─── ADESA / OPENLANE Locations ─────────────────────────────────────────────
# Source: ADESA (Manheim/OPENLANE brand) public location directory

ADESA_LOCATIONS = {
    "ADESA Des Moines": {"phone": "(833) 289-3533", "address": "1600 SE Gateway Dr", "city": "Grimes", "state": "IA", "zip": "50111"},
    "ADESA Atlanta": {"phone": "(833) 289-3533", "address": "5055 Oakley Industrial Blvd", "city": "Fairburn", "state": "GA", "zip": "30213"},
    "ADESA Birmingham": {"phone": "(833) 289-3533", "address": "700 Sunbelt Pkwy", "city": "Moody", "state": "AL", "zip": "35004"},
    "ADESA Boston": {"phone": "(833) 289-3533", "address": "63 Western Ave", "city": "Framingham", "state": "MA", "zip": "01702"},
    "ADESA Buffalo": {"phone": "(833) 289-3533", "address": "7300 Southwestern Blvd", "city": "West Seneca", "state": "NY", "zip": "14224"},
    "ADESA Charlotte": {"phone": "(833) 289-3533", "address": "6115 Wilkinson Blvd", "city": "Belmont", "state": "NC", "zip": "28012"},
    "ADESA Chicago": {"phone": "(833) 289-3533", "address": "2200 S Ashland Ave", "city": "Chicago Heights", "state": "IL", "zip": "60411"},
    "ADESA Cleveland": {"phone": "(833) 289-3533", "address": "9200 Brookpark Rd", "city": "Parma", "state": "OH", "zip": "44129"},
    "ADESA Colorado Springs": {"phone": "(833) 289-3533", "address": "2575 Aerotech Dr", "city": "Colorado Springs", "state": "CO", "zip": "80916"},
    "ADESA Dallas": {"phone": "(833) 289-3533", "address": "3501 Lancaster-Hutchins Rd", "city": "Hutchins", "state": "TX", "zip": "75141"},
    "ADESA Indianapolis": {"phone": "(833) 289-3533", "address": "3085 N 1000 E", "city": "Plainfield", "state": "IN", "zip": "46168"},
    "ADESA Kansas City": {"phone": "(833) 289-3533", "address": "1500 E 103rd St", "city": "Kansas City", "state": "MO", "zip": "64131"},
    "ADESA Lexington": {"phone": "(833) 289-3533", "address": "151 Burt Rd", "city": "Lexington", "state": "KY", "zip": "40503"},
    "ADESA Memphis": {"phone": "(833) 289-3533", "address": "5400 Getwell Rd", "city": "Memphis", "state": "TN", "zip": "38118"},
    "ADESA Milwaukee": {"phone": "(833) 289-3533", "address": "N9394 US Highway 45", "city": "New London", "state": "WI", "zip": "54961"},
    "ADESA Minneapolis": {"phone": "(833) 289-3533", "address": "8000 Lakeland Ave N", "city": "Brooklyn Park", "state": "MN", "zip": "55445"},
    "ADESA New Jersey": {"phone": "(833) 289-3533", "address": "635 Hwy 1 S", "city": "Edison", "state": "NJ", "zip": "08817"},
    "ADESA Phoenix": {"phone": "(833) 289-3533", "address": "2701 W Durango St", "city": "Phoenix", "state": "AZ", "zip": "85009"},
    "ADESA Portland": {"phone": "(833) 289-3533", "address": "9555 NE Alderwood Rd", "city": "Portland", "state": "OR", "zip": "97220"},
    "ADESA Sacramento": {"phone": "(833) 289-3533", "address": "3837 Florin Perkins Rd", "city": "Sacramento", "state": "CA", "zip": "95826"},
    "ADESA San Diego": {"phone": "(833) 289-3533", "address": "8555 Miramar Pl", "city": "San Diego", "state": "CA", "zip": "92121"},
    "ADESA Tampa": {"phone": "(833) 289-3533", "address": "6712 E Broadway", "city": "Tampa", "state": "FL", "zip": "33619"},
    "ADESA Washington DC": {"phone": "(833) 289-3533", "address": "3701 Ironwood Pl", "city": "Landover", "state": "MD", "zip": "20785"},
}


def _normalize_name(name: str) -> str:
    """Normalize auction location name for matching.

    Handles: case differences, dashes, extra whitespace.
    'Copart - Clearwater' → 'copart clearwater'
    'COPART CLEARWATER' → 'copart clearwater'
    """
    if not name:
        return ""
    # Lowercase, replace dashes with space, collapse whitespace
    normalized = name.lower().strip()
    normalized = re.sub(r"[-–—]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _build_lookup_index() -> dict:
    """Build a normalized name → location data index from all directories."""
    index = {}
    for locations in [COPART_LOCATIONS, IAA_LOCATIONS, MANHEIM_LOCATIONS, ADESA_LOCATIONS]:
        for name, data in locations.items():
            key = _normalize_name(name)
            index[key] = {**data, "name": name}
    return index


_LOOKUP_INDEX = _build_lookup_index()


def lookup_auction_location(name: Optional[str]) -> Optional[dict]:
    """Look up auction location by name.

    Args:
        name: Auction location name (e.g., "Copart Clearwater", "IAA Tampa")

    Returns:
        Dict with phone, address, city, state, zip or None if not found.
    """
    if not name:
        return None

    key = _normalize_name(name)
    if not key:
        return None

    result = _LOOKUP_INDEX.get(key)
    if result is None:
        # Fallback 1: strip parenthetical like "Copart Clearwater (FL)"
        stripped = re.sub(r'\s*\([^)]*\)\s*', ' ', key).strip()
        stripped = re.sub(r'\s+', ' ', stripped)
        if stripped != key:
            result = _LOOKUP_INDEX.get(stripped)
        # Fallback 2: strip trailing 2-letter state code "Copart Clearwater FL"
        if result is None:
            stripped2 = re.sub(r'\s+[a-z]{2}$', '', key)
            if stripped2 != key:
                result = _LOOKUP_INDEX.get(stripped2)
    if result is None:
        logger.info(f"Auction location not found: '{name}' (normalized: '{key}')")
    return result


def find_by_city_state(city: str, state: str) -> Optional[dict]:
    """Find auction/dealer location by city and state.

    Searches Copart, IAA, and Manheim directories for a location
    matching the given city and state.

    Returns:
        Dict with name, phone, address, city, state, zip or None if not found.
    """
    if not city or not state:
        return None
    city_lower = city.lower().strip()
    state_lower = state.lower().strip()
    for loc in _LOOKUP_INDEX.values():
        loc_city = (loc.get("city") or "").lower()
        loc_state = (loc.get("state") or "").lower()
        if loc_city == city_lower and loc_state == state_lower:
            return loc
    return None
