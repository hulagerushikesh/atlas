"""Keyless questions on the demo sheet, with auth switched ON.

The route fixture runs with no auth middleware, which would make every branch
here unreachable; this file adds the real middleware against a SQLite store.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas.api import auth
from atlas.api.budget import BudgetExceeded, SpendMeter
from atlas.api.middleware.auth_mw import APIKeyMiddleware
from atlas.api.spendstore import MemorySpendBackend

DEMO = "duckdb"


@pytest.fixture
def demo(client: TestClient, tmp_path: Path) -> Iterator[TestClient]:
    store = auth.configure_store("sqlite", sqlite_path=tmp_path / "k.db")
    asyncio.run(store.init())
    auth._windows.clear()
    client.app.add_middleware(APIKeyMiddleware, enabled=True, demo_rpm=2)  # type: ignore[attr-defined]
    state = client.app.state.atlas  # type: ignore[attr-defined]
    state.spend = SpendMeter(budget_usd=1.0)
    state.demo_namespace = DEMO
    state.demo_spend = SpendMeter(budget_usd=0.1, scope="demo", parent=state.spend)
    yield client
    auth._windows.clear()


def _ask(client: TestClient, sheet: str = DEMO, ip: str = "1.1.1.1", **kw: object) -> object:
    return client.post("/query", json={"query": "q", "namespace": sheet, **kw},
                       headers={"X-Forwarded-For": f"{ip}, 10.0.0.1"})


class TestWhoGetsIn:
    def test_a_keyless_question_on_the_demo_sheet_is_answered(self, demo: TestClient) -> None:
        r = _ask(demo)
        assert r.status_code == 200, r.text  # type: ignore[attr-defined]

    def test_another_sheet_still_needs_a_key(self, demo: TestClient) -> None:
        r = _ask(demo, sheet="default")
        assert r.status_code == 403  # type: ignore[attr-defined]
        assert r.json()["detail"]["code"] == "key_required"  # type: ignore[attr-defined]

    def test_everything_else_still_needs_a_key(self, demo: TestClient) -> None:
        r = demo.post("/ingest", json={"path": "x", "namespace": DEMO})
        assert r.status_code == 401

    def test_a_wrong_key_is_refused_not_treated_as_keyless(self, demo: TestClient) -> None:
        r = demo.post("/query", json={"query": "q", "namespace": DEMO},
                      headers={"Authorization": "Bearer atlas_nope"})
        assert r.status_code == 401

    def test_with_no_demo_sheet_configured_nothing_changes(self, demo: TestClient) -> None:
        demo.app.state.atlas.demo_namespace = ""  # type: ignore[attr-defined]
        assert _ask(demo).status_code == 401  # type: ignore[attr-defined]


class TestTheCaps:
    def test_a_spent_demo_allowance_refuses_keyless_questions(self, demo: TestClient) -> None:
        asyncio.run(demo.app.state.atlas.demo_spend.add(0.1))  # type: ignore[attr-defined]
        r = _ask(demo)
        assert r.status_code == 429  # type: ignore[attr-defined]
        assert r.json()["detail"]["code"] == "demo_cap"  # type: ignore[attr-defined]

    def test_a_spent_demo_allowance_leaves_key_holders_alone(self, demo: TestClient) -> None:
        asyncio.run(demo.app.state.atlas.demo_spend.add(0.1))  # type: ignore[attr-defined]
        key, _ = asyncio.run(auth.create_key("t"))
        r = demo.post("/query", json={"query": "q", "namespace": DEMO},
                      headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200

    def test_the_overall_cap_still_binds_keyless_questions(self, demo: TestClient) -> None:
        asyncio.run(demo.app.state.atlas.spend.add(1.0))  # type: ignore[attr-defined]
        assert _ask(demo).status_code == 429  # type: ignore[attr-defined]

    def test_the_cap_is_checked_before_a_stream_starts(self, demo: TestClient) -> None:
        asyncio.run(demo.app.state.atlas.demo_spend.add(0.1))  # type: ignore[attr-defined]
        r = _ask(demo, stream=True)
        assert r.status_code == 429  # type: ignore[attr-defined]

    def test_one_visitor_is_limited_per_minute(self, demo: TestClient) -> None:
        assert _ask(demo, ip="2.2.2.2").status_code == 200  # type: ignore[attr-defined]
        assert _ask(demo, ip="2.2.2.2").status_code == 200  # type: ignore[attr-defined]
        r = _ask(demo, ip="2.2.2.2")
        assert r.status_code == 429  # type: ignore[attr-defined]
        assert r.json()["detail"]["code"] == "demo_rate"  # type: ignore[attr-defined]
        assert _ask(demo, ip="3.3.3.3").status_code == 200  # type: ignore[attr-defined]


class TestTheScopedMeter:
    def test_demo_spend_counts_against_the_overall_total(self) -> None:
        backend = MemorySpendBackend()
        overall = SpendMeter(budget_usd=1.0, backend=backend)
        demo = SpendMeter(budget_usd=0.1, backend=backend, scope="demo", parent=overall)

        asyncio.run(demo.add(0.04))

        assert asyncio.run(overall.today_usd()) == pytest.approx(0.04)
        assert asyncio.run(demo.today_usd()) == pytest.approx(0.04)

    def test_key_holder_spend_does_not_use_up_the_demo(self) -> None:
        backend = MemorySpendBackend()
        overall = SpendMeter(budget_usd=1.0, backend=backend)
        demo = SpendMeter(budget_usd=0.1, backend=backend, scope="demo", parent=overall)

        asyncio.run(overall.add(0.5))

        assert asyncio.run(demo.today_usd()) == 0.0
        asyncio.run(demo.check())

    def test_the_refusal_says_which_cap(self) -> None:
        demo = SpendMeter(budget_usd=0.1, scope="demo", parent=SpendMeter(budget_usd=1.0))
        asyncio.run(demo.add(0.1))
        with pytest.raises(BudgetExceeded) as exc:
            asyncio.run(demo.check())
        assert exc.value.scope == "demo"
