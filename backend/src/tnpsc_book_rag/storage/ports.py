"""Storage protocols kept independent from local filesystems and object stores."""

from collections.abc import Buffer
from typing import Protocol

from tnpsc_book_rag.storage.models import ArtifactKey, ArtifactMetadata, ArtifactWriteResult


class ReadableBinary(Protocol):
    """Synchronous binary source consumed from its current position in a worker thread."""

    def read(self, size: int = -1, /) -> bytes:
        """Read at most ``size`` bytes, returning empty bytes at EOF."""
        ...


class WritableBinary(Protocol):
    """Synchronous binary destination written from a worker thread."""

    def write(self, data: Buffer, /) -> int:
        """Write bytes and optionally return the number accepted."""
        ...


class ArtifactStorageLifecycle(Protocol):
    """Small application boundary used by startup and readiness checks."""

    async def initialize(self) -> None:
        """Prepare the backing store before the application begins serving."""
        ...

    async def is_ready(self) -> bool:
        """Return whether the backing store is available for ordinary I/O."""
        ...


class ArtifactStorage(ArtifactStorageLifecycle, Protocol):
    """Async, provider-neutral storage boundary for immutable durable artifacts."""

    async def put(
        self,
        key: ArtifactKey,
        source: ReadableBinary,
        *,
        expected_sha256: str | None = None,
        max_bytes: int | None = None,
    ) -> ArtifactWriteResult:
        """Atomically create or idempotently confirm an immutable artifact."""
        ...

    async def copy_to(
        self,
        key: ArtifactKey,
        destination: WritableBinary,
    ) -> ArtifactMetadata:
        """Stream an artifact into a caller-owned destination and calculate its checksum."""
        ...

    async def stat(self, key: ArtifactKey) -> ArtifactMetadata:
        """Return integrity metadata calculated from the currently stored bytes."""
        ...

    async def delete(self, key: ArtifactKey) -> bool:
        """Delete an artifact, returning whether a file existed."""
        ...
