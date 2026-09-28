"""
What a /query request reports, and is charged, for the tokens it spent.

Until 2026-09-28 both numbers came from the generation call alone. That was
described in the route's docstring as a reporting gap, but the same figure is
what `spend.add()` charges the daily cap — so the cap was admitting roughly
twice the spend it was configured for. These tests pin the whole request.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from atlas.cost import estimate_usage_cost
from atlas.usage import ModelUsage, UsageMeter


def _bill(pipeline: MagicMock, **calls: tuple[int, int]) -> None:
    """Make the mock pipeline spend tokens the way a real one does: through a
    provider that records into whatever scope is active."""
    provider = UsageMeter()
    original = pipeline.run

    async def run(question: str) -> object:
        for model, (prompt, completion) in calls.items():
            provider.record(model, prompt_tokens=prompt, completion_tokens=completion)
        provider.record("embed-1", kind="embedding", prompt_tokens=12)
        return await original(question)

    pipeline.run = run


class TestQueryTokenUsage:
    def test_counts_every_call_the_request_made(self, client: TestClient) -> None:
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        # A real request: router, grader, generator, faithfulness — not just
        # the generation call.
        _bill(pipeline, **{"chat-1": (4000, 300)})

        usage = client.post("/query", json={"query": "q"}).json()["token_usage"]

        # 4000 prompt + 12 embedding tokens, and the completion.
        assert usage["prompt_tokens"] == 4012
        assert usage["completion_tokens"] == 300
        assert usage["total_tokens"] == 4312

    def test_cost_prices_chat_and_embedding_separately(self, client: TestClient) -> None:
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        _bill(pipeline, **{"gpt-4o-mini": (1000, 100)})

        usage = client.post("/query", json={"query": "q"}).json()["token_usage"]
        expected = estimate_usage_cost({
            "gpt-4o-mini": ModelUsage(kind="chat", calls=1,
                                      prompt_tokens=1000, completion_tokens=100),
            "embed-1": ModelUsage(kind="embedding", calls=1, prompt_tokens=12),
        })
        assert usage["estimated_cost_usd"] == expected

    def test_the_daily_cap_is_charged_what_the_request_cost(
        self, client: TestClient
    ) -> None:
        state = client.app.state.atlas
        _bill(state.registry.get("default").pipeline, **{"gpt-4o-mini": (100_000, 10_000)})
        state.spend.add = AsyncMock()

        response = client.post("/query", json={"query": "q"}).json()

        state.spend.add.assert_awaited_once_with(response["token_usage"]["estimated_cost_usd"])
        assert response["token_usage"]["estimated_cost_usd"] > 0

    def test_a_failed_pipeline_is_still_charged_for_what_it_spent(
        self, client: TestClient
    ) -> None:
        """A cap that only counts successes is one a failing deployment can
        walk straight through."""
        state = client.app.state.atlas
        pipeline = state.registry.get("default").pipeline
        provider = UsageMeter()

        async def run(question: str) -> object:
            provider.record("gpt-4o-mini", prompt_tokens=50_000, completion_tokens=1_000)
            raise RuntimeError("faithfulness check exploded")

        pipeline.run = run
        state.spend.add = AsyncMock()

        assert client.post("/query", json={"query": "q"}).status_code == 500
        state.spend.add.assert_awaited_once()
        assert state.spend.add.await_args.args[0] > 0

    def test_a_cached_answer_costs_nothing(self, client: TestClient) -> None:
        cache = client.app.state.atlas.cache
        cache._mem[cache._make_key("default:free")] = json.dumps({
            "query": "free", "answer": "a", "classification": "simple",
            "citations": [], "is_faithful": True, "faithfulness_score": 1.0,
            "retrieved_chunk_ids": [], "timings": {"total_ms": 1.0},
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0,
                            "total_tokens": 0, "estimated_cost_usd": 0.0},
            "cached": False,
        })
        client.app.state.atlas.spend.add = AsyncMock()

        assert client.post("/query", json={"query": "free"}).json()["cached"] is True
        client.app.state.atlas.spend.add.assert_not_awaited()


class TestStreamingTokenUsage:
    def test_the_stream_charges_for_routing_and_grading_too(
        self, client: TestClient
    ) -> None:
        """The streamed answer itself has no usage block and is approximated
        at ~4 chars/token. Everything before it is measured, and none of it
        used to be counted at all."""
        state = client.app.state.atlas
        pipeline = state.registry.get("default").pipeline
        provider = UsageMeter()
        original = pipeline._router.classify

        async def classify(query: str) -> str:
            provider.record("gpt-4o-mini", prompt_tokens=90_000, completion_tokens=10)
            return await original(query)

        pipeline._router.classify = classify
        # The shared fixture leaves the grader an auto-MagicMock, which is not
        # awaitable — the stream dies at stage 4 before reaching the charge,
        # and no existing test reads far enough down the body to notice.
        pipeline._grader.grade = AsyncMock(return_value=(True, 0.9, "q"))
        state.spend.add = AsyncMock()

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            list(resp.iter_lines())

        state.spend.add.assert_awaited_once()
        # 90k prompt tokens at gpt-4o-mini's $0.15/1M is far more than the
        # few characters of streamed answer could account for.
        assert state.spend.add.await_args.args[0] > 0.01

    def test_an_out_of_scope_stream_still_pays_for_its_routing_call(
        self, client: TestClient
    ) -> None:
        state = client.app.state.atlas
        pipeline = state.registry.get("default").pipeline
        provider = UsageMeter()

        async def classify(query: str) -> str:
            provider.record("gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=0)
            return "out_of_scope"

        pipeline._router.classify = classify
        state.spend.add = AsyncMock()

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            body = "".join(resp.iter_lines())

        assert "out_of_scope" in body
        state.spend.add.assert_awaited_once()
        assert state.spend.add.await_args.args[0] > 0
