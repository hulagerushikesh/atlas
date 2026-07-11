"""
PDF document loader using pypdf.

Design rationale:
    pypdf is pure-Python and handles the vast majority of corporate PDFs
    without requiring a system-level dependency (e.g. poppler). For scanned
    PDFs that require OCR, the loader raises a clear ValueError so the caller
    can route to an OCR-capable loader rather than silently returning empty
    text.

    Page text is joined with a form-feed character (\f) to preserve page
    boundaries. Downstream chunkers can use \f as a hard split point to avoid
    chunks that span page boundaries, which reduces citation accuracy.

    We emit one Document per PDF file (not one per page) because the page
    structure is metadata, not a semantic boundary — the chunker decides the
    actual split points.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pypdf

from atlas.ingestion.hashing import hash_bytes
from atlas.interfaces.document import Document, DocumentType
from atlas.interfaces.loader import BaseDocumentLoader


class PDFLoader(BaseDocumentLoader):
    """Extract text from PDF files using pypdf."""

    @property
    def supported_extensions(self) -> frozenset[str]:
        return frozenset({".pdf"})

    async def load(self, path: Path) -> list[Document]:
        raw_bytes = await asyncio.to_thread(path.read_bytes)
        content = await asyncio.to_thread(self._extract_text, raw_bytes)

        if not content.strip():
            raise ValueError(
                f"No text extracted from {path}. "
                "The file may be a scanned PDF requiring OCR."
            )

        return [
            Document(
                source=str(path),
                doc_type=DocumentType.PDF,
                content=content,
                content_hash=hash_bytes(raw_bytes),
                metadata={"page_count": content.count("\f") + 1},
            )
        ]

    @staticmethod
    def _extract_text(raw_bytes: bytes) -> str:
        import io
        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        # Form-feed separates pages; chunkers can split on \f for page-aligned chunks
        return "\f".join(
            page.extract_text() or "" for page in reader.pages
        )
