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

import structlog
from qdrant_client import AsyncQdrantClient

from atlas.config import Settings
from atlas.ingestion.chunkers import get_chunker
from atlas.ingestion.dense import QdrantDenseIndex
from atlas.ingestion.embedder import OpenAIEmbedder
from atlas.ingestion.indexer import DocumentIndexer
from atlas.ingestion.sparse import BM25SparseIndex
from atlas.orchestration.decomposer import QueryDecomposer
from atlas.orchestration.faithfulness import FaithfulnessChecker
from atlas.orchestration.generator import AnswerGenerator
from atlas.orchestration.grader import RetrievalGrader
from atlas.orchestration.llm import OpenAILLMProvider
from atlas.orchestration.pipeline import RAGPipeline
from atlas.orchestration.router import QueryRouter
from atlas.retrieval.dense import QdrantDenseRetriever
from atlas.retrieval.hybrid import HybridRetriever
from atlas.retrieval.reranker import CrossEncoderReranker
from atlas.retrieval.sparse import BM25Retriever

logger = structlog.get_logger(__name__)

_COLLECTION_PREFIX = "atlas_"


def namespace_to_collection(namespace: str) -> str:
    """Map a namespace string to a Qdrant collection name."""
    return f"{_COLLECTION_PREFIX}{namespace}"


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
        self.reranker = CrossEncoderReranker(settings.reranker)
        api_key = settings.qdrant.api_key.get_secret_value() if settings.qdrant.api_key else None
        self.qdrant_client = AsyncQdrantClient(url=settings.qdrant.url, api_key=api_key)


class NamespaceComponents:
    """Per-namespace pipeline and indexer."""

    def __init__(self, pipeline: RAGPipeline, indexer: DocumentIndexer) -> None:
        self.pipeline = pipeline
        self.indexer = indexer


class NamespaceRegistry:
    """
    Lazy per-namespace component cache.

    Call get(namespace) to retrieve (or build) the pipeline and indexer for
    a given corpus. List available namespaces via list_namespaces().
    """

    def __init__(self, shared: SharedComponents) -> None:
        self._shared = shared
        self._cache: dict[str, NamespaceComponents] = {}

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

        sparse = BM25SparseIndex()

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
            router=QueryRouter(s.llm),
            decomposer=QueryDecomposer(s.llm),
            grader=RetrievalGrader(s.llm),
            generator=AnswerGenerator(s.llm),
            faithfulness=FaithfulnessChecker(s.llm),
        )

        indexer = DocumentIndexer(
            chunker=get_chunker(cfg, embedder=s.embedder),
            embedder=s.embedder,
            dense_index=QdrantDenseIndex(qdrant_cfg, s.embedder.dimensions),
            sparse_index=sparse,
        )

        return NamespaceComponents(pipeline=pipeline, indexer=indexer)

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
