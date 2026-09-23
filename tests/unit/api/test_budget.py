"""Daily spend cap: SpendMeter accounting and the 429 it produces at the routes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from atlas.api.budget import BudgetExceeded, SpendMeter, seconds_until_utc_midnight
from atlas.api.spendstore import RedisSpendBackend


class TestSpendMeter:
    async def test_disabled_by_default(self) -> None:
        meter = SpendMeter()
        assert not meter.enabled
        await meter.add(1_000.0)
        await meter.check()  # never raises when budget is 0

    async def test_accumulates_and_trips(self) -> None:
        meter = SpendMeter(budget_usd=0.10)
        await meter.check()
        assert await meter.add(0.04) == pytest.approx(0.04)
        await meter.check()
        await meter.add(0.06)
        with pytest.raises(BudgetExceeded) as exc:
            await meter.check()
        assert exc.value.spent_usd == pytest.approx(0.10)
        assert exc.value.budget_usd == 0.10
        assert "daily budget exhausted" in str(exc.value)

    async def test_negative_or_zero_spend_ignored(self) -> None:
        meter = SpendMeter(budget_usd=1.0)
        await meter.add(0.0)
        await meter.add(-5.0)
        assert await meter.today_usd() == 0.0

    async def test_rolls_over_at_utc_midnight(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import atlas.api.budget as budget

        days = iter(["2026-09-20", "2026-09-20", "2026-09-21", "2026-09-21"])
        monkeypatch.setattr(budget, "_today", lambda: next(days))
        meter = SpendMeter(budget_usd=0.01)  # consumes day 1
        await meter.add(0.05)                # day 1 → over budget
        assert await meter.today_usd() == 0.0  # day 2 → fresh
        await meter.check()

    async def test_redis_shared_counter(self) -> None:
        redis = MagicMock()
        redis.get = AsyncMock(return_value="0.25")
        redis.incrbyfloat = AsyncMock(return_value="0.30")
        redis.expire = AsyncMock()
        meter = SpendMeter(budget_usd=1.0, backend=RedisSpendBackend(redis))

        assert await meter.today_usd() == 0.25
        assert await meter.add(0.05) == 0.30
        redis.incrbyfloat.assert_awaited_once()
        redis.expire.assert_awaited_once()

    async def test_backend_failure_falls_back_to_this_process_total(self) -> None:
        """An unreachable counter must not uncap the spend: the process's own
        mirror still trips the budget."""
        redis = MagicMock()
        redis.get = AsyncMock(side_effect=ConnectionError("down"))
        redis.incrbyfloat = AsyncMock(side_effect=ConnectionError("down"))
        meter = SpendMeter(budget_usd=0.05, backend=RedisSpendBackend(redis))
        await meter.add(0.05)
        with pytest.raises(BudgetExceeded):
            await meter.check()

    def test_retry_after_is_within_a_day(self) -> None:
        assert 1 <= seconds_until_utc_midnight() <= 24 * 3600


class _SpentBackend:
    """A counter that already holds today's spend, whatever day it is."""

    def __init__(self, usd: float) -> None:
        self.usd = usd

    async def total(self, day: str) -> float:
        return self.usd

    async def add(self, day: str, usd: float) -> float:
        self.usd += usd
        return self.usd


class TestBudgetAtRoutes:
    def _trip(self, client: TestClient) -> None:
        client.app.state.atlas.spend = SpendMeter(
            budget_usd=0.01, backend=_SpentBackend(0.01)
        )

    def test_query_returns_429_with_retry_after(self, client: TestClient) -> None:
        self._trip(client)
        resp = client.post("/query", json={"query": "What is Atlas?"})
        assert resp.status_code == 429
        assert "daily budget exhausted" in resp.json()["detail"]
        assert int(resp.headers["Retry-After"]) >= 1

    def test_streaming_query_returns_429(self, client: TestClient) -> None:
        self._trip(client)
        resp = client.post("/query", json={"query": "What is Atlas?", "stream": True})
        assert resp.status_code == 429

    def test_cache_hit_is_free(self, client: TestClient) -> None:
        first = client.post("/query", json={"query": "What is Atlas?"})
        assert first.status_code == 200
        self._trip(client)
        second = client.post("/query", json={"query": "What is Atlas?"})
        assert second.status_code == 200
        assert second.json()["cached"] is True

    def test_ingest_returns_429(self, client: TestClient, tmp_path) -> None:  # type: ignore[no-untyped-def]
        self._trip(client)
        f = tmp_path / "t.txt"
        f.write_text("hello")
        resp = client.post("/ingest", json={"path": str(f)})
        assert resp.status_code == 429

    def test_query_charges_the_meter(self, client: TestClient) -> None:
        client.app.state.atlas.spend = SpendMeter(budget_usd=10.0)
        resp = client.post("/query", json={"query": "What is Atlas?"})
        assert resp.status_code == 200
        charged = asyncio.run(client.app.state.atlas.spend.today_usd())
        assert charged == pytest.approx(resp.json()["token_usage"]["estimated_cost_usd"])

    def test_health_reports_budget_when_enabled(self, client: TestClient) -> None:
        assert client.get("/health").json()["budget"] is None
        client.app.state.atlas.spend = SpendMeter(
            budget_usd=0.5, backend=_SpentBackend(0.125)
        )
        body = client.get("/health").json()["budget"]
        assert body == {"daily_usd": 0.5, "spent_today_usd": 0.125}
