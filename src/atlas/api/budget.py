"""
Daily spend cap.

Design rationale:
    The API is the only surface that turns on a meter without a human in the
    loop (the CLI scripts are run by hand). A hard daily cap means a runaway
    client, a bug in a retry loop, or a public endpoint being discovered can
    cost at most one day's budget — the same guard sextant carries as
    SEXTANT_DAILY_BUDGET_USD.

    Spend is the pipeline's own cost estimate (atlas.api.cost), accumulated
    per UTC day. With Redis present the counter is shared across workers and
    survives restarts; without it each process keeps its own in-memory total,
    which is still a cap, just a per-process one.

    Budget 0 (the default) disables the check so tests and local dev are not
    affected. The check happens BEFORE the metered call and the charge AFTER,
    so a single request can overshoot by at most its own cost.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_REDIS_TTL_SECONDS = 2 * 24 * 3600  # keep yesterday for a day, then drop


class BudgetExceeded(Exception):
    """Raised by SpendMeter.check() when today's spend has reached the cap."""

    def __init__(self, spent_usd: float, budget_usd: float) -> None:
        self.spent_usd = spent_usd
        self.budget_usd = budget_usd
        super().__init__(
            f"daily budget exhausted: ${spent_usd:.4f} of ${budget_usd:.2f} spent today (UTC)"
        )


def _today() -> str:
    return dt.datetime.now(dt.UTC).date().isoformat()


def seconds_until_utc_midnight() -> int:
    now = dt.datetime.now(dt.UTC)
    tomorrow = (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


class SpendMeter:
    """Per-UTC-day USD accumulator with an optional hard cap."""

    def __init__(self, budget_usd: float = 0.0, redis_client: Any = None) -> None:
        self._budget = max(0.0, budget_usd)
        self._redis = redis_client
        self._day = _today()
        self._local = 0.0

    @property
    def budget_usd(self) -> float:
        return self._budget

    @property
    def enabled(self) -> bool:
        return self._budget > 0

    def _key(self) -> str:
        return f"atlas:spend:{_today()}"

    def _roll_day(self) -> None:
        today = _today()
        if today != self._day:
            self._day = today
            self._local = 0.0

    async def today_usd(self) -> float:
        self._roll_day()
        if self._redis is not None:
            try:
                raw = await self._redis.get(self._key())
                return float(raw) if raw else 0.0
            except Exception as exc:  # Redis down → fall back to local total
                logger.warning("spend_meter_redis_read_failed", error=str(exc))
        return self._local

    async def add(self, usd: float) -> float:
        """Record spend; returns the new daily total."""
        if usd <= 0:
            return await self.today_usd()
        self._roll_day()
        self._local += usd
        if self._redis is not None:
            try:
                key = self._key()
                total = float(await self._redis.incrbyfloat(key, usd))
                await self._redis.expire(key, _REDIS_TTL_SECONDS)
                return total
            except Exception as exc:
                logger.warning("spend_meter_redis_write_failed", error=str(exc))
        return self._local

    async def check(self) -> None:
        """Raise BudgetExceeded if today's spend has reached the cap."""
        if not self.enabled:
            return
        spent = await self.today_usd()
        if spent >= self._budget:
            logger.warning("daily_budget_exhausted", spent_usd=spent, budget_usd=self._budget)
            raise BudgetExceeded(spent, self._budget)
