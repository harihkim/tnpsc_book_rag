"""Local embedding generation using BGE-small-en-v1.5."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Sequence

_LOGGER = structlog.stdlib.get_logger(__name__)

EMBEDDING_DIMENSION = 384


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    """One batch of generated embeddings with model provenance."""

    model_identifier: str
    model_revision: str
    dimension: int
    vectors: list[list[float]]
    content_checksums: list[str]


class EmbeddingService:
    """Generate normalized embeddings locally using sentence-transformers."""

    def __init__(
        self,
        model_identifier: str = "BAAI/bge-small-en-v1.5",
        model_revision: str = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
        *,
        device: str = "auto",
        batch_size: int = 32,
    ) -> None:
        self._model_identifier = model_identifier
        self._model_revision = model_revision
        self._device = device
        self._batch_size = batch_size
        self._model: Any = None

    @property
    def model_identifier(self) -> str:
        return self._model_identifier

    @property
    def model_revision(self) -> str:
        return self._model_revision

    def _load_model(self) -> Any:
        """Lazy-load the sentence-transformer model."""
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            device = self._device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"

            _LOGGER.info(
                "embedding_model_loading",
                model=self._model_identifier,
                revision=self._model_revision,
                device=device,
            )
            self._model = SentenceTransformer(
                self._model_identifier,
                revision=self._model_revision,
                device=device,
            )
            _LOGGER.info("embedding_model_loaded", device=device)
        return self._model

    def embed_texts(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Generate normalized embeddings for a batch of texts."""
        if not texts:
            return EmbeddingBatch(
                model_identifier=self._model_identifier,
                model_revision=self._model_revision,
                dimension=EMBEDDING_DIMENSION,
                vectors=[],
                content_checksums=[],
            )

        model = self._load_model()
        # sentence-transformers encode returns numpy arrays
        vectors = model.encode(  # type: ignore[union-attr]
            list(texts),
            batch_size=self._batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )

        checksums = [hashlib.sha256(text.encode()).hexdigest() for text in texts]

        return EmbeddingBatch(
            model_identifier=self._model_identifier,
            model_revision=self._model_revision,
            dimension=EMBEDDING_DIMENSION,
            vectors=[vec.tolist() for vec in vectors],
            content_checksums=checksums,
        )

    def embed_query(self, query: str) -> list[float]:
        """Generate a normalized embedding for a single query."""
        batch = self.embed_texts([query])
        return batch.vectors[0]
