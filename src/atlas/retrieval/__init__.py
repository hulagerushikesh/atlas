"""
Module B — Hybrid retrieval and reranking.

Submodules:
    dense     — Qdrant ANN dense retriever
    sparse    — BM25 sparse retriever
    fusion    — Reciprocal Rank Fusion of dense + sparse results
    reranker  — Cross-encoder reranker (sentence-transformers)
    hybrid    — HybridRetriever: orchestrates the full retrieve → fuse → rerank pipeline
"""

from typing import TYPE_CHECKING, Any

from atlas.retrieval.dense import QdrantDenseRetriever
from atlas.retrieval.fusion import reciprocal_rank_fusion
from atlas.retrieval.hybrid import HybridRetrievalResult, HybridRetriever
from atlas.retrieval.lazy import LazyCrossEncoderReranker
from atlas.retrieval.sparse import BM25Retriever

if TYPE_CHECKING:  # pragma: no cover - import-time cost is the thing avoided
    from atlas.retrieval.reranker import CrossEncoderReranker

__all__ = [
    "QdrantDenseRetriever",
    "BM25Retriever",
    "reciprocal_rank_fusion",
    "CrossEncoderReranker",
    "LazyCrossEncoderReranker",
    "HybridRetriever",
    "HybridRetrievalResult",
]


def __getattr__(name: str) -> Any:
    """Resolve `CrossEncoderReranker` on access rather than on import.

    Importing this package used to pull in torch, transformers and
    sentence-transformers — 12.41 s of a 36.9 s Cloud Run cold start,
    measured in-container with the image already local. Everything that
    needs the real class asks for it and pays then; `atlas.api.namespaces`
    imports the package to reach three light retrievers and no longer pays
    at all. Keeping the name exported means `from atlas.retrieval import
    CrossEncoderReranker` still works for tests and scripts.
    """
    if name == "CrossEncoderReranker":
        from atlas.retrieval.reranker import CrossEncoderReranker

        return CrossEncoderReranker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
