"""Contract tests for implemented capabilities and catalog read routes."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx2 import ASGITransport, AsyncClient

from tnpsc_book_rag.textbook_catalog.entities import BookDocument, NewBook
from tnpsc_book_rag.textbook_catalog.models import CatalogStatus, DocumentLanguage, DocumentState
from tnpsc_book_rag.textbook_catalog.mutations import (
    AcceptedDocumentUpload,
    BookMutationResult,
    MutationResult,
    PendingDocumentUpload,
    UploadMutationResult,
)
from tnpsc_book_rag.textbook_catalog.read_models import (
    BookListFilters,
    CatalogBook,
    CatalogBookDetail,
    CatalogBookOption,
    CatalogFilterOptions,
)
from tnpsc_book_rag.textbook_catalog.services import CatalogBookPage, InvalidCursorError
from tnpsc_book_rag.config import AppEnvironment, Settings
from tnpsc_book_rag.ingestion_pipeline.entities import IngestionRun as IngestionRunEntity
from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.ingestion_pipeline.status import IngestionRunStatus
from tnpsc_book_rag.main import create_app

_NOW = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)


class FakeArtifactStorage:
    """No-op storage lifecycle for transport tests."""

    async def initialize(self) -> None: ...

    async def is_ready(self) -> bool:
        return True


def _catalog_book() -> CatalogBook:
    return CatalogBook(
        id=UUID("3c508224-5f38-4721-b22c-31f9a043e877"),
        title="Science — Standard 8",
        standard=8,
        subject="Science",
        language=DocumentLanguage.ENGLISH,
        publisher="Tamil Nadu Textbook Corporation",
        catalog_identifier=None,
        catalog_status=CatalogStatus.READY,
        document_count=1,
        active_document_id=UUID("2e55606d-d0e1-4bbd-9052-1a39dd71a56a"),
        latest_document_id=UUID("2e55606d-d0e1-4bbd-9052-1a39dd71a56a"),
        latest_document_state=DocumentState.READY,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _document(book: CatalogBook) -> BookDocument:
    assert book.active_document_id is not None
    return BookDocument(
        id=book.active_document_id,
        book_id=book.id,
        edition="2025-2026",
        source_filename="science-standard-8.pdf",
        media_type="application/pdf",
        source_artifact_key="private/source.pdf",
        docling_artifact_key="private/docling.json",
        source_sha256="a" * 64,
        file_size_bytes=1_024,
        page_count=212,
        state=DocumentState.READY,
        activated_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )


class FakeCatalog:
    """Controllable catalog reader for HTTP mapping tests."""

    def __init__(self) -> None:
        self.book = _catalog_book()
        self.last_filters: BookListFilters | None = None
        self.raise_invalid_cursor = False

    @property
    def mutations_enabled(self) -> bool:
        return True

    async def get_book(self, book_id: UUID) -> CatalogBookDetail | None:
        if book_id != self.book.id:
            return None
        return CatalogBookDetail(book=self.book, documents=(_document(self.book),))

    async def get_filters(self) -> CatalogFilterOptions:
        return CatalogFilterOptions(
            standards=(8,),
            subjects=("Science",),
            books=(
                CatalogBookOption(
                    id=self.book.id,
                    title=self.book.title,
                    standard=self.book.standard,
                    subject=self.book.subject,
                ),
            ),
        )

    async def list_books(
        self,
        filters: BookListFilters,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> CatalogBookPage:
        self.last_filters = filters
        if self.raise_invalid_cursor:
            raise InvalidCursorError("opaque detail")
        assert limit == 10
        assert cursor is None
        return CatalogBookPage(
            items=(self.book,),
            previous_cursor=None,
            next_cursor="opaque-next",
            total_items=1 if include_count else None,
        )

    async def create_book(self, new_book: NewBook, *, idempotency_key: str) -> BookMutationResult:
        assert new_book.title
        assert idempotency_key
        return MutationResult(
            value=self.book,
            status_code=201,
            headers={"Location": f"/v1/books/{self.book.id}"},
            replayed=False,
        )

    async def upload_document(
        self,
        book_id: UUID,
        upload: PendingDocumentUpload,
        *,
        idempotency_key: str,
    ) -> UploadMutationResult:
        assert book_id == self.book.id
        assert upload.filename
        assert idempotency_key
        document = replace(
            _document(self.book),
            page_count=None,
            state=DocumentState.QUEUED,
            activated_at=None,
        )
        run = IngestionRunEntity(
            id=UUID("cb5d573f-8331-42bf-99a6-73a43092e109"),
            document_id=document.id,
            status=IngestionRunStatus.QUEUED,
            current_stage=IngestionStage.QUEUED,
            retry_count=0,
            started_at=None,
            completed_at=None,
            warnings=(),
            error=None,
            created_at=_NOW,
            updated_at=_NOW,
        )
        return MutationResult(
            value=AcceptedDocumentUpload(
                document=document,
                ingestion_run=run,
                poll_after_seconds=2,
                document_url=f"/v1/documents/{document.id}",
                ingestion_run_url=f"/v1/ingestion-runs/{run.id}",
            ),
            status_code=202,
            headers={},
            replayed=False,
        )


def _app(catalog: FakeCatalog | None = None, *, cors: bool = False):
    settings = Settings.model_validate(
        {
            "environment": AppEnvironment.TEST,
            "otel_enabled": False,
            "cors_origins": ["http://localhost:5173"] if cors else [],
        }
    )
    return create_app(
        settings,
        database=None,
        artifact_storage=FakeArtifactStorage(),
        catalog=catalog,
    )


@pytest.mark.anyio
async def test_capabilities_publish_partial_deployment_and_limits() -> None:
    """Clients can feature-detect the current read-only deployment without provider details."""
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/capabilities", headers={"X-Request-ID": "client-123"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "client-123"
    payload = response.json()
    assert payload["api_version"] == "v1"
    assert not any(payload["features"].values())
    assert payload["limits"] == {
        "max_upload_bytes": 52_428_800,
        "max_query_characters": 1_000,
        "max_top_k": 50,
        "max_answer_characters_per_section": 8_000,
        "answer_timeout_seconds": 60,
        "answer_retention_seconds": 86_400,
        "thumbnail_max_edge_pixels": 640,
    }
    assert payload["upload"] == {
        "accepted_media_types": ["application/pdf"],
        "requires_text_layer": True,
    }


@pytest.mark.anyio
async def test_capabilities_enable_catalog_mutation_when_dependencies_are_ready() -> None:
    """The frontend reveals catalog controls only when mutation dependencies are usable."""
    transport = ASGITransport(app=_app(FakeCatalog()))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/capabilities")

    assert response.status_code == 200
    assert response.json()["features"]["catalog_mutation"] is True


@pytest.mark.anyio
async def test_catalog_routes_map_filters_pages_and_detail_without_private_keys() -> None:
    """The read API returns frozen public projections and repeatable filters."""
    catalog = FakeCatalog()
    transport = ASGITransport(app=_app(catalog))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        filters_response = await client.get("/v1/catalog/filters")
        page_response = await client.get(
            "/v1/books",
            params=[
                ("standard", "8"),
                ("subject", " Science "),
                ("q", " force "),
                ("limit", "10"),
                ("include_count", "true"),
            ],
        )
        detail_response = await client.get(f"/v1/books/{catalog.book.id}")

    assert filters_response.json() == {
        "standards": [8],
        "subjects": ["Science"],
        "books": [
            {
                "id": str(catalog.book.id),
                "title": catalog.book.title,
                "standard": 8,
                "subject": "Science",
            }
        ],
    }
    assert page_response.status_code == 200
    assert page_response.json()["next_cursor"] == "opaque-next"
    assert page_response.json()["total_items"] == 1
    assert catalog.last_filters == BookListFilters(
        standards=(8,), subjects=("Science",), query="force"
    )
    detail = detail_response.json()
    assert detail["catalog_status"] == "ready"
    assert detail["documents"][0]["state"] == "ready"
    assert "source_artifact_key" not in detail["documents"][0]
    assert "docling_artifact_key" not in detail["documents"][0]


@pytest.mark.anyio
async def test_catalog_mutations_require_idempotency_and_return_frozen_shapes() -> None:
    """Book creation and PDF acceptance expose durable resource and polling contracts."""
    catalog = FakeCatalog()
    transport = ASGITransport(app=_app(catalog))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing_key = await client.post(
            "/v1/books",
            json={
                "title": "Science - Standard 8",
                "standard": 8,
                "subject": "Science",
                "publisher": "Tamil Nadu Textbook Corporation",
            },
        )
        created = await client.post(
            "/v1/books",
            headers={"Idempotency-Key": "create-book-123"},
            json={
                "title": " Science - Standard 8 ",
                "standard": 8,
                "subject": " Science ",
                "publisher": " Tamil Nadu Textbook Corporation ",
            },
        )
        uploaded = await client.post(
            f"/v1/books/{catalog.book.id}/documents",
            headers={"Idempotency-Key": "upload-book-123"},
            files={"file": ("science.pdf", b"%PDF-1.7\nfixture", "application/pdf")},
            data={"edition": "2025-2026"},
        )

    assert missing_key.status_code == 422
    assert missing_key.json()["code"] == "validation_error"
    assert created.status_code == 201
    assert created.headers["location"] == f"/v1/books/{catalog.book.id}"
    assert created.json()["id"] == str(catalog.book.id)
    assert uploaded.status_code == 202
    assert uploaded.json()["document"]["state"] == "queued"
    assert uploaded.json()["ingestion_run"]["status"] == "queued"
    assert uploaded.json()["poll_after_seconds"] == 2


@pytest.mark.anyio
async def test_catalog_errors_use_problem_details() -> None:
    """Not-found, invalid cursor, and request validation share the safe v1 error shape."""
    catalog = FakeCatalog()
    transport = ASGITransport(app=_app(catalog))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing = await client.get(f"/v1/books/{uuid4()}")
        invalid_query = await client.get("/v1/books", params={"limit": "0"})
        catalog.raise_invalid_cursor = True
        invalid_cursor = await client.get("/v1/books", params={"limit": "10", "cursor": "bad"})

    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["code"] == "not_found"
    assert invalid_query.status_code == 422
    assert invalid_query.json()["code"] == "validation_error"
    assert invalid_query.json()["errors"][0]["field"].startswith("query")
    assert invalid_cursor.status_code == 422
    assert invalid_cursor.json()["code"] == "invalid_cursor"
    assert "opaque detail" not in invalid_cursor.text


@pytest.mark.anyio
async def test_catalog_without_database_returns_safe_unavailable_problem() -> None:
    """A partial process never leaks missing dependency configuration."""
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/books")

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert response.json()["errors"] == []


@pytest.mark.anyio
async def test_cors_preflight_uses_the_frozen_browser_contract() -> None:
    """Only configured origins receive the exact methods and headers needed by the frontend."""
    transport = ASGITransport(app=_app(FakeCatalog(), cors=True))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/v1/books",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "Idempotency-Key,X-Request-ID",
            },
        )
        actual = await client.get("/v1/capabilities", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-max-age"] == "600"
    assert "PATCH" in response.headers["access-control-allow-methods"]
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()
    assert "x-request-id" in actual.headers["access-control-expose-headers"].lower()
    assert "access-control-allow-credentials" not in response.headers
