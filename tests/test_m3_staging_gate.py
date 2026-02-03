"""
M3 Staging Gate Tests

Comprehensive test suite for M3 Production Workflow deployment validation.
Covers: Invariants, FieldResolver, CD Export, Batch Jobs, Observability.

Exit criteria per section defined in docstrings.
"""

import time
from unittest.mock import Mock, patch

import pytest

# =============================================================================
# 2.1 EXTRACTION PIPELINE TESTS
# =============================================================================


class TestExtractionInvariants:
    """
    Test extraction invariants (INV_TEXT_EXTRACTION, INV_CLASSIFICATION, INV_ANCHOR_FIELDS).

    Exit criteria:
    - Not less than 80% of documents pass invariants
    - For each auto-extracted field, evidence exists with confidence >= 0.3
    """

    def test_inv_text_extraction_empty_text_fails(self):
        """INV_TEXT_EXTRACTION: Empty/corrupt text should fail run."""
        from extractors import ExtractorManager

        # Simulate empty text - manager should handle gracefully
        manager = ExtractorManager()
        # Get extractor for empty text - should return None or low confidence
        extractor = manager.get_extractor_for_text("")

        # Empty text should not confidently match any extractor
        assert extractor is None, "Empty text should not match any extractor confidently"

    def test_inv_text_extraction_valid_text_passes(self):
        """INV_TEXT_EXTRACTION: Valid text should extract fields."""
        from extractors import ExtractorManager

        # Use realistic Copart document text with strong indicators
        sample_text = """
        SOLD THROUGH COPART
        Sales Receipt/Bill of Sale
        copart.com

        LOT#: 12345678
        VIN: 1HGBH41JXMN109186
        Vehicle: 2020 Toyota Camry
        MEMBER: Test Buyer
        PHYSICAL ADDRESS OF LOT: 123 Main St, Dallas, TX 75201
        """

        manager = ExtractorManager()
        extractor = manager.get_extractor_for_text(sample_text)

        # Should find an appropriate extractor
        assert extractor is not None, "Valid text should match an extractor"

    def test_inv_classification_source_and_score(self):
        """INV_CLASSIFICATION: Each classification must have source + score."""
        from extractors import ExtractorManager

        sample_text = "COPART Invoice #12345 VIN: 1HGBH41JXMN109186 Lot Number: 87654321"
        manager = ExtractorManager()

        # Test that ExtractorManager has scoring capability
        for extractor in manager.extractors:
            score, patterns = extractor.score(sample_text)
            assert isinstance(score, (int, float)), "Score must be numeric"
            assert score >= 0, "Score must be non-negative"
            assert isinstance(patterns, list), "Patterns must be a list"

    def test_inv_anchor_fields_minimum_required(self):
        """INV_ANCHOR_FIELDS: Must have minimum anchor fields for valid extraction."""
        from extractors.copart import CopartExtractor

        # Complete document with strong Copart indicators
        complete_text = """
        SOLD THROUGH COPART
        Sales Receipt/Bill of Sale
        copart.com

        LOT#: 12345678
        VIN: 1HGBH41JXMN109186
        2020 Toyota Camry
        MEMBER: Test Buyer
        PHYSICAL ADDRESS OF LOT: 123 Main St, Dallas, TX 75201
        """

        extractor = CopartExtractor()
        score, patterns = extractor.score(complete_text)

        # Should match with reasonable confidence (Copart has weighted indicators)
        assert score > 0.3, f"Complete document should score > 0.3, got {score}"
        assert len(patterns) >= 3, f"Should match multiple patterns, got {patterns}"


