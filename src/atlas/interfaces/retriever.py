"""
Abstract retriever interface and retrieval result models.

Design rationale:
    Both the dense retriever (Qdrant ANN) and sparse retriever (BM25) satisfy
    the same ABC. Module B's HybridRetriever holds a list[BaseRetriever] and
    invokes them in parallel with asyncio.gather(), then fuses the results.

    RetrievedChunk extends ChunkMetadata with a retriever-assigned score.
    The score semantics differ between dense (cosine similarity ∈ [-1, 1])
    and sparse (BM25 ∈ [0, ∞]), so the hybrid fusion layer normalises before
    combining — see retrieval/fusion.py.

    RetrievalResult bundles the ranked list with provenance about which
    retriever produced it; this feeds the eval harness (Module D) for
    context_precision and context_recall metrics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from atlas.interfaces.document import ChunkMetadata


class RetrievedChunk(BaseModel):
    chunk_id: str
    content: str
    score: float  # raw score from this retriever (not normalised)
    metadata: ChunkMetadata


class RetrievalResult(BaseModel):
    query: str
    chunks: list[RetrievedChunk]
    retriever_name: str


class BaseRetriever(ABC):
    """Retrieve the top-k most relevant chunks for a query."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifier used in provenance metadata and logs."""

    @abstractmethod
    async def retrieve(self, query: str, top_k: int) -> RetrievalResult:
        """Return up to top_k chunks ranked by relevance score (descending)."""
