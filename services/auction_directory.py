"""
Auction Location Directory — Copart, IAA, Manheim, ADESA, America's AA, AutoNation lookup.

When extraction returns a pickup_name like "Copart Clearwater" but no phone,
this directory provides the phone number and address for auto-fill.

Data sources: publicly available auction location directories.

To update Copart directory from CSV, run: python scripts/update_copart_directory.py <csv_file>
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Copart Locations ────────────────────────────────────────────────────────
# Source: Copart public location directory (~170+ US locations)
# Last updated: 2026-03-02

COPART_LOCATIONS = {
    # ── Alabama ──
    "Copart Birmingham": {"phone": "(205) 791-2784", "address": "1500 35th Ave N", "city": "Birmingham", "state": "AL", "zip": "35207"},
    "Copart Mobile": {"phone": "(251) 443-6470", "address": "8651 Lott Rd", "city": "Eight Mile", "state": "AL", "zip": "36613"},
    "Copart Montgomery": {"phone": "(334) 263-5765", "address": "655 Coliseum Blvd", "city": "Montgomery", "state": "AL", "zip": "36109"},
    # ── Arizona ──
    "Copart Phoenix": {"phone": "(602) 243-7301", "address": "1211 N 59th Ave", "city": "Phoenix", "state": "AZ", "zip": "85043"},
    "Copart Tucson": {"phone": "(520) 574-0303", "address": "2701 N Dos Amigos Dr", "city": "Tucson", "state": "AZ", "zip": "85745"},
    # ── Arkansas ──
    "Copart Little Rock": {"phone": "(501) 945-3142", "address": "8400 Counts Massie Rd", "city": "North Little Rock", "state": "AR", "zip": "72118"},
    # ── California ──
    "Copart Los Angeles": {"phone": "(818) 890-8944", "address": "14360 Aetna St", "city": "Van Nuys", "state": "CA", "zip": "91401"},
    "Copart Sun Valley": {"phone": "(818) 767-5580", "address": "8507 Tujunga Ave", "city": "Sun Valley", "state": "CA", "zip": "91352"},
    "Copart Rancho Cucamonga": {"phone": "(909) 476-2257", "address": "9701 Cherry Ave", "city": "Fontana", "state": "CA", "zip": "92335"},
    "Copart Sacramento": {"phone": "(916) 991-5555", "address": "8110 Calvine Rd", "city": "Sacramento", "state": "CA", "zip": "95828"},
    "Copart San Diego": {"phone": "(619) 710-2636", "address": "2295 Otay Lakes Rd", "city": "Chula Vista", "state": "CA", "zip": "91914"},
    "Copart San Bernardino": {"phone": "(909) 889-1227", "address": "1600 S Waterman Ave", "city": "San Bernardino", "state": "CA", "zip": "92408"},
    "Copart Fresno": {"phone": "(559) 268-2360", "address": "4875 E Hedges Ave", "city": "Fresno", "state": "CA", "zip": "93703"},
    "Copart Bakersfield": {"phone": "(661) 833-3212", "address": "6601 Fruitvale Ave", "city": "Bakersfield", "state": "CA", "zip": "93308"},
    "Copart Hayward": {"phone": "(510) 786-0225", "address": "2931 Industrial Pkwy SW", "city": "Hayward", "state": "CA", "zip": "94544"},
    "Copart Martinez": {"phone": "(925) 313-2060", "address": "3777 Pacheco Blvd", "city": "Martinez", "state": "CA", "zip": "94553"},
    "Copart Vallejo": {"phone": "(707) 557-2000", "address": "100 Auto Center Dr", "city": "Vallejo", "state": "CA", "zip": "94591"},
    "Copart Long Beach": {"phone": "(562) 437-4811", "address": "1701 W Pacific Coast Hwy", "city": "Long Beach", "state": "CA", "zip": "90810"},
    "Copart Antelope": {"phone": "(916) 991-5555", "address": "8286 Antelope North Rd", "city": "Antelope", "state": "CA", "zip": "95843"},
    # ── Colorado ──
    "Copart Littleton": {"phone": "(303) 791-1001", "address": "8300 Blakeland Dr", "city": "Littleton", "state": "CO", "zip": "80125"},
    "Copart Denver": {"phone": "(303) 307-0096", "address": "8201 E 96th Ave", "city": "Henderson", "state": "CO", "zip": "80640"},
    "Copart Colorado Springs": {"phone": "(719) 392-9530", "address": "2329 Sinton Rd", "city": "Colorado Springs", "state": "CO", "zip": "80916"},
    # ── Connecticut ──
    "Copart Hartford": {"phone": "(860) 292-0600", "address": "275 Middle Tpke W", "city": "Manchester", "state": "CT", "zip": "06042"},
    "Copart Brookfield": {"phone": "(203) 740-0700", "address": "19 Old Pocono Rd", "city": "Brookfield", "state": "CT", "zip": "06804"},
    # ── Florida ──
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
    "Copart Miami South": {"phone": "(305) 233-7911", "address": "16325 SW 288th St", "city": "Homestead", "state": "FL", "zip": "33033"},
    "Copart Gainesville": {"phone": "(352) 378-5454", "address": "4011 NE 39th Ave", "city": "Gainesville", "state": "FL", "zip": "32609"},
    # ── Georgia ──
    "Copart Atlanta East": {"phone": "(770) 784-5699", "address": "3015 Global Fwy", "city": "Fairburn", "state": "GA", "zip": "30213"},
    "Copart Atlanta South": {"phone": "(404) 366-2298", "address": "1930 Rex Rd", "city": "Lake City", "state": "GA", "zip": "30260"},
    "Copart Atlanta North": {"phone": "(770) 945-5568", "address": "3432 Nevins Rd", "city": "Gainesville", "state": "GA", "zip": "30507"},
    "Copart Savannah": {"phone": "(912) 826-1666", "address": "348 Edgewater Dr", "city": "Savannah", "state": "GA", "zip": "31406"},
    "Copart Macon": {"phone": "(478) 788-2270", "address": "2115 Emery Hwy", "city": "Macon", "state": "GA", "zip": "31217"},
    "Copart Augusta": {"phone": "(706) 868-7999", "address": "1638 US Highway 1", "city": "Grovetown", "state": "GA", "zip": "30813"},
    # ── Idaho ──
    "Copart Boise": {"phone": "(208) 389-9222", "address": "4200 S Orchard St", "city": "Boise", "state": "ID", "zip": "83716"},
    # ── Illinois ──
    "Copart Chicago North": {"phone": "(708) 891-6800", "address": "16401 S Lathrop Ave", "city": "Harvey", "state": "IL", "zip": "60426"},
    "Copart Chicago South": {"phone": "(773) 568-2448", "address": "13300 S Western Ave", "city": "Blue Island", "state": "IL", "zip": "60406"},
    "Copart Southern Illinois": {"phone": "(618) 397-1200", "address": "3900 Bunkum Rd", "city": "Caseyville", "state": "IL", "zip": "62232"},
    "Copart Peoria": {"phone": "(309) 697-5655", "address": "2101 W Farmington Rd", "city": "Peoria", "state": "IL", "zip": "61604"},
    # ── Indiana ──
    "Copart Indianapolis": {"phone": "(317) 272-3820", "address": "2950 S Post Rd", "city": "Indianapolis", "state": "IN", "zip": "46239"},
    "Copart Ft Wayne": {"phone": "(260) 478-0200", "address": "6131 Ardmore Ave", "city": "Fort Wayne", "state": "IN", "zip": "46809"},
    "Copart Evansville": {"phone": "(812) 867-2282", "address": "5650 E Indiana St", "city": "Evansville", "state": "IN", "zip": "47715"},
    # ── Iowa ──
    "Copart Des Moines": {"phone": "(515) 986-3386", "address": "1000 NE 60th Ave", "city": "Des Moines", "state": "IA", "zip": "50313"},
    "Copart Davenport": {"phone": "(563) 386-7950", "address": "4700 Wapello Ave", "city": "Davenport", "state": "IA", "zip": "52802"},
    # ── Kansas ──
    "Copart Wichita": {"phone": "(316) 269-4055", "address": "1600 S West St", "city": "Wichita", "state": "KS", "zip": "67213"},
    "Copart Kansas City": {"phone": "(913) 334-6600", "address": "2940 S 88th St", "city": "Kansas City", "state": "KS", "zip": "66111"},
    # ── Kentucky ──
    "Copart Louisville": {"phone": "(502) 454-2080", "address": "3704 Bells Ln", "city": "Louisville", "state": "KY", "zip": "40211"},
    "Copart Lexington": {"phone": "(859) 263-6680", "address": "3550 Leestown Rd", "city": "Lexington", "state": "KY", "zip": "40511"},
    "Copart Lexington East": {"phone": "(859) 264-7401", "address": "5921 Athens Boonesboro Rd", "city": "Lexington", "state": "KY", "zip": "40509"},
    # ── Louisiana ──
    "Copart New Orleans": {"phone": "(504) 466-0735", "address": "4701 Earhart Blvd", "city": "New Orleans", "state": "LA", "zip": "70125"},
    "Copart Baton Rouge": {"phone": "(225) 751-4243", "address": "2818 Plank Rd", "city": "Baton Rouge", "state": "LA", "zip": "70805"},
    "Copart Shreveport": {"phone": "(318) 425-2269", "address": "2515 N Market St", "city": "Shreveport", "state": "LA", "zip": "71107"},
    # ── Maryland ──
    "Copart Baltimore": {"phone": "(410) 354-0044", "address": "6800 Pulaski Hwy", "city": "Baltimore", "state": "MD", "zip": "21237"},
    "Copart Waldorf": {"phone": "(301) 374-6100", "address": "6130 Crain Hwy", "city": "Upper Marlboro", "state": "MD", "zip": "20772"},
    # ── Massachusetts ──
    "Copart Boston": {"phone": "(508) 384-3304", "address": "139 W Main St", "city": "Norton", "state": "MA", "zip": "02766"},
    "Copart North Boston": {"phone": "(978) 772-2300", "address": "77 Fitchburg Rd", "city": "Ayer", "state": "MA", "zip": "01432"},
    "Copart North Billerica": {"phone": "(978) 528-5095", "address": "55R High St", "city": "North Billerica", "state": "MA", "zip": "01862"},
    "Copart West Warren": {"phone": "(413) 436-7563", "address": "108 Old West Brookfield Rd", "city": "West Warren", "state": "MA", "zip": "01092"},
    # ── Michigan ──
    "Copart Detroit": {"phone": "(734) 479-4579", "address": "8251 Rawsonville Rd", "city": "Belleville", "state": "MI", "zip": "48111"},
    "Copart Flint": {"phone": "(810) 635-3595", "address": "6660 E Mt Morris Rd", "city": "Flushing", "state": "MI", "zip": "48433"},
    "Copart Lansing": {"phone": "(517) 882-0400", "address": "3200 Jolly Rd", "city": "Lansing", "state": "MI", "zip": "48911"},
    "Copart Grand Rapids": {"phone": "(616) 532-2222", "address": "6350 Roger B Chaffee Memorial Blvd SE", "city": "Grand Rapids", "state": "MI", "zip": "49548"},
    "Copart Kalamazoo": {"phone": "(269) 343-1710", "address": "8500 Stadium Dr", "city": "Kalamazoo", "state": "MI", "zip": "49009"},
    # ── Minnesota ──
    "Copart Minneapolis": {"phone": "(612) 726-5500", "address": "8535 13th Ave E", "city": "Bloomington", "state": "MN", "zip": "55425"},
    "Copart St Cloud": {"phone": "(320) 251-6000", "address": "2525 2nd St S", "city": "St Cloud", "state": "MN", "zip": "56301"},
    # ── Mississippi ──
    "Copart Jackson": {"phone": "(601) 922-4840", "address": "5425 Highway 49 S", "city": "Jackson", "state": "MS", "zip": "39272"},
    # ── Missouri ──
    "Copart St Louis": {"phone": "(314) 739-3700", "address": "2820 Fee Fee Rd", "city": "Bridgeton", "state": "MO", "zip": "63044"},
    "Copart Kansas City East": {"phone": "(816) 252-0700", "address": "18801 E Valley View Pkwy", "city": "Independence", "state": "MO", "zip": "64055"},
    "Copart Springfield": {"phone": "(417) 889-3600", "address": "3350 E Talmage St", "city": "Springfield", "state": "MO", "zip": "65803"},
    # ── Nebraska ──
    "Copart Omaha": {"phone": "(402) 896-3232", "address": "10425 S 144th St", "city": "Omaha", "state": "NE", "zip": "68138"},
    "Copart Lincoln": {"phone": "(402) 466-1800", "address": "5544 W Huntington Ave", "city": "Lincoln", "state": "NE", "zip": "68521"},
    # ── Nevada ──
    "Copart Las Vegas": {"phone": "(702) 263-0610", "address": "4650 Mitchell St", "city": "North Las Vegas", "state": "NV", "zip": "89081"},
    "Copart Reno": {"phone": "(775) 331-3300", "address": "8185 Mushroom Rd", "city": "Reno", "state": "NV", "zip": "89506"},
    # ── New Hampshire ──
    "Copart Candia": {"phone": "(603) 483-8300", "address": "15 Depot Rd", "city": "Candia", "state": "NH", "zip": "03034"},
    # ── New Jersey ──
    "Copart Newark": {"phone": "(973) 589-5678", "address": "55 Lyon St", "city": "Newark", "state": "NJ", "zip": "07105"},
    "Copart Somerville": {"phone": "(908) 707-0404", "address": "301 Old York Rd", "city": "Bridgewater", "state": "NJ", "zip": "08807"},
    "Copart Glassboro": {"phone": "(856) 307-4039", "address": "500 Sharptown Auburn Rd", "city": "Swedesboro", "state": "NJ", "zip": "08085"},
    "Copart Trenton": {"phone": "(609) 890-4900", "address": "400 Shiloh Rd", "city": "Hamilton", "state": "NJ", "zip": "08691"},
    # ── New Mexico ──
    "Copart Albuquerque": {"phone": "(505) 352-5000", "address": "10300 Avalon Rd NW", "city": "Albuquerque", "state": "NM", "zip": "87105"},
    # ── New York ──
    "Copart Brookhaven": {"phone": "(631) 289-3535", "address": "130 Horseblock Rd", "city": "Brookhaven", "state": "NY", "zip": "11719"},
    "Copart Newburgh": {"phone": "(845) 567-7820", "address": "1392 Route 300", "city": "Newburgh", "state": "NY", "zip": "12550"},
    "Copart Albany": {"phone": "(518) 465-3200", "address": "1604 State Route 9P", "city": "Saratoga Springs", "state": "NY", "zip": "12866"},
    "Copart Rochester": {"phone": "(585) 426-6300", "address": "1800 Scottsville Rd", "city": "Rochester", "state": "NY", "zip": "14623"},
    "Copart Buffalo": {"phone": "(716) 662-0600", "address": "3156 S Park Ave", "city": "Lackawanna", "state": "NY", "zip": "14218"},
    "Copart Le Roy": {"phone": "(585) 768-8160", "address": "4 West Ave", "city": "LeRoy", "state": "NY", "zip": "14482"},
    "Copart Syracuse": {"phone": "(315) 437-2700", "address": "7500 E Taft Rd", "city": "Syracuse", "state": "NY", "zip": "13212"},
    # ── North Carolina ──
    "Copart Charlotte": {"phone": "(704) 391-4146", "address": "3425 Highway 601 S", "city": "Concord", "state": "NC", "zip": "28025"},
    "Copart Raleigh": {"phone": "(919) 553-3715", "address": "261 Hwy 210 East", "city": "Angier", "state": "NC", "zip": "27501"},
    "Copart China Grove": {"phone": "(704) 857-9380", "address": "2011 E Main St", "city": "China Grove", "state": "NC", "zip": "28023"},
    "Copart Lumberton": {"phone": "(910) 618-2600", "address": "105 VFW Rd", "city": "Lumberton", "state": "NC", "zip": "28358"},
    "Copart Mebane": {"phone": "(919) 563-8777", "address": "1600 S Third St", "city": "Mebane", "state": "NC", "zip": "27302"},
    # ── Ohio ──
    "Copart Columbus": {"phone": "(614) 443-6503", "address": "1155 S High St", "city": "Columbus", "state": "OH", "zip": "43207"},
    "Copart Cleveland": {"phone": "(330) 225-2000", "address": "8787 Columbia Rd", "city": "Valley View", "state": "OH", "zip": "44125"},
    "Copart Cleveland West": {"phone": "(440) 327-5959", "address": "46920 Middle Ridge Rd", "city": "Lorain", "state": "OH", "zip": "44053"},
    "Copart Cincinnati": {"phone": "(513) 771-8255", "address": "985 E Crescentville Rd", "city": "Cincinnati", "state": "OH", "zip": "45246"},
    "Copart Dayton": {"phone": "(937) 233-7332", "address": "5600 N Dixie Dr", "city": "Dayton", "state": "OH", "zip": "45414"},
    "Copart Akron": {"phone": "(330) 628-3377", "address": "5443 S Arlington Rd", "city": "Akron", "state": "OH", "zip": "44319"},
    # ── Oklahoma ──
    "Copart Oklahoma City": {"phone": "(405) 631-3337", "address": "7300 S Byers Ave", "city": "Oklahoma City", "state": "OK", "zip": "73149"},
    "Copart Tulsa": {"phone": "(918) 437-7000", "address": "900 N Union Ave", "city": "Tulsa", "state": "OK", "zip": "74127"},
    # ── Oregon ──
    "Copart Portland": {"phone": "(503) 257-1110", "address": "15001 NE Cabot Ct", "city": "Portland", "state": "OR", "zip": "97230"},
    "Copart Eugene": {"phone": "(541) 689-7111", "address": "4550 Cloudburst Way", "city": "Eugene", "state": "OR", "zip": "97402"},
    # ── Pennsylvania ──
    "Copart Philadelphia": {"phone": "(215) 365-7335", "address": "790 E Pennsylvania Blvd", "city": "Feasterville", "state": "PA", "zip": "19053"},
    "Copart Pittsburgh": {"phone": "(724) 457-1964", "address": "100 Industrial Blvd", "city": "West Mifflin", "state": "PA", "zip": "15122"},
    "Copart Harrisburg": {"phone": "(717) 564-6110", "address": "200 S Hershey Rd", "city": "Harrisburg", "state": "PA", "zip": "17112"},
    "Copart Allentown": {"phone": "(610) 395-0700", "address": "5447 Catasauqua Rd", "city": "Whitehall", "state": "PA", "zip": "18052"},
    "Copart Scranton": {"phone": "(570) 346-9000", "address": "1200 Sans Souci Pkwy", "city": "Hanover Township", "state": "PA", "zip": "18706"},
    # ── Rhode Island ──
    "Copart Exeter": {"phone": "(401) 294-6600", "address": "10 Industrial Dr", "city": "Exeter", "state": "RI", "zip": "02822"},
    # ── South Carolina ──
    "Copart Columbia": {"phone": "(803) 754-7100", "address": "2232 Fish Hatchery Rd", "city": "West Columbia", "state": "SC", "zip": "29172"},
    "Copart Spartanburg": {"phone": "(864) 578-8680", "address": "8529 Asheville Hwy", "city": "Spartanburg", "state": "SC", "zip": "29303"},
    "Copart Charleston": {"phone": "(843) 821-0441", "address": "2100 County Line Rd", "city": "Ladson", "state": "SC", "zip": "29456"},
    # ── Tennessee ──
    "Copart Nashville": {"phone": "(615) 399-4219", "address": "1609 Antioch Pike", "city": "Nashville", "state": "TN", "zip": "37211"},
    "Copart Memphis": {"phone": "(901) 345-4985", "address": "4609 E Raines Rd", "city": "Memphis", "state": "TN", "zip": "38118"},
    "Copart Knoxville": {"phone": "(865) 947-6490", "address": "5300 Clinton Hwy", "city": "Knoxville", "state": "TN", "zip": "37912"},
    "Copart Chattanooga": {"phone": "(423) 894-7300", "address": "2728 E 37th St", "city": "Chattanooga", "state": "TN", "zip": "37407"},
    # ── Texas ──
    "Copart Houston": {"phone": "(281) 999-0440", "address": "2535 West Rd", "city": "Houston", "state": "TX", "zip": "77038"},
    "Copart Houston East": {"phone": "(713) 450-3055", "address": "16602 East Fwy", "city": "Channelview", "state": "TX", "zip": "77530"},
    "Copart Dallas": {"phone": "(972) 225-7602", "address": "505 S Central Expy", "city": "Grand Prairie", "state": "TX", "zip": "75051"},
    "Copart Ft Worth": {"phone": "(817) 447-4951", "address": "3748 McPherson Blvd", "city": "Fort Worth", "state": "TX", "zip": "76140"},
    "Copart San Antonio": {"phone": "(210) 628-2622", "address": "11275 Applewhite Rd", "city": "San Antonio", "state": "TX", "zip": "78224"},
    "Copart Austin": {"phone": "(512) 821-0150", "address": "2191 Highway 21 W", "city": "Dale", "state": "TX", "zip": "78616"},
    "Copart Corpus Christi": {"phone": "(361) 289-7277", "address": "4701 Agnes St", "city": "Corpus Christi", "state": "TX", "zip": "78405"},
    "Copart El Paso": {"phone": "(915) 855-7700", "address": "14564 Gateway Blvd W", "city": "El Paso", "state": "TX", "zip": "79927"},
    "Copart Lufkin": {"phone": "(936) 639-3128", "address": "5606 US Highway 59 N", "city": "Lufkin", "state": "TX", "zip": "75904"},
    "Copart Abilene": {"phone": "(325) 695-8555", "address": "7150 Interstate 20 W", "city": "Abilene", "state": "TX", "zip": "79601"},
    "Copart Waco": {"phone": "(254) 662-0900", "address": "5609 Texas Central Pkwy", "city": "Waco", "state": "TX", "zip": "76712"},
    "Copart Andrews": {"phone": "(432) 524-6666", "address": "204 NW 4200", "city": "Andrews", "state": "TX", "zip": "79714"},
    "Copart Crashedtoys Dallas": {"phone": "(972) 225-7602", "address": "505 S Central Expy", "city": "Grand Prairie", "state": "TX", "zip": "75051"},
    # ── Utah ──
    "Copart Salt Lake City": {"phone": "(801) 596-5700", "address": "750 S 4070 W", "city": "Salt Lake City", "state": "UT", "zip": "84104"},
    "Copart Ogden": {"phone": "(801) 399-8644", "address": "1600 S 1100 W", "city": "Ogden", "state": "UT", "zip": "84401"},
    # ── Virginia ──
    "Copart Richmond": {"phone": "(804) 232-6700", "address": "1200 E Belt Blvd", "city": "Richmond", "state": "VA", "zip": "23224"},
    "Copart Hampton": {"phone": "(757) 826-3699", "address": "410 E Mercury Blvd", "city": "Hampton", "state": "VA", "zip": "23669"},
    "Copart Fredericksburg": {"phone": "(540) 786-3000", "address": "600 Southpoint Pkwy", "city": "Fredericksburg", "state": "VA", "zip": "22407"},
    "Copart Danville": {"phone": "(434) 793-2400", "address": "153 Highway 29 Bus", "city": "Danville", "state": "VA", "zip": "24541"},
    "Copart Suffolk": {"phone": "(757) 539-6000", "address": "2533 Pruden Blvd", "city": "Suffolk", "state": "VA", "zip": "23434"},
    # ── Washington ──
    "Copart Seattle": {"phone": "(253) 735-2620", "address": "2800 W Commodore Way", "city": "Seattle", "state": "WA", "zip": "98199"},
    "Copart Spokane": {"phone": "(509) 928-2020", "address": "16002 E Euclid Ave", "city": "Spokane Valley", "state": "WA", "zip": "99216"},
    "Copart North Seattle": {"phone": "(360) 805-4500", "address": "2001 N Broadway", "city": "Everett", "state": "WA", "zip": "98201"},
    "Copart Pasco": {"phone": "(509) 547-3633", "address": "2606 E Ainsworth Ave", "city": "Pasco", "state": "WA", "zip": "99301"},
    # ── West Virginia ──
    "Copart Charleston WV": {"phone": "(304) 756-2855", "address": "1200 MacCorkle Ave SE", "city": "Charleston", "state": "WV", "zip": "25314"},
    # ── Wisconsin ──
    "Copart Milwaukee": {"phone": "(414) 764-8600", "address": "8800 S 13th St", "city": "Oak Creek", "state": "WI", "zip": "53154"},
    "Copart Madison": {"phone": "(608) 222-5200", "address": "5500 Femrite Dr", "city": "Madison", "state": "WI", "zip": "53718"},
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
    "ADESA Denver": {"phone": "(833) 289-3533", "address": "5000 S Federal Blvd", "city": "Englewood", "state": "CO", "zip": "80110"},
    "ADESA Houston": {"phone": "(833) 289-3533", "address": "4526 N Sam Houston Pkwy E", "city": "Houston", "state": "TX", "zip": "77032"},
    "ADESA Las Vegas": {"phone": "(833) 289-3533", "address": "3650 N Nellis Blvd", "city": "North Las Vegas", "state": "NV", "zip": "89032"},
    "ADESA Los Angeles": {"phone": "(833) 289-3533", "address": "3560 Etiwanda Ave", "city": "Mira Loma", "state": "CA", "zip": "91752"},
    "ADESA New York": {"phone": "(833) 289-3533", "address": "175 Peconic Ave", "city": "Medford", "state": "NY", "zip": "11763"},
    "ADESA Orlando": {"phone": "(833) 289-3533", "address": "1200 Dolgner Pl", "city": "Sanford", "state": "FL", "zip": "32771"},
    "ADESA Philadelphia": {"phone": "(833) 289-3533", "address": "333 N Ship Rd", "city": "Exton", "state": "PA", "zip": "19341"},
    "ADESA San Francisco": {"phone": "(833) 289-3533", "address": "5800 S Chrisman Rd", "city": "Tracy", "state": "CA", "zip": "95377"},
    "ADESA Seattle": {"phone": "(833) 289-3533", "address": "1818 C St SW", "city": "Auburn", "state": "WA", "zip": "98001"},
    "ADESA St. Louis": {"phone": "(833) 289-3533", "address": "1370 N Lindbergh Blvd", "city": "Hazelwood", "state": "MO", "zip": "63042"},
}

# ─── America's Auto Auction Locations ─────────────────────────────────────────
# Source: americasaa.com public location directory (verified locations only)

AMERICAS_AA_LOCATIONS = {
    "America's Auto Auction Houston": {"phone": "(281) 819-3600", "address": "1826 Almeda Genoa Rd", "city": "Houston", "state": "TX", "zip": "77047"},
    "America's Auto Auction Atlanta": {"phone": "(770) 382-1010", "address": "440 Joe Frank Harris Pkwy SE", "city": "Cartersville", "state": "GA", "zip": "30120"},
    "America's Auto Auction Dallas": {"phone": "(972) 445-1044", "address": "219 N Loop 12", "city": "Irving", "state": "TX", "zip": "75061"},
    "America's Auto Auction Northern California": {"phone": "(707) 864-1040", "address": "250 Dittmer Rd", "city": "Fairfield", "state": "CA", "zip": "94534"},
    "America's Auto Auction Las Vegas": {"phone": "(702) 255-0990", "address": "3038 Losee Rd", "city": "North Las Vegas", "state": "NV", "zip": "89030"},
    "America's Auto Auction Jacksonville": {"phone": "(904) 764-7653", "address": "11982 New Kings Rd", "city": "Jacksonville", "state": "FL", "zip": "32219"},
    "America's Auto Auction Tampa Bay": {"phone": "(727) 572-8800", "address": "3010 Scherer Dr N", "city": "St. Petersburg", "state": "FL", "zip": "33716"},
    "America's Auto Auction Miami": {"phone": "(727) 572-8800", "address": "5895 NW 167th St", "city": "Hialeah", "state": "FL", "zip": "33015"},
    "America's Auto Auction New Jersey": {"phone": "(732) 566-3403", "address": "1005 State Route 33", "city": "Freehold", "state": "NJ", "zip": "07728"},
    "America's Auto Auction Chicago": {"phone": "(708) 389-4488", "address": "14001 Karlov Ave", "city": "Crestwood", "state": "IL", "zip": "60418"},
    "America's Auto Auction Kansas City": {"phone": "(816) 502-3318", "address": "11101 N Congress Ave", "city": "Kansas City", "state": "MO", "zip": "64153"},
    "America's Auto Auction Toledo": {"phone": "(419) 872-0872", "address": "9797 Freemont Pike", "city": "Perrysburg", "state": "OH", "zip": "43551"},
    "America's Auto Auction St. Louis": {"phone": "(618) 332-1227", "address": "721 S 45th St", "city": "East St. Louis", "state": "IL", "zip": "62207"},
    "America's Auto Auction Oklahoma": {"phone": "(918) 794-0660", "address": "66 N Mingo Rd", "city": "Tulsa", "state": "OK", "zip": "74116"},
    "America's Auto Auction Harrisburg": {"phone": "(717) 697-2222", "address": "1100 S York St", "city": "Mechanicsburg", "state": "PA", "zip": "17055"},
    "America's Auto Auction Savannah": {"phone": "(912) 965-9901", "address": "1712 Dean Forest Rd", "city": "Savannah", "state": "GA", "zip": "31408"},
    "America's Auto Auction New Orleans": {"phone": "(985) 345-3302", "address": "18310 Wood-Scale Rd", "city": "Hammond", "state": "LA", "zip": "70401"},
    "America's Auto Auction Austin": {"phone": "(512) 268-6600", "address": "16611 S I-35 Frontage Rd", "city": "Buda", "state": "TX", "zip": "78610"},
    "America's Auto Auction San Antonio": {"phone": "(210) 298-5477", "address": "13510 Toepperwein Rd", "city": "Live Oak", "state": "TX", "zip": "78233"},
    "America's Auto Auction Virginia": {"phone": "(757) 487-3464", "address": "656 S Military Hwy", "city": "Virginia Beach", "state": "VA", "zip": "23464"},
    "America's Auto Auction Baton Rouge": {"phone": "(225) 778-3737", "address": "3960 Blount Rd", "city": "Baton Rouge", "state": "LA", "zip": "70807"},
    "America's Auto Auction Greenville": {"phone": "(864) 801-1199", "address": "2415 SC-101", "city": "Greer", "state": "SC", "zip": "29651"},
}

# ─── AutoNation Auto Auction Locations ────────────────────────────────────────
# Source: autonationautoauction.com (only 4 physical auction locations exist)

AUTONATION_LOCATIONS = {
    "AutoNation Auto Auction Atlanta": {"phone": "(855) 907-2622", "address": "2491 Old Anvil Block Rd", "city": "Ellenwood", "state": "GA", "zip": "30294"},
    "AutoNation Auto Auction Houston": {"phone": "(855) 905-2622", "address": "608 W Mitchell Rd", "city": "Houston", "state": "TX", "zip": "77037"},
    "AutoNation Auto Auction Orlando": {"phone": "(855) 906-2622", "address": "650 N US Highway 17-92", "city": "Longwood", "state": "FL", "zip": "32750"},
    "AutoNation Auto Auction Los Angeles": {"phone": "(855) 904-2622", "address": "777 W 190th St", "city": "Gardena", "state": "CA", "zip": "90248"},
}


def _normalize_name(name: str) -> str:
    """Normalize auction location name for matching.

    Handles: case differences, dashes, extra whitespace.
    'Copart - Clearwater' → 'copart clearwater'
    'COPART CLEARWATER' → 'copart clearwater'
    """
    if not name:
        return ""
    # Lowercase, strip apostrophes, replace dashes with space, collapse whitespace
    normalized = name.lower().strip()
    normalized = normalized.replace("'", "").replace("\u2019", "")
    normalized = re.sub(r"[-\u2013\u2014]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _build_lookup_index() -> dict:
    """Build a normalized name → location data index from all directories."""
    index = {}
    for locations in [COPART_LOCATIONS, IAA_LOCATIONS, MANHEIM_LOCATIONS, ADESA_LOCATIONS, AMERICAS_AA_LOCATIONS, AUTONATION_LOCATIONS]:
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
