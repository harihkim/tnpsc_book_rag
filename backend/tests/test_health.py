"""Tests for the API health endpoints."""

import logging

import pytest
from httpx2 import ASGITransport, AsyncClient

from tnpsc_book_rag.config import AppEnvironment, Settings
from tnpsc_book_rag.main import app, create_app
from tnpsc_book_rag.observability import create_telemetry


@pytest.mark.anyio
async def test_liveness() -> None:
    """The liveness endpoint reports that the API process is available."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_application_uses_validated_settings() -> None:
    """The application factory applies its explicit settings instance."""
    settings = Settings.model_validate(
        {
            "api_title": "Configured test API",
            "api_version": "9.9.9",
            "debug": True,
        }
    )

    configured_app = create_app(settings)

    assert configured_app.title == "Configured test API"
    assert configured_app.version == "9.9.9"
    assert configured_app.debug is True


@pytest.mark.anyio
async def test_application_lifespan_configures_and_shuts_down_observability() -> None:
    """The application owns logging and tracing lifecycle."""
    settings = Settings.model_validate({"environment": AppEnvironment.TEST, "otel_enabled": False})
    telemetry = create_telemetry(settings)
    configured_app = create_app(settings, telemetry=telemetry)
    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    previous_level = root_logger.level
    access_logger = logging.getLogger("uvicorn.access")
    access_was_disabled = access_logger.disabled

    try:
        async with configured_app.router.lifespan_context(configured_app):
            assert logging.getLogger("uvicorn.access").disabled is True
    finally:
        root_logger.handlers = previous_handlers
        root_logger.setLevel(previous_level)
        access_logger.disabled = access_was_disabled
