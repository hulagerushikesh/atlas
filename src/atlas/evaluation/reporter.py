"""
Evaluation reporter: render EvalResult as JSON and a markdown table.

Design rationale:
    Two output formats serve different audiences:
    - JSON: machine-readable, diffable in git, ingested by the comparator and
      any downstream dashboards. Full fidelity — every per-sample score and
      reasoning string is preserved.
    - Markdown table: human-readable for PR descriptions, README sections, and
      interview portfolio presentations. Compact aggregate view.

    The markdown table uses a fixed column order (matching the metric
    definitions' logical sequence) rather than dict insertion order, so tables
    are comparable across runs even if metrics were added/removed between runs.
    Missing metrics get a "—" cell rather than breaking the table.

    Files are written atomically: JSON is serialised to a string first; only if
    serialisation succeeds is the file written. This prevents partial writes
    from corrupting a previous report if the process is killed mid-write.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from atlas.cost import USD_TO_INR, estimate_usage_cost
from atlas.interfaces.evaluator import EvalResult

# `runner` records this score for a sample that errored and leaves it out of
# the mean. Defined here as well rather than imported, because importing the
# runner into the reporter would point the dependency the wrong way round.
_FAILED_SENTINEL = -1.0

_METRIC_ORDER = [
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_relevance",
    "answer_correctness",
]


def _md_table(result: EvalResult) -> str:
    """Render a markdown summary table for the eval result."""
    config_name = result.pipeline_config.name
    header_metrics = [m for m in _METRIC_ORDER if m in result.aggregate_scores]
    # Include any extra metrics not in the standard order
    extras = [m for m in result.aggregate_scores if m not in _METRIC_ORDER]
    all_metrics = header_metrics + extras

    # Header row
    col_header = " | ".join(["Metric", config_name])
    separator = " | ".join(["---"] * 2)

    skipped = _inapplicable_counts(result)
    failed = _failed_counts(result)

    rows = [f"| {col_header} |", f"| {separator} |"]
    for metric in all_metrics:
        score = result.aggregate_scores.get(metric, None)
        cell = f"{score:.4f}" if score is not None else "—"
        # A mean over 14 of 15 samples is a different number from a mean over
        # 15, and the table must not let the two look alike.
        n = skipped.get(metric, 0)
        f = failed.get(metric, 0)
        if n or f:
            parts = []
            if n:
                parts.append(f"{n} n/a")
            if f:
                parts.append(f"**{f} failed**")
            cell += f" *(over {len(result.sample_results) - n - f} of " \
                    f"{len(result.sample_results)}; {', '.join(parts)})*"
        rows.append(f"| {metric} | {cell} |")

    rows.append("")  # trailing newline
    rows.append(f"*{len(result.sample_results)} samples · "
                f"{result.duration_seconds:.1f}s · "
                f"{result.total_tokens_used:,} tokens{_tokens_qualifier(result)}*")

    spend = _md_tokens(result)
    if spend:
        rows.append("")
        rows.append(spend)

    served = _md_models(result)
    if served:
        rows.append("")
        rows.append(served)

    latency = _md_latency(result)
    if latency:
        rows.append("")
        rows.append(latency)
    return "\n".join(rows)


def _tokens_qualifier(result: EvalResult) -> str:
    """Say which of the two meanings of "tokens" this report's total has.

    Reports written before 2026-09-28 count the generation call only — no
    router, no decomposer, no grader, no faithfulness checker, no judges, no
    embeddings. That is roughly half a run. Both kinds of report will be read
    side by side for as long as `eval_data/reports/` exists, so the older
    number has to arrive labelled rather than be silently compared with a
    complete one.
    """
    if result.token_usage or not result.total_tokens_used:
        return ""
    return " (generation call only)"


def _md_tokens(result: EvalResult) -> str:
    """Per-model tokens and what they cost.

    Split by model because that is the only level at which tokens can be
    priced: a run's chat and embedding models differ in price by more than an
    order of magnitude, so a single total cannot be turned into a number. The
    cost is an estimate from a price table that goes stale — it answers "is
    this configuration cheaper than that one?", which is a ratio and survives
    a stale table, not "what will the invoice say".
    """
    usage = result.token_usage
    if not usage:
        return ""

    rows = ["| Model | Calls | Prompt | Completion | Est. cost |",
            "| --- | ---: | ---: | ---: | ---: |"]
    for model, entry in sorted(usage.items(), key=lambda kv: -kv[1].total_tokens):
        cost = estimate_usage_cost({model: entry})
        # Em dash rather than 0 for an embedding: it has no completion to
        # count, which is a different fact from having produced none.
        completion_cell = f"{entry.completion_tokens:,}" if entry.kind == "chat" else "—"
        rows.append(
            f"| {model} ({entry.kind}) | {entry.calls:,} | {entry.prompt_tokens:,} "
            f"| {completion_cell} | ${cost:.4f} |"
        )
    total_cost = estimate_usage_cost(usage)
    calls = sum(e.calls for e in usage.values())
    prompt = sum(e.prompt_tokens for e in usage.values())
    completion = sum(e.completion_tokens for e in usage.values())
    rows.append(
        f"| **total** | **{calls:,}** | **{prompt:,}** | **{completion:,}** "
        f"| **${total_cost:.4f}** (~₹{total_cost * USD_TO_INR:.2f}) |"
    )
    rows.append("")
    rows.append(_md_cost_per_query(result))
    rows.append(f"*estimated from list prices at {USD_TO_INR:.0f} ₹/$; "
                f"the ratio between two runs is the part to trust*")
    return "\n".join(rows)


def _md_cost_per_query(result: EvalResult) -> str:
    """What one production query cost, as distinct from one sample of a run.

    The run total above cannot answer this. It includes the judges -- roughly
    twice the chat calls a production query makes -- so dividing it by sample
    count overstates a real query by whatever the judges spent. Reports before
    2026-10-14 carry no per-sample usage, so this line is omitted rather than
    computed from a total that does not mean what the line would claim.
    """
    measured = [sr for sr in result.sample_results if sr.token_usage]
    if not measured:
        return ""

    per_sample = [estimate_usage_cost(sr.token_usage) for sr in measured]
    mean_cost = sum(per_sample) / len(per_sample)
    judged = estimate_usage_cost(result.token_usage) - sum(per_sample)
    note = ""
    if len(measured) != len(result.sample_results):
        note = f" over {len(measured)} of {len(result.sample_results)} samples"
    return (
        f"**Cost per query: ${mean_cost:.5f}** (~₹{mean_cost * USD_TO_INR:.2f}){note} — "
        f"the pipeline's own calls, judges excluded. The judges added "
        f"${judged:.4f} to this run, which is why the total above is not "
        f"`n x` this number.\n"
    )


def _md_models(result: EvalResult) -> str:
    """Name the model that served this run, but only when it was not just one.

    A run served entirely by the configured primary needs no note — the config
    line already says which that is. A run that fell back does: on 2026-09-24
    the primary returned 503 throughout and a different model produced the
    scores, which makes the run incomparable with the one it was being diffed
    against. Silence here would have hidden that.
    """
    calls = result.model_calls
    if len(calls) < 2:
        return ""
    total = sum(calls.values())
    parts = [
        f"{model} {n} ({n / total:.0%})"
        for model, n in sorted(calls.items(), key=lambda kv: -kv[1])
    ]
    return (
        f"> **Mixed models.** {' · '.join(parts)}. The configured primary failed "
        f"on some calls and the fallback answered them, so these scores are not "
        f"a clean measurement of either model."
    )


def _inapplicable_counts(result: EvalResult) -> dict[str, int]:
    """Per metric, how many samples it declined to score.

    Reported rather than buried: excluding a sample always moves the mean, so
    a reader has to be able to see that it happened. Refusals are the case
    that exists today — a refusal has no claims, so faithfulness has no
    opinion, but a harness that silently drops them would report 1.000 for a
    pipeline that answered nothing.
    """
    counts: dict[str, int] = {}
    for sr in result.sample_results:
        for ms in sr.metrics:
            if not ms.applicable:
                counts[ms.metric_name] = counts.get(ms.metric_name, 0) + 1
    return counts


def _failed_counts(result: EvalResult) -> dict[str, int]:
    """Per metric, how many samples errored instead of scoring.

    Separate from `_inapplicable_counts`, and added 2026-10-17 because the
    two were not separate and only one was printed. A sample that errors is
    recorded applicable with `score=-1.0` and dropped from the mean by the
    runner, so it moved the number while the table went on reporting the full
    sample count with no note of any kind. A HyDE run lost two samples to an
    out-of-memory reranker and read as a clean 16; the means were over 14.

    A refusal is a result and a crash is not, so they are counted apart and
    the crash is the one set in bold.
    """
    counts: dict[str, int] = {}
    for sr in result.sample_results:
        for ms in sr.metrics:
            if ms.applicable and ms.score == _FAILED_SENTINEL:
                counts[ms.metric_name] = counts.get(ms.metric_name, 0) + 1
    return counts


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile. Public because `comparator` checks the budget
    with it, and a p95 that is checked by one rule and printed by another is
    two numbers under one name.

    The eval set is 15 samples; interpolating
    between two of them would imply a precision the sample size does not have."""
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[idx]


