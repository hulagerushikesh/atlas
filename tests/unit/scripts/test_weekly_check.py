"""
scripts/weekly_check.py: it stays quiet when the site is well and says why when not.

The network is stubbed, so these run in CI and cost nothing. The live check
itself runs from .github/workflows/weekly-check.yml.
"""

from __future__ import annotations

import importlib.util
import io
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "weekly_check.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("atlas_weekly_check", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def wc() -> Any:
    return _load()


GOOD_ANSWER = {
    "answer": "In DuckDB 2.0, X'CAFE' is a BLOB literal [1].",
    "citations": [{"index": 1}],
    "is_faithful": True,
    "faithfulness_score": 1.0,
    "token_usage": {"estimated_cost_usd": 0.0023},
}


class FakeSite:
    """Answers like the live site; override one path to break it."""

    def __init__(self, wc: Any, **overrides: Any) -> None:
        self.wc = wc
        self.calls: list[tuple[str, str]] = []
        self.routes = {
            "GET /": wc.Response(200, "<html>"),
            "GET /app": wc.Response(200, "<html>"),
            "GET /health": wc.Response(
                200, {"status": "ok", "components": {"qdrant": {"status": "ok"}}}
            ),
            "POST /query": wc.Response(200, dict(GOOD_ANSWER)),
        }
        self.routes.update(overrides)

    def __call__(self, method: str, url: str, payload: Any) -> Any:
        path = url.removeprefix(self.wc.BASE) or "/"
        self.calls.append((method, path))
        if path == "/query":
            assert payload == {"query": self.wc.QUESTION, "namespace": "duckdb"}
        return self.routes[f"{method} {path}"]


def test_healthy_site_passes_and_asks_one_keyless_question(wc: Any) -> None:
    site = FakeSite(wc)
    ok, report = wc.run(site)
    assert ok
    assert "all good" in report
    assert "$0.0023" in report
    assert site.calls.count(("POST", "/query")) == 1


def test_test_alert_fails_without_touching_the_site(wc: Any) -> None:
    site = FakeSite(wc)
    ok, report = wc.run(site, test_alert=True)
    assert not ok
    assert "test alert" in report
    assert "close this issue" in report
    assert "suggested question" not in report
    assert site.calls == []


@pytest.mark.parametrize(
    ("route", "response", "expected"),
    [
        ("GET /", (500, "oops"), "returned 500"),
        ("GET /app", (0, "unreachable"), "no answer at all"),
        ("GET /health", (503, "down"), "health page returned 503"),
        ("GET /health", (200, {"status": "degraded", "components": {}}), "'degraded'"),
        (
            "POST /query",
            (503, {"detail": {"code": "demo_paused"}}),
            "Gemini has no credit left",
        ),
        ("POST /query", (403, {"detail": {"code": "key_required"}}), "403 key_required"),
        ("POST /query", (200, {**GOOD_ANSWER, "answer": "It is VARCHAR."}), "no longer says BLOB"),
        ("POST /query", (200, {**GOOD_ANSWER, "citations": []}), "no citations"),
        (
            "POST /query",
            (200, {**GOOD_ANSWER, "is_faithful": False, "faithfulness_score": 0.4}),
            "score 0.4",
        ),
    ],
)
def test_each_fault_fails_and_is_named(
    wc: Any, route: str, response: tuple[int, Any], expected: str
) -> None:
    site = FakeSite(wc, **{route: wc.Response(*response)})
    ok, report = wc.run(site)
    assert not ok
    assert expected in report
    assert "Next:" in report


def test_used_up_allowance_is_a_note_not_an_alert(wc: Any) -> None:
    site = FakeSite(wc, **{"POST /query": wc.Response(429, {"detail": {"code": "demo_cap"}})})
    ok, report = wc.run(site)
    assert ok
    assert "demo_cap" in report


def test_main_writes_report_and_exit_code(
    wc: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    report = tmp_path / "report.md"

    assert wc.main(["--report", str(report)], fetch=FakeSite(wc)) == 0
    assert "all good" in report.read_text()

    report.unlink()
    assert wc.main(["--report", str(report), "--test-alert"], fetch=FakeSite(wc)) == 1
    assert "test alert" in report.read_text()
    assert summary.read_text().count("Atlas weekly check") == 2


def test_http_fetch_reads_error_bodies_and_survives_no_network(
    wc: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(req: Any, timeout: float) -> Any:
        body = io.BytesIO(b'{"detail": {"code": "demo_paused"}}')
        raise urllib.error.HTTPError(req.full_url, 503, "paused", {}, body)  # type: ignore[arg-type]

    monkeypatch.setattr(wc.urllib.request, "urlopen", refuse)
    r = wc.http_fetch("POST", "https://example.test/query", {"query": "q"})
    assert (r.status, r.body) == (503, {"detail": {"code": "demo_paused"}})

    def offline(req: Any, timeout: float) -> Any:
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(wc.urllib.request, "urlopen", offline)
    r = wc.http_fetch("GET", "https://example.test/")
    assert r.status == 0
    assert "unreachable" in r.body


def test_http_fetch_returns_text_when_not_json(wc: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    class Page(io.BytesIO):
        status = 200

    monkeypatch.setattr(wc.urllib.request, "urlopen", lambda req, timeout: Page(b"<html>"))
    assert wc.http_fetch("GET", "https://example.test/").body == "<html>"
