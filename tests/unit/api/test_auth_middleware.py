"""APIKeyMiddleware end to end against a SQLite store in a temp dir."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api import auth
from atlas.api.middleware.auth_mw import APIKeyMiddleware
from atlas.api.routes import health, keys
from atlas.config import get_settings


@pytest.fixture
def auth_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ADMIN_SECRET", "s3cret")
    get_settings.cache_clear()
    store = auth.configure_store("sqlite", sqlite_path=tmp_path / "k.db")
    # SQLite ids restart at 1 per temp db; the in-memory limiter is per-process.
    auth._windows.clear()

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware, enabled=True)
    app.include_router(health.router)
    app.include_router(keys.router)

    @app.get("/private")
    async def private() -> dict[str, str]:
        return {"ok": "yes"}

    asyncio.run(store.init())
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def _mint(client: TestClient, rpm: int = 60) -> str:
    r = client.post("/keys", headers={"X-Admin-Secret": "s3cret"},
                    json={"name": "t", "rate_limit_rpm": rpm})
    assert r.status_code == 201, r.text
    return r.json()["key"]


class TestAPIKeyMiddleware:
    def test_keys_endpoint_needs_no_bearer(self, auth_client: TestClient) -> None:
        # Chicken-and-egg otherwise: the first key could never be created.
        key = _mint(auth_client)
        assert key.startswith("atlas_")

    def test_keys_endpoint_still_needs_admin_secret(self, auth_client: TestClient) -> None:
        r = auth_client.post("/keys", json={"name": "t"})
        assert r.status_code == 403

    def test_missing_bearer_is_401(self, auth_client: TestClient) -> None:
        assert auth_client.get("/private").status_code == 401

    def test_bad_key_is_401(self, auth_client: TestClient) -> None:
        r = auth_client.get("/private", headers={"Authorization": "Bearer atlas_nope"})
        assert r.status_code == 401

    def test_good_key_passes(self, auth_client: TestClient) -> None:
        key = _mint(auth_client)
        r = auth_client.get("/private", headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200

    def test_rate_limit_429_with_retry_after(self, auth_client: TestClient) -> None:
        key = _mint(auth_client, rpm=2)
        h = {"Authorization": f"Bearer {key}"}
        assert auth_client.get("/private", headers=h).status_code == 200
        assert auth_client.get("/private", headers=h).status_code == 200
        r = auth_client.get("/private", headers=h)
        assert r.status_code == 429 and r.headers["Retry-After"] == "60"


class TestTheKeepWarmCanReachWhatItWasWrittenFor:
    """`/warm` is public because the only caller it exists for is anonymous.

    It shipped behind auth on rev `atlas-api-00019-qrn` and production
    answered `atlas-keepwarm`'s own URL with 401 — an endpoint added to fix
    a cold start, unreachable by the scheduler it was written for. Nothing
    in the suite would have caught it, because nothing asserted which paths
    the middleware lets through.
    """

    @staticmethod
    def _with_state(client: TestClient) -> TestClient:
        """Both routes read app.state.atlas; this fixture's app has none.

        Supplied here rather than in the fixture because what is under test
        is the middleware's allowlist, and the handlers only have to get far
        enough to prove they were not turned away at the door.
        """
        shared = MagicMock()
        shared.reranker = None
        # /health awaits this one; a plain MagicMock is not awaitable and
        # the TypeError escapes the handler's own except clause.
        shared.qdrant_client = AsyncMock()
        registry = MagicMock()
        registry._shared = shared
        spend = MagicMock()
        spend.enabled = False  # /health skips the awaited budget read
        client.app.state.atlas = MagicMock(registry=registry, spend=spend)
        return client

    def test_warm_is_reachable_without_a_bearer_key(self, auth_client: TestClient) -> None:
        response = self._with_state(auth_client).post("/warm")
        assert response.status_code == 200, response.text
        assert response.json()["reranker"] == "disabled"

    def test_health_still_is_too(self, auth_client: TestClient) -> None:
        assert self._with_state(auth_client).get("/health").status_code != 401

    def test_and_a_private_route_still_is_not(self, auth_client: TestClient) -> None:
        # The allowlist widened by one path, not by one path and a door.
        assert auth_client.get("/private").status_code == 401


class TestKeyLifecycleOverHTTP:
    """Revocation end to end: the admin routes, then a 401 on the revoked key.

    The store-level tests in `test_keystore.py` prove `set_key_active` writes
    the field. This proves the thing that matters operationally — that an
    operator with the admin secret, and nothing else, can stop a leaked key
    from answering.
    """

    _ADMIN = {"X-Admin-Secret": "s3cret"}

    def test_listing_needs_the_admin_secret(self, auth_client: TestClient) -> None:
        assert auth_client.get("/keys").status_code == 403

    def test_revoking_needs_it_too(self, auth_client: TestClient) -> None:
        _mint(auth_client)
        response = auth_client.patch("/keys/1", json={"is_active": False})
        assert response.status_code == 403
        # And the key still works, i.e. the 403 was a refusal, not a slow write.
        assert auth_client.get("/usage", headers={
            "Authorization": f"Bearer {_mint(auth_client)}"}).status_code == 200

    def test_listing_shows_the_keys_without_any_key_material(
        self, auth_client: TestClient
    ) -> None:
        raw = _mint(auth_client)
        body = auth_client.get("/keys", headers=self._ADMIN).json()
        assert [k["name"] for k in body["keys"]] == ["t"]
        assert body["keys"][0]["is_active"] is True
        assert raw not in str(body)
        assert auth.hash_key(raw) not in str(body)

    def test_usage_counters_reach_the_listing(self, auth_client: TestClient) -> None:
        raw = _mint(auth_client)
        headers = {"Authorization": f"Bearer {raw}"}
        assert auth_client.get("/usage", headers=headers).status_code == 200
        asyncio.run(auth.log_usage(1, "default", 10, 2, 50.0, cache_hit=False))
        record = auth_client.get("/keys", headers=self._ADMIN).json()["keys"][0]
        assert record["total_queries"] == 1 and record["last_query_at"] is not None

    def test_revoked_key_is_401_on_the_next_request(self, auth_client: TestClient) -> None:
        raw = _mint(auth_client)
        headers = {"Authorization": f"Bearer {raw}"}
        assert auth_client.get("/usage", headers=headers).status_code == 200

        key_id = auth_client.get("/keys", headers=self._ADMIN).json()["keys"][0]["key_id"]
        patched = auth_client.patch(
            f"/keys/{key_id}", headers=self._ADMIN, json={"is_active": False}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["is_active"] is False

        refused = auth_client.get("/usage", headers=headers)
        assert refused.status_code == 401
        assert refused.json()["error"] == "Invalid or inactive API key"

    def test_restore_puts_it_back(self, auth_client: TestClient) -> None:
        raw = _mint(auth_client)
        headers = {"Authorization": f"Bearer {raw}"}
        key_id = auth_client.get("/keys", headers=self._ADMIN).json()["keys"][0]["key_id"]
        auth_client.patch(f"/keys/{key_id}", headers=self._ADMIN, json={"is_active": False})
        assert auth_client.get("/usage", headers=headers).status_code == 401

        auth_client.patch(f"/keys/{key_id}", headers=self._ADMIN, json={"is_active": True})
        assert auth_client.get("/usage", headers=headers).status_code == 200

    def test_unknown_key_id_is_404(self, auth_client: TestClient) -> None:
        response = auth_client.patch(
            "/keys/9999", headers=self._ADMIN, json={"is_active": False}
        )
        assert response.status_code == 404

    def test_the_patch_route_is_not_open_to_a_bearer_holder(
        self, auth_client: TestClient
    ) -> None:
        # "/keys/" is on the middleware's public prefix list so the admin
        # secret can reach it; that must not mean any key holder can revoke
        # any other key.
        raw = _mint(auth_client)
        response = auth_client.patch(
            "/keys/1", headers={"Authorization": f"Bearer {raw}"}, json={"is_active": False}
        )
        assert response.status_code == 403
