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


class TestNamespaceScoping:
    """The namespace is part of the key, and the part invalidation can find.

    Before 2026-10-29 the caller glued `f"{namespace}:{query}"` together and
    handed it over as one string, so the namespace went *inside* the hash.
    Entries were correctly separated by corpus and simultaneously impossible
    to enumerate by corpus, which is why an ingest could not drop them.
    """

    @pytest.mark.asyncio
    async def test_same_query_two_namespaces_do_not_collide(self) -> None:
        cache = QueryCache()
        await cache.set("what is a dependency?", {"answer": "fastapi"}, "default")
        await cache.set("what is a dependency?", {"answer": "field notes"}, "notes")

        from_default = await cache.get("what is a dependency?", "default")
        from_notes = await cache.get("what is a dependency?", "notes")
        assert from_default is not None and from_default["answer"] == "fastapi"
        assert from_notes is not None and from_notes["answer"] == "field notes"

    @pytest.mark.asyncio
    async def test_get_without_namespace_defaults(self) -> None:
        cache = QueryCache()
        await cache.set("q", {"a": 1}, "default")
        assert await cache.get("q") is not None

    @pytest.mark.asyncio
    async def test_invalidate_drops_only_its_own_namespace(self) -> None:
        cache = QueryCache()
        await cache.set("q1", {"a": 1}, "notes")
        await cache.set("q2", {"a": 2}, "notes")
        await cache.set("q1", {"a": 3}, "default")

        dropped = await cache.invalidate_namespace("notes")

        assert dropped == 2
        assert await cache.get("q1", "notes") is None
        assert await cache.get("q2", "notes") is None
        # The corpus nobody ingested into keeps its paid-for answers.
        survivor = await cache.get("q1", "default")
        assert survivor is not None and survivor["a"] == 3

    @pytest.mark.asyncio
    async def test_invalidate_unknown_namespace_is_zero_not_an_error(self) -> None:
        cache = QueryCache()
        await cache.set("q", {"a": 1}, "default")
        assert await cache.invalidate_namespace("never-existed") == 0
        assert await cache.get("q", "default") is not None

    @pytest.mark.asyncio
    async def test_glob_namespace_cannot_invalidate_everything(self) -> None:
        """A corpus called `*` must not match every other corpus.

        This is the whole reason the namespace is hashed rather than written
        into the key in the clear: the Redis side invalidates with `KEYS
        <prefix>*`, and an unhashed `*` would expand to every entry the
        process holds. The memory side would fail the same way via
        `startswith`.
        """
        cache = QueryCache()
        await cache.set("q", {"a": "mine"}, "*")
        await cache.set("q", {"a": "theirs"}, "default")

        assert await cache.invalidate_namespace("*") == 1
        survivor = await cache.get("q", "default")
        assert survivor is not None and survivor["a"] == "theirs"

    @pytest.mark.asyncio
    async def test_colon_in_namespace_is_not_a_prefix_of_a_nested_one(self) -> None:
        cache = QueryCache()
        await cache.set("q", {"a": 1}, "team")
        await cache.set("q", {"a": 2}, "team:private")

        assert await cache.invalidate_namespace("team") == 1
        nested = await cache.get("q", "team:private")
        assert nested is not None and nested["a"] == 2

    @pytest.mark.asyncio
    async def test_invalidate_deletes_the_redis_keys_it_found(self) -> None:
        redis = MagicMock()
        redis.keys = AsyncMock(return_value=["atlas:query:ns:one"])
        redis.delete = AsyncMock()
        cache = QueryCache(redis_client=redis)

        await cache.invalidate_namespace("notes")

        pattern = redis.keys.call_args[0][0]
        assert pattern == f"{cache._ns_prefix('notes')}*"
        redis.delete.assert_awaited_once_with("atlas:query:ns:one")

    @pytest.mark.asyncio
    async def test_invalidate_skips_delete_when_redis_holds_nothing(self) -> None:
        redis = MagicMock()
        redis.keys = AsyncMock(return_value=[])
        redis.delete = AsyncMock()
        cache = QueryCache(redis_client=redis)

        await cache.invalidate_namespace("notes")
        redis.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_fail_the_ingest(self) -> None:
        """The ingest already succeeded by the time this runs. An unreachable
        cache must not turn a written corpus into a 500."""
        redis = MagicMock()
        redis.keys = AsyncMock(side_effect=ConnectionError("redis down"))
        cache = QueryCache(redis_client=redis)
        await cache.set("q", {"a": 1}, "notes")

        assert await cache.invalidate_namespace("notes") == 1   # L1 still cleared
        assert await cache.get("q", "notes") is None

    @pytest.mark.asyncio
    async def test_the_redis_pattern_cannot_contain_a_users_glob(self) -> None:
        """The claim the hashing exists for, pinned on the side that would
        actually break. `KEYS atlas:query:*:*` matches every corpus in the
        process; the memory side would survive an unhashed `*` because
        `startswith` is literal, so only this test fails if the hash goes."""
        redis = MagicMock()
        redis.keys = AsyncMock(return_value=[])
        cache = QueryCache(redis_client=redis)

        await cache.invalidate_namespace("*")

        pattern = redis.keys.call_args[0][0]
        assert pattern.startswith("atlas:query:")
        assert "*" not in pattern.removesuffix("*")
