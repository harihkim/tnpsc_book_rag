"""Security, integrity, and atomicity tests for local artifact storage."""

import asyncio
from collections.abc import Buffer
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest

from tnpsc_book_rag.artifact_storage import (
    ArtifactChecksumMismatchError,
    ArtifactConflictError,
    ArtifactKey,
    ArtifactNotFoundError,
    ArtifactTooLargeError,
    LocalArtifactStorage,
    UnsafeArtifactPathError,
    create_artifact_storage,
)
from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.telemetry_logging import correlation_context, get_correlation_context

_PAYLOAD = b"immutable textbook artifact\n" * 128


class FailingReader:
    """Binary source which fails after one successful chunk."""

    def __init__(self) -> None:
        self._reads = 0

    def read(self, size: int | None = -1, /) -> bytes:
        del size
        self._reads += 1
        if self._reads == 1:
            return b"partial"
        raise OSError("simulated source failure")


class ContextObservingReader:
    """Binary source which records correlation visible in its filesystem thread."""

    def __init__(self, value: bytes) -> None:
        self._source = BytesIO(value)
        self.seen_context: dict[str, str] | None = None

    def read(self, size: int | None = -1, /) -> bytes:
        self.seen_context = dict(get_correlation_context())
        return self._source.read(size)


class PartialWriter:
    """Destination which accepts only a bounded prefix on each write."""

    def __init__(self, max_write_size: int) -> None:
        self._max_write_size = max_write_size
        self.value = bytearray()

    def write(self, data: Buffer, /) -> int:
        accepted = bytes(memoryview(data)[: self._max_write_size])
        self.value.extend(accepted)
        return len(accepted)


class RefusingWriter:
    """Destination which makes no progress."""

    def write(self, data: Buffer, /) -> int:
        del data
        return 0


@pytest.fixture
def storage(tmp_path: Path) -> LocalArtifactStorage:
    return LocalArtifactStorage(tmp_path / "artifacts", chunk_size=64)


def test_constructor_validates_chunk_size(tmp_path: Path) -> None:
    """Invalid I/O configuration fails without touching the filesystem."""
    with pytest.raises(ValueError, match="chunk size must be positive"):
        LocalArtifactStorage(tmp_path / "invalid-size", chunk_size=0)


@pytest.mark.anyio
async def test_initialize_rejects_root_file(tmp_path: Path) -> None:
    """Startup rejects a configured root which is an ordinary file."""
    root_file = tmp_path / "root-file"
    root_file.write_bytes(b"not a directory")
    with pytest.raises(NotADirectoryError):
        await LocalArtifactStorage(root_file).initialize()


@pytest.mark.anyio
async def test_settings_factory_initializes_local_root_without_import_side_effects(
    tmp_path: Path,
) -> None:
    """Application wiring resolves the root but only startup creates it."""
    configured_root = tmp_path / "configured-artifacts"
    created = create_artifact_storage(Settings.model_validate({"artifact_root": configured_root}))

    assert isinstance(created, LocalArtifactStorage)
    assert created.root == configured_root.resolve()
    assert created.root.exists() is False
    await created.initialize()
    assert created.root.is_dir()


@pytest.mark.anyio
async def test_put_stat_and_copy_stream_without_loading_complete_file(
    storage: LocalArtifactStorage,
) -> None:
    """Stored metadata and copied bytes are calculated from the actual stream."""
    key = ArtifactKey("sources/ab/book.pdf")
    expected_sha256 = sha256(_PAYLOAD).hexdigest()

    result = await storage.put(
        key,
        BytesIO(_PAYLOAD),
        expected_sha256=expected_sha256,
    )
    stat_result = await storage.stat(key)
    destination = BytesIO()
    copied = await storage.copy_to(key, destination)

    assert result.created is True
    assert result.artifact == stat_result == copied
    assert result.artifact.size_bytes == len(_PAYLOAD)
    assert result.artifact.sha256 == expected_sha256
    assert destination.getvalue() == _PAYLOAD
    assert await storage.is_ready() is True


@pytest.mark.anyio
async def test_copy_handles_partial_destination_writes_and_rejects_no_progress(
    storage: LocalArtifactStorage,
) -> None:
    """Materialization works with ordinary short writes and fails on a stuck sink."""
    key = ArtifactKey("objects/partial-writer.bin")
    await storage.put(key, BytesIO(_PAYLOAD))
    partial_writer = PartialWriter(max_write_size=7)

    await storage.copy_to(key, partial_writer)
    assert bytes(partial_writer.value) == _PAYLOAD

    with pytest.raises(OSError, match="did not accept"):
        await storage.copy_to(key, RefusingWriter())


