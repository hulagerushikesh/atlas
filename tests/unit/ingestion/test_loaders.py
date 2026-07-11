"""
Tests for document loaders.

All file I/O uses tmp_path so tests are hermetic and leave no artifacts.
External library calls (pypdf, bs4) run against real in-memory content —
no mocking needed because loaders are pure transformations with no network I/O.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.ingestion.loaders import HTMLLoader, MarkdownLoader, TextLoader, get_loader
from atlas.ingestion.loaders.registry import LoaderRegistry
from atlas.interfaces.document import DocumentType


class TestMarkdownLoader:
    @pytest.mark.asyncio
    async def test_loads_content(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("# Hello\n\nWorld paragraph.")
        docs = await MarkdownLoader().load(f)
        assert len(docs) == 1
        assert "Hello" in docs[0].content

    @pytest.mark.asyncio
    async def test_sets_doc_type(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("content")
        docs = await MarkdownLoader().load(f)
        assert docs[0].doc_type == DocumentType.MARKDOWN

    @pytest.mark.asyncio
    async def test_content_hash_populated(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("content")
        docs = await MarkdownLoader().load(f)
        assert docs[0].content_hash != ""

    @pytest.mark.asyncio
    async def test_same_content_same_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("same content")
        docs1 = await MarkdownLoader().load(f)
        docs2 = await MarkdownLoader().load(f)
        assert docs1[0].content_hash == docs2[0].content_hash

    @pytest.mark.asyncio
    async def test_changed_content_changed_hash(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("version 1")
        docs1 = await MarkdownLoader().load(f)
        f.write_text("version 2")
        docs2 = await MarkdownLoader().load(f)
        assert docs1[0].content_hash != docs2[0].content_hash

    def test_supported_extensions(self) -> None:
        loader = MarkdownLoader()
        assert ".md" in loader.supported_extensions
        assert ".markdown" in loader.supported_extensions


class TestTextLoader:
    @pytest.mark.asyncio
    async def test_loads_plain_text(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.txt"
        f.write_text("plain text content")
        docs = await TextLoader().load(f)
        assert docs[0].content == "plain text content"
        assert docs[0].doc_type == DocumentType.TEXT

    def test_supported_extensions(self) -> None:
        assert ".txt" in TextLoader().supported_extensions
        assert ".rst" in TextLoader().supported_extensions


class TestHTMLLoader:
    @pytest.mark.asyncio
    async def test_strips_script_tags(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.html"
        f.write_text("<html><body><script>evil()</script><p>Good content</p></body></html>")
        docs = await HTMLLoader().load(f)
        assert "evil" not in docs[0].content
        assert "Good content" in docs[0].content

    @pytest.mark.asyncio
    async def test_extracts_title(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.html"
        f.write_text("<html><head><title>My Title</title></head><body><p>text</p></body></html>")
        docs = await HTMLLoader().load(f)
        assert docs[0].metadata["title"] == "My Title"

    @pytest.mark.asyncio
    async def test_doc_type_is_html(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.html"
        f.write_text("<html><body>hi</body></html>")
        docs = await HTMLLoader().load(f)
        assert docs[0].doc_type == DocumentType.HTML


class TestLoaderRegistry:
    def test_get_loader_by_extension(self, tmp_path: Path) -> None:
        md_file = tmp_path / "test.md"
        md_file.touch()
        loader = get_loader(md_file)
        assert isinstance(loader, MarkdownLoader)

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "test.xyz"
        f.touch()
        with pytest.raises(ValueError, match="No loader registered"):
            get_loader(f)

    def test_custom_loader_registration(self, tmp_path: Path) -> None:
        registry = LoaderRegistry()
        txt_loader = TextLoader()
        # Override .txt with the same loader (harmless, tests register())
        registry.register(txt_loader)
        f = tmp_path / "test.txt"
        f.touch()
        assert registry.get(f) is txt_loader
