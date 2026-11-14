#!/usr/bin/env python3
"""
weekly_check.py — ask the live site one real question; exit 1 if anything is wrong.

Run every Monday by .github/workflows/weekly-check.yml, which opens a GitHub
issue (and so emails the owner) only when this exits 1. Standard library only,
so the workflow installs nothing. The one keyless question costs about ₹0.20,
so four or five runs a month stay under ₹1.

Usage:
    python3 scripts/weekly_check.py [--report report.md]
    python3 scripts/weekly_check.py --test-alert   # fail on purpose, ask nothing, ₹0
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

BASE = "https://atlas.hulage.in"
SHEET = "duckdb"
QUESTION = "What type does X'CAFE' produce in DuckDB?"
# The DuckDB 2.0 answer. A model answering from memory says VARCHAR, so this
# word only appears when retrieval found the right page.
EXPECT = "BLOB"


@dataclass
class Response:
    status: int  # 0 when the site could not be reached at all
    body: Any  # parsed JSON, or the raw text when it is not JSON


Fetch = Callable[[str, str, dict[str, Any] | None], Response]


def http_fetch(method: str, url: str, payload: dict[str, Any] | None = None) -> Response:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "User-Agent": "atlas-weekly-check"},
    )
    try:
        # Generous: a cold start loads the reranker before answering (~12 s).
        with urllib.request.urlopen(req, timeout=150) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError) as e:
        return Response(0, f"unreachable: {e}")
    text = raw.decode("utf-8", "replace")
    try:
        return Response(status, json.loads(text))
    except ValueError:
        return Response(status, text)


def _code(r: Response) -> str:
    detail = r.body.get("detail") if isinstance(r.body, dict) else None
    return str(detail.get("code", "")) if isinstance(detail, dict) else ""


def _status(r: Response) -> str:
    return str(r.status) if r.status else "no answer at all"


def check_pages(fetch: Fetch) -> list[str]:
    problems = []
    for path in ("/", "/app"):
        r = fetch("GET", BASE + path, None)
        if r.status != 200:
            problems.append(f"The page {BASE}{path} returned {_status(r)}.")
    return problems


def check_health(fetch: Fetch) -> list[str]:
    r = fetch("GET", BASE + "/health", None)
    if r.status != 200 or not isinstance(r.body, dict):
        return [f"The server's health page returned {_status(r)}."]
    problems = []
    if r.body.get("status") != "ok":
        problems.append(f"The server reports its health as {r.body.get('status')!r}.")
    qdrant = (r.body.get("components") or {}).get("qdrant") or {}
    if qdrant.get("status") != "ok":
        problems.append(f"The search database reports {qdrant.get('status')!r}.")
    return problems


def check_question(fetch: Fetch) -> tuple[list[str], list[str]]:
    """Returns (problems, notes). A used-up free allowance is a note, not a fault."""
    r = fetch("POST", BASE + "/query", {"query": QUESTION, "namespace": SHEET})
    code = _code(r)
    if r.status == 429:
        return [], [f"The test question was not asked: the free allowance was in use ({code})."]
    if r.status == 503 and code == "demo_paused":
        return ["The demo is paused: Gemini has no credit left. Top up the prepaid balance."], []
    if r.status != 200 or not isinstance(r.body, dict):
        return [f"The test question returned {_status(r)} {code}".rstrip() + "."], []

    problems = []
    if EXPECT not in str(r.body.get("answer", "")):
        problems.append(f"The answer no longer says {EXPECT}; the documents or the search changed.")
    if not r.body.get("citations"):
        problems.append("The answer carried no citations.")
    if r.body.get("is_faithful") is not True:
        score = r.body.get("faithfulness_score")
        problems.append(f"The answer failed its own grounding check (score {score}).")
    cost = (r.body.get("token_usage") or {}).get("estimated_cost_usd")
    notes = [f"The test question cost ${cost:.4f}."] if isinstance(cost, (int, float)) else []
    return problems, notes


def run(fetch: Fetch, test_alert: bool = False) -> tuple[bool, str]:
    if test_alert:
        problems = ["This is a test alert. Nothing is wrong; it shows an alert reaches you."]
        notes = ["Next: close this issue. The real check runs every Monday."]
        return False, format_report(problems, notes, advise=False)
    else:
        problems = check_pages(fetch) + check_health(fetch)
        asked, notes = check_question(fetch)
        problems += asked
    return not problems, format_report(problems, notes)


def format_report(problems: list[str], notes: list[str], advise: bool = True) -> str:
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    if not problems:
        head = f"**Atlas weekly check, {day}: all good.**"
    else:
        n = len(problems)
        head = f"**Atlas weekly check, {day}: {n} problem{'s' if n > 1 else ''}.**"
    lines = [head, ""] + [f"- {p}" for p in problems]
    if notes:
        lines += ["", *(f"- {x}" for x in notes)]
    if problems and advise:
        lines += [
            "",
            f"Next: open {BASE}/app and ask the suggested question to see it yourself. "
            "Close this issue once it is fixed; next Monday's check opens a new one "
            "if it is still broken.",
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, fetch: Fetch = http_fetch) -> int:
    parser = argparse.ArgumentParser(description="Check the live Atlas site.")
    parser.add_argument("--report", help="Also write the report to this file.")
    parser.add_argument("--test-alert", action="store_true", help="Fail on purpose.")
    args = parser.parse_args(argv)

    ok, report = run(fetch, args.test_alert)
    print(report)
    for path in filter(None, (args.report, os.environ.get("GITHUB_STEP_SUMMARY"))):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(report)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
