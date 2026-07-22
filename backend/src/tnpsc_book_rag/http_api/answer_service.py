"""Answer orchestration service combining retrieval, context assembly, and generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from tnpsc_rag.models import (
    AnswerRequest,
    EvidencePack,
    GenerationRequest,
    GenerationResult,
    SearchResult,
)

if TYPE_CHECKING:
    from tnpsc_rag.ports import AnswerGenerator, ContextAssembler, Retriever

_LOGGER = structlog.stdlib.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """Complete answer result with evidence and generation."""

    search_result: SearchResult
    evidence_pack: EvidencePack
    generation: GenerationResult


class AnswerOrchestrator:
    """Orchestrate the full answer pipeline: retrieve -> assemble -> generate."""

    def __init__(
        self,
        retriever: Retriever,
        context_assembler: ContextAssembler,
        generator: AnswerGenerator,
    ) -> None:
        self._retriever = retriever
        self._context_assembler = context_assembler
        self._generator = generator

    async def answer(self, request: AnswerRequest) -> AnswerResult:
        """Execute the full answer pipeline."""
        # Step 1: Retrieve evidence
        _LOGGER.info(
            "answer_retrieval_started",
            query_length=len(request.search.query),
            top_k=request.search.top_k,
        )
        search_result = await self._retriever.search(request.search)
        _LOGGER.info(
            "answer_retrieval_completed",
            hit_count=len(search_result.hits),
        )

        # Step 2: Assemble context
        evidence_pack = self._context_assembler.assemble(request, search_result)
        _LOGGER.info(
            "answer_context_assembled",
            evidence_count=len(evidence_pack.items),
            estimated_tokens=evidence_pack.estimated_tokens,
        )

        # Step 3: Generate answer
        generation_request = GenerationRequest(evidence_pack=evidence_pack)
        generation = await self._generator.generate(generation_request)
        _LOGGER.info(
            "answer_generation_completed",
            abstained=generation.abstained,
            citation_count=len(generation.citation_ids),
        )

        return AnswerResult(
            search_result=search_result,
            evidence_pack=evidence_pack,
            generation=generation,
        )
