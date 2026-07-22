"""Registered SQLAlchemy records for the package-owned schema."""

from tnpsc_book_rag.database_persistence.models.catalog import BookDocumentRecord, BookRecord
from tnpsc_book_rag.database_persistence.models.content import (
    EMBEDDING_DIMENSION,
    AssetRecord,
    ChunkEmbeddingRecord,
    ChunkPageRecord,
    ChunkRecord,
    ContentUnitPageRecord,
    ContentUnitRecord,
    PageRecord,
)
from tnpsc_book_rag.database_persistence.models.idempotency import IdempotencyRecord
from tnpsc_book_rag.database_persistence.models.ingestion import IngestionRunRecord

__all__ = [
    "EMBEDDING_DIMENSION",
    "AssetRecord",
    "BookDocumentRecord",
    "BookRecord",
    "ChunkEmbeddingRecord",
    "ChunkPageRecord",
    "ChunkRecord",
    "ContentUnitPageRecord",
    "ContentUnitRecord",
    "IdempotencyRecord",
    "IngestionRunRecord",
    "PageRecord",
]
