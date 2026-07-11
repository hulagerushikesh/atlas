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

    Cache key: xxh3_64 of the lower-cased, stripped query string. We do NOT
    include top_k in the key because it varies rarely and the caller can
    truncate the cached chunk list if needed.

    When to NOT cache:
      - Streaming requests (we cache the complete response, streaming is
        unsuitable for cache population because we'd need to buffer the stream)
      - Ingest results (idempotent by design, cheap to recompute)

    Cache invalidation: TTL-based only. When a document is re-indexed (content
    changes), queries that would now return different results are not proactively
    invalidated — the TTL expiry handles it. For production, explicit invalidation
    on ingest can be added by calling cache.clear() or deleting by key prefix.
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

    def _make_key(self, query: str) -> str:
        return f"atlas:query:{hash_text(query.lower().strip())}"

    async def get(self, query: str) -> dict[str, Any] | None:
        key = self._make_key(query)

        # L1 — memory
        if key in self._mem:
            self._mem.move_to_end(key)  # refresh LRU position
            logger.debug("cache_hit_memory", key=key[:20])
            return json.loads(self._mem[key])

        # L2 — Redis
        if self._redis is not None:
            try:
                raw = await self._redis.get(key)
                if raw is not None:
                    logger.debug("cache_hit_redis", key=key[:20])
                    self._mem_set(key, raw if isinstance(raw, str) else raw.decode())
                    return json.loads(raw)
            except Exception as exc:
                logger.warning("cache_redis_get_failed", error=str(exc))

        return None

    async def set(self, query: str, payload: dict[str, Any]) -> None:
        key = self._make_key(query)
        serialised = json.dumps(payload)
        self._mem_set(key, serialised)

        if self._redis is not None:
            try:
                await self._redis.setex(key, self._ttl, serialised)
            except Exception as exc:
                logger.warning("cache_redis_set_failed", error=str(exc))

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
