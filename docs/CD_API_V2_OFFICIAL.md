# CD API V2 Official Schema Reference

> Source: Central Dispatch Marketplace API V2 documentation (confirmed Mar 2026).
> This file is the single source of truth for CD API field names.

## Authentication

```
Token URL:  https://id.centraldispatch.com/connect/token
API Base:   https://marketplace-api.centraldispatch.com
Scope:      marketplace
Grant Type: client_credentials
```

### Headers (all requests)
```
Content-Type: application/vnd.coxauto.v2+json
Accept: application/vnd.coxauto.v2+json
Authorization: Bearer {token}
```

### Update (PUT) additional headers
```
If-Match: {etag}
```

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/listings` | Create listing |
| PUT | `/listings/id/{listingId}` | Update listing (requires ETag) |
| GET | `/listings/id/{listingId}` | Get listing by ID |
| GET | `/listings` | Search listings |

---

## Create/Update Listing Schema

### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `externalId` | string (≤50) | YES | Your unique load ID |
| `partnerReferenceId` | string (≤50) | NO | Partner reference |
| `shipperOrderId` | string (≤50) | NO | Shipper order ID |
| `trailerType` | string | YES | `OPEN` or `ENCLOSED` |
| `hasInOpVehicle` | boolean | YES | Has inoperable vehicle |
| `requiresInspection` | boolean | NO | Require carrier inspection |
| `availableDate` | datetime | YES | ISO 8601 (YYYY-MM-DDT00:00:00Z) |
| `expirationDate` | datetime | NO | Listing expiration |
| `desiredDeliveryDate` | datetime | NO | Desired delivery |
| `loadSpecificTerms` | string (≤500) | NO | Load-specific terms |
| `transportationReleaseNotes` | string | NO | Release notes |

---

### price Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `price.total` | number | YES | Total transport price |

#### price.cod

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `price.cod.amount` | number | NO | COD amount |
| `price.cod.paymentMethod` | string | NO | `CASH_CERTIFIED_FUNDS`, `CHECK`, `MONEY_ORDER`, `COMCHEK`, `TCHECK`, `COMPANY_CHECK`, `CASH`, `CASHIERS_CHECK`, `ACH`, `WIRE` |
| `price.cod.paymentLocation` | string | NO | `DELIVERY`, `PICKUP` |

#### price.balance

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `price.balance.amount` | number | NO | Balance amount |
| `price.balance.balancePaymentMethod` | string | NO | `CERTIFIED_FUNDS`, `CHECK`, `MONEY_ORDER`, `COMCHEK`, `TCHECK`, `COMPANY_CHECK`, `CASH`, `CASHIERS_CHECK`, `ACH`, `WIRE` |
| `price.balance.paymentTime` | string | NO | `FIFTEEN_BUSINESS_DAYS`, `FIVE_BUSINESS_DAYS`, `IMMEDIATELY`, `TEN_BUSINESS_DAYS`, `THIRTY_BUSINESS_DAYS`, `TWO_BUSINESS_DAYS` |
| `price.balance.balancePaymentTermsBeginOn` | string | NO | `DELIVERY`, `PICKUP`, `RECEIVING_SIGNED_BOL` |

---

### stops[] Array

Each stop object:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `stopNumber` | integer | YES | 1=pickup, 2=delivery |
| `locationName` | string | NO | Facility/business name |
| `address` | string | YES | Street address |
| `city` | string | YES | City |
| `state` | string | YES | 2-letter US state |
| `postalCode` | string | YES | 5-digit ZIP |
| `country` | string | NO | Default: "US" |
| `locationType` | string | NO | See locationType values below |
| `phone` | string | NO | Facility main phone |
| `contactName` | string | NO | Contact person name |
| `contactPhone` | string | NO | Contact person phone |
| `contactEmailAddress` | string | NO | Contact email (**NOT** "email") |
| `buyerNumber` | string | NO | Buyer reference / member ID (**NOT** "buyerReferenceNumber") |
| `operatingHours` | string | NO | Facility hours |

#### locationType Values
```
Unspecified, Airport, RentalCenter, Auction, AuctionSatelliteLot,
CommercialBusiness, CorporateOfficePlant, CrossDockSatelliteStagingLot,
Dealership, Impound, MarshallingYard, MilitaryBase, MobileAuction,
Port, RailYard, ReconFacility, RentalCar, RetailSite, Repo,
Residence, ServiceCenter, ConsumerMoves, Terminal, Other,
MechanicShop, Warehouse, ParkingLot
```

---

### vehicles[] Array

Each vehicle object:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pickupStopNumber` | integer | YES | Must match a stop |
| `dropoffStopNumber` | integer | YES | Must match a stop |
| `vin` | string | NO | 17-char VIN |
| `year` | integer | NO | Model year |
| `make` | string | NO | Manufacturer |
| `model` | string | NO | Model name |
| `color` | string | NO | Vehicle color |
| `vehicleType` | string | NO | See vehicleType values below |
| `lotNumber` | string | NO | Auction lot number |
| `isInoperable` | boolean | YES | Operable/inoperable |
| `additionalInfo` | string | NO | Gate pass, release info |
| `trim` | string | NO | Vehicle trim |
| `licensePlate` | string | NO | License plate |
| `licensePlateState` | string | NO | Plate state |
| `tariff` | number | NO | Per-vehicle tariff |
| `externalVehicleId` | string | NO | External vehicle ID |

#### vehicleType Values
```
ATV, BOAT, CAR, COUPE, DUALLY, EXOTIC_SPORTS, HATCHBACK,
HEAVY_EQUIPMENT, LARGE_YACHT, MINIVAN, MOTORCYCLE, OTHER,
PICKUP, RECREATIONAL_VEHICLE, SEDAN, SMALL_YACHT, SUV,
TRAILER, TRAVEL_TRAILER, TRUCK, VAN, WAGON
```

---

### marketplaces[] Array

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `marketplaceId` | integer | YES | 10000 = Super Dispatch + CD |
| `searchable` | boolean | NO | Visible in marketplace |
| `digitalOffersEnabled` | boolean | NO | Accept digital offers |
| `offersAutoAcceptEnabled` | boolean | NO | Auto-accept offers |
| `autoDispatchOnOfferAccepted` | boolean | NO | Auto-dispatch |
| `predispatchNotes` | string | NO | Notes shown pre-dispatch |
| `customersExcludedFromOffers` | array | NO | Excluded customer IDs |

---

### tags[] Array

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | YES | Tag name (**NOT** "key") |
| `value` | string | YES | Tag value |

---

## Response Codes

| Code | Meaning |
|------|---------|
| 201 | Created (POST) |
| 200/204 | Updated (PUT) |
| 409 | Conflict (duplicate externalId) |
| 412 | Precondition Failed (ETag mismatch) |
| 429 | Rate Limited |

> **Warning:** CD API V2 silently ignores unknown fields and returns 201/200.
> Always verify field names against this schema.

---

## Known Field Name Traps

| Wrong | Correct | Notes |
|-------|---------|-------|
| `buyerReferenceNumber` | `buyerNumber` | Was silently ignored |
| `email` | `contactEmailAddress` | Was silently ignored |
| `tags[].key` | `tags[].name` | Was silently ignored |
