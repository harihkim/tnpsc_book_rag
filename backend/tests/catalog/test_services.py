"""Tests for opaque catalog pagination and filter derivation."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from tnpsc_book_rag.catalog.models import CatalogStatus, DocumentLanguage
from tnpsc_book_rag.catalog.ports import CatalogRepository
from tnpsc_book_rag.catalog.read_models import (
    BookListFilters,
    BookOrderKey,
    BookWindow,
    CatalogBook,
    CatalogBookOption,
)
from tnpsc_book_rag.catalog.services import CatalogService, InvalidCursorError

_NOW = datetime(2026, 7, 16, tzinfo=UTC)


def _book(number: int, title: str) -> CatalogBook:
    return CatalogBook(
        id=UUID(int=number),
        title=title,
        standard=8,
        subject="Science",
        language=DocumentLanguage.ENGLISH,
        publisher="Tamil Nadu Textbook Corporation",
        catalog_identifier=None,
        catalog_status=CatalogStatus.EMPTY,
        document_count=0,
        active_document_id=None,
        latest_document_id=None,
        latest_document_state=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


class FakeReadRepository:
    """In-memory keyset behavior for application-service tests."""

    books = (_book(1, "Alpha"), _book(2, "Beta"), _book(3, "Gamma"))

    async def list_catalog_books(
        self,
        _: BookListFilters,
        *,
        limit: int,
        after: BookOrderKey | None = None,
        before: BookOrderKey | None = None,
    ) -> BookWindow:
        if after is not None:
            assert after == self.books[1].order_key
            return BookWindow(items=(self.books[2],), has_previous=True, has_next=False)
        if before is not None:
            assert before == self.books[2].order_key
            return BookWindow(items=self.books[:limit], has_previous=False, has_next=True)
        return BookWindow(items=self.books[:limit], has_previous=False, has_next=True)

    async def count_catalog_books(self, _: BookListFilters) -> int:
        return len(self.books)

    async def list_ready_book_options(self) -> tuple[CatalogBookOption, ...]:
        return (
            CatalogBookOption(UUID(int=3), "Gamma", 8, "science"),
            CatalogBookOption(UUID(int=2), "Beta", 7, "Science"),
        )


def _service(repository: FakeReadRepository) -> CatalogService:
    @asynccontextmanager
    async def transactions() -> AsyncGenerator[CatalogRepository]:
        yield cast(CatalogRepository, repository)

    return CatalogService(transactions)


@pytest.mark.anyio
async def test_book_cursors_navigate_both_directions_and_publish_count() -> None:
    """Next and previous cursors preserve stable adjacency without exposing order keys."""
    filters = BookListFilters(standards=(8,), subjects=("Science",), query="force")
    service = _service(FakeReadRepository())

    first = await service.list_books(filters, limit=2, cursor=None, include_count=True)
    assert [book.title for book in first.items] == ["Alpha", "Beta"]
    assert first.previous_cursor is None
    assert first.next_cursor is not None
    assert first.total_items == 3

    second = await service.list_books(
        filters, limit=2, cursor=first.next_cursor, include_count=False
    )
    assert [book.title for book in second.items] == ["Gamma"]
    assert second.previous_cursor is not None
    assert second.next_cursor is None
    assert second.total_items is None

    previous = await service.list_books(
        filters, limit=2, cursor=second.previous_cursor, include_count=False
    )
    assert [book.title for book in previous.items] == ["Alpha", "Beta"]
    assert previous.previous_cursor is None
    assert previous.next_cursor is not None


@pytest.mark.anyio
async def test_book_cursor_is_bound_to_normalized_filters() -> None:
    """Opaque cursors cannot be reused after changing the active filters."""
    service = _service(FakeReadRepository())
    first = await service.list_books(
        BookListFilters(subjects=("SCIENCE",)),
        limit=2,
        cursor=None,
        include_count=False,
    )
    assert first.next_cursor is not None

    with pytest.raises(InvalidCursorError):
        await service.list_books(
            BookListFilters(subjects=("History",)),
            limit=2,
            cursor=first.next_cursor,
            include_count=False,
        )


@pytest.mark.anyio
async def test_ready_filter_subjects_are_case_insensitively_deduplicated() -> None:
    """Filter values remain canonical even if stored subject casing differs."""
    filters = await _service(FakeReadRepository()).get_filters()

    assert filters.standards == (7, 8)
    assert filters.subjects == ("science",)
    assert [book.title for book in filters.books] == ["Gamma", "Beta"]
