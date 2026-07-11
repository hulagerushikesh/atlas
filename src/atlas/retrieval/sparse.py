"""
BM25 sparse retriever.

Design rationale:
    Wraps BM25SparseIndex.search() (which is synchronous / CPU-bound) behind
    the async BaseRetriever interface using asyncio.to_thread(). This keeps the
    event loop unblocked while numpy-heavy BM25 scoring runs on a worker thread.

    The BM25SparseIndex instance is injected rather than constructed here so
    the Module A index and the Module B retriever share the same in-memory
    corpus — no duplication, and changes made during a session are immediately
    visible to the retriever.

    BM25 raw scores are on [0, ∞). The fusion layer (RRF) doesn't use absolute
    score values — only rank position — so no normalisation is needed here.
    We still surface the raw score in RetrievedChunk for observability.
"""

from __future__ import annotations

import asyncio

import structlog

from atlas.ingestion.sparse import BM25SparseIndex
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import BaseRetriever, RetrievalResult, RetrievedChunk

logger = structlog.get_logger(__name__)


class BM25Retriever(BaseRetriever):
    """Keyword retrieval via the in-memory BM25 sparse index."""

    def __init__(self, index: BM25SparseIndex) -> None:
        self._index = index

    @property
    def name(self) -> str:
        return "bm25_sparse"

    async def retrieve(self, query: str, top_k: int) -> RetrievalResult:
        # Run CPU-bound BM25 scoring on a thread so we don't block the loop
        results = await asyncio.to_thread(self._index.search, query, top_k)

        chunks = [
            RetrievedChunk(
                chunk_id=entry["chunk_id"],
                content=entry["content"],
                score=score,
                metadata=self._entry_to_metadata(entry),
            )
            for entry, score in results
        ]
        logger.debug("sparse_retrieve", query=query[:60], hits=len(chunks))
        return RetrievalResult(query=query, chunks=chunks, retriever_name=self.name)

    @staticmethod
    def _entry_to_metadata(entry: dict) -> ChunkMetadata:  # type: ignore[type-arg]
        m = entry["metadata"]
        return ChunkMetadata(
            doc_id=m["doc_id"],
            source=m["source"],
            doc_type=DocumentType(m["doc_type"]),
            chunk_index=m["chunk_index"],
            start_char=m["start_char"],
            end_char=m["end_char"],
            page_number=m.get("page_number"),
            content_hash=m.get("content_hash", ""),
            extra=m.get("extra", {}),
        )
