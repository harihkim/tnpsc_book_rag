"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from tnpsc_book_rag.config import Settings, get_settings
from tnpsc_book_rag.observability import (
    RequestObservabilityMiddleware,
    Telemetry,
    configure_logging,
    create_telemetry,
)


class HealthResponse(BaseModel):
    """Response returned by application health probes."""

    status: Literal["ok"]


async def liveness() -> HealthResponse:
    """Report whether the API process is running."""
    return HealthResponse(status="ok")


def create_app(
    settings: Settings | None = None,
    *,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    """Create a FastAPI application from validated settings."""
    resolved_settings = settings or get_settings()
    resolved_telemetry = telemetry or create_telemetry(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        configure_logging(resolved_settings)
        try:
            yield
        finally:
            resolved_telemetry.shutdown()

    application = FastAPI(
        title=resolved_settings.api_title,
        description="Retrieval-augmented generation over Tamil Nadu State Board textbooks.",
        version=resolved_settings.api_version,
        debug=resolved_settings.debug,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.telemetry = resolved_telemetry
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
    return application


app = create_app()
