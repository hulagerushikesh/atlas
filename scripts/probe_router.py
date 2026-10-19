"""
Router-only probe: what does the classifier say, and where is it wrong?

Why this exists alongside eval_retrieval.py and run_eval.py:
    The router is one LLM call with max_tokens=128. Measuring a router-prompt
    change through run_eval.py costs ≈₹0.3 and buries the answer under four
    other stages; measuring it through eval_retrieval.py is impossible, because
    that harness skips the router entirely. This runs the classifier alone over
    a dataset: ≈₹0.1 for the set, no Qdrant, no cross-encoder, no retrieval.

    It exists because the last router-prompt change measured at exactly zero.
    A prompt edit that is obviously right is still a hypothesis, and the only
    honest way to hold one is a before and an after on the same questions.

What it grades:
    The scope axis only — refused or not refused. `metadata.out_of_scope: true`
    means the row must classify `out_of_scope`; every other row must not. The
    simple/complex split is printed but not graded, because it changes the path
    a query takes rather than whether it gets an answer, and no dataset row
    carries a label for it.

    Both error directions are counted and named, because they are not
    symmetric and a prompt change usually trades one for the other:
      - wrongly_refused: an answerable question sent to the refusal path. This
        is the 2026-10-13 failure, where a whole uploaded corpus was refused
        before retrieval ran and the console reported it as having no
        references.
      - wrongly_answered: an out-of-scope question routed to retrieval, which
        returns a confident-looking wrong page and scores 0.000.

Usage:
    .venv/bin/python scripts/probe_router.py --dataset eval_data/fastapi_dataset.json
    .venv/bin/python scripts/probe_router.py --dataset ... --json > before.json
    .venv/bin/python scripts/probe_router.py --dataset ... --query "..." --expect out_of_scope
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import structlog

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from atlas.config import get_settings  # noqa: E402
from atlas.cost import estimate_usage_cost  # noqa: E402
from atlas.evaluation.dataset import DatasetError, load_dataset  # noqa: E402
from atlas.orchestration.llm import OpenAILLMProvider  # noqa: E402
from atlas.orchestration.router import QueryRouter  # noqa: E402
from atlas.usage import usage_scope  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Classify a dataset's questions, router only.")
    p.add_argument("--dataset", help="Path to an EvalDataset JSON.")
    p.add_argument("--namespace", default="default", help="Picks which domain sentence applies.")
    p.add_argument(
        "--query", action="append", default=[], metavar="TEXT",
        help="An extra question to classify, outside any dataset. Repeatable.",
    )
    p.add_argument(
        "--expect", action="append", default=[], metavar="CLASS",
        help="Expected scope for the matching --query: out_of_scope or in_scope. "
             "Repeatable, positional against --query. Unpaired queries are "
             "classified and printed but not graded.",
    )
    p.add_argument("--json", action="store_true", help="Print the report as JSON only.")
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    if args.json:
        # Same reason as eval_retrieval.py: structlog writes to stdout, so
        # --json would otherwise hand a parser a stream of log lines with an
        # object at the end of it.
        structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))

    if not args.dataset and not args.query:
        print("Error: pass --dataset, --query, or both.", file=sys.stderr)
        return 1

    # (id, question, expected_out_of_scope or None for ungraded)
    rows: list[tuple[str, str, bool | None]] = []

    if args.dataset:
        dataset_path = Path(args.dataset)
        if not dataset_path.exists():
            print(f"Error: dataset not found: {dataset_path}", file=sys.stderr)
            return 1
        try:
            dataset, notes = load_dataset(dataset_path)
        except DatasetError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        for note in notes:
            print(f"Warning: {note}", file=sys.stderr)
        for sample in dataset.samples:
            rows.append(
                (sample.id, sample.question, bool(sample.metadata.get("out_of_scope", False)))
            )

    for i, query in enumerate(args.query):
        expected: bool | None = None
        if i < len(args.expect):
            raw = args.expect[i]
            if raw not in {"out_of_scope", "in_scope"}:
                print(f"Error: --expect must be out_of_scope or in_scope, got {raw!r}",
                      file=sys.stderr)
                return 1
            expected = raw == "out_of_scope"
        rows.append((f"adhoc-{i + 1}", query, expected))

    settings = get_settings()
    # Resolve the domain sentence per namespace exactly as NamespaceRegistry
    # does. Passing `settings.router` straight through would probe the default
    # namespace's domain whatever --namespace said, which is the one mistake
    # this script exists to catch in other people's prompts.
    router_cfg = settings.router.model_copy(
        update={"domain": settings.router.domain_for(args.namespace)}
    )
    # No registry, no SharedComponents: those load the cross-encoder and open a
    # Qdrant client, neither of which the router touches.
    router = QueryRouter(OpenAILLMProvider(settings.openai), router_cfg)
    domain = router_cfg.domain

    results: list[dict[str, object]] = []
    started = time.perf_counter()
    with usage_scope() as usage:
        classifications = await asyncio.gather(
            *(router.classify(question) for _, question, _ in rows)
        )

    wrongly_refused: list[str] = []
    wrongly_answered: list[str] = []
    for (rid, question, expected), classification in zip(rows, classifications, strict=True):
        refused = classification == "out_of_scope"
        verdict = "ungraded"
        if expected is not None:
            if expected and not refused:
                verdict = "wrongly_answered"
                wrongly_answered.append(rid)
            elif not expected and refused:
                verdict = "wrongly_refused"
                wrongly_refused.append(rid)
            else:
                verdict = "ok"
        results.append({
            "id": rid,
            "question": question,
            "classification": classification,
            "expected_out_of_scope": expected,
            "verdict": verdict,
        })

    graded = [r for r in results if r["verdict"] != "ungraded"]
    report = {
        "domain": domain,
        "namespace": args.namespace,
        "rows": len(results),
        "graded": len(graded),
        "correct": sum(1 for r in graded if r["verdict"] == "ok"),
        "wrongly_refused": wrongly_refused,
        "wrongly_answered": wrongly_answered,
        "seconds": round(time.perf_counter() - started, 1),
        "tokens": usage.total_tokens,
        "cost_usd": estimate_usage_cost(usage.by_model),
        "results": results,
    }

    if args.json:
        print(json.dumps(report, indent=1))
        return 0

    print(f"\ndomain: {domain}\n")
    for r in results:
        mark = {"ok": "  ", "ungraded": " ?", "wrongly_refused": "!!",
                "wrongly_answered": "!!"}[str(r["verdict"])]
        print(f"{mark} {r['id']:<9} {str(r['classification']):<13} {str(r['question'])[:62]}")
    print(f"\ncorrect on scope  : {report['correct']}/{report['graded']}")
    print(f"wrongly refused   : {len(wrongly_refused)} {wrongly_refused or ''}")
    print(f"wrongly answered  : {len(wrongly_answered)} {wrongly_answered or ''}")
    print(f"tokens            : {report['tokens']}")
    print(f"cost              : ${report['cost_usd']:.6f}")
    print(f"elapsed           : {report['seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
