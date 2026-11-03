"""
The cache on the streaming path: that it is written, replayed, and refused.

Until 2026-11-03 `/query` with `stream: true` neither read the cache nor wrote
it, on the stated grounds that caching a stream means buffering it. The console
streams by default, so that exemption was not narrow — it meant no real query
ever touched the cache. The first outside user's session recorded zero cache
hits across five queries, which reads as a broken cache and was a cache nothing
consulted: every repeat re-ran the full paid pipeline.

What is pinned here is the whole shape of the fix, because the cheap version of
it is wrong in a way nothing would notice. A hit could return the answer in one
event and be "cached"; the reader would then lose the stage strip, the evidence
trail and the verdict badge on the second ask — a trust instrument that goes
blank when you repeat yourself. So a hit replays the same event sequence a live
run emits, and these tests compare the two rather than checking a flag.

The refusals matter as much as the hits. An entry stored from a stream that
died mid-answer, or one whose faithfulness judge fell over, would be served for
the rest of the TTL: the first as a truncated answer, the second as a
permanent "unchecked" on an answer that was never actually in doubt.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from atlas.api.cache import QueryCache
from atlas.api.schemas import QueryResponse


@pytest.fixture(autouse=True)
def eager_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the route's fire-and-forget cache write inline.

    The real `spawn` creates an asyncio task, and under `TestClient` the
    request's loop is torn down as soon as the response body is consumed — so
    whether the write landed before teardown is a race, and a test that polls
    for it is a test that passes on a fast machine.

    Stepping the coroutine once runs it to completion here because
    `QueryCache.set` has no await points when no Redis is configured, which is
    how the test fixture builds it. If that stops being true the `send` returns
    rather than raising `StopIteration`, and the assertion that follows fails
    loudly instead of silently testing nothing.
    """
    def _inline(coro: Any, *, name: str) -> None:
        try:
            coro.send(None)
        except StopIteration:
            return
        raise AssertionError(
            f"background task {name!r} suspended; this shim only runs "
            "coroutines that complete without awaiting"
        )

    monkeypatch.setattr("atlas.api.routes.query.spawn", _inline)


def _events(resp: Any) -> list[dict]:
    out = []
    for line in resp.iter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        out.append({"type": "[DONE]"} if payload == "[DONE]" else json.loads(payload))
    return out


def _stream(client: TestClient, query: str = "q") -> tuple[list[dict], dict[str, str]]:
    with client.stream("POST", "/query", json={"query": query, "stream": True}) as resp:
        return _events(resp), dict(resp.headers)


def _entries(client: TestClient) -> list[dict]:
    cache: QueryCache = client.app.state.atlas.cache
    return [json.loads(v) for v in cache._mem.values()]


class TestAFinishedStreamIsCached:
    def test_the_entry_exists_after_one_streamed_query(self, client: TestClient) -> None:
        assert _entries(client) == [], "fixture cache should start empty"

        _stream(client, "what is atlas")

        [entry] = _entries(client)
        assert entry["answer"] == "Hello world", (
            "the entry has to hold the answer the client was streamed, "
            "reassembled from the deltas"
        )

    def test_the_entry_validates_as_a_query_response(self, client: TestClient) -> None:
        """Shape parity with the non-streaming path, which is what makes one
        cache serve both. A hand-assembled dict passes json.dumps and fails
        `model_validate` an hour later, on a hit, in an unrelated request."""
        _stream(client, "what is atlas")

        [entry] = _entries(client)
        parsed = QueryResponse.model_validate(entry)

        assert parsed.classification == "simple"
        assert parsed.is_faithful is True
        assert parsed.faithfulness_score == 0.95
        assert parsed.cached is False, (
            "stored false and asserted true on the way out — the flag describes "
            "this response, not the entry"
        )

    def test_the_stored_timings_include_the_stages_the_client_measured(
        self, client: TestClient
    ) -> None:
        # The console times generation off its own clock, which is right for a
        # live run and impossible for a replayed one: a cached entry is the
        # only place the number can come from.
        _stream(client, "what is atlas")

        [entry] = _entries(client)
        timings = entry["timings"]
        for stage in ("routing_ms", "retrieval_ms", "grading_ms", "generation_ms",
                      "faithfulness_ms", "total_ms"):
            assert timings[stage] is not None, f"{stage} missing from a cached stream"

    def test_the_key_is_the_one_the_non_streaming_path_uses(
        self, client: TestClient
    ) -> None:
        cache: QueryCache = client.app.state.atlas.cache

        _stream(client, "what is atlas")

        assert cache._make_key("what is atlas", "default") in cache._mem


