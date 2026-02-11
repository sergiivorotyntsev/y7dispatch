"""
E2E Pipeline Tests for IAA Documents

Tests full extraction pipeline: PDF file → extraction → validation
Uses real IAA PDF from golden dataset with ground truth comparison.

Test Assertions (per v3.1 spec):
1. test_extraction_creates_db_row - DB row exists with correct status/type
2. test_vin_accuracy - VIN matches ground truth exactly
3. test_address_extraction - city, state, zip match
4. test_gate_pass_from_email_body - IAA gate pass extracted
5. test_confidence_scores_present - extraction metadata present
"""

import io
import pytest
from pathlib import Path


class TestIAAExtractionPipeline:
    """
    Full extraction pipeline tests for IAA documents.

    Uses real IAA PDF from tests/sample_docs/ShowReport1.pdf
    with ground truth from tests/golden_set/expected/ShowReport1_expected.json
    """

    def test_extraction_creates_db_row(self, client, iaa_pdf):
        """
        Test: PDF upload → extraction → DB row exists with correct status.

        Verifies:
        - Document is created in database
        - Extraction run is created
        - Status indicates completion
        - Auction type is IAA
        """
        # Upload document with auto-extraction
        response = client.post(
            "/api/documents/upload",
            files={"file": ("test_iaa.pdf", io.BytesIO(iaa_pdf), "application/pdf")},
            data={
                "auto_extract": "true",
                "source": "test_lab",
                "is_test": "true",
            }
        )

        assert response.status_code in (200, 201), f"Upload failed: {response.text}"
        data = response.json()

        # Verify document was created
        assert data.get("document") is not None, "No document in response"
        doc = data["document"]

        assert doc.get("id") is not None, "Document has no ID"
        assert doc.get("uuid") is not None, "Document has no UUID"

        # Verify extraction run was created
        assert data.get("run_id") is not None, "No extraction run created"

        # Status should not be failed
        run_status = data.get("run_status", "")
        assert run_status not in ("failed",), f"Extraction failed with status: {run_status}"

        # Auction type should be detected as IAA
        detected = data.get("detected_source", "")
        auction_code = doc.get("auction_type_code", "")
        assert detected.upper() == "IAA" or auction_code.upper() == "IAA", \
            f"Expected IAA, got detected='{detected}', code='{auction_code}'"

        # Cleanup
        if doc.get("id"):
            client.delete(f"/api/documents/{doc['id']}")

    def test_vin_accuracy(self, iaa_pdf_path, iaa_ground_truth, extraction_runner):
        """
        Test: VIN extraction matches ground truth exactly.

        This is a Gate 2 test (VIN accuracy ≥ 99%).
        """
        # Run extraction
        extracted = extraction_runner(iaa_pdf_path)

        # Verify no extraction error
        assert "error" not in extracted, f"Extraction error: {extracted.get('error')}"

        # Get expected VIN from ground truth
        expected_vin = iaa_ground_truth["expected_fields"]["vehicle_vin"]
        extracted_vin = extracted.get("vehicle_vin")

        # VIN comparison (normalized uppercase, 17 chars)
        assert extracted_vin is not None, "VIN not extracted"
        assert len(extracted_vin) == 17, f"VIN length is {len(extracted_vin)}, expected 17"

        # Exact match required
        assert extracted_vin.upper() == expected_vin.upper(), \
            f"VIN mismatch: extracted='{extracted_vin}', expected='{expected_vin}'"

    def test_address_extraction(self, iaa_pdf_path, iaa_ground_truth, extraction_runner):
        """
        Test: Pickup address components match ground truth.

        This is a Gate 3 test (Address accuracy ≥ 95%).
        Verifies: pickup_city, pickup_state, pickup_zip
        """
        # Run extraction
        extracted = extraction_runner(iaa_pdf_path)
        expected = iaa_ground_truth["expected_fields"]

        # Verify no extraction error
        assert "error" not in extracted, f"Extraction error: {extracted.get('error')}"

        # Test pickup_city
        ext_city = extracted.get("pickup_city", "")
        exp_city = expected.get("pickup_city", "")
        assert ext_city.upper() == exp_city.upper(), \
            f"City mismatch: '{ext_city}' vs expected '{exp_city}'"

        # Test pickup_state (normalize to 2 letters)
        ext_state = (extracted.get("pickup_state") or "")[:2].upper()
        exp_state = (expected.get("pickup_state") or "")[:2].upper()
        assert ext_state == exp_state, \
            f"State mismatch: '{ext_state}' vs expected '{exp_state}'"

        # Test pickup_zip (normalize to 5 digits)
        ext_zip = (extracted.get("pickup_zip") or "").split("-")[0][:5]
        exp_zip = (expected.get("pickup_zip") or "").split("-")[0][:5]
        assert ext_zip == exp_zip, \
            f"ZIP mismatch: '{ext_zip}' vs expected '{exp_zip}'"

    def test_gate_pass_from_email_body(self):
        """
        Test: Gate pass extracted from IAA email body text.

        IAA uses "Gate Pass" or "IAAI Pass" terminology.
        """
        from extractors.gate_pass import GatePassExtractor

        # Sample IAA email body with gate pass
        email_body = """
        IAA Pickup Authorization

        Stock Number: 35678901
        IAA Gate Pass: IAA456789

        Present this pass at the gate for pickup.
        Branch: IAAI Tampa South
        Vehicle: 2023 TOYOTA CAMRY
        """

        # Extract gate pass
        result = GatePassExtractor.extract_primary(email_body)

        assert result is not None, "No gate pass extracted from email body"
        assert result == "IAA456789", f"Gate pass mismatch: got '{result}'"

        # Test with IAAI Pass format (alternative)
        email_body_alt = """
        Your pickup is ready!
        IAAI Pass: PICKUP123
        """
        result_alt = GatePassExtractor.extract_primary(email_body_alt)
        assert result_alt == "PICKUP123", f"IAAI Pass mismatch: got '{result_alt}'"

    def test_extraction_metadata_present(self, iaa_pdf_path, extraction_runner):
        """
        Test: Extraction returns metadata including source and confidence info.

        Verifies that extraction pipeline produces trackable results
        with classification information.
        """
        # Run extraction
        extracted = extraction_runner(iaa_pdf_path)

        # Verify no extraction error
        assert "error" not in extracted, f"Extraction error: {extracted.get('error')}"

        # Check extraction metadata is present
        meta = extracted.get("_extraction_meta", {})
        assert meta.get("extractor_used") is not None, "No extractor info"
        assert meta.get("has_invoice") is True, "Invoice not extracted"

        # Verify key fields were extracted (minimum coverage)
        required_fields = ["vehicle_vin", "vehicle_year", "vehicle_make", "pickup_city", "pickup_state"]
        missing = [f for f in required_fields if not extracted.get(f)]
        assert len(missing) == 0, f"Missing required fields: {missing}"


