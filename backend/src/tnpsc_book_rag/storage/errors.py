"""Stable artifact-storage failures for application and transport adapters."""


class ArtifactStorageError(Exception):
    """Base class for failures raised by an artifact storage adapter."""


class InvalidArtifactKeyError(ValueError, ArtifactStorageError):
    """Raised when an artifact key is unsafe or non-portable."""


class InvalidArtifactChecksumError(ValueError, ArtifactStorageError):
    """Raised when a caller supplies a malformed SHA-256 checksum."""


class UnsupportedArtifactMediaTypeError(ValueError, ArtifactStorageError):
    """Raised when no safe canonical asset extension exists for a media type."""


class UnsafeArtifactPathError(ArtifactStorageError):
    """Raised when a local path or symlink escapes the configured storage root."""


class ArtifactNotFoundError(ArtifactStorageError):
    """Raised when an artifact key has no stored regular file."""


class ArtifactConflictError(ArtifactStorageError):
    """Raised when immutable bytes already exist at a key with different content."""


class ArtifactChecksumMismatchError(ArtifactStorageError):
    """Raised when streamed content does not match its expected SHA-256 value."""


class ArtifactTooLargeError(ArtifactStorageError):
    """Raised when streamed content exceeds an operation-specific byte limit."""
