"""
A reranker that does not import torch until something needs to rerank.

Why this exists:
    A Cloud Run cold start measured 36.9 s on 2026-10-21, and 12.41 s of it
    is the import graph — measured inside the container with the image
    already local, so it is import cost with no pull in it at all. Nearly all
    of that is `atlas.retrieval.reranker` pulling in torch, transformers and
    sentence-transformers, and it ran before uvicorn had bound the port,
    because `atlas.api.namespaces` imported `CrossEncoderReranker` at module
    scope. Every visitor arriving during those twelve seconds waited for a
    model that only `/query` uses — the landing page and the console need
    nothing from it.

    This wrapper moves that cost off the startup path. The port binds, the
    static pages serve, and the model loads behind them. `warm()` starts that
    load from the lifespan so it is usually finished before the first query
    rather than charged to it.

What it deliberately does not do:
    Fall back to no reranking when the model is not ready. Returning the
    fused order instead would answer the query with measurably worse
    retrieval and no sign that anything was different — the same shape as a
    reranker quietly migrating to CPU mid-run, which this codebase already
    rejected once in `reranker.py`. A query that arrives early waits for the
    load and is slow; it is never silently answered at lower quality.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from atlas.config import RerankerConfig
from atlas.interfaces.reranker import BaseReranker
from atlas.interfaces.retriever import RetrievedChunk

logger = structlog.get_logger(__name__)


class LazyCrossEncoderReranker(BaseReranker):
    """`CrossEncoderReranker`, constructed on first use instead of at import."""

    def __init__(self, config: RerankerConfig) -> None:
        self._config = config
        self._delegate: BaseReranker | None = None
        # Guards the build, so a burst of concurrent first queries loads one
        # model rather than one each. The double check around it is what
        # makes the common path — already loaded — lock-free.
        self._lock = asyncio.Lock()

    def _build(self) -> BaseReranker:
        # Imported here and nowhere else: this function body is the whole
        # point of the module.
        from atlas.retrieval.reranker import CrossEncoderReranker

        return CrossEncoderReranker(self._config)

    async def _ensure(self) -> BaseReranker:
        if self._delegate is not None:
            return self._delegate
        async with self._lock:
            if self._delegate is None:
                started = time.monotonic()
                # to_thread because importing torch and loading the weights
                # are both synchronous and slow, and the event loop is
                # serving the pages this class exists to unblock.
                self._delegate = await asyncio.to_thread(self._build)
                logger.info(
                    "reranker_loaded_lazily",
                    seconds=round(time.monotonic() - started, 2),
                    model=self._config.model,
                )
        return self._delegate

    @property
    def is_loaded(self) -> bool:
        """Whether a query would be served without waiting for the model."""
        return self._delegate is not None

    async def warm(self) -> None:
        """Load the model now, off the request path.

        Failures are logged and swallowed: this runs as a background task
        from the lifespan, and a reranker that cannot load must not take the
        API down with it when every page except `/query` is fine without it.
        The next `rerank` retries and raises to its caller, which is where
        the failure belongs.
        """
        try:
            await self._ensure()
        except Exception as exc:
            logger.warning(
                "reranker_warm_failed",
                error=str(exc),
                detail="the first query will retry and surface this",
            )

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        delegate = await self._ensure()
        return await delegate.rerank(query, candidates, top_k)