def _md_latency(result: EvalResult) -> str:
    """Per-stage latency table.

    The run's own `duration_seconds` is wall clock across the whole set at
    whatever concurrency was configured, so it says nothing about what one
    caller waits for. These are per-sample, which is the number a user feels.
    """
    samples = [s for s in result.sample_results if s.stage_ms]
    if not samples:
        return ""

    stages: dict[str, list[float]] = {}
    totals: list[float] = []
    for s in samples:
        for stage, ms in s.stage_ms.items():
            stages.setdefault(stage, []).append(ms)
        totals.append(sum(s.stage_ms.values()))

    rows = ["| Stage | p50 ms | p95 ms |", "| --- | --- | --- |"]
    for stage, values in sorted(stages.items(), key=lambda kv: -percentile(kv[1], 50)):
        rows.append(f"| {stage} | {percentile(values, 50):.0f} | {percentile(values, 95):.0f} |")
    rows.append(
        f"| **total** | **{percentile(totals, 50):.0f}** "
        f"| **{percentile(totals, 95):.0f}** |"
    )
    rows.append("")
    rows.append(f"*per-sample latency, {len(samples)} samples; the run's own "
                f"{result.duration_seconds:.1f}s is concurrency-wide and not comparable*")
    return "\n".join(rows)


def save_report(
    result: EvalResult,
    output_dir: Path,
    run_name: str = "eval",
) -> tuple[Path, Path]:
    """
    Write JSON and markdown reports to *output_dir*.

    Returns:
        (json_path, markdown_path) — the two created files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{run_name}.json"
    md_path = output_dir / f"{run_name}.md"

    # JSON — full fidelity
    payload = result.model_dump()
    json_path.write_text(json.dumps(payload, indent=2))

    # Markdown — human-readable summary
    md_path.write_text(_md_table(result))

    return json_path, md_path


def print_report(result: EvalResult) -> None:
    """Print a markdown summary to stdout (useful for CI logs)."""
    print(_md_table(result))