@pytest.mark.anyio
async def test_same_key_and_bytes_are_idempotent_but_different_bytes_conflict(
    storage: LocalArtifactStorage,
) -> None:
    """A durable evidence key can never silently change its content."""
    key = ArtifactKey("objects/immutable.bin")

    first = await storage.put(key, BytesIO(_PAYLOAD))
    repeated = await storage.put(key, BytesIO(_PAYLOAD))
    with pytest.raises(ArtifactConflictError):
        await storage.put(key, BytesIO(b"different"))

    destination = BytesIO()
    await storage.copy_to(key, destination)
    assert first.created is True
    assert repeated.created is False
    assert destination.getvalue() == _PAYLOAD


@pytest.mark.anyio
async def test_concurrent_same_content_writers_create_exactly_once(
    storage: LocalArtifactStorage,
) -> None:
    """The same-directory hard-link commit is race-safe and never overwrites."""
    key = ArtifactKey("objects/concurrent.bin")

    results = await asyncio.gather(
        storage.put(key, BytesIO(_PAYLOAD)),
        storage.put(key, BytesIO(_PAYLOAD)),
    )

    assert sum(result.created for result in results) == 1
    assert results[0].artifact == results[1].artifact


@pytest.mark.anyio
async def test_failed_stream_checksum_and_size_limit_leave_no_partial_artifacts(
    storage: LocalArtifactStorage,
) -> None:
    """All pre-commit failures clean their same-directory temporary files."""
    source_failure_key = ArtifactKey("objects/source-failure.bin")
    with pytest.raises(OSError, match="simulated source failure"):
        await storage.put(source_failure_key, FailingReader())

    checksum_failure_key = ArtifactKey("objects/checksum-failure.bin")
    with pytest.raises(ArtifactChecksumMismatchError):
        await storage.put(
            checksum_failure_key,
            BytesIO(_PAYLOAD),
            expected_sha256="0" * 64,
        )

    too_large_key = ArtifactKey("objects/too-large.bin")
    with pytest.raises(ArtifactTooLargeError):
        await storage.put(
            too_large_key,
            BytesIO(_PAYLOAD),
            max_bytes=len(_PAYLOAD) - 1,
        )

    for key in (source_failure_key, checksum_failure_key, too_large_key):
        with pytest.raises(ArtifactNotFoundError):
            await storage.stat(key)

    assert list(storage.root.rglob("*.tmp")) == []


@pytest.mark.anyio
async def test_invalid_operation_limit_is_rejected_before_io(
    storage: LocalArtifactStorage,
) -> None:
    """Negative limits cannot accidentally disable upload-size enforcement."""
    with pytest.raises(ValueError, match="cannot be negative"):
        await storage.put(
            ArtifactKey("objects/invalid-limit.bin"),
            BytesIO(_PAYLOAD),
            max_bytes=-1,
        )


@pytest.mark.anyio
async def test_symlinked_parent_cannot_escape_storage_root(
    storage: LocalArtifactStorage,
    tmp_path: Path,
) -> None:
    """Validated keys still cannot cross an operator-created local symlink."""
    outside = tmp_path / "outside"
    outside.mkdir()
    await storage.initialize()
    (storage.root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafeArtifactPathError):
        await storage.put(ArtifactKey("escape/file.bin"), BytesIO(_PAYLOAD))

    assert list(outside.iterdir()) == []


@pytest.mark.anyio
async def test_existing_file_cannot_be_used_as_an_artifact_parent(
    storage: LocalArtifactStorage,
) -> None:
    """Unexpected filesystem objects fail as unsafe paths rather than raw OS errors."""
    await storage.initialize()
    (storage.root / "blocked").write_bytes(b"file")

    with pytest.raises(UnsafeArtifactPathError, match="not a directory"):
        await storage.put(ArtifactKey("blocked/child.bin"), BytesIO(_PAYLOAD))


@pytest.mark.anyio
async def test_delete_is_explicit_and_idempotent(storage: LocalArtifactStorage) -> None:
    """Retention workflows can delete known keys without treating absence as failure."""
    key = ArtifactKey("objects/delete.bin")
    await storage.put(key, BytesIO(_PAYLOAD))

    assert await storage.delete(key) is True
    assert await storage.delete(key) is False
    with pytest.raises(ArtifactNotFoundError):
        await storage.stat(key)


@pytest.mark.anyio
async def test_storage_thread_preserves_approved_correlation_context(
    storage: LocalArtifactStorage,
) -> None:
    """Filesystem offloads retain stage correlation without serializing content."""
    source = ContextObservingReader(_PAYLOAD)

    with correlation_context(request_id="request-1", stage="uploaded"):
        await storage.put(ArtifactKey("objects/context.bin"), source)

    assert source.seen_context == {"request_id": "request-1", "stage": "uploaded"}
