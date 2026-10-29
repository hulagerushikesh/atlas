"""
Two-level query cache: in-memory LRU + optional Redis.

Design rationale:
    Enterprise knowledge bases receive many repeated queries — the same
    question asked by different employees throughout the day. Caching the full
    pipeline response eliminates LLM calls for these repeated queries,
    reducing both latency and cost.

    Two-level design:
      L1 — in-memory OrderedDict (LRU, bounded by max_size). Sub-millisecond
           lookup, zero network overhead. Evicted items fall through to L2.
      L2 — Redis (optional). Survives process restarts and is shared across
           multiple API workers. Configurable TTL (default 1 hour).

    Cache key: `atlas:query:<hash(namespace)>:<hash(query)>`. Both halves are
    hashed, which is what makes `invalidate_namespace` safe. A readable
    namespace in the key would be two bugs at once: Redis `KEYS` takes a glob,
    so a corpus called `*` would match every other corpus's entries, and a
    corpus whose name contains `:` would share a prefix with a nested one. A
    fixed-width hash has neither problem. top_k is deliberately absent — it
    varies rarely and the caller can truncate the cached chunk list.

    When to NOT cache:
      - Streaming requests (we cache the complete response, streaming is
        unsuitable for cache population because we'd need to buffer the stream)
      - Ingest results (idempotent by design, cheap to recompute)

    Cache invalidation: both endpoints in `routes/ingest.py` call
    `invalidate_namespace` after a successful index, because a corpus that
    just gained a document answers differently and a cached answer is the one
    thing a user cannot tell apart from a wrong one. Scoped to the namespace
    on purpose: ingesting into one corpus must not throw away another's
    answers, each of which costs a paid pipeline run to rebuild.

    What this does *not* cover, stated rather than implied: L1 is per-process,
    and Cloud Run runs with `REDIS_URL=""` and `--max-instances 2`. An ingest
    served by one instance cannot reach the other instance's memory, so that
    one keeps its stale entries until `cache_ttl_seconds` expires them (1 h by
    default). This is the same shape of bug the BM25 index had before it became
    a cache rebuilt from Qdrant; the difference is that a stale BM25 index
    loses an answer, while a stale cache entry returns a confident old one.
    Closing it properly needs the shared L2 that `REDIS_URL` already supports.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

import structlog

from atlas.ingestion.hashing import hash_text

logger = structlog.get_logger(__name__)


class QueryCache:
    """Two-level (memory + Redis) cache for full pipeline responses."""

    def __init__(
        self,
        max_memory_size: int = 256,
        redis_client: Any = None,   # redis.asyncio.Redis | None
        ttl_seconds: int = 3600,
    ) -> None:
        self._mem: OrderedDict[str, str] = OrderedDict()
        self._max_size = max_memory_size
        self._redis = redis_client
        self._ttl = ttl_seconds

    def _ns_prefix(self, namespace: str) -> str:
        """Key prefix every entry for *namespace* shares. Fixed width, so it
        cannot run past its own namespace into a neighbour's."""
        return f"atlas:query:{hash_text(namespace)}:"

    def _make_key(self, query: str, namespace: str = "default") -> str:
        return f"{self._ns_prefix(namespace)}{hash_text(query.lower().strip())}"

    async def get(self, query: str, namespace: str = "default") -> dict[str, Any] | None:
        key = self._make_key(query, namespace)

        # L1 — memory
        if key in self._mem:
            self._mem.move_to_end(key)  # refresh LRU position
            logger.debug("cache_hit_memory", key=key[:20])
            hit: dict[str, Any] = json.loads(self._mem[key])
            return hit

        # L2 — Redis
        if self._redis is not None:
            try:
                raw = await self._redis.get(key)
                if raw is not None:
                    logger.debug("cache_hit_redis", key=key[:20])
                    self._mem_set(key, raw if isinstance(raw, str) else raw.decode())
                    redis_hit: dict[str, Any] = json.loads(raw)
                    return redis_hit
            except Exception as exc:
                logger.warning("cache_redis_get_failed", error=str(exc))

        return None

    async def set(
        self, query: str, payload: dict[str, Any], namespace: str = "default"
    ) -> None:
        key = self._make_key(query, namespace)
        serialised = json.dumps(payload)
        self._mem_set(key, serialised)

        if self._redis is not None:
            try:
                await self._redis.setex(key, self._ttl, serialised)
            except Exception as exc:
                logger.warning("cache_redis_set_failed", error=str(exc))

    async def invalidate_namespace(self, namespace: str) -> int:
        """
        Drop every cached answer for one corpus. Returns the L1 count dropped.

        Called after an ingest. The count is returned rather than logged alone
        so the caller can report it: "0 entries dropped" after an upload is
        either an empty cache or a namespace mismatch, and those need telling
        apart. Redis failures are swallowed the same way `get`/`set` swallow
        them — a cache that cannot be reached must not fail an ingest that
        already succeeded — but they are logged at warning, because the stale
        entries then outlive the ingest.
        """
        prefix = self._ns_prefix(namespace)
        stale = [k for k in self._mem if k.startswith(prefix)]
        for key in stale:
            del self._mem[key]

        if self._redis is not None:
            try:
                keys = await self._redis.keys(f"{prefix}*")
                if keys:
                    await self._redis.delete(*keys)
            except Exception as exc:
                logger.warning(
                    "cache_redis_invalidate_failed", namespace=namespace, error=str(exc)
                )

        logger.info("cache_invalidated", namespace=namespace, memory_entries=len(stale))
        return len(stale)

    async def clear(self) -> None:
        self._mem.clear()
        if self._redis is not None:
            try:
                # Delete all atlas:query:* keys
                keys = await self._redis.keys("atlas:query:*")
                if keys:
                    await self._redis.delete(*keys)
            except Exception as exc:
                logger.warning("cache_redis_clear_failed", error=str(exc))

    def _mem_set(self, key: str, value: str) -> None:
        """Insert into LRU dict, evicting the oldest entry if at capacity."""
        if key in self._mem:
            self._mem.move_to_end(key)
        self._mem[key] = value
        if len(self._mem) > self._max_size:
            self._mem.popitem(last=False)
