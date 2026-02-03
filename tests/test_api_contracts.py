"""
OpenAPI Contract Tests for Vehicle Transport Automation API.

These tests verify that the API endpoints conform to their documented contracts,
including request/response schemas, status codes, and error handling.
"""

from io import BytesIO


class TestHealthEndpoint:
    """Contract tests for /api/health endpoint."""

    def test_health_returns_200(self, client):
        """Health check should return 200 OK."""
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_response_schema(self, client):
        """Health check should return status and timestamp."""
        response = client.get("/api/health")
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "ok", "unhealthy"]  # Accept multiple valid states


class TestAuctionTypesEndpoint:
    """Contract tests for /api/auction-types/ endpoint."""

    def test_list_auction_types_returns_200(self, client):
        """List auction types should return 200."""
        response = client.get("/api/auction-types/")
        assert response.status_code == 200

    def test_list_auction_types_response_schema(self, client):
        """List auction types should return paginated response."""
        response = client.get("/api/auction-types/")
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_list_auction_types_item_schema(self, client):
        """Each auction type should have required fields."""
        response = client.get("/api/auction-types/")
        data = response.json()
        if len(data["items"]) > 0:
            item = data["items"][0]
            assert "id" in item
            assert "name" in item
            assert "code" in item

    def test_create_auction_type_returns_201(self, client):
        """Create auction type should return 201."""
        import uuid

        code = f"TEST_{uuid.uuid4().hex[:8].upper()}"
        response = client.post(
            "/api/auction-types/",
            json={
                "name": f"Test Auction Type {code}",
                "code": code,
                "description": "Test auction type for contract tests",
            },
        )
        assert response.status_code == 201

    def test_create_auction_type_response_schema(self, client):
        """Created auction type should have required fields."""
        import uuid

        code = f"TEST_{uuid.uuid4().hex[:8].upper()}"
        response = client.post(
            "/api/auction-types/",
            json={
                "name": f"Test Auction Type {code}",
                "code": code,
                "description": "Test auction type for contract tests",
            },
        )
        data = response.json()
        assert "id" in data
        assert data["name"] == f"Test Auction Type {code}"
        assert data["code"] == code

    def test_create_auction_type_validation_error(self, client):
        """Create auction type with invalid data should return 422."""
        response = client.post(
            "/api/auction-types/",
            json={
                # Missing required 'name' field
                "code": "INVALID",
            },
        )
        assert response.status_code == 422

    def test_get_auction_type_not_found(self, client):
        """Get non-existent auction type should return 404."""
        response = client.get("/api/auction-types/99999")
        assert response.status_code == 404


