"""
Reconcile the per-key Firestore usage counters against what production served.

Why this exists:
    Three writes on the `/query` path are deliberately not awaited — the
    per-key usage record, the cache write, and (on the cache-hit branch) a
    second usage record. `atlas.api.background` holds a reference to each one
    and drains what is still in flight at shutdown, but on 2026-10-23 the
    drain was found to be unobservable in production: in the whole retained
    log history no Atlas instance has ever logged `atlas_shutdown`, because
    the service runs with request-scoped CPU and SIGTERM work is throttled to
    near-zero before SIGKILL arrives.

    That left a question the code cannot answer about itself: how much is
    actually being lost? `BUDGET.md`'s `cost / query` is divided out of these
    counters, so the answer decides whether that figure can be quoted at all.
    The two fixes on the table — always-allocated CPU, or a synchronous
    Firestore round trip on every response — both cost something real and
    neither is worth pricing before the loss is a number.

What it compares, and why these two sources:
    The denominator is Cloud Run's own **request** log, not the application's
    stdout. Request entries are written by the infrastructure, so an
    application that drops a line, dies mid-write or never gets scheduled
    cannot make one disappear; `query_complete` can, and does. On the first
    run of this script the stdout stream had lost one of 39 requests outright
    and one `request_complete` line from a request that did log everything
    else — roughly 2.5%, all of it during a twelve-way concurrent burst —
    while the Firestore counters had lost nothing at all. The instrument the
    backlog proposed as trustworthy turned out to be the lossier of the two.

    The numerator is `usage.total_queries` on each key document, which is what
    the counters actually promise: one increment per served query, cache hits
    included.

Two corrections the raw difference needs, both of them history rather than loss:
    * Queries served before a key's first Cloud Run request — a key created
      and exercised locally against production Firestore before the first
      revision booted. Found by comparing the key's `created_at` with the
      first request in the log.
    * Streamed queries served before 2026-10-23. Until that day the streaming
      path charged the daily cap and nothing else, so a streamed query is a
      200 in the request log with no per-key record behind it, by design at
      the time. They are counted from `query_stream_start`, which is the only
      line that distinguishes them: streaming and non-streaming share one URL
      and one method, and the middleware closes a streamed request in tens of
      milliseconds while the body is still being written.

Costs nothing: Cloud Logging reads and a handful of Firestore document reads.

Usage:
    .venv/bin/python scripts/reconcile_usage.py
    .venv/bin/python scripts/reconcile_usage.py --project atlas-rag-rush --days 45
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from typing import Any

SERVICE = "atlas-api"
COLLECTION = "atlas_api_keys"
# The day the streaming path started writing a per-key record (commit ed9dbd0,
# deployed as atlas-api-00026-zcx). Streamed queries before this are expected
# to be missing from the counters and are not counted as loss.
STREAM_CHARGED_FROM = "2026-10-23"


def _run(cmd: list[str]) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if out.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd[:3])}...\n{out.stderr.strip()}")
    return out.stdout


def _logs(project: str, days: int, extra: str) -> list[dict[str, Any]]:
    base = f'resource.type="cloud_run_revision" AND resource.labels.service_name="{SERVICE}"'
    raw = _run([
        "gcloud", "logging", "read", f"{base} AND {extra}",
        f"--project={project}", f"--freshness={days}d", "--format=json",
    ])
    return list(json.loads(raw or "[]"))


def _oldest_retained(project: str, days: int) -> str:
    """Timestamp of the oldest log entry the bucket still holds for the service.

    This, not the first `/query` in the window, is what decides whether a key
    can be reconciled: a key created inside the retained window has every one
    of its queries in the request log, whatever it did first.
    """
    base = f'resource.type="cloud_run_revision" AND resource.labels.service_name="{SERVICE}"'
    raw = _run([
        "gcloud", "logging", "read", base, f"--project={project}",
        f"--freshness={days}d", "--order=asc", "--limit=1", "--format=json",
    ])
    rows = json.loads(raw or "[]")
    return str(rows[0]["timestamp"]) if rows else "9999"


def _keys(project: str) -> list[dict[str, Any]]:
    token = _run(["gcloud", "auth", "print-access-token"]).strip()
    url = (
        f"https://firestore.googleapis.com/v1/projects/{project}"
        f"/databases/(default)/documents/{COLLECTION}?pageSize=200"
    )
    raw = _run(["curl", "-s", "-H", f"Authorization: Bearer {token}", url])
    body = json.loads(raw)
    if "error" in body:
        sys.exit(f"firestore: {body['error'].get('message')}")
    return list(body.get("documents", []))


def _num(field: dict[str, Any]) -> float:
    if "integerValue" in field:
        return int(field["integerValue"])
    if "doubleValue" in field:
        return float(field["doubleValue"])
    return 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default="atlas-rag-rush")
    # Default 45 rather than 30: the bucket keeps 30 days, and asking for more
    # than is retained returns everything there is instead of failing, which is
    # what makes "the whole history" checkable when the service is young.
    ap.add_argument("--days", type=int, default=45)
    args = ap.parse_args()

    served = [
        r for r in _logs(
            args.project, args.days,
            f'logName="projects/{args.project}/logs/run.googleapis.com%2Frequests"'
            ' AND httpRequest.requestUrl:"/query"',
        )
        if r["httpRequest"].get("status") == 200
    ]
    streamed = _logs(args.project, args.days, 'jsonPayload.event="query_stream_start"')
    failed_writes = _logs(args.project, args.days, 'jsonPayload.event="usage_log_failed"')
    failed_tasks = _logs(args.project, args.days, 'jsonPayload.event="background_task_failed"')
    drains = _logs(args.project, args.days, 'jsonPayload.event="background_drain_start"')

    served.sort(key=lambda r: r["timestamp"])
    if not served:
        print("no successful /query requests in the window")
        return 0
    stream_ts = sorted(r["timestamp"] for r in streamed)
    uncharged_streams = [t for t in stream_ts if t[:10] < STREAM_CHARGED_FROM]

    docs = sorted(_keys(args.project), key=lambda d: _num(d["fields"]["created_at"]))
    retained_from = _oldest_retained(args.project, args.days)
    print(f"retained log from {retained_from}")
    print(f"window: {served[0]['timestamp']} .. {served[-1]['timestamp']}")
    print(f"served (Cloud Run POST /query -> 200): {len(served)}")
    print(f"streamed, before {STREAM_CHARGED_FROM} (no per-key record by design): "
          f"{len(uncharged_streams)}")
    print(f"usage_log_failed: {len(failed_writes)}   background_task_failed: {len(failed_tasks)}"
          f"   drains observed: {len(drains)}")
    print()

    total_loss = reconciled = unreconciled = 0
    for doc in docs:
        f = doc["fields"]
        name = f.get("name", {}).get("stringValue", "?")
        created = dt.datetime.fromtimestamp(_num(f["created_at"]), dt.UTC).isoformat()
        usage = f.get("usage", {}).get("mapValue", {}).get("fields", {})
        counted = int(_num(usage.get("total_queries", {})))
        # A key owns every request from its own creation until the next key's,
        # which is exact here because the keys were used one at a time. With
        # overlapping keys this becomes an upper bound and the request log
        # would have to carry the key id to do better.
        later = [d for d in docs if _num(d["fields"]["created_at"]) > _num(f["created_at"])]
        end = (
            dt.datetime.fromtimestamp(_num(later[0]["fields"]["created_at"]), dt.UTC).isoformat()
            if later else "9999"
        )
        print(f"{name:<12} created {created}")
        if created < retained_from:
            # The counters are lifetime; the log bucket keeps 30 days. A key
            # that predates the oldest retained request cannot be reconciled
            # at all, and saying so is the only honest result — counting its
            # queries as lost would report retention as data loss.
            print(f"  not reconcilable: created before the retained log"
                  f" ({retained_from})")
            print(f"  firestore total_queries {counted:>4}")
            unreconciled += counted
            continue
        mine = [r for r in served if created <= r["timestamp"] < end]
        mine_streams = [t for t in uncharged_streams if created <= t < end]
        expected = len(mine) - len(mine_streams)
        loss = expected - counted
        total_loss += max(loss, 0)
        reconciled += expected
        print(f"  served {len(mine):>4}  - uncharged streams {len(mine_streams):>3}"
              f"  = expected {expected:>4}")
        print(f"  firestore total_queries {counted:>4}   difference {loss:+d}")
        if loss < 0:
            # More counted than served is never a lost write. Cloud Logging
            # deletes lazily, so the boundary above is approximate and a
            # request can age out while an older entry is still returned; a
            # key exercised locally against production Firestore before the
            # first revision booted looks the same from here.
            print("  (negative is not loss: those queries are older than the"
                  " request log still holds, or were served outside Cloud Run)")
    print()
    print(f"reconciled {reconciled} queries, lost writes: {total_loss}")
    if unreconciled:
        print(f"{unreconciled} queries on keys older than the retained window were not checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
