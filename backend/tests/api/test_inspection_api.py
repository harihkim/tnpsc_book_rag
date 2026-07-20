"""Contract tests for implemented ingestion and extraction inspection routes."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx2 import ASGITransport, AsyncClient

from tnpsc_book_rag.catalog.entities import BookDocument
from tnpsc_book_rag.catalog.models import (
    AssetType,
    ChunkContentType,
    DocumentState,
)
from tnpsc_book_rag.config import AppEnvironment, Settings
from tnpsc_book_rag.ingestion.entities import IngestionRun
from tnpsc_book_rag.ingestion.models import IngestionStage
from tnpsc_book_rag.ingestion.status import IngestionRunStatus
from tnpsc_book_rag.inspection.models import (
    AssetInspection,
    BookReference,
    BoundingBox,
    ChunkSummary,
    DocumentInspection,
    DocumentReference,
    IngestionOperation,
    InspectionPage,
    PageDetail,
    PageSummary,
    RunListFilters,
)
from tnpsc_book_rag.inspection.services import InvalidInspectionCursorError
from tnpsc_book_rag.main import create_app

_NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
_BOOK_ID = UUID("3c508224-5f38-4721-b22c-31f9a043e877")
_DOCUMENT_ID = UUID("2e55606d-d0e1-4bbd-9052-1a39dd71a56a")
_RUN_ID = UUID("cb5d573f-8331-42bf-99a6-73a43092e109")
_PAGE_ID = UUID("6b2c1c96-b196-49d0-94f4-82d0282d087d")
_CHUNK_ID = UUID("9a14726c-ef0b-4b92-a352-79f3b387585f")
_ASSET_ID = UUID("a3dd0fab-b4f8-42e8-ae1a-698ed795a6c1")


class FakeArtifactStorage:
    async def initialize(self) -> None: ...

    async def is_ready(self) -> bool:
        return True


def _run() -> IngestionRun:
    return IngestionRun(
        id=_RUN_ID,
        document_id=_DOCUMENT_ID,
        status=IngestionRunStatus.SUCCEEDED,
        current_stage=IngestionStage.CHUNKING,
        retry_count=0,
        started_at=_NOW,
        completed_at=_NOW,
        warnings=(
            {
                "code": "empty_text_layer",
                "message": "Page has no text.",
                "stage": "extraction",
                "pdf_page_index": 3,
            },
        ),
        error=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _document() -> BookDocument:
    return BookDocument(
        id=_DOCUMENT_ID,
        book_id=_BOOK_ID,
        edition="Term I",
        source_filename="science.pdf",
        media_type="application/pdf",
        source_artifact_key="private/source.pdf",
        docling_artifact_key="private/docling.json",
        source_sha256="a" * 64,
        file_size_bytes=1024,
        page_count=108,
        state=DocumentState.CHUNKING,
        activated_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _page_summary() -> PageSummary:
    return PageSummary(
        id=_PAGE_ID,
        document_id=_DOCUMENT_ID,
        pdf_page_index=3,
        printed_page_label=None,
        width=612.0,
        height=792.0,
        warning_count=1,
        created_at=_NOW,
    )


def _chunk() -> ChunkSummary:
    return ChunkSummary(
        id=_CHUNK_ID,
        page_id=_PAGE_ID,
        document_id=_DOCUMENT_ID,
        sequence_number=7,
        display_text="Matter occupies space.",
        chapter_title="Matter",
        section_path=("Matter",),
        content_type=ChunkContentType.PROSE,
        token_count=8,
        created_at=_NOW,
    )


def _asset() -> AssetInspection:
    return AssetInspection(
        id=_ASSET_ID,
        page_id=_PAGE_ID,
        asset_type=AssetType.DIAGRAM,
        caption="Matter diagram",
        alt_text="Matter diagram",
        alt_text_source="caption",
        is_decorative=False,
        pixel_width=800,
        pixel_height=600,
        thumbnail_pixel_width=320,
        thumbnail_pixel_height=240,
        mime_type="image/png",
        sha256="b" * 64,
        bounding_box=BoundingBox(10, 20, 100, 120, "bottom_left"),
        created_at=_NOW,
    )


def _page_detail() -> PageDetail:
    from tnpsc_book_rag.inspection.models import IngestionIssue

    return PageDetail(
        summary=_page_summary(),
        raw_text="Matter occupies space.",
        normalized_text="Matter occupies space.",
        warnings=(
            IngestionIssue(
                code="empty_text_layer",
                message="Page has no text.",
                stage=IngestionStage.EXTRACTION,
                pdf_page_index=3,
            ),
        ),
        chunks=(_chunk(),),
        assets=(_asset(),),
    )


class FakeInspection:
    def __init__(self) -> None:
        self.last_filters: RunListFilters | None = None
        self.last_page_id: UUID | None = None
        self.updated_label: str | None = None
        self.invalid_cursor = False

    async def get_document(self, document_id: UUID) -> DocumentInspection | None:
        if document_id != _DOCUMENT_ID:
            return None
        return DocumentInspection(_document(), _run())

    async def get_ingestion_run(self, run_id: UUID) -> IngestionRun | None:
        return _run() if run_id == _RUN_ID else None

    async def list_ingestion_operations(
        self,
        filters: RunListFilters,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[IngestionOperation]:
        self.last_filters = filters
        if self.invalid_cursor:
            raise InvalidInspectionCursorError
        assert limit == 10
        assert cursor is None
        return InspectionPage(
            items=(
                IngestionOperation(
                    ingestion_run=_run(),
                    document=DocumentReference(
                        id=_DOCUMENT_ID,
                        edition="Term I",
                        source_filename="science.pdf",
                        state=DocumentState.CHUNKING,
                    ),
                    book=BookReference(
                        id=_BOOK_ID,
                        title="Standard 6 Science",
                        standard=6,
                        subject="Science",
                    ),
                ),
            ),
            previous_cursor=None,
            next_cursor="next-run",
            total_items=1 if include_count else None,
        )

    async def list_document_runs(
        self,
        document_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[IngestionRun]:
        if document_id != _DOCUMENT_ID:
            from tnpsc_book_rag.inspection.services import InspectionResourceNotFoundError

            raise InspectionResourceNotFoundError
        return InspectionPage((_run(),), None, None, 1 if include_count else None)

    async def list_pages(
        self,
        document_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[PageSummary]:
        return InspectionPage((_page_summary(),), None, None, 1 if include_count else None)

    async def get_page(self, page_id: UUID) -> PageDetail | None:
        return _page_detail() if page_id == _PAGE_ID else None

    async def update_printed_page_label(
        self, page_id: UUID, printed_page_label: str | None
    ) -> PageDetail | None:
        if page_id != _PAGE_ID:
            return None
        self.updated_label = printed_page_label
        return replace(
            _page_detail(),
            summary=replace(_page_summary(), printed_page_label=printed_page_label),
        )

    async def list_chunks(
        self,
        document_id: UUID,
        *,
        page_id: UUID | None,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[ChunkSummary]:
        self.last_page_id = page_id
        return InspectionPage((_chunk(),), None, None, 1 if include_count else None)


def _app(inspection: FakeInspection | None):
    return create_app(
        Settings.model_validate(
            {
                "environment": AppEnvironment.TEST,
                "otel_enabled": False,
            }
        ),
        database=None,
        artifact_storage=FakeArtifactStorage(),
        inspection=inspection,
    )


@pytest.mark.anyio
async def test_ingestion_routes_map_frozen_operations_and_polling_shapes() -> None:
    inspection = FakeInspection()
    transport = ASGITransport(app=_app(inspection))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        capabilities = await client.get("/v1/capabilities")
        document = await client.get(f"/v1/documents/{_DOCUMENT_ID}")
        operations = await client.get(
            "/v1/ingestion-runs",
            params=[
                ("status", "succeeded"),
                ("stage", "chunking"),
                ("book_id", str(_BOOK_ID)),
                ("document_id", str(_DOCUMENT_ID)),
                ("limit", "10"),
                ("include_count", "true"),
            ],
        )
        history = await client.get(
            f"/v1/documents/{_DOCUMENT_ID}/ingestion-runs",
            params={"include_count": "true"},
        )
        detail = await client.get(f"/v1/ingestion-runs/{_RUN_ID}")

    assert capabilities.json()["features"]["ingestion_inspection"] is True
    assert document.status_code == 200
    assert document.json()["latest_ingestion_run"]["status"] == "succeeded"
    assert "source_artifact_key" not in document.text
    assert operations.status_code == 200
    assert operations.json()["total_items"] == 1
    assert operations.json()["items"][0]["book"]["standard"] == 6
    assert inspection.last_filters == RunListFilters(
        statuses=(IngestionRunStatus.SUCCEEDED,),
        stages=(IngestionStage.CHUNKING,),
        book_id=_BOOK_ID,
        document_id=_DOCUMENT_ID,
    )
    assert history.json()["items"][0]["warnings"][0]["pdf_page_index"] == 3
    assert detail.headers["cache-control"] == "no-store"
    assert detail.json()["poll_after_seconds"] == 2


@pytest.mark.anyio
async def test_page_and_chunk_routes_expose_display_metadata_without_embedding_fields() -> None:
    inspection = FakeInspection()
    transport = ASGITransport(app=_app(inspection))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        pages = await client.get(
            f"/v1/documents/{_DOCUMENT_ID}/pages",
            params={"include_count": "true"},
        )
        detail = await client.get(f"/v1/pages/{_PAGE_ID}")
        updated = await client.patch(
            f"/v1/pages/{_PAGE_ID}",
            json={"printed_page_label": " 12 "},
        )
        chunks = await client.get(
            f"/v1/documents/{_DOCUMENT_ID}/chunks",
            params={"page_id": str(_PAGE_ID), "include_count": "true"},
        )

    assert pages.json()["items"][0]["pdf_page_index"] == 3
    assert pages.json()["total_items"] == 1
    payload = detail.json()
    assert payload["chunks"][0]["display_text"] == "Matter occupies space."
    assert "embedding_text" not in detail.text
    assert payload["assets"][0]["content_url"] == f"/v1/assets/{_ASSET_ID}/content"
    assert payload["assets"][0]["bounding_box"]["coordinate_origin"] == "bottom_left"
    assert updated.json()["printed_page_label"] == "12"
    assert inspection.updated_label == "12"
    assert chunks.json()["total_items"] == 1
    assert inspection.last_page_id == _PAGE_ID


@pytest.mark.anyio
async def test_inspection_routes_return_safe_unavailable_not_found_and_cursor_problems() -> None:
    inspection = FakeInspection()
    inspection.invalid_cursor = True
    unavailable_transport = ASGITransport(app=_app(None))
    inspection_transport = ASGITransport(app=_app(inspection))
    async with AsyncClient(
        transport=unavailable_transport, base_url="http://testserver"
    ) as unavailable_client:
        unavailable = await unavailable_client.get("/v1/ingestion-runs")
    async with AsyncClient(transport=inspection_transport, base_url="http://testserver") as client:
        missing = await client.get(f"/v1/pages/{uuid4()}")
        invalid = await client.get("/v1/ingestion-runs")

    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "database_unavailable"
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_cursor"
    assert invalid.json()["errors"] == []
