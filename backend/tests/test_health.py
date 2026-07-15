"""Tests for the API health endpoints."""

import asyncio
import json
import logging
from typing import override

import pytest
from httpx2 import ASGITransport, AsyncClient

from tnpsc_book_rag.config import AppEnvironment, Settings
from tnpsc_book_rag.main import app, create_app
from tnpsc_book_rag.observability import Telemetry, create_telemetry


class FakeDatabase:
    """Controllable database boundary for API lifecycle tests."""

    def __init__(self, *, ready: bool) -> None:
        self.ready = ready
        self.closed = False

    async def is_ready(self) -> bool:
        return self.ready

    async def close(self) -> None:
        self.closed = True


class FailingDatabase(FakeDatabase):
    """Database boundary that exposes ordinary shutdown failure behavior."""

    @override
    async def close(self) -> None:
        self.closed = True
        raise RuntimeError("sensitive database shutdown detail")


class CancelledDatabase(FakeDatabase):
    """Database boundary that simulates cancellation during async cleanup."""

    @override
    async def close(self) -> None:
        self.closed = True
        raise asyncio.CancelledError


class FakeArtifactStorage:
    """Controllable storage lifecycle for API readiness and startup tests."""

    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.initialized = False

    async def initialize(self) -> None:
        self.initialized = True

    async def is_ready(self) -> bool:
        return self.ready


@pytest.mark.anyio
async def test_liveness() -> None:
    """The liveness endpoint reports that the API process is available."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
@pytest.mark.parametrize(
    (
        "database",
        "artifact_storage",
        "expected_status",
        "expected_database",
        "expected_storage",
    ),
    [
        (FakeDatabase(ready=True), FakeArtifactStorage(ready=True), 200, "ok", "ok"),
        (
            FakeDatabase(ready=False),
            FakeArtifactStorage(ready=True),
            503,
            "unavailable",
            "ok",
        ),
        (None, FakeArtifactStorage(ready=True), 503, "not_configured", "ok"),
        (
            FakeDatabase(ready=True),
            FakeArtifactStorage(ready=False),
            503,
            "ok",
            "unavailable",
        ),
    ],
)
async def test_readiness_reports_required_dependency_state_without_details(
    database: FakeDatabase | None,
    artifact_storage: FakeArtifactStorage,
    expected_status: int,
    expected_database: str,
    expected_storage: str,
) -> None:
    """Readiness distinguishes safe dependency states without exposing paths or a DSN."""
    settings = Settings.model_validate({"environment": AppEnvironment.TEST})
    configured_app = create_app(
        settings,
        database=database,
        artifact_storage=artifact_storage,
    )
    transport = ASGITransport(app=configured_app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health/ready")

    assert response.status_code == expected_status
    assert response.json()["checks"] == {
        "database": expected_database,
        "artifact_storage": expected_storage,
    }


def test_application_uses_validated_settings() -> None:
    """The application factory applies its explicit settings instance."""
    settings = Settings.model_validate(
        {
            "api_title": "Configured test API",
            "api_version": "9.9.9",
            "debug": True,
        }
    )

    configured_app = create_app(settings, artifact_storage=FakeArtifactStorage())

    assert configured_app.title == "Configured test API"
    assert configured_app.version == "9.9.9"
    assert configured_app.debug is True


@pytest.mark.anyio
async def test_application_lifespan_configures_and_shuts_down_observability() -> None:
    """The application owns logging, tracing, and database lifecycle."""
    settings = Settings.model_validate({"environment": AppEnvironment.TEST, "otel_enabled": False})
    telemetry = create_telemetry(settings)
    database = FakeDatabase(ready=True)
    artifact_storage = FakeArtifactStorage()
    configured_app = create_app(
        settings,
        telemetry=telemetry,
        database=database,
        artifact_storage=artifact_storage,
    )
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

    assert database.closed is True
    assert artifact_storage.initialized is True


@pytest.mark.anyio
async def test_cleanup_failures_are_isolated_and_logged_without_messages(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each ordinary cleanup failure is recorded without blocking the next cleanup."""
    settings = Settings.model_validate({"environment": AppEnvironment.TEST, "otel_enabled": False})
    telemetry = create_telemetry(settings)
    database = FailingDatabase(ready=True)
    configured_app = create_app(
        settings,
        telemetry=telemetry,
        database=database,
        artifact_storage=FakeArtifactStorage(),
    )
    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    previous_level = root_logger.level

    def fail_telemetry_shutdown(_: Telemetry) -> None:
        raise RuntimeError("sensitive telemetry shutdown detail")

    monkeypatch.setattr(Telemetry, "shutdown", fail_telemetry_shutdown)
    try:
        async with configured_app.router.lifespan_context(configured_app):
            pass
        output = capsys.readouterr().out
    finally:
        root_logger.handlers = previous_handlers
        root_logger.setLevel(previous_level)

    payloads = [json.loads(line) for line in output.splitlines()]
    assert database.closed is True
    assert {payload["event"] for payload in payloads} == {
        "database_shutdown_failed",
        "telemetry_shutdown_failed",
    }
    assert {payload["error_type"] for payload in payloads} == {"builtins.RuntimeError"}
    assert "sensitive" not in output


@pytest.mark.anyio
async def test_cancellation_during_database_close_still_shuts_down_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BaseException cancellation propagates only after telemetry cleanup is attempted."""
    settings = Settings.model_validate({"environment": AppEnvironment.TEST, "otel_enabled": False})
    telemetry = create_telemetry(settings)
    database = CancelledDatabase(ready=True)
    configured_app = create_app(
        settings,
        telemetry=telemetry,
        database=database,
        artifact_storage=FakeArtifactStorage(),
    )
    telemetry_shutdown_called = False
    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    previous_level = root_logger.level

    def record_telemetry_shutdown(_: Telemetry) -> None:
        nonlocal telemetry_shutdown_called
        telemetry_shutdown_called = True

    monkeypatch.setattr(Telemetry, "shutdown", record_telemetry_shutdown)
    try:
        with pytest.raises(asyncio.CancelledError):
            async with configured_app.router.lifespan_context(configured_app):
                pass
    finally:
        root_logger.handlers = previous_handlers
        root_logger.setLevel(previous_level)

    assert database.closed is True
    assert telemetry_shutdown_called
