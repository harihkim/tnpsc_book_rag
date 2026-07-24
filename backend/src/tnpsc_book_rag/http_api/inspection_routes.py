"""Frozen v1 ingestion and extraction-inspection HTTP routes."""

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.debug_inspection.models import (
    ChunkSummary as ChunkSummaryModel,
)
from tnpsc_book_rag.debug_inspection.models import (
    DocumentInspection,
    IngestionOperation,
    InspectionPage,
    RunListFilters,
)
from tnpsc_book_rag.debug_inspection.models import (
    PageDetail as PageDetailModel,
)
from tnpsc_book_rag.debug_inspection.models import (
    PageSummary as PageSummaryModel,
)
from tnpsc_book_rag.debug_inspection.services import (
    InspectionResourceNotFoundError,
    InvalidInspectionCursorError,
)
from tnpsc_book_rag.http_api.auth import ApiScope, require_scopes
from tnpsc_book_rag.http_api.errors import ApiProblem
from tnpsc_book_rag.http_api.rate_limits import (
    ADMIN_WRITE,
    INSPECTION_READ,
    enforce_authenticated_rate,
)
from tnpsc_book_rag.http_api.schemas import (
    ChunkListQuery,
    ChunkPage,
    ChunkSummary,
    DocumentDetail,
    IngestionOperationItem,
    IngestionOperationPage,
    IngestionRun,
    IngestionRunDetailResponse,
    IngestionRunListQuery,
    IngestionRunPage,
    PageDetail,
    PageSummary,
    PageSummaryPage,
    PaginationQuery,
    Problem,
    UpdatePageRequest,
)
from tnpsc_book_rag.ingestion_pipeline.entities import IngestionRun as IngestionRunEntity


def _problem_response(description: str) -> dict[str, object]:
    return {
        "description": description,
        "model": Problem,
        "content": {"application/problem+json": {}},
    }


