"""
Tests for reporter (JSON + markdown output) and A/B comparator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.interfaces.evaluator import EvalResult, PipelineConfig, SampleResult, MetricScore
from atlas.evaluation.comparator import compare, save_comparison, _SIGNIFICANCE_THRESHOLD
from atlas.evaluation.reporter import save_report, _md_table


# ── Helpers ───────────────────────────────────────────────────────────────────

def _result(name: str, scores: dict) -> EvalResult:
    samples = [
        SampleResult(
            sample_id="s1", question="q", generated_answer="a",
            retrieved_chunk_ids=["c1"],
            metrics=[MetricScore(metric_name=k, score=v) for k, v in scores.items()],
        )
    ]
    return EvalResult(
        pipeline_config=PipelineConfig(name=name),
        sample_results=samples,
        aggregate_scores=scores,
        total_tokens_used=1000,
        duration_seconds=5.2,
    )


# ── Reporter ──────────────────────────────────────────────────────────────────

class TestReporter:
    def test_json_report_written(self, tmp_path: Path) -> None:
        result = _result("baseline", {"context_precision": 0.75, "faithfulness": 0.85})
        json_path, _ = save_report(result, tmp_path, "test_run")
        assert json_path.exists()
        payload = json.loads(json_path.read_text())
        assert payload["aggregate_scores"]["context_precision"] == pytest.approx(0.75)

    def test_markdown_report_written(self, tmp_path: Path) -> None:
        result = _result("baseline", {"faithfulness": 0.9})
        _, md_path = save_report(result, tmp_path, "test_run")
        assert md_path.exists()
        content = md_path.read_text()
        assert "faithfulness" in content
        assert "0.9000" in content

    def test_markdown_contains_config_name(self, tmp_path: Path) -> None:
        result = _result("my_config", {"context_recall": 0.6})
        _, md_path = save_report(result, tmp_path, "run")
        assert "my_config" in md_path.read_text()

    def test_markdown_contains_sample_count(self) -> None:
        result = _result("cfg", {"faithfulness": 0.8})
        md = _md_table(result)
        assert "1 samples" in md

    def test_output_dir_created(self, tmp_path: Path) -> None:
        output = tmp_path / "nested" / "reports"
        result = _result("cfg", {"faithfulness": 0.8})
        save_report(result, output, "run")
        assert output.exists()


# ── Comparator ────────────────────────────────────────────────────────────────

class TestComparator:
    def test_b_wins_on_higher_scores(self) -> None:
        a = _result("A", {"context_precision": 0.5, "faithfulness": 0.6})
        b = _result("B", {"context_precision": 0.8, "faithfulness": 0.85})
        comparison = compare(a, b)
        assert comparison.overall_winner == "B"

    def test_a_wins_on_higher_scores(self) -> None:
        a = _result("A", {"faithfulness": 0.9})
        b = _result("B", {"faithfulness": 0.5})
        comparison = compare(a, b)
        precision_delta = next(d for d in comparison.deltas if d.metric == "faithfulness")
        assert precision_delta.winner == "A"

    def test_delta_calculated_correctly(self) -> None:
        a = _result("A", {"context_precision": 0.6})
        b = _result("B", {"context_precision": 0.8})
        comparison = compare(a, b)
        delta = comparison.deltas[0]
        assert delta.delta == pytest.approx(0.2, abs=1e-4)

    def test_insignificant_delta_is_tie(self) -> None:
        tiny = _SIGNIFICANCE_THRESHOLD / 2
        a = _result("A", {"faithfulness": 0.8})
        b = _result("B", {"faithfulness": 0.8 + tiny})
        comparison = compare(a, b)
        assert comparison.deltas[0].winner == "tie"
        assert comparison.deltas[0].is_significant is False

    def test_significant_delta_flagged(self) -> None:
        a = _result("A", {"faithfulness": 0.5})
        b = _result("B", {"faithfulness": 0.9})
        comparison = compare(a, b)
        assert comparison.deltas[0].is_significant is True

    def test_config_names_in_comparison(self) -> None:
        a = _result("no-rerank", {"faithfulness": 0.7})
        b = _result("with-rerank", {"faithfulness": 0.9})
        comparison = compare(a, b)
        assert comparison.config_a_name == "no-rerank"
        assert comparison.config_b_name == "with-rerank"

    def test_markdown_contains_both_configs(self) -> None:
        a = _result("baseline", {"context_precision": 0.6})
        b = _result("reranked", {"context_precision": 0.8})
        comparison = compare(a, b)
        md = comparison.as_markdown()
        assert "baseline" in md
        assert "reranked" in md
        assert "+0.2000" in md

    def test_save_comparison(self, tmp_path: Path) -> None:
        a = _result("A", {"faithfulness": 0.7})
        b = _result("B", {"faithfulness": 0.9})
        path = tmp_path / "comparison.md"
        save_comparison(compare(a, b), path)
        assert path.exists()
        assert "faithfulness" in path.read_text()

    def test_overall_tie_when_split(self) -> None:
        # A wins precision, B wins recall → tie
        a = _result("A", {"context_precision": 0.9, "context_recall": 0.5})
        b = _result("B", {"context_precision": 0.5, "context_recall": 0.9})
        comparison = compare(a, b)
        assert comparison.overall_winner == "tie"
