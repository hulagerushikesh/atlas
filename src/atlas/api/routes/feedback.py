"""
What readers think of an answer, and what a sheet could not answer (E6).

    POST /feedback        thumbs up or down on one answer, with an optional reason
    GET  /org/unanswered  for organisation admins: questions a sheet could not
                          answer, or whose answer was marked down, most asked first

Both live in the audit record (atlas.api.audit), so they are kept, read and
deleted under the same rule as every other question.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field

from atlas.api import audit, tenancy
from atlas.api.authz import access_unavailable, authorize, require_org_admin

router = APIRouter()

Reason = Literal["wrong_answer", "wrong_source", "no_answer", "other"]
_SCAN = 2000          # newest entries read for the report; a page of the record


class FeedbackRequest(BaseModel):
    sheet: str = Field(..., min_length=1, max_length=200)
    question: str = Field(..., min_length=1, max_length=4000)
    rating: Literal["up", "down"]
    reason: Reason | None = None
    comment: str = Field("", max_length=500)
    sources: list[str] = Field(default_factory=list, max_length=20)


@router.post("/feedback", status_code=204)
async def give_feedback(body: FeedbackRequest, request: Request) -> Response:
    audit.note(request, "feedback", sheet=body.sheet, question=body.question,
               rating=body.rating, reason=body.reason, comment=body.comment.strip(),
               sources=[s[:300] for s in body.sources])
    # Only about a sheet the caller may read: feedback is also a question.
    await authorize(request, body.sheet, "read")
    return Response(status_code=204)


def _key(question: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", " ".join(question.lower().split()))


@router.get("/org/unanswered")
async def unanswered(request: Request, days: int = Query(30, ge=1, le=365)) -> dict[str, Any]:
    principal = require_org_admin(request)
    since = time.time() - days * 86400
    store = tenancy.get_tenancy()
    try:
        entries = await store.list_audit(principal.org_id, limit=_SCAN)
    except Exception as exc:
        raise access_unavailable() from exc
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for e in entries:
        detail = e.get("detail") or {}
        down = e["action"] == "feedback" and detail.get("rating") == "down"
        wanted = e["action"] == "unanswered" or down
        if e["ts"] < since or not wanted or not detail.get("question"):
            continue
        g = groups.setdefault((e.get("sheet", ""), _key(detail["question"])), {
            "sheet": e.get("sheet", ""), "question": detail["question"], "times": 0,
            "people": set(), "last": e["ts"], "why": Counter(), "comments": []})
        g["times"] += 1
        g["people"].add(e.get("actor", {}).get("id", ""))
        g["why"][detail.get("reason") or ("marked down" if down else "")] += 1
        if detail.get("comment") and len(g["comments"]) < 3:
            g["comments"].append(detail["comment"])
    rows = sorted(groups.values(), key=lambda g: (-g["times"], -g["last"]))
    return {"days": days, "scanned": len(entries), "questions": [
        {**g, "people": len(g["people"]), "why": dict(g["why"])} for g in rows[:200]]}
