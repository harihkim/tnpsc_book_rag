"""Tests for the API health endpoints."""

import pytest
from httpx2 import ASGITransport, AsyncClient

from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.main import app, create_app


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
