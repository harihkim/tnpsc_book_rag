"""Atomic local-filesystem implementation of the artifact storage boundary."""

import os
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from tnpsc_book_rag.observability import run_in_thread_with_context
from tnpsc_book_rag.storage.errors import (
    ArtifactChecksumMismatchError,
    ArtifactConflictError,
    ArtifactNotFoundError,
    ArtifactTooLargeError,
    UnsafeArtifactPathError,
)
from tnpsc_book_rag.storage.keys import validate_sha256
from tnpsc_book_rag.storage.models import ArtifactKey, ArtifactMetadata, ArtifactWriteResult
from tnpsc_book_rag.storage.ports import ReadableBinary, WritableBinary

_DEFAULT_CHUNK_SIZE = 1024 * 1024


class LocalArtifactStorage:
    """Write-once local artifact storage rooted outside publicly served paths."""

    def __init__(self, root: Path, *, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> None:
        if chunk_size <= 0:
            msg = "artifact I/O chunk size must be positive"
            raise ValueError(msg)

        self._root = root.expanduser().resolve()
        self._chunk_size = chunk_size

    @property
    def root(self) -> Path:
        """Return the resolved adapter root for lifecycle wiring and diagnostics."""
        return self._root

    async def initialize(self) -> None:
        """Create and validate the configured root outside module import time."""
        await run_in_thread_with_context(self._initialize)

    async def put(
        self,
        key: ArtifactKey,
        source: ReadableBinary,
        *,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> ArtifactWriteResult:
        """Stream to a same-directory temporary file and atomically link it into place."""
        normalized_checksum = (
            validate_sha256(expected_sha256) if expected_sha256 is not None else None
        )
        if max_bytes is not None and max_bytes < 0:
            msg = "artifact byte limit cannot be negative"
            raise ValueError(msg)
        return await run_in_thread_with_context(
            self._put,
            key,
            source,
            normalized_checksum,
            max_bytes,
        )

    async def copy_to(
        self,
        key: ArtifactKey,
        destination: WritableBinary,
    ) -> ArtifactMetadata:
        """Copy stored bytes without materializing the complete artifact in memory."""
        return await run_in_thread_with_context(self._copy_to, key, destination)

    async def stat(self, key: ArtifactKey) -> ArtifactMetadata:
        """Recalculate size and checksum so corruption is not hidden by cached metadata."""
        return await run_in_thread_with_context(self._stat, key)

    async def delete(self, key: ArtifactKey) -> bool:
        """Remove one regular artifact without following symlinks."""
        return await run_in_thread_with_context(self._delete, key)

    async def is_ready(self) -> bool:
        """Check the initialized root without creating health-check probe files."""
        return await run_in_thread_with_context(self._is_ready)

    def _put(
        self,
        key: ArtifactKey,
        source: ReadableBinary,
        expected_sha256: str | None,
        max_bytes: int | None,
    ) -> ArtifactWriteResult:
        self._initialize()
        target = self._prepare_target(key)
        temporary_path: Path | None = None

        try:
            digest = sha256()
            size_bytes = 0
            with NamedTemporaryFile(
                mode="w+b",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                while chunk := source.read(self._chunk_size):
                    size_bytes += len(chunk)
                    if max_bytes is not None and size_bytes > max_bytes:
                        raise ArtifactTooLargeError(
                            f"artifact exceeds the {max_bytes}-byte operation limit"
                        )
                    temporary.write(chunk)
                    digest.update(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())

            actual_sha256 = digest.hexdigest()
            if expected_sha256 is not None and actual_sha256 != expected_sha256:
                raise ArtifactChecksumMismatchError("artifact bytes do not match expected SHA-256")

            metadata = ArtifactMetadata(
                key=key,
                size_bytes=size_bytes,
                sha256=actual_sha256,
            )
            try:
                os.link(temporary_path, target)
            except FileExistsError:
                existing = self._stat(key)
                if existing.size_bytes != size_bytes or existing.sha256 != actual_sha256:
                    raise ArtifactConflictError(
                        "immutable artifact key already contains different bytes"
                    ) from None
                return ArtifactWriteResult(artifact=existing, created=False)

            self._fsync_directory(target.parent)
            return ArtifactWriteResult(artifact=metadata, created=True)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _copy_to(self, key: ArtifactKey, destination: WritableBinary) -> ArtifactMetadata:
        path = self._existing_file(key)
        digest = sha256()
        size_bytes = 0
        with path.open("rb") as source:
            while chunk := source.read(self._chunk_size):
                self._write_all(destination, chunk)
                digest.update(chunk)
                size_bytes += len(chunk)
        return ArtifactMetadata(key=key, size_bytes=size_bytes, sha256=digest.hexdigest())

    def _stat(self, key: ArtifactKey) -> ArtifactMetadata:
        path = self._existing_file(key)
        digest = sha256()
        size_bytes = 0
        with path.open("rb") as artifact:
            while chunk := artifact.read(self._chunk_size):
                digest.update(chunk)
                size_bytes += len(chunk)
        return ArtifactMetadata(key=key, size_bytes=size_bytes, sha256=digest.hexdigest())

    def _delete(self, key: ArtifactKey) -> bool:
        path = self._artifact_path(key)
        if not path.exists():
            return False
        if not path.is_file():
            raise ArtifactConflictError("artifact key does not identify a regular file")
        path.unlink()
        self._fsync_directory(path.parent)
        return True

    def _is_ready(self) -> bool:
        return self._root.is_dir() and os.access(self._root, os.R_OK | os.W_OK | os.X_OK)

    def _initialize(self) -> None:
        try:
            self._root.mkdir(mode=0o750, parents=True, exist_ok=True)
        except FileExistsError:
            raise NotADirectoryError(self._root) from None
        if not self._root.is_dir():
            raise NotADirectoryError(self._root)

    def _prepare_target(self, key: ArtifactKey) -> Path:
        current = self._root
        for part in key.parts[:-1]:
            current /= part
            if current.is_symlink():
                raise UnsafeArtifactPathError("artifact storage refuses to follow symlinks")
            try:
                current.mkdir(mode=0o750, exist_ok=True)
            except FileExistsError:
                raise UnsafeArtifactPathError("artifact parent is not a directory") from None
            if not current.is_dir():
                raise UnsafeArtifactPathError("artifact parent is not a directory")
        return self._artifact_path(key)

    def _artifact_path(self, key: ArtifactKey) -> Path:
        candidate = self._root.joinpath(*key.parts)
        current = self._root
        for part in key.parts:
            current /= part
            if current.is_symlink():
                raise UnsafeArtifactPathError("artifact storage refuses to follow symlinks")

        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise UnsafeArtifactPathError("artifact path escapes the configured storage root")
        return resolved

    def _existing_file(self, key: ArtifactKey) -> Path:
        path = self._artifact_path(key)
        if not path.exists():
            raise ArtifactNotFoundError("artifact does not exist")
        if not path.is_file():
            raise ArtifactConflictError("artifact key does not identify a regular file")
        return path

    @staticmethod
    def _write_all(destination: WritableBinary, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = destination.write(data[offset:])
            if written <= 0:
                raise OSError("artifact destination did not accept streamed bytes")
            offset += written

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
