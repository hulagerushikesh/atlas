"""
Namespace registry — per-corpus pipeline and indexer construction.

Design rationale:
    A namespace maps to a Qdrant collection (atlas_{namespace}). Components
    that are stateless across corpora (LLM, embedder, reranker, Qdrant
    connection) are constructed once and shared. Components that are corpus-
    specific (BM25 sparse index, hybrid retriever, pipeline, document
    indexer) are built lazily on first access and cached for the process
    lifetime.

    This means the first query to a new namespace pays a one-time build cost
    (~50ms); subsequent requests are zero-overhead. No background thread or
    warm-up is needed — the registry is thread-safe for async use because
    all construction is synchronous (no awaits), and the asyncio event loop
    is single-threaded.

    Collection naming: atlas_{namespace}. "default" → atlas_default.
    The QDRANT_COLLECTION_NAME env var is ignored in namespace mode; the
    namespace string is always the source of truth.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from qdrant_client import AsyncQdrantClient

from atlas.config import Settings
from atlas.ingestion.chunkers import get_chunker
from atlas.ingestion.dense import QdrantDenseIndex
from atlas.ingestion.embedder import OpenAIEmbedder
from atlas.ingestion.indexer import DocumentIndexer
from atlas.ingestion.sparse import BM25SparseIndex, corpus_entry
from atlas.orchestration.decomposer import QueryDecomposer
from atlas.orchestration.faithfulness import FaithfulnessChecker
from atlas.orchestration.generator import AnswerGenerator
from atlas.orchestration.grader import RetrievalGrader
from atlas.orchestration.hyde import HyDEExpander
from atlas.orchestration.llm import OpenAILLMProvider
from atlas.orchestration.pipeline import RAGPipeline
from atlas.orchestration.router import QueryRouter
from atlas.retrieval.dense import QdrantDenseRetriever
from atlas.retrieval.hybrid import HybridRetriever
from atlas.retrieval.lazy import LazyCrossEncoderReranker
from atlas.retrieval.sparse import BM25Retriever

logger = structlog.get_logger(__name__)

_COLLECTION_PREFIX = "atlas_"

# Points per scroll page when rebuilding a sparse index from Qdrant. The same
# figure the dense index uses for its own filtered scroll.
_SCROLL_PAGE = 256

# "No count was read" -- distinct from None, which the count itself uses to
# mean "Qdrant could not be reached". A caller that has already paid for the
# number passes it in; one that has not leaves it unset and the reconciler
# fetches it, or skips the check entirely while its last one is still fresh.
_UNREAD: Any = object()


@dataclass(frozen=True)
class SparseSync:
    """What a reconcile did, for the caller that wants to log or assert it."""

    checked: bool          # a dense count was consulted
    rebuilt: bool          # the sparse corpus was replaced from Qdrant
    sparse_chunks: int     # rows held after this call
    dense_chunks: int | None   # points in Qdrant, None when unreachable


def namespace_to_collection(namespace: str) -> str:
    """Map a namespace string to a Qdrant collection name."""
    return f"{_COLLECTION_PREFIX}{namespace}"


def sparse_index_path(namespace: str) -> Path:
    """
    Per-namespace BM25 persistence file. One shared file would leak chunks
    across tenants (found on the first live run). ATLAS_INDEX_DIR overrides
    the root, e.g. a mounted volume in production.
    """
    root = Path(os.environ.get("ATLAS_INDEX_DIR", "data/index"))
    return root / namespace / "bm25_index.json"


def collection_to_namespace(collection: str) -> str | None:
    """Reverse mapping — returns None if not an Atlas-managed collection."""
    if collection.startswith(_COLLECTION_PREFIX):
        return collection[len(_COLLECTION_PREFIX):]
    return None


class SharedComponents:
    """Stateless components shared across all namespaces."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embedder = OpenAIEmbedder(settings.openai)
        self.llm = OpenAILLMProvider(settings.openai)
        # Lazy: constructing this must not import torch, because that import
        # is 12.41 s of a 36.9 s cold start and it ran before uvicorn bound
        # the port. The model loads behind the server via `warm()`.
        self.reranker = (
            LazyCrossEncoderReranker(settings.reranker) if settings.reranker.enabled else None
        )
        api_key = settings.qdrant.api_key.get_secret_value() if settings.qdrant.api_key else None
        self.qdrant_client = AsyncQdrantClient(
            url=settings.qdrant.url,
            api_key=api_key,
            timeout=settings.qdrant.timeout_seconds,
        )


