"""
Where the daily spend total lives.

Design rationale:
    SpendMeter's cap is only as durable as its counter. In-process is fine
    for one long-lived server, but Cloud Run scales to zero: the instance
    that recorded today's spend is gone minutes later, and the next cold
    start starts the day at $0. The cap then limits a single instance's
    lifetime, not a day — exactly the guarantee a runaway client would
    dodge. Redis solves it when there is a Redis; on the M2 topology there
    isn't one, so the same Firestore that already holds API keys holds one
    document per UTC day.

    All three backends answer the same two questions — what is today's
    total, and add this much — so SpendMeter never learns which it has.
"""

from __future__ import annotations

from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)

_REDIS_TTL_SECONDS = 2 * 24 * 3600  # keep yesterday for a day, then drop


class SpendBackend(Protocol):
    """Per-UTC-day USD counter."""

    async def total(self, day: str) -> float: ...

    async def add(self, day: str, usd: float) -> float:
        """Record spend for `day`; returns the new total."""
        ...


class MemorySpendBackend:
    """Per-process totals. A cap, just not a shared or durable one."""

    def __init__(self) -> None:
        self._totals: dict[str, float] = {}

    async def total(self, day: str) -> float:
        return self._totals.get(day, 0.0)

    async def add(self, day: str, usd: float) -> float:
        self._totals[day] = self._totals.get(day, 0.0) + usd
        return self._totals[day]


class RedisSpendBackend:
    """Shared across workers, survives restarts, expires after two days."""

    def __init__(self, client: Any) -> None:
        self._redis = client

    def _key(self, day: str) -> str:
        return f"atlas:spend:{day}"

    async def total(self, day: str) -> float:
        raw = await self._redis.get(self._key(day))
        return float(raw) if raw else 0.0

    async def add(self, day: str, usd: float) -> float:
        key = self._key(day)
        new_total = float(await self._redis.incrbyfloat(key, usd))
        await self._redis.expire(key, _REDIS_TTL_SECONDS)
        return new_total


class FirestoreSpendBackend:
    """
    Document per UTC day at {collection}/{YYYY-MM-DD}, incremented server-side
    so concurrent instances cannot lose a charge to a read-modify-write race.
    One document per day is well inside the free tier.
    """

    def __init__(self, project: str | None = None, collection: str = "atlas_spend",
                 client: Any = None) -> None:
        self._project = project
        self._collection = collection
        self._client = client

    def _doc(self, day: str) -> Any:
        if self._client is None:
            from google.cloud import firestore  # noqa: PLC0415 — optional dependency

            self._client = firestore.AsyncClient(project=self._project)
        return self._client.collection(self._collection).document(day)

    async def total(self, day: str) -> float:
        snap = await self._doc(day).get()
        if not snap.exists:
            return 0.0
        return float((snap.to_dict() or {}).get("usd", 0.0))

    async def add(self, day: str, usd: float) -> float:
        from google.cloud.firestore_v1 import Increment  # noqa: PLC0415

        doc = self._doc(day)
        await doc.set({"usd": Increment(usd)}, merge=True)
        return await self.total(day)


def build_spend_backend(
    backend: str,
    *,
    redis_client: Any = None,
    firestore_project: str | None = None,
) -> SpendBackend:
    """
    Resolve BUDGET_STORE. "auto" prefers Redis when a live client was handed
    in, so existing deployments keep the counter they had.
    """
    if backend == "auto":
        backend = "redis" if redis_client is not None else "memory"
    if backend == "memory":
        return MemorySpendBackend()
    if backend == "redis":
        if redis_client is None:
            logger.warning("spend_store_redis_unavailable", detail="falling back to in-process")
            return MemorySpendBackend()
        return RedisSpendBackend(redis_client)
    if backend == "firestore":
        return FirestoreSpendBackend(project=firestore_project)
    raise ValueError(f"unknown BUDGET_STORE {backend!r}: use memory, redis, firestore or auto")
