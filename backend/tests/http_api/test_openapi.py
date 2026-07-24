"""Generated OpenAPI checks for the implemented frozen-contract subset."""

from pathlib import Path
from typing import Any

import yaml

from tnpsc_book_rag.main import app

_CONTRACT_PATH = Path(__file__).parents[3] / "openapi.v1.yaml"


def test_generated_openapi_exposes_live_catalog_and_search_operations() -> None:
    """Frontend clients can distinguish implemented operations from checked-in mocks."""
    paths: dict[str, Any] = app.openapi()["paths"]

    assert paths["/v1/capabilities"]["get"]["operationId"] == "getCapabilities"
    assert paths["/v1/catalog/filters"]["get"]["operationId"] == "getCatalogFilters"
    assert paths["/v1/books"]["get"]["operationId"] == "listBooks"
    assert paths["/v1/books"]["post"]["operationId"] == "createBook"
    assert paths["/v1/books/{book_id}"]["get"]["operationId"] == "getBook"
    assert paths["/v1/books/{book_id}/documents"]["post"]["operationId"] == "uploadBookDocument"
    assert paths["/v1/documents/{document_id}"]["get"]["operationId"] == "getDocument"
    assert paths["/v1/ingestion-runs"]["get"]["operationId"] == "listIngestionRuns"
    assert (
        paths["/v1/documents/{document_id}/ingestion-runs"]["get"]["operationId"]
        == "listDocumentIngestionRuns"
    )
    assert paths["/v1/ingestion-runs/{run_id}"]["get"]["operationId"] == "getIngestionRun"
    assert paths["/v1/documents/{document_id}/pages"]["get"]["operationId"] == "listDocumentPages"
    assert paths["/v1/pages/{page_id}"]["get"]["operationId"] == "getPage"
    assert paths["/v1/pages/{page_id}"]["patch"]["operationId"] == "updatePrintedPageLabel"
    assert paths["/v1/documents/{document_id}/chunks"]["get"]["operationId"] == "listDocumentChunks"
    # Phase 2-4: search and answer endpoints are now implemented
    assert "/v1/search" in paths
    assert "/v1/answers" in paths


def test_generated_openapi_marks_protected_operations_with_bearer_auth() -> None:
    """Generated clients can distinguish public catalog reads from protected operations."""
    schema: dict[str, Any] = app.openapi()
    scheme = schema["components"]["securitySchemes"]["HTTPBearer"]

    assert scheme == {
        "type": "http",
        "description": (
            "Short-lived access token issued by the configured OpenID Connect provider."
        ),
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    assert "security" not in schema["paths"]["/v1/books"]["get"]
    assert schema["paths"]["/v1/books"]["post"]["security"] == [{"HTTPBearer": []}]
    assert schema["paths"]["/v1/search"]["post"]["security"] == [{"HTTPBearer": []}]
    assert schema["paths"]["/v1/answers"]["post"]["security"] == [{"HTTPBearer": []}]


def test_generated_catalog_success_schemas_match_frozen_component_names() -> None:
    """Generated clients receive stable resource names instead of implementation suffixes."""
    schema: dict[str, Any] = app.openapi()
    paths = schema["paths"]

    assert (
        paths["/v1/capabilities"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/Capabilities"
    )
    assert (
        paths["/v1/catalog/filters"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/CatalogFilters"
    )
    assert (
        paths["/v1/books"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/BookPage"
    )
    assert (
        paths["/v1/books/{book_id}"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/BookDetail"
    )
    assert (
        paths["/v1/books"]["post"]["responses"]["201"]["content"]["application/json"]["schema"][
            "$ref"
        ]
        == "#/components/schemas/Book"
    )
    assert (
        paths["/v1/books/{book_id}/documents"]["post"]["responses"]["202"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/DocumentUploadAccepted"
    )
    assert {
        "Book",
        "BookDetail",
        "BookPage",
        "CatalogFilters",
        "CreateBookRequest",
        "DocumentSummary",
        "DocumentUploadAccepted",
        "IngestionRun",
        "IngestionOperationPage",
        "IngestionRunDetailResponse",
        "IngestionRunPage",
        "PageDetail",
        "PageSummaryPage",
        "ChunkPage",
        "Problem",
        "TextbookStandard",
    } <= schema["components"]["schemas"].keys()


def test_generated_inspection_operations_match_frozen_success_components() -> None:
    """Every newly live operation retains its frozen ID, status, and response component."""
    contract: dict[str, Any] = yaml.safe_load(_CONTRACT_PATH.read_text(encoding="utf-8"))
    generated: dict[str, Any] = app.openapi()
    operations = (
        ("/v1/documents/{document_id}", "get", "200"),
        ("/v1/ingestion-runs", "get", "200"),
        ("/v1/documents/{document_id}/ingestion-runs", "get", "200"),
        ("/v1/ingestion-runs/{run_id}", "get", "200"),
        ("/v1/documents/{document_id}/pages", "get", "200"),
        ("/v1/pages/{page_id}", "get", "200"),
        ("/v1/pages/{page_id}", "patch", "200"),
        ("/v1/documents/{document_id}/chunks", "get", "200"),
    )
    for path, method, success_status in operations:
        frozen_operation = contract["paths"][path][method]
        generated_operation = generated["paths"][path][method]
        assert frozen_operation["x-implementation-status"] == "implemented"
        assert generated_operation["operationId"] == frozen_operation["operationId"]
        frozen_schema = frozen_operation["responses"][success_status]["content"][
            "application/json"
        ]["schema"]
        generated_schema = generated_operation["responses"][success_status]["content"][
            "application/json"
        ]["schema"]
        assert generated_schema["$ref"] == frozen_schema["$ref"]
