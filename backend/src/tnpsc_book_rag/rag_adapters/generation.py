"""PydanticAI-based answer generation implementing the tnpsc_rag AnswerGenerator protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field

from tnpsc_rag.models import (
    AnswerMode,
    EvidencePack,
    GenerationRequest,
    GenerationResult,
)

if TYPE_CHECKING:
    pass

_LOGGER = structlog.stdlib.get_logger(__name__)


class TextSegment(BaseModel):
    """A text segment in the generated answer."""

    content: str


class CitationSegment(BaseModel):
    """A citation reference in the generated answer."""

    citation_id: str = Field(pattern=r"^T[1-9][0-9]*$")


class AnswerBlock(BaseModel):
    """A paragraph block with inline text and citation nodes."""

    segments: list[TextSegment | CitationSegment] = Field(default_factory=list)


class StructuredAnswer(BaseModel):
    """Validated structured output from the LLM."""

    answer_text: str = Field(description="The main textbook-based answer text")
    citation_ids: list[str] = Field(
        default_factory=list,
        description="Citation IDs (T1, T2, etc.) referenced in the answer",
    )
    supplementary_text: str | None = Field(
        default=None,
        description="Optional supplementary general knowledge for textbook_plus_general mode",
    )
    abstained: bool = Field(
        default=False,
        description="True if the evidence is insufficient to answer the question",
    )


class PydanticAIGenerator:
    """Generate structured answers using PydanticAI with configurable providers."""

    def __init__(
        self,
        provider: str = "openrouter",
        model: str = "nvidia/nemotron-3-nano-30b-a3b:free",
        fallback_model: str = "nvidia/nemotron-nano-9b-v2:free",
        *,
        openrouter_api_key: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self._provider = provider
        self._model = model
        self._fallback_model = fallback_model
        self._openrouter_api_key = openrouter_api_key
        self._timeout_seconds = timeout_seconds
        self._agent: object | None = None

    def _build_agent(self) -> object:
        """Build the PydanticAI agent with fallback model support."""
        if self._agent is None:
            from pydantic_ai import Agent
            from pydantic_ai.models.fallback import FallbackModel
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openrouter import OpenRouterProvider

            # Build model based on provider
            if self._provider == "openrouter":
                provider = OpenRouterProvider(
                    api_key=self._openrouter_api_key or "sk-or-v1-dummy",
                )
                primary = OpenAIChatModel(self._model, provider=provider)
                fallback = OpenAIChatModel(self._fallback_model, provider=provider)
                model = FallbackModel(primary, fallback)
            else:
                # Default to openrouter
                provider = OpenRouterProvider(
                    api_key=self._openrouter_api_key or "sk-or-v1-dummy",
                )
                model = OpenAIChatModel(self._model, provider=provider)

            self._agent = Agent(
                model,  # type: ignore[arg-type]
                output_type=StructuredAnswer,
                system_prompt=self._build_system_prompt(),
                retries=2,
            )
            _LOGGER.info(
                "pydantic_ai_agent_created",
                provider=self._provider,
                model=self._model,
            )
        return self._agent

    def _build_system_prompt(self) -> str:
        """Build the system prompt for answer generation."""
        return (
            "You are an educational assistant helping students understand "
            "Tamil Nadu State Board textbook content.\n\n"
            "Your task is to answer questions using ONLY the provided textbook evidence. "
            "Follow these rules:\n\n"
            "1. Base your answer strictly on the provided evidence passages.\n"
            "2. Reference citations using their IDs (T1, T2, etc.) when using information.\n"
            "3. If evidence is insufficient, set abstained=true with a brief explanation.\n"
            "4. Write clear, educational explanations appropriate for school students.\n"
            "5. Do not invent facts not present in the evidence.\n"
            "6. For textbook_plus_general mode, you may add supplementary general knowledge.\n\n"
            "Format your answer as valid JSON matching the StructuredAnswer schema."
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate a structured answer from the evidence pack."""
        evidence_pack = request.evidence_pack

        if not evidence_pack.items:
            return GenerationResult(
                answer=(
                    "I don't have enough textbook evidence to answer this question. "
                    "Please try rephrasing your question or searching for related topics."
                ),
                citation_ids=(),
                supplementary_explanation=None,
                abstained=True,
            )

        agent = self._build_agent()
        user_prompt = self._build_user_prompt(evidence_pack)

        try:
            # Run the agent
            result = await agent.run(user_prompt)  # type: ignore[union-attr]
            answer: StructuredAnswer = result.output  # type: ignore[assignment]

            # Validate citation IDs against available evidence
            valid_citation_ids = {item.citation_id for item in evidence_pack.items}
            filtered_citations = tuple(
                cid for cid in answer.citation_ids if cid in valid_citation_ids
            )

            return GenerationResult(
                answer=answer.answer_text,
                citation_ids=filtered_citations,
                supplementary_explanation=answer.supplementary_text,
                abstained=answer.abstained,
            )
        except Exception as error:
            _LOGGER.error(
                "generation_failed",
                error_type=f"{type(error).__module__}.{type(error).__qualname__}",
            )
            # Return a graceful failure
            return GenerationResult(
                answer="I'm unable to generate an answer right now. Please try again later.",
                citation_ids=(),
                supplementary_explanation=None,
                abstained=True,
            )

    def _build_user_prompt(self, evidence_pack: EvidencePack) -> str:
        """Build the user prompt with evidence context."""
        mode_instruction = (
            "Answer using ONLY the textbook evidence below."
            if evidence_pack.mode == AnswerMode.TEXTBOOK_ONLY
            else (
                "Answer using the textbook evidence below. "
                "You may add supplementary general knowledge if helpful."
            )
        )

        evidence_sections = []
        for item in evidence_pack.items:
            ev = item.evidence
            section_path = " > ".join(ev.section_path) if ev.section_path else "General"
            evidence_sections.append(
                f"[{item.citation_id}] {ev.book_title} (Standard {ev.standard}, {ev.subject})\n"
                f"Section: {section_path}\n"
                f"Page: {ev.printed_page_label or f'PDF page {ev.pdf_page_index + 1}'}\n"
                f"Content: {ev.text}"
            )

        evidence_text = "\n\n---\n\n".join(evidence_sections)

        return f"""Question: {evidence_pack.query}

{mode_instruction}

Available Evidence:

{evidence_text}

Provide your answer as JSON with:
- answer_text: Your explanation based on the evidence
- citation_ids: List of citation IDs you referenced (e.g., ["T1", "T2"])
- supplementary_text: Optional general knowledge (null for textbook_only mode)
- abstained: false if you can answer, true if evidence is insufficient"""
