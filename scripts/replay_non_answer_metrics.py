#!/usr/bin/env python
"""Rescore a stored report's declined rows under the current metrics, for free.

Why this exists:
    On 2026-10-19 the router started correctly refusing out-of-scope
    questions, and the eval harness turned out not to recognise the message it
    refuses with. `answer_correctness` scored `fq-016` 0.000 with the reasoning
    "the pipeline answered instead of refusing"; `answer_relevance` averaged
    its 0.41 into the headline; `faithfulness` audited "This question appears
    to be outside the scope..." as two supported claims and returned 1.0. The
    pipeline got better and three published numbers got worse.

    Finding that after a ₹6 run should not cost another ₹6. Every metric that
    skips a declined answer short-circuits *before* its model call — the
    verdict is a string comparison — so the rows the fix touches can be
    replayed from the stored answers with no network at all. Rows that were
    really answered are left exactly as the run scored them; this does not
    re-judge a run, it corrects the handful of rows a judge never saw.

Trust check:
    The metrics are constructed with a provider that raises on any call, so a
    row that would reach the model aborts the replay instead of quietly
    costing money. The printed cost of a successful replay is therefore ₹0 as
    a consequence rather than as a claim.

Usage:
    .venv/bin/python scripts/replay_non_answer_metrics.py \
        eval_data/reports/router-scope_20261019-202434.json
    .venv/bin/python scripts/replay_non_answer_metrics.py REPORT --write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from atlas.evaluation.metrics import (  # noqa: E402
    AnswerCorrectnessMetric,
    AnswerRelevanceMetric,
    FaithfulnessMetric,
)
from atlas.orchestration.generator import is_non_answer  # noqa: E402

_FAILED_SENTINEL = -1.0
_REPLAYABLE = ("faithfulness", "answer_relevance", "answer_correctness")


def _no_network() -> AsyncMock:
    """A provider that makes a paid call impossible rather than unlikely."""
    stub = AsyncMock()
    stub.generate = AsyncMock(
        side_effect=AssertionError("replay tried to call the model — refusing to pay")
    )
    stub.embed_texts = AsyncMock(
        side_effect=AssertionError("replay tried to call the embedder — refusing to pay")
    )
    return stub


def _aggregate(sample_results: list[dict[str, Any]]) -> dict[str, float]:
    """Reproduce runner.py's denominator: applicable, non-failed rows only."""
    agg: dict[str, float] = {}
    names = {m["metric_name"] for sr in sample_results for m in sr["metrics"]}
    for name in sorted(names):
        values = [
            m["score"]
            for sr in sample_results
            for m in sr["metrics"]
            if m["metric_name"] == name
            and m["score"] != _FAILED_SENTINEL
            and m.get("applicable", True)
        ]
        agg[name] = round(mean(values), 4) if values else 0.0
    return agg


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("report", help="Path to a stored eval report JSON.")
    parser.add_argument(
        "--write", action="store_true",
        help="Save the corrected report alongside the original, suffixed -replayed.",
    )
    args = parser.parse_args()

    path = Path(args.report)
    if not path.exists():
        print(f"Error: report not found: {path}", file=sys.stderr)
        return 1
    report = json.loads(path.read_text())

    stub = _no_network()
    metrics = {
        "faithfulness": FaithfulnessMetric(stub),
        "answer_relevance": AnswerRelevanceMetric(stub, stub),
        "answer_correctness": AnswerCorrectnessMetric(stub),
    }

    before = dict(report.get("aggregate_scores", {}))
    changes: list[tuple[str, str, float, float]] = []

    for sample in report["sample_results"]:
        answer = sample["generated_answer"]
        if not is_non_answer(answer):
            continue
        for name in _REPLAYABLE:
            stored = next((m for m in sample["metrics"] if m["metric_name"] == name), None)
            if stored is None or stored["score"] == _FAILED_SENTINEL:
                continue
            fresh = await metrics[name].score(
                question=sample["question"],
                ground_truth_answer="",
                generated_answer=answer,
                retrieved_chunks=[],
                # An empty list is what marks a row out of scope, and a
                # replay cannot recover the dataset's labels from a report.
                # Only rows the dataset declared out of scope reach the
                # branch that cares, and those are the rows with no labels.
                relevant_doc_ids=[],
            )
            if (fresh.score, fresh.applicable) != (stored["score"], stored.get("applicable", True)):
                changes.append((sample["sample_id"], name, stored["score"], fresh.score))
            stored["score"] = fresh.score
            stored["applicable"] = fresh.applicable
            stored["reasoning"] = fresh.reasoning

    after = _aggregate(report["sample_results"])
    report["aggregate_scores"] = after

    if not changes:
        print("No declined rows scored differently; the report already reflects this code.")
        return 0

    print(f"\nReplayed {len(changes)} metric(s) on declined rows, 0 model calls:\n")
    for sample_id, name, old, new in changes:
        print(f"  {sample_id:<8} {name:<19} {old:.4f} -> {new:.4f}")
    print(f"\n{'metric':<19} {'as run':>9} {'replayed':>9} {'delta':>9}")
    for name in sorted(after):
        delta = after[name] - before.get(name, after[name])
        print(f"{name:<19} {before.get(name, 0.0):>9.4f} {after[name]:>9.4f} {delta:>+9.4f}")

    if args.write:
        out = path.with_name(f"{path.stem}-replayed.json")
        out.write_text(json.dumps(report, indent=1))
        print(f"\nWrote {out}")
    else:
        print("\n(not saved — pass --write to keep the corrected report)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
