"""
Semantic chunker: split on embedding-similarity drops between sentences.

Design rationale:
    Fixed-size and recursive chunkers are syntactic — they don't know when
    a topic changes. The semantic chunker embeds each sentence, computes the
    cosine similarity between consecutive sentences, and inserts a chunk
    boundary wherever similarity drops below *threshold*. This keeps
    topically coherent text together regardless of paragraph structure.

    Algorithm (Greg Kamradt's "semantic chunking"):
      1. Split document into sentences (naive period-split; good enough for
         English prose without pulling in spaCy).
      2. Embed all sentences in one batched call to the embedder.
      3. Compute cosine similarity between consecutive sentence vectors.
      4. Wherever similarity < threshold, start a new chunk.
      5. Apply min_size / max_size guards: if a segment is too small it's
         merged into the adjacent chunk; if too large it's split recursively.

    Tradeoff: requires one embedding call per document at index time (vs zero
    for fixed/recursive). This adds ~50–200ms per document but produces
    meaningfully better chunk boundaries for long, multi-topic documents.
    We accept the cost because indexing is an offline, amortized operation.

    The embedder is injected at construction time so this class doesn't
    hardwire any provider — consistent with the DI principle throughout Atlas.
"""

from __future__ import annotations

import numpy as np

from atlas.ingestion.hashing import hash_text
from atlas.interfaces.chunker import BaseChunker
from atlas.interfaces.document import Chunk, ChunkMetadata, Document
from atlas.interfaces.embedder import BaseEmbedder

# Sentence splitting: split after ". ", "! ", "? " but not inside "e.g. " etc.
import re

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


class SemanticChunker(BaseChunker):
    """
    Chunk by detecting topic-shift boundaries via embedding cosine similarity.
    """

    def __init__(
        self,
        embedder: BaseEmbedder,
        threshold: float = 0.75,
        min_chunk_size: int = 100,
        max_chunk_size: int = 1024,
    ) -> None:
        self.embedder = embedder
        self.threshold = threshold
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size

    async def chunk(self, document: Document) -> list[Chunk]:
        sentences = _split_sentences(document.content)

        if len(sentences) <= 1:
            # Single sentence or very short doc → one chunk
            return self._make_chunks(document, [document.content])

        # Batch embed all sentences in one API call
        result = await self.embedder.embed_texts(sentences)
        vectors = np.array(result.vectors, dtype=np.float32)

        # Find boundaries: positions where sim drops below threshold
        boundary_indices: list[int] = [0]
        for i in range(1, len(sentences)):
            sim = _cosine_sim(vectors[i - 1], vectors[i])
            if sim < self.threshold:
                boundary_indices.append(i)
        boundary_indices.append(len(sentences))

        # Build raw segments from boundaries
        segments: list[str] = []
        for start_i, end_i in zip(boundary_indices, boundary_indices[1:]):
            segment = " ".join(sentences[start_i:end_i])
            segments.append(segment)

        # Enforce min/max size guards
        segments = self._enforce_size(segments)

        return self._make_chunks(document, segments)

    def _enforce_size(self, segments: list[str]) -> list[str]:
        """Merge under-sized segments, split over-sized ones."""
        merged: list[str] = []
        buf = ""
        for seg in segments:
            if len(buf) + len(seg) < self.min_chunk_size:
                buf = (buf + " " + seg).strip()
            else:
                if buf:
                    merged.append(buf)
                buf = seg
        if buf:
            merged.append(buf)

        # Hard-split segments still over max_chunk_size
        result: list[str] = []
        for seg in merged:
            if len(seg) <= self.max_chunk_size:
                result.append(seg)
            else:
                for i in range(0, len(seg), self.max_chunk_size):
                    result.append(seg[i : i + self.max_chunk_size])

        return result

    def _make_chunks(self, document: Document, segments: list[str]) -> list[Chunk]:
        chunks: list[Chunk] = []
        cursor = 0
        for idx, content in enumerate(segments):
            start = document.content.find(content[:40], cursor)
            if start == -1:
                start = cursor
            end = start + len(content)
            cursor = end

            chunks.append(
                Chunk(
                    content=content,
                    metadata=ChunkMetadata(
                        doc_id=document.id,
                        source=document.source,
                        doc_type=document.doc_type,
                        chunk_index=idx,
                        start_char=start,
                        end_char=end,
                        content_hash=hash_text(content),
                    ),
                )
            )
        return chunks
