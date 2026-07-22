"""Catalog domain types and lifecycle policy."""

from tnpsc_book_rag.textbook_catalog.entities import Book, BookDocument, NewBook, NewBookDocument
from tnpsc_book_rag.textbook_catalog.lifecycle import (
    InvalidDocumentStateTransition,
    can_transition_document,
    require_document_transition,
)
from tnpsc_book_rag.textbook_catalog.models import (
    AssetType,
    ChunkContentType,
    DocumentLanguage,
    DocumentState,
)
from tnpsc_book_rag.textbook_catalog.ports import CatalogRepository

__all__ = [
    "AssetType",
    "Book",
    "BookDocument",
    "CatalogRepository",
    "ChunkContentType",
    "DocumentLanguage",
    "DocumentState",
    "InvalidDocumentStateTransition",
    "NewBook",
    "NewBookDocument",
    "can_transition_document",
    "require_document_transition",
]
