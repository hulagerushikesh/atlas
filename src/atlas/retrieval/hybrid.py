"""
HybridRetriever: the public entry point for Module B.

Design rationale:
    Orchestrates the three-stage pipeline:
      1. Retrieve from all registered retrievers concurrently (asyncio.gather).
      2. Fuse via RRF into a single ranked list.
      3. Rerank the fused list with the cross-encoder.

    Concurrency in step 1 is the key latency win: dense ANN (~10ms) and BM25
    scoring (~5ms) overlap rather than running sequentially, shaving ~30–50%
    off total retrieval latency at negligible complexity cost.

    The reranker is optional (pass reranker=None) so Module D's eval harness
    can run A/B tests comparing "retrieval only" vs "retrieval + rerank" by
    toggling a single constructor argument.

    HybridRetrievalResult extends the base interface with per-retriever
    provenance so the eval harness can compute retriever-specific metrics
    (e.g. "what fraction of relevant chunks did dense-only find vs BM25-only?").
"""

from __future__ import annotations

import asyncio

import structlog

from atlas.config import RetrievalConfig
from atlas.interfaces.retriever import BaseRetriever, RetrievalResult, RetrievedChunk
from atlas.interfaces.reranker import BaseReranker
from atlas.retrieval.fusion import reciprocal_rank_fusion

logger = structlog.get_logger(__name__)


class HybridRetrievalResult:
    """Full provenance for one hybrid retrieval call."""

    def __init__(
        self,
        query: str,
        per_retriever: list[RetrievalResult],
        fused: list[RetrievedChunk],
        reranked: list[RetrievedChunk],
    ) -> None:
        self.query = query
        self.per_retriever = per_retriever   # raw results from each retriever
        self.fused = fused                   # after RRF, before reranking
        self.reranked = reranked             # final output (or fused if no reranker)

    @property
    def chunks(self) -> list[RetrievedChunk]:
        """Convenience accessor — the final ranked list for callers."""
        return self.reranked


class HybridRetriever:
    """Dense + sparse retrieval, RRF fusion, cross-encoder reranking."""

    def __init__(
        self,
        retrievers: list[BaseRetriever],
        config: RetrievalConfig,
        reranker: BaseReranker | None = None,
        reranker_top_k: int = 5,
    ) -> None:
        if not retrievers:
            raise ValueError("HybridRetriever requires at least one retriever")
        self._retrievers = retrievers
        self._config = config
        self._reranker = reranker
        self._reranker_top_k = reranker_top_k

    async def retrieve(self, query: str) -> HybridRetrievalResult:
        # Stage 1: fan out to all retrievers concurrently
        per_retriever: list[RetrievalResult] = await asyncio.gather(
            *[r.retrieve(query, self._config.top_k) for r in self._retrievers]
        )

        # Stage 2: RRF fusion
        # After fusion we still pass top_k candidates to the reranker so it has
        # enough material to work with; the reranker then cuts to reranker_top_k.
        fused = reciprocal_rank_fusion(
            results=list(per_retriever),
            top_k=self._config.top_k,
        )

        # Stage 3: optional cross-encoder reranking
        if self._reranker is not None and fused:
            reranked = await self._reranker.rerank(query, fused, self._reranker_top_k)
        else:
            reranked = fused[: self._reranker_top_k]

        logger.info(
            "hybrid_retrieve_complete",
            query=query[:60],
            per_retriever_counts={r.retriever_name: len(r.chunks) for r in per_retriever},
            fused=len(fused),
            reranked=len(reranked),
        )

        return HybridRetrievalResult(
            query=query,
            per_retriever=list(per_retriever),
            fused=fused,
            reranked=reranked,
        )
