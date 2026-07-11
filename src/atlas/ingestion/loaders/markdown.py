"""
Markdown document loader.

Design rationale:
    We store the *raw* markdown text rather than converting to plain text. The
    recursive chunker splits on markdown headings and paragraph breaks by
    default, so preserving the markup gives it better split-point signals.
    Heading text also appears in chunk content, which improves BM25 recall
    for queries that match document section titles.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from atlas.ingestion.hashing import hash_bytes
from atlas.interfaces.document import Document, DocumentType
from atlas.interfaces.loader import BaseDocumentLoader


class MarkdownLoader(BaseDocumentLoader):
    """Load plain markdown files preserving original markup."""

    @property
    def supported_extensions(self) -> frozenset[str]:
        return frozenset({".md", ".markdown"})

    async def load(self, path: Path) -> list[Document]:
        raw_bytes = await asyncio.to_thread(path.read_bytes)
        content = raw_bytes.decode("utf-8", errors="replace")

        return [
            Document(
                source=str(path),
                doc_type=DocumentType.MARKDOWN,
                content=content,
                content_hash=hash_bytes(raw_bytes),
            )
        ]
