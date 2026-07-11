"""
Document loader implementations and auto-detection registry.

Import the registry for the normal use case:
    from atlas.ingestion.loaders import get_loader
"""

from atlas.ingestion.loaders.html import HTMLLoader
from atlas.ingestion.loaders.markdown import MarkdownLoader
from atlas.ingestion.loaders.pdf import PDFLoader
from atlas.ingestion.loaders.registry import LoaderRegistry, get_loader
from atlas.ingestion.loaders.text import TextLoader

__all__ = [
    "PDFLoader",
    "MarkdownLoader",
    "TextLoader",
    "HTMLLoader",
    "LoaderRegistry",
    "get_loader",
]
