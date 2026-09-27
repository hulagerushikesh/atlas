#!/usr/bin/env python
"""Recompute context_precision / context_recall from a stored report, for free.

Why this exists:
    Changing a dataset's `relevant_doc_ids` invalidates every precision and
    recall number ever measured against it, and the obvious way to find out
    what the new labels imply is to pay for another eval run. That is not
    necessary. A report stores the retrieved chunk ids, chunk ids are uuid5 of
    `(document_id(source), chunk_index)`, and both context metrics are pure
    set arithmetic over doc ids. So the whole comparison can be replayed
    offline against any label set, with no model calls.

    It cannot replay the judged metrics (faithfulness, answer_relevance) --
    those need the LLM, and a label change does not affect them anyway.

Trust check:
    Run it against the labels a report was actually scored with and the
    printed per-sample numbers must equal the stored ones. If they do not,
    the reverse map is wrong and nothing below it is worth reading, so the
    mismatch is reported rather than swallowed.

Usage:
    .venv/bin/python scripts/replay_context_metrics.py \
        eval_data/reports/ctx-headers_*.json --corpus data/corpus/fastapi
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from atlas.interfaces.document import chunk_id, document_id

# release-notes.md alone is well over a thousand chunks; the ceiling only has
# to exceed the longest document, and overshooting costs a few uuid5 calls.
_MAX_CHUNKS_PER_DOC = 4000


def build_reverse_map(corpus: Path) -> dict[str, str]:
    """chunk id -> corpus-relative doc id, the form datasets are written in."""
    rev: dict[str, str] = {}
    for path in sorted(corpus.rglob("*")):
        if not path.is_file():
            continue
        doc = document_id(str(path))
        rel = path.relative_to(corpus).with_suffix("").as_posix()
        for i in range(_MAX_CHUNKS_PER_DOC):
            rev[chunk_id(doc, i)] = rel
    return rev


def score(sources: list[str], relevant: set[str]) -> tuple[float, float]:
    hits = [s for s in sources if s in relevant]
    return len(hits) / len(sources), len(set(hits) & relevant) / len(relevant)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path)
    ap.add_argument("--dataset", type=Path, default=Path("eval_data/fastapi_dataset.json"))
    ap.add_argument("--corpus", type=Path, default=Path("data/corpus/fastapi"))
    args = ap.parse_args()

    rev = build_reverse_map(args.corpus)
    dataset = json.loads(args.dataset.read_text())
    labels = {s["id"]: set(s["relevant_doc_ids"]) for s in dataset["samples"]}
    report: dict[str, Any] = json.loads(args.report.read_text())

    precisions: list[float] = []
    recalls: list[float] = []
    unresolved = 0
    drift = 0

    for sample in report["sample_results"]:
        relevant = labels.get(sample["sample_id"], set())
        sources = [rev.get(c, "<unresolved>") for c in sample["retrieved_chunk_ids"]]
        unresolved += sources.count("<unresolved>")
        if not relevant:
            print(f"  {sample['sample_id']}  n/a (out of scope)")
            continue
        precision, recall = score(sources, relevant)
        precisions.append(precision)
        recalls.append(recall)

        stored = {m["metric_name"]: m["score"] for m in sample["metrics"]}
        moved = (
            abs(precision - stored["context_precision"]) > 1e-3
            or abs(recall - stored["context_recall"]) > 1e-3
        )
        drift += moved
        note = ""
        if moved:
            note = (
                f"   was p={stored['context_precision']:.4f}"
                f" r={stored['context_recall']:.4f}"
            )
        print(f"  {sample['sample_id']}  p={precision:.4f}  r={recall:.4f}{note}")

    n = len(precisions)
    print(f"\n  MEAN over {n}: precision {sum(precisions) / n:.4f}  recall {sum(recalls) / n:.4f}")
    print(f"  {drift} sample(s) differ from the stored scores.")
    if unresolved:
        # Either the corpus moved under the report or _MAX_CHUNKS_PER_DOC is
        # too low; both make the numbers above quietly too small.
        print(f"  WARNING: {unresolved} chunk id(s) did not map to any file in {args.corpus}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
