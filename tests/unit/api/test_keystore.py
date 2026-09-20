"""KeyStore backends: SQLite against a temp file, Firestore against a fake client."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from atlas.api import auth
from atlas.api.keystore import FirestoreKeyStore, SQLiteKeyStore, build_key_store, hash_key

# ── SQLite ────────────────────────────────────────────────────────────────────

@pytest.fixture
async def sqlite_store(tmp_path: Path) -> SQLiteKeyStore:
    store = SQLiteKeyStore(tmp_path / "keys.db")
    await store.init()
    return store


class TestSQLiteKeyStore:
    async def test_create_then_lookup(self, sqlite_store: SQLiteKeyStore) -> None:
        raw, key_id = await sqlite_store.create_key("alice", "a@x.io", rate_limit_rpm=7)
        assert raw.startswith("atlas_")
        found = await sqlite_store.lookup_key(raw)
        assert found is not None
        assert (found.id, found.name, found.email, found.rate_limit_rpm) == (
            key_id, "alice", "a@x.io", 7
        )

    async def test_unknown_key_is_none(self, sqlite_store: SQLiteKeyStore) -> None:
        assert await sqlite_store.lookup_key("atlas_nope") is None

    async def test_usage_aggregates(self, sqlite_store: SQLiteKeyStore) -> None:
        _, key_id = await sqlite_store.create_key("bob")
        await sqlite_store.log_usage(key_id, "default", 100, 20, 200.0, False)
        await sqlite_store.log_usage(key_id, "default", 0, 0, 1.0, True)
        await sqlite_store.log_usage(key_id, "docs", 50, 10, 100.0, False)
        stats = await sqlite_store.get_usage_stats(key_id)
        assert stats["total_queries"] == 3
        assert stats["cache_hits"] == 1
        assert stats["total_prompt_tokens"] == 150
        assert stats["avg_latency_ms"] == pytest.approx(100.3, abs=0.1)
        assert stats["by_namespace"][0] == {"namespace": "default", "queries": 2}

    async def test_stats_for_unused_key_are_zero(self, sqlite_store: SQLiteKeyStore) -> None:
        _, key_id = await sqlite_store.create_key("idle")
        stats = await sqlite_store.get_usage_stats(key_id)
        assert stats["total_queries"] == 0 and stats["by_namespace"] == []


# ── Firestore (fake client) ───────────────────────────────────────────────────

class _Snap:
    def __init__(self, doc_id: str, data: dict[str, Any] | None) -> None:
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return None if self._data is None else dict(self._data)


class _Doc:
    def __init__(self, store: dict[str, dict[str, Any]], doc_id: str) -> None:
        self._store, self.id = store, doc_id

    async def set(self, data: dict[str, Any]) -> None:
        self._store[self.id] = data

    async def get(self) -> _Snap:
        return _Snap(self.id, self._store.get(self.id))

    async def update(self, fields: dict[str, Any]) -> None:
        doc = self._store[self.id]
        for dotted, value in fields.items():
            *path, leaf = dotted.split(".")
            node = doc
            for part in path:
                node = node.setdefault(part, {})
            if type(value).__name__ == "Increment":  # the real transform
                node[leaf] = node.get(leaf, 0) + value.value
            else:
                node[leaf] = value


class _Query:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store

    def limit(self, n: int) -> _Query:
        return self

    async def get(self) -> list[_Snap]:
        return [_Snap(k, v) for k, v in list(self._store.items())[:1]]


class _Collection(_Query):
    def document(self, doc_id: str) -> _Doc:
        return _Doc(self._store, doc_id)


class _FakeClient:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def collection(self, name: str) -> _Collection:
        return _Collection(self.docs)


@pytest.fixture
def firestore_store() -> FirestoreKeyStore:
    pytest.importorskip("google.cloud.firestore_v1")
    return FirestoreKeyStore(client=_FakeClient())


class TestFirestoreKeyStore:
    async def test_doc_id_is_hash_and_lookup_roundtrips(
        self, firestore_store: FirestoreKeyStore
    ) -> None:
        await firestore_store.init()
        raw, key_id = await firestore_store.create_key("carol", rate_limit_rpm=3)
        assert key_id == hash_key(raw)
        found = await firestore_store.lookup_key(raw)
        assert found is not None and found.id == key_id and found.rate_limit_rpm == 3

    async def test_inactive_key_rejected(self, firestore_store: FirestoreKeyStore) -> None:
        raw, key_id = await firestore_store.create_key("dave")
        firestore_store._client.docs[key_id]["is_active"] = False
        assert await firestore_store.lookup_key(raw) is None

    async def test_usage_counters(self, firestore_store: FirestoreKeyStore) -> None:
        _, key_id = await firestore_store.create_key("erin")
        await firestore_store.log_usage(key_id, "default", 100, 20, 200.0, False)
        await firestore_store.log_usage(key_id, "docs", 0, 0, 100.0, True)
        stats = await firestore_store.get_usage_stats(key_id)
        assert stats["total_queries"] == 2
        assert stats["cache_hits"] == 1
        assert stats["total_prompt_tokens"] == 100
        assert stats["avg_latency_ms"] == 150.0
        assert {d["namespace"] for d in stats["by_namespace"]} == {"default", "docs"}
        assert stats["last_query_at"] is not None

    async def test_missing_key_stats_are_zero(self, firestore_store: FirestoreKeyStore) -> None:
        stats = await firestore_store.get_usage_stats("deadbeef")
        assert stats["total_queries"] == 0


# ── Facade ────────────────────────────────────────────────────────────────────

class TestFacade:
    async def test_configure_store_switches_backend(self, tmp_path: Path) -> None:
        store = auth.configure_store("sqlite", sqlite_path=tmp_path / "k.db")
        assert auth.get_store() is store
        await auth.init_db()
        raw, key_id = await auth.create_key("zed")
        assert (await auth.lookup_key(raw)).id == key_id  # type: ignore[union-attr]

    def test_unknown_backend_raises(self) -> None:
        with pytest.raises(ValueError, match="AUTH_STORE"):
            build_key_store("dynamo")

    def test_firestore_backend_builds_without_client(self) -> None:
        assert isinstance(build_key_store("firestore"), FirestoreKeyStore)
