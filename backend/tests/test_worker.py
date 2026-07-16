"""Tests for the dependency-aware Phase 0 worker host and health heartbeat."""

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import cast

import pytest

from tnpsc_book_rag.config import AppEnvironment, Settings
from tnpsc_book_rag.observability import Telemetry
from tnpsc_book_rag.worker import (
    WorkerRuntime,
    WorkerStartupError,
    worker_heartbeat_is_fresh,
)


class FakeDatabase:
    """Controllable worker database lifecycle."""

    def __init__(self, *, ready: bool) -> None:
        self.ready = ready
        self.closed = False

    async def is_ready(self) -> bool:
        return self.ready

    async def close(self) -> None:
        self.closed = True


class FakeArtifactStorage:
    """Controllable worker artifact lifecycle."""

    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.initialized = False

    async def initialize(self) -> None:
        self.initialized = True

    async def is_ready(self) -> bool:
        return self.ready


class FakeTelemetry:
    """Record worker telemetry shutdown without an exporter."""

    def __init__(self) -> None:
        self.shutdown_called = False

    def shutdown(self) -> None:
        self.shutdown_called = True


def _settings(path: Path) -> Settings:
    return Settings.model_validate(
        {
            "environment": AppEnvironment.TEST,
            "otel_enabled": False,
            "worker_heartbeat_path": path,
            "worker_heartbeat_interval_seconds": 0.5,
            "worker_heartbeat_stale_after_seconds": 2.0,
        }
    )


def test_worker_health_rejects_missing_stale_malformed_and_symlink_heartbeats(
    tmp_path: Path,
) -> None:
    """Container health depends on a recent regular file with the closed ready shape."""
    heartbeat = tmp_path / "worker.json"
    assert worker_heartbeat_is_fresh(heartbeat, stale_after_seconds=2) is False

    heartbeat.write_text(
        json.dumps({"pid": 123, "status": "ready", "updated_at": "2026-07-16T12:00:00Z"}),
        encoding="utf-8",
    )
    assert worker_heartbeat_is_fresh(heartbeat, stale_after_seconds=2) is True

    old_time = time.time() - 10
    os.utime(heartbeat, (old_time, old_time))
    assert worker_heartbeat_is_fresh(heartbeat, stale_after_seconds=2) is False

    heartbeat.write_text("not-json", encoding="utf-8")
    assert worker_heartbeat_is_fresh(heartbeat, stale_after_seconds=2) is False

    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    heartbeat.unlink()
    heartbeat.symlink_to(target)
    assert worker_heartbeat_is_fresh(heartbeat, stale_after_seconds=2) is False


@pytest.mark.anyio
async def test_worker_checks_dependencies_publishes_health_and_cleans_up(tmp_path: Path) -> None:
    """A running worker is healthy only after dependencies pass and always closes resources."""
    heartbeat = tmp_path / "worker.json"
    settings = _settings(heartbeat)
    database = FakeDatabase(ready=True)
    storage = FakeArtifactStorage()
    telemetry = FakeTelemetry()
    runtime = WorkerRuntime(
        settings,
        database=database,
        artifact_storage=storage,
        telemetry=cast(Telemetry, telemetry),
    )
    stop = asyncio.Event()
    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    previous_level = root_logger.level

    try:
        task = asyncio.create_task(runtime.run(stop))
        for _ in range(100):
            if heartbeat.exists():
                break
            await asyncio.sleep(0.01)
        assert worker_heartbeat_is_fresh(heartbeat, stale_after_seconds=2)
        stop.set()
        await task
    finally:
        root_logger.handlers = previous_handlers
        root_logger.setLevel(previous_level)

    assert storage.initialized is True
    assert database.closed is True
    assert telemetry.shutdown_called is True
    assert heartbeat.exists() is False


@pytest.mark.anyio
async def test_worker_fails_startup_safely_when_database_is_unavailable(
    tmp_path: Path,
) -> None:
    """No heartbeat survives a failed readiness check and cleanup still runs."""
    heartbeat = tmp_path / "worker.json"
    database = FakeDatabase(ready=False)
    telemetry = FakeTelemetry()
    runtime = WorkerRuntime(
        _settings(heartbeat),
        database=database,
        artifact_storage=FakeArtifactStorage(),
        telemetry=cast(Telemetry, telemetry),
    )
    root_logger = logging.getLogger()
    previous_handlers = list(root_logger.handlers)
    previous_level = root_logger.level

    try:
        with pytest.raises(WorkerStartupError):
            await runtime.run(asyncio.Event())
    finally:
        root_logger.handlers = previous_handlers
        root_logger.setLevel(previous_level)

    assert database.closed is True
    assert telemetry.shutdown_called is True
    assert heartbeat.exists() is False
