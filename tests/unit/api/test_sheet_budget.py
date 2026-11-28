"""
E4.3: a daily spending limit for each sheet, inside the overall one.
"""

# ruff: noqa: F811 -- fixtures are imported, then used as arguments

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

from atlas.api import sheet_budget, tenancy
from atlas.api.budget import SpendMeter
from atlas.cost import USD_TO_INR
from tests.unit.api.conftest import _make_pipeline_result
from tests.unit.api.test_sign_in import (  # noqa: F401 -- pytest fixtures
    CONSOLE,
    Site,
    google_key,
    site,
)


def _sheet(site: Site, key: str = "a/docs") -> tenancy.Workspace:
    ws = asyncio.run(tenancy.get_tenancy().get_workspace(site.ws[key]))
    assert ws is not None
    return ws


def _spend(site: Site, inr: float, key: str = "a/docs") -> None:
    """Charge a sheet as a question would."""
    overall = site.app.state.atlas.spend
    meter = asyncio.run(sheet_budget.meter_for(_sheet(site, key), overall))
    asyncio.run(meter.add(inr / USD_TO_INR))


def _ask(c: Any, sheet: str = "docs", question: str = "How much leave?") -> Any:
    # A cached answer costs nothing and is served past any limit, so tests
    # that expect a refusal ask something new.
    return c.post("/query", headers=CONSOLE, json={"query": question, "namespace": sheet})


def _answering(site: Site) -> None:
    site.app.state.atlas.registry.get.return_value.pipeline.run = AsyncMock(
        return_value=_make_pipeline_result())


class TestSettingALimit:
    def test_an_admin_sets_one_and_sees_today_per_sheet(self, site: Site) -> None:
        admin = site.sign_in("admin@acme.com")
        r = admin.put("/org/spending/docs", headers=CONSOLE, json={"daily_inr": 20})
        assert r.status_code == 200, r.text
        assert r.json() == {"sheet": "docs", "daily_inr": 20.0, "spent_today_inr": 0.0}
        _spend(site, 3.5)
        body = admin.get("/org/spending").json()
        rows = {s["sheet"]: s for s in body["sheets"]}
        assert set(rows) == {"docs", "hr"}            # only this organisation's sheets
        assert rows["docs"] == {"sheet": "docs", "daily_inr": 20.0, "spent_today_inr": 3.5}
        assert rows["hr"]["daily_inr"] == 0.0
        assert body["overall"]["spent_today_inr"] == 3.5   # counted overall too

    def test_admins_only_and_only_their_own_sheets(self, site: Site) -> None:
        reader = site.sign_in("reader@gmail.com")
        assert reader.get("/org/spending").status_code == 403
        assert reader.put("/org/spending/docs", headers=CONSOLE,
                          json={"daily_inr": 1}).status_code == 403
        bolt = site.sign_in("admin@bolt.io")
        assert bolt.put("/org/spending/hr", headers=CONSOLE,
                        json={"daily_inr": 1}).status_code == 404

    def test_a_negative_limit_is_refused(self, site: Site) -> None:
        admin = site.sign_in("admin@acme.com")
        assert admin.put("/org/spending/docs", headers=CONSOLE,
                         json={"daily_inr": -1}).status_code == 422


class TestTheLimitHolds:
    def test_a_sheet_over_its_limit_stops_and_the_others_go_on(self, site: Site) -> None:
        _answering(site)
        admin = site.sign_in("admin@acme.com")
        admin.put("/org/spending/docs", headers=CONSOLE, json={"daily_inr": 5})
        assert _ask(admin).status_code == 200
        _spend(site, 5)
        r = _ask(admin, question="Dental cover?")
        assert r.status_code == 429 and r.json()["detail"]["code"] == "sheet_cap"
        assert int(r.headers["Retry-After"]) > 0
        assert _ask(admin).status_code == 200            # asked before: from the cache
        assert _ask(admin, "hr", "Dental cover?").status_code == 200

    def test_lifting_the_limit_lets_it_answer_again(self, site: Site) -> None:
        _answering(site)
        admin = site.sign_in("admin@acme.com")
        admin.put("/org/spending/docs", headers=CONSOLE, json={"daily_inr": 5})
        _spend(site, 6)
        assert _ask(admin).status_code == 429
        admin.put("/org/spending/docs", headers=CONSOLE, json={"daily_inr": 0})
        assert _ask(admin).status_code == 200

    def test_a_sheet_limit_never_lifts_the_overall_one(self, site: Site) -> None:
        _answering(site)
        site.app.state.atlas.spend = SpendMeter(budget_usd=1 / USD_TO_INR)
        admin = site.sign_in("admin@acme.com")
        admin.put("/org/spending/docs", headers=CONSOLE, json={"daily_inr": 1000})
        _spend(site, 2, "a/hr")
        r = _ask(admin)
        assert r.status_code == 429 and "daily budget exhausted" in str(r.json()["detail"])

    def test_adding_documents_stops_too(self, site: Site) -> None:
        admin = site.sign_in("admin@acme.com")
        admin.put("/org/spending/docs", headers=CONSOLE, json={"daily_inr": 5})
        _spend(site, 5)
        r = admin.post("/ingest/upload", headers=CONSOLE, data={"namespace": "docs"},
                       files=[("files", ("a.md", b"# A", "text/markdown"))])
        assert r.status_code == 429 and r.json()["detail"]["code"] == "sheet_cap"

    def test_a_changed_limit_keeps_what_was_spent(self) -> None:
        ws = tenancy.Workspace(id="w1", org_id="o", name="docs", collection="c")
        overall = SpendMeter()
        sheet_budget.reset()
        first = asyncio.run(sheet_budget.meter_for(ws, overall))
        asyncio.run(first.add(0.01))
        sheet_budget._limits["w1"] = (100.0, 1e18)
        second = asyncio.run(sheet_budget.meter_for(ws, overall))
        assert second is not first and second.budget_usd == 100.0 / USD_TO_INR
        assert asyncio.run(second.today_usd()) == 0.01
        sheet_budget.reset()
