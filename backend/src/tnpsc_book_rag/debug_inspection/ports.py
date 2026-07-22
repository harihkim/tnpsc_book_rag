"""Persistence contracts required by the inspection application service."""

from typing import Protocol
from uuid import UUID

from tnpsc_book_rag.ingestion_pipeline.entities import IngestionRun
from tnpsc_book_rag.debug_inspection.models import (
    ChunkOrderKey,
    ChunkSummary,
    DocumentInspection,
    IngestionOperation,
    InspectionWindow,
    PageDetail,
    PageOrderKey,
    PageSummary,
    RunListFilters,
    RunOrderKey,
)


class InspectionRepository(Protocol):
    """Load administrative projections without owning transaction completion."""

    async def get_document(self, document_id: UUID) -> DocumentInspection | None: ...

    async def get_ingestion_run(self, run_id: UUID) -> IngestionRun | None: ...

    async def list_ingestion_operations(
        self,
        filters: RunListFilters,
        *,
        limit: int,
        after: RunOrderKey | None,
        before: RunOrderKey | None,
    ) -> InspectionWindow[IngestionOperation]: ...

    async def count_ingestion_operations(self, filters: RunListFilters) -> int: ...

    async def list_document_runs(
        self,
        document_id: UUID,
        *,
        limit: int,
        after: RunOrderKey | None,
        before: RunOrderKey | None,
    ) -> InspectionWindow[IngestionRun]: ...

    async def count_document_runs(self, document_id: UUID) -> int: ...

    async def list_pages(
        self,
        document_id: UUID,
        *,
        limit: int,
        after: PageOrderKey | None,
        before: PageOrderKey | None,
    ) -> InspectionWindow[PageSummary]: ...

    async def count_pages(self, document_id: UUID) -> int: ...

    async def get_page(self, page_id: UUID) -> PageDetail | None: ...

    async def update_printed_page_label(
        self, page_id: UUID, printed_page_label: str | None
    ) -> PageDetail | None: ...

    async def page_belongs_to_document(self, page_id: UUID, document_id: UUID) -> bool: ...

    async def list_chunks(
        self,
        document_id: UUID,
        *,
        page_id: UUID | None,
        limit: int,
        after: ChunkOrderKey | None,
        before: ChunkOrderKey | None,
    ) -> InspectionWindow[ChunkSummary]: ...

    async def count_chunks(self, document_id: UUID, *, page_id: UUID | None) -> int: ...
