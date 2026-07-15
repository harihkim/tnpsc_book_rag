"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal

import structlog
from fastapi import FastAPI, Response, status
from pydantic import BaseModel

from tnpsc_book_rag.config import Settings, get_settings
from tnpsc_book_rag.db import DatabaseLifecycle, create_database
from tnpsc_book_rag.observability import (
    RequestObservabilityMiddleware,
    Telemetry,
    configure_logging,
    create_telemetry,
)

_LOGGER = structlog.stdlib.get_logger(__name__)


class HealthResponse(BaseModel):
    """Response returned by application health probes."""

    status: Literal["ok"]


class ReadinessChecks(BaseModel):
    """Dependency status reported without exposing connection details."""

    database: Literal["ok", "unavailable", "not_configured"]


class ReadinessResponse(BaseModel):
    """Response returned when checking whether the API can serve database work."""

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
) -> FastAPI:
    """Create a FastAPI application from validated settings."""
    resolved_settings = settings or get_settings()
    resolved_telemetry = telemetry or create_telemetry(resolved_settings)
    resolved_database = database if database is not None else create_database(resolved_settings)

    async def readiness(response: Response) -> ReadinessResponse:
        """Report database and migration readiness without leaking failure details."""
        if resolved_database is None:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(
                status="not_ready",
                checks=ReadinessChecks(database="not_configured"),
            )
        if not await resolved_database.is_ready():
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(
                status="not_ready",
                checks=ReadinessChecks(database="unavailable"),
            )
        return ReadinessResponse(status="ok", checks=ReadinessChecks(database="ok"))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        configure_logging(resolved_settings)
        try:
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
    # Response decorators such as CORS must be registered after this boundary so
    # they wrap the generic 500 response produced before response headers are sent.
    application.add_middleware(
        RequestObservabilityMiddleware,
        telemetry=resolved_telemetry,
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
    return application


app = create_app()