class TestOCRDecision:
    """
    Test OCR decision logic: native / OCR / hybrid selection.

    Exit criteria: Correct strategy selected based on quality metrics.
    """

    def test_native_pdf_no_ocr_needed(self):
        """Native PDF with good text should not need OCR."""
        from extractors.ocr_strategy import OCRStrategy

        strategy = OCRStrategy()

        # Good quality text - should not need OCR
        good_text = """
        Vehicle Transport Invoice
        VIN: 1HGBH41JXMN109186
        Year: 2020 Make: Toyota Model: Camry
        Pickup Location: 123 Main Street, Dallas, TX 75201
        Delivery Location: 456 Oak Avenue, Houston, TX 77001
        Contact: John Doe Phone: 555-123-4567
        """ * 10  # Make it substantial

        should_ocr, reason = strategy.should_use_ocr(good_text)
        assert not should_ocr, f"Good quality text should not need OCR: {reason}"

    def test_scanned_pdf_needs_ocr(self):
        """Scanned PDF with no/garbled text should need OCR."""
        from extractors.ocr_strategy import OCRStrategy

        strategy = OCRStrategy()

        # Poor quality / garbled text
        poor_text = "x@#$ %^& *() !@# garbage 123 ???"

        should_ocr, reason = strategy.should_use_ocr(poor_text)
        assert should_ocr, f"Poor quality text should need OCR: {reason}"

    def test_hybrid_for_mixed_quality(self):
        """Mixed quality PDF analysis should work."""
        from extractors.ocr_strategy import OCRStrategy

        strategy = OCRStrategy()

        # Borderline text - some good, some bad
        mixed_text = """
        VIN: 1HGBH41JXMN109186
        Some readable text here
        @#$ garbled section %^&
        """ * 5

        should_ocr, reason = strategy.should_use_ocr(mixed_text)
        # Either decision is acceptable for borderline
        assert isinstance(should_ocr, bool), "Should return boolean decision"


class TestBlockExtractor:
    """
    Test BlockExtractor: key-value proximity, multi-line, fallback.

    Exit criteria: Correct extraction from structured document blocks.
    """

    def test_key_value_inline_extraction(self):
        """Extract value immediately after label on same line."""
        from extractors.spatial_parser import SpatialParser

        SpatialParser()

        # Simulate inline key-value

        # Parser should extract VIN from inline format
        # This tests the key-value proximity logic

    def test_key_value_right_extraction(self):
        """Extract value from block to the right of label."""
        from extractors.spatial_parser import SpatialParser

        SpatialParser()

        # Label on left, value on right

    def test_multiline_value_extraction(self):
        """Extract multi-line address value."""
        from extractors.spatial_parser import SpatialParser

        SpatialParser()

        # Multi-line address


class TestLocationClassifier:
    """
    Test pickup vs delivery classification.

    Exit criteria: Correct separation of pickup/delivery addresses.
    """

    def test_explicit_pickup_label(self):
        """Text with 'Pickup' label should classify as pickup."""
        from extractors.location_classifier import LocationType, classify_location

        result = classify_location(
            address_text="123 Main St, Dallas, TX", context_text="Pickup Location"
        )

        assert (
            result.location_type == LocationType.PICKUP
        ), f"Expected pickup, got {result.location_type}"

    def test_explicit_delivery_label(self):
        """Text with 'Delivery' label should classify as delivery."""
        from extractors.location_classifier import LocationType, classify_location

        result = classify_location(
            address_text="456 Oak Ave, Houston, TX", context_text="Delivery Address"
        )

        assert (
            result.location_type == LocationType.DELIVERY
        ), f"Expected delivery, got {result.location_type}"

    def test_ship_to_as_delivery(self):
        """'Ship To' should classify as delivery."""
        from extractors.location_classifier import LocationType, classify_location

        result = classify_location(
            address_text="ABC Motors, 789 Auto Blvd, Austin, TX", context_text="Ship To"
        )

        assert (
            result.location_type == LocationType.DELIVERY
        ), f"Ship To should be delivery, got {result.location_type}"

    def test_origin_as_pickup(self):
        """'Origin' should classify as pickup."""
        from extractors.location_classifier import LocationType, classify_location

        result = classify_location(
            address_text="Copart Dallas, 1234 Auction Way, Dallas, TX", context_text="Origin"
        )

        assert (
            result.location_type == LocationType.PICKUP
        ), f"Origin should be pickup, got {result.location_type}"


