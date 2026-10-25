"""
What the SSE `done` event is allowed to claim.

The `done` event used to send `"is_faithful": true` on both the success
branch and the out-of-scope one, while the streaming path ran no check at
all. The console happened to render UNCHECKED because it keys off the absent
score, so the UI was more honest than the API; every other client was told a
never-checked answer had been verified. That field is the one the project's
whole claim rests on, so `done` still reports null -- at the moment it is
sent, nothing has been checked.

What changed on 2026-10-25 is that something is checked afterwards. The
check runs once the answer is fully streamed and arrives as a separate
`verdict` event, so the reader waits for the answer and not for the audit.
`done` carries `verdict_pending` to say whether one is coming. The tests
below pin both halves: that `done` still claims nothing, and that the
verdict actually follows it rather than being asserted into existence.

Also here: the mid-delta failure. `_stream_query` catches an exception after
the first byte and turns it into an `error` event, and that was tested at the
grading boundary -- which happens *before* any answer text is sent. The case
the recovery exists for is the one where deltas are already on the wire, and
nothing exercised it.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


def _events(resp: Any) -> list[dict]:
    out = []
    for line in resp.iter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        out.append({"type": "[DONE]"} if payload == "[DONE]" else json.loads(payload))
    return out


def _stream(client: TestClient, query: str = "q") -> list[dict]:
    with client.stream("POST", "/query", json={"query": query, "stream": True}) as resp:
        return _events(resp)


class TestTheDoneEventClaimsNothingItDidNotCheck:
    def test_the_success_path_reports_unchecked_not_verified(
        self, client: TestClient
    ) -> None:
        [done] = [e for e in _stream(client) if e["type"] == "done"]

        assert done["is_faithful"] is None, (
            "the streaming path runs no faithfulness check, so the only honest "
            "value is null; `true` here is indistinguishable to a client from a "
            "verified answer"
        )

    def test_the_out_of_scope_path_reports_unchecked_too(
        self, client: TestClient
    ) -> None:
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline._router.classify = AsyncMock(return_value="out_of_scope")

        [done] = [e for e in _stream(client) if e["type"] == "done"]

        assert done["classification"] == "out_of_scope"
        assert done["is_faithful"] is None, (
            "a refusal grounds nothing and cites nothing, so there is no check "
            "it passed"
        )

    def test_the_field_is_present_rather_than_omitted(self, client: TestClient) -> None:
        # Null, not missing: a client reading `event.is_faithful` on a dict
        # without the key gets undefined in JS, which is falsey and therefore
        # reads as "not faithful" -- the opposite error to the one being fixed.
        [done] = [e for e in _stream(client) if e["type"] == "done"]

        assert "is_faithful" in done

    def test_the_streamed_answer_still_arrives(self, client: TestClient) -> None:
        # Guard against "fixing" the claim by breaking the path that makes it.
        events = _stream(client)

        assert "".join(e["text"] for e in events if e["type"] == "delta") == "Hello world"
        assert events[-1]["type"] == "[DONE]"


class TestAFailureAfterTheFirstDelta:
    """
    The grading-boundary test breaks the stream before a single token of answer
    has been sent. `_stream_query`'s docstring is about the harder case -- "an
    exception raised after the first byte cannot become a 500" -- and that case
    had no test, so the recovery was only ever proved on the easy side of the
    boundary it is named after.
    """

    @staticmethod
    def _break_mid_delta(client: TestClient) -> None:
        async def _half_a_stream(*args: Any, **kwargs: Any) -> Any:
            yield "Hello "
            raise RuntimeError("upstream died holding the qdrant url")

        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline._generator.stream = _half_a_stream

    def test_the_partial_answer_is_followed_by_an_error_event(
        self, client: TestClient
    ) -> None:
        self._break_mid_delta(client)

        events = _stream(client)

        assert [e["text"] for e in events if e["type"] == "delta"] == ["Hello "]
        [error] = [e for e in events if e["type"] == "error"]
        assert error["stage"] == "generation", (
            "the stage is read back off the `status: start` events, so a break "
            "during generation must name generation and not the last stage that "
            "finished"
        )

    def test_it_still_ends_with_the_sentinel(self, client: TestClient) -> None:
        # Without this a reader cannot tell a truncated answer from a complete
        # one, which is the entire bug the error event exists for.
        self._break_mid_delta(client)

        events = _stream(client)

        assert events[-1]["type"] == "[DONE]"
        assert not [e for e in events if e["type"] == "done"]

    def test_the_partial_failure_leaks_nothing(self, client: TestClient) -> None:
        self._break_mid_delta(client)

        events = _stream(client)

        assert "qdrant url" not in json.dumps(events)


class TestTheVerdictArrivesAfterTheAnswer:
    """
    Stream-then-badge. The check was skipped here on the stated grounds that
    it would mean buffering the answer -- but `full_answer` is already built
    for the citation map, and by the time it exists the reader has the text
    on screen. So the cost of checking is one LLM call and no perceived
    latency, and the streaming path stopped being the dishonest one.
    """

    def test_a_verdict_event_follows_the_done_event(self, client: TestClient) -> None:
        events = _stream(client)
        kinds = [e["type"] for e in events]

        assert "verdict" in kinds, "the check runs after `done`, so its result must be sent"
        assert kinds.index("verdict") > kinds.index("done"), (
            "a verdict before `done` would mean the reader waited for it"
        )
        assert kinds[-1] == "[DONE]", "the sentinel still terminates the stream"

    def test_the_verdict_carries_the_score_the_checker_returned(
        self, client: TestClient
    ) -> None:
        [verdict] = [e for e in _stream(client) if e["type"] == "verdict"]

        assert verdict["is_faithful"] is True
        assert verdict["score"] == 0.95
        assert verdict["unsupported_claims"] == []
        assert isinstance(verdict["ms"], int)

    def test_done_announces_that_a_verdict_is_coming(self, client: TestClient) -> None:
        # Without this the client cannot tell "checking" from "never checked",
        # and a server that predates the verdict event would leave a spinner
        # running for ever.
        [done] = [e for e in _stream(client) if e["type"] == "done"]

        assert done["verdict_pending"] is True

    def test_a_disabled_checker_promises_nothing_and_sends_nothing(
        self, client: TestClient
    ) -> None:
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline._faithfulness.enabled = False

        events = _stream(client)
        [done] = [e for e in events if e["type"] == "done"]

        assert done["verdict_pending"] is False
        assert not [e for e in events if e["type"] == "verdict"]

    def test_an_out_of_scope_refusal_promises_no_verdict(
        self, client: TestClient
    ) -> None:
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline._router.classify = AsyncMock(return_value="out_of_scope")

        events = _stream(client)
        [done] = [e for e in events if e["type"] == "done"]

        assert done["verdict_pending"] is False
        assert not [e for e in events if e["type"] == "verdict"]

    def test_a_judge_that_falls_over_does_not_destroy_the_answer(
        self, client: TestClient
    ) -> None:
        # The answer is already delivered and cited. Letting the judge's
        # exception reach `_stream_query` would turn it into an `error`
        # event, and the console replaces the whole answer with a failure
        # card on one of those -- so a broken auditor would cost the user a
        # perfectly good answer it had already read.
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        pipeline._faithfulness.check = AsyncMock(side_effect=RuntimeError("judge died"))

        events = _stream(client)

        assert "".join(e["text"] for e in events if e["type"] == "delta") == "Hello world"
        assert not [e for e in events if e["type"] == "error"]
        [verdict] = [e for e in events if e["type"] == "verdict"]
        assert verdict["is_faithful"] is None, "no verdict was reached, which is not a failed one"
        assert verdict["score"] is None
        assert events[-1]["type"] == "[DONE]"

    def test_the_check_reads_the_answer_that_was_streamed(
        self, client: TestClient
    ) -> None:
        # Checking some other string would make every verdict above
        # meaningless while keeping them green.
        pipeline = client.app.state.atlas.registry.get("default").pipeline
        _stream(client)

        answer = pipeline._faithfulness.check.await_args.args[0]
        assert answer == "Hello world"
