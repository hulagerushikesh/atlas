"""
A/B comparator: diff two EvalResults to surface metric improvements/regressions.

Design rationale:
    The comparator answers the exact question asked in interviews:
    "How did you prove that reranking improved context precision?"

    It produces:
    - Per-metric absolute delta (config_b - config_a)
    - A winner declaration per metric (positive delta = B wins)
    - An overall winner (most metrics improved)
    - A markdown table suitable for a PR description or portfolio README

    Statistical note: with ~30 eval samples, individual metric differences of
    < 0.02 are within noise — we flag these as "no significant change" to avoid
    over-claiming. The threshold (0.02) is a pragmatic choice; with larger
    datasets you'd use a proper significance test (Wilcoxon signed-rank, etc.).
    The ComparisonResult.is_significant dict makes this explicit rather than
    burying it in the numbers.

    We compare aggregate scores (means over all samples) rather than doing
    per-sample paired comparisons, which requires both runs to have covered
    the same samples. This docstring used to claim we raised ValueError when
    they had not. We did not — there was no check at all, and `compare` would
    happily declare an overall winner between a 30-question HR run and a
    15-question FastAPI one. It does check now, on three things, in order of
    how much they prove:

      - **The sample ids.** Derived from `sample_results`, so this works on
        every report ever written, including the ones from before any of
        these fields existed. Different rows means different denominators and
        the means are not comparable.
      - **The dataset fingerprint.** The strongest of the three and the only
        one that catches a relabelling: on 2026-09-27 nine of fifteen rows
        were relabelled while the file kept its name and all fifteen ids, and
        every precision and recall number recorded before that edit stopped
        being comparable with every one after it. Nothing said so.
      - **The dataset name.** Weakest, checked last, and only worth anything
        for the error message it produces.

    A report written before the fingerprint existed carries an empty one.
    That is reported as a note on the comparison and printed with it, rather
    than passed over: not knowing whether two runs match is a different state
    from knowing they do, and the whole class of fault here is the second
    being assumed from the first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from atlas.interfaces.evaluator import EvalResult

_SIGNIFICANCE_THRESHOLD = 0.02   # deltas below this are considered noise

# How many differing sample ids to name before the message stops helping.
_MAX_NAMED = 5


class DatasetMismatch(ValueError):
    """Two runs that measured different things, so their means do not compare."""


@dataclass
class MetricDelta:
    metric: str
    score_a: float
    score_b: float
    delta: float           # b - a
    winner: str            # "A" | "B" | "tie"
    is_significant: bool   # |delta| >= threshold


@dataclass
class ComparisonResult:
    config_a_name: str
    config_b_name: str
    deltas: list[MetricDelta] = field(default_factory=list)
    overall_winner: str = "tie"    # "A" | "B" | "tie"
    # What could not be verified. Printed with the table, because a
    # comparison nobody could check should not look like one that was.
    notes: list[str] = field(default_factory=list)

    def as_markdown(self) -> str:
        lines = [
            f"## A/B Comparison: {self.config_a_name} vs {self.config_b_name}",
            "",
            f"| Metric | {self.config_a_name} | {self.config_b_name} | Delta | Winner |",
            "| --- | --- | --- | --- | --- |",
        ]
        for d in self.deltas:
            delta_str = f"{d.delta:+.4f}"
            sig = "" if d.is_significant else " *(ns)*"
            lines.append(
                f"| {d.metric} | {d.score_a:.4f} | {d.score_b:.4f} | "
                f"{delta_str}{sig} | {d.winner} |"
            )
        lines.append("")
        lines.append(f"**Overall winner: {self.overall_winner}**")
        lines.append("")
        lines.append(
            f"*(ns) = not significant (|delta| < {_SIGNIFICANCE_THRESHOLD})*"
        )
        for note in self.notes:
            lines.append("")
            lines.append(f"> **Unverified:** {note}")
        return "\n".join(lines)


def _check_comparable(result_a: EvalResult, result_b: EvalResult) -> list[str]:
    """Raise on a comparison that cannot be valid; return notes on one that
    cannot be verified."""
    ids_a = {r.sample_id for r in result_a.sample_results}
    ids_b = {r.sample_id for r in result_b.sample_results}
    if ids_a != ids_b:
        only_a = sorted(ids_a - ids_b)[:_MAX_NAMED]
        only_b = sorted(ids_b - ids_a)[:_MAX_NAMED]
        raise DatasetMismatch(
            f"these runs covered different samples — {len(ids_a)} and {len(ids_b)} "
            f"of them, only in A: {only_a or 'none'}, only in B: {only_b or 'none'}. "
            f"The aggregates are means over different denominators, so no delta "
            f"between them means anything."
        )

    fp_a, fp_b = result_a.dataset_fingerprint, result_b.dataset_fingerprint
    if fp_a and fp_b and fp_a != fp_b:
        named = ""
        if result_a.dataset_name and result_a.dataset_name != result_b.dataset_name:
            named = f" ('{result_a.dataset_name}' vs '{result_b.dataset_name}')"
        raise DatasetMismatch(
            f"same sample ids, different dataset{named}: the questions or the "
            f"labels changed between these two runs, so the scores measure "
            f"different things. Re-run the baseline against the current dataset, "
            f"or replay it — scripts/replay_context_metrics.py recomputes both "
            f"context metrics from a stored report for nothing."
        )

    if not fp_a or not fp_b:
        if not fp_a and not fp_b:
            which = "Neither run carries"
        else:
            which = f"Run {'A' if not fp_a else 'B'} does not carry"
        return [
            f"{which} a dataset fingerprint, so a relabelling between these "
            f"runs would not be detected. The sample ids match, which rules "
            f"out a different set of rows but not a different set of labels "
            f"on the same rows."
        ]
    return []


def compare(result_a: EvalResult, result_b: EvalResult) -> ComparisonResult:
    """
    Compare two EvalResults metric-by-metric.

    Both results must cover the same set of metrics; extra metrics in one
    result are still reported with score=0.0 for the other.

    Raises `DatasetMismatch` when the two runs did not measure the same
    thing. That is not a formality — this function's output ends in
    **Overall winner**, which is the sentence a wrong comparison gets quoted
    as.
    """
    notes = _check_comparable(result_a, result_b)

    all_metrics = sorted(
        set(result_a.aggregate_scores) | set(result_b.aggregate_scores)
    )

    deltas: list[MetricDelta] = []
    b_wins = 0
    a_wins = 0

    for metric in all_metrics:
        sa = result_a.aggregate_scores.get(metric, 0.0)
        sb = result_b.aggregate_scores.get(metric, 0.0)
        delta = sb - sa
        significant = abs(delta) >= _SIGNIFICANCE_THRESHOLD

        if not significant:
            winner = "tie"
        elif delta > 0:
            winner = "B"
            b_wins += 1
        else:
            winner = "A"
            a_wins += 1

        deltas.append(MetricDelta(
            metric=metric,
            score_a=round(sa, 4),
            score_b=round(sb, 4),
            delta=round(delta, 4),
            winner=winner,
            is_significant=significant,
        ))

    overall = "B" if b_wins > a_wins else ("A" if a_wins > b_wins else "tie")
    return ComparisonResult(
        config_a_name=result_a.pipeline_config.name,
        config_b_name=result_b.pipeline_config.name,
        deltas=deltas,
        overall_winner=overall,
        notes=notes,
    )


def save_comparison(comparison: ComparisonResult, path: Path) -> None:
    """Write the comparison markdown to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(comparison.as_markdown())
