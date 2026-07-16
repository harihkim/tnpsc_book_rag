"""Implemented v1 capabilities and read-only catalog routes."""

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Query, Response

from tnpsc_book_rag.api.errors import ApiProblem
from tnpsc_book_rag.api.schemas import (
    Book,
    BookDetail,
    BookListQuery,
    BookPage,
    Capabilities,
    CapabilityFeatures,
    CapabilityLimits,
    CatalogBookOption,
    CatalogFilters,
    Problem,
    TextbookStandard,
    UploadCapabilities,
)
from tnpsc_book_rag.catalog.read_models import (
    BookListFilters,
    CatalogBookDetail,
    CatalogFilterOptions,
)
from tnpsc_book_rag.catalog.services import CatalogBookPage, InvalidCursorError
from tnpsc_book_rag.config import Settings


def _problem_response(description: str) -> dict[str, object]:
    """Describe a Problem Details response while registering its shared schema."""
    return {
        "description": description,
        "model": Problem,
        "content": {"application/problem+json": {}},
    }


class CatalogReader(Protocol):
    """Read operations required by the HTTP catalog routes."""

    async def get_book(self, book_id: UUID) -> CatalogBookDetail | None: ...

    async def get_filters(self) -> CatalogFilterOptions: ...

    async def list_books(
        self,
        filters: BookListFilters,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> CatalogBookPage: ...


def _unavailable() -> ApiProblem:
    return ApiProblem(
        status=503,
        code="database_unavailable",
        title="Database unavailable",
        detail="The textbook catalog is temporarily unavailable.",
    )


def create_v1_router(
    settings: Settings,
    catalog: CatalogReader | None,
) -> APIRouter:
    """Create routes whose dependencies are fixed for one application instance."""
    router = APIRouter(prefix="/v1")

    @router.get(
        "/capabilities",
        response_model=Capabilities,
        tags=["capabilities"],
        operation_id="getCapabilities",
        summary="Return client-visible features and runtime limits.",
        responses={503: _problem_response("Service unavailable.")},
    )
    async def get_capabilities(response: Response) -> Capabilities:
        response.headers["Cache-Control"] = "no-store"
        return Capabilities(
            features=CapabilityFeatures(),
            limits=CapabilityLimits(
                max_upload_bytes=settings.max_upload_bytes,
                max_query_characters=settings.max_query_characters,
                max_top_k=settings.max_top_k,
                max_answer_characters_per_section=settings.max_answer_characters_per_section,
                answer_timeout_seconds=settings.answer_timeout_seconds,
                answer_retention_seconds=settings.answer_retention_seconds,
                thumbnail_max_edge_pixels=settings.thumbnail_max_edge_pixels,
            ),
            upload=UploadCapabilities(
                accepted_media_types=["application/pdf"],
                requires_text_layer=True,
            ),
        )

    @router.get(
        "/catalog/filters",
        response_model=CatalogFilters,
        tags=["catalog"],
        operation_id="getCatalogFilters",
        summary="Return search filters derived from active ready documents.",
        responses={503: _problem_response("Service unavailable.")},
    )
    async def get_catalog_filters() -> CatalogFilters:
        if catalog is None:
            raise _unavailable()
        filters = await catalog.get_filters()
        return CatalogFilters(
            standards=[TextbookStandard(standard) for standard in filters.standards],
            subjects=list(filters.subjects),
            books=[
                CatalogBookOption.model_validate(book, from_attributes=True)
                for book in filters.books
            ],
        )

    @router.get(
        "/books",
        response_model=BookPage,
        tags=["catalog"],
        operation_id="listBooks",
        summary="List conceptual textbooks.",
        responses={
            422: _problem_response("Request validation or cursor failure."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def list_books(
        query: Annotated[BookListQuery, Query()],
    ) -> BookPage:
        if catalog is None:
            raise _unavailable()
        filters = BookListFilters(
            standards=tuple(int(standard) for standard in query.standard),
            subjects=tuple(query.subject),
            query=query.q,
        )
        try:
            page = await catalog.list_books(
                filters,
                limit=query.limit,
                cursor=query.cursor,
                include_count=query.include_count,
            )
        except InvalidCursorError as error:
            raise ApiProblem(
                status=422,
                code="invalid_cursor",
                title="Invalid cursor",
                detail="The pagination cursor is invalid for these filters.",
            ) from error
        return BookPage(
            items=[Book.from_catalog(book) for book in page.items],
            previous_cursor=page.previous_cursor,
            next_cursor=page.next_cursor,
            total_items=page.total_items,
        )

    @router.get(
        "/books/{book_id}",
        response_model=BookDetail,
        tags=["catalog"],
        operation_id="getBook",
        summary="Get a book and its registered documents.",
        responses={
            404: _problem_response("Book not found."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def get_book(book_id: UUID) -> BookDetail:
        if catalog is None:
            raise _unavailable()
        detail = await catalog.get_book(book_id)
        if detail is None:
            raise ApiProblem(
                status=404,
                code="not_found",
                title="Book not found",
                detail="The requested textbook does not exist.",
            )
        return BookDetail.from_catalog_detail(detail)

    return router
