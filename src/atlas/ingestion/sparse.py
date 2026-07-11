"""
BM25 sparse index implementation.

Design rationale:
    rank-bm25 is an in-memory library — there is no incremental update API;
    the index must be rebuilt whenever the corpus changes. This is the key
    tradeoff vs a proper sparse index (Elasticsearch, Qdrant sparse vectors).
    We accept it because:
      1. For corpora up to ~100k chunks, rebuild takes <1s.
      2. It keeps the dependency graph simple (no Elasticsearch service).
      3. The eval harness (Module D) benefits from deterministic, reproducible
         retrieval without external service state.

    Persistence: the corpus (list of tokenized documents + chunk metadata) is
    serialised to disk as JSON so it survives process restarts. The BM25 index
    itself is rebuilt from the persisted corpus on startup — JSON is more
    portable than pickle and avoids compatibility issues across BM25 library
    versions.

    Idempotency: same as the dense index — skip chunks whose content_hash
    matches the stored value.

    Thread safety: asyncio.to_thread() wraps the CPU-bound BM25 rebuild so it
    doesn't block the event loop. Because upsert/retrieve are the only mutators
    and FastAPI runs a single event loop per worker, there is no concurrent
    mutation risk. If you switch to multi-process workers, protect _corpus with
    a file-level lock.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import structlog
from rank_bm25 import BM25Okapi

from atlas.interfaces.document import Chunk, ChunkMetadata, DocumentType
from atlas.interfaces.index import BaseIndex, IndexStats

logger = structlog.get_logger(__name__)


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + lowercase tokeniser. Swap for a stemmer if needed."""
    return text.lower().split()


class BM25SparseIndex(BaseIndex):
    """In-memory BM25 index with JSON persistence."""

    def __init__(self, persist_path: Path = Path("bm25_index.json")) -> None:
        self._persist_path = persist_path
        # Each entry: {"chunk_id": ..., "content": ..., "content_hash": ..., "metadata": {...}}
        self._corpus: list[dict[str, Any]] = []
        self._bm25: BM25Okapi | None = None
        self._load_from_disk()

    # ── Public interface ──────────────────────────────────────────────────────

    async def upsert(self, chunks: list[Chunk]) -> int:
        existing_hashes = {e["chunk_id"]: e["content_hash"] for e in self._corpus}

        new_entries: list[dict[str, Any]] = []
        for chunk in chunks:
            if existing_hashes.get(chunk.id) == chunk.metadata.content_hash:
                continue  # unchanged — skip
            # Remove stale version if present
            self._corpus = [e for e in self._corpus if e["chunk_id"] != chunk.id]
            new_entries.append(
                {
                    "chunk_id": chunk.id,
                    "content": chunk.content,
                    "content_hash": chunk.metadata.content_hash,
                    "metadata": chunk.metadata.model_dump(),
                }
            )

        if not new_entries:
            return 0

        self._corpus.extend(new_entries)
        await asyncio.to_thread(self._rebuild)
        await asyncio.to_thread(self._save_to_disk)

        logger.info("bm25_index_upserted", count=len(new_entries))
        return len(new_entries)

    async def delete(self, chunk_ids: list[str]) -> int:
        id_set = set(chunk_ids)
        before = len(self._corpus)
        self._corpus = [e for e in self._corpus if e["chunk_id"] not in id_set]
        removed = before - len(self._corpus)
        if removed:
            await asyncio.to_thread(self._rebuild)
            await asyncio.to_thread(self._save_to_disk)
        return removed

    async def stats(self) -> IndexStats:
        return IndexStats(
            total_chunks=len(self._corpus),
            collection_name=str(self._persist_path),
            index_type="sparse",
        )

    def search(self, query: str, top_k: int) -> list[tuple[dict[str, Any], float]]:
        """
        Synchronous search — called by BM25Retriever from within an executor.
        Returns [(entry_dict, score)] sorted by score descending.
        """
        if self._bm25 is None or not self._corpus:
            return []
        tokens = _tokenize(query)
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            zip(self._corpus, scores), key=lambda x: x[1], reverse=True
        )
        return [(entry, float(score)) for entry, score in ranked[:top_k]]

    # ── Private helpers ───────────────────────────────────────────────────────

    def _rebuild(self) -> None:
        if not self._corpus:
            self._bm25 = None
            return
        tokenized = [_tokenize(e["content"]) for e in self._corpus]
        self._bm25 = BM25Okapi(tokenized)

    def _save_to_disk(self) -> None:
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._persist_path.write_text(json.dumps(self._corpus, indent=2))

    def _load_from_disk(self) -> None:
        if not self._persist_path.exists():
            return
        try:
            self._corpus = json.loads(self._persist_path.read_text())
            self._rebuild()
            logger.info("bm25_index_loaded", chunks=len(self._corpus))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("bm25_index_load_failed", error=str(e))
            self._corpus = []

    @staticmethod
    def _entry_to_chunk_metadata(entry: dict[str, Any]) -> ChunkMetadata:
        meta = entry["metadata"]
        return ChunkMetadata(
            doc_id=meta["doc_id"],
            source=meta["source"],
            doc_type=DocumentType(meta["doc_type"]),
            chunk_index=meta["chunk_index"],
            start_char=meta["start_char"],
            end_char=meta["end_char"],
            page_number=meta.get("page_number"),
            content_hash=meta.get("content_hash", ""),
            extra=meta.get("extra", {}),
        )
