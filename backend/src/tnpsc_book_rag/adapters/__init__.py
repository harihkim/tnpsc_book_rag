"""Infrastructure adapters implementing tnpsc_rag protocols."""

from tnpsc_book_rag.adapters.context import EvidenceContextAssembler
from tnpsc_book_rag.adapters.embeddings import EmbeddingService
from tnpsc_book_rag.adapters.generation import PydanticAIGenerator
from tnpsc_book_rag.adapters.retrieval import PgVectorRetriever

__all__ = [
    "EmbeddingService",
    "EvidenceContextAssembler",
    "PgVectorRetriever",
    "PydanticAIGenerator",
]
