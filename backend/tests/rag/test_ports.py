"""Tests for infrastructure-independent RAG ports."""

import pytest

from tnpsc_rag import (
    AnswerGenerator,
    AnswerMode,
    AnswerRequest,
    ContextAssembler,
    EvidencePack,
    GenerationRequest,
    GenerationResult,
    Retriever,
    SearchRequest,
    SearchResult,
)


class StubRetriever:
    """Minimal in-memory retrieval adapter used by contract tests."""

    async def search(self, request: SearchRequest) -> SearchResult:
        """Return an empty but valid result set."""
        return SearchResult(request=request)


class StubContextAssembler:
    """Minimal deterministic context adapter used by contract tests."""

    def assemble(self, request: AnswerRequest, result: SearchResult) -> EvidencePack:
        """Build an empty context while preserving query and answer mode."""
        assert result.request == request.search
        return EvidencePack(query=request.search.query, mode=request.mode)


class StubAnswerGenerator:
    """Minimal generation adapter used by contract tests."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Return deterministic abstention without making a model request."""
        assert request.evidence_pack.items == ()
        return GenerationResult(answer="The textbook evidence is insufficient.", abstained=True)


@pytest.mark.anyio
async def test_protocol_adapters_compose_without_framework_dependencies() -> None:
    """Structurally typed adapters support the future RAG workflow."""
    retriever = StubRetriever()
    assembler = StubContextAssembler()
    generator = StubAnswerGenerator()

    assert isinstance(retriever, Retriever)
    assert isinstance(assembler, ContextAssembler)
    assert isinstance(generator, AnswerGenerator)

    search_request = SearchRequest(query="unknown topic")
    answer_request = AnswerRequest(
        search=search_request,
        mode=AnswerMode.TEXTBOOK_ONLY,
    )
    search_result = await retriever.search(search_request)
    evidence_pack = assembler.assemble(answer_request, search_result)
    generation_result = await generator.generate(GenerationRequest(evidence_pack=evidence_pack))

    assert search_result.hits == ()
    assert generation_result.abstained is True
