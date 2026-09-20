"""
Qdrant dense vector index implementation.

Design rationale:
    Qdrant stores each chunk as a "point" with:
      - id: the chunk's UUID (Qdrant accepts string UUIDs natively)
      - vector: the embedding
      - payload: the full ChunkMetadata dict + content

    Idempotency: before upserting we check the stored payload's content_hash.
    If it matches the incoming chunk's hash, we skip the write. This avoids
    redundant embedding API calls AND keeps Qdrant's HNSW graph stable (every
    upsert triggers a partial graph rebuild for affected segments).

    We use the Qdrant Python client's async interface throughout. The
    collection is created on first use with HNSW + cosine distance — cosine
    is appropriate for text embeddings from OpenAI (which are L2-normalised,
    making cosine equivalent to dot-product but more semantically meaningful
    as a label for interview discussions).

    Batch size of 100 is the Qdrant recommended batch size for upserts;
    above this the HTTP payload grows enough to risk server-side rejection.
"""

from __future__ import annotations

import asyncio

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)

from atlas.config import QdrantConfig
from atlas.interfaces.document import Chunk
from atlas.interfaces.index import BaseIndex, IndexStats

logger = structlog.get_logger(__name__)

_UPSERT_BATCH = 100


class QdrantDenseIndex(BaseIndex):
    """Store and retrieve chunk embeddings via Qdrant ANN search."""

    def __init__(self, config: QdrantConfig, dimensions: int) -> None:
        self._config = config
        self._dimensions = dimensions
        api_key = config.api_key.get_secret_value() if config.api_key else None
        self._client = AsyncQdrantClient(url=config.url, api_key=api_key)
        self._ensure_lock = asyncio.Lock()
        self._collection_ready = False

    async def ensure_collection(self) -> None:
        """Create the collection if it doesn't exist. Idempotent and safe
        under concurrency: the indexer runs several documents at once and on
        a fresh database they all race to create the collection (409)."""
        if self._collection_ready:
            return
        async with self._ensure_lock:
            if self._collection_ready:
                return
            collections = await self._client.get_collections()
            names = {c.name for c in collections.collections}
            if self._config.collection_name not in names:
                try:
                    await self._client.create_collection(
                        collection_name=self._config.collection_name,
                        vectors_config=VectorParams(
                            size=self._dimensions,
                            distance=Distance.COSINE,
                        ),
                    )
                except UnexpectedResponse as e:
                    if e.status_code != 409:  # created by another process
                        raise
                logger.info(
                    "qdrant_collection_created",
                    collection=self._config.collection_name,
                    dimensions=self._dimensions,
                )
            self._collection_ready = True

    async def unchanged_ids(self, chunks: list[Chunk]) -> set[str]:
        await self.ensure_collection()
        if not chunks:
            return set()
        # Fetch existing content hashes for all incoming chunk IDs in one call
        existing = await self._client.retrieve(
            collection_name=self._config.collection_name,
            ids=[c.id for c in chunks],
            with_payload=["content_hash"],
        )
        existing_hashes: dict[str, str] = {
            str(p.id): (p.payload or {}).get("content_hash", "") for p in existing
        }
        return {
            c.id for c in chunks
            if existing_hashes.get(c.id, "") == c.metadata.content_hash
        }

    async def upsert(self, chunks: list[Chunk]) -> int:
        await self.ensure_collection()

        unchanged = await self.unchanged_ids(chunks)
        to_write = [c for c in chunks if c.id not in unchanged]
        skipped = len(chunks) - len(to_write)

        if skipped:
            logger.debug("dense_index_chunks_skipped", count=skipped)

        if not to_write:
            return 0

        points = []
        for chunk in to_write:
            if chunk.embedding is None:
                raise ValueError(f"Chunk {chunk.id} has no embedding — embed before indexing")
            points.append(
                PointStruct(
                    id=chunk.id,
                    vector=chunk.embedding,
                    payload={
                        "content": chunk.content,
                        "content_hash": chunk.metadata.content_hash,
                        **chunk.metadata.model_dump(),
                    },
                )
            )

        # Batch upserts to stay within Qdrant's recommended payload size
        for i in range(0, len(points), _UPSERT_BATCH):
            await self._client.upsert(
                collection_name=self._config.collection_name,
                points=points[i : i + _UPSERT_BATCH],
            )

        logger.info("dense_index_upserted", count=len(to_write))
        return len(to_write)

    async def delete(self, chunk_ids: list[str]) -> int:
        from qdrant_client.models import PointIdsList
        await self._client.delete(
            collection_name=self._config.collection_name,
            points_selector=PointIdsList(points=list(chunk_ids)),
        )
        return len(chunk_ids)

    async def stats(self) -> IndexStats:
        info = await self._client.get_collection(self._config.collection_name)
        return IndexStats(
            total_chunks=info.points_count or 0,
            collection_name=self._config.collection_name,
            index_type="dense",
        )
