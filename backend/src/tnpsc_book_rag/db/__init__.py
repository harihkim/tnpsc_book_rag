"""Database engine, metadata, and lifecycle primitives."""

from tnpsc_book_rag.db.database import (
    Database,
    DatabaseLifecycle,
    DatabaseNotConfiguredError,
    UnsupportedDatabaseDriverError,
    create_database,
    get_database_url,
)
from tnpsc_book_rag.db.metadata import Base, schema_metadata
from tnpsc_book_rag.db.models import (
    EMBEDDING_DIMENSION,
    AssetRecord,
    BookDocumentRecord,
    BookRecord,
    ChunkEmbeddingRecord,
    ChunkPageRecord,
    ChunkRecord,
    IngestionRunRecord,
    PageRecord,
)

__all__ = [
    "EMBEDDING_DIMENSION",
    "AssetRecord",
    "Base",
    "BookDocumentRecord",
    "BookRecord",
    "ChunkEmbeddingRecord",
    "ChunkPageRecord",
    "ChunkRecord",
    "Database",
    "DatabaseLifecycle",
    "DatabaseNotConfiguredError",
    "IngestionRunRecord",
    "PageRecord",
    "UnsupportedDatabaseDriverError",
    "create_database",
    "get_database_url",
    "schema_metadata",
]
