"""Tests for safe checksum-based offline package discovery."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import tnpsc_book_rag.ingestion.package_inbox as inbox_module
from tnpsc_book_rag.ingestion.package_inbox import (
    ExtractionPackageInbox,
    ExtractionPackageInboxError,
)


@pytest.mark.anyio
async def test_inbox_indexes_verified_archives_by_source_checksum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_checksum = "a" * 64
    second_checksum = "b" * 64
    first = tmp_path / "science.zip"
    second = tmp_path / "nested" / "mathematics.zip"
    second.parent.mkdir()
    first.write_bytes(b"science")
    second.write_bytes(b"mathematics")

    def verify(path: Path) -> SimpleNamespace:
        checksum = first_checksum if path.name == first.name else second_checksum
        return SimpleNamespace(source_sha256=checksum)

    async def run_direct(function, *args, **kwargs):  # type: ignore[no-untyped-def]
        return function(*args, **kwargs)

    monkeypatch.setattr(inbox_module, "verify_extraction_package", verify)
    monkeypatch.setattr(inbox_module, "run_in_thread_with_context", run_direct)
    inbox = ExtractionPackageInbox(tmp_path)

    assert await inbox.find_by_source_sha256(first_checksum) == first.resolve()
    assert await inbox.find_by_source_sha256(second_checksum) == second.resolve()
    assert await inbox.find_by_source_sha256("c" * 64) is None


@pytest.mark.anyio
async def test_inbox_rejects_duplicate_source_packages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checksum = "d" * 64
    (tmp_path / "variant-256.zip").write_bytes(b"256")
    (tmp_path / "variant-384.zip").write_bytes(b"384")

    async def run_direct(function, *args, **kwargs):  # type: ignore[no-untyped-def]
        return function(*args, **kwargs)

    monkeypatch.setattr(
        inbox_module,
        "verify_extraction_package",
        lambda _: SimpleNamespace(source_sha256=checksum),
    )
    monkeypatch.setattr(inbox_module, "run_in_thread_with_context", run_direct)

    with pytest.raises(ExtractionPackageInboxError, match="multiple archives"):
        await ExtractionPackageInbox(tmp_path).find_by_source_sha256(checksum)


@pytest.mark.anyio
async def test_inbox_rejects_missing_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_direct(function, *args, **kwargs):  # type: ignore[no-untyped-def]
        return function(*args, **kwargs)

    monkeypatch.setattr(inbox_module, "run_in_thread_with_context", run_direct)
    with pytest.raises(ExtractionPackageInboxError, match="regular directory"):
        await ExtractionPackageInbox(tmp_path / "missing").find_by_source_sha256("e" * 64)


@pytest.mark.anyio
async def test_inbox_rejects_symlink_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "inbox"
    root.symlink_to(target, target_is_directory=True)

    async def run_direct(function, *args, **kwargs):  # type: ignore[no-untyped-def]
        return function(*args, **kwargs)

    monkeypatch.setattr(inbox_module, "run_in_thread_with_context", run_direct)
    with pytest.raises(ExtractionPackageInboxError, match="regular directory"):
        await ExtractionPackageInbox(root).find_by_source_sha256("f" * 64)