class NamespaceComponents:
    """Per-namespace pipeline and indexer."""

    def __init__(
        self,
        pipeline: RAGPipeline,
        indexer: DocumentIndexer,
        sparse_index: BM25SparseIndex | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.indexer = indexer
        # Kept so the API can inventory a namespace without a Qdrant scroll.
        self.sparse_index = sparse_index
        # When this process last compared its sparse half against Qdrant,
        # on the monotonic clock -- None means never. Wall time would make a
        # TTL expire early or late whenever the host adjusts the clock.
        self.synced_at: float | None = None
        # One reconcile at a time per namespace. Two concurrent first
        # requests would otherwise each scroll the whole collection and the
        # second would overwrite the first with the same rows.
        self.sync_lock = asyncio.Lock()


class NamespaceRegistry:
    """
    Lazy per-namespace component cache.

    Call get(namespace) to retrieve (or build) the pipeline and indexer for
    a given corpus. List available namespaces via list_namespaces().
    """

    def __init__(self, shared: SharedComponents) -> None:
        self._shared = shared
        self._cache: dict[str, NamespaceComponents] = {}

    @property
    def settings(self) -> Settings:
        """
        The settings every namespace is built from.

        Routes that need to answer a question *about* a namespace rather than
        query it -- is this corpus described, and therefore not writable --
        read it from here, so the answer and the pipeline that enforces it
        come from the same object.
        """
        return self._shared.settings

    def get(self, namespace: str) -> NamespaceComponents:
        """Return cached components, building them on first access."""
        if namespace not in self._cache:
            self._cache[namespace] = self._build(namespace)
            logger.info("namespace_created", namespace=namespace,
                        collection=namespace_to_collection(namespace))
        return self._cache[namespace]

    def _build(self, namespace: str) -> NamespaceComponents:
        s = self._shared
        cfg = s.settings
        collection = namespace_to_collection(namespace)

        # Override collection name for this namespace
        qdrant_cfg = cfg.qdrant.model_copy(update={"collection_name": collection})

        # The router's domain sentence belongs to one corpus, not to the
        # process. Resolving it per namespace is what stops a corpus uploaded
        # from the console being refused for not being the corpus ROUTER_DOMAIN
        # happens to describe.
        router_cfg = cfg.router.model_copy(
            update={"domain": cfg.router.domain_for(namespace)}
        )

        sparse = BM25SparseIndex(persist_path=sparse_index_path(namespace))

        hybrid = HybridRetriever(
            retrievers=[
                QdrantDenseRetriever(qdrant_cfg, s.embedder),
                BM25Retriever(sparse),
            ],
            config=cfg.retrieval,
            reranker=s.reranker,
            reranker_top_k=cfg.reranker.top_k,
        )

        pipeline = RAGPipeline(
            retriever=hybrid,
            router=QueryRouter(s.llm, router_cfg),
            decomposer=QueryDecomposer(s.llm),
            grader=RetrievalGrader(s.llm, cfg.grader),
            generator=AnswerGenerator(s.llm),
            faithfulness=FaithfulnessChecker(s.llm),
            reranker=s.reranker,
            hyde=HyDEExpander(s.llm, cfg.hyde) if cfg.hyde.enabled else None,
        )

        indexer = DocumentIndexer(
            chunker=get_chunker(cfg, embedder=s.embedder),
            embedder=s.embedder,
            dense_index=QdrantDenseIndex(qdrant_cfg, s.embedder.dimensions),
            sparse_index=sparse,
            context_headers=cfg.chunking.context_headers,
        )

        return NamespaceComponents(pipeline=pipeline, indexer=indexer, sparse_index=sparse)

    async def dense_chunk_count(self, namespace: str) -> int | None:
        """
        Points in this namespace's Qdrant collection.

        0 means the collection is absent — a real disagreement when the sparse
        side has rows. None means Qdrant could not be reached, which is not the
        same thing and must not be reported as zero: a count whose own failure
        is silenced reports whatever the caller expected.
        """
        collection = namespace_to_collection(namespace)
        client = self._shared.qdrant_client
        try:
            if not await client.collection_exists(collection):
                return 0
            info = await client.get_collection(collection)
            return info.points_count or 0
        except Exception as exc:  # noqa: BLE001 — any failure means "unknown"
            logger.warning("dense_chunk_count_failed", namespace=namespace, error=str(exc))
            return None

    async def reconcile_sparse(
        self, namespace: str, dense_chunks: Any = _UNREAD
    ) -> SparseSync:
        """
        Make this process's keyword index agree with the vector store.

        The two halves of a namespace do not live together. The dense half is
        in Qdrant, which every instance shares; the sparse half is a JSON file
        on the instance's own filesystem, which Cloud Run throws away when it
        recycles the container. With more than one instance that made an
        upload a coin flip: it landed on whichever container served the
        request, and whether a document was keyword-retrievable afterwards
        depended on which one answered the next question. Two PDFs uploaded in
        one session on 2026-10-25 were both in Qdrant and only one was in the
        container that was asked.

        So Qdrant is the single source of truth and the sparse index is a
        cache of it, rebuilt here when the two disagree. Everything the cache
        holds is already in the point payload -- `corpus_entry` does the
        conversion -- which is what makes rebuilding possible at all.

        **The disagreement test is a count.** It costs one collection-info
        call, where comparing ids would cost a full scroll, and a full scroll
        is the thing being avoided. The gap that leaves: an equal number of
        different chunks is not detected. That needs a write that reached one
        half and not the other, or a delete and an add of the same size
        between two checks, and the cost of closing it is paying the scroll
        on every check.

        **An empty collection never empties the cache.** Dense 0 against a
        populated sparse index is reported by `/namespaces/{ns}/sources` and
        acted on nowhere, because the baked FastAPI index cannot be rebuilt
        from a collection that no longer holds it -- a transient empty read
        would cost the container its corpus until the next deploy. Every
        other mismatch, including a delete that took the count down by one,
        rebuilds.

        Pass *dense_chunks* when the caller has already read it; the sources
        route has, and this then costs nothing extra there.
        """
        components = self.get(namespace)
        sparse = components.sparse_index
        if sparse is None:
            return SparseSync(False, False, 0, None)

        given = dense_chunks is not _UNREAD
        if not given and self._sync_is_fresh(components):
            return SparseSync(False, False, sparse.chunk_count(), None)

        async with components.sync_lock:
            # Re-read under the lock: the request that was holding it may
            # have done this one's work while it waited.
            if not given and self._sync_is_fresh(components):
                return SparseSync(False, False, sparse.chunk_count(), None)

            dense = dense_chunks if given else await self.dense_chunk_count(namespace)
            held = sparse.chunk_count()
            if dense is None:
                # Unreachable is not "zero" and not "agreed". Leave the
                # timestamp alone so the next request tries again rather
                # than trusting an answer nobody got.
                return SparseSync(True, False, held, None)

            components.synced_at = time.monotonic()
            if dense == held or (dense == 0 and held > 0):
                return SparseSync(True, False, held, dense)

            entries = await self._scroll_corpus(namespace)
            if entries is None:
                return SparseSync(True, False, held, dense)

            await sparse.replace_all(entries)
            logger.info(
                "sparse_index_reconciled",
                namespace=namespace, before=held, after=len(entries), dense=dense,
            )
            return SparseSync(True, True, len(entries), dense)

    def _sync_is_fresh(self, components: NamespaceComponents) -> bool:
        """Whether the last reconcile is recent enough to skip another."""
        ttl = self._shared.settings.retrieval.sparse_sync_ttl_seconds
        if ttl <= 0 or components.synced_at is None:
            return False
        return (time.monotonic() - components.synced_at) < ttl

    async def _scroll_corpus(self, namespace: str) -> list[dict[str, Any]] | None:
        """
        Every point in the collection, as sparse corpus rows.

        None on any failure, and the caller keeps what it has. A partial read
        is the dangerous case: a scroll that dies on page three looks exactly
        like a corpus that shrank, and adopting it would delete two thirds of
        the index to match a number that was never true. Vectors are left
        behind -- this half does not use them and they are the whole weight.
        """
        collection = namespace_to_collection(namespace)
        client = self._shared.qdrant_client
        rows: list[dict[str, Any]] = []
        offset = None
        try:
            while True:
                points, offset = await client.scroll(
                    collection_name=collection,
                    limit=_SCROLL_PAGE,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                rows.extend(corpus_entry(str(p.id), p.payload or {}) for p in points)
                if offset is None:
                    return rows
        except Exception as exc:  # noqa: BLE001 -- any failure means "keep what we have"
            logger.warning(
                "sparse_reconcile_scroll_failed",
                namespace=namespace, read=len(rows), error=str(exc),
            )
            return None

    async def list_namespaces(self) -> list[str]:
        """Return namespaces that have an Atlas-managed Qdrant collection."""
        try:
            result = await self._shared.qdrant_client.get_collections()
            namespaces = []
            for c in result.collections:
                ns = collection_to_namespace(c.name)
                if ns is not None:
                    namespaces.append(ns)
            return sorted(namespaces)
        except Exception as exc:
            logger.warning("list_namespaces_failed", error=str(exc))
            return []
