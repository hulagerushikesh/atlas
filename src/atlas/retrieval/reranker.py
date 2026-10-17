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

    Batch size is ours, not the library's default of 32. Peak memory is that
    number times the sequence length, and the sequence length is set by the
    caller: HyDE in `concat` mode puts a hypothesis of up to 220 tokens in
    front of every query, so every pair in the batch grows at once. On
    2026-10-17 that combination died with "MPS backend out of memory" on two
    samples of a 16-sample eval, on a machine where the same reranker had
    just finished the baseline run — unified memory, and a browser had the
    rest of it. The eval recorded both samples at the failure sentinel,
    dropped them from every mean, and printed "16 samples".

    So the failure is handled in two places and neither of them is silence.
    A smaller batch makes it rarer. An out-of-memory error that happens
    anyway falls back to CPU for that call and says so at WARNING, because a
    slow correct score beats a dead sample — and because the alternative,
    discovering it in the aggregate afterwards, is what happened once
    already. The fallback is per call and the model stays where it was: a
    reranker that quietly migrated to CPU mid-run would make every later
    sample's latency a different measurement under the same name.
    """

from __future__ import annotations

import asyncio
from typing import Any, cast

import structlog
import torch
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
        self._model = CrossEncoder(config.model, device=config.device)
        # Built on the first out-of-memory and kept, so a run that hits the
        # fallback repeatedly pays the ~200ms model load once.
        self._cpu_model: CrossEncoder | None = None
        logger.info(
            "reranker_loaded",
            model=config.model,
            device=config.device or "auto",
            batch_size=config.batch_size,
        )

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
        scores: list[float] = await asyncio.to_thread(self._predict, pairs)

        ranked = sorted(
            # strict: the cross-encoder returns one score per pair; a mismatch
            # would silently attach the wrong score to a candidate.
            zip(candidates, scores, strict=True),
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

    def _predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Score *pairs*, retrying on CPU if the accelerator runs out of memory.

        Catching RuntimeError rather than a typed exception is deliberate:
        torch raises a plain RuntimeError for an MPS out-of-memory, and the
        only thing distinguishing it from any other backend failure is the
        message. So the message is matched, and anything else is re-raised
        untouched — swallowing an unrecognised RuntimeError here would turn a
        broken reranker into a silently unranked result set, which is the
        failure this whole class exists to prevent.
        """
        try:
            return list(
                self._model.predict(pairs, batch_size=self._config.batch_size)
            )
        except RuntimeError as exc:
            if "out of memory" not in str(exc).lower():
                raise
            logger.warning(
                "reranker_oom_cpu_fallback",
                pairs=len(pairs),
                batch_size=self._config.batch_size,
                error=str(exc),
            )
            if self._cpu_model is None:
                self._cpu_model = CrossEncoder(self._config.model, device="cpu")
            with torch.no_grad():
                # cast: the stub types `predict` over every modality
                # sentence-transformers supports, and a list of (query, text)
                # pairs is not spelled in that union. The line above takes the
                # same argument and type-checks only because the constructor
                # there is inferred as Any.
                return list(
                    self._cpu_model.predict(
                        cast(Any, pairs), batch_size=self._config.batch_size
                    )
                )
