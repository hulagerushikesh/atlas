"""
Integration-style tests for the FastAPI routes.

We construct the app without the lifespan (so no real Qdrant/Redis/OpenAI
connections) and inject a mock AppState directly onto app.state. This gives us
realistic HTTP-layer testing (request parsing, status codes, response schemas)
without any network I/O.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from atlas.api.cache import QueryCache
from atlas.api.dependencies import AppState
from atlas.api.schemas import QueryResponse
from atlas.orchestration.faithfulness import FaithfulnessResult
from atlas.orchestration.generator import CitationRef, GeneratorResult
from atlas.orchestration.pipeline import PipelineResult


# ── Fixtures ──────────────────────────────────────────────────────────────────

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
    return result


@pytest.fixture
def client() -> TestClient:
    """Build the app without lifespan and inject a mock state."""
    from fastapi import FastAPI
    from atlas.api.routes import health, ingest, query, metrics_route
    from atlas.api.middleware.tracing import TracingMiddleware

    app = FastAPI()
    app.add_middleware(TracingMiddleware)
    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(query.router)
    app.include_router(metrics_route.router)

    # Mock pipeline
    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value=_make_pipeline_result())
    mock_pipeline._router = MagicMock()
    mock_pipeline._router.classify = AsyncMock(return_value="simple")
    mock_pipeline._decomposer = MagicMock()
    mock_pipeline._retrieve_all = AsyncMock(return_value=[])
    mock_pipeline._generator = MagicMock()

    async def _gen_stream(*args, **kwargs):  # type: ignore[return]
        yield "Hello "
        yield "world"

    mock_pipeline._generator.stream = _gen_stream

    app.state.atlas = AppState(
        pipeline=mock_pipeline,
        indexer=MagicMock(),
        cache=QueryCache(max_memory_size=10),
        embedding_model="text-embedding-3-small",
    )

    return TestClient(app, raise_server_exceptions=False)


# ── /query ────────────────────────────────────────────────────────────────────

class TestQueryRoute:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.post("/query", json={"query": "What is Atlas?"})
        assert resp.status_code == 200

    def test_response_has_answer(self, client: TestClient) -> None:
        resp = client.post("/query", json={"query": "What is Atlas?"})
        body = resp.json()
        assert "answer" in body
        assert body["answer"] == "The answer [1]."

    def test_response_schema_valid(self, client: TestClient) -> None:
        resp = client.post("/query", json={"query": "What is Atlas?"})
        # Validate against the response schema
        parsed = QueryResponse.model_validate(resp.json())
        assert parsed.classification == "simple"

    def test_request_id_header_present(self, client: TestClient) -> None:
        resp = client.post("/query", json={"query": "test"})
        assert "X-Request-ID" in resp.headers

    def test_response_time_header_present(self, client: TestClient) -> None:
        resp = client.post("/query", json={"query": "test"})
        assert "X-Response-Time-Ms" in resp.headers

    def test_empty_query_rejected(self, client: TestClient) -> None:
        resp = client.post("/query", json={"query": ""})
        assert resp.status_code == 422

    def test_cache_hit_returns_cached_true(self, client: TestClient) -> None:
        import json
        from atlas.ingestion.hashing import hash_text
        # Pre-populate the L1 memory cache directly (no event loop needed)
        cache: QueryCache = client.app.state.atlas.cache
        payload = {
            "query": "cached question",
            "answer": "cached answer",
            "classification": "simple",
            "citations": [],
            "is_faithful": True,
            "faithfulness_score": 0.9,
            "retrieved_chunk_ids": [],
            "timings": {"total_ms": 1.0},
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0,
                            "total_tokens": 0, "estimated_cost_usd": 0.0},
            "cached": False,
        }
        key = cache._make_key("cached question")
        cache._mem[key] = json.dumps(payload)

        resp = client.post("/query", json={"query": "cached question"})
        assert resp.status_code == 200
        assert resp.json()["cached"] is True

    def test_streaming_returns_event_stream(self, client: TestClient) -> None:
        resp = client.post("/query", json={"query": "stream this", "stream": True})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]


# ── /ingest ───────────────────────────────────────────────────────────────────

class TestIngestRoute:
    def test_path_not_found_returns_404(self, client: TestClient) -> None:
        resp = client.post("/ingest", json={"path": "/nonexistent/path/xyz"})
        assert resp.status_code == 404

    def test_valid_path_returns_200(self, client: TestClient, tmp_path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello world")

        # Mock the indexer to return an IndexResult
        from atlas.ingestion.indexer import IndexResult
        mock_result = IndexResult()
        mock_result.documents_processed = 1
        mock_result.documents_skipped = 0
        mock_result.chunks_indexed = 3
        mock_result.total_tokens = 100
        client.app.state.atlas.indexer.index_path = AsyncMock(return_value=mock_result)

        resp = client.post("/ingest", json={"path": str(f)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["documents_processed"] == 1
        assert body["chunks_indexed"] == 3


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealthRoute:
    def test_health_returns_200_or_503(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code in (200, 503)

    def test_health_has_version(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert "version" in resp.json()

    def test_health_has_status(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.json()["status"] in ("ok", "degraded", "down")


# ── /metrics ──────────────────────────────────────────────────────────────────

class TestMetricsRoute:
    def test_metrics_returns_200(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type(self, client: TestClient) -> None:
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]