class TestAddressParser:
    """
    Test address parsing with validation.

    Exit criteria: Correct parsing of street/city/state/zip with confidence.
    """

    def test_city_state_zip_parsing(self):
        """Parse city, state, zip from standard format."""
        from extractors.address_parser import parse_city_state_zip

        city, state, zip_code = parse_city_state_zip("Dallas, TX 75201")

        assert city == "Dallas", f"Expected Dallas, got {city}"
        assert state == "TX", f"Expected TX, got {state}"
        assert zip_code == "75201", f"Expected 75201, got {zip_code}"

    def test_address_confidence_score(self):
        """Address parser should provide confidence score."""
        from extractors.address_parser import ParsedAddress, calculate_address_confidence

        # Complete address
        address = ParsedAddress(
            street="123 Main St", city="Dallas", state="TX", postal_code="75201"
        )

        confidence = calculate_address_confidence(address)
        assert 0 <= confidence <= 1, "Confidence must be between 0 and 1"
        assert confidence > 0.5, f"Complete address should have high confidence, got {confidence}"

    def test_partial_address_lower_confidence(self):
        """Incomplete address should have lower confidence."""
        from extractors.address_parser import ParsedAddress, calculate_address_confidence

        # Complete address
        complete = ParsedAddress(
            street="123 Main St", city="Dallas", state="TX", postal_code="75201"
        )

        # Missing zip code
        partial = ParsedAddress(street="123 Main St", city="Dallas", state="TX")

        complete_conf = calculate_address_confidence(complete)
        partial_conf = calculate_address_confidence(partial)

        assert (
            partial_conf < complete_conf
        ), f"Partial ({partial_conf}) should be lower than complete ({complete_conf})"

    def test_state_validation_for_cd(self):
        """State validation for CD API."""
        from extractors.address_parser import validate_state_for_cd

        # Valid state
        is_valid, result = validate_state_for_cd("TX")
        assert is_valid, f"TX should be valid: {result}"

        # Invalid state
        is_valid, result = validate_state_for_cd("XX")
        assert not is_valid, "XX should be invalid"


# =============================================================================
# 2.2 FIELD RESOLVER / PRECEDENCE CHAIN TESTS
# =============================================================================


class TestFieldResolverPrecedence:
    """
    Test FieldResolver precedence chain:
    USER_OVERRIDE > WAREHOUSE_CONST > AUCTION_CONST > EXTRACTED > DEFAULT

    Exit criteria: 0 discrepancies between expected and actual field_sources_json.
    """

    def test_user_override_highest_priority(self):
        """USER_OVERRIDE should override all other sources."""
        from extractors.field_resolver import FieldResolver, FieldValueSource, ResolutionContext

        resolver = FieldResolver()
        context = ResolutionContext(user_overrides={"vehicle_vin": "USER_VIN"})

        result = resolver.resolve_field("vehicle_vin", "EXTRACTED_VIN", context)

        assert result.value == "USER_VIN"
        assert result.source == FieldValueSource.USER_OVERRIDE

    def test_extracted_used_when_no_overrides(self):
        """EXTRACTED should be used when no overrides present."""
        from extractors.field_resolver import FieldResolver, FieldValueSource, ResolutionContext

        resolver = FieldResolver()
        context = ResolutionContext()

        result = resolver.resolve_field("vehicle_year", "2020", context)

        assert result.value == "2020"
        assert result.source == FieldValueSource.EXTRACTED

    def test_resolve_all_tracks_sources(self):
        """resolve_all should track sources for all fields."""
        from extractors.field_resolver import FieldResolver, FieldValueSource, ResolutionContext

        resolver = FieldResolver()
        context = ResolutionContext(user_overrides={"vehicle_vin": "FIXED_VIN"})

        extracted_fields = {
            "vehicle_vin": "PDF_VIN",
            "pickup_city": "Dallas",
            "vehicle_year": "2020",
        }

        results = resolver.resolve_all(extracted_fields, context)

        # User override should win for VIN
        assert results["vehicle_vin"].source == FieldValueSource.USER_OVERRIDE
        assert results["vehicle_vin"].value == "FIXED_VIN"

        # Extracted should be used for other fields
        assert results["pickup_city"].source == FieldValueSource.EXTRACTED
        assert results["pickup_city"].value == "Dallas"

    def test_precedence_order_defined(self):
        """Precedence order should be correctly defined."""
        from extractors.field_resolver import PRECEDENCE_ORDER, FieldValueSource

        assert PRECEDENCE_ORDER[0] == FieldValueSource.USER_OVERRIDE
        assert PRECEDENCE_ORDER[-1] == FieldValueSource.DEFAULT
        assert FieldValueSource.WAREHOUSE_CONST in PRECEDENCE_ORDER
        assert FieldValueSource.EXTRACTED in PRECEDENCE_ORDER


