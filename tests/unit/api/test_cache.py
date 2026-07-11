"""Tests for two-level QueryCache."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.api.cache import QueryCache


@pytest.fixture
def cache() -> QueryCache:
    return QueryCache(max_memory_size=3)


class TestQueryCache:
    @pytest.mark.asyncio
    async def test_miss_returns_none(self, cache: QueryCache) -> None:
        result = await cache.get("unknown query")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_then_get(self, cache: QueryCache) -> None:
        await cache.set("what is atlas?", {"answer": "A RAG platform."})
        result = await cache.get("what is atlas?")
        assert result is not None
        assert result["answer"] == "A RAG platform."

    @pytest.mark.asyncio
    async def test_case_insensitive_key(self, cache: QueryCache) -> None:
        await cache.set("What Is Atlas?", {"answer": "yes"})
        result = await cache.get("what is atlas?")
        assert result is not None

    @pytest.mark.asyncio
    async def test_lru_eviction(self) -> None:
        cache = QueryCache(max_memory_size=2)
        await cache.set("q1", {"a": 1})
        await cache.set("q2", {"a": 2})
        await cache.set("q3", {"a": 3})   # evicts q1 (oldest)
        assert await cache.get("q1") is None
        assert await cache.get("q2") is not None
        assert await cache.get("q3") is not None

    @pytest.mark.asyncio
    async def test_lru_refresh_on_get(self) -> None:
        cache = QueryCache(max_memory_size=2)
        await cache.set("q1", {"a": 1})
        await cache.set("q2", {"a": 2})
        await cache.get("q1")             # refresh q1's position
        await cache.set("q3", {"a": 3})  # should evict q2 (now oldest)
        assert await cache.get("q1") is not None
        assert await cache.get("q2") is None

    @pytest.mark.asyncio
    async def test_clear_empties_memory(self, cache: QueryCache) -> None:
        await cache.set("q", {"a": 1})
        await cache.clear()
        assert await cache.get("q") is None

    @pytest.mark.asyncio
    async def test_redis_populated_on_set(self) -> None:
        redis = MagicMock()
        redis.setex = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        cache = QueryCache(redis_client=redis, ttl_seconds=60)
        await cache.set("q", {"a": 1})
        redis.setex.assert_awaited_once()
        args = redis.setex.call_args[0]
        assert args[1] == 60  # TTL

    @pytest.mark.asyncio
    async def test_redis_hit_populates_memory(self) -> None:
        import json
        redis = MagicMock()
        redis.get = AsyncMock(return_value=json.dumps({"answer": "from redis"}))
        cache = QueryCache(redis_client=redis)
        result = await cache.get("q")
        assert result is not None
        assert result["answer"] == "from redis"
        # Should now be in memory too
        assert cache._make_key("q") in cache._mem

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_raise(self) -> None:
        redis = MagicMock()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))
        redis.setex = AsyncMock(side_effect=ConnectionError("redis down"))
        cache = QueryCache(redis_client=redis)
        # Should not raise — graceful degradation to memory-only
        result = await cache.get("q")
        assert result is None
        await cache.set("q", {"a": 1})  # should store in memory
        assert await cache.get("q") is not None
