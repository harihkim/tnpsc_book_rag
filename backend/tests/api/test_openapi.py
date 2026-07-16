"""Generated OpenAPI checks for the implemented frozen-contract subset."""

from typing import Any

from tnpsc_book_rag.main import app


def test_generated_openapi_exposes_only_live_catalog_operations() -> None:
    """Frontend clients can distinguish implemented operations from checked-in mocks."""
    paths: dict[str, Any] = app.openapi()["paths"]

    assert paths["/v1/capabilities"]["get"]["operationId"] == "getCapabilities"
    assert paths["/v1/catalog/filters"]["get"]["operationId"] == "getCatalogFilters"
    assert paths["/v1/books"]["get"]["operationId"] == "listBooks"
    assert paths["/v1/books/{book_id}"]["get"]["operationId"] == "getBook"
    assert "post" not in paths["/v1/books"]
    assert "/v1/books/{book_id}/documents" not in paths
    assert "/v1/search" not in paths
    assert "/v1/answers" not in paths


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
    assert {
        "Book",
        "BookDetail",
        "BookPage",
        "CatalogFilters",
        "DocumentSummary",
        "Problem",
        "TextbookStandard",
    } <= schema["components"]["schemas"].keys()