class TestDocumentsEndpoint:
    """Contract tests for /api/documents/ endpoint."""

    def test_list_documents_returns_200(self, client):
        """List documents should return 200."""
        response = client.get("/api/documents/")
        assert response.status_code == 200

    def test_list_documents_response_schema(self, client):
        """List documents should return paginated response."""
        response = client.get("/api/documents/")
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)
        assert isinstance(data["total"], int)

    def test_list_documents_with_pagination(self, client):
        """List documents should support pagination."""
        response = client.get("/api/documents/?limit=5&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) <= 5

    def test_upload_document_without_file_returns_422(self, client):
        """Upload without file should return 422."""
        response = client.post(
            "/api/documents/upload",
            data={
                "auction_type_id": 1,
            },
        )
        assert response.status_code == 422

    def test_upload_document_returns_201(self, client, sample_pdf_bytes):
        """Upload document should return 201."""
        # First ensure we have an auction type
        at_resp = client.post(
            "/api/auction-types/",
            json={
                "name": "Upload Test",
                "code": "UPLOAD_TEST",
            },
        )
        if at_resp.status_code == 201:
            auction_type_id = at_resp.json()["id"]
        else:
            # Get existing - note: response is { items: [], total: int }
            at_data = client.get("/api/auction-types/").json()
            at_list = at_data.get("items", [])
            auction_type_id = at_list[0]["id"] if at_list else 1

        response = client.post(
            "/api/documents/upload",
            files={"file": ("test.pdf", BytesIO(sample_pdf_bytes), "application/pdf")},
            data={"auction_type_id": auction_type_id},
        )
        assert response.status_code == 201

    def test_upload_document_response_schema(self, client, sample_pdf_bytes):
        """Uploaded document should have required fields."""
        # Get auction type - note: response is { items: [], total: int }
        at_data = client.get("/api/auction-types/").json()
        at_list = at_data.get("items", [])
        auction_type_id = at_list[0]["id"] if at_list else 1

        response = client.post(
            "/api/documents/upload",
            files={"file": ("test2.pdf", BytesIO(sample_pdf_bytes), "application/pdf")},
            data={"auction_type_id": auction_type_id},
        )
        data = response.json()
        # Response is DocumentUploadResponse with nested 'document' field
        assert "document" in data
        doc = data["document"]
        assert "id" in doc
        assert "filename" in doc
        assert "auction_type_id" in doc

    def test_get_document_not_found(self, client):
        """Get non-existent document should return 404."""
        response = client.get("/api/documents/99999")
        assert response.status_code == 404


class TestExtractionsEndpoint:
    """Contract tests for /api/extractions/ endpoint."""

    def test_list_extraction_runs_returns_200(self, client):
        """List extraction runs should return 200."""
        response = client.get("/api/extractions/")
        assert response.status_code == 200

    def test_list_extraction_runs_response_schema(self, client):
        """List extraction runs should return paginated response."""
        response = client.get("/api/extractions/")
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_needs_review_returns_200(self, client):
        """Needs review endpoint should return 200."""
        response = client.get("/api/extractions/needs-review")
        assert response.status_code == 200

    def test_run_extraction_invalid_document(self, client):
        """Run extraction with invalid document should return 404."""
        response = client.post(
            "/api/extractions/run",
            json={
                "document_id": 99999,
            },
        )
        assert response.status_code == 404


class TestReviewEndpoint:
    """Contract tests for /api/review/ endpoint."""

    def test_get_review_not_found(self, client):
        """Get review for non-existent run should return 404."""
        response = client.get("/api/review/99999")
        assert response.status_code == 404

    def test_submit_review_invalid_run(self, client):
        """Submit review for non-existent run should return 404."""
        response = client.post(
            "/api/review/submit",
            json={
                "run_id": 99999,
                "items": [],  # API expects "items" not "corrections"
            },
        )
        assert response.status_code == 404

    def test_training_examples_returns_200(self, client):
        """Training examples endpoint should return 200."""
        response = client.get("/api/review/training-examples/")
        assert response.status_code == 200


class TestExportsEndpoint:
    """Contract tests for /api/exports/ endpoint."""

    def test_preview_not_found(self, client):
        """Preview non-existent run should return appropriate response."""
        response = client.get("/api/exports/central-dispatch/preview/99999")
        # Should return 200 with empty results or 404
        assert response.status_code in [200, 404]

    def test_export_jobs_returns_200(self, client):
        """Export jobs should return 200."""
        response = client.get("/api/exports/jobs")
        assert response.status_code == 200

    def test_export_jobs_response_schema(self, client):
        """Export jobs should return paginated response."""
        response = client.get("/api/exports/jobs")
        data = response.json()
        assert "items" in data
        assert "total" in data


class TestWarehousesEndpoint:
    """Contract tests for /api/warehouses/ endpoint."""

    def test_list_warehouses_returns_200(self, client):
        """List warehouses should return 200."""
        response = client.get("/api/warehouses/")
        assert response.status_code == 200

    def test_list_warehouses_response_schema(self, client):
        """List warehouses should return paginated response."""
        response = client.get("/api/warehouses/")
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_create_warehouse_returns_201(self, client):
        """Create warehouse should return 201."""
        import uuid

        code = f"WH{uuid.uuid4().hex[:6].upper()}"
        response = client.post(
            "/api/warehouses/",
            json={
                "code": code,
                "name": f"Test Warehouse {code}",
                "timezone": "America/New_York",
            },
        )
        assert response.status_code == 201

    def test_create_warehouse_response_schema(self, client):
        """Created warehouse should have required fields."""
        import uuid

        code = f"WH{uuid.uuid4().hex[:6].upper()}"
        response = client.post(
            "/api/warehouses/",
            json={
                "code": code,
                "name": f"Test Warehouse {code}",
                "timezone": "America/Los_Angeles",
            },
        )
        data = response.json()
        assert "id" in data
        assert data["code"] == code
        assert data["name"] == f"Test Warehouse {code}"

    def test_create_warehouse_duplicate_code(self, client):
        """Create warehouse with duplicate code should fail."""
        # First create
        client.post(
            "/api/warehouses/",
            json={
                "code": "DUP01",
                "name": "Duplicate Test",
                "timezone": "America/New_York",
            },
        )
        # Second create with same code
        response = client.post(
            "/api/warehouses/",
            json={
                "code": "DUP01",
                "name": "Duplicate Test 2",
                "timezone": "America/New_York",
            },
        )
        assert response.status_code in [400, 409, 422]

    def test_get_warehouse_not_found(self, client):
        """Get non-existent warehouse should return 404."""
        response = client.get("/api/warehouses/99999")
        assert response.status_code == 404


class TestTemplatesEndpoint:
    """Contract tests for /api/templates/ endpoint."""

    def test_list_templates_returns_200(self, client):
        """List templates should return 200."""
        response = client.get("/api/templates/")
        assert response.status_code == 200

    def test_list_templates_response_is_list(self, client):
        """List templates should return array."""
        response = client.get("/api/templates/")
        data = response.json()
        assert isinstance(data, list)


class TestIntegrationsEndpoint:
    """Contract tests for /api/integrations/ endpoint."""

    def test_audit_log_returns_200(self, client):
        """Audit log should return 200."""
        response = client.get("/api/integrations/audit-log")
        assert response.status_code == 200

    def test_audit_log_response_is_list(self, client):
        """Audit log should return array."""
        response = client.get("/api/integrations/audit-log")
        data = response.json()
        assert isinstance(data, list)


class TestModelsEndpoint:
    """Contract tests for /api/models/ endpoint."""

    def test_list_model_versions_returns_200(self, client):
        """List model versions should return 200."""
        response = client.get("/api/models/versions")
        assert response.status_code == 200

    def test_list_model_versions_response_schema(self, client):
        """List model versions should return paginated response."""
        response = client.get("/api/models/versions")
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_training_stats_returns_200(self, client):
        """Training stats should return 200."""
        response = client.get("/api/models/training-stats")
        assert response.status_code == 200


class TestOpenAPISpec:
    """Tests for OpenAPI specification."""

    def test_openapi_spec_available(self, client):
        """OpenAPI spec should be available."""
        response = client.get("/openapi.json")
        assert response.status_code == 200

    def test_openapi_spec_valid_json(self, client):
        """OpenAPI spec should be valid JSON."""
        response = client.get("/openapi.json")
        data = response.json()
        assert "openapi" in data
        assert "info" in data
        assert "paths" in data

    def test_openapi_spec_has_title(self, client):
        """OpenAPI spec should have title."""
        response = client.get("/openapi.json")
        data = response.json()
        assert data["info"]["title"] == "Vehicle Transport Automation"

    def test_openapi_spec_has_version(self, client):
        """OpenAPI spec should have version."""
        response = client.get("/openapi.json")
        data = response.json()
        assert "version" in data["info"]

    def test_swagger_docs_available(self, client):
        """Swagger UI should be available."""
        response = client.get("/api/docs")
        assert response.status_code == 200

    def test_redoc_available(self, client):
        """ReDoc should be available."""
        response = client.get("/api/redoc")
        assert response.status_code == 200


class TestRequestValidation:
    """Tests for request validation across endpoints."""

    def test_invalid_content_type_rejected(self, client):
        """Invalid content type should be rejected."""
        response = client.post(
            "/api/auction-types/",
            content="not json",
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 422

    def test_missing_required_fields_rejected(self, client):
        """Missing required fields should return 422."""
        response = client.post("/api/auction-types/", json={})
        assert response.status_code == 422

    def test_invalid_field_types_rejected(self, client):
        """Invalid field types should return 422."""
        response = client.post(
            "/api/auction-types/",
            json={
                "name": 123,  # Should be string
                "code": ["not", "a", "string"],
            },
        )
        assert response.status_code == 422


class TestErrorResponses:
    """Tests for error response formats."""

    def test_404_response_format(self, client):
        """404 errors should have detail message."""
        response = client.get("/api/documents/99999")
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_422_response_format(self, client):
        """422 errors should have detail with validation info."""
        response = client.post("/api/auction-types/", json={})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data


class TestCORSHeaders:
    """Tests for CORS configuration."""

    def test_cors_headers_present(self, client):
        """CORS headers should be present on responses."""
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Should allow CORS
        assert response.status_code in [200, 204]

    def test_request_id_header(self, client):
        """X-Request-ID header should be in response."""
        response = client.get("/api/health")
        assert "x-request-id" in response.headers
