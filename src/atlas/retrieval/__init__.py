"""
Module B — Hybrid retrieval and reranking.

Submodules:
    dense     — Qdrant ANN dense retriever
    sparse    — BM25 sparse retriever
    fusion    — Reciprocal Rank Fusion of dense + sparse results
    reranker  — Cross-encoder reranker (sentence-transformers)
    hybrid    — HybridRetriever: orchestrates the full retrieve → fuse → rerank pipeline
"""

from atlas.retrieval.dense import QdrantDenseRetriever
from atlas.retrieval.fusion import reciprocal_rank_fusion
from atlas.retrieval.hybrid import HybridRetriever, HybridRetrievalResult
from atlas.retrieval.reranker import CrossEncoderReranker
from atlas.retrieval.sparse import BM25Retriever

__all__ = [
    "QdrantDenseRetriever",
    "BM25Retriever",
    "reciprocal_rank_fusion",
    "CrossEncoderReranker",
    "HybridRetriever",
    "HybridRetrievalResult",
]
