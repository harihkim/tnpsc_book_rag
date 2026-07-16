"""Dependency-aware ingestion worker host; Phase 1 adds queue execution."""

import argparse
import asyncio
import json
import os
import signal
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import structlog

from tnpsc_book_rag.config import Settings, get_settings
from tnpsc_book_rag.db import DatabaseLifecycle, create_database
from tnpsc_book_rag.observability import (
    Telemetry,
    configure_logging,
    create_telemetry,
    run_in_thread_with_context,
)
from tnpsc_book_rag.storage import ArtifactStorageLifecycle, create_artifact_storage

_LOGGER = structlog.stdlib.get_logger(__name__)


class WorkerStartupError(RuntimeError):
    """Raised when a required worker dependency is not ready."""


def _write_heartbeat(path: Path) -> None:
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "pid": os.getpid(),
            "status": "ready",
            "updated_at": datetime.now(UTC).isoformat(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _remove_heartbeat(path: Path) -> None:
    path.unlink(missing_ok=True)


def worker_heartbeat_is_fresh(path: Path, *, stale_after_seconds: float) -> bool:
    """Return whether a valid ready heartbeat was updated within the health window."""
    try:
        if not path.is_file() or path.is_symlink():
            return False
        age_seconds = time.time() - path.stat().st_mtime
        if age_seconds < 0 or age_seconds > stale_after_seconds:
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("status") == "ready"
        and isinstance(payload.get("pid"), int)
        and isinstance(payload.get("updated_at"), str)
    )


class WorkerRuntime:
    """Own worker dependency checks, heartbeat, and graceful shutdown."""

    def __init__(
        self,
        settings: Settings,
        *,
        database: DatabaseLifecycle | None,
        artifact_storage: ArtifactStorageLifecycle,
        telemetry: Telemetry,
    ) -> None:
        self._settings = settings
        self._database = database
        self._artifact_storage = artifact_storage
        self._telemetry = telemetry

    async def run(self, stop: asyncio.Event) -> None:
        """Stay ready for Phase 1 queue work while publishing process health."""
        configure_logging(self._settings)
        try:
            await self._artifact_storage.initialize()
            if self._database is None or not await self._database.is_ready():
                raise WorkerStartupError("database is not ready")
            if not await self._artifact_storage.is_ready():
                raise WorkerStartupError("artifact storage is not ready")
            _LOGGER.info("worker_ready")
            while not stop.is_set():
                await run_in_thread_with_context(
                    _write_heartbeat,
                    self._settings.worker_heartbeat_path,
                )
                try:
                    await asyncio.wait_for(
                        stop.wait(),
                        timeout=self._settings.worker_heartbeat_interval_seconds,
                    )
                except TimeoutError:
                    continue
        finally:
            try:
                try:
                    await run_in_thread_with_context(
                        _remove_heartbeat,
                        self._settings.worker_heartbeat_path,
                    )
                except Exception:
                    _LOGGER.exception("worker_heartbeat_cleanup_failed")
            finally:
                try:
                    if self._database is not None:
                        try:
                            await self._database.close()
                        except Exception:
                            _LOGGER.exception("database_shutdown_failed")
                finally:
                    try:
                        self._telemetry.shutdown()
                    except Exception:
                        _LOGGER.exception("telemetry_shutdown_failed")
            _LOGGER.info("worker_stopped")


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for handled_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(handled_signal, stop.set)


async def _run_worker(settings: Settings) -> None:
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    runtime = WorkerRuntime(
        settings,
        database=create_database(settings),
        artifact_storage=create_artifact_storage(settings),
        telemetry=create_telemetry(settings),
    )
    await runtime.run(stop)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the container worker process or its local heartbeat health probe."""
    parser = argparse.ArgumentParser(prog="tnpsc-book-rag-worker")
    parser.add_argument("command", choices=("run", "health"))
    parsed = parser.parse_args(arguments)
    settings = get_settings()
    if parsed.command == "health":
        return (
            0
            if worker_heartbeat_is_fresh(
                settings.worker_heartbeat_path,
                stale_after_seconds=settings.worker_heartbeat_stale_after_seconds,
            )
            else 1
        )
    try:
        asyncio.run(_run_worker(settings))
    except WorkerStartupError as error:
        configure_logging(settings)
        _LOGGER.error(
            "worker_startup_failed",
            error_code="dependency_unavailable",
            error_type=f"{type(error).__module__}.{type(error).__qualname__}",
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
