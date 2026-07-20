"""Persistence boundary required by the extraction worker."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from tnpsc_book_rag.extraction.chunking import ExtractedChunk, TextbookChunkingResult
from tnpsc_book_rag.extraction.docling import ExtractionBundle
from tnpsc_book_rag.extraction.persistence import StoredAsset
from tnpsc_book_rag.ingestion.entities import IngestionWorkItem


class IngestionRepository(Protocol):
    """Worker-facing operations scoped to one caller-owned database transaction."""

    async def claim_next_ingestion_run(self, worker_id: str) -> IngestionWorkItem | None:
        """Claim the oldest queued run without waiting on another worker."""
        ...

    async def persist_extraction(
        self,
        work_item: IngestionWorkItem,
        bundle: ExtractionBundle,
        chunks: Sequence[ExtractedChunk],
        assets: Sequence[StoredAsset],
    ) -> None:
        """Persist pages, chunks, assets, and successful extraction state atomically."""
        ...

    async def persist_parent_child_extraction(
        self,
        work_item: IngestionWorkItem,
        bundle: ExtractionBundle,
        chunking: TextbookChunkingResult,
        assets: Sequence[StoredAsset],
    ) -> None:
        """Persist package-v2 parents, children, assets, and run metadata atomically."""
        ...

    async def mark_ingestion_failed(
        self,
        run_id: UUID,
        *,
        code: str,
        message: str,
        completed_at: datetime,
    ) -> None:
        """Record sanitized failure state without exposing exception details."""
        ...
