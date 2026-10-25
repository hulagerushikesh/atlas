"""
What a /query request reports, and is charged, for the tokens it spent.

Until 2026-09-28 both numbers came from the generation call alone. That was
described in the route's docstring as a reporting gap, but the same figure is
what `spend.add()` charges the daily cap — so the cap was admitting roughly
twice the spend it was configured for. These tests pin the whole request.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog.testing
from fastapi.testclient import TestClient

from atlas.api.middleware.metrics_mw import COST_USD, TOKEN_USAGE
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


class TestStreamingFailures:
    """An exception after the first byte cannot become a 500 — the status line
    is already sent. It used to end the body mid-event instead, which every
    layer read as a completed stream: the console's `for await` simply stopped,
    no error was thrown, no `done` arrived, and the spinner ran for ever."""

    @staticmethod
    def _events(resp: object) -> list[dict]:
        out = []
        for line in resp.iter_lines():  # type: ignore[attr-defined]
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                out.append({"type": "[DONE]"})
            else:
                out.append(json.loads(payload))
        return out

    def _break_at_grading(self, client: TestClient) -> MagicMock:
        state = client.app.state.atlas
        pipeline = state.registry.get("default").pipeline
        pipeline._grader.grade = AsyncMock(side_effect=RuntimeError("qdrant went away"))
        return state

    def test_a_mid_stream_failure_becomes_an_error_event(self, client: TestClient) -> None:
        self._break_at_grading(client)

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            events = self._events(resp)

        assert resp.status_code == 200  # the status line went out long ago
        errors = [e for e in events if e["type"] == "error"]
        assert len(errors) == 1
        assert "Atlas failed to answer this query" in errors[0]["error"]

    def test_the_error_event_does_not_leak_the_exception(
        self, client: TestClient
    ) -> None:
        # `str(exc)` on this pipeline is where the Qdrant URL, the collection
        # name and the upstream model id surface. It goes to the log, which
        # carries the same request id, and not to the wire.
        self._break_at_grading(client)

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            events = self._events(resp)

        [error] = [e for e in events if e["type"] == "error"]
        assert "qdrant went away" not in json.dumps(error)
        assert error["request_id"]
        assert resp.headers["X-Request-ID"] == error["request_id"]

    def test_the_500_does_not_leak_the_exception_either(
        self, client: TestClient
    ) -> None:
        # Both paths, one message. The streaming event used to copy the 500's
        # `str(exc)` deliberately, for consistency — so fixing one without
        # the other would restore exactly the inconsistency that argued for
        # the leak in the first place.
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline.run = AsyncMock(side_effect=RuntimeError("qdrant went away"))

        resp = client.post("/query", json={"query": "q", "stream": False})

        assert resp.status_code == 500
        assert "qdrant went away" not in resp.text
        assert resp.headers["X-Request-ID"] in resp.json()["detail"]

    def test_the_error_event_names_the_stage_that_broke(self, client: TestClient) -> None:
        self._break_at_grading(client)

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            events = self._events(resp)

        assert [e for e in events if e["type"] == "error"][0]["stage"] == "grading"

    def test_a_failed_stream_still_ends_with_the_done_sentinel(
        self, client: TestClient
    ) -> None:
        # The sentinel is what lets a reader tell "finished" from "socket
        # closed", which is the whole bug.
        self._break_at_grading(client)

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            events = self._events(resp)

        assert events[-1]["type"] == "[DONE]"

    def test_a_successful_stream_also_ends_with_the_sentinel(
        self, client: TestClient
    ) -> None:
        # It always did on the out-of-scope branch and never did on the path
        # that streams an answer.
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline._grader.grade = AsyncMock(return_value=(True, 0.9, "q"))

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            events = self._events(resp)

        assert events[-1]["type"] == "[DONE]"
        # `done` is no longer the penultimate event -- the faithfulness
        # verdict is sent after it, once the answer is already on screen.
        # What this test is about is that a success ends with an ending at
        # all, so it asserts the sentinel closes a stream that announced one.
        assert "done" in [e["type"] for e in events]

    def test_a_failed_stream_is_charged_for_what_it_already_spent(
        self, client: TestClient
    ) -> None:
        """The non-streaming path was fixed for this on 2026-09-28 and the
        streaming one kept the hole: a stream that dies at generation has
        already paid for routing, embedding, retrieval and grading."""
        state = self._break_at_grading(client)
        pipeline = state.registry.get("default").pipeline
        provider = UsageMeter()
        original = pipeline._router.classify

        async def classify(query: str) -> str:
            provider.record("gpt-4o-mini", prompt_tokens=80_000, completion_tokens=10)
            return await original(query)

        pipeline._router.classify = classify
        state.spend.add = AsyncMock()

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            list(resp.iter_lines())

        state.spend.add.assert_awaited_once()
        assert state.spend.add.await_args.args[0] > 0

    def test_the_error_event_arrives_after_the_stages_that_did_work(
        self, client: TestClient
    ) -> None:
        # A client that has already rendered routing and retrieval should not
        # have them rolled back; the error is an ending, not a replacement.
        self._break_at_grading(client)

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            events = self._events(resp)

        names = [e.get("name") for e in events if e["type"] == "stage"]
        assert "routing" in names and "retrieval" in names
        assert events.index([e for e in events if e["type"] == "error"][0]) > 0

    def test_no_done_event_is_emitted_when_the_stream_fails(
        self, client: TestClient
    ) -> None:
        # `done` carries citations and a faithfulness verdict. Sending one
        # after a failure would tell the client the answer is complete.
        self._break_at_grading(client)

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            events = self._events(resp)

        assert not [e for e in events if e["type"] == "done"]


class TestTheCompletionLogCarriesTheCostOfTheQuery:
    """A sum cannot be turned back into a distribution.

    On 2026-10-22 `cost / query` had to be answered from the Firestore usage
    counters, which store totals per key. That yields a mean over n=34 and no
    percentile at all, while the ceiling in BUDGET.md is a per-query one. The
    tokens and the cost were in the response body and in two Prometheus
    counters, and in neither case per query. One structured log line per query
    is what makes a p95 recoverable later without paying for the queries
    again, so these fields are part of the contract, not decoration.
    """

    @staticmethod
    def _complete(logs: list[dict[str, object]]) -> dict[str, object]:
        events = [entry for entry in logs if entry.get("event") == "query_complete"]
        assert len(events) == 1, [entry.get("event") for entry in logs]
        return events[0]

    def test_it_logs_the_tokens_and_the_cost(self, client: TestClient) -> None:
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        _bill(pipeline, **{"gpt-4o-mini": (1000, 100)})

        with structlog.testing.capture_logs() as logs:
            body = client.post("/query", json={"query": "q"}).json()

        logged = self._complete(logs)
        assert logged["prompt_tokens"] == body["token_usage"]["prompt_tokens"]
        assert logged["completion_tokens"] == body["token_usage"]["completion_tokens"]
        assert logged["cost_usd"] == body["token_usage"]["estimated_cost_usd"]

    def test_the_logged_cost_is_not_zero_for_a_query_that_spent(
        self, client: TestClient
    ) -> None:
        # A silent zero here would read as a free query and drag any mean
        # computed from these lines downwards, which is the exact failure the
        # n=1 figure already had in the other direction.
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        _bill(pipeline, **{"gpt-4o-mini": (1000, 100)})

        with structlog.testing.capture_logs() as logs:
            client.post("/query", json={"query": "q"})

        assert self._complete(logs)["cost_usd"] > 0


class TestAStreamedQueryIsVisibleToEveryUsageSink:
    """Until 2026-10-23 a streamed query reached the daily cap and nothing else.

    `COST_USD`, `TOKEN_USAGE` and `log_usage` were incremented on the
    non-streaming path only. The cap being correct is why this never showed
    up as money going missing; what it produced instead was a `cost / query`
    mean silently computed over the non-streaming subset, and `/metrics`
    under-reporting spend by however much of the traffic streamed. One
    streamed query existed in the first 90 days, so the error was invisible
    — and the console is the streaming client, so it would not have stayed
    invisible.
    """

    @staticmethod
    def _stream(client: TestClient) -> None:
        state = client.app.state.atlas
        pipeline = state.registry.get("default").pipeline
        provider = UsageMeter()
        original = pipeline._router.classify

        async def classify(query: str) -> str:
            provider.record("gpt-4o-mini", prompt_tokens=90_000, completion_tokens=10)
            return await original(query)

        pipeline._router.classify = classify
        pipeline._grader.grade = AsyncMock(return_value=(True, 0.9, "q"))
        state.spend.add = AsyncMock()

        with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
            list(resp.iter_lines())

    def test_it_increments_the_cost_counter_metrics_exposes(
        self, client: TestClient
    ) -> None:
        before = COST_USD._value.get()
        self._stream(client)
        assert COST_USD._value.get() > before

    def test_it_increments_the_token_counter_metrics_exposes(
        self, client: TestClient
    ) -> None:
        before = TOKEN_USAGE.labels(model="gpt-4o-mini", type="prompt")._value.get()
        self._stream(client)
        after = TOKEN_USAGE.labels(model="gpt-4o-mini", type="prompt")._value.get()
        assert after - before >= 90_000

    def test_it_routes_its_spend_through_the_one_function_that_feeds_all_four(
        self, client: TestClient, monkeypatch: object
    ) -> None:
        # The per-key sink cannot be reached through the route here: auth is
        # disabled in this fixture, so `request.state.api_key_id` is never
        # set and `_charge` correctly skips `log_usage`. What the route is
        # responsible for is calling `_charge` at all, and handing it the
        # key id and namespace — that is what is asserted here. That
        # `_charge` then writes the per-key record is pinned directly below,
        # in TestChargeWritesThePerKeyRecord.
        from atlas.api.routes import query as query_route

        calls: list[dict[str, object]] = []
        original = query_route._charge

        async def spy(usage: object, spend: object, **kwargs: object) -> float:
            calls.append(kwargs)
            return await original(usage, spend, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(query_route, "_charge", spy)  # type: ignore[attr-defined]
        self._stream(client)

        assert len(calls) == 1, calls
        assert calls[0]["namespace"] == "default"
        assert "api_key_id" in calls[0]

    def test_it_logs_query_complete_under_the_same_event_name(
        self, client: TestClient
    ) -> None:
        # One event name across both paths, because a p95 of cost / query
        # mined from these lines has to cover every query. `stream` tells
        # them apart without splitting the population.
        with structlog.testing.capture_logs() as logs:
            self._stream(client)

        done = [e for e in logs if e.get("event") == "query_complete"]
        assert len(done) == 1, [e.get("event") for e in logs]
        assert done[0]["stream"] is True
        assert done[0]["failed"] is False
        assert int(done[0]["prompt_tokens"]) >= 90_000  # type: ignore[arg-type]
        assert float(done[0]["cost_usd"]) > 0  # type: ignore[arg-type]


class TestChargeWritesThePerKeyRecord:
    """`_charge` is the only writer of the counters BUDGET.md reads.

    No test on either path had ever asserted that the route writes a per-key
    usage record — the fixture disables auth, so `api_key_id` is None and the
    write is skipped. `cost / query` is computed from exactly these records,
    so the sink that produces them is pinned here directly instead.
    """

    @staticmethod
    def _meter() -> UsageMeter:
        meter = UsageMeter()
        meter.record("gpt-4o-mini", prompt_tokens=1000, completion_tokens=100)
        meter.record("embed-1", kind="embedding", prompt_tokens=12)
        return meter

    @pytest.mark.asyncio
    async def test_it_writes_one_record_with_the_tokens_the_request_spent(
        self, monkeypatch: object
    ) -> None:
        from atlas.api import auth as _auth
        from atlas.api.routes import query as query_route

        recorded: list[dict[str, object]] = []

        async def fake_log_usage(**kwargs: object) -> None:
            recorded.append(kwargs)

        monkeypatch.setattr(_auth, "log_usage", fake_log_usage)  # type: ignore[attr-defined]
        await query_route._charge(
            self._meter(), None, api_key_id="k1", namespace="docs", latency_ms=42.0
        )
        await asyncio.sleep(0)  # the write is fire-and-forget

        assert len(recorded) == 1, recorded
        assert recorded[0]["api_key_id"] == "k1"
        assert recorded[0]["namespace"] == "docs"
        # 1000 chat prompt + 12 embedding; embeddings are flattened into
        # prompt_tokens, exactly as the response schema does it.
        assert recorded[0]["prompt_tokens"] == 1012
        assert recorded[0]["completion_tokens"] == 100
        assert recorded[0]["cache_hit"] is False

    @pytest.mark.asyncio
    async def test_it_writes_nothing_when_there_is_no_key_to_attribute_it_to(
        self, monkeypatch: object
    ) -> None:
        from atlas.api import auth as _auth
        from atlas.api.routes import query as query_route

        recorded: list[object] = []

        async def fake_log_usage(**kwargs: object) -> None:
            recorded.append(kwargs)

        monkeypatch.setattr(_auth, "log_usage", fake_log_usage)  # type: ignore[attr-defined]
        await query_route._charge(
            self._meter(), None, api_key_id=None, namespace="default", latency_ms=1.0
        )
        await asyncio.sleep(0)

        assert recorded == []

    @pytest.mark.asyncio
    async def test_a_request_that_spent_nothing_charges_nothing(self) -> None:
        # A cache hit reaches neither call site, but an out-of-scope refusal
        # that never called a model does. Incrementing a cost counter by zero
        # is harmless; writing a usage record for it would inflate the query
        # count that cost / query divides by.
        spend = AsyncMock()
        from atlas.api.routes import query as query_route

        cost = await query_route._charge(
            UsageMeter(), spend, api_key_id="k1", namespace="default", latency_ms=1.0
        )

        assert cost == 0.0
        spend.add.assert_not_awaited()


class _AttributeTo:
    """Pure-ASGI middleware that sets what the auth middleware would set.

    `conftest`'s app has no `APIKeyMiddleware`, so `request.state.api_key_id`
    is never set and every branch guarded on it is dead in the route tests.
    That is the gap `ed9dbd0` shipped into: it left a second `log_usage`
    call beside the one `_charge` makes, referencing an `_auth` name bound
    only inside the cache-hit branch, and 773 tests passed over it because
    none of them ever reached the branch.

    `BaseHTTPMiddleware` cannot be used for this — it re-dispatches the
    request in its own task and breaks the streaming route. Writing into
    `scope["state"]` is what `Request.state` reads, so this is the same
    attribution the real middleware performs, with none of the machinery.
    """

    def __init__(self, app: object, key_id: str = "k-test") -> None:
        self.app, self.key_id = app, key_id

    async def __call__(self, scope: dict, receive: object, send: object) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["api_key_id"] = self.key_id
        await self.app(scope, receive, send)  # type: ignore[operator]


class TestAnAttributedQueryIsCountedOnceAndDoesNotCrash:
    """The per-key counters are what BUDGET.md's `cost / query` is computed
    from, so "counted" has to mean counted exactly once."""

    @staticmethod
    def _records(client: TestClient, monkeypatch: object, **body: object) -> list[dict]:
        from atlas.api import auth as _auth

        calls: list[dict] = []

        async def spy(**kw: object) -> None:
            calls.append(kw)

        monkeypatch.setattr(_auth, "log_usage", spy)  # type: ignore[attr-defined]
        client.app.add_middleware(_AttributeTo)
        state = client.app.state.atlas
        state.spend.add = AsyncMock()

        # `_charge` returns before any sink when the request spent nothing,
        # and the mock pipeline spends nothing, so the query has to be made
        # to cost something before the per-key write is on the path at all.
        # The standard path calls `pipeline.run`, not the stages, so the
        # spend has to be recorded there — recording into a fresh meter is
        # enough, because `record` also writes to whatever `usage_scope` is
        # active, which is the request's.
        pipeline = state.registry.get("default").pipeline
        original_run = pipeline.run

        async def run(*args: object, **kw: object) -> object:
            UsageMeter().record("gpt-4o-mini", prompt_tokens=1200, completion_tokens=40)
            return await original_run(*args, **kw)

        pipeline.run = run
        payload = {"query": "What is Atlas?"}
        payload.update(body)  # type: ignore[arg-type]
        resp = client.post("/query", json=payload)
        assert resp.status_code == 200, resp.text
        return calls

    def test_the_standard_path_does_not_raise_for_an_authenticated_caller(
        self, client: TestClient, monkeypatch: object
    ) -> None:
        # Verbatim the bug in ed9dbd0: UnboundLocalError on `_auth`, on
        # every authenticated cache miss — which is every real query on
        # this path. Unpushed and undeployed when it was found.
        self._records(client, monkeypatch)

    def test_it_writes_exactly_one_per_key_record(
        self, client: TestClient, monkeypatch: object
    ) -> None:
        calls = self._records(client, monkeypatch)
        assert len(calls) == 1, calls
        assert calls[0]["api_key_id"] == "k-test"
        assert calls[0]["cache_hit"] is False

    def test_the_record_carries_the_tokens_the_response_reported(
        self, client: TestClient, monkeypatch: object
    ) -> None:
        # A double write was invisible in the totals precisely because both
        # copies were plausible; pinning the figure to the response body is
        # what makes a second one detectable.
        calls = self._records(client, monkeypatch)
        assert calls[0]["prompt_tokens"] == 1200
        assert calls[0]["completion_tokens"] == 40
