# Central Dispatch Listings API v2 -- Field Matrix

> Maps every UI/DB field to the canonical CD API v2 Create Listing payload.
> Source of truth: CD API v2 docs + `cd_field_mapping_v2.yaml`.

## Payload Envelope

| CD Field Path | Type | Required | Source / Autofill | Current UI/DB Field | Gap? |
|---|---|---|---|---|---|
| `externalId` | string(50) | yes | Generated: `DC-{date}-{auction}-{uuid8}` | auto | -- |
| `shipperOrderId` | string | no | `clickup_task_id` | runs.clickup_task_id | -- |
| `partnerReferenceId` | string(50) | no | `CD-RUN-{run_id}` | auto | -- |
| `trailerType` | enum | yes | Default `OPEN`; `ENCLOSED` for luxury makes | cd_defaults / rule | -- |
| `hasInOpVehicle` | bool | yes | From `vehicle_is_inoperable` | extraction | -- |
| `availableDate` | date | yes | `utcnow()` | auto | -- |
| `expirationDate` | date | no | `availableDate + 14d` | auto | -- |
| `transportationReleaseNotes` | string | no | Template per auction type | extraction + template | -- |

## Price Object (`price`)

| CD Field Path | Type | Required | Source | Current Field | Gap? |
|---|---|---|---|---|---|
| `price.total` | float | yes | `total_amount` or default $450 | extraction / default | **MI API not integrated** |
| `price.cod.amount` | float | no | = `price.total` | auto | -- |
| `price.cod.paymentMethod` | enum | no | Default `CASH_CERTIFIED_FUNDS` | cd_defaults | -- |
| `price.cod.paymentLocation` | enum | no | Default `DELIVERY` | cd_defaults | -- |
| `price.balance` | float | no | 0.0 | -- | **Not in payload** |

## SLA Object (`sla`) -- NEW

| CD Field Path | Type | Required | Source | Current Field | Gap? |
|---|---|---|---|---|---|
| `sla.type` | enum(`STANDARD`,`EXPEDITED`,`GUARANTEED`) | no | Default `STANDARD` | -- | **Not in schema** |
| `sla.pickupByDate` | date | no | -- | -- | **Not in schema** |
| `sla.deliverByDate` | date | no | -- | -- | **Not in schema** |

## Stops Array (`stops[]`) -- exactly 2

| CD Field Path | Type | Required | Source | Current Field | Gap? |
|---|---|---|---|---|---|
| `stops[0].stopNumber` | int | yes | Always `1` (pickup) | auto | -- |
| `stops[0].locationType` | enum | no | `AUCTION` / `BUSINESS` / `RESIDENCE` | Default `AUCTION` | -- |
| `stops[0].locationName` | string | no | `pickup_name` or `{auction} Pickup` | extraction | -- |
| `stops[0].address` | string | yes | `pickup_address` | extraction | -- |
| `stops[0].city` | string | yes | `pickup_city` | extraction | -- |
| `stops[0].state` | string(2) | yes | `pickup_state` | extraction | -- |
| `stops[0].postalCode` | string | yes | `pickup_zip` | extraction | -- |
| `stops[0].country` | string(2) | no | Default `US` | auto | -- |
| `stops[0].contactName` | string | no | `pickup_contact` | extraction | -- |
| `stops[0].phone` | string | no | `pickup_phone` | extraction | -- |
| `stops[1].stopNumber` | int | yes | Always `2` (delivery) | auto | -- |
| `stops[1].locationType` | enum | no | `BUSINESS` | Default `BUSINESS` | -- |
| `stops[1].locationName` | string | no | `delivery_name` / warehouse name | warehouse const | -- |
| `stops[1].address` | string | yes | `delivery_address` / warehouse addr | warehouse const | -- |
| `stops[1].city` | string | yes | `delivery_city` / warehouse city | warehouse const | -- |
| `stops[1].state` | string(2) | yes | `delivery_state` / warehouse state | warehouse const | -- |
| `stops[1].postalCode` | string | yes | `delivery_zip` / warehouse zip | warehouse const | -- |
| `stops[1].country` | string(2) | no | Default `US` | auto | -- |
| `stops[1].contactName` | string | no | warehouse contact | warehouse const | -- |
| `stops[1].phone` | string | no | warehouse phone | warehouse const | -- |

## Vehicles Array (`vehicles[]`) -- 1..12, no duplicate VINs

| CD Field Path | Type | Required | Source | Current Field | Gap? |
|---|---|---|---|---|---|
| `vehicles[].pickupStopNumber` | int | yes | `1` | auto | -- |
| `vehicles[].dropoffStopNumber` | int | yes | `2` | auto | -- |
| `vehicles[].vin` | string(17) | yes | `vehicle_vin` | extraction | -- |
| `vehicles[].year` | int | yes | `vehicle_year` | extraction | -- |
| `vehicles[].make` | string | yes | `vehicle_make` | extraction | -- |
| `vehicles[].model` | string | yes | `vehicle_model` | extraction | -- |
| `vehicles[].vehicleType` | enum | no | Default `AUTO` | cd_defaults | -- |
| `vehicles[].isInoperable` | bool | no | `vehicle_is_inoperable` | extraction | -- |
| `vehicles[].color` | string | no | `vehicle_color` | extraction | -- |
| `vehicles[].lotNumber` | string | no | `lot_number` | extraction | -- |
| `vehicles[].shippingSpecs.length` | float | no | -- | -- | **Not extracted** |
| `vehicles[].shippingSpecs.width` | float | no | -- | -- | **Not extracted** |
| `vehicles[].shippingSpecs.height` | float | no | -- | -- | **Not extracted** |
| `vehicles[].shippingSpecs.weight` | float | no | -- | -- | **Not extracted** |

## Marketplaces Array (`marketplaces[]`)

| CD Field Path | Type | Required | Source | Current Field | Gap? |
|---|---|---|---|---|---|
| `marketplaces[].marketplaceId` | int | yes | Config constant | `12345` placeholder | **Needs real ID** |
| `marketplaces[].searchable` | bool | no | Default `true` | cd_defaults | -- |
| `marketplaces[].digitalOffersEnabled` | bool | no | Default `false` | cd_defaults | -- |
| `marketplaces[].makeOffersEnabled` | bool | no | Default `true` | -- | **Not in payload** |

## Tags Array (`tags[]`)

| CD Field Path | Type | Required | Source | Current Field | Gap? |
|---|---|---|---|---|---|
| `tags[].name` | string | no | Auction-specific | cd_field_mapping_v2 | -- |
| `tags[].value` | string | no | Auction-specific | cd_field_mapping_v2 | -- |

Example tags: `{name: "auctionSource", value: "COPART"}`, `{name: "auctionType", value: "SALVAGE"}`

## Identified Gaps Summary

| # | Gap | Impact | Resolution |
|---|-----|--------|------------|
| 1 | `price.balance` not in payload | Low -- optional field | Add to schema, default 0 |
| 2 | `sla` object missing entirely | Medium -- needed for expedited | Add Pydantic schema + UI section |
| 3 | `marketplaceId` is placeholder `12345` | High -- wrong marketplace | Load from config / env |
| 4 | `makeOffersEnabled` not in payload | Low -- optional | Add to marketplace schema |
| 5 | Vehicle `shippingSpecs` not extracted | Low -- optional | Leave empty, add to schema |
| 6 | Market Intelligence API not integrated | Medium -- pricing defaults to $450 | Future: PROMPT 5 |
| 7 | Accept header is `application/json` | High -- should be `application/vnd.coxauto.v2+json` | Fix in cd_client.py |

---

*Last updated: 2026-02-05*