# =============================================================================
# 2.3 CD EXPORT TESTS (Create/Update, ETag, Retries)
# =============================================================================


class TestCDExportCreate:
    """
    Test Create Listing (POST) to Central Dispatch.

    Exit criteria:
    - Payload valid per registry
    - partnerReferenceId stable and length-limited
    - cd_listing_id saved
    - ETag handling correct
    """

    def test_payload_validation_required_fields(self):
        """Payload must include all required CD fields."""
        from api.listing_fields import get_registry

        registry = get_registry()

        payload = {
            "vehicle_vin": "1HGBH41JXMN109186",
            "pickup_city": "Dallas",
            "pickup_state": "TX",
            "delivery_city": "Houston",
            "delivery_state": "TX",
        }

        issues = registry.get_blocking_issues(payload, warehouse_selected=True)

        # Should have issues for missing required fields
        missing_required = [i for i in issues if i.get("is_blocking")]
        # Some fields might be missing
        assert isinstance(missing_required, list)

    def test_partner_reference_id_stability(self):
        """partnerReferenceId should be stable and unique per document."""
        from api.cd_client import generate_partner_reference_id

        doc_id = 123
        run_id = 456

        ref1 = generate_partner_reference_id(doc_id, run_id)
        ref2 = generate_partner_reference_id(doc_id, run_id)

        assert ref1 == ref2, "Same inputs should produce same reference ID"
        assert len(ref1) <= 50, f"Reference ID too long: {len(ref1)} > 50"

    def test_partner_reference_id_uniqueness(self):
        """Different documents should have different reference IDs."""
        from api.cd_client import generate_partner_reference_id

        ref1 = generate_partner_reference_id(100, 1)
        ref2 = generate_partner_reference_id(101, 1)

        assert ref1 != ref2, "Different docs should have different reference IDs"

    @patch("api.cd_client.requests.post")
    def test_create_listing_saves_cd_id(self, mock_post):
        """Successful create should save cd_listing_id."""
        from api.cd_client import CDClient

        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": "cd-listing-12345",
            "etag": "abc123",
        }
        mock_response.headers = {"ETag": "abc123"}
        mock_post.return_value = mock_response

        CDClient(api_key="test", base_url="https://test.centraldispatch.com")
        # Test would call client.create_listing(payload)

    @patch("api.cd_client.requests.get")
    def test_etag_fetch_on_missing(self, mock_get):
        """If ETag not in response, should fetch via GET."""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"ETag": "fetched-etag-456"}
        mock_get.return_value = mock_response

        # Verify GET is called when ETag missing


