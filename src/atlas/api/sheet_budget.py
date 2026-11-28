"""
A daily spending limit for each sheet (E4.3).

Atlas already stops at one daily limit for everything (`BUDGET_DAILY_USD`,
atlas.api.budget). That protects the bill, not the teams: one busy sheet can
use the whole day and leave every other sheet refusing questions. An
organisation admin can now give a sheet a limit of its own.

Every charge on a sheet goes through `meter_for`: a scoped SpendMeter whose
parent is the meter the request would have used anyway (the overall one, or
the keyless demo one), so a sheet's limit can only ever be tighter than the
overall limit, never lift it. Sheets without a limit are still counted, so
the admin sees what each sheet spends before choosing a figure.

Limits are kept in rupees, as the owner and the console think in them, and
converted once, here, to the dollars the spend counter holds. Questions,
uploads, path ingests, MCP searches and Drive syncs are all charged; a Drive
sync over its sheet's limit still applies sharing changes and removals
(they cost nothing) and leaves new text for after the reset.
"""

from __future__ import annotations

import time
from typing import Any

from atlas.api import tenancy
from atlas.api.budget import SpendMeter
from atlas.cost import USD_TO_INR

KIND = "sheet_budget"
MAX_DAILY_INR = 100_000.0

_limits: dict[str, tuple[float, float]] = {}      # workspace id -> (₹ a day, read at)
_meters: dict[tuple[str, str], SpendMeter] = {}   # (workspace id, parent scope) -> meter


def scope(ws: tenancy.Workspace) -> str:
    return f"sheet-{ws.id}"


async def daily_inr(ws: tenancy.Workspace) -> float:
    """The sheet's own daily limit in rupees; 0 means none of its own."""
    found = _limits.get(ws.id)
    if found is not None and time.time() - found[1] < 60:
        return found[0]
    record = await tenancy.get_tenancy().get_record(KIND, ws.id) or {}
    limit = float(record.get("daily_inr") or 0.0)
    _limits[ws.id] = (limit, time.time())
    return limit


async def set_daily_inr(ws: tenancy.Workspace, limit: float, by: str) -> None:
    await tenancy.get_tenancy().put_record(KIND, ws.id, ws.org_id, {
        "workspace_id": ws.id, "daily_inr": limit, "set_by": by, "set_at": time.time()})
    _limits.pop(ws.id, None)


async def meter_for(ws: tenancy.Workspace, parent: SpendMeter) -> SpendMeter:
    """The meter a charge on *ws* goes through. Kept per sheet for the life of
    the process, so its own mirror of today's spend still holds the limit if
    the shared counter cannot be read."""
    limit_usd = await daily_inr(ws) / USD_TO_INR
    key = (ws.id, parent.scope)
    meter = _meters.get(key)
    if meter is None or meter.parent is not parent or meter.budget_usd != limit_usd:
        fresh = SpendMeter(budget_usd=limit_usd, backend=parent.backend,
                           scope=scope(ws), parent=parent)
        if meter is not None and meter.parent is parent:
            fresh.adopt_mirror(meter)
        meter = _meters[key] = fresh
    return meter


async def view(ws: tenancy.Workspace, parent: SpendMeter) -> dict[str, Any]:
    meter = await meter_for(ws, parent)
    return {"sheet": ws.name, "daily_inr": await daily_inr(ws),
            "spent_today_inr": round(await meter.today_usd() * USD_TO_INR, 2)}


def reset() -> None:
    """Forget cached limits and meters (tests)."""
    _limits.clear()
    _meters.clear()
