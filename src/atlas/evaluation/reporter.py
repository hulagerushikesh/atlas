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
from pathlib import Path

from atlas.interfaces.evaluator import EvalResult

_METRIC_ORDER = [
    "context_precision",
    "context_recall",
    "faithfulness",
    "answer_relevance",
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

    rows = [f"| {col_header} |", f"| {separator} |"]
    for metric in all_metrics:
        score = result.aggregate_scores.get(metric, None)
        cell = f"{score:.4f}" if score is not None else "—"
        rows.append(f"| {metric} | {cell} |")

    rows.append("")  # trailing newline
    rows.append(f"*{len(result.sample_results)} samples · "
                f"{result.duration_seconds:.1f}s · "
                f"{result.total_tokens_used:,} tokens*")
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
