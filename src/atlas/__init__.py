"""
Atlas — production-grade agentic RAG platform.

Package layout:
    atlas.interfaces   — shared ABCs and Pydantic models (no logic here)
    atlas.ingestion    — document loaders, chunkers, dual indexing (Module A)
    atlas.retrieval    — hybrid retrieval + reranking (Module B)
    atlas.orchestration — query routing, decomposition, grading, generation (Module C)
    atlas.evaluation   — metrics, dataset runner, A/B comparison (Module D)
    atlas.api          — FastAPI app, tracing, caching, streaming (Module E)
"""

__version__ = "0.1.0"
