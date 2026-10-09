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

    A rewritten *reference answer* is checked separately, and only between
    two runs that both measured `answer_correctness` — the one metric that
    reads it. Four of the five do not, so a single fingerprint over
    everything would refuse a precision comparison because a reference
    answer's wording changed, and a guard that cries wolf is one that gets
    bypassed with a flag.

    Metric deltas are not the whole verdict. This function used to build one
    from `aggregate_scores` alone and end in **Overall winner**, while the
    report it sat next to already carried per-sample `stage_ms` and per-model
    `token_usage` — so a change buying +0.03 recall at twice the p95 and
    double the cost was declared the winner with the regression printed
    nowhere. It now measures both against `planning/BUDGET.md` and withholds
    the winner on a breach, which is the one sentence anybody quotes.

    Two honest limits on that check. The latency numbers are per-sample and
    mean what a caller waits for, so they are the budget's own quantity. The
    cost is a whole eval run, which pays for the metric judges as well
    (~7.8 chat calls a sample against production's ~4) — so it checks a run
    against the run ceiling and a regression against the other run, and is
    not the production cost per query. Getting that would need per-sample
    token accounting, which no stored report has, and demanding it would
    make the check unusable against every baseline already on disk.

    The same applies to the two reports' token totals, which is the other
    number a reader diffs by eye. Before 2026-09-28 a report counted the
    generation call and nothing else; after it, every call including the
    judges and the embeddings. Reading one against the other makes the newer
    configuration look about twice as expensive whatever it did. That is a
    note rather than a refusal, because the metric deltas are still valid —
    only the cost comparison is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from atlas.cost import estimate_usage_cost
from atlas.evaluation.reporter import percentile
from atlas.interfaces.evaluator import EvalResult

_SIGNIFICANCE_THRESHOLD = 0.02   # deltas below this are considered noise

# ── The agreed budget: planning/BUDGET.md, accepted 2026-10-08 ───────────────
# The numbers live here as well as in the document because a budget nothing
# reads is a wish. Measured at acceptance, for scale: warm p50 10,062 ms,
# warm p95 16,859 ms, one 16-row run $0.0709.
_P50_CEILING_MS = 12_000.0
_P95_CEILING_MS = 20_000.0
_RUN_COST_CEILING_USD = 0.100
# Regression allowances, against whichever run this one is compared with.
_P95_REGRESSION_LIMIT = 0.15
_COST_REGRESSION_LIMIT = 0.20

# The one metric that reads `ground_truth_answer`, and so the only one a
# rewritten reference answer can move.
_CORRECTNESS = "answer_correctness"

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
    winner: str            # "A" | "B" | "tie" | "n/a"
    is_significant: bool   # |delta| >= threshold
    # "A" or "B" when only the other run measured this metric at all. Such a
    # row has no delta: the absent side is not a zero, it is a run that never
    # asked the question.
    missing_in: str = ""


@dataclass
class BudgetDelta:
    """One budgeted quantity, measured in both runs.

    `ceiling` is the absolute line B has to sit under; `limit` is how far it
    may rise against A. Both are checked, because a run can be well inside
    the regression allowance and still over the ceiling when the run it is
    compared with was already close to it.
    """

    name: str
    unit: str                 # "ms" | "USD"
    value_a: float
    value_b: float
    ratio: float | None       # value_b / value_a - 1; None when A measured 0
    limit: float | None       # allowed fractional increase, None when unbounded
    ceiling: float | None     # absolute ceiling for B, None when none applies
    breach: str = ""          # why it breached; empty string when it did not


@dataclass
class ComparisonResult:
    config_a_name: str
    config_b_name: str
    deltas: list[MetricDelta] = field(default_factory=list)
    overall_winner: str = "tie"    # "A" | "B" | "tie"
    # What could not be verified. Printed with the table, because a
    # comparison nobody could check should not look like one that was.
    notes: list[str] = field(default_factory=list)
    # Latency and cost against planning/BUDGET.md. Kept apart from `notes`,
    # which is about whether the two runs measured the same thing: a budget
    # that could not be checked is a different fact from a dataset that could
    # not be matched, and collapsing them would hide one behind the other.
    budget: list[BudgetDelta] = field(default_factory=list)
    budget_notes: list[str] = field(default_factory=list)

    @property
    def budget_breaches(self) -> list[str]:
        """Every breached budget line, in words. Empty when none breached —
        which is not the same as a budget that was checked, so read
        `budget` or `budget_notes` to tell those apart."""
        return [d.breach for d in self.budget if d.breach]

    def _quality_sentence(self) -> str:
        if self.overall_winner == "tie":
            return "neither run wins on quality"
        return f"{self.overall_winner} wins on quality"

    def as_markdown(self) -> str:
        lines = [
            f"## A/B Comparison: {self.config_a_name} vs {self.config_b_name}",
            "",
            f"| Metric | {self.config_a_name} | {self.config_b_name} | Delta | Winner |",
            "| --- | --- | --- | --- | --- |",
        ]
        for d in self.deltas:
            if d.missing_in:
                measured = f"{d.score_b:.4f}" if d.missing_in == "A" else f"{d.score_a:.4f}"
                cells = ("—", measured) if d.missing_in == "A" else (measured, "—")
                lines.append(
                    f"| {d.metric} | {cells[0]} | {cells[1]} | — | not measured in "
                    f"{d.missing_in} |"
                )
                continue
            delta_str = f"{d.delta:+.4f}"
            sig = "" if d.is_significant else " *(ns)*"
            lines.append(
                f"| {d.metric} | {d.score_a:.4f} | {d.score_b:.4f} | "
                f"{delta_str}{sig} | {d.winner} |"
            )
        lines.append("")

        if self.budget:
            lines.append("### Budget (planning/BUDGET.md)")
            lines.append("")
            lines.append(
                f"| Budgeted | {self.config_a_name} | {self.config_b_name} "
                f"| Change | Allowed | Ceiling | Verdict |"
            )
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            for line in self.budget:
                change = "—" if line.ratio is None else f"{line.ratio:+.1%}"
                allowed = "—" if line.limit is None else f"{line.limit:+.0%}"
                ceiling = (
                    "—" if line.ceiling is None else _fmt(line.ceiling, line.unit)
                )
                verdict = "**BREACH**" if line.breach else "ok"
                lines.append(
                    f"| {line.name} | {_fmt(line.value_a, line.unit)} "
                    f"| {_fmt(line.value_b, line.unit)} | {change} | {allowed} "
                    f"| {ceiling} | {verdict} |"
                )
            lines.append("")

        breaches = self.budget_breaches
        if breaches:
            # The winner is withheld rather than annotated. This line is the
            # one that gets pasted into a commit message, and "Overall
            # winner: B" with a caveat three paragraphs down is how a
            # regression ships.
            lines.append(
                f"**Overall winner: withheld** — {self._quality_sentence()}, "
                f"but the agreed budget is breached:"
            )
            lines.append("")
            for breach in breaches:
                lines.append(f"- {breach}")
            lines.append("")
            lines.append(
                "Shipping it anyway is allowed and needs a "
                "`planning/DECISIONS.md` entry naming the quality gain it "
                "buys. Shipping it silently is what the budget exists to stop."
            )
        else:
            lines.append(f"**Overall winner: {self.overall_winner}**")

        lines.append("")
        lines.append(
            f"*(ns) = not significant (|delta| < {_SIGNIFICANCE_THRESHOLD})*"
        )
        for note in self.notes:
            lines.append("")
            lines.append(f"> **Unverified:** {note}")
        for note in self.budget_notes:
            lines.append("")
            lines.append(f"> **Budget:** {note}")
        return "\n".join(lines)


def _fmt(value: float, unit: str) -> str:
    if unit == "USD":
        return f"${value:.4f}"
    return f"{value:,.0f} {unit}"


def _sample_totals(result: EvalResult) -> list[float]:
    """Per-sample end-to-end latency, in ms.

    A sample with no `stage_ms` is left out rather than counted as zero: the
    field was added after several of the stored reports were written, and a
    run that did not record latency has not got a fast one.
    """
    return [sum(s.stage_ms.values()) for s in result.sample_results if s.stage_ms]


def _budgeted(
    *,
    name: str,
    unit: str,
    value_a: float,
    value_b: float,
    ceiling: float | None,
    limit: float | None,
) -> BudgetDelta:
    # Rounded before it is either judged or printed, so the figure in the
    # table and the figure in the breach line are the same figure. They were
    # not: 0.21250585 printed as +21.3% in the sentence and +21.2% in the
    # table, which is two numbers for one measurement.
    ratio = round(value_b / value_a - 1, 4) if value_a else None
    reasons: list[str] = []
    if ceiling is not None and value_b > ceiling:
        reasons.append(
            f"{name} is {_fmt(value_b, unit)}, over the "
            f"{_fmt(ceiling, unit)} ceiling"
        )
    if limit is not None and ratio is not None and ratio > limit:
        reasons.append(
            f"{name} rose {ratio:+.1%} ({_fmt(value_a, unit)} → "
            f"{_fmt(value_b, unit)}) against an allowed {limit:+.0%}"
        )
    return BudgetDelta(
        name=name,
        unit=unit,
        value_a=round(value_a, 4),
        value_b=round(value_b, 4),
        ratio=ratio,
        limit=limit,
        ceiling=ceiling,
        breach="; ".join(reasons),
    )


def _check_budget(
    result_a: EvalResult,
    result_b: EvalResult,
    *,
    same_metrics: bool,
) -> tuple[list[BudgetDelta], list[str]]:
    """Measure both runs against planning/BUDGET.md.

    Returns the budgeted lines and whatever could not be checked. A line that
    could not be measured is absent from the first and named in the second —
    never silently passed, which would make an unmeasurable run look like a
    compliant one.
    """
    deltas: list[BudgetDelta] = []
    notes: list[str] = []

    totals_a, totals_b = _sample_totals(result_a), _sample_totals(result_b)
    if totals_a and totals_b:
        deltas.append(_budgeted(
            name="warm p50 latency", unit="ms",
            value_a=percentile(totals_a, 50), value_b=percentile(totals_b, 50),
            ceiling=_P50_CEILING_MS, limit=None,
        ))
        deltas.append(_budgeted(
            name="warm p95 latency", unit="ms",
            value_a=percentile(totals_a, 95), value_b=percentile(totals_b, 95),
            ceiling=_P95_CEILING_MS, limit=_P95_REGRESSION_LIMIT,
        ))
    else:
        if not totals_a and not totals_b:
            which = "Neither run recorded"
        else:
            which = f"Run {'A' if not totals_a else 'B'} did not record"
        notes.append(
            f"{which} per-sample `stage_ms`, so the latency half of the "
            f"budget is unchecked. The run's own `duration_seconds` is "
            f"concurrency-wide and is not a substitute."
        )

    cost_a = estimate_usage_cost(result_a.token_usage) if result_a.token_usage else 0.0
    cost_b = estimate_usage_cost(result_b.token_usage) if result_b.token_usage else 0.0
    if not (result_a.token_usage and result_b.token_usage):
        missing = "Neither run" if not (cost_a or cost_b) else (
            f"Run {'A' if not cost_a else 'B'}"
        )
        notes.append(
            f"{missing} carries per-model `token_usage`, so the cost half of "
            f"the budget is unchecked — a report written before 2026-09-28 "
            f"counted the generation call alone and cannot be priced."
        )
    elif not same_metrics:
        notes.append(
            f"The two runs did not measure the same metrics, so the cost half "
            f"of the budget is unchecked: the judges spend tokens too, and "
            f"the run carrying an extra metric would look more expensive for "
            f"that reason alone (A ${cost_a:.4f}, B ${cost_b:.4f}, reported "
            f"here and not judged)."
        )
    else:
        deltas.append(_budgeted(
            name="eval run cost", unit="USD",
            value_a=cost_a, value_b=cost_b,
            ceiling=_RUN_COST_CEILING_USD, limit=_COST_REGRESSION_LIMIT,
        ))
        notes.append(
            "The cost line is a whole eval run, judges included — about 7.8 "
            "chat calls a sample against production's ~4. It checks the run "
            "ceiling and the run-to-run regression; it is not the production "
            "cost per query, which would need per-sample token accounting no "
            "stored report has."
        )

    return deltas, notes


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

    graded = _CORRECTNESS in result_a.aggregate_scores and \
        _CORRECTNESS in result_b.aggregate_scores
    ans_a, ans_b = result_a.answers_fingerprint, result_b.answers_fingerprint
    if graded and ans_a and ans_b and ans_a != ans_b:
        raise DatasetMismatch(
            f"both runs measured {_CORRECTNESS}, and they were graded against "
            f"different reference answers. That metric reads "
            f"`ground_truth_answer` directly, so its two scores are not the "
            f"same measurement. The other metrics do not read it, which is why "
            f"the reference answers are fingerprinted separately — re-run the "
            f"baseline if the correctness delta is the one you need."
        )

    counted_a, counted_b = bool(result_a.token_usage), bool(result_b.token_usage)
    if counted_a != counted_b and (result_a.total_tokens_used or result_b.total_tokens_used):
        older = "A" if not counted_a else "B"
        notes_on_tokens = [
            f"Run {older}'s token total counts the generation call only — it "
            f"predates per-model accounting (2026-09-28) — while the other "
            f"counts every call and every embedding. The metric deltas below "
            f"are unaffected; the two token figures are not a cost comparison "
            f"and diffing them makes the newer run look ~2x more expensive "
            f"whatever it did."
        ]
    else:
        notes_on_tokens = []

    if not fp_a or not fp_b:
        if not fp_a and not fp_b:
            which = "Neither run carries"
        else:
            which = f"Run {'A' if not fp_a else 'B'} does not carry"
        return notes_on_tokens + [
            f"{which} a dataset fingerprint, so a relabelling between these "
            f"runs would not be detected. The sample ids match, which rules "
            f"out a different set of rows but not a different set of labels "
            f"on the same rows."
        ]
    return notes_on_tokens


def compare(result_a: EvalResult, result_b: EvalResult) -> ComparisonResult:
    """
    Compare two EvalResults metric-by-metric.

    Both results must cover the same set of metrics; extra metrics in one
    result are still reported with score=0.0 for the other.

    Raises `DatasetMismatch` when the two runs did not measure the same
    thing. That is not a formality — this function's output ends in
    **Overall winner**, which is the sentence a wrong comparison gets quoted
    as.

    `overall_winner` is the quality verdict and nothing else. The latency and
    cost budget is measured separately into `budget`, and on a breach the
    rendered markdown withholds the winner instead of printing it: a change
    may still ship, with a `planning/DECISIONS.md` entry naming what the
    regression bought.
    """
    notes = _check_comparable(result_a, result_b)

    all_metrics = sorted(
        set(result_a.aggregate_scores) | set(result_b.aggregate_scores)
    )

    deltas: list[MetricDelta] = []
    b_wins = 0
    a_wins = 0

    for metric in all_metrics:
        in_a = metric in result_a.aggregate_scores
        in_b = metric in result_b.aggregate_scores
        sa = result_a.aggregate_scores.get(metric, 0.0)
        sb = result_b.aggregate_scores.get(metric, 0.0)

        if in_a != in_b:
            # A metric one run never computed. This used to read as 0.0 and
            # hand the other run a win, which was harmless only for as long
            # as both runs always had the same four metrics. The first run
            # with `answer_correctness` would otherwise have shown
            # 0.0 -> 0.85 against every stored baseline and called it an
            # improvement.
            missing = "A" if not in_a else "B"
            notes.append(
                f"'{metric}' was measured only in {'B' if missing == 'A' else 'A'}. "
                f"It is shown without a delta: the other run did not score 0.0 on "
                f"it, it never computed it, and treating the two alike invents a "
                f"result."
            )
            deltas.append(MetricDelta(
                metric=metric,
                score_a=round(sa, 4),
                score_b=round(sb, 4),
                delta=0.0,
                winner="n/a",
                is_significant=False,
                missing_in=missing,
            ))
            continue

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

    # The cost line only means anything between two runs that paid for the
    # same judges, so the metric set decides whether it is checked at all.
    same_metrics = not any(d.missing_in for d in deltas)
    budget, budget_notes = _check_budget(
        result_a, result_b, same_metrics=same_metrics
    )

    return ComparisonResult(
        config_a_name=result_a.pipeline_config.name,
        config_b_name=result_b.pipeline_config.name,
        deltas=deltas,
        overall_winner=overall,
        notes=notes,
        budget=budget,
        budget_notes=budget_notes,
    )


def save_comparison(comparison: ComparisonResult, path: Path) -> None:
    """Write the comparison markdown to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(comparison.as_markdown())
