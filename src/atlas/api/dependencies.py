"""
FastAPI dependency injection for pipeline components.

Design rationale:
    All heavy components (LLM provider, embedder, Qdrant client, BM25 index,
    reranker) are constructed once at startup in the lifespan handler and
    stored on app.state. FastAPI's dependency system then plucks them from
    app.state on each request via these lightweight accessor functions.

    Why app.state over module-level singletons?
      - app.state is request-context-free, so there's no risk of sharing
        state across concurrent requests in ways that cause data races.
      - Tests can swap out components by patching app.state before calling
        the test client — no monkeypatching of module globals.
      - The lifespan handler (in app.py) ensures components are initialised
        before the first request and cleaned up on shutdown.

    AppState is a typed dataclass (not a Pydantic model) because it holds
    live objects that can't be serialised — Pydantic's __init__ would
    attempt validation on them.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from atlas.api.cache import QueryCache
from atlas.ingestion.indexer import DocumentIndexer
from atlas.orchestration.pipeline import RAGPipeline


@dataclass
class AppState:
    """All live components shared across requests."""
    pipeline: RAGPipeline
    indexer: DocumentIndexer
    cache: QueryCache
    embedding_model: str   # surfaced for cost estimation in routes


def get_app_state(request: Request) -> AppState:
    """FastAPI dependency: retrieve the typed app state."""
    return request.app.state.atlas  # type: ignore[attr-defined]


def get_pipeline(request: Request) -> RAGPipeline:
    return get_app_state(request).pipeline


def get_indexer(request: Request) -> DocumentIndexer:
    return get_app_state(request).indexer


def get_cache(request: Request) -> QueryCache:
    return get_app_state(request).cache
