"""
Abstract reranker interface.

Design rationale:
    The reranker sits after hybrid fusion and operates on the fused candidate
    set. It re-scores every (query, chunk) pair with a cross-encoder, which is
    far more accurate than bi-encoder similarity but too slow to run over the
    full index — hence the two-stage architecture: fast ANN retrieval narrows
    the candidate pool, then the cross-encoder reranks a small set (20–50).

    Returning RetrievedChunk (same model as retriever output) means callers
    don't need to unwrap a different type after reranking.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from atlas.interfaces.retriever import RetrievedChunk


class BaseReranker(ABC):
    """Rerank a list of candidate chunks given a query."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """
        Return the top_k most relevant chunks, re-scored by the cross-encoder.
        Output list is sorted by score descending.
        """
