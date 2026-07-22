"""Stable ingestion stage values shared by workers and persistence."""

from enum import StrEnum


class IngestionStage(StrEnum):
    """Durable processing milestone currently entered by an ingestion run."""

    QUEUED = "queued"
    EXTRACTION = "extraction"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    ACTIVATION = "activation"
