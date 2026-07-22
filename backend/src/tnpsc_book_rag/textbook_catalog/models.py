"""Stable catalog enum values shared by persistence and application services."""

from enum import StrEnum

from tnpsc_extraction.models import ChunkContentType  # noqa: F401


class DocumentLanguage(StrEnum):
    """Languages accepted by the textbook catalog."""

    ENGLISH = "english"


class DocumentState(StrEnum):
    """Visibility and processing lifecycle of a textbook document."""

    UPLOADED = "uploaded"
    QUEUED = "queued"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"


class CatalogStatus(StrEnum):
    """Derived availability of a conceptual textbook in the catalog."""

    EMPTY = "empty"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class AssetType(StrEnum):
    """Supported classifications for images preserved from a textbook."""

    IMAGE = "image"
    DIAGRAM = "diagram"
    MAP = "map"
    PHOTOGRAPH = "photograph"
    FIGURE = "figure"
    UNKNOWN = "unknown"
