"""
How often does evidence reuse (E2.5) serve a reworded question, and how often
would it serve the wrong one? Runs the real `EvidenceReuse` with the live
search and the live fit check.

Each test-set question is stored with its reference answer (no answers are
generated); each of its three rewordings then asks. A negative control asks
every *other* original against each stored one, so the hit rate cannot hide
wrong reuse. Cost: one search and one embedding per question plus one fit
check per candidate, well under ₹1 for the set.

Usage:
    .venv/bin/python scripts/measure_reuse_hits.py --namespace duckdb
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from atlas.api.namespaces import NamespaceRegistry, SharedComponents  # noqa: E402
from atlas.api.reuse import EvidenceReuse  # noqa: E402
from atlas.config import get_settings  # noqa: E402
from atlas.cost import estimate_usage_cost  # noqa: E402
from atlas.usage import usage_scope  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--paraphrases", default="eval_data/paraphrase_reuse.json")
    p.add_argument("--answers", default="eval_data/duckdb_dataset.json")
    p.add_argument("--namespace", default="duckdb")
    p.add_argument("--out", default="eval_data/reports")
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))
    groups = json.loads(Path(args.paraphrases).read_text())["groups"]
    answers = {s["id"]: s["ground_truth_answer"]
               for s in json.loads(Path(args.answers).read_text())["samples"]}
    groups = [g for g in groups if g["id"] in answers]

    settings = get_settings()
    shared = SharedComponents(settings)
    registry = NamespaceRegistry(shared)
    await registry.reconcile_sparse(args.namespace)
    pipeline = registry.get(args.namespace).pipeline
    config = settings.reuse

    async def probe(reuse: EvidenceReuse, q: str):  # type: ignore[no-untyped-def]
        found = await pipeline._retrieve_all([q], q)
        return await reuse.probe(q, [c.chunk_id for c in found.chunks]), found.chunks

    with usage_scope() as usage:
        stored = {}
        for g in groups:
            stored[g["id"]] = await probe(EvidenceReuse(shared.embedder, shared.llm, config),
                                          g["original"])

        def one(gid: str) -> EvidenceReuse:
            reuse = EvidenceReuse(shared.embedder, shared.llm, config)
            p, chunks = stored[gid]
            reuse.remember("sheet", "v", next(g["original"] for g in groups if g["id"] == gid),
                           p, [list(c.metadata.acl) for c in chunks],
                           {"answer": answers[gid], "id": gid})
            return reuse

        rewordings = []
        for g in groups:
            reuse = one(g["id"])
            for style, q in zip(("casual", "keywords", "long"), g["paraphrases"], strict=True):
                p, _ = await probe(reuse, q)
                hit = await reuse.find("sheet", "v", q, p, None)
                rewordings.append({"group": g["id"], "style": style, "reused": hit is not None})

        wrong = []
        for g in groups:
            reuse = one(g["id"])
            for other in groups:
                if other["id"] == g["id"]:
                    continue
                p, _ = await probe(reuse, other["original"])
                if await reuse.find("sheet", "v", other["original"], p, None) is not None:
                    wrong.append(f"{g['id']} served to {other['id']}")

    hits = sum(r["reused"] for r in rewordings)
    pairs = len(groups) * (len(groups) - 1)
    report = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "namespace": args.namespace,
        "config": config.model_dump(),
        "questions": len(groups),
        "rewordings": len(rewordings),
        "rewordings_reused_pct": round(100 * hits / len(rewordings), 1),
        "by_style_pct": {
            s: round(100 * sum(r["reused"] for r in rewordings if r["style"] == s)
                     / sum(1 for r in rewordings if r["style"] == s), 1)
            for s in ("casual", "keywords", "long")
        },
        "unrelated_pairs": pairs,
        "unrelated_served_wrongly": wrong,
        "cost_usd": round(estimate_usage_cost(usage.by_model), 5),
        "rows": rewordings,
    }
    out = Path(args.out) / f"reuse-hits_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))
    print(f"\nwritten: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
