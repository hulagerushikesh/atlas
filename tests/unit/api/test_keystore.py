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
    def __init__(self, store: dict[str, dict[str, Any]], limit: int | None = None) -> None:
        self._store, self._limit = store, limit

    def limit(self, n: int) -> _Query:
        # Used to ignore n and `get()` used to slice [:1] regardless, which was
        # indistinguishable from the real thing while `init()` was the only
        # caller. `list_keys()` calls `get()` with no limit, so the fake now has
        # to tell the two apart or it would report one key however many exist.
        return _Query(self._store, n)

    async def get(self) -> list[_Snap]:
        items = list(self._store.items())
        if self._limit is not None:
            items = items[: self._limit]
        return [_Snap(k, v) for k, v in items]


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
    # No importorskip here. It used to gate this fixture on
    # google.cloud.firestore_v1, which skipped all four tests below whenever
    # the `gcp` extra was absent -- and `make install` asked for `.[dev]`
    # until 2026-10-12, so CI's first run skipped the lot without a word
    # while two neighbouring tests that import google.cloud at module level
    # failed loudly and took the attention. Only test_usage_counters touches
    # google at all (log_usage needs Increment); the other three run entirely
    # against _FakeClient. Firestore is the production key store, so a
    # missing extra is a broken gate, not a degraded one -- see
    # test_the_gcp_extra_is_installed for the pin that says so in one line.
    return FirestoreKeyStore(client=_FakeClient())


def test_the_gcp_extra_is_installed() -> None:
    """
    Production authenticates against Firestore (AUTH_STORE=firestore), so the
    `gcp` extra is required for the gate even though it is optional at import
    time -- keystore.py builds its client lazily on purpose. This test exists
    so that a missing extra produces one failure that names the cause instead
    of four quiet skips: `FirestoreKeyStore.log_usage` swallows every
    exception, ImportError included, and logs `usage_log_failed` at warning
    level, so without this pin the only other symptom is a counter assertion
    that does not mention google at all.
    """
    import google.cloud.firestore_v1  # noqa: PLC0415 - the point of the test

    assert hasattr(google.cloud.firestore_v1, "Increment"), (
        "google-cloud-firestore is importable but has no Increment; "
        "log_usage builds every usage counter out of it"
    )


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


# ── Key lifecycle ─────────────────────────────────────────────────────────────

class TestSQLiteKeyLifecycle:
    """`is_active` had no writer until these methods existed.

    Both stores read the field in `lookup_key` and both tests below used to set
    it by hand, so the branch was covered and unreachable: a leaked key could
    only be revoked by editing the store. See DECISIONS 2026-10-24.
    """

    async def test_list_is_newest_first_and_carries_usage(
        self, sqlite_store: SQLiteKeyStore
    ) -> None:
        _, first = await sqlite_store.create_key("first")
        _, second = await sqlite_store.create_key("second")
        await sqlite_store.log_usage(second, "default", 10, 2, 50.0, False)

        records = await sqlite_store.list_keys()
        assert [r.id for r in records] == [second, first]
        assert records[0].total_queries == 1 and records[0].last_query_at is not None
        assert records[1].total_queries == 0 and records[1].last_query_at is None
        assert all(r.is_active for r in records)

    async def test_revoke_makes_the_key_stop_resolving(
        self, sqlite_store: SQLiteKeyStore
    ) -> None:
        raw, key_id = await sqlite_store.create_key("doomed")
        assert await sqlite_store.lookup_key(raw) is not None

        record = await sqlite_store.set_key_active(key_id, False)
        assert record is not None and record.is_active is False
        assert await sqlite_store.lookup_key(raw) is None

    async def test_restore_brings_it_back(self, sqlite_store: SQLiteKeyStore) -> None:
        raw, key_id = await sqlite_store.create_key("pardoned")
        await sqlite_store.set_key_active(key_id, False)
        record = await sqlite_store.set_key_active(key_id, True)
        assert record is not None and record.is_active is True
        assert await sqlite_store.lookup_key(raw) is not None

    async def test_unknown_id_is_none_not_an_error(
        self, sqlite_store: SQLiteKeyStore
    ) -> None:
        assert await sqlite_store.set_key_active(9999, False) is None

    async def test_a_firestore_shaped_id_is_a_miss_not_a_crash(
        self, sqlite_store: SQLiteKeyStore
    ) -> None:
        # The route takes the id as a string and does not know which backend is
        # mounted; a 64-char hash against SQLite must 404, not 500.
        assert await sqlite_store.set_key_active("a" * 64, False) is None


class TestFirestoreKeyLifecycle:
    async def test_list_returns_every_key(self, firestore_store: FirestoreKeyStore) -> None:
        await firestore_store.create_key("one")
        await firestore_store.create_key("two")
        records = await firestore_store.list_keys()
        assert sorted(r.name for r in records) == ["one", "two"]
        assert all(r.is_active and r.total_queries == 0 for r in records)

    async def test_list_carries_the_usage_counters(
        self, firestore_store: FirestoreKeyStore
    ) -> None:
        _, key_id = await firestore_store.create_key("busy")
        await firestore_store.log_usage(key_id, "default", 10, 2, 50.0, False)
        record = next(r for r in await firestore_store.list_keys() if r.id == key_id)
        assert record.total_queries == 1 and record.last_query_at is not None

    async def test_revoke_makes_the_key_stop_resolving(
        self, firestore_store: FirestoreKeyStore
    ) -> None:
        raw, key_id = await firestore_store.create_key("doomed")
        assert await firestore_store.lookup_key(raw) is not None

        record = await firestore_store.set_key_active(key_id, False)
        assert record is not None and record.is_active is False
        assert await firestore_store.lookup_key(raw) is None
        assert await firestore_store.set_key_active(key_id, True) is not None
        assert await firestore_store.lookup_key(raw) is not None

    async def test_unknown_id_is_none(self, firestore_store: FirestoreKeyStore) -> None:
        assert await firestore_store.set_key_active("deadbeef", False) is None

    async def test_the_record_never_carries_a_hash(
        self, firestore_store: FirestoreKeyStore
    ) -> None:
        # `id` is the hash on this backend and has to be, because PATCH needs
        # it. Nothing else in the record may be one.
        raw, key_id = await firestore_store.create_key("quiet")
        record = (await firestore_store.list_keys())[0]
        fields = {k: v for k, v in vars(record).items() if k != "id"}
        assert hash_key(raw) not in str(fields)
        assert raw not in str(fields)
