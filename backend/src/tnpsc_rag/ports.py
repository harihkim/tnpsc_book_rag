"""Dependency-inversion protocols implemented by backend infrastructure."""

from typing import Protocol, runtime_checkable

from tnpsc_rag.models import (
    AnswerRequest,
    EvidencePack,
    GenerationRequest,
    GenerationResult,
    SearchRequest,
    SearchResult,
)


@runtime_checkable
class Retriever(Protocol):
    """Return ranked textbook evidence without generating prose."""

    async def search(self, request: SearchRequest) -> SearchResult:
        """Search the active textbook corpus."""
        ...


@runtime_checkable
class ContextAssembler(Protocol):
    """Convert retrieval candidates into bounded, citable evidence."""

    def assemble(self, request: AnswerRequest, result: SearchResult) -> EvidencePack:
        """Build deterministic generation context."""
        ...


@runtime_checkable
class AnswerGenerator(Protocol):
    """Generate a structured answer from an already assembled evidence pack."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate without performing retrieval itself."""
        ...