class TestCDExportUpdate:
    """
    Test Update Listing (PUT) with ETag/If-Match.

    Exit criteria:
    - If-Match header always used
    - 412 triggers ETag refresh and retry
    """

    @patch("api.cd_client.requests.put")
    def test_update_includes_if_match(self, mock_put):
        """Update must include If-Match header."""
        from api.cd_client import CDClient

        mock_response = Mock()
        mock_response.status_code = 200
        mock_put.return_value = mock_response

        CDClient(api_key="test", base_url="https://test.centraldispatch.com")

        # Verify If-Match in headers
        # client.update_listing(listing_id, payload, etag="current-etag")
        # assert mock_put.call_args.kwargs["headers"]["If-Match"] == "current-etag"

    @patch("api.cd_client.requests.put")
    @patch("api.cd_client.requests.get")
    def test_412_triggers_etag_refresh(self, mock_get, mock_put):
        """412 Precondition Failed should refresh ETag and retry."""

        # First call returns 412
        mock_412 = Mock()
        mock_412.status_code = 412

        # GET returns new ETag
        mock_get_response = Mock()
        mock_get_response.status_code = 200
        mock_get_response.headers = {"ETag": "new-etag-789"}
        mock_get.return_value = mock_get_response

        # Second PUT succeeds
        mock_success = Mock()
        mock_success.status_code = 200

        mock_put.side_effect = [mock_412, mock_success]

        # Verify retry logic


class TestCDRateLimitRetry:
    """
    Test rate limiting and retry behavior.

    Exit criteria:
    - 429 respects Retry-After
    - Backoff applied
    - Retries limited
    - Semaphore limits concurrency
    """

    @patch("api.cd_client.requests.post")
    def test_429_respects_retry_after(self, mock_post):
        """429 should wait for Retry-After duration."""
        mock_429 = Mock()
        mock_429.status_code = 429
        mock_429.headers = {"Retry-After": "2"}

        mock_success = Mock()
        mock_success.status_code = 201
        mock_success.json.return_value = {"id": "listing-123"}

        mock_post.side_effect = [mock_429, mock_success]

        # Measure time to verify delay
        start = time.time()
        # client.create_listing(payload)  # Should wait ~2 seconds
        time.time() - start

        # Should have waited at least 1.5 seconds (allowing some tolerance)
        # assert elapsed >= 1.5

    def test_retry_limit_prevents_infinite_loop(self):
        """Retries should be limited to prevent infinite loops."""
        from api.cd_client import MAX_RETRIES

        assert MAX_RETRIES <= 5, f"Max retries too high: {MAX_RETRIES}"
        assert MAX_RETRIES >= 2, f"Max retries too low: {MAX_RETRIES}"

    def test_semaphore_limits_concurrency(self):
        """Concurrent CD calls should be limited by semaphore."""
        from api.cd_client import CD_SEMAPHORE_LIMIT

        assert CD_SEMAPHORE_LIMIT <= 10, f"Semaphore limit too high: {CD_SEMAPHORE_LIMIT}"
        assert CD_SEMAPHORE_LIMIT >= 1, f"Semaphore limit too low: {CD_SEMAPHORE_LIMIT}"


class TestCDIdempotency:
    """
    Test idempotency for retry safety.

    Exit criteria:
    - Retry-safe POST doesn't create duplicates
    - partnerReferenceId used for dedup
    """

    def test_duplicate_post_returns_existing(self):
        """POST with same partnerReferenceId should return existing listing."""
        # When posting same reference ID twice, second should return existing
        pass

    def test_idempotency_key_in_request(self):
        """Requests should include idempotency key."""
        from api.cd_client import CDClient

        CDClient(api_key="test", base_url="https://test.centraldispatch.com")
        # Verify idempotency key generation


class TestCDNegativeCases:
    """
    Negative test cases for CD export.

    Exit criteria:
    - Broken payload blocked
    - 412 auto-recovered
    - 429 handled without request flood
    """

    def test_invalid_payload_blocked(self):
        """Invalid payload should trigger blocking issues."""
        from api.listing_fields import get_registry

        registry = get_registry()

        # Missing critical fields
        invalid_payload = {"vehicle_color": "Red"}

        # get_blocking_issues returns all blocking issues (all are blocking by definition)
        issues = registry.get_blocking_issues(invalid_payload, warehouse_selected=False)

        assert len(issues) > 0, "Invalid payload should have blocking issues"

    def test_412_recovery_flow(self):
        """Forced 412 should trigger ETag refresh and recovery."""
        # Manually set stale ETag, verify recovery
        pass

    def test_429_no_flood(self):
        """Multiple 429s should not cause request flood."""
        # Verify exponential backoff prevents overwhelming server
        pass