class TestARepeatIsServedFromTheCache:
    def test_no_model_is_called_on_the_second_identical_question(
        self, client: TestClient
    ) -> None:
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        _stream(client, "what is atlas")
        pipeline._router.classify.reset_mock()
        pipeline._grader.grade.reset_mock()
        pipeline._faithfulness.check.reset_mock()

        _stream(client, "what is atlas")

        assert not pipeline._router.classify.called
        assert not pipeline._grader.grade.called
        assert not pipeline._faithfulness.check.called, (
            "a hit that re-runs the judge is not free, and the judge is the "
            "most expensive call in the request after generation"
        )

    def test_the_hit_does_not_reconcile_the_sparse_index(
        self, client: TestClient
    ) -> None:
        """A hit retrieves nothing, so it does not need the keyword index to be
        current — the same reason the non-streaming path checks the cache before
        the reconcile and before the daily cap."""
        registry = client.app.state.atlas.registry
        _stream(client, "what is atlas")
        registry.reconcile_sparse.reset_mock()

        _stream(client, "what is atlas")

        assert not registry.reconcile_sparse.called

    def test_a_different_question_still_runs_the_pipeline(
        self, client: TestClient
    ) -> None:
        # The key is an exact hash of the lower-cased question, so a *similar*
        # question is a miss by design. Pinned because the opposite — a fuzzy
        # key — would serve one question's answer to another.
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        _stream(client, "what is atlas")
        pipeline._router.classify.reset_mock()

        _stream(client, "what is atlas really")

        assert pipeline._router.classify.called

    def test_the_header_says_which_it_was(self, client: TestClient) -> None:
        _, miss = _stream(client, "what is atlas")
        _, hit = _stream(client, "what is atlas")

        assert miss["x-cache"] == "miss"
        assert hit["x-cache"] == "hit"
        assert hit["x-namespace"] == "default"


class TestTheReplayLooksLikeALiveRun:
    def test_every_stage_a_live_run_announces_is_announced_again(
        self, client: TestClient
    ) -> None:
        live, _ = _stream(client, "what is atlas")
        replay, _ = _stream(client, "what is atlas")

        def stages(events: list[dict]) -> list[tuple[str, str]]:
            return [(e["name"], e["status"]) for e in events if e["type"] == "stage"]

        assert stages(replay) == stages(live), (
            "a cached answer that arrives without its stage strip is an answer "
            "the reader cannot audit"
        )

    def test_the_answer_arrives_as_deltas_a_client_can_concatenate(
        self, client: TestClient
    ) -> None:
        live, _ = _stream(client, "what is atlas")
        replay, _ = _stream(client, "what is atlas")

        def answer(events: list[dict]) -> str:
            return "".join(e["text"] for e in events if e["type"] == "delta")

        assert answer(replay) == answer(live) == "Hello world"

    def test_the_verdict_still_arrives_as_its_own_event(
        self, client: TestClient
    ) -> None:
        # `done` claims nothing even on a replay, where both values are known:
        # one contract for live and replayed streams is worth more than saving
        # an event, and every client reads the verdict from the verdict event.
        _stream(client, "what is atlas")
        replay, _ = _stream(client, "what is atlas")

        [done] = [e for e in replay if e["type"] == "done"]
        [verdict] = [e for e in replay if e["type"] == "verdict"]

        assert done["is_faithful"] is None
        assert done["verdict_pending"] is True
        assert verdict["is_faithful"] is True
        assert verdict["score"] == 0.95

    def test_the_done_event_says_it_came_from_the_cache(
        self, client: TestClient
    ) -> None:
        live, _ = _stream(client, "what is atlas")
        replay, _ = _stream(client, "what is atlas")

        assert [e for e in live if e["type"] == "done"][0].get("cached") is not True
        assert [e for e in replay if e["type"] == "done"][0]["cached"] is True, (
            "a reader has to be able to tell a replayed answer from a fresh "
            "one: it was produced against the corpus as it stood up to an hour "
            "ago"
        )

    def test_the_stream_ends_the_way_the_live_one_does(
        self, client: TestClient
    ) -> None:
        _stream(client, "what is atlas")
        replay, _ = _stream(client, "what is atlas")

        assert replay[-1]["type"] == "[DONE]", (
            "a client that waits for the sentinel would hang for ever without it"
        )

    def test_the_evidence_trail_is_replayed(self, client: TestClient) -> None:
        from atlas.orchestration.pipeline import EvidenceChunk, RetrievalPass
        from tests.unit.api.conftest import _evidence_chunk

        pipeline = client.app.state.atlas.registry.get("default").pipeline
        chunk = _evidence_chunk("c1", "Atlas is a RAG service.")
        pipeline._retrieve_all = AsyncMock(return_value=RetrievalPass(
            chunks=[chunk],
            evidence=[EvidenceChunk(chunk=chunk, scores={"dense": 0.8}, selected=True)],
        ))

        _stream(client, "what is atlas")
        replay, _ = _stream(client, "what is atlas")

        [retrieval] = [e for e in replay
                       if e["type"] == "stage" and e["name"] == "retrieval"
                       and e["status"] == "done"]
        assert [e["chunk_id"] for e in retrieval["evidence"]] == ["c1"]
        assert retrieval["chunks"] == 1


