"""SQLAlchemy adapter for controlled ingestion and extraction inspection."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from tnpsc_book_rag.textbook_catalog.entities import BookDocument
from tnpsc_book_rag.database_persistence.database import Database
from tnpsc_book_rag.database_persistence.models import (
    AssetRecord,
    BookDocumentRecord,
    BookRecord,
    ChunkPageRecord,
    ChunkRecord,
    IngestionRunRecord,
    PageRecord,
)
from tnpsc_book_rag.ingestion_pipeline.entities import IngestionRun
from tnpsc_book_rag.ingestion_pipeline.models import IngestionStage
from tnpsc_book_rag.debug_inspection.models import (
    AssetInspection,
    BookReference,
    BoundingBox,
    ChunkOrderKey,
    ChunkSummary,
    DocumentInspection,
    DocumentReference,
    IngestionIssue,
    IngestionOperation,
    InspectionWindow,
    PageDetail,
    PageOrderKey,
    PageSummary,
    RunListFilters,
    RunOrderKey,
)
from tnpsc_book_rag.debug_inspection.ports import InspectionRepository


def _document(record: BookDocumentRecord) -> BookDocument:
    return BookDocument(
        id=record.id,
        book_id=record.book_id,
        edition=record.edition,
        source_filename=record.source_filename,
        media_type=record.media_type,
        source_artifact_key=record.source_artifact_key,
        docling_artifact_key=record.docling_artifact_key,
        source_sha256=record.source_sha256,
        file_size_bytes=record.file_size_bytes,
        page_count=record.page_count,
        state=record.state,
        activated_at=record.activated_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _issue(
    value: object,
    *,
    default_stage: IngestionStage | None,
    default_page_index: int | None,
) -> IngestionIssue:
    payload = value if isinstance(value, dict) else {}
    raw_stage = payload.get("stage")
    try:
        stage = default_stage if raw_stage is None else IngestionStage(str(raw_stage))
    except ValueError:
        stage = default_stage
    raw_page = payload.get("pdf_page_index")
    page_index = (
        raw_page
        if isinstance(raw_page, int) and not isinstance(raw_page, bool) and raw_page >= 0
        else default_page_index
    )
    code = payload.get("code")
    message = payload.get("message")
    return IngestionIssue(
        code=code if isinstance(code, str) and code else "ingestion_issue",
        message=message if isinstance(message, str) and message else "Ingestion reported an issue.",
        stage=stage,
        pdf_page_index=page_index,
    )


def _issue_payload(issue: IngestionIssue) -> dict[str, object]:
    return {
        "code": issue.code,
        "message": issue.message,
        "stage": None if issue.stage is None else issue.stage.value,
        "pdf_page_index": issue.pdf_page_index,
    }


def _run(record: IngestionRunRecord) -> IngestionRun:
    warnings = tuple(
        _issue_payload(
            _issue(
                value,
                default_stage=IngestionStage.EXTRACTION,
                default_page_index=None,
            )
        )
        for value in record.warning_details
    )
    error = (
        None
        if record.error_details is None
        else _issue_payload(
            _issue(
                record.error_details,
                default_stage=record.current_stage,
                default_page_index=None,
            )
        )
    )
    return IngestionRun(
        id=record.id,
        document_id=record.document_id,
        status=record.status,
        current_stage=record.current_stage,
        retry_count=record.retry_count,
        started_at=record.started_at,
        completed_at=record.completed_at,
        warnings=warnings,
        error=error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _page_summary(record: PageRecord) -> PageSummary:
    return PageSummary(
        id=record.id,
        document_id=record.document_id,
        pdf_page_index=record.pdf_page_index,
        printed_page_label=record.printed_page_label,
        width=record.width,
        height=record.height,
        warning_count=len(record.extraction_warnings),
        created_at=record.created_at,
    )


def _chunk(record: ChunkRecord) -> ChunkSummary:
    return ChunkSummary(
        id=record.id,
        page_id=record.page_id,
        document_id=record.document_id,
        sequence_number=record.sequence_number,
        display_text=record.display_text,
        chapter_title=record.chapter_title,
        section_path=tuple(record.section_path),
        content_type=record.content_type,
        token_count=record.token_count,
        created_at=record.created_at,
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    result = float(value)
    return result if result >= 0 else None


def _bounding_box(
    value: dict[str, object] | None,
    coordinate_origin: str | None,
) -> BoundingBox | None:
    if value is None:
        return None
    raw_values = (
        (value.get("x_min"), value.get("y_min"), value.get("x_max"), value.get("y_max"))
        if {"x_min", "y_min", "x_max", "y_max"} <= set(value)
        else (value.get("l"), value.get("b"), value.get("r"), value.get("t"))
    )
    numbers = tuple(_number(item) for item in raw_values)
    if any(item is None for item in numbers):
        return None
    x_one, y_one, x_two, y_two = cast(tuple[float, float, float, float], numbers)
    raw_origin_value: object = coordinate_origin or value.get("coord_origin")
    if not isinstance(raw_origin_value, str):
        return None
    normalized_origin = raw_origin_value.casefold().replace("_", "")
    if normalized_origin not in {"bottomleft", "topleft"}:
        return None
    origin = "bottom_left" if normalized_origin == "bottomleft" else "top_left"
    return BoundingBox(
        x_min=min(x_one, x_two),
        y_min=min(y_one, y_two),
        x_max=max(x_one, x_two),
        y_max=max(y_one, y_two),
        coordinate_origin=origin,
    )


def _asset(record: AssetRecord) -> AssetInspection:
    decorative = record.accessibility_status == "decorative"
    if decorative:
        alt_source = "not_applicable"
    elif record.alt_text_source in {"manual", "human"}:
        alt_source = "manual"
    elif record.alt_text_source in {"caption", "docling_caption"}:
        alt_source = "caption"
    else:
        alt_source = "unavailable"
    return AssetInspection(
        id=record.id,
        page_id=record.page_id,
        asset_type=record.asset_type,
        caption=record.caption,
        alt_text=None if decorative else record.alt_text,
        alt_text_source=alt_source,
        is_decorative=decorative,
        pixel_width=record.width,
        pixel_height=record.height,
        thumbnail_pixel_width=record.thumbnail_width,
        thumbnail_pixel_height=record.thumbnail_height,
        mime_type=record.mime_type,
        sha256=record.sha256,
        bounding_box=_bounding_box(record.bounding_box, record.coordinate_origin),
        created_at=record.created_at,
    )


def _window[T](
    values: list[T],
    *,
    limit: int,
    reverse: bool,
    after_supplied: bool,
    before_supplied: bool,
) -> InspectionWindow[T]:
    has_extra = len(values) > limit
    values = values[:limit]
    if reverse:
        values.reverse()
    return InspectionWindow(
        items=tuple(values),
        has_previous=has_extra if reverse else after_supplied,
        has_next=before_supplied if reverse else has_extra,
    )


class SqlAlchemyInspectionRepository:
    """Read inspection projections inside one caller-owned async session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_document(self, document_id: UUID) -> DocumentInspection | None:
        record = await self._session.get(BookDocumentRecord, document_id)
        if record is None:
            return None
        run_record = await self._session.scalar(
            select(IngestionRunRecord)
            .where(IngestionRunRecord.document_id == document_id)
            .order_by(IngestionRunRecord.created_at.desc(), IngestionRunRecord.id.desc())
            .limit(1)
        )
        return DocumentInspection(
            document=_document(record),
            latest_ingestion_run=None if run_record is None else _run(run_record),
        )

    async def get_ingestion_run(self, run_id: UUID) -> IngestionRun | None:
        record = await self._session.get(IngestionRunRecord, run_id)
        return None if record is None else _run(record)

    @staticmethod
    def _run_conditions(filters: RunListFilters) -> tuple[Any, ...]:
        conditions: list[Any] = []
        if filters.statuses:
            conditions.append(IngestionRunRecord.status.in_(filters.statuses))
        if filters.stages:
            conditions.append(IngestionRunRecord.current_stage.in_(filters.stages))
        if filters.book_id is not None:
            conditions.append(BookRecord.id == filters.book_id)
        if filters.document_id is not None:
            conditions.append(BookDocumentRecord.id == filters.document_id)
        return tuple(conditions)

    async def list_ingestion_operations(
        self,
        filters: RunListFilters,
        *,
        limit: int,
        after: RunOrderKey | None,
        before: RunOrderKey | None,
    ) -> InspectionWindow[IngestionOperation]:
        statement = (
            select(IngestionRunRecord, BookDocumentRecord, BookRecord)
            .join(BookDocumentRecord, BookDocumentRecord.id == IngestionRunRecord.document_id)
            .join(BookRecord, BookRecord.id == BookDocumentRecord.book_id)
            .where(*self._run_conditions(filters))
        )
        if after is not None:
            statement = statement.where(
                tuple_(IngestionRunRecord.created_at, IngestionRunRecord.id)
                < (after.created_at, after.id)
            )
        if before is not None:
            statement = statement.where(
                tuple_(IngestionRunRecord.created_at, IngestionRunRecord.id)
                > (before.created_at, before.id)
            )
        reverse = before is not None
        order = (
            (IngestionRunRecord.created_at.asc(), IngestionRunRecord.id.asc())
            if reverse
            else (IngestionRunRecord.created_at.desc(), IngestionRunRecord.id.desc())
        )
        rows = (await self._session.execute(statement.order_by(*order).limit(limit + 1))).all()
        values = [
            IngestionOperation(
                ingestion_run=_run(run_record),
                document=DocumentReference(
                    id=document_record.id,
                    edition=document_record.edition,
                    source_filename=document_record.source_filename,
                    state=document_record.state,
                ),
                book=BookReference(
                    id=book_record.id,
                    title=book_record.title,
                    standard=book_record.standard,
                    subject=book_record.subject,
                ),
            )
            for run_record, document_record, book_record in rows
        ]
        return _window(
            values,
            limit=limit,
            reverse=reverse,
            after_supplied=after is not None,
            before_supplied=before is not None,
        )

    async def count_ingestion_operations(self, filters: RunListFilters) -> int:
        value = await self._session.scalar(
            select(func.count(IngestionRunRecord.id))
            .join(BookDocumentRecord, BookDocumentRecord.id == IngestionRunRecord.document_id)
            .join(BookRecord, BookRecord.id == BookDocumentRecord.book_id)
            .where(*self._run_conditions(filters))
        )
        return value or 0

    async def list_document_runs(
        self,
        document_id: UUID,
        *,
        limit: int,
        after: RunOrderKey | None,
        before: RunOrderKey | None,
    ) -> InspectionWindow[IngestionRun]:
        statement = select(IngestionRunRecord).where(IngestionRunRecord.document_id == document_id)
        if after is not None:
            statement = statement.where(
                tuple_(IngestionRunRecord.created_at, IngestionRunRecord.id)
                < (after.created_at, after.id)
            )
        if before is not None:
            statement = statement.where(
                tuple_(IngestionRunRecord.created_at, IngestionRunRecord.id)
                > (before.created_at, before.id)
            )
        reverse = before is not None
        order = (
            (IngestionRunRecord.created_at.asc(), IngestionRunRecord.id.asc())
            if reverse
            else (IngestionRunRecord.created_at.desc(), IngestionRunRecord.id.desc())
        )
        records = list(
            (await self._session.scalars(statement.order_by(*order).limit(limit + 1))).all()
        )
        return _window(
            [_run(record) for record in records],
            limit=limit,
            reverse=reverse,
            after_supplied=after is not None,
            before_supplied=before is not None,
        )

    async def count_document_runs(self, document_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.count(IngestionRunRecord.id)).where(
                IngestionRunRecord.document_id == document_id
            )
        )
        return value or 0

    async def list_pages(
        self,
        document_id: UUID,
        *,
        limit: int,
        after: PageOrderKey | None,
        before: PageOrderKey | None,
    ) -> InspectionWindow[PageSummary]:
        statement = select(PageRecord).where(PageRecord.document_id == document_id)
        if after is not None:
            statement = statement.where(
                tuple_(PageRecord.pdf_page_index, PageRecord.id) > (after.pdf_page_index, after.id)
            )
        if before is not None:
            statement = statement.where(
                tuple_(PageRecord.pdf_page_index, PageRecord.id)
                < (before.pdf_page_index, before.id)
            )
        reverse = before is not None
        order = (
            (PageRecord.pdf_page_index.desc(), PageRecord.id.desc())
            if reverse
            else (PageRecord.pdf_page_index.asc(), PageRecord.id.asc())
        )
        records = list(
            (await self._session.scalars(statement.order_by(*order).limit(limit + 1))).all()
        )
        return _window(
            [_page_summary(record) for record in records],
            limit=limit,
            reverse=reverse,
            after_supplied=after is not None,
            before_supplied=before is not None,
        )

    async def count_pages(self, document_id: UUID) -> int:
        value = await self._session.scalar(
            select(func.count(PageRecord.id)).where(PageRecord.document_id == document_id)
        )
        return value or 0

    async def _page_detail(self, page_id: UUID) -> PageDetail | None:
        page = await self._session.get(PageRecord, page_id)
        if page is None:
            return None
        chunks = tuple(
            _chunk(record)
            for record in (
                await self._session.scalars(
                    select(ChunkRecord)
                    .join(ChunkPageRecord, ChunkPageRecord.chunk_id == ChunkRecord.id)
                    .where(ChunkPageRecord.page_id == page_id)
                    .order_by(ChunkRecord.sequence_number, ChunkRecord.id)
                )
            ).all()
        )
        assets = tuple(
            _asset(record)
            for record in (
                await self._session.scalars(
                    select(AssetRecord)
                    .where(AssetRecord.page_id == page_id)
                    .order_by(AssetRecord.created_at, AssetRecord.id)
                )
            ).all()
        )
        warnings = tuple(
            _issue(
                value,
                default_stage=IngestionStage.EXTRACTION,
                default_page_index=page.pdf_page_index,
            )
            for value in page.extraction_warnings
        )
        return PageDetail(
            summary=_page_summary(page),
            raw_text=page.raw_text,
            normalized_text=page.normalized_text,
            warnings=warnings,
            chunks=chunks,
            assets=assets,
        )

    async def get_page(self, page_id: UUID) -> PageDetail | None:
        return await self._page_detail(page_id)

    async def update_printed_page_label(
        self,
        page_id: UUID,
        printed_page_label: str | None,
    ) -> PageDetail | None:
        page = await self._session.get(PageRecord, page_id)
        if page is None:
            return None
        page.printed_page_label = printed_page_label
        await self._session.flush()
        await self._session.refresh(page)
        return await self._page_detail(page_id)

    async def page_belongs_to_document(self, page_id: UUID, document_id: UUID) -> bool:
        value = await self._session.scalar(
            select(func.count(PageRecord.id)).where(
                PageRecord.id == page_id,
                PageRecord.document_id == document_id,
            )
        )
        return bool(value)

    def _chunk_statement(self, document_id: UUID, page_id: UUID | None):
        statement = select(ChunkRecord).where(ChunkRecord.document_id == document_id)
        if page_id is not None:
            statement = statement.join(
                ChunkPageRecord, ChunkPageRecord.chunk_id == ChunkRecord.id
            ).where(ChunkPageRecord.page_id == page_id)
        return statement

    async def list_chunks(
        self,
        document_id: UUID,
        *,
        page_id: UUID | None,
        limit: int,
        after: ChunkOrderKey | None,
        before: ChunkOrderKey | None,
    ) -> InspectionWindow[ChunkSummary]:
        statement = self._chunk_statement(document_id, page_id)
        if after is not None:
            statement = statement.where(
                tuple_(ChunkRecord.sequence_number, ChunkRecord.id)
                > (after.sequence_number, after.id)
            )
        if before is not None:
            statement = statement.where(
                tuple_(ChunkRecord.sequence_number, ChunkRecord.id)
                < (before.sequence_number, before.id)
            )
        reverse = before is not None
        order = (
            (ChunkRecord.sequence_number.desc(), ChunkRecord.id.desc())
            if reverse
            else (ChunkRecord.sequence_number.asc(), ChunkRecord.id.asc())
        )
        records = list(
            (await self._session.scalars(statement.order_by(*order).limit(limit + 1))).all()
        )
        return _window(
            [_chunk(record) for record in records],
            limit=limit,
            reverse=reverse,
            after_supplied=after is not None,
            before_supplied=before is not None,
        )

    async def count_chunks(self, document_id: UUID, *, page_id: UUID | None) -> int:
        statement = select(func.count()).select_from(
            self._chunk_statement(document_id, page_id).subquery()
        )
        value = await self._session.scalar(statement)
        return value or 0


@asynccontextmanager
async def inspection_transaction(
    database: Database,
) -> AsyncGenerator[InspectionRepository]:
    """Adapt one caller-owned transaction to the inspection repository port."""
    async with database.transaction() as session:
        yield SqlAlchemyInspectionRepository(session)


__all__ = ["SqlAlchemyInspectionRepository", "inspection_transaction"]
