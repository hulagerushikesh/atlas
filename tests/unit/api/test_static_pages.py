"""
The two HTML entry points, / and /app.

Both are served as routes rather than left to the StaticFiles mount, because
the mount answers /app with a 307 to /app/ whose Location it builds from the
request's own host. Behind the domain proxy that host is the Cloud Run origin,
so a visitor clicking through atlas.hulage.in would land on the run.app URL.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from atlas.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app(), follow_redirects=False)


class TestEntryPoints:
    def test_landing_is_served_at_root(self) -> None:
        resp = _client().get("/")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")

    def test_console_is_served_at_app_without_a_redirect(self) -> None:
        resp = _client().get("/app")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")

    def test_console_assets_still_come_from_the_mount(self) -> None:
        resp = _client().get("/app/assets")
        assert resp.status_code in (200, 404)  # directory listing is not served
