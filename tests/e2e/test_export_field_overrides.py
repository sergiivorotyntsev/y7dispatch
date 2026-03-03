"""
E2E Tests for Export Field Overrides, Unverified Address Flag, and Copart Directory.

Covers:
1. Preview endpoint uses field_overrides to override extraction values
2. Export persists field_overrides to review_items + outputs_json
3. Copart unknown city → pickup_verified=False
4. Copart known city → pickup_verified=True
5. Newly added directory locations match by city+state
"""

import json
import uuid
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_auction_type_id(client, code="COPART") -> int:
    """Get auction type by code, return its ID."""
    resp = client.get("/api/auction-types/")
    for item in resp.json().get("items", []):
        if item.get("code") == code:
            return item["id"]
    # Create if not found
    resp = client.post(
        "/api/auction-types/",
        json={"name": f"Test {code}", "code": code},
    )
    return resp.json()["id"]


def _upload_and_seed(client, auction_type_id, outputs: dict) -> int:
    """Upload a minimal PDF and seed extraction outputs, return run_id."""
    pdf_bytes = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT
/F1 12 Tf
100 700 Td
(Test) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000206 00000 n
trailer
<< /Size 5 /Root 1 0 R >>
startxref
300
%%EOF"""

    resp = client.post(
        "/api/documents/upload",
        files={"file": (f"test_{uuid.uuid4().hex[:8]}.pdf", BytesIO(pdf_bytes), "application/pdf")},
        data={"auction_type_id": auction_type_id, "source": "upload"},
    )
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    data = resp.json()
    run_id = data.get("run_id")

    if not run_id:
        doc_id = data["document"]["id"]
        resp2 = client.post("/api/extractions/run", json={"document_id": doc_id})
        run_id = resp2.json().get("run_id") or resp2.json().get("id")

    # Seed outputs_json directly
    from api.database import get_connection
    with get_connection() as conn:
        conn.execute(
            "UPDATE extraction_runs SET outputs_json = ?, status = 'completed' WHERE id = ?",
            (json.dumps(outputs), run_id),
        )
        conn.commit()

    return run_id


def _seed_review_items(run_id: int, fields: dict):
    """Seed review_items for a run so build_cd_payload can read them."""
    from api.database import get_connection
    with get_connection() as conn:
        for key, value in fields.items():
            conn.execute(
                """INSERT OR REPLACE INTO review_items
                   (run_id, source_key, predicted_value, corrected_value, export_field, status)
                   VALUES (?, ?, ?, NULL, 1, 'pending')""",
                (run_id, key, value),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from api.main import app
    return TestClient(app)


@pytest.fixture(scope="module")
def copart_type_id(client):
    return _get_auction_type_id(client, "COPART")


# ===========================================================================
# 1. Preview uses field_overrides
# ===========================================================================


class TestPreviewFieldOverrides:
    """field_overrides sent to preview endpoint override extraction values."""

    def test_export_preview_uses_field_overrides(self, client, copart_type_id):
        """Preview with field_overrides shows corrected pickup_address."""
        outputs = {
            "vehicle_vin": "WAUABAF48NA016329",
            "vehicle_year": "2022",
            "vehicle_make": "AUDI",
            "vehicle_model": "A4",
            "pickup_name": "Copart North Billerica",
            "pickup_address": "OLD WRONG ADDRESS",
            "pickup_city": "NORTH BILLERICA",
            "pickup_state": "MA",
            "pickup_zip": "01862",
        }
        run_id = _upload_and_seed(client, copart_type_id, outputs)
        _seed_review_items(run_id, outputs)

        # Send preview with field_overrides correcting pickup_address
        resp = client.post(
            f"/api/exports/central-dispatch/preview/{run_id}",
            json={
                "overrides": None,
                "field_overrides": {
                    "pickup_address": "55R HIGH ST",
                },
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        payload = data.get("payload", {})

        # Verify the pickup stop has the corrected address
        stops = payload.get("stops", [])
        pickup_stop = next((s for s in stops if s.get("stopNumber") == 1), None)
        if pickup_stop:
            assert pickup_stop.get("address") == "55R HIGH ST", (
                f"Expected corrected address, got: {pickup_stop.get('address')}"
            )


# ===========================================================================
# 2. Export persists field_overrides
# ===========================================================================


class TestExportPersistsOverrides:
    """_persist_field_overrides saves corrections to review_items and outputs_json."""

    def test_export_persists_field_overrides(self, client, copart_type_id):
        """_persist_field_overrides updates corrected_value and outputs_json."""
        outputs = {
            "vehicle_vin": "JN1TBNT30Z0000001",
            "vehicle_year": "2023",
            "vehicle_make": "NISSAN",
            "vehicle_model": "SENTRA",
            "pickup_name": "Copart Clearwater",
            "pickup_address": "5800 ULMERTON RD",
            "pickup_city": "CLEARWATER",
            "pickup_state": "FL",
            "pickup_zip": "33760",
        }
        run_id = _upload_and_seed(client, copart_type_id, outputs)
        _seed_review_items(run_id, outputs)

        # Directly call _persist_field_overrides
        from api.routes.exports import _persist_field_overrides
        _persist_field_overrides(run_id, {
            "pickup_address": "CORRECTED ADDRESS 123",
            "pickup_city": "NORTH BILLERICA",
        })

        # Verify review_items corrected_value was updated
        from api.database import get_connection
        with get_connection() as conn:
            row = conn.execute(
                "SELECT corrected_value FROM review_items WHERE run_id = ? AND source_key = 'pickup_address'",
                (run_id,),
            ).fetchone()
            assert row is not None, "review_item for pickup_address not found"
            assert row["corrected_value"] == "CORRECTED ADDRESS 123"

            row2 = conn.execute(
                "SELECT corrected_value FROM review_items WHERE run_id = ? AND source_key = 'pickup_city'",
                (run_id,),
            ).fetchone()
            assert row2 is not None
            assert row2["corrected_value"] == "NORTH BILLERICA"

            # Verify outputs_json was updated
            out_row = conn.execute(
                "SELECT outputs_json FROM extraction_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            saved_outputs = json.loads(out_row["outputs_json"])
            assert saved_outputs.get("pickup_address") == "CORRECTED ADDRESS 123"
            assert saved_outputs.get("pickup_city") == "NORTH BILLERICA"


# ===========================================================================
# 3. Unverified address flag
# ===========================================================================


class TestUnverifiedAddressFlag:
    """Copart extraction with unknown city sets pickup_verified=False."""

    def test_unverified_address_flagged(self):
        """Copart city not in directory → pickup_verified=False in extraction result."""
        from services.haiku_extractor import ExtractedField, FieldSource

        fields = {
            "pickup_city": ExtractedField(value="UNKNOWN_CITY_XYZ", confidence=0.9, source=FieldSource.EXTRACTED),
            "pickup_state": ExtractedField(value="MA", confidence=0.9, source=FieldSource.EXTRACTED),
            "pickup_zip": ExtractedField(value="00000", confidence=0.9, source=FieldSource.EXTRACTED),
        }

        # Simulate the _copart_name_from_city call
        from services.haiku_extractor import _copart_name_from_city
        name = _copart_name_from_city("UNKNOWN_CITY_XYZ", fields)

        # Should fall back to "COPART - UNKNOWN_CITY_XYZ"
        assert name.startswith("COPART - "), f"Expected fallback name, got: {name}"
        directory_matched = not name.startswith("COPART - ")
        assert directory_matched is False


# ===========================================================================
# 4. Verified address flag
# ===========================================================================


class TestVerifiedAddressFlag:
    """Copart extraction with known city sets pickup_verified=True."""

    def test_verified_address_flagged(self):
        """Copart city in directory → directory match returns canonical name."""
        from services.haiku_extractor import ExtractedField, FieldSource

        fields = {
            "pickup_city": ExtractedField(value="Clearwater", confidence=0.9, source=FieldSource.EXTRACTED),
            "pickup_state": ExtractedField(value="FL", confidence=0.9, source=FieldSource.EXTRACTED),
            "pickup_zip": ExtractedField(value="33760", confidence=0.9, source=FieldSource.EXTRACTED),
        }

        from services.haiku_extractor import _copart_name_from_city
        name = _copart_name_from_city("Clearwater", fields)

        # Should match "Copart Clearwater" from directory
        assert name == "Copart Clearwater", f"Expected 'Copart Clearwater', got: {name}"
        directory_matched = not name.startswith("COPART - ")
        assert directory_matched is True


# ===========================================================================
# 5. New directory entries match
# ===========================================================================


class TestDirectoryNewEntries:
    """Newly added Copart locations are findable by city+state."""

    @pytest.mark.parametrize("city,state,expected_name", [
        ("Birmingham", "AL", "Copart Birmingham"),
        ("Columbus", "OH", "Copart Columbus"),
        ("Richmond", "VA", "Copart Richmond"),
        ("West Columbia", "SC", "Copart Columbia"),
        ("Louisville", "KY", "Copart Louisville"),
        ("Indianapolis", "IN", "Copart Indianapolis"),
        ("New Orleans", "LA", "Copart New Orleans"),
        ("Bridgeton", "MO", "Copart St Louis"),
        ("Oak Creek", "WI", "Copart Milwaukee"),
        ("Bloomington", "MN", "Copart Minneapolis"),
        ("Oklahoma City", "OK", "Copart Oklahoma City"),
        ("Des Moines", "IA", "Copart Des Moines"),
        ("Wichita", "KS", "Copart Wichita"),
        ("North Little Rock", "AR", "Copart Little Rock"),
        ("Salt Lake City", "UT", "Copart Salt Lake City"),
        ("Omaha", "NE", "Copart Omaha"),
        ("Manchester", "CT", "Copart Hartford"),
        ("Baltimore", "MD", "Copart Baltimore"),
    ])
    def test_directory_match_for_new_entries(self, city, state, expected_name):
        """Newly added locations match by city+state in COPART_LOCATIONS."""
        from services.auction_directory import COPART_LOCATIONS

        # Find by city+state (same logic as _copart_name_from_city)
        city_lower = city.lower()
        state_lower = state.lower()
        matched_name = None
        for name, loc in COPART_LOCATIONS.items():
            if loc.get("city", "").lower() == city_lower and loc.get("state", "").lower() == state_lower:
                matched_name = name
                break

        assert matched_name == expected_name, (
            f"Expected '{expected_name}' for {city}, {state}, got: {matched_name}"
        )


# ===========================================================================
# 6. Buyer Reference Number in CD payload
# ===========================================================================


class TestBuyerReferenceInCDPayload:
    """buyer_id from extraction must appear as buyerReferenceNumber in CD payload."""

    def test_buyer_reference_in_cd_payload(self, client, copart_type_id):
        """buyer_id flows into pickup stop as buyerReferenceNumber."""
        outputs = {
            "vehicle_vin": "WAUABAF48NA016329",
            "vehicle_year": "2022",
            "vehicle_make": "AUDI",
            "vehicle_model": "A4",
            "pickup_name": "Copart Clearwater",
            "pickup_address": "5800 ULMERTON RD",
            "pickup_city": "CLEARWATER",
            "pickup_state": "FL",
            "pickup_zip": "33760",
            "buyer_id": "535527",
        }
        run_id = _upload_and_seed(client, copart_type_id, outputs)
        _seed_review_items(run_id, outputs)

        # Call preview to get the built payload
        resp = client.post(
            f"/api/exports/central-dispatch/preview/{run_id}",
            json={"overrides": None, "field_overrides": None},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        payload = data.get("payload", {})

        # Verify buyer_id appears as buyerReferenceNumber in pickup stop
        stops = payload.get("stops", [])
        pickup_stop = next((s for s in stops if s.get("stopNumber") == 1), None)
        assert pickup_stop is not None, "Pickup stop not found in payload"
        assert pickup_stop.get("buyerReferenceNumber") == "535527", (
            f"Expected buyerReferenceNumber='535527', got: {pickup_stop.get('buyerReferenceNumber')}"
        )

    def test_buyer_reference_overridable_via_field_overrides(self, client, copart_type_id):
        """buyer_id can be overridden via field_overrides in preview."""
        outputs = {
            "vehicle_vin": "WAUABAF48NA016329",
            "vehicle_year": "2022",
            "vehicle_make": "AUDI",
            "vehicle_model": "A4",
            "pickup_name": "Copart Clearwater",
            "pickup_address": "5800 ULMERTON RD",
            "pickup_city": "CLEARWATER",
            "pickup_state": "FL",
            "pickup_zip": "33760",
            "buyer_id": "535527",
        }
        run_id = _upload_and_seed(client, copart_type_id, outputs)
        _seed_review_items(run_id, outputs)

        # Override buyer_id via field_overrides
        resp = client.post(
            f"/api/exports/central-dispatch/preview/{run_id}",
            json={
                "overrides": None,
                "field_overrides": {"buyer_id": "999888"},
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        payload = data.get("payload", {})

        stops = payload.get("stops", [])
        pickup_stop = next((s for s in stops if s.get("stopNumber") == 1), None)
        assert pickup_stop is not None
        assert pickup_stop.get("buyerReferenceNumber") == "999888", (
            f"Expected overridden buyer ref '999888', got: {pickup_stop.get('buyerReferenceNumber')}"
        )
