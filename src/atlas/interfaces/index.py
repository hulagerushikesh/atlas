"""
Abstract index interface covering both dense (vector) and sparse (BM25) stores.

Design rationale:
    Using a single ABC for both index types lets the ingestion pipeline treat
    indexing uniformly — it fans out to [dense_index, sparse_index] without
    caring about implementation details.

    upsert() is idempotent by design: callers pass the chunk_id as the
    primary key. If the content_hash hasn't changed the implementation should
    skip the write (the concrete class is responsible for that check).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from atlas.interfaces.document import Chunk


class IndexStats(BaseModel):
    total_chunks: int
    collection_name: str
    index_type: str  # "dense" | "sparse"


class BaseIndex(ABC):
    """Persist and query an index of Chunks."""

    @abstractmethod
    async def upsert(self, chunks: list[Chunk]) -> int:
        """
        Insert or update chunks. Returns the count of chunks actually written
        (skipped chunks with unchanged content_hash are not counted).
        """

    @abstractmethod
    async def delete(self, chunk_ids: list[str]) -> int:
        """Delete chunks by id. Returns count deleted."""

    @abstractmethod
    async def stats(self) -> IndexStats:
        """Return current collection statistics."""
