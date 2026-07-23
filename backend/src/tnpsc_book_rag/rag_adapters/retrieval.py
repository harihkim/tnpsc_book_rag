"""pgvector-backed semantic retrieval implementing the tnpsc_rag Retriever protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tnpsc_rag.models import (
    Evidence,
    SearchHit,
    SearchRequest,
    SearchResult,
    TextbookStandard,
)

if TYPE_CHECKING:
    from tnpsc_book_rag.database_persistence.database import Database
    from tnpsc_book_rag.rag_adapters.embeddings import EmbeddingService

_LOGGER = structlog.stdlib.get_logger(__name__)


class PgVectorRetriever:
    """Retrieve ranked textbook evidence using cosine similarity over pgvector."""

    def __init__(
        self,
        database: Database,
        embedding_service: EmbeddingService,
    ) -> None:
        self._database = database
        self._embedding_service = embedding_service

    async def search(self, request: SearchRequest) -> SearchResult:
        """Search the active textbook corpus using cosine similarity."""
        query_vector = self._embedding_service.embed_query(request.query)

        async with self._database.sessions() as session:
            hits = await self._execute_search(session, request, query_vector)

        return SearchResult(request=request, hits=tuple(hits))

    async def _execute_search(
        self,
        session: AsyncSession,
        request: SearchRequest,
        query_vector: list[float],
    ) -> list[SearchHit]:
        """Execute the pgvector similarity search with filters."""
        from tnpsc_book_rag.database_persistence.models import (
            BookDocumentRecord,
            BookRecord,
            ChunkEmbeddingRecord,
            ChunkRecord,
            ContentUnitRecord,
            PageRecord,
        )

        # Build the base query joining chunks -> embeddings -> pages -> documents -> books
        # Only search active, ready documents
        embedding_col = ChunkEmbeddingRecord.embedding

        # Cosine similarity: 1 - cosine_distance
        # pgvector cosine distance operator is <=>
        similarity = 1 - embedding_col.cosine_distance(query_vector)

        stmt = (
            select(
                ChunkRecord.id.label("chunk_id"),
                ChunkRecord.display_text,
                ChunkRecord.content_type,
                ChunkRecord.section_path,
                PageRecord.id.label("page_id"),
                PageRecord.pdf_page_index,
                PageRecord.printed_page_label,
                BookDocumentRecord.id.label("document_id"),
                BookDocumentRecord.edition,
                BookRecord.id.label("book_id"),
                BookRecord.title.label("book_title"),
                BookRecord.standard,
                BookRecord.subject,
                similarity.label("score"),
            )
            .join(
                ChunkEmbeddingRecord,
                ChunkEmbeddingRecord.chunk_id == ChunkRecord.id,
            )
            .join(PageRecord, PageRecord.id == ChunkRecord.page_id)
            .join(
                BookDocumentRecord,
                BookDocumentRecord.id == ChunkRecord.document_id,
            )
            .join(BookRecord, BookRecord.id == BookDocumentRecord.book_id)
            .join(
                ContentUnitRecord,
                ContentUnitRecord.id == ChunkRecord.content_unit_id,
            )
            .where(
                # Only active, ready documents
                BookDocumentRecord.activated_at.isnot(None),
                BookDocumentRecord.state == "ready",
                # Only retrieval-eligible content
                ContentUnitRecord.retrieval_eligible.is_(True),
                # Match the configured embedding model
                ChunkEmbeddingRecord.model_identifier == self._embedding_service.model_identifier,
                ChunkEmbeddingRecord.model_revision == self._embedding_service.model_revision,
            )
            .order_by(similarity.desc(), ChunkRecord.id)
            .limit(request.top_k)
        )

        # Apply filters
        stmt = self._apply_filters(stmt, request, BookRecord, BookDocumentRecord)

        result = await session.execute(stmt)
        rows = result.all()

        hits: list[SearchHit] = []
        for rank, row in enumerate(rows, start=1):
            evidence = Evidence(
                chunk_id=UUID(str(row.chunk_id)),
                document_id=UUID(str(row.document_id)),
                book_id=UUID(str(row.book_id)),
                book_title=row.book_title,
                edition=row.edition,
                standard=TextbookStandard(row.standard),
                subject=row.subject,
                pdf_page_index=row.pdf_page_index,
                printed_page_label=row.printed_page_label,
                section_path=tuple(row.section_path) if row.section_path else (),
                text=row.display_text,
            )
            hits.append(
                SearchHit(
                    rank=rank,
                    score=float(row.score),
                    evidence=evidence,
                )
            )

        return hits

    def _apply_filters(
        self,
        stmt: Any,
        request: SearchRequest,
        book_record: Any,
        document_record: Any,
    ) -> Any:
        """Apply optional metadata filters to the search query."""
        filters = request.filters

        if filters.standards:
            standards = [int(s) for s in filters.standards]
            stmt = stmt.where(book_record.standard.in_(standards))  # type: ignore[union-attr]

        if filters.subjects:
            # Case-insensitive subject matching
            subject_conditions = [
                func.lower(book_record.subject) == subject.lower()  # type: ignore[union-attr]
                for subject in filters.subjects
            ]
            from sqlalchemy import or_

            stmt = stmt.where(or_(*subject_conditions))  # type: ignore[union-attr]

        if filters.book_ids:
            stmt = stmt.where(book_record.id.in_(filters.book_ids))  # type: ignore[union-attr]

        if filters.document_ids:
            stmt = stmt.where(document_record.id.in_(filters.document_ids))  # type: ignore[union-attr]

        return stmt
