"""
Fixed-size character-level chunker.

Design rationale:
    The simplest possible chunker — slide a window of *size* characters across
    the document with *overlap* characters of context carry-over. Useful as a
    baseline in the eval harness (Module D) to measure how much the recursive
    and semantic chunkers actually improve retrieval quality.

    Character counts rather than token counts are used here intentionally:
    calling a tokenizer per chunk during indexing adds latency and a dependency
    on the specific LLM tokenizer. The embedding model handles tokens
    internally; characters are a good enough proxy for chunk boundaries.
    chunk_size=512 chars ≈ 100–130 tokens for English prose, well within
    the 8192-token context of text-embedding-3-small.

    start_char / end_char on ChunkMetadata are exact so callers can reconstruct
    the original text span for citation highlighting.
"""

from __future__ import annotations

from atlas.ingestion.hashing import hash_text
from atlas.interfaces.chunker import BaseChunker
from atlas.interfaces.document import Chunk, ChunkMetadata, Document


class FixedSizeChunker(BaseChunker):
    """Slide a fixed-size window across the document text."""

    def __init__(self, size: int = 512, overlap: int = 64) -> None:
        if overlap >= size:
            raise ValueError(f"overlap ({overlap}) must be less than size ({size})")
        self.size = size
        self.overlap = overlap

    async def chunk(self, document: Document) -> list[Chunk]:
        text = document.content
        step = self.size - self.overlap
        chunks: list[Chunk] = []

        for idx, start in enumerate(range(0, len(text), step)):
            end = min(start + self.size, len(text))
            content = text[start:end]

            if not content.strip():
                continue

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

            if end == len(text):
                break

        return chunks
