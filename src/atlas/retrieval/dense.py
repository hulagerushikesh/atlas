"""
Qdrant dense retriever.

Design rationale:
    Queries the Qdrant collection with ANN search using the embedded query
    vector. The score returned by Qdrant for cosine distance is in [-1, 1]
    (higher = more similar). We pass it through unchanged; normalisation to
    [0, 1] happens in the fusion layer so the retriever itself stays
    stateless and testable in isolation.

    The payload stored by QdrantDenseIndex (Module A) contains the full
    ChunkMetadata dict, so we reconstruct ChunkMetadata from the payload
    rather than making a second lookup — one round-trip per query.
"""

from __future__ import annotations

import structlog
from qdrant_client import AsyncQdrantClient

from atlas.config import QdrantConfig
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.embedder import BaseEmbedder
from atlas.interfaces.retriever import BaseRetriever, RetrievalResult, RetrievedChunk

logger = structlog.get_logger(__name__)


class QdrantDenseRetriever(BaseRetriever):
    """ANN retrieval against the Qdrant dense index."""

    def __init__(self, config: QdrantConfig, embedder: BaseEmbedder) -> None:
        self._config = config
        self._embedder = embedder
        api_key = config.api_key.get_secret_value() if config.api_key else None
        self._client = AsyncQdrantClient(url=config.url, api_key=api_key)

    @property
    def name(self) -> str:
        return "qdrant_dense"

    async def retrieve(self, query: str, top_k: int) -> RetrievalResult:
        query_vector = await self._embedder.embed_query(query)

        hits = await self._client.search(
            collection_name=self._config.collection_name,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
        )

        chunks = [self._hit_to_chunk(h) for h in hits]
        logger.debug("dense_retrieve", query=query[:60], hits=len(chunks))
        return RetrievalResult(query=query, chunks=chunks, retriever_name=self.name)

    @staticmethod
    def _hit_to_chunk(hit: object) -> RetrievedChunk:  # type: ignore[override]
        p = hit.payload  # type: ignore[attr-defined]
        meta = ChunkMetadata(
            doc_id=p["doc_id"],
            source=p["source"],
            doc_type=DocumentType(p["doc_type"]),
            chunk_index=p["chunk_index"],
            start_char=p["start_char"],
            end_char=p["end_char"],
            page_number=p.get("page_number"),
            content_hash=p.get("content_hash", ""),
            extra=p.get("extra", {}),
        )
        return RetrievedChunk(
            chunk_id=str(hit.id),  # type: ignore[attr-defined]
            content=p["content"],
            score=hit.score,  # type: ignore[attr-defined]
            metadata=meta,
        )
