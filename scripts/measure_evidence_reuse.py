"""
Would reworded questions reuse each other's evidence? (S2, docs/company-scale.md)

Runs the live retriever only (one embedding call per question, ≈₹0.01 for the
set; no answers generated) over groups of one question plus three rewordings,
and reports how often a rewording pulls the same top passages as the original,
alone and combined with how close the two questions are in meaning. A negative
control compares unrelated originals, so a hit rate cannot hide false matches.

Usage:
    .venv/bin/python scripts/measure_evidence_reuse.py --namespace duckdb
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from atlas.api.namespaces import NamespaceRegistry, SharedComponents  # noqa: E402
from atlas.config import get_settings  # noqa: E402

TOP = 5  # what the grader judges; the fingerprint logged in S1 covers these


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--dataset", default="eval_data/paraphrase_reuse.json")
    p.add_argument("--namespace", default="duckdb")
    p.add_argument("--out", default="eval_data/reports")
    return p.parse_args()


def _compare(a: dict[str, list[str]], b: dict[str, list[str]]) -> dict[str, object]:
    ca, cb = set(a["chunks"][:TOP]), set(b["chunks"][:TOP])
    da, db = set(a["docs"][:TOP]), set(b["docs"][:TOP])
    wide_a, wide_b = set(a["chunks"]), set(b["chunks"])
    return {
        "same_top1": a["chunks"][:1] == b["chunks"][:1],
        "shared_top5": len(ca & cb),
        "same_top5_set": ca == cb,
        "same_top5_docs": da == db,
        "jaccard_all": round(len(wide_a & wide_b) / len(wide_a | wide_b), 3)
        if wide_a | wide_b else 0.0,
    }


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = (sum(x * x for x in a) * sum(y * y for y in b)) ** 0.5
    return round(dot / norm, 4) if norm else 0.0


def _rate(rows: list[dict[str, object]], test: str) -> float:
    if "&cos>=" in test:
        shared, cos = test.split("&cos>=")
        need, floor = int(shared.split(">=")[1]), float(cos)
        hits = sum(1 for r in rows
                   if int(r["shared_top5"]) >= need and float(r["cos"]) >= floor)  # type: ignore[call-overload, arg-type]
    elif test.startswith("shared>="):
        need = int(test.split(">=")[1])
        hits = sum(1 for r in rows if int(r["shared_top5"]) >= need)  # type: ignore[call-overload]
    else:
        hits = sum(1 for r in rows if r[test])
    return round(100 * hits / len(rows), 1) if rows else 0.0


async def main() -> int:
    args = _parse_args()
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))
    data = json.loads(Path(args.dataset).read_text())
    groups = data["groups"]

    registry = NamespaceRegistry(SharedComponents(get_settings()))
    sync = await registry.reconcile_sparse(args.namespace)
    print(f"keyword index: {sync}", file=sys.stderr)
    retriever = registry.get(args.namespace).pipeline._retriever

    async def fetch(q: str) -> dict[str, list[str]]:
        chunks = (await retriever.retrieve(q)).chunks
        return {
            "chunks": [c.chunk_id for c in chunks],
            "docs": [c.metadata.source for c in chunks],
        }

    texts = [q for g in groups for q in (g["original"], *g["paraphrases"])]
    vectors = dict(zip(texts, (await registry._shared.embedder.embed_texts(texts)).vectors,
                       strict=True))

    started = time.perf_counter()
    pairs: list[dict[str, object]] = []
    originals: dict[str, dict[str, list[str]]] = {}
    for g in groups:
        base = await fetch(g["original"])
        originals[g["id"]] = base
        for style, para in zip(("casual", "keywords", "long"), g["paraphrases"], strict=True):
            pairs.append({"group": g["id"], "style": style,
                          "cos": _cosine(vectors[g["original"]], vectors[para]),
                          **_compare(base, await fetch(para))})

    ask = {g["id"]: g["original"] for g in groups}
    control = [
        {"group": f"{x}~{y}", "cos": _cosine(vectors[ask[x]], vectors[ask[y]]),
         **_compare(originals[x], originals[y])}
        for x, y in combinations(originals, 2)
    ]

    tests = ["same_top1", "same_top5_set", "shared>=4", "shared>=3", "same_top5_docs",
             "shared>=3&cos>=0.80", "shared>=3&cos>=0.85", "shared>=3&cos>=0.90"]
    report = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "namespace": args.namespace,
        "groups": len(groups),
        "rewordings": len(pairs),
        "seconds": round(time.perf_counter() - started, 1),
        "rewording_reuse_pct": {t: _rate(pairs, t) for t in tests},
        "by_style_shared>=4_pct": {
            s: _rate([p for p in pairs if p["style"] == s], "shared>=4")
            for s in ("casual", "keywords", "long")
        },
        "unrelated_false_match_pct": {t: _rate(control, t) for t in tests},
        "cos_rewordings_min_median": [min(p["cos"] for p in pairs),  # type: ignore[type-var]
                                      sorted(p["cos"] for p in pairs)[len(pairs) // 2]],  # type: ignore[type-var]
        "cos_unrelated_max": max(c["cos"] for c in control),  # type: ignore[type-var]
        "unrelated_pairs_sharing_4plus": [
            c["group"] for c in control if int(c["shared_top5"]) >= 4  # type: ignore[call-overload]
        ],
        "pairs": pairs,
        "control": control,
    }

    out = Path(args.out) / f"paraphrase-reuse_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k not in ("pairs", "control")}, indent=1))
    print(f"\nwritten: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
