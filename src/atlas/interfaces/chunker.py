"""
Abstract base class for chunking strategies.

Design rationale:
    Chunking strategy is one of the highest-leverage knobs in RAG quality.
    By hiding it behind an ABC we can swap strategies (fixed-size, recursive,
    semantic) without touching the indexing pipeline — the pipeline always
    calls chunker.chunk(doc) and gets back a list[Chunk].

    The embedder dependency on BaseChunker is intentional for SemanticChunker:
    it needs to compute embeddings to find similarity-drop boundaries. Passing
    the embedder at construction time (DI) keeps the ABC itself I/O-free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from atlas.interfaces.document import Chunk, Document


class BaseChunker(ABC):
    """Split a Document into indexable Chunks."""

    @abstractmethod
    async def chunk(self, document: Document) -> list[Chunk]:
        """
        Segment *document* into chunks.

        Each returned Chunk must have:
          - A populated ChunkMetadata referencing the parent document.
          - content_hash set on metadata (same xxhash logic as Document).
          - embedding left as None (embedding is the embedder's job).
        """
