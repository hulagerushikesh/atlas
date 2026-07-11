"""
Abstract embedder interface.

Design rationale:
    Embedding is called in two hot paths: indexing (batch) and query-time
    (single). The ABC exposes both separately so implementations can
    optimise batch calls (e.g. openai allows up to 2048 inputs per request)
    without the caller needing to know about batching logic.

    EmbeddingResult carries the model name and token count so Module E can
    track per-request embedding cost alongside generation cost.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class EmbeddingResult(BaseModel):
    vectors: list[list[float]]
    model: str
    total_tokens: int


class BaseEmbedder(ABC):
    """Convert text into dense vectors."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Dimensionality of output vectors."""

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        """Embed a batch of texts. Implementations should handle rate-limiting internally."""

    async def embed_query(self, query: str) -> list[float]:
        """Convenience wrapper for single-query embedding at retrieval time."""
        result = await self.embed_texts([query])
        return result.vectors[0]
