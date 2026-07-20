"""Opaque pagination and scope tests for the inspection application service."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from tnpsc_book_rag.catalog.entities import BookDocument
from tnpsc_book_rag.catalog.models import ChunkContentType, DocumentState
from tnpsc_book_rag.inspection.models import (
    ChunkOrderKey,
    ChunkSummary,
    DocumentInspection,
    InspectionWindow,
    PageOrderKey,
    PageSummary,
)
from tnpsc_book_rag.inspection.ports import InspectionRepository
from tnpsc_book_rag.inspection.services import (
    InspectionResourceNotFoundError,
    InspectionService,
    InvalidInspectionCursorError,
)

_NOW = datetime(2026, 7, 20, tzinfo=UTC)
_DOCUMENT_ID = UUID("2e55606d-d0e1-4bbd-9052-1a39dd71a56a")
_PAGE_IDS = (
    UUID("0db0bb09-9301-483d-9091-f5b5776fa304"),
    UUID("65c745a1-6f55-48c8-b06b-70eb3c3c2b35"),
    UUID("92daf61c-f6d9-4586-bfb9-d15f853db369"),
)


def _document() -> DocumentInspection:
    return DocumentInspection(
        document=BookDocument(
            id=_DOCUMENT_ID,
            book_id=uuid4(),
            edition="Term I",
            source_filename="science.pdf",
            media_type="application/pdf",
            source_artifact_key="private/source.pdf",
            docling_artifact_key=None,
            source_sha256="a" * 64,
            file_size_bytes=100,
            page_count=3,
            state=DocumentState.CHUNKING,
            activated_at=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
        latest_ingestion_run=None,
    )


def _pages() -> tuple[PageSummary, ...]:
    return tuple(
        PageSummary(
            id=page_id,
            document_id=_DOCUMENT_ID,
            pdf_page_index=index,
            printed_page_label=None,
            width=100,
            height=200,
            warning_count=0,
            created_at=_NOW,
        )
        for index, page_id in enumerate(_PAGE_IDS)
    )


def _chunks() -> tuple[ChunkSummary, ...]:
    return tuple(
        ChunkSummary(
            id=uuid4(),
            page_id=_PAGE_IDS[index],
            document_id=_DOCUMENT_ID,
            sequence_number=index,
            display_text=f"Chunk {index}",
            chapter_title=None,
            section_path=(),
            content_type=ChunkContentType.PROSE,
            token_count=2,
            created_at=_NOW,
        )
        for index in range(3)
    )


class _Repository:
    def __init__(self) -> None:
        self.pages = _pages()
        self.chunks = _chunks()

    async def get_document(self, document_id: UUID) -> DocumentInspection | None:
        return _document() if document_id == _DOCUMENT_ID else None

    async def list_pages(
        self,
        document_id: UUID,
        *,
        limit: int,
        after: PageOrderKey | None,
        before: PageOrderKey | None,
    ) -> InspectionWindow[PageSummary]:
        if after is not None:
            after_key = (after.pdf_page_index, after.id)
            values = tuple(
                page for page in self.pages if (page.pdf_page_index, page.id) > after_key
            )
            return InspectionWindow(values[:limit], True, len(values) > limit)
        if before is not None:
            before_key = (before.pdf_page_index, before.id)
            values = tuple(
                page for page in self.pages if (page.pdf_page_index, page.id) < before_key
            )
            selected = values[-limit:]
            return InspectionWindow(selected, len(values) > limit, True)
        return InspectionWindow(self.pages[:limit], False, len(self.pages) > limit)

    async def count_pages(self, document_id: UUID) -> int:
        return len(self.pages)

    async def page_belongs_to_document(self, page_id: UUID, document_id: UUID) -> bool:
        return document_id == _DOCUMENT_ID and page_id in _PAGE_IDS

    async def list_chunks(
        self,
        document_id: UUID,
        *,
        page_id: UUID | None,
        limit: int,
        after: ChunkOrderKey | None,
        before: ChunkOrderKey | None,
    ) -> InspectionWindow[ChunkSummary]:
        values = (
            self.chunks
            if page_id is None
            else tuple(chunk for chunk in self.chunks if chunk.page_id == page_id)
        )
        return InspectionWindow(values[:limit], False, len(values) > limit)

    async def count_chunks(self, document_id: UUID, *, page_id: UUID | None) -> int:
        return (
            len(self.chunks)
            if page_id is None
            else sum(chunk.page_id == page_id for chunk in self.chunks)
        )


def _service(repository: _Repository) -> InspectionService:
    @asynccontextmanager
    async def transaction() -> AsyncGenerator[InspectionRepository]:
        yield cast(InspectionRepository, repository)

    return InspectionService(transaction)


@pytest.mark.anyio
async def test_page_cursors_support_adjacent_navigation_and_bind_to_document() -> None:
    service = _service(_Repository())
    first = await service.list_pages(
        _DOCUMENT_ID,
        limit=2,
        cursor=None,
        include_count=True,
    )
    assert [page.pdf_page_index for page in first.items] == [0, 1]
    assert first.total_items == 3
    assert first.previous_cursor is None
    assert first.next_cursor is not None

    second = await service.list_pages(
        _DOCUMENT_ID,
        limit=2,
        cursor=first.next_cursor,
        include_count=False,
    )
    assert [page.pdf_page_index for page in second.items] == [2]
    assert second.previous_cursor is not None
    assert second.next_cursor is None

    previous = await service.list_pages(
        _DOCUMENT_ID,
        limit=2,
        cursor=second.previous_cursor,
        include_count=False,
    )
    assert [page.pdf_page_index for page in previous.items] == [0, 1]

    with pytest.raises(InvalidInspectionCursorError):
        await service.list_pages(
            uuid4(),
            limit=2,
            cursor=first.next_cursor,
            include_count=False,
        )


@pytest.mark.anyio
async def test_chunk_page_filter_requires_page_membership_and_binds_counts() -> None:
    service = _service(_Repository())
    page = await service.list_chunks(
        _DOCUMENT_ID,
        page_id=_PAGE_IDS[1],
        limit=20,
        cursor=None,
        include_count=True,
    )
    assert len(page.items) == 1
    assert page.items[0].page_id == _PAGE_IDS[1]
    assert page.total_items == 1

    with pytest.raises(InspectionResourceNotFoundError):
        await service.list_chunks(
            _DOCUMENT_ID,
            page_id=uuid4(),
            limit=20,
            cursor=None,
            include_count=False,
        )
