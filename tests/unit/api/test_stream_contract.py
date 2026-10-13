"""
What the SSE `done` event is allowed to claim.

The streaming path does not run the faithfulness check -- it would have to
buffer the whole answer, which defeats streaming -- and the `done` event sent
`"is_faithful": true` anyway, on both the success branch and the out-of-scope
one. The console happened to render UNCHECKED because it keys off the absent
score, so the UI was more honest than the API; every other client was told a
never-checked answer had been verified. That field is the one the project's
whole claim rests on.

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
