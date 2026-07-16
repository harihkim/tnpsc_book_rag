"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import partial
from typing import Literal

import structlog
from fastapi import FastAPI, Response, status
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

from tnpsc_book_rag.api.errors import install_exception_handlers
from tnpsc_book_rag.api.routes import CatalogReader, create_v1_router
from tnpsc_book_rag.catalog.services import CatalogService
from tnpsc_book_rag.config import Settings, get_settings
from tnpsc_book_rag.db import Database, DatabaseLifecycle, create_database
from tnpsc_book_rag.db.repositories import catalog_transaction
from tnpsc_book_rag.observability import (
    RequestObservabilityMiddleware,
    Telemetry,
    configure_logging,
    create_telemetry,
)
from tnpsc_book_rag.storage import ArtifactStorageLifecycle, create_artifact_storage

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


def create_app(
    settings: Settings | None = None,
    *,
    telemetry: Telemetry | None = None,
    database: DatabaseLifecycle | None = None,
    artifact_storage: ArtifactStorageLifecycle | None = None,
    catalog: CatalogReader | None = None,
) -> FastAPI:
    """Create a FastAPI application from validated settings."""
    resolved_settings = settings or get_settings()
    resolved_telemetry = telemetry or create_telemetry(resolved_settings)
    resolved_database = database if database is not None else create_database(resolved_settings)
    resolved_artifact_storage = artifact_storage or create_artifact_storage(resolved_settings)
    resolved_catalog = catalog
    if resolved_catalog is None and isinstance(resolved_database, Database):
        resolved_catalog = CatalogService(partial(catalog_transaction, resolved_database))

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
            yield
        finally:
            try:
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
    application.include_router(create_v1_router(resolved_settings, resolved_catalog))
    return application


app = create_app()
