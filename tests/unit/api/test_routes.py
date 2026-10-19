"""
Integration-style tests for the FastAPI routes.

We construct the app without the lifespan (so no real Qdrant/Redis/OpenAI
connections) and inject a mock AppState directly onto app.state. This gives us
realistic HTTP-layer testing (request parsing, status codes, response schemas)
without any network I/O.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from atlas.api.cache import QueryCache
from atlas.api.schemas import QueryResponse
from atlas.orchestration.pipeline import RetrievalPass
from tests.unit.api.conftest import _evidence_chunk, _make_pipeline_result

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
        key = cache._make_key("default:cached question")
        cache._mem[key] = json.dumps(payload)

        resp = client.post("/query", json={"query": "cached question"})
        assert resp.status_code == 200
        assert resp.json()["cached"] is True

    def test_streaming_returns_event_stream(self, client: TestClient) -> None:
        resp = client.post("/query", json={"query": "stream this", "stream": True})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

    def test_stage_timings_populated(self, client: TestClient) -> None:
        """Per-stage ms used to be dropped; only total_ms reached the client."""
        body = client.post("/query", json={"query": "What is Atlas?"}).json()
        t = body["timings"]
        assert t["routing_ms"] == 12.0
        assert t["retrieval_ms"] == 80.0
        assert t["generation_ms"] == 400.0
        assert t["decompose_ms"] is None
        assert "total_ms" in t

    def test_evidence_serialised_with_citation_link(self, client: TestClient) -> None:
        """
        Evidence carries each chunk's score trail and, when the generator
        cited it, its citation number — the join the console needs to
        deep-link a chip to its card.
        """
        from atlas.orchestration.pipeline import EvidenceChunk

        result = _make_pipeline_result()
        result.evidence = [
            EvidenceChunk(
                chunk=_evidence_chunk("c1", "x" * 500),
                scores={"dense": 0.81, "bm25": 12.4, "rrf": 0.0321, "rerank": 0.94},
                selected=True,
            ),
            EvidenceChunk(
                chunk=_evidence_chunk("c9", "cut by reranker"),
                scores={"dense": 0.4, "rrf": 0.01},
                selected=False,
            ),
        ]
        client.app.state.atlas.registry.get.return_value.pipeline.run = AsyncMock(
            return_value=result
        )

        body = client.post("/query", json={"query": "evidence please"}).json()

        cited, cut = body["evidence"]
        assert cited["chunk_id"] == "c1"
        assert cited["citation"] == 1          # generation cites chunk c1 as [1]
        assert cited["selected"] is True
        assert cited["scores"] == {"dense": 0.81, "bm25": 12.4, "rrf": 0.0321, "rerank": 0.94}
        assert cited["start_char"] == 0 and cited["end_char"] == 10
        assert len(cited["excerpt"]) < 500 and cited["excerpt"].endswith("…")
        assert cut["citation"] is None
        assert cut["selected"] is False
        assert "rerank" not in cut["scores"]

    def test_streaming_retrieval_event_carries_evidence(self, client: TestClient) -> None:
        """Evidence must arrive with the retrieval stage, before generation streams."""
        import json

        from atlas.orchestration.pipeline import EvidenceChunk

        pipeline = client.app.state.atlas.registry.get.return_value.pipeline
        pipeline._retrieve_all = AsyncMock(return_value=RetrievalPass(
            chunks=[_evidence_chunk("c1", "streamed chunk")],
            evidence=[EvidenceChunk(
                chunk=_evidence_chunk("c1", "streamed chunk"),
                scores={"dense": 0.7, "rerank": 0.9},
            )],
        ))

        resp = client.post("/query", json={"query": "stream", "stream": True})
        events = [
            json.loads(line[5:])
            for line in resp.text.splitlines()
            if line.startswith("data:") and line != "data: [DONE]"
        ]

        retrieval_done = next(
            e for e in events if e["type"] == "stage"
            and e["name"] == "retrieval" and e["status"] == "done"
        )
        [ev] = retrieval_done["evidence"]
        assert ev["chunk_id"] == "c1"
        assert ev["scores"] == {"dense": 0.7, "rerank": 0.9}
        assert ev["selected"] is True
        # Generation has not run yet at this point, so no citation number.
        assert ev["citation"] is None


# ── /ingest ───────────────────────────────────────────────────────────────────

class TestIngestRoute:
    # These tests are about 404 and 200, not about the ingest root, so each one
    # declares the root it wants. Leaving the fixture unconfined instead would
    # make the default under test differ from the shipped default, which is the
    # one that matters: `/ingest` reads server files and `/query` reads them
    # back out.
    @staticmethod
    def _allow(client: TestClient, root) -> None:  # type: ignore[no-untyped-def]
        from atlas.config import IngestConfig
        client.app.state.atlas.ingest = IngestConfig(root=str(root))

    def test_path_not_found_returns_404(self, client: TestClient, tmp_path) -> None:  # type: ignore[no-untyped-def]
        self._allow(client, tmp_path)
        resp = client.post("/ingest", json={"path": str(tmp_path / "nope.txt")})
        assert resp.status_code == 404

    def test_valid_path_returns_200(self, client: TestClient, tmp_path) -> None:
        self._allow(client, tmp_path)
        f = tmp_path / "test.txt"
        f.write_text("hello world")

        # Mock the indexer to return an IndexResult
        from atlas.ingestion.indexer import IndexResult
        mock_result = IndexResult()
        mock_result.documents_processed = 1
        mock_result.documents_skipped = 0
        mock_result.chunks_indexed = 3
        mock_result.total_tokens = 100
        client.app.state.atlas.registry.get.return_value.indexer.index_path = AsyncMock(
            return_value=mock_result
        )

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


# ── /namespaces/{ns}/sources ──────────────────────────────────────────────────

class TestSourcesRoute:
    def test_lists_sources_with_totals(self, client: TestClient) -> None:
        body = client.get("/namespaces/fastapi/sources").json()
        assert body["namespace"] == "fastapi"
        assert [s["source"] for s in body["sources"]] == [
            "tutorial/first-steps.md", "reference/depends.md",
        ]
        assert body["total_sources"] == 2
        assert body["total_chunks"] == 19

    def test_namespace_without_sparse_index_is_empty(self, client: TestClient) -> None:
        client.app.state.atlas.registry.get.return_value.sparse_index = None
        client.app.state.atlas.registry.dense_chunk_count = AsyncMock(return_value=0)
        body = client.get("/namespaces/bare/sources").json()
        assert body["sources"] == [] and body["total_chunks"] == 0

    def test_agreeing_halves_report_consistent_and_no_warning(
        self, client: TestClient
    ) -> None:
        body = client.get("/namespaces/fastapi/sources").json()
        assert body["dense_chunks"] == 19
        assert body["consistent"] is True
        assert body["warning"] is None

    def test_sparse_only_namespace_is_flagged_not_advertised(
        self, client: TestClient
    ) -> None:
        """
        The shipped bug: the image bakes a sparse index whose collection never
        reached Qdrant, and the console reported its sources as searchable.
        """
        client.app.state.atlas.registry.dense_chunk_count = AsyncMock(return_value=0)
        body = client.get("/namespaces/orphan/sources").json()
        assert body["total_chunks"] == 19 and body["dense_chunks"] == 0
        assert body["consistent"] is False
        assert "19" in body["warning"] and "0" in body["warning"]

    def test_partial_drift_is_flagged(self, client: TestClient) -> None:
        client.app.state.atlas.registry.dense_chunk_count = AsyncMock(return_value=15)
        body = client.get("/namespaces/fastapi/sources").json()
        assert body["consistent"] is False and body["dense_chunks"] == 15

    def test_unreachable_qdrant_is_unknown_not_zero(self, client: TestClient) -> None:
        """None, never 0 — an unreadable count must not read as "empty"."""
        client.app.state.atlas.registry.dense_chunk_count = AsyncMock(return_value=None)
        body = client.get("/namespaces/fastapi/sources").json()
        assert body["dense_chunks"] is None
        assert body["consistent"] is None
        assert "unreachable" in body["warning"]
