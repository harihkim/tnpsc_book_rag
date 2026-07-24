"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import partial
from typing import Any, Literal

import structlog
from fastapi import FastAPI, Response, status
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from tnpsc_book_rag.artifact_storage import (
    ArtifactStorageLifecycle,
    LocalArtifactStorage,
    create_artifact_storage,
)
from tnpsc_book_rag.config import Settings, get_settings
from tnpsc_book_rag.database_persistence import Database, DatabaseLifecycle, create_database
from tnpsc_book_rag.database_persistence.repositories import (
    catalog_transaction,
    inspection_transaction,
)
from tnpsc_book_rag.debug_inspection import InspectionService
from tnpsc_book_rag.http_api.answer_service import AnswerOrchestrator
from tnpsc_book_rag.http_api.auth import AuthenticationService, create_authentication_service
from tnpsc_book_rag.http_api.errors import install_exception_handlers
from tnpsc_book_rag.http_api.inspection_routes import InspectionReader, create_inspection_router
from tnpsc_book_rag.http_api.rate_limits import RateLimiter, create_rate_limiter
from tnpsc_book_rag.http_api.routes import CatalogReader, create_v1_router
from tnpsc_book_rag.http_api.search_routes import (
    AnswerService,
    SearchService,
    create_search_router,
)
from tnpsc_book_rag.telemetry_logging import (
    RequestObservabilityMiddleware,
    Telemetry,
    configure_logging,
    create_telemetry,
)
from tnpsc_book_rag.textbook_catalog.services import CatalogService

_LOGGER = structlog.stdlib.get_logger(__name__)


class HealthResponse(BaseModel):
    """Response returned by application health probes."""

    status: Literal["ok"]


class ReadinessChecks(BaseModel):
    """Dependency status reported without exposing connection details."""

    database: Literal["ok", "unavailable", "not_configured"]
    artifact_storage: Literal["ok", "unavailable"]


class ReadinessResponse(BaseModel):
    """Response returned when checking required service dependencies."""

    status: Literal["ok", "not_ready"]
    checks: ReadinessChecks


async def liveness() -> HealthResponse:
    """Report whether the API process is running."""
    return HealthResponse(status="ok")


def _create_search_and_answer_services(
    settings: Settings,
    database: Database,
) -> tuple[SearchService | None, AnswerService | None]:
    """Create search and answer services when database is available."""
    from tnpsc_book_rag.rag_adapters.context import EvidenceContextAssembler
    from tnpsc_book_rag.rag_adapters.embeddings import EmbeddingService
    from tnpsc_book_rag.rag_adapters.generation import PydanticAIGenerator
    from tnpsc_book_rag.rag_adapters.retrieval import PgVectorRetriever

    embedding_service = EmbeddingService(
        model_identifier=settings.embedding_model_identifier,
        model_revision=settings.embedding_model_revision,
        device=settings.embedding_device,
        batch_size=settings.embedding_batch_size,
    )

    retriever = PgVectorRetriever(database, embedding_service)
    context_assembler = EvidenceContextAssembler(
        token_budget=settings.context_token_budget,
    )

    # Get OpenRouter API key
    openrouter_key = None
    if settings.openrouter_api_key is not None:
        openrouter_key = settings.openrouter_api_key.get_secret_value()

    generator = PydanticAIGenerator(
        provider=settings.llm_provider,
        model=settings.llm_model,
        fallback_model=settings.llm_fallback_model,
        openrouter_api_key=openrouter_key,
        timeout_seconds=settings.answer_timeout_seconds,
    )

    answer_orchestrator = AnswerOrchestrator(
        retriever=retriever,
        context_assembler=context_assembler,
        generator=generator,
    )

    return retriever, answer_orchestrator


_UNSET = object()