class TestIAAFieldValidation:
    """
    Additional validation tests for IAA extracted fields.
    """

    def test_vehicle_year_is_valid(self, iaa_pdf_path, iaa_ground_truth, extraction_runner):
        """Test vehicle year is a valid year number."""
        extracted = extraction_runner(iaa_pdf_path)
        expected = iaa_ground_truth["expected_fields"]

        ext_year = extracted.get("vehicle_year")
        exp_year = expected.get("vehicle_year")

        assert ext_year is not None, "Vehicle year not extracted"

        # Convert to int if string
        if isinstance(ext_year, str):
            ext_year = int(ext_year)
        if isinstance(exp_year, str):
            exp_year = int(exp_year)

        # Year should be reasonable (1900-2030)
        assert 1900 <= ext_year <= 2030, f"Invalid year: {ext_year}"
        assert ext_year == exp_year, f"Year mismatch: {ext_year} vs {exp_year}"

    def test_vehicle_make_model_extracted(self, iaa_pdf_path, iaa_ground_truth, extraction_runner):
        """Test vehicle make and model are extracted."""
        extracted = extraction_runner(iaa_pdf_path)
        expected = iaa_ground_truth["expected_fields"]

        # Make
        ext_make = extracted.get("vehicle_make", "")
        exp_make = expected.get("vehicle_make", "")
        assert ext_make, "Vehicle make not extracted"
        assert ext_make.upper() == exp_make.upper(), \
            f"Make mismatch: '{ext_make}' vs '{exp_make}'"

        # Model (may have variations, check contains)
        ext_model = extracted.get("vehicle_model", "")
        exp_model = expected.get("vehicle_model", "")
        assert ext_model, "Vehicle model not extracted"
        # Model comparison is more lenient (partial match OK)
        assert exp_model.upper() in ext_model.upper() or ext_model.upper() in exp_model.upper(), \
            f"Model mismatch: '{ext_model}' vs '{exp_model}'"

    def test_stock_number_extracted(self, iaa_pdf_path, iaa_ground_truth, extraction_runner):
        """Test stock/lot number is extracted for IAA documents."""
        extracted = extraction_runner(iaa_pdf_path)
        expected = iaa_ground_truth["expected_fields"]

        ext_lot = extracted.get("vehicle_lot") or extracted.get("reference_id")
        exp_lot = expected.get("vehicle_lot") or expected.get("reference_id")

        # IAA may not always have reference_id filled in ground truth
        if exp_lot:
            assert ext_lot is not None, "Stock number not extracted"
            # Lot numbers should match (may have formatting differences like 000- prefix)
            assert str(ext_lot).replace("-", "").lstrip("0") == str(exp_lot).replace("-", "").lstrip("0"), \
                f"Lot mismatch: '{ext_lot}' vs '{exp_lot}'"

    def test_buyer_info_extracted(self, iaa_pdf_path, iaa_ground_truth, extraction_runner):
        """Test buyer information is extracted."""
        extracted = extraction_runner(iaa_pdf_path)
        expected = iaa_ground_truth["expected_fields"]

        # Buyer ID
        ext_buyer_id = extracted.get("buyer_id")
        exp_buyer_id = expected.get("buyer_id")
        if exp_buyer_id:
            assert ext_buyer_id is not None, "Buyer ID not extracted"
            assert str(ext_buyer_id) == str(exp_buyer_id), \
                f"Buyer ID mismatch: '{ext_buyer_id}' vs '{exp_buyer_id}'"

        # Buyer name
        ext_buyer_name = extracted.get("buyer_name", "")
        exp_buyer_name = expected.get("buyer_name", "")
        if exp_buyer_name:
            assert ext_buyer_name, "Buyer name not extracted"
            # Case-insensitive comparison
            assert ext_buyer_name.upper() == exp_buyer_name.upper(), \
                f"Buyer name mismatch: '{ext_buyer_name}' vs '{exp_buyer_name}'"
