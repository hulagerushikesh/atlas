"""
Shared route-test fixtures.

The app is built without its lifespan (no real Qdrant/Redis/OpenAI) and a
mock AppState is injected onto app.state, so tests exercise the HTTP layer
— parsing, status codes, schemas — without network I/O.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from atlas.api.cache import QueryCache
from atlas.api.dependencies import AppState
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.faithfulness import FaithfulnessResult
from atlas.orchestration.generator import CitationRef, GeneratorResult
from atlas.orchestration.pipeline import PipelineResult, RetrievalPass


def _make_pipeline_result(answer: str = "The answer [1].", faithful: bool = True) -> PipelineResult:
    result = MagicMock(spec=PipelineResult)
    result.query = "What is Atlas?"
    result.classification = "simple"
    result.sub_queries = ["What is Atlas?"]
    result.retrieved_chunks = []
    result.grader_score = 0.9
    result.grader_retries = 0
    result.generation = GeneratorResult(
        answer=answer,
        citations={1: CitationRef(chunk_id="c1", source="doc.md", page_number=None)},
    )
    result.faithfulness = FaithfulnessResult(
        score=0.95 if faithful else 0.3,
        is_faithful=faithful,
        summary="ok",
    )
    result.answer = answer
    result.is_faithful = faithful
    result.evidence = []
    result.stage_ms = {"routing": 12.0, "retrieval": 80.0, "generation": 400.0}
    return result


def _evidence_chunk(cid: str, content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, content=content, score=0.0,
        metadata=ChunkMetadata(
            doc_id="d1", source="doc.md", doc_type=DocumentType.MARKDOWN,
            chunk_index=3, start_char=0, end_char=10,
        ),
    )


@pytest.fixture
def client() -> TestClient:
    """Build the app without lifespan and inject a mock state."""
    from fastapi import FastAPI

    from atlas.api.middleware.tracing import TracingMiddleware
    from atlas.api.routes import health, ingest, metrics_route, namespaces, query

    app = FastAPI()
    app.add_middleware(TracingMiddleware)
    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(query.router)
    app.include_router(metrics_route.router)
    app.include_router(namespaces.router)

    # Mock pipeline
    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value=_make_pipeline_result())
    mock_pipeline._router = MagicMock()
    mock_pipeline._router.classify = AsyncMock(return_value="simple")
    mock_pipeline._decomposer = MagicMock()
    mock_pipeline._retrieve_all = AsyncMock(return_value=RetrievalPass(chunks=[], evidence=[]))
    mock_pipeline._generator = MagicMock()

    async def _gen_stream(*args, **kwargs):  # type: ignore[return]
        yield "Hello "
        yield "world"

    mock_pipeline._generator.stream = _gen_stream

    mock_indexer = MagicMock()

    # Build a mock NamespaceRegistry that returns the mocked pipeline+indexer
    from atlas.api.namespaces import NamespaceComponents
    mock_ns = MagicMock(spec=NamespaceComponents)
    mock_ns.pipeline = mock_pipeline
    mock_ns.indexer = mock_indexer
    mock_ns.sparse_index = MagicMock()
    mock_ns.sparse_index.sources.return_value = [
        {"source": "tutorial/first-steps.md", "doc_type": "markdown", "chunks": 12},
        {"source": "reference/depends.md", "doc_type": "markdown", "chunks": 7},
    ]

    from atlas.api.namespaces import NamespaceRegistry
    mock_registry = MagicMock(spec=NamespaceRegistry)
    mock_registry.get.return_value = mock_ns

    app.state.atlas = AppState(
        registry=mock_registry,
        cache=QueryCache(max_memory_size=10),
        embedding_model="text-embedding-3-small",
    )

    return TestClient(app, raise_server_exceptions=False)


