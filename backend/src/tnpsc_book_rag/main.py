"""FastAPI application entry point."""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from tnpsc_book_rag.config import Settings, get_settings


class HealthResponse(BaseModel):
    """Response returned by application health probes."""

    status: Literal["ok"]


async def liveness() -> HealthResponse:
    """Report whether the API process is running."""
    return HealthResponse(status="ok")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a FastAPI application from validated settings."""
    resolved_settings = settings or get_settings()
    application = FastAPI(
        title=resolved_settings.api_title,
        description="Retrieval-augmented generation over Tamil Nadu State Board textbooks.",
        version=resolved_settings.api_version,
        debug=resolved_settings.debug,
    )
    application.state.settings = resolved_settings
    application.add_api_route(
        "/health/live",
        liveness,
        methods=["GET"],
        response_model=HealthResponse,
        tags=["health"],
    )
    return application


app = create_app()
