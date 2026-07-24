"""Implemented v1 capabilities and read-only catalog routes."""

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile, status

from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.http_api.auth import ApiScope, require_scopes
from tnpsc_book_rag.http_api.errors import ApiProblem, ValidationFieldError
from tnpsc_book_rag.http_api.rate_limits import (
    CATALOG_WRITE,
    PUBLIC_READ,
    UPLOAD_DAILY,
    UPLOAD_HOURLY,
    UPLOAD_USER_CONCURRENCY,
    enforce_authenticated_rate,
    enforce_concurrency,
    enforce_public_rate,
)
from tnpsc_book_rag.http_api.schemas import (
    Book,
    BookDetail,
    BookListQuery,
    BookPage,
    Capabilities,
    CapabilityFeatures,
    CapabilityLimits,
    CatalogBookOption,
    CatalogFilters,
    CreateBookRequest,
    DocumentSummary,
    DocumentUploadAccepted,
    IngestionRun,
    LibraryItem,
    LibraryResponse,
    Problem,
    TextbookStandard,
    UploadCapabilities,
    UploadLinks,
)
from tnpsc_book_rag.textbook_catalog.entities import NewBook
from tnpsc_book_rag.textbook_catalog.mutations import (
    BookMutationResult,
    BookNotFoundError,
    CatalogMutationUnavailableError,
    DuplicateCatalogIdentifierError,
    DuplicateSourceError,
    IdempotencyConflictError,
    PendingDocumentUpload,
    UnsupportedUploadMediaTypeError,
    UploadMutationResult,
    UploadTooLargeError,
)
from tnpsc_book_rag.textbook_catalog.read_models import (
    BookListFilters,
    CatalogBookDetail,
    CatalogFilterOptions,
    CatalogLibraryItem,
)
from tnpsc_book_rag.textbook_catalog.services import CatalogBookPage, InvalidCursorError


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

    async def get_library(self) -> tuple[CatalogLibraryItem, ...]: ...

    async def list_books(
        self,
        filters: BookListFilters,
        *,
        limit: int,
        cursor: str | None,
        include_count: bool,
    ) -> CatalogBookPage: ...

    async def create_book(
        self, new_book: NewBook, *, idempotency_key: str
    ) -> BookMutationResult: ...

    async def upload_document(
        self,
        book_id: UUID,
        upload: PendingDocumentUpload,
        *,
        idempotency_key: str,
    ) -> UploadMutationResult: ...


def _unavailable() -> ApiProblem:
    return ApiProblem(
        status=503,
        code="database_unavailable",
        title="Database unavailable",
        detail="The textbook catalog is temporarily unavailable.",
    )


def _mutation_problem(error: Exception) -> ApiProblem:
    if isinstance(error, IdempotencyConflictError):
        return ApiProblem(
            status=409,
            code="idempotency_conflict",
            title="Idempotency conflict",
            detail="The idempotency key was already used for a different request.",
        )
    if isinstance(error, DuplicateCatalogIdentifierError):
        return ApiProblem(
            status=409,
            code="invalid_state",
            title="Catalog identifier conflict",
            detail="The catalog identifier is already registered.",
        )
    if isinstance(error, DuplicateSourceError):
        return ApiProblem(
            status=409,
            code="duplicate_source",
            title="Duplicate source",
            detail="The same PDF is already registered in the textbook corpus.",
        )
    if isinstance(error, BookNotFoundError):
        return ApiProblem(
            status=404,
            code="not_found",
            title="Book not found",
            detail="The requested textbook does not exist.",
        )
    if isinstance(error, UploadTooLargeError):
        return ApiProblem(
            status=413,
            code="payload_too_large",
            title="Upload too large",
            detail="The PDF exceeds the configured upload limit.",
        )
    if isinstance(error, UnsupportedUploadMediaTypeError):
        return ApiProblem(
            status=415,
            code="unsupported_media_type",
            title="Unsupported media type",
            detail="The upload must be a PDF with a valid PDF signature.",
        )
    if isinstance(error, CatalogMutationUnavailableError):
        return ApiProblem(
            status=503,
            code="storage_unavailable",
            title="Storage unavailable",
            detail="Artifact storage is temporarily unavailable.",
        )
    if isinstance(error, ValueError):
        return ApiProblem(
            status=422,
            code="validation_error",
            title="Validation failed",
            detail="One or more request fields are invalid.",
            errors=(
                ValidationFieldError(
                    field="form.file",
                    message="The uploaded filename or edition is invalid.",
                    code="value_error",
                ),
            ),
        )
    raise error