class InspectionReader(Protocol):
    """Application reads required by the frozen inspection routes."""

    async def get_document(self, document_id: UUID) -> DocumentInspection | None: ...

    async def get_ingestion_run(self, run_id: UUID) -> IngestionRunEntity | None: ...

    async def list_ingestion_operations(
        self,
        filters: RunListFilters,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[IngestionOperation]: ...

    async def list_document_runs(
        self,
        document_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[IngestionRunEntity]: ...

    async def list_pages(
        self,
        document_id: UUID,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[PageSummaryModel]: ...

    async def get_page(self, page_id: UUID) -> PageDetailModel | None: ...

    async def update_printed_page_label(
        self, page_id: UUID, printed_page_label: str | None
    ) -> PageDetailModel | None: ...

    async def list_chunks(
        self,
        document_id: UUID,
        *,
        page_id: UUID | None,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> InspectionPage[ChunkSummaryModel]: ...


def _unavailable() -> ApiProblem:
    return ApiProblem(
        status=503,
        code="database_unavailable",
        title="Database unavailable",
        detail="Ingestion inspection is temporarily unavailable.",
    )


def _not_found(resource: str) -> ApiProblem:
    return ApiProblem(
        status=404,
        code="not_found",
        title=f"{resource} not found",
        detail=f"The requested {resource.casefold()} does not exist.",
    )


def _invalid_cursor() -> ApiProblem:
    return ApiProblem(
        status=422,
        code="invalid_cursor",
        title="Invalid cursor",
        detail="The pagination cursor is invalid for these filters.",
    )


def create_inspection_router(
    settings: Settings,
    inspection: InspectionReader | None,
) -> APIRouter:
    """Create implemented administrative routes from one fixed dependency boundary."""
    router = APIRouter(prefix="/v1")

    @router.get(
        "/documents/{document_id}",
        dependencies=[
            Depends(require_scopes(ApiScope.INGESTION_READ)),
            Depends(enforce_authenticated_rate(INSPECTION_READ)),
        ],
        response_model=DocumentDetail,
        tags=["catalog"],
        operation_id="getDocument",
        summary="Get document detail and latest ingestion run.",
        responses={
            404: _problem_response("Document not found."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def get_document(document_id: UUID) -> DocumentDetail:
        if inspection is None:
            raise _unavailable()
        detail = await inspection.get_document(document_id)
        if detail is None:
            raise _not_found("Document")
        return DocumentDetail.from_inspection(detail)

    @router.get(
        "/ingestion-runs",
        dependencies=[
            Depends(require_scopes(ApiScope.INGESTION_READ)),
            Depends(enforce_authenticated_rate(INSPECTION_READ)),
        ],
        response_model=IngestionOperationPage,
        tags=["ingestion"],
        operation_id="listIngestionRuns",
        summary="List ingestion operations across the catalog.",
        responses={
            422: _problem_response("Request validation or cursor failure."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def list_ingestion_runs(
        query: Annotated[IngestionRunListQuery, Query()],
    ) -> IngestionOperationPage:
        if inspection is None:
            raise _unavailable()
        try:
            page = await inspection.list_ingestion_operations(
                RunListFilters(
                    statuses=tuple(query.status),
                    stages=tuple(query.stage),
                    book_id=query.book_id,
                    document_id=query.document_id,
                ),
                limit=query.limit,
                cursor=query.cursor,
                include_count=query.include_count,
            )
        except InvalidInspectionCursorError as error:
            raise _invalid_cursor() from error
        return IngestionOperationPage(
            items=[
                IngestionOperationItem.model_validate(item, from_attributes=True)
                for item in page.items
            ],
            previous_cursor=page.previous_cursor,
            next_cursor=page.next_cursor,
            total_items=page.total_items,
        )

    @router.get(
        "/documents/{document_id}/ingestion-runs",
        dependencies=[
            Depends(require_scopes(ApiScope.INGESTION_READ)),
            Depends(enforce_authenticated_rate(INSPECTION_READ)),
        ],
        response_model=IngestionRunPage,
        tags=["ingestion"],
        operation_id="listDocumentIngestionRuns",
        summary="List ingestion runs for one document.",
        responses={
            404: _problem_response("Document not found."),
            422: _problem_response("Request validation or cursor failure."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def list_document_ingestion_runs(
        document_id: UUID,
        query: Annotated[PaginationQuery, Query()],
    ) -> IngestionRunPage:
        if inspection is None:
            raise _unavailable()
        try:
            page = await inspection.list_document_runs(
                document_id,
                limit=query.limit,
                cursor=query.cursor,
                include_count=query.include_count,
            )
        except InspectionResourceNotFoundError as error:
            raise _not_found("Document") from error
        except InvalidInspectionCursorError as error:
            raise _invalid_cursor() from error
        return IngestionRunPage(
            items=[IngestionRun.model_validate(item, from_attributes=True) for item in page.items],
            previous_cursor=page.previous_cursor,
            next_cursor=page.next_cursor,
            total_items=page.total_items,
        )

    @router.get(
        "/ingestion-runs/{run_id}",
        dependencies=[
            Depends(require_scopes(ApiScope.INGESTION_READ)),
            Depends(enforce_authenticated_rate(INSPECTION_READ)),
        ],
        response_model=IngestionRunDetailResponse,
        tags=["ingestion"],
        operation_id="getIngestionRun",
        summary="Get an ingestion run and polling hint.",
        responses={
            404: _problem_response("Ingestion run not found."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def get_ingestion_run(
        run_id: UUID,
        response: Response,
    ) -> IngestionRunDetailResponse:
        if inspection is None:
            raise _unavailable()
        run = await inspection.get_ingestion_run(run_id)
        if run is None:
            raise _not_found("Ingestion run")
        response.headers["Cache-Control"] = "no-store"
        return IngestionRunDetailResponse(
            ingestion_run=IngestionRun.model_validate(run, from_attributes=True),
            poll_after_seconds=settings.ingestion_poll_after_seconds,
        )

    @router.get(
        "/documents/{document_id}/pages",
        dependencies=[
            Depends(require_scopes(ApiScope.INSPECTION_READ)),
            Depends(enforce_authenticated_rate(INSPECTION_READ)),
        ],
        response_model=PageSummaryPage,
        tags=["inspection"],
        operation_id="listDocumentPages",
        summary="List extracted pages for a document.",
        responses={
            404: _problem_response("Document not found."),
            422: _problem_response("Request validation or cursor failure."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def list_document_pages(
        document_id: UUID,
        query: Annotated[PaginationQuery, Query()],
    ) -> PageSummaryPage:
        if inspection is None:
            raise _unavailable()
        try:
            page = await inspection.list_pages(
                document_id,
                limit=query.limit,
                cursor=query.cursor,
                include_count=query.include_count,
            )
        except InspectionResourceNotFoundError as error:
            raise _not_found("Document") from error
        except InvalidInspectionCursorError as error:
            raise _invalid_cursor() from error
        return PageSummaryPage(
            items=[PageSummary.model_validate(item, from_attributes=True) for item in page.items],
            previous_cursor=page.previous_cursor,
            next_cursor=page.next_cursor,
            total_items=page.total_items,
        )

    @router.get(
        "/pages/{page_id}",
        dependencies=[
            Depends(require_scopes(ApiScope.INSPECTION_READ)),
            Depends(enforce_authenticated_rate(INSPECTION_READ)),
        ],
        response_model=PageDetail,
        tags=["inspection"],
        operation_id="getPage",
        summary="Get extraction detail for one page.",
        responses={
            404: _problem_response("Page not found."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def get_page(page_id: UUID) -> PageDetail:
        if inspection is None:
            raise _unavailable()
        detail = await inspection.get_page(page_id)
        if detail is None:
            raise _not_found("Page")
        return PageDetail.from_inspection(detail)

    @router.patch(
        "/pages/{page_id}",
        dependencies=[
            Depends(require_scopes(ApiScope.INSPECTION_WRITE)),
            Depends(enforce_authenticated_rate(ADMIN_WRITE)),
        ],
        response_model=PageDetail,
        tags=["inspection"],
        operation_id="updatePrintedPageLabel",
        summary="Correct the human-facing printed page label.",
        responses={
            404: _problem_response("Page not found."),
            422: _problem_response("Request validation failed."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def update_printed_page_label(
        page_id: UUID,
        request: UpdatePageRequest,
    ) -> PageDetail:
        if inspection is None:
            raise _unavailable()
        detail = await inspection.update_printed_page_label(
            page_id,
            request.printed_page_label,
        )
        if detail is None:
            raise _not_found("Page")
        return PageDetail.from_inspection(detail)

    @router.get(
        "/documents/{document_id}/chunks",
        dependencies=[
            Depends(require_scopes(ApiScope.INSPECTION_READ)),
            Depends(enforce_authenticated_rate(INSPECTION_READ)),
        ],
        response_model=ChunkPage,
        tags=["inspection"],
        operation_id="listDocumentChunks",
        summary="List extracted chunks for a document.",
        responses={
            404: _problem_response("Document or page not found."),
            422: _problem_response("Request validation or cursor failure."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def list_document_chunks(
        document_id: UUID,
        query: Annotated[ChunkListQuery, Query()],
    ) -> ChunkPage:
        if inspection is None:
            raise _unavailable()
        try:
            page = await inspection.list_chunks(
                document_id,
                page_id=query.page_id,
                limit=query.limit,
                cursor=query.cursor,
                include_count=query.include_count,
            )
        except InspectionResourceNotFoundError as error:
            raise _not_found("Document or page") from error
        except InvalidInspectionCursorError as error:
            raise _invalid_cursor() from error
        return ChunkPage(
            items=[ChunkSummary.model_validate(item, from_attributes=True) for item in page.items],
            previous_cursor=page.previous_cursor,
            next_cursor=page.next_cursor,
            total_items=page.total_items,
        )

    return router


__all__ = ["InspectionReader", "create_inspection_router"]
