"""Infrastructure adapters implementing tnpsc_rag protocols."""

from tnpsc_book_rag.rag_adapters.context import EvidenceContextAssembler
from tnpsc_book_rag.rag_adapters.embeddings import EmbeddingService
from tnpsc_book_rag.rag_adapters.generation import PydanticAIGenerator
from tnpsc_book_rag.rag_adapters.retrieval import PgVectorRetriever

__all__ = [
    "EmbeddingService",
    "EvidenceContextAssembler",
    "PgVectorRetriever",
    "PydanticAIGenerator",
]
