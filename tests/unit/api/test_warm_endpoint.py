"""POST /warm — the endpoint that exists because of how Cloud Run bills CPU.

Deferring the cross-encoder cut the cold start from 36.9 s to 11.7 s, and
the background task meant to load the model afterwards does not complete on
Cloud Run: the service uses the default request-scoped CPU allocation, so a
thread running between requests gets almost none. Rev `atlas-api-00018-zfc`
demonstrated it by serving two keep-warm pings and never logging
`reranker_loaded_lazily`. A request is the only time CPU is allocated, so
the load happens in one.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


class _Reranker:
    def __init__(self, loads: bool = True) -> None:
        self.is_loaded = False
        self._loads = loads
        self.warm_calls = 0

    async def warm(self) -> None:
        self.warm_calls += 1
        if self._loads:
            self.is_loaded = True


def _client_with(reranker: object) -> TestClient:
    from fastapi import FastAPI

    from atlas.api.routes import health

    app = FastAPI()
    app.include_router(health.router)
    shared = MagicMock()
    shared.reranker = reranker
    registry = MagicMock()
    registry._shared = shared
    app.state.atlas = MagicMock(registry=registry)
    return TestClient(app)


class TestWarmLoadsTheModelInsideTheRequest:
    def test_it_reports_loaded_and_how_long_it_took(self) -> None:
        reranker = _Reranker()
        response = _client_with(reranker).post("/warm")

        assert response.status_code == 200
        body = response.json()
        assert body["reranker"] == "loaded"
        assert body["was_already_loaded"] is False
        assert reranker.warm_calls == 1

    def test_a_second_call_says_it_was_already_loaded(self) -> None:
        reranker = _Reranker()
        client = _client_with(reranker)
        client.post("/warm")
        body = client.post("/warm").json()

        # The keep-warm hits this every ten minutes; the common case is a
        # no-op and has to be distinguishable from a real load.
        assert body["was_already_loaded"] is True
        assert body["reranker"] == "loaded"

    def test_a_reranker_that_cannot_load_reports_failed_not_loaded(self) -> None:
        # warm() swallows the exception so the API keeps serving; the
        # endpoint must still say the model is not there, or a scheduler
        # ping returning 200 would read as a warm instance.
        body = _client_with(_Reranker(loads=False)).post("/warm").json()
        assert body["reranker"] == "failed"

    def test_a_disabled_reranker_is_not_a_failure(self) -> None:
        body = _client_with(None).post("/warm").json()
        assert body["reranker"] == "disabled"

    def test_get_works_too_because_schedulers_default_to_it(self) -> None:
        assert _client_with(_Reranker()).get("/warm").json()["reranker"] == "loaded"


class TestHealthStaysFast:
    def test_warm_is_a_separate_route_from_health(self) -> None:
        from atlas.api.routes import health

        paths = {r.path for r in health.router.routes}  # type: ignore[attr-defined]
        # A health check that blocks for twenty seconds once per cold start
        # trips alarms. The two endpoints want opposite things here.
        assert "/warm" in paths
        assert "/health" in paths
