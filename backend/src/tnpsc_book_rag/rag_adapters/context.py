"""Deterministic context assembly implementing the tnpsc_rag ContextAssembler protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from tnpsc_rag.models import (
    AnswerRequest,
    EvidenceInclusionReason,
    EvidenceItem,
    EvidencePack,
    SearchHit,
    SearchResult,
)

if TYPE_CHECKING:
    pass

_LOGGER = structlog.stdlib.get_logger(__name__)

# Approximate tokens per character ratio for English text
_CHARS_PER_TOKEN = 4


class EvidenceContextAssembler:
    """Convert retrieval candidates into bounded, citable evidence for generation."""

    def __init__(self, token_budget: int = 3000) -> None:
        self._token_budget = token_budget

    def assemble(self, request: AnswerRequest, result: SearchResult) -> EvidencePack:
        """Build deterministic generation context from search results."""
        if not result.hits:
            return EvidencePack(
                query=request.search.query,
                mode=request.mode,
                items=(),
                estimated_tokens=0,
            )

        # Select evidence within token budget
        selected_items: list[EvidenceItem] = []
        used_chunk_ids: set[Any] = set()
        estimated_tokens = 0
        citation_counter = 0

        for hit in result.hits:
            # Skip duplicates
            if hit.evidence.chunk_id in used_chunk_ids:
                continue

            # Estimate tokens for this evidence
            item_tokens = self._estimate_tokens(hit)

            # Check if we'd exceed the budget
            if estimated_tokens + item_tokens > self._token_budget:
                # Try to fit at least some evidence
                if not selected_items:
                    # Always include at least the top hit
                    citation_counter += 1
                    selected_items.append(
                        EvidenceItem(
                            citation_id=f"T{citation_counter}",
                            evidence=hit.evidence,
                            inclusion_reason=EvidenceInclusionReason.SEMANTIC_MATCH,
                        )
                    )
                    used_chunk_ids.add(hit.evidence.chunk_id)
                    estimated_tokens += item_tokens
                break

            citation_counter += 1
            selected_items.append(
                EvidenceItem(
                    citation_id=f"T{citation_counter}",
                    evidence=hit.evidence,
                    inclusion_reason=EvidenceInclusionReason.SEMANTIC_MATCH,
                )
            )
            used_chunk_ids.add(hit.evidence.chunk_id)
            estimated_tokens += item_tokens

        return EvidencePack(
            query=request.search.query,
            mode=request.mode,
            items=tuple(selected_items),
            estimated_tokens=estimated_tokens,
        )

    def _estimate_tokens(self, hit: SearchHit) -> int:
        """Estimate token count for an evidence item."""
        text_length = len(hit.evidence.text)
        # Add overhead for section path and metadata
        metadata_length = sum(len(s) for s in hit.evidence.section_path) + 50
        return (text_length + metadata_length) // _CHARS_PER_TOKEN + 1
