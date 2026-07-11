"""Plain text document loader."""

from __future__ import annotations

import asyncio
from pathlib import Path

from atlas.ingestion.hashing import hash_bytes
from atlas.interfaces.document import Document, DocumentType
from atlas.interfaces.loader import BaseDocumentLoader


class TextLoader(BaseDocumentLoader):
    """Load UTF-8 plain text files."""

    @property
    def supported_extensions(self) -> frozenset[str]:
        return frozenset({".txt", ".text", ".rst"})

    async def load(self, path: Path) -> list[Document]:
        raw_bytes = await asyncio.to_thread(path.read_bytes)
        return [
            Document(
                source=str(path),
                doc_type=DocumentType.TEXT,
                content=raw_bytes.decode("utf-8", errors="replace"),
                content_hash=hash_bytes(raw_bytes),
            )
        ]
