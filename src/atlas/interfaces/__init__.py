"""
Shared contracts for all Atlas modules.

Everything in this package is pure ABCs and Pydantic models — no I/O, no
dependencies on concrete implementations. Any module (A, B, C, D, E) can
import from here without pulling in transitive deps from sibling modules.

Exported at package level for ergonomic imports:
    from atlas.interfaces import Document, Chunk, BaseRetriever, ...
"""

from atlas.interfaces.document import Chunk, ChunkMetadata, Document, DocumentType
from atlas.interfaces.embedder import BaseEmbedder, EmbeddingResult
from atlas.interfaces.evaluator import (
    EvalDataset,
    EvalResult,
    EvalSample,
    MetricScore,
    PipelineConfig,
)
from atlas.interfaces.index import BaseIndex, IndexStats
from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, GenerationResponse, Message
from atlas.interfaces.loader import BaseDocumentLoader
from atlas.interfaces.chunker import BaseChunker
from atlas.interfaces.retriever import BaseRetriever, RetrievalResult, RetrievedChunk
from atlas.interfaces.reranker import BaseReranker

__all__ = [
    # Document models
    "Document",
    "DocumentType",
    "Chunk",
    "ChunkMetadata",
    # Loaders & chunkers
    "BaseDocumentLoader",
    "BaseChunker",
    # Embeddings
    "BaseEmbedder",
    "EmbeddingResult",
    # Indexes
    "BaseIndex",
    "IndexStats",
    # Retrieval
    "BaseRetriever",
    "RetrievedChunk",
    "RetrievalResult",
    "BaseReranker",
    # LLM
    "BaseLLMProvider",
    "Message",
    "GenerationRequest",
    "GenerationResponse",
    # Evaluation
    "EvalSample",
    "EvalDataset",
    "MetricScore",
    "EvalResult",
    "PipelineConfig",
]
