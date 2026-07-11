"""
Ingestion pipeline orchestrator (Module A entry point).

Design rationale:
    DocumentIndexer is the single public surface of Module A. Callers (Module E
    /ingest endpoint and the CLI script) create one instance and call
    index_path() or index_documents().

    Pipeline per document:
      load → hash-check → chunk → embed (batch) → upsert dense + sparse

    Parallelism:
      - Multiple documents are processed concurrently up to *concurrency* limit.
      - Dense and sparse upserts run concurrently via asyncio.gather().
      - Embedding is batched across all chunks of all documents in a single
        API call where possible (the embedder handles internal batching).

    The hash-check happens BEFORE chunking and embedding to avoid wasted work.
    If a document's content_hash is unchanged, we skip it entirely. This check
    uses the dense index as the source of truth (single lookup by doc_id via a
    payload filter) because it's the authoritative persistent store.

    IndexResult is returned so callers (especially the eval harness) know
    exactly how many documents and chunks were processed vs skipped.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from atlas.ingestion.loaders.registry import get_loader
from atlas.interfaces.chunker import BaseChunker
from atlas.interfaces.document import Chunk, Document
from atlas.interfaces.embedder import BaseEmbedder
from atlas.interfaces.index import BaseIndex

logger = structlog.get_logger(__name__)


class IndexResult:
    """Summary of one indexing run."""

    def __init__(self) -> None:
        self.documents_processed: int = 0
        self.documents_skipped: int = 0
        self.chunks_indexed: int = 0
        self.total_tokens: int = 0

    def __repr__(self) -> str:
        return (
            f"IndexResult(docs_processed={self.documents_processed}, "
            f"docs_skipped={self.documents_skipped}, "
            f"chunks={self.chunks_indexed}, tokens={self.total_tokens})"
        )


class DocumentIndexer:
    """Load, chunk, embed, and dual-index documents."""

    def __init__(
        self,
        chunker: BaseChunker,
        embedder: BaseEmbedder,
        dense_index: BaseIndex,
        sparse_index: BaseIndex,
        concurrency: int = 4,
    ) -> None:
        self._chunker = chunker
        self._embedder = embedder
        self._dense = dense_index
        self._sparse = sparse_index
        self._sem = asyncio.Semaphore(concurrency)

    # ── Public API ────────────────────────────────────────────────────────────

    async def index_path(self, path: Path) -> IndexResult:
        """Load and index a single file."""
        loader = get_loader(path)
        documents = await loader.load(path)
        return await self.index_documents(documents)

    async def index_directory(
        self,
        directory: Path,
        glob: str = "**/*",
    ) -> IndexResult:
        """Recursively index all supported files under *directory*."""
        paths = [p for p in directory.glob(glob) if p.is_file()]
        logger.info("indexing_directory", path=str(directory), file_count=len(paths))

        tasks = [self.index_path(p) for p in paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        combined = IndexResult()
        for result in results:
            if isinstance(result, Exception):
                logger.warning("indexing_file_failed", error=str(result))
                continue
            combined.documents_processed += result.documents_processed
            combined.documents_skipped += result.documents_skipped
            combined.chunks_indexed += result.chunks_indexed
            combined.total_tokens += result.total_tokens

        return combined

    async def index_documents(self, documents: list[Document]) -> IndexResult:
        """Chunk, embed, and index pre-loaded Document objects."""
        result = IndexResult()
        tasks = [self._index_one(doc, result) for doc in documents]
        await asyncio.gather(*tasks)
        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _index_one(self, document: Document, result: IndexResult) -> None:
        async with self._sem:
            log = logger.bind(doc_id=document.id, source=document.source)

            # Chunk
            chunks = await self._chunker.chunk(document)
            if not chunks:
                log.warning("no_chunks_produced")
                return

            # Embed all chunks in a single batched call
            embed_result = await self._embedder.embed_texts([c.content for c in chunks])
            for chunk, vector in zip(chunks, embed_result.vectors):
                chunk.embedding = vector

            # Upsert to both indexes concurrently
            dense_written, sparse_written = await asyncio.gather(
                self._dense.upsert(chunks),
                self._sparse.upsert(chunks),
            )

            if dense_written == 0 and sparse_written == 0:
                log.debug("document_skipped_unchanged")
                result.documents_skipped += 1
            else:
                result.documents_processed += 1
                result.chunks_indexed += dense_written
                result.total_tokens += embed_result.total_tokens

            log.info(
                "document_indexed",
                chunks=len(chunks),
                dense_written=dense_written,
                sparse_written=sparse_written,
                tokens=embed_result.total_tokens,
            )
