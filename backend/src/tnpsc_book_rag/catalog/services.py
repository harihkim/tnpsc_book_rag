"""Application services for read-only textbook catalog operations."""

import base64
import binascii
import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from tnpsc_book_rag.catalog.ports import CatalogRepository
from tnpsc_book_rag.catalog.read_models import (
    BookListFilters,
    BookOrderKey,
    CatalogBook,
    CatalogBookDetail,
    CatalogFilterOptions,
)

_CURSOR_VERSION = 1
_MAX_CURSOR_LENGTH = 2_048
type CursorDirection = Literal["next", "previous"]
type CatalogTransactionFactory = Callable[[], AbstractAsyncContextManager[CatalogRepository]]


class InvalidCursorError(ValueError):
    """Raised when an opaque cursor is malformed or belongs to other filters."""


@dataclass(frozen=True, slots=True)
class CatalogBookPage:
    """One public page with opaque adjacent-navigation cursors."""

    items: tuple[CatalogBook, ...]
    previous_cursor: str | None
    next_cursor: str | None
    total_items: int | None


def _filter_fingerprint(filters: BookListFilters) -> str:
    payload = {
        "endpoint": "books",
        "q": None if filters.query is None else filters.query.casefold(),
        "standards": sorted(filters.standards),
        "subjects": sorted(subject.casefold() for subject in filters.subjects),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _encode_cursor(
    direction: CursorDirection,
    key: BookOrderKey,
    fingerprint: str,
) -> str:
    payload = {
        "d": direction,
        "f": fingerprint,
        "k": [key.standard, key.subject, key.title, str(key.id)],
        "v": _CURSOR_VERSION,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_cursor(cursor: str, fingerprint: str) -> tuple[CursorDirection, BookOrderKey]:
    if not cursor or len(cursor) > _MAX_CURSOR_LENGTH:
        raise InvalidCursorError("cursor is invalid")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"d", "f", "k", "v"}:
            raise InvalidCursorError("cursor is invalid")
        direction = payload["d"]
        key = payload["k"]
        if (
            payload["v"] != _CURSOR_VERSION
            or payload["f"] != fingerprint
            or direction not in ("next", "previous")
            or not isinstance(key, list)
            or len(key) != 4
            or not isinstance(key[0], int)
            or not isinstance(key[1], str)
            or not isinstance(key[2], str)
            or not isinstance(key[3], str)
        ):
            raise InvalidCursorError("cursor is invalid")
        order_key = BookOrderKey(
            standard=key[0],
            subject=key[1],
            title=key[2],
            id=UUID(key[3]),
        )
    except (
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ) as error:
        raise InvalidCursorError("cursor is invalid") from error
    return direction, order_key


class CatalogService:
    """Coordinate repository reads and keep transport concerns out of persistence."""

    def __init__(self, transactions: CatalogTransactionFactory) -> None:
        self._transactions = transactions

    async def get_book(self, book_id: UUID) -> CatalogBookDetail | None:
        """Return one public catalog detail projection."""
        async with self._transactions() as repository:
            return await repository.get_catalog_book(book_id)

    async def get_filters(self) -> CatalogFilterOptions:
        """Derive retrieval filters from active ready English editions."""
        async with self._transactions() as repository:
            books = await repository.list_ready_book_options()
        standards = tuple(sorted({book.standard for book in books}))
        subjects_by_key: dict[str, str] = {}
        for book in books:
            subjects_by_key.setdefault(book.subject.casefold(), book.subject)
        subjects = tuple(subjects_by_key[key] for key in sorted(subjects_by_key))
        return CatalogFilterOptions(standards=standards, subjects=subjects, books=books)

    async def list_books(
        self,
        filters: BookListFilters,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> CatalogBookPage:
        """Return one filter-bound keyset page and optional exact total."""
        fingerprint = _filter_fingerprint(filters)
        after: BookOrderKey | None = None
        before: BookOrderKey | None = None
        if cursor is not None:
            direction, key = _decode_cursor(cursor, fingerprint)
            if direction == "next":
                after = key
            else:
                before = key
        async with self._transactions() as repository:
            window = await repository.list_catalog_books(
                filters,
                limit=limit,
                after=after,
                before=before,
            )
            total_items = await repository.count_catalog_books(filters) if include_count else None
        if cursor is not None and not window.items:
            raise InvalidCursorError("cursor no longer identifies a catalog page")
        previous_cursor = (
            _encode_cursor("previous", window.items[0].order_key, fingerprint)
            if window.has_previous and window.items
            else None
        )
        next_cursor = (
            _encode_cursor("next", window.items[-1].order_key, fingerprint)
            if window.has_next and window.items
            else None
        )
        return CatalogBookPage(
            items=window.items,
            previous_cursor=previous_cursor,
            next_cursor=next_cursor,
            total_items=total_items,
        )
