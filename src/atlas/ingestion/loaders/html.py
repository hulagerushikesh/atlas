"""
HTML document loader using BeautifulSoup.

Design rationale:
    We strip script/style tags before text extraction because they produce
    garbage tokens (JS code, CSS selectors) that degrade both embedding
    quality and BM25 scores. get_text(separator="\n") preserves paragraph
    breaks, giving the recursive chunker reasonable split candidates.

    The <title> and <h1-h6> text is captured separately in metadata so that
    the ingestion pipeline can include it as a "header" prefix on every chunk,
    improving retrieval of headless documents where the first paragraph gives
    no context about the topic.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from bs4 import BeautifulSoup

from atlas.ingestion.hashing import hash_bytes
from atlas.interfaces.document import Document, DocumentType
from atlas.interfaces.loader import BaseDocumentLoader


class HTMLLoader(BaseDocumentLoader):
    """Extract visible text from HTML files."""

    @property
    def supported_extensions(self) -> frozenset[str]:
        return frozenset({".html", ".htm"})

    async def load(self, path: Path) -> list[Document]:
        raw_bytes = await asyncio.to_thread(path.read_bytes)
        content, metadata = await asyncio.to_thread(self._parse, raw_bytes)

        return [
            Document(
                source=str(path),
                doc_type=DocumentType.HTML,
                content=content,
                content_hash=hash_bytes(raw_bytes),
                metadata=metadata,
            )
        ]

    @staticmethod
    def _parse(raw_bytes: bytes) -> tuple[str, dict[str, str]]:
        soup = BeautifulSoup(raw_bytes, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        h1 = soup.find("h1")
        heading = h1.get_text(strip=True) if h1 else ""

        text = soup.get_text(separator="\n")
        # Collapse excessive blank lines that survive tag removal
        import re
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return text, {"title": title, "h1": heading}
