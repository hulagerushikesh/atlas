#!/usr/bin/env python3
"""
compare_reports.py — compare two stored eval reports. No API calls, no spend.

`make eval-compare` runs a fresh eval and compares it with a baseline, which
is the right thing when there is something new to measure and the wrong thing
when there is not. Re-judging two runs already on disk cost a full paid run
until 2026-10-17, when a comparator fix changed a verdict and the only way to
see the corrected verdict was to buy the measurement again.

Usage:
    python scripts/compare_reports.py A.json B.json
    python scripts/compare_reports.py A.json B.json --out report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two stored eval reports (free; reads JSON only)."
    )
    parser.add_argument("baseline", type=Path, help="Run A: the baseline report JSON.")
    parser.add_argument("candidate", type=Path, help="Run B: the report to judge.")
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Write the comparison markdown here as well as printing it.",
    )
    args = parser.parse_args()

    from atlas.evaluation.comparator import DatasetMismatch, compare, save_comparison
    from atlas.interfaces.evaluator import EvalResult

    try:
        a = EvalResult.model_validate(json.loads(args.baseline.read_text()))
        b = EvalResult.model_validate(json.loads(args.candidate.read_text()))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read a report: {exc}", file=sys.stderr)
        return 2

    try:
        comparison = compare(a, b)
    except DatasetMismatch as exc:
        # Not an error to hide: it is the comparator doing its job.
        print(f"Refusing to compare these runs — {exc}", file=sys.stderr)
        return 1

    print(comparison.as_markdown())
    if args.out:
        save_comparison(comparison, args.out)
        print(f"\nWritten to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
