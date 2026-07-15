"""Tests for the API health endpoints."""

import pytest
from httpx2 import ASGITransport, AsyncClient

from tnpsc_book_rag.main import app


@pytest.mark.anyio
async def test_liveness() -> None:
    """The liveness endpoint reports that the API process is available."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
