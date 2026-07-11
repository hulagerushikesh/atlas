"""
Cross-encoder reranker using sentence-transformers.

Design rationale:
    A cross-encoder takes the full (query, document) pair as input and outputs
    a relevance score — far more accurate than bi-encoder cosine similarity
    because it can model query-document interactions (e.g. "not" in the query
    negating a term in the document). The cost is O(n) forward passes per
    query, which is why we only rerank the small fused candidate set (≤20–50
    chunks) rather than the full index.

    We use sentence-transformers' CrossEncoder class, which wraps a BERT-family
    model fine-tuned on MS MARCO passage ranking (the default:
    cross-encoder/ms-marco-MiniLM-L-6-v2). MiniLM gives ~95% of the quality
    of a full BERT-large cross-encoder at ~8× the speed, which is an excellent
    tradeoff for this two-stage architecture.

    asyncio.to_thread() wraps the synchronous PyTorch forward pass so the event
    loop stays unblocked during inference. If you deploy on a GPU instance,
    the thread overhead is negligible compared to GPU utilisation gains.

    Batch prediction: sentence-transformers CrossEncoder.predict() accepts a
    list of (query, text) pairs and runs them as a batch, which is significantly
    faster than calling predict() once per pair when CUDA is available.
"""

from __future__ import annotations

import asyncio

import structlog
from sentence_transformers import CrossEncoder

from atlas.config import RerankerConfig
from atlas.interfaces.reranker import BaseReranker
from atlas.interfaces.retriever import RetrievedChunk

logger = structlog.get_logger(__name__)


class CrossEncoderReranker(BaseReranker):
    """Rerank candidates using a sentence-transformers CrossEncoder."""

    def __init__(self, config: RerankerConfig) -> None:
        self._config = config
        # Load model once at construction time (expensive — ~200ms)
        self._model = CrossEncoder(config.model)
        logger.info("reranker_loaded", model=config.model)

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []

        pairs = [(query, c.content) for c in candidates]
        # Run synchronous batch inference off the event loop
        scores: list[float] = await asyncio.to_thread(
            self._model.predict, pairs  # type: ignore[arg-type]
        )

        ranked = sorted(
            zip(candidates, scores),
            key=lambda x: x[1],
            reverse=True,
        )

        reranked: list[RetrievedChunk] = []
        for chunk, score in ranked[:top_k]:
            updated = chunk.model_copy()
            updated.score = float(score)
            reranked.append(updated)

        logger.debug(
            "reranker_complete",
            candidates=len(candidates),
            top_k=top_k,
            top_score=reranked[0].score if reranked else None,
        )
        return reranked