def create_app(
    settings: Settings | None = None,
    *,
    telemetry: Telemetry | None = None,
    database: DatabaseLifecycle | None | object = _UNSET,
    artifact_storage: ArtifactStorageLifecycle | None | object = _UNSET,
    catalog: CatalogReader | None = None,
    inspection: InspectionReader | None = None,
    authentication: AuthenticationService | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    """Create a FastAPI application from validated settings."""
    resolved_settings = settings or get_settings()
    resolved_telemetry = telemetry or create_telemetry(resolved_settings)
    resolved_database: Any = create_database(resolved_settings) if database is _UNSET else database
    resolved_artifact_storage: Any = (
        create_artifact_storage(resolved_settings)
        if artifact_storage is _UNSET
        else artifact_storage
    )
    resolved_catalog = catalog
    resolved_inspection = inspection
    resolved_authentication = authentication or create_authentication_service(resolved_settings)
    resolved_rate_limiter = rate_limiter or create_rate_limiter(resolved_settings)
    if resolved_catalog is None and isinstance(resolved_database, Database):
        resolved_catalog = CatalogService(
            partial(catalog_transaction, resolved_database),
            storage=(
                resolved_artifact_storage
                if isinstance(resolved_artifact_storage, LocalArtifactStorage)
                else None
            ),
            max_upload_bytes=resolved_settings.max_upload_bytes,
            idempotency_retention_seconds=resolved_settings.idempotency_retention_seconds,
            ingestion_poll_after_seconds=resolved_settings.ingestion_poll_after_seconds,
        )
    if resolved_inspection is None and isinstance(resolved_database, Database):
        resolved_inspection = InspectionService(partial(inspection_transaction, resolved_database))

    async def readiness(response: Response) -> ReadinessResponse:
        """Report required dependency readiness without leaking failure details."""
        database_status: Literal["ok", "unavailable", "not_configured"]
        if resolved_database is None:
            database_status = "not_configured"
        elif await resolved_database.is_ready():
            database_status = "ok"
        else:
            database_status = "unavailable"

        storage_status: Literal["ok", "unavailable"] = (
            "ok" if await resolved_artifact_storage.is_ready() else "unavailable"
        )
        checks = ReadinessChecks(
            database=database_status,
            artifact_storage=storage_status,
        )
        if database_status != "ok" or storage_status != "ok":
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(status="not_ready", checks=checks)
        return ReadinessResponse(status="ok", checks=checks)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        configure_logging(resolved_settings)
        try:
            await resolved_artifact_storage.initialize()
            await resolved_rate_limiter.initialize()
            yield
        finally:
            try:
                try:
                    await resolved_rate_limiter.close()
                except Exception:
                    _LOGGER.exception("rate_limiter_shutdown_failed")
                if resolved_database is not None:
                    try:
                        await resolved_database.close()
                    except Exception:
                        _LOGGER.exception("database_shutdown_failed")
            finally:
                try:
                    resolved_telemetry.shutdown()
                except Exception:
                    _LOGGER.exception("telemetry_shutdown_failed")

    application = FastAPI(
        title=resolved_settings.api_title,
        description="Retrieval-augmented generation over Tamil Nadu State Board textbooks.",
        version=resolved_settings.api_version,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.telemetry = resolved_telemetry
    application.state.database = resolved_database
    application.state.artifact_storage = resolved_artifact_storage
    application.state.catalog = resolved_catalog
    application.state.inspection = resolved_inspection
    application.state.authentication = resolved_authentication
    application.state.rate_limiter = resolved_rate_limiter
    install_exception_handlers(application)
    # Response decorators such as CORS must be registered after this boundary so
    # they wrap the generic 500 response produced before response headers are sent.
    application.add_middleware(
        RequestObservabilityMiddleware,
        telemetry=resolved_telemetry,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-None-Match",
            "X-Request-ID",
        ],
        expose_headers=[
            "Content-Disposition",
            "ETag",
            "Location",
            "Retry-After",
            "X-Request-ID",
        ],
        max_age=600,
    )
    application.add_api_route(
        "/health/live",
        liveness,
        methods=["GET"],
        response_model=HealthResponse,
        tags=["health"],
    )
    application.add_api_route(
        "/health/ready",
        readiness,
        methods=["GET"],
        response_model=ReadinessResponse,
        tags=["health"],
    )

    # Wire up search and answer services
    search_service: SearchService | None = None
    answer_service: AnswerService | None = None
    if isinstance(resolved_database, Database):
        search_service, answer_service = _create_search_and_answer_services(
            resolved_settings, resolved_database
        )
    application.state.search_service = search_service
    application.state.answer_service = answer_service

    application.include_router(
        create_v1_router(
            resolved_settings,
            resolved_catalog,
            ingestion_inspection=resolved_inspection is not None,
            semantic_search=search_service is not None,
            answer_generation=answer_service is not None,
        )
    )
    application.include_router(create_inspection_router(resolved_settings, resolved_inspection))
    application.include_router(create_search_router(search_service, answer_service))

    return application


app = create_app()
