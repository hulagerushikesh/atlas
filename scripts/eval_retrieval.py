"""
Retrieval-only evaluation: context precision and recall, no LLM stages.

Why this exists alongside run_eval.py:
    The full harness routes, decomposes, generates and judges — four LLM calls
    per question, ≈₹0.3 a run. Most retrieval work (tokenisers, fusion weights,
    rerank windows) cannot move faithfulness or answer relevance at all, so
    paying for them to measure a BM25 change is waste. This runs the retriever
    alone: one embedding call per question, ≈₹0.01 for the set, and the numbers
    are deterministic run to run.

    It is a different measurement from run_eval.py, not a cheaper copy of it:
    there is no query decomposition here, so a complex question retrieves once
    instead of once per sub-question. Compare its numbers with its own, never
    with a published full-eval score.

Usage:
    .venv/bin/python scripts/eval_retrieval.py
    .venv/bin/python scripts/eval_retrieval.py --dataset eval_data/fastapi_dataset.json
    .venv/bin/python scripts/eval_retrieval.py --set retrieval.top_k=30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from atlas.api.namespaces import NamespaceRegistry, SharedComponents  # noqa: E402
from atlas.config import get_settings  # noqa: E402
from atlas.evaluation.doc_match import chunk_matches, recalled_ids  # noqa: E402
from atlas.evaluation.overrides import apply_overrides, parse_override  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--dataset", default="eval_data/fastapi_dataset.json")
    p.add_argument("--namespace", default="default")
    p.add_argument(
        "--set", dest="overrides", action="append", default=[],
        metavar="SECTION.FIELD=VALUE",
        help="Override a setting for this run, e.g. retrieval.top_k=30. Repeatable.",
    )
    p.add_argument("--json", action="store_true", help="Print the report as JSON only.")
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    settings = get_settings()
    if args.overrides:
        settings = apply_overrides(settings, dict(parse_override(o) for o in args.overrides))

    registry = NamespaceRegistry(SharedComponents(settings))
    retriever = registry.get(args.namespace).pipeline._retriever
    samples = json.loads(Path(args.dataset).read_text())["samples"]

    precisions: list[float] = []
    recalls: list[float] = []
    misses: list[dict[str, object]] = []
    started = time.perf_counter()

    for sample in samples:
        relevant = set(sample["relevant_doc_ids"])
        if not relevant:
            continue  # out-of-scope question: the router, not the retriever, owns it
        result = await retriever.retrieve(sample["question"])
        chunks = result.chunks[: settings.reranker.top_k]
        hits = [c for c in chunks if chunk_matches(c, relevant)]
        precisions.append(len(hits) / len(chunks) if chunks else 0.0)
        found = recalled_ids(chunks, relevant)
        recalls.append(len(found) / len(relevant))
        if found != relevant:
            misses.append({"id": sample["id"], "missing": sorted(relevant - found)})

    n = len(recalls)
    report = {
        "questions": n,
        "context_precision": round(sum(precisions) / n, 4),
        "context_recall": round(sum(recalls) / n, 4),
        "fully_recalled": n - len(misses),
        "seconds": round(time.perf_counter() - started, 1),
        "overrides": args.overrides,
        "misses": misses,
    }

    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    print(f"\ncontext precision : {report['context_precision']:.4f}")
    print(f"context recall    : {report['context_recall']:.4f}")
    print(f"fully recalled    : {report['fully_recalled']}/{n}")
    print(f"elapsed           : {report['seconds']}s")
    for miss in misses:
        print(f"  miss {miss['id']}: {', '.join(miss['missing'])}")  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
