"""Provider-neutral artifact keys and immutable storage results."""

import re
from dataclasses import dataclass

from tnpsc_book_rag.artifact_storage.errors import InvalidArtifactKeyError

_MAX_KEY_LENGTH = 1024
_MAX_SEGMENT_LENGTH = 255
_PORTABLE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"aux", "con", "nul", "prn"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


@dataclass(frozen=True, slots=True, order=True)
class ArtifactKey:
    """Validated portable POSIX-style key, never a caller-selected filesystem path."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value) > _MAX_KEY_LENGTH:
            msg = "artifact key must contain between 1 and 1024 characters"
            raise InvalidArtifactKeyError(msg)

        segments = self.value.split("/")
        for segment in segments:
            if (
                not segment
                or len(segment) > _MAX_SEGMENT_LENGTH
                or _PORTABLE_SEGMENT.fullmatch(segment) is None
                or segment.endswith(".")
                or segment.split(".", maxsplit=1)[0].casefold() in _WINDOWS_RESERVED_NAMES
            ):
                msg = "artifact key contains an unsafe or non-portable path segment"
                raise InvalidArtifactKeyError(msg)

    @property
    def parts(self) -> tuple[str, ...]:
        """Return already-validated path segments for a storage adapter."""
        return tuple(self.value.split("/"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    """Integrity metadata calculated from stored bytes."""

    key: ArtifactKey
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactWriteResult:
    """Metadata plus whether this operation created the immutable object."""

    artifact: ArtifactMetadata
    created: bool
