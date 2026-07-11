"""
Recursive character-level chunker with configurable separator hierarchy.

Design rationale:
    "Recursive" means: try to split on the highest-level separator first (e.g.
    "\n\n" for paragraphs); if a resulting piece is still over *size*, recurse
    with the next separator in the hierarchy. This keeps semantically coherent
    units (paragraphs, sentences) intact as long as they fit within the size
    budget, only falling back to character-level splitting as a last resort.

    The default separator hierarchy is tuned for mixed document types:
      1. \f  — page break (PDFs)
      2. \n\n — paragraph break
      3. \n   — line break
      4. ". " — sentence boundary (rough; avoids pulling in an NLP dependency)
      5. " "  — word boundary
      6. ""   — character (last resort)

    Markdown headings (## ) are inserted before \n\n because heading-level
    splits preserve section structure, which is critical for documents where
    the same term appears in multiple sections with different meanings.

    Overlap is re-attached from the *end* of the previous chunk, not the
    start of the next one, so the overlap appears at the beginning of the
    new chunk — where an LLM or retriever reads first.
"""

from __future__ import annotations

from atlas.ingestion.hashing import hash_text
from atlas.interfaces.chunker import BaseChunker
from atlas.interfaces.document import Chunk, ChunkMetadata, Document

# Default separator hierarchy for mixed-document corpora
_DEFAULT_SEPARATORS = ["\f", "\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""]


class RecursiveChunker(BaseChunker):
    """Split text recursively using a separator hierarchy."""

    def __init__(
        self,
        size: int = 512,
        overlap: int = 64,
        separators: list[str] | None = None,
    ) -> None:
        if overlap >= size:
            raise ValueError(f"overlap ({overlap}) must be less than size ({size})")
        self.size = size
        self.overlap = overlap
        self.separators = separators if separators is not None else _DEFAULT_SEPARATORS

    async def chunk(self, document: Document) -> list[Chunk]:
        pieces = self._split(document.content, self.separators)
        merged = self._merge(pieces)

        chunks: list[Chunk] = []
        char_cursor = 0  # tracks approximate position in original text

        for idx, content in enumerate(merged):
            # Locate start_char by searching from the last known position
            start = document.content.find(content[:40], char_cursor)
            if start == -1:
                start = char_cursor  # fallback if exact match fails (overlap edge case)
            end = start + len(content)
            char_cursor = max(0, end - self.overlap)

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

    def _split(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text until all pieces are ≤ size."""
        if not separators:
            # Character-level fallback: slice directly
            return [text[i : i + self.size] for i in range(0, len(text), self.size)]

        sep, remaining_seps = separators[0], separators[1:]

        if sep == "":
            return [text[i : i + self.size] for i in range(0, len(text), self.size)]

        pieces = text.split(sep)
        result: list[str] = []
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            if len(piece) <= self.size:
                result.append(piece)
            else:
                result.extend(self._split(piece, remaining_seps))

        return result

    def _merge(self, pieces: list[str]) -> list[str]:
        """
        Greedily merge small pieces up to *size*, carrying *overlap* forward.
        This avoids an explosion of tiny chunks from sentence-level splits.
        """
        chunks: list[str] = []
        current_parts: list[str] = []
        current_len = 0

        for piece in pieces:
            if current_len + len(piece) + 1 > self.size and current_parts:
                chunks.append(" ".join(current_parts))
                # Keep last overlap characters as context for the next chunk
                overlap_text = " ".join(current_parts)[-self.overlap :]
                current_parts = [overlap_text] if overlap_text.strip() else []
                current_len = len(overlap_text)

            current_parts.append(piece)
            current_len += len(piece) + 1

        if current_parts:
            chunks.append(" ".join(current_parts))

        return [c for c in chunks if c.strip()]
