"""Application orchestration and opaque pagination for inspection reads."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from tnpsc_book_rag.ingestion.entities import IngestionRun
from tnpsc_book_rag.inspection.models import (
    ChunkOrderKey,
    ChunkSummary,
    DocumentInspection,
    IngestionOperation,
    InspectionPage,
    InspectionWindow,
    PageDetail,
    PageOrderKey,
    PageSummary,
    RunListFilters,
    RunOrderKey,
)
from tnpsc_book_rag.inspection.ports import InspectionRepository

_CURSOR_VERSION = 1
_MAX_CURSOR_LENGTH = 2_048
type CursorDirection = Literal["next", "previous"]
type InspectionTransactionFactory = Callable[[], AbstractAsyncContextManager[InspectionRepository]]


class InvalidInspectionCursorError(ValueError):
    """Raised when an opaque cursor is malformed or used with different filters."""


class InspectionResourceNotFoundError(LookupError):
    """Raised when a scoped inspection parent or page does not exist."""


def _fingerprint(endpoint: str, filters: dict[str, object]) -> str:
    payload = {"endpoint": endpoint, **filters}
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _encode_cursor(
    direction: CursorDirection,
    key: Sequence[str | int],
    fingerprint: str,
) -> str:
    payload = {
        "d": direction,
        "f": fingerprint,
        "k": list(key),
        "v": _CURSOR_VERSION,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode_cursor(cursor: str, fingerprint: str) -> tuple[CursorDirection, list[object]]:
    if not cursor or len(cursor) > _MAX_CURSOR_LENGTH:
        raise InvalidInspectionCursorError("cursor is invalid")
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"d", "f", "k", "v"}:
            raise InvalidInspectionCursorError("cursor is invalid")
        direction = payload["d"]
        key = payload["k"]
        if (
            payload["v"] != _CURSOR_VERSION
            or payload["f"] != fingerprint
            or direction not in ("next", "previous")
            or not isinstance(key, list)
        ):
            raise InvalidInspectionCursorError("cursor is invalid")
    except (
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ) as error:
        if isinstance(error, InvalidInspectionCursorError):
            raise
        raise InvalidInspectionCursorError("cursor is invalid") from error
    return cast(CursorDirection, direction), cast(list[object], key)


def _run_key(values: list[object]) -> RunOrderKey:
    try:
        if len(values) != 2:
            raise ValueError
        created_at, run_id = values
        if not isinstance(created_at, str) or not isinstance(run_id, str):
            raise ValueError
        return RunOrderKey(datetime.fromisoformat(created_at), UUID(run_id))
    except (TypeError, ValueError) as error:
        raise InvalidInspectionCursorError("cursor is invalid") from error


def _page_key(values: list[object]) -> PageOrderKey:
    try:
        if (
            len(values) != 2
            or isinstance(values[0], bool)
            or not isinstance(values[0], int)
            or not isinstance(values[1], str)
        ):
            raise ValueError
        return PageOrderKey(values[0], UUID(values[1]))
    except (TypeError, ValueError) as error:
        raise InvalidInspectionCursorError("cursor is invalid") from error


def _chunk_key(values: list[object]) -> ChunkOrderKey:
    try:
        if (
            len(values) != 2
            or isinstance(values[0], bool)
            or not isinstance(values[0], int)
            or not isinstance(values[1], str)
        ):
            raise ValueError
        return ChunkOrderKey(values[0], UUID(values[1]))
    except (TypeError, ValueError) as error:
        raise InvalidInspectionCursorError("cursor is invalid") from error


def _bounds[K](
    cursor: str | None,
    fingerprint: str,
    decoder: Callable[[list[object]], K],
) -> tuple[K | None, K | None]:
    if cursor is None:
        return None, None
    direction, values = _decode_cursor(cursor, fingerprint)
    key = decoder(values)
    return (key, None) if direction == "next" else (None, key)


def _page_result[T, K](
    window: InspectionWindow[T],
    *,
    cursor: str | None,
    fingerprint: str,
    key: Callable[[T], K],
    serialize: Callable[[K], Sequence[str | int]],
    total_items: int | None,
) -> InspectionPage[T]:
    if cursor is not None and not window.items:
        raise InvalidInspectionCursorError("cursor no longer identifies an inspection page")
    previous_cursor = (
        _encode_cursor("previous", serialize(key(window.items[0])), fingerprint)
        if window.has_previous and window.items
        else None
    )
    next_cursor = (
        _encode_cursor("next", serialize(key(window.items[-1])), fingerprint)
        if window.has_next and window.items
        else None
    )
    return InspectionPage(
        items=window.items,
        previous_cursor=previous_cursor,
        next_cursor=next_cursor,
        total_items=total_items,
    )


class InspectionService:
    """Coordinate bounded inspection reads and keep cursors out of persistence."""

    def __init__(self, transactions: InspectionTransactionFactory) -> None:
        self._transactions = transactions

    async def get_document(self, document_id: UUID) -> DocumentInspection | None:
        async with self._transactions() as repository:
            return await repository.get_document(document_id)

    async def get_ingestion_run(self, run_id: UUID) -> IngestionRun | None:
        async with self._transactions() as repository:
            return await repository.get_ingestion_run(run_id)

    async def list_ingestion_operations(
        self,
        filters: RunListFilters,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[IngestionOperation]:
        fingerprint = _fingerprint(
            "ingestion-runs",
            {
                "statuses": sorted(value.value for value in filters.statuses),
                "stages": sorted(value.value for value in filters.stages),
                "book_id": None if filters.book_id is None else str(filters.book_id),
                "document_id": (None if filters.document_id is None else str(filters.document_id)),
            },
        )
        after, before = _bounds(cursor, fingerprint, _run_key)
        async with self._transactions() as repository:
            window = await repository.list_ingestion_operations(
                filters,
                limit=limit,
                after=after,
                before=before,
            )
            total = await repository.count_ingestion_operations(filters) if include_count else None
        return _page_result(
            window,
            cursor=cursor,
            fingerprint=fingerprint,
            key=lambda item: RunOrderKey(item.ingestion_run.created_at, item.ingestion_run.id),
            serialize=lambda value: (value.created_at.isoformat(), str(value.id)),
            total_items=total,
        )

    async def list_document_runs(
        self,
        document_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[IngestionRun]:
        fingerprint = _fingerprint("document-ingestion-runs", {"document_id": str(document_id)})
        after, before = _bounds(cursor, fingerprint, _run_key)
        async with self._transactions() as repository:
            if await repository.get_document(document_id) is None:
                raise InspectionResourceNotFoundError("document does not exist")
            window = await repository.list_document_runs(
                document_id,
                limit=limit,
                after=after,
                before=before,
            )
            total = await repository.count_document_runs(document_id) if include_count else None
        return _page_result(
            window,
            cursor=cursor,
            fingerprint=fingerprint,
            key=lambda run: RunOrderKey(run.created_at, run.id),
            serialize=lambda value: (value.created_at.isoformat(), str(value.id)),
            total_items=total,
        )

    async def list_pages(
        self,
        document_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[PageSummary]:
        fingerprint = _fingerprint("document-pages", {"document_id": str(document_id)})
        after, before = _bounds(cursor, fingerprint, _page_key)
        async with self._transactions() as repository:
            if await repository.get_document(document_id) is None:
                raise InspectionResourceNotFoundError("document does not exist")
            window = await repository.list_pages(
                document_id,
                limit=limit,
                after=after,
                before=before,
            )
            total = await repository.count_pages(document_id) if include_count else None
        return _page_result(
            window,
            cursor=cursor,
            fingerprint=fingerprint,
            key=lambda page: page.order_key,
            serialize=lambda value: (value.pdf_page_index, str(value.id)),
            total_items=total,
        )

    async def get_page(self, page_id: UUID) -> PageDetail | None:
        async with self._transactions() as repository:
            return await repository.get_page(page_id)

    async def update_printed_page_label(
        self,
        page_id: UUID,
        printed_page_label: str | None,
    ) -> PageDetail | None:
        async with self._transactions() as repository:
            return await repository.update_printed_page_label(page_id, printed_page_label)

    async def list_chunks(
        self,
        document_id: UUID,
        *,
        page_id: UUID | None,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[ChunkSummary]:
        fingerprint = _fingerprint(
            "document-chunks",
            {
                "document_id": str(document_id),
                "page_id": None if page_id is None else str(page_id),
            },
        )
        after, before = _bounds(cursor, fingerprint, _chunk_key)
        async with self._transactions() as repository:
            if await repository.get_document(document_id) is None:
                raise InspectionResourceNotFoundError("document does not exist")
            if page_id is not None and not await repository.page_belongs_to_document(
                page_id, document_id
            ):
                raise InspectionResourceNotFoundError("page does not belong to document")
            window = await repository.list_chunks(
                document_id,
                page_id=page_id,
                limit=limit,
                after=after,
                before=before,
            )
            total = (
                await repository.count_chunks(document_id, page_id=page_id)
                if include_count
                else None
            )
        return _page_result(
            window,
            cursor=cursor,
            fingerprint=fingerprint,
            key=lambda chunk: chunk.order_key,
            serialize=lambda value: (value.sequence_number, str(value.id)),
            total_items=total,
        )


__all__ = [
    "InspectionResourceNotFoundError",
    "InspectionService",
    "InspectionTransactionFactory",
    "InvalidInspectionCursorError",
]
