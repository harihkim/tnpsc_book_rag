"""Domain-specific, provider-neutral RAG contracts for TNPSC textbooks."""

from tnpsc_rag.models import (
    AnswerMode,
    AnswerRequest,
    Evidence,
    EvidenceInclusionReason,
    EvidenceItem,
    EvidencePack,
    GenerationRequest,
    GenerationResult,
    SearchFilters,
    SearchHit,
    SearchRequest,
    SearchResult,
    TextbookStandard,
)
from tnpsc_rag.ports import AnswerGenerator, ContextAssembler, Retriever

__all__ = [
    "AnswerGenerator",
    "AnswerMode",
    "AnswerRequest",
    "ContextAssembler",
    "Evidence",
    "EvidenceInclusionReason",
    "EvidenceItem",
    "EvidencePack",
    "GenerationRequest",
    "GenerationResult",
    "Retriever",
    "SearchFilters",
    "SearchHit",
    "SearchRequest",
    "SearchResult",
    "TextbookStandard",
]
