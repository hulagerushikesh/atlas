#!/usr/bin/env python
"""Measure how much each metric moves between reruns, from stored reports.

Why this exists:
    `comparator` calls a delta insignificant below a floor, and that floor
    used to be one number — 0.02 — applied to every metric and justified as
    "a pragmatic choice". It was wrong in both directions at once: ten times
    too lax for answer_relevance, three times too tight for answer_correctness.
    The tight direction is the dangerous one, and it fired on 2026-10-19,
    printing "Overall winner: A" off 0.0565 of pure rerun movement.

    A floor should be measured, and measuring it needs no new runs. Reports
    store per-sample scores and the chunk ids each sample retrieved. Where two
    runs retrieved byte-identical evidence for a sample, the pipeline was given
    the same input twice, so whatever the metric does between them is what the
    metric does on a rerun. That is the floor.

What it separates, because the answer is not what the name suggests:
    - Rows where the generated answer text was *also* identical isolate the
      judges alone. They reproduce exactly: 0.0000, every observation.
    - Rows where the evidence matched but the answer text differed add the
      generator's own variance. This is where the movement lives — one
      reworded sentence swings an answer_correctness row by 0.5, because the
      metric counts facts present over a handful of facts.

    So "judge noise" is a misnomer for what the floor absorbs. It is generator
    noise, graded coarsely.

Reading the output:
    The per-row columns describe one sample. The aggregate column is the one
    a floor has to clear, and it is much smaller, because per-row jitter
    partly cancels in a mean. Set floors off the aggregate column, with
    headroom proportional to how few pairs there are.

Usage:
    .venv/bin/python scripts/measure_noise_floor.py
    .venv/bin/python scripts/measure_noise_floor.py --reports eval_data/reports
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from atlas.evaluation.comparator import noise_floor  # noqa: E402

_FAILED_SENTINEL = -1.0
_METRICS = (
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_relevance",
    "answer_correctness",
)


def _comparable_groups(reports: dict[str, dict[str, Any]]) -> list[list[str]]:
    """Reports that measured the same thing, so a difference means something.

    Keyed on both fingerprints and the config overrides. Without the
    fingerprints two runs over different label sets would be read as one
    pipeline disagreeing with itself; without the overrides, a deliberate
    change would be counted as noise, which is the exact mistake this script
    exists to stop other people making.
    """
    # A replay is a corrected copy of one run, not a second run of the same
    # pipeline. Pairing one against its source reports the correction as
    # rerun noise: doing exactly that put answer_correctness's per-row figure
    # at 1.0000 and raised its aggregate from 0.0565 to 0.0625, which would
    # have set the floor from a bug fix.
    superseded = {
        report["replayed_from"]
        for report in reports.values()
        if report.get("replayed_from")
    }
    groups: dict[tuple, list[str]] = defaultdict(list)
    for name, report in reports.items():
        if name in superseded:
            continue  # a corrected copy of this run exists; read that instead
        fingerprints = (report.get("dataset_fingerprint"), report.get("answers_fingerprint"))
        if None in fingerprints or "" in fingerprints:
            continue  # written before fingerprints existed; not comparable
        overrides = tuple(
            sorted((report.get("pipeline_config") or {}).get("overrides", {}).items())
        )
        groups[(*fingerprints, overrides)].append(name)
    return [sorted(names) for names in groups.values() if len(names) > 1]


def _scores(sample: dict[str, Any], metric: str) -> float | None:
    entry = next((m for m in sample["metrics"] if m["metric_name"] == metric), None)
    if entry is None or not entry.get("applicable", True):
        return None
    if entry["score"] == _FAILED_SENTINEL:
        return None
    return float(entry["score"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--reports", default="eval_data/reports", help="Directory of reports.")
    args = parser.parse_args()

    paths = sorted(Path(args.reports).glob("*.json"))
    if not paths:
        print(f"Error: no reports under {args.reports}", file=sys.stderr)
        return 1
    reports = {p.name: json.loads(p.read_text()) for p in paths}

    groups = _comparable_groups(reports)
    if not groups:
        print("No two reports share a dataset fingerprint and a config; nothing to measure.")
        return 1

    per_row_judge: dict[str, list[float]] = defaultdict(list)
    per_row_all: dict[str, list[float]] = defaultdict(list)
    aggregate: dict[str, list[float]] = defaultdict(list)
    # Every score seen, so a metric that never moved can be told apart from a
    # metric that never left one value. Those read identically in a column of
    # zeroes and mean opposite things: the first is a measurement, the second
    # is an absence of one.
    observed: dict[str, set[float]] = defaultdict(set)
    pairs = 0

    for names in groups:
        for name_a, name_b in itertools.combinations(names, 2):
            a = {s["sample_id"]: s for s in reports[name_a]["sample_results"]}
            b = {s["sample_id"]: s for s in reports[name_b]["sample_results"]}
            shared = [
                k for k in sorted(set(a) & set(b))
                if a[k]["retrieved_chunk_ids"] == b[k]["retrieved_chunk_ids"]
            ]
            if not shared:
                continue
            pairs += 1
            for metric in _METRICS:
                signed: list[float] = []
                for key in shared:
                    sa, sb = _scores(a[key], metric), _scores(b[key], metric)
                    if sa is None or sb is None:
                        continue
                    signed.append(sb - sa)
                    observed[metric].update((sa, sb))
                    bag = (
                        per_row_judge
                        if a[key]["generated_answer"] == b[key]["generated_answer"]
                        else per_row_all
                    )
                    bag[metric].append(abs(sb - sa))
                if signed:
                    aggregate[metric].append(abs(st.mean(signed)))

    observations = sum(len(v) for v in per_row_judge.values()) + sum(
        len(v) for v in per_row_all.values()
    )
    print(f"\n{pairs} comparable report pair(s), {observations} paired row observations\n")
    header = (
        f"{'metric':<19} {'judge only':>11} {'+generator':>11} "
        f"{'aggregate':>10} {'floor':>7}  verdict"
    )
    print(header)
    print("-" * len(header))
    for metric in _METRICS:
        judged = per_row_judge.get(metric, [])
        allrows = per_row_all.get(metric, [])
        aggs = aggregate.get(metric, [])
        if not aggs:
            continue
        worst = max(aggs)
        floor = noise_floor(metric)
        values = observed.get(metric, set())
        if not allrows and not judged:
            verdict = "no data"
        elif len(values) == 1:
            # Never moved because it never left one value. Calling that
            # "deterministic" would turn an absence of evidence into a
            # measurement, and the floor resting on it is an assumption.
            only = next(iter(values))
            verdict = f"UNVARIED — every observation was {only:.2f}; floor is an assumption"
        elif worst == 0.0:
            verdict = "deterministic on reruns"
        elif floor < worst:
            verdict = f"FLOOR TOO LOW — noise reaches {worst:.4f}"
        else:
            verdict = f"ok ({floor / worst:.1f}x headroom)" if worst else "ok"
        print(
            f"{metric:<19} "
            f"{(max(judged) if judged else 0.0):>11.4f} "
            f"{(max(allrows) if allrows else 0.0):>11.4f} "
            f"{worst:>10.4f} {floor:>7.3f}  {verdict}"
        )
    print(
        "\njudge only  = biggest per-row move where the answer text was identical too"
        "\n+generator  = biggest per-row move where only the evidence matched"
        "\naggregate   = biggest shift in the run mean; this is what a floor must clear"
    )
    too_low = [m for m in _METRICS if aggregate.get(m) and noise_floor(m) < max(aggregate[m])]
    if too_low:
        print(f"\nFloors below measured noise: {', '.join(too_low)} — update _NOISE_FLOORS.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
