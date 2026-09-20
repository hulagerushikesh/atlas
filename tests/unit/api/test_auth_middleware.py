"""APIKeyMiddleware end to end against a SQLite store in a temp dir."""

from __future__ import annotations

import asyncio
from pathlib import Path

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
