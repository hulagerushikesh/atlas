"""When the model provider has no credit left, the visitor is told the demo is
paused instead of being handed the generic failure and a request id.

Proved with a built refusal rather than a live one: spending the balance to
zero to watch it happen is the one test this cannot afford.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from tests.unit.billing_errors import gemini_429


def _events(client: TestClient) -> list[dict[str, Any]]:
    out = []
    with client.stream("POST", "/query", json={"query": "q", "stream": True}) as resp:
        for line in resp.iter_lines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                out.append({"type": "[DONE]"} if payload == "[DONE]" else json.loads(payload))
    return out


def _pipeline(client: TestClient) -> Any:
    return client.app.state.atlas.registry.get("default").pipeline  # type: ignore[attr-defined]


class TestWithoutStreaming:
    def test_the_answer_is_a_503_that_says_demo_paused(self, client: TestClient) -> None:
        _pipeline(client).run = AsyncMock(side_effect=gemini_429())

        resp = client.post("/query", json={"query": "q", "stream": False})

        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["code"] == "demo_paused"
        assert detail["message"].startswith("Demo paused")

    def test_a_refusal_wrapped_by_a_stage_is_still_recognised(
        self, client: TestClient
    ) -> None:
        try:
            raise RuntimeError("generation failed") from gemini_429()
        except RuntimeError as wrapped:
            _pipeline(client).run = AsyncMock(side_effect=wrapped)

        resp = client.post("/query", json={"query": "q", "stream": False})

        assert resp.json()["detail"]["code"] == "demo_paused"

    def test_any_other_failure_keeps_the_generic_500(self, client: TestClient) -> None:
        _pipeline(client).run = AsyncMock(side_effect=RuntimeError("qdrant went away"))

        resp = client.post("/query", json={"query": "q", "stream": False})

        assert resp.status_code == 500
        assert "Demo paused" not in resp.text


class TestWhileStreaming:
    def test_the_error_event_says_demo_paused(self, client: TestClient) -> None:
        _pipeline(client)._router.classify = AsyncMock(side_effect=gemini_429())

        events = _events(client)

        [error] = [e for e in events if e["type"] == "error"]
        assert error["code"] == "demo_paused"
        assert error["error"].startswith("Demo paused")
        assert error["stage"] == "routing"
        assert events[-1]["type"] == "[DONE]"

    def test_the_provider_message_is_not_passed_through(self, client: TestClient) -> None:
        _pipeline(client)._router.classify = AsyncMock(side_effect=gemini_429())

        assert "ai.studio" not in json.dumps(_events(client))

    def test_any_other_failure_carries_no_code(self, client: TestClient) -> None:
        _pipeline(client)._router.classify = AsyncMock(side_effect=RuntimeError("boom"))

        [error] = [e for e in _events(client) if e["type"] == "error"]
        assert "code" not in error
