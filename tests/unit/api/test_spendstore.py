"""
Spend backends: the same two questions answered three ways.

The Firestore case uses a fake client that honours merge semantics and the
Increment transform, because that transform is the whole point — two Cloud
Run instances charging at once must not lose one of the charges to a
read-modify-write race, and a fake that just assigns would hide that.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.api.spendstore import (
    FirestoreSpendBackend,
    MemorySpendBackend,
    RedisSpendBackend,
    build_spend_backend,
)

DAY = "2026-09-23"


class TestMemory:
    async def test_accumulates_per_day(self) -> None:
        b = MemorySpendBackend()
        assert await b.total(DAY) == 0.0
        assert await b.add(DAY, 0.02) == pytest.approx(0.02)
        assert await b.add(DAY, 0.03) == pytest.approx(0.05)
        assert await b.total("2026-09-24") == 0.0


class TestRedis:
    async def test_reads_and_increments(self) -> None:
        redis = MagicMock()
        redis.get = AsyncMock(return_value="0.25")
        redis.incrbyfloat = AsyncMock(return_value="0.30")
        redis.expire = AsyncMock()
        b = RedisSpendBackend(redis)

        assert await b.total(DAY) == 0.25
        assert await b.add(DAY, 0.05) == 0.30
        redis.get.assert_awaited_with(f"atlas:spend:{DAY}")
        redis.expire.assert_awaited_once()

    async def test_missing_key_is_zero(self) -> None:
        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        assert await RedisSpendBackend(redis).total(DAY) == 0.0


# ── Firestore (fake client) ───────────────────────────────────────────────────

class _Snap:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return None if self._data is None else dict(self._data)


class _Doc:
    def __init__(self, store: dict[str, dict[str, Any]], doc_id: str) -> None:
        self._store, self.id = store, doc_id

    async def set(self, data: dict[str, Any], merge: bool = False) -> None:
        doc = self._store.setdefault(self.id, {}) if merge else {}
        for field, value in data.items():
            if type(value).__name__ == "Increment":  # the real transform
                doc[field] = doc.get(field, 0) + value.value
            else:
                doc[field] = value
        self._store[self.id] = doc

    async def get(self) -> _Snap:
        return _Snap(self._store.get(self.id))


class _Collection:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store

    def document(self, doc_id: str) -> _Doc:
        return _Doc(self._store, doc_id)


class _FakeClient:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def collection(self, name: str) -> _Collection:
        return _Collection(self.docs)


class TestFirestore:
    @pytest.fixture
    def backend(self) -> FirestoreSpendBackend:
        return FirestoreSpendBackend(client=_FakeClient())

    async def test_unspent_day_is_zero(self, backend: FirestoreSpendBackend) -> None:
        assert await backend.total(DAY) == 0.0

    async def test_charges_accumulate_on_one_document_per_day(
        self, backend: FirestoreSpendBackend
    ) -> None:
        assert await backend.add(DAY, 0.02) == pytest.approx(0.02)
        assert await backend.add(DAY, 0.03) == pytest.approx(0.05)
        assert await backend.total("2026-09-24") == 0.0
        assert list(backend._client.docs) == [DAY]  # type: ignore[union-attr]

    async def test_concurrent_charges_are_not_lost(
        self, backend: FirestoreSpendBackend
    ) -> None:
        """Increment is server-side, so interleaved writers both count."""
        import asyncio

        await asyncio.gather(*(backend.add(DAY, 0.01) for _ in range(5)))
        assert await backend.total(DAY) == pytest.approx(0.05)


class TestBuild:
    def test_auto_prefers_redis_when_connected(self) -> None:
        assert isinstance(build_spend_backend("auto", redis_client=MagicMock()), RedisSpendBackend)

    def test_auto_without_redis_is_in_process(self) -> None:
        assert isinstance(build_spend_backend("auto"), MemorySpendBackend)

    def test_redis_requested_but_absent_degrades_instead_of_raising(self) -> None:
        assert isinstance(build_spend_backend("redis"), MemorySpendBackend)

    def test_firestore(self) -> None:
        assert isinstance(build_spend_backend("firestore"), FirestoreSpendBackend)

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown BUDGET_STORE"):
            build_spend_backend("postgres")
