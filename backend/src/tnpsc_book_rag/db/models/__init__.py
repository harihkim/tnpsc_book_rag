"""Registered SQLAlchemy records for the package-owned schema."""

from tnpsc_book_rag.db.models.catalog import BookDocumentRecord, BookRecord
from tnpsc_book_rag.db.models.content import (
    EMBEDDING_DIMENSION,
    AssetRecord,
    ChunkEmbeddingRecord,
    ChunkPageRecord,
    ChunkRecord,
    PageRecord,
)
from tnpsc_book_rag.db.models.ingestion import IngestionRunRecord

__all__ = [
    "EMBEDDING_DIMENSION",
    "AssetRecord",
    "BookDocumentRecord",
    "BookRecord",
    "ChunkEmbeddingRecord",
    "ChunkPageRecord",
    "ChunkRecord",
    "IngestionRunRecord",
    "PageRecord",
]
