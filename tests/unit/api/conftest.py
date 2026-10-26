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
from atlas.config import GENERIC_DOMAIN, RouterConfig, Settings
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
    result.hypotheses = []
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

    # Awaitable, because `MagicMock()._grader.grade(...)` is not: the streaming
    # path awaits it at stage 4, so with an auto-mock here every streamed
    # request died there and became an `error` event. Tests that only read the
    # early stages still passed, which is how it survived -- a fixture that
    # cannot reach `done` makes every success-path assertion below it a
    # comment. Tests that want the failure opt in by setting a side_effect.
    mock_pipeline._grader = MagicMock()
    mock_pipeline._grader.grade = AsyncMock(return_value=(True, 0.9, "sufficient"))

    async def _gen_stream(*args, **kwargs):  # type: ignore[return]
        yield "Hello "
        yield "world"

    mock_pipeline._generator.stream = _gen_stream

    # Same trap as `_grader` above, one stage later: the streaming path now
    # awaits the faithfulness check after `done`, and an auto-mock's `check`
    # returns a MagicMock that cannot be awaited. The route catches that and
    # reports "no verdict", so every verdict assertion would pass against a
    # check that never ran. `enabled` is explicit for the same reason -- an
    # auto-mock attribute is truthy, which is the right answer by accident.
    mock_pipeline._faithfulness = MagicMock()
    mock_pipeline._faithfulness.enabled = True
    mock_pipeline._faithfulness.check = AsyncMock(
        return_value=FaithfulnessResult(score=0.95, is_faithful=True, summary="ok")
    )

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
    # Agrees with the sparse rows above (12 + 7) so the default fixture is a
    # consistent namespace; mismatch tests override it.
    mock_registry.dense_chunk_count = AsyncMock(return_value=19)
    # The ingest routes ask the registry whether a namespace is described
    # before writing to it, and the sources route reports the same answer.
    # On a bare `MagicMock` that question returns a truthy mock, which would
    # 409 every ingest test in the suite. Real config, built explicitly
    # rather than from `Settings()` -- that reads the developer's .env, where
    # ROUTER_DOMAIN *is* set, so the fixture would describe `default` on this
    # machine and not in CI. The contentless domain here means "an
    # undescribed corpus"; tests that want a described one say so.
    mock_registry.settings = MagicMock(spec=Settings)
    mock_registry.settings.router = RouterConfig(
        domain=GENERIC_DOMAIN, domain_namespace="default"
    )

    app.state.atlas = AppState(
        registry=mock_registry,
        cache=QueryCache(max_memory_size=10),
        embedding_model="text-embedding-3-small",
    )

    return TestClient(app, raise_server_exceptions=False)


