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

    async def unchanged_ids(self, chunks: list[Chunk]) -> set[str]:
        """
        Ids of chunks already stored with the same content_hash. Lets the
        indexer skip embedding unchanged chunks. Default: nothing is known.
        """
        return set()

    @abstractmethod
    async def delete(self, chunk_ids: list[str]) -> int:
        """Delete chunks by id. Returns count deleted."""

    async def prune_document(self, doc_id: str, chunk_count: int) -> int:
        """
        Delete chunks of *doc_id* whose chunk_index >= *chunk_count*. Ids are
        (doc_id, chunk_index), so when a re-ingested document produces fewer
        chunks than before the tail of the old version would otherwise stay
        behind. Returns count deleted. Default: nothing to prune.
        """
        return 0

    # ── E2: one document's access list (docs/e2-permissions.md §4) ───────────

    async def document_acl(self, doc_id: str) -> list[str] | None:
        """The access list *doc_id*'s passages carry now; None if it has none
        stored. A re-ingest keeps it, so editing a narrowed document cannot
        reopen it. Default: nothing known."""
        return None

    async def readable_passages(self, doc_id: str, access: frozenset[str]) -> int:
        """How many of *doc_id*'s passages a caller holding *access* may read."""
        raise NotImplementedError

    async def set_document_acl(self, doc_id: str, acl: list[str]) -> int:
        """Give every passage of *doc_id* this access list. Returns how many
        passages were changed where the index can tell. Default: none."""
        return 0

    async def delete_document(self, doc_id: str) -> int:
        """Remove every passage of *doc_id*. Default: none."""
        return 0

    @abstractmethod
    async def stats(self) -> IndexStats:
        """Return current collection statistics."""