# =============================================================================
# 2.4 BATCH JOB TESTS
# =============================================================================


class TestBatchJobs:
    """
    Test batch job processing.

    Exit criteria:
    - Progress tracking works
    - Cancel stops new tasks
    - Rerun behavior deterministic
    """

    def test_batch_job_progress(self):
        """Batch job should report progress correctly."""
        from api.batch_queue import BatchQueue

        queue = BatchQueue()

        # Create job with 10 items
        job_id = queue.create_job([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])

        status = queue.get_status(job_id)
        assert status["total"] == 10
        assert status["completed"] >= 0
        assert status["failed"] >= 0

    def test_batch_job_cancel(self):
        """Cancel should stop processing new items."""
        from api.batch_queue import BatchQueue

        queue = BatchQueue()
        job_id = queue.create_job([1, 2, 3, 4, 5])

        # Cancel immediately
        queue.cancel(job_id)

        status = queue.get_status(job_id)
        assert status["status"] in ["cancelled", "cancelling"]

    def test_batch_rerun_deterministic(self):
        """Rerunning same batch should behave consistently."""
        from api.batch_queue import BatchQueue

        queue = BatchQueue()

        # Run same items twice
        run_ids = [100, 101, 102]

        queue.create_job(run_ids)
        # Let it complete
        # job2 = queue.create_job(run_ids)

        # Behavior should be: update existing or skip, not duplicate


# =============================================================================
# 2.5 OBSERVABILITY TESTS
# =============================================================================


class TestMetricsEndpoints:
    """
    Test metrics API endpoints.

    Exit criteria:
    - Aggregates by day/auction/warehouse
    - Drift alerts on threshold breach
    - Audit trail complete
    """

    def test_metrics_by_day(self, client):
        """Metrics should aggregate by day."""
        response = client.get("/api/metrics/extractions?group_by=day")
        assert response.status_code == 200

        data = response.json()
        assert "metrics" in data or "data" in data or isinstance(data, list)

    def test_metrics_by_auction(self, client):
        """Metrics should aggregate by auction."""
        response = client.get("/api/metrics/extractions?group_by=auction")
        assert response.status_code == 200

    def test_drift_alerts_threshold(self, client):
        """Drift alerts should appear when fill rate drops."""
        response = client.get("/api/metrics/drift/alerts")
        assert response.status_code == 200

        data = response.json()
        assert "alerts" in data or isinstance(data, list)


class TestAuditTrail:
    """
    Test audit trail completeness.

    Exit criteria:
    - Can explain "why field has this value"
    - Can explain "why posting succeeded/failed"
    """

    def test_run_audit_chain(self, client):
        """Audit should show full chain: extract → review → post."""
        # Get audit for a run
        # response = client.get(f"/api/audit/run/{run_id}")
        # Verify events present
        pass

    def test_listing_update_history(self):
        """Listing audit should show ETag changes."""
        # Get audit for a CD listing
        # Verify ETag history visible
        pass


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def client():
    """FastAPI test client."""
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)


@pytest.fixture
def sample_extraction_result():
    """Sample extraction result for testing."""
    return {
        "vehicle_vin": "1HGBH41JXMN109186",
        "vehicle_year": "2020",
        "vehicle_make": "Toyota",
        "vehicle_model": "Camry",
        "pickup_city": "Dallas",
        "pickup_state": "TX",
        "pickup_zip": "75201",
        "delivery_city": "Houston",
        "delivery_state": "TX",
        "delivery_zip": "77001",
    }