class TestOneEntryServesBothPaths:
    def test_a_streamed_answer_is_returned_to_a_non_streaming_caller(
        self, client: TestClient
    ) -> None:
        """The reason the entry is a `QueryResponse` and not a stream
        transcript. A client that asked a question over SSE and a client that
        asked the same one over JSON are owed the same answer, and the second
        should not pay for it again."""
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        _stream(client, "what is atlas")
        pipeline.run.reset_mock()

        body = client.post("/query", json={"query": "what is atlas"}).json()

        assert body["cached"] is True
        assert body["answer"] == "Hello world"
        assert not pipeline.run.called

    def test_a_non_streamed_answer_is_replayed_to_a_streaming_caller(
        self, client: TestClient
    ) -> None:
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        client.post("/query", json={"query": "what is atlas"})
        pipeline._router.classify.reset_mock()

        replay, headers = _stream(client, "what is atlas")

        assert headers["x-cache"] == "hit"
        assert not pipeline._router.classify.called
        assert "".join(e["text"] for e in replay if e["type"] == "delta") == (
            "The answer [1]."
        )


class TestWhatIsRefusedTheCache:
    def test_a_stream_that_dies_mid_answer_is_not_cached(
        self, client: TestClient
    ) -> None:
        """The case the whole `complete` flag exists for. A truncated answer in
        the cache is worse than no cache: it is served confidently, for an
        hour, to everyone who asks."""
        pipeline = client.app.state.atlas.registry.get("default").pipeline

        async def _half_then_die(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
            yield "Hello "
            raise RuntimeError("upstream died mid-answer")

        pipeline._generator.stream = _half_then_die

        events, _ = _stream(client, "what is atlas")

        assert [e for e in events if e["type"] == "error"], "expected an error event"
        assert _entries(client) == []

    def test_a_failed_faithfulness_judge_is_not_cached(
        self, client: TestClient
    ) -> None:
        """The answer is delivered and kept — a judge that falls over must not
        destroy a finished response. But storing it would serve "unchecked" for
        the rest of the TTL on the strength of one transient failure, and the
        verdict is the one claim this project rests on."""
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline._faithfulness.check = AsyncMock(side_effect=RuntimeError("judge down"))

        events, _ = _stream(client, "what is atlas")

        [verdict] = [e for e in events if e["type"] == "verdict"]
        assert verdict["is_faithful"] is None
        assert "".join(e["text"] for e in events if e["type"] == "delta") == "Hello world"
        assert _entries(client) == [], (
            "an answer whose check failed must be re-checked on the next ask, "
            "not cached as unchecked"
        )

    def test_the_next_ask_after_a_failed_judge_runs_the_check_again(
        self, client: TestClient
    ) -> None:
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline._faithfulness.check = AsyncMock(side_effect=RuntimeError("judge down"))
        _stream(client, "what is atlas")
        pipeline._faithfulness.check.reset_mock()

        _stream(client, "what is atlas")

        assert pipeline._faithfulness.check.called


class TestARefusalIsCachedToo:
    def test_an_out_of_scope_answer_is_stored(self, client: TestClient) -> None:
        # The cheapest entry in the cache and the most repeated question in a
        # demo — "what is the capital of France?" is what people try first —
        # and it still costs a routing call to produce.
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline._router.classify = AsyncMock(return_value="out_of_scope")

        _stream(client, "capital of france")

        [entry] = _entries(client)
        assert entry["classification"] == "out_of_scope"
        assert entry["is_faithful"] is None, (
            "a refusal grounds nothing, so the entry records that nothing was "
            "checked rather than that a check passed"
        )

    def test_the_refusal_is_replayed_as_a_refusal(self, client: TestClient) -> None:
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline._router.classify = AsyncMock(return_value="out_of_scope")
        live, _ = _stream(client, "capital of france")
        replay, headers = _stream(client, "capital of france")

        assert headers["x-cache"] == "hit"
        [live_done] = [e for e in live if e["type"] == "done"]
        [replay_done] = [e for e in replay if e["type"] == "done"]
        assert replay_done["classification"] == "out_of_scope"
        assert replay_done["answer"] == live_done["answer"], (
            "the refusal text is one constant precisely so a replayed refusal "
            "and a live one cannot drift apart"
        )
        assert replay_done["verdict_pending"] is False
        assert not [e for e in replay if e["type"] == "verdict"]