def create_v1_router(
    settings: Settings,
    catalog: CatalogReader | None,
    *,
    ingestion_inspection: bool = False,
    semantic_search: bool = False,
    answer_generation: bool = False,
) -> APIRouter:
    """Create routes whose dependencies are fixed for one application instance."""
    router = APIRouter(prefix="/v1")

    @router.get(
        "/capabilities",
        dependencies=[Depends(enforce_public_rate(PUBLIC_READ))],
        response_model=Capabilities,
        tags=["capabilities"],
        operation_id="getCapabilities",
        summary="Return client-visible features and runtime limits.",
        responses={503: _problem_response("Service unavailable.")},
    )
    async def get_capabilities(response: Response) -> Capabilities:
        response.headers["Cache-Control"] = "no-store"
        return Capabilities(
            features=CapabilityFeatures(
                catalog_mutation=bool(
                    catalog is not None and getattr(catalog, "mutations_enabled", False)
                ),
                ingestion_inspection=ingestion_inspection,
                semantic_search=semantic_search,
                answer_generation=answer_generation,
                answer_streaming=answer_generation,
            ),
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
        dependencies=[Depends(enforce_public_rate(PUBLIC_READ))],
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
        "/library",
        dependencies=[Depends(enforce_public_rate(PUBLIC_READ))],
        response_model=LibraryResponse,
        tags=["catalog"],
        operation_id="getLibrary",
        summary="Return flat list of all textbook PDF source documents with metadata.",
        responses={503: _problem_response("Service unavailable.")},
    )
    async def get_library() -> LibraryResponse:
        if catalog is None:
            raise _unavailable()
        items = await catalog.get_library()
        return LibraryResponse(items=[LibraryItem.from_catalog_item(item) for item in items])

    @router.get(
        "/books",
        dependencies=[Depends(enforce_public_rate(PUBLIC_READ))],
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

    @router.post(
        "/books",
        dependencies=[
            Depends(require_scopes(ApiScope.CATALOG_WRITE)),
            Depends(enforce_authenticated_rate(CATALOG_WRITE)),
        ],
        response_model=Book,
        status_code=status.HTTP_201_CREATED,
        tags=["catalog"],
        operation_id="createBook",
        summary="Create a conceptual textbook.",
        responses={
            409: _problem_response("Request conflicts with mutation history or catalog state."),
            422: _problem_response("Request validation failed."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def create_book(
        request: CreateBookRequest,
        response: Response,
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=8,
                max_length=128,
                pattern=r"^[A-Za-z0-9._:-]+$",
            ),
        ],
    ) -> Book:
        if catalog is None:
            raise _unavailable()
        try:
            result = await catalog.create_book(
                NewBook(
                    title=request.title,
                    standard=int(request.standard),
                    subject=request.subject,
                    language=request.language,
                    publisher=request.publisher,
                    catalog_identifier=request.catalog_identifier,
                ),
                idempotency_key=idempotency_key,
            )
        except (ValueError, CatalogMutationUnavailableError) as error:
            raise _mutation_problem(error) from error
        response.status_code = result.status_code
        for name, value in result.headers.items():
            response.headers[name] = value
        return Book.from_catalog(result.value)

    @router.get(
        "/books/{book_id}",
        dependencies=[Depends(enforce_public_rate(PUBLIC_READ))],
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

    @router.post(
        "/books/{book_id}/documents",
        dependencies=[
            Depends(require_scopes(ApiScope.CATALOG_WRITE)),
            Depends(enforce_authenticated_rate(UPLOAD_HOURLY)),
            Depends(enforce_authenticated_rate(UPLOAD_DAILY)),
            Depends(enforce_concurrency(UPLOAD_USER_CONCURRENCY)),
        ],
        response_model=DocumentUploadAccepted,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["catalog", "ingestion"],
        operation_id="uploadBookDocument",
        summary="Upload and queue a digital textbook PDF.",
        responses={
            404: _problem_response("Book not found."),
            409: _problem_response("Request conflicts with mutation history or source content."),
            413: _problem_response("Upload exceeds the configured limit."),
            415: _problem_response("Upload is not a supported PDF."),
            422: _problem_response("Request validation failed."),
            503: _problem_response("Service unavailable."),
        },
    )
    async def upload_book_document(
        book_id: UUID,
        response: Response,
        file: Annotated[UploadFile, File()],
        edition: Annotated[str, Form(min_length=1, max_length=200)],
        idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                min_length=8,
                max_length=128,
                pattern=r"^[A-Za-z0-9._:-]+$",
            ),
        ],
    ) -> DocumentUploadAccepted:
        if catalog is None:
            raise _unavailable()
        try:
            result = await catalog.upload_document(
                book_id,
                PendingDocumentUpload(
                    filename=file.filename or "",
                    media_type=file.content_type or "",
                    edition=edition,
                    source=file.file,
                ),
                idempotency_key=idempotency_key,
            )
        except (ValueError, CatalogMutationUnavailableError) as error:
            raise _mutation_problem(error) from error
        response.status_code = result.status_code
        for name, value in result.headers.items():
            response.headers[name] = value
        accepted = result.value
        return DocumentUploadAccepted(
            document=DocumentSummary.from_document(accepted.document),
            ingestion_run=IngestionRun.model_validate(
                accepted.ingestion_run,
                from_attributes=True,
            ),
            poll_after_seconds=accepted.poll_after_seconds,
            links=UploadLinks(
                document=accepted.document_url,
                ingestion_run=accepted.ingestion_run_url,
            ),
        )

    return router
