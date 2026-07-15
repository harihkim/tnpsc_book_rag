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

__all__ = [
    "Base",
    "Database",
    "DatabaseLifecycle",
    "DatabaseNotConfiguredError",
    "UnsupportedDatabaseDriverError",
    "create_database",
    "get_database_url",
    "schema_metadata",
]
