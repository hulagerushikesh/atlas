"""
Tests for reporter (JSON + markdown output) and A/B comparator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.cost import estimate_usage_cost
from atlas.evaluation.comparator import (
    _SIGNIFICANCE_THRESHOLD,
    DatasetMismatch,
    compare,
    save_comparison,
)
from atlas.evaluation.dataset import (
    dataset_answers_fingerprint,
    dataset_fingerprint,
    load_dataset,
)
from atlas.evaluation.reporter import _md_latency, _md_table, save_report
from atlas.interfaces.evaluator import (
    EvalDataset,
    EvalResult,
    EvalSample,
    MetricScore,
    PipelineConfig,
    SampleResult,
)
from atlas.usage import ModelUsage

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


# ── Latency table ─────────────────────────────────────────────────────────────

def _timed(stage_ms_per_sample: list[dict[str, float]]) -> EvalResult:
    samples = [
        SampleResult(
            sample_id=f"s{i}", question="q", generated_answer="a",
            retrieved_chunk_ids=["c1"], metrics=[], stage_ms=sm,
        )
        for i, sm in enumerate(stage_ms_per_sample)
    ]
    return EvalResult(
        pipeline_config=PipelineConfig(name="run"),
        sample_results=samples,
        aggregate_scores={},
        total_tokens_used=0,
        duration_seconds=5.2,
    )


class TestLatencyTable:
    def test_absent_when_no_timings_recorded(self) -> None:
        # Reports written before stage_ms existed must still render.
        assert _md_latency(_result("baseline", {"faithfulness": 1.0})) == ""

    def test_stages_ordered_slowest_first(self) -> None:
        table = _md_latency(_timed([{"routing": 100.0, "grading": 900.0, "retrieval": 400.0}]))
        rows = [r for r in table.splitlines() if r.startswith("| ") and "---" not in r]
        assert [r.split("|")[1].strip() for r in rows[1:]] == [
            "grading", "retrieval", "routing", "**total**",
        ]

    def test_total_is_the_sum_per_sample_not_the_sum_of_percentiles(self) -> None:
        # Sample A is slow at retrieval, B slow at grading. Adding the two p50s
        # would invent a 900 ms request that never happened; both totals are 600.
        table = _md_latency(_timed([
            {"retrieval": 500.0, "grading": 100.0},
            {"retrieval": 100.0, "grading": 500.0},
        ]))
        total = next(r for r in table.splitlines() if "**total**" in r)
        assert "**600**" in total

    def test_percentile_uses_nearest_rank(self) -> None:
        # 15 samples, one outlier: p95 must surface it, p50 must not.
        values = [{"grading": 100.0} for _ in range(14)] + [{"grading": 9000.0}]
        table = _md_latency(_timed(values))
        row = next(r for r in table.splitlines() if r.startswith("| grading"))
        assert row.split("|")[2].strip() == "100"
        assert row.split("|")[3].strip() == "9000"

    def test_says_run_duration_is_not_comparable(self) -> None:
        # The footnote exists so nobody reads concurrency-wide wall clock as latency.
        assert "concurrency-wide" in _md_latency(_timed([{"grading": 1.0}]))

    def test_table_reaches_the_markdown_report(self) -> None:
        assert "p95 ms" in _md_table(_timed([{"grading": 120.0}]))


# ── Refusals ──────────────────────────────────────────────────────────────────

def _mixed(scores_per_sample: list[tuple[float, bool]]) -> EvalResult:
    """One metric ("faithfulness"), one (score, applicable) pair per sample."""
    samples = [
        SampleResult(
            sample_id=f"s{i}", question="q", generated_answer="a",
            retrieved_chunk_ids=["c1"],
            metrics=[
                MetricScore(metric_name="faithfulness", score=score, applicable=applicable)
            ],
        )
        for i, (score, applicable) in enumerate(scores_per_sample)
    ]
    return EvalResult(
        pipeline_config=PipelineConfig(name="run"),
        sample_results=samples,
        aggregate_scores={"faithfulness": 1.0},
        total_tokens_used=0,
        duration_seconds=5.2,
    )


class TestInapplicableScores:
    def test_table_says_how_many_samples_the_mean_covers(self) -> None:
        md = _md_table(_mixed([(1.0, True), (1.0, True), (1.0, False)]))
        assert "over 2 of 3" in md
        assert "1 n/a" in md

    def test_silent_when_every_sample_counted(self) -> None:
        # The annotation is an exception report; a clean run must stay clean.
        assert "n/a" not in _md_table(_mixed([(1.0, True), (0.9, True)]))

    def test_metrics_default_to_applicable(self) -> None:
        # Reports and metrics written before the flag existed must not vanish
        # from the aggregate.
        assert MetricScore(metric_name="faithfulness", score=0.5).applicable is True


# ── Served models ─────────────────────────────────────────────────────────────

def _served(model_calls: dict[str, int]) -> EvalResult:
    return EvalResult(
        pipeline_config=PipelineConfig(name="run"),
        sample_results=[
            SampleResult(
                sample_id="s1", question="q", generated_answer="a",
                retrieved_chunk_ids=["c1"],
                metrics=[MetricScore(metric_name="faithfulness", score=1.0)],
            )
        ],
        aggregate_scores={"faithfulness": 1.0},
        total_tokens_used=0,
        duration_seconds=1.0,
        model_calls=model_calls,
    )


class TestServedModels:
    def test_single_model_run_says_nothing(self) -> None:
        # The config line already names the primary; repeating it is noise.
        assert "Mixed models" not in _md_table(_served({"gemini-3.1-flash-lite": 90}))

    def test_fallback_run_is_called_out_with_shares(self) -> None:
        md = _md_table(_served({"gemini-3.1-flash-lite": 10, "gemini-3.5-flash-lite": 90}))
        assert "Mixed models" in md
        assert "gemini-3.5-flash-lite 90 (90%)" in md
        assert "not a clean measurement" in md

    def test_majority_model_listed_first(self) -> None:
        md = _md_table(_served({"primary": 1, "fallback": 99}))
        assert md.index("fallback 99") < md.index("primary 1")

    def test_old_reports_without_the_field_still_render(self) -> None:
        assert "Mixed models" not in _md_table(_result("cfg", {"faithfulness": 1.0}))


# ── Comparability ─────────────────────────────────────────────────────────────

def _provenance(
    name: str,
    scores: dict,
    sample_ids: list[str],
    fingerprint: str = "",
    dataset_name: str = "",
) -> EvalResult:
    return EvalResult(
        pipeline_config=PipelineConfig(name=name),
        sample_results=[
            SampleResult(
                sample_id=sid, question="q", generated_answer="a",
                retrieved_chunk_ids=["c1"],
                metrics=[MetricScore(metric_name=k, score=v) for k, v in scores.items()],
            )
            for sid in sample_ids
        ],
        aggregate_scores=scores,
        dataset_name=dataset_name,
        dataset_fingerprint=fingerprint,
    )


class TestComparabilityGuard:
    """`compare` prints **Overall winner**, which is the sentence a wrong
    comparison gets quoted as. Until 2026-09-28 it would produce one between
    a 30-question HR run and a 15-question FastAPI run, and the module
    docstring claimed it raised ValueError in that case. It did not."""

    def test_different_sample_sets_are_refused(self) -> None:
        a = _provenance("a", {"context_precision": 0.9}, ["hr-1", "hr-2"])
        b = _provenance("b", {"context_precision": 0.1}, ["fq-001"])

        with pytest.raises(DatasetMismatch, match="different samples"):
            compare(a, b)

    def test_the_sample_check_works_without_any_new_field(self) -> None:
        """Derived from sample_results, so it applies to reports written
        before the provenance fields existed — including the twelve already
        in eval_data/reports."""
        a = _provenance("a", {"m": 0.5}, ["s1", "s2"])
        b = _provenance("b", {"m": 0.5}, ["s1", "s2", "s3"])
        assert a.dataset_fingerprint == ""

        with pytest.raises(DatasetMismatch, match="2 and 3"):
            compare(a, b)

    def test_a_relabelling_is_refused_even_though_the_ids_match(self) -> None:
        """The 2026-09-27 audit: nine of fifteen rows relabelled, same file
        name, same fifteen ids, every prior number quietly incomparable."""
        a = _provenance("a", {"m": 0.37}, ["fq-001"], fingerprint="before")
        b = _provenance("b", {"m": 0.47}, ["fq-001"], fingerprint="after")

        with pytest.raises(DatasetMismatch, match="labels changed"):
            compare(a, b)

    def test_the_error_names_the_datasets_when_they_differ(self) -> None:
        a = _provenance("a", {"m": 0.5}, ["s1"], fingerprint="x", dataset_name="hr")
        b = _provenance("b", {"m": 0.5}, ["s1"], fingerprint="y", dataset_name="fastapi")

        with pytest.raises(DatasetMismatch, match="'hr' vs 'fastapi'"):
            compare(a, b)

    def test_matching_fingerprints_compare_cleanly(self) -> None:
        a = _provenance("a", {"m": 0.30}, ["s1"], fingerprint="same")
        b = _provenance("b", {"m": 0.50}, ["s1"], fingerprint="same")

        comparison = compare(a, b)

        assert comparison.notes == []
        assert comparison.overall_winner == "B"

    def test_a_missing_fingerprint_is_a_note_not_a_refusal(self) -> None:
        """Not knowing whether two runs match is a different state from
        knowing they do, and it is said out loud rather than assumed."""
        a = _provenance("a", {"m": 0.30}, ["s1"])
        b = _provenance("b", {"m": 0.50}, ["s1"], fingerprint="new")

        comparison = compare(a, b)

        assert len(comparison.notes) == 1
        assert "Run A does not carry" in comparison.notes[0]
        assert "Unverified" in comparison.as_markdown()

    def test_neither_side_carrying_one_says_neither(self) -> None:
        comparison = compare(
            _provenance("a", {"m": 0.3}, ["s1"]), _provenance("b", {"m": 0.5}, ["s1"])
        )
        assert "Neither run carries" in comparison.notes[0]


class TestDatasetFingerprint:
    """What makes two runs the same measurement."""

    @staticmethod
    def _dataset(labels: list[str], question: str = "How?", name: str = "ds") -> EvalDataset:
        return EvalDataset(
            name=name,
            samples=[
                EvalSample(
                    id="s1",
                    question=question,
                    ground_truth_answer="Like this.",
                    relevant_doc_ids=labels,
                )
            ],
        )

    def test_the_same_dataset_fingerprints_the_same(self) -> None:
        assert dataset_fingerprint(self._dataset(["a/b"])) == dataset_fingerprint(
            self._dataset(["a/b"])
        )

    def test_a_relabelling_changes_it(self) -> None:
        assert dataset_fingerprint(self._dataset(["a/b"])) != dataset_fingerprint(
            self._dataset(["a/b", "c/d"])
        )

    def test_a_reworded_question_changes_it(self) -> None:
        """The question is what the retriever is given, so it is part of the
        measurement even when the labels are untouched."""
        assert dataset_fingerprint(self._dataset(["a/b"])) != dataset_fingerprint(
            self._dataset(["a/b"], question="How, exactly?")
        )

    def test_label_order_and_repeats_do_not_change_it(self) -> None:
        """Recall works on a set, so neither is a different measurement."""
        assert dataset_fingerprint(self._dataset(["a/b", "c/d"])) == dataset_fingerprint(
            self._dataset(["c/d", "a/b", "a/b"])
        )

    def test_a_rewritten_reference_answer_does_not_change_it(self) -> None:
        """Still true after `answer_correctness` arrived on 2026-09-28, and
        the reason changed. Four of the five metrics do not read
        `ground_truth_answer`, so folding it in here would refuse a
        precision comparison over a field that cannot move precision. The
        reference answers get their own fingerprint instead, checked only
        between two runs that both measured correctness."""
        a = self._dataset(["a/b"])
        b = self._dataset(["a/b"])
        b.samples[0].ground_truth_answer = "Completely differently."
        assert dataset_fingerprint(a) == dataset_fingerprint(b)
        assert dataset_answers_fingerprint(a) != dataset_answers_fingerprint(b)

    def test_the_answers_fingerprint_ignores_labels_and_questions(self) -> None:
        """The mirror image: `answer_correctness` reads neither, so neither
        makes two correctness scores incomparable."""
        a = self._dataset(["a/b"])
        b = self._dataset(["c/d"], question="Phrased another way?")
        assert dataset_answers_fingerprint(a) == dataset_answers_fingerprint(b)

    def test_the_shipped_datasets_fingerprint_differently(self) -> None:
        fastapi, _ = load_dataset(Path("eval_data/fastapi_dataset.json"), strict=False)
        sample, _ = load_dataset(Path("eval_data/sample_dataset.json"), strict=False)
        assert dataset_fingerprint(fastapi) != dataset_fingerprint(sample)


# ── Token accounting ──────────────────────────────────────────────────────────

def _spent(
    usage: dict[str, ModelUsage] | None = None,
    total: int = 0,
    fingerprint: str = "fp",
) -> EvalResult:
    return EvalResult(
        pipeline_config=PipelineConfig(name="run"),
        sample_results=[
            SampleResult(
                sample_id="s1", question="q", generated_answer="a",
                retrieved_chunk_ids=["c1"],
                metrics=[MetricScore(metric_name="faithfulness", score=1.0)],
            )
        ],
        aggregate_scores={"faithfulness": 1.0},
        token_usage=usage or {},
        total_tokens_used=total,
        dataset_fingerprint=fingerprint,
        duration_seconds=1.0,
    )


_CHAT = {"gemini-3.1-flash-lite": ModelUsage(kind="chat", calls=75,
                                             prompt_tokens=300_000, completion_tokens=9_000)}
_CHAT_AND_EMBED = _CHAT | {
    "gemini-embedding-001": ModelUsage(kind="embedding", calls=15, prompt_tokens=400)
}


class TestTokenReporting:
    def test_per_model_breakdown_is_printed(self) -> None:
        md = _md_table(_spent(_CHAT_AND_EMBED, total=309_400))
        assert "gemini-3.1-flash-lite (chat) | 75 | 300,000 | 9,000" in md
        assert "gemini-embedding-001 (embedding) | 15 | 400 | —" in md

    def test_cost_is_estimated_per_model_not_per_total(self) -> None:
        """Chat and embedding prices differ by more than 10x, so one total
        cannot be priced — the split is the whole point of the breakdown."""
        md = _md_table(_spent(_CHAT_AND_EMBED, total=309_400))
        expected = estimate_usage_cost(_CHAT_AND_EMBED)
        assert f"${expected:.4f}" in md
        assert "₹" in md

    def test_a_pre_2026_09_28_report_says_what_its_total_means(self) -> None:
        """Generation-only and complete totals differ by roughly 2x. Both
        kinds of report live in eval_data/reports and will be read side by
        side, so the older one has to arrive labelled."""
        md = _md_table(_spent(total=120_000))
        assert "generation call only" in md
        assert "| Model | Calls |" not in md

    def test_a_complete_report_carries_no_qualifier(self) -> None:
        assert "generation call only" not in _md_table(_spent(_CHAT, total=309_000))

    def test_a_run_that_spent_nothing_says_nothing(self) -> None:
        md = _md_table(_spent(total=0))
        assert "generation call only" not in md


class TestTokenComparability:
    def test_mixed_provenance_is_noted(self) -> None:
        old = _spent(total=120_000)
        new = _spent(_CHAT_AND_EMBED, total=309_400)
        result = compare(old, new)

        assert any("generation call only" in n for n in result.notes)
        assert "Unverified" in result.as_markdown()

    def test_two_complete_reports_get_no_note(self) -> None:
        assert compare(_spent(_CHAT, total=309_000), _spent(_CHAT, total=309_000)).notes == []

    def test_two_legacy_reports_are_comparable_with_each_other(self) -> None:
        """Both counted the same wrong thing, so the ratio still holds —
        which is exactly why this was never noticed."""
        assert compare(_spent(total=120_000), _spent(total=130_000)).notes == []

    def test_the_note_does_not_suppress_the_metric_deltas(self) -> None:
        old = _spent(total=120_000)
        new = _spent(_CHAT, total=309_000)
        assert compare(old, new).deltas


# ── Correctness: a fifth metric, and what it does to a comparison ─────────────

def _graded(
    correctness: float | None,
    answers: str = "ans-fp",
    precision: float = 0.46,
) -> EvalResult:
    scores: dict[str, float] = {"context_precision": precision}
    if correctness is not None:
        scores["answer_correctness"] = correctness
    return EvalResult(
        pipeline_config=PipelineConfig(name="run"),
        sample_results=[
            SampleResult(
                sample_id="s1", question="q", generated_answer="a",
                retrieved_chunk_ids=["c1"],
                metrics=[MetricScore(metric_name=k, score=v) for k, v in scores.items()],
            )
        ],
        aggregate_scores=scores,
        dataset_fingerprint="fp",
        answers_fingerprint=answers,
    )


class TestOneSidedMetrics:
    """A metric only one run computed. Before answer_correctness existed
    every run had the same four, so `aggregate_scores.get(metric, 0.0)`
    never fired — and the first run carrying a fifth would have shown
    0.0 -> 0.85 against every stored baseline and called it an improvement."""

    def test_a_new_metric_is_not_a_win(self) -> None:
        result = compare(_graded(None), _graded(0.85))
        correctness = next(d for d in result.deltas if d.metric == "answer_correctness")

        assert correctness.winner == "n/a"
        assert correctness.missing_in == "A"
        assert result.overall_winner == "tie"

    def test_it_renders_without_a_delta(self) -> None:
        md = compare(_graded(None), _graded(0.85)).as_markdown()
        assert "| answer_correctness | — | 0.8500 | — | not measured in A |" in md

    def test_it_is_called_out_in_the_notes(self) -> None:
        notes = compare(_graded(None), _graded(0.85)).notes
        assert any("measured only in B" in n for n in notes)

    def test_the_shared_metrics_still_compare(self) -> None:
        result = compare(_graded(None, precision=0.40), _graded(0.85, precision=0.46))
        precision = next(d for d in result.deltas if d.metric == "context_precision")
        assert precision.delta == pytest.approx(0.06)
        assert precision.winner == "B"


class TestAnswersFingerprint:
    def test_two_correctness_runs_on_different_references_are_refused(self) -> None:
        """`answer_correctness` reads the reference answer directly, so a
        rewrite of one — which is what happened to fq-010 on 2026-09-27 —
        makes two correctness scores different measurements."""
        with pytest.raises(DatasetMismatch, match="different reference answers"):
            compare(_graded(0.80, answers="before"), _graded(0.85, answers="after"))

    def test_the_same_references_compare_fine(self) -> None:
        assert compare(_graded(0.80), _graded(0.85)).overall_winner == "B"

    def test_a_rewrite_does_not_block_a_precision_comparison(self) -> None:
        """The other four metrics cannot depend on the reference answer, so
        refusing here would be a guard crying wolf — and a guard that cries
        wolf is one that gets bypassed with a flag."""
        a = _graded(None, answers="before", precision=0.40)
        b = _graded(None, answers="after", precision=0.46)
        assert compare(a, b).overall_winner == "B"

    def test_a_report_without_the_field_is_not_refused(self) -> None:
        """Every report written before 2026-09-28 carries an empty one."""
        old = _graded(0.80, answers="")
        assert compare(old, _graded(0.85)).overall_winner == "B"


# ── The budget: planning/BUDGET.md, enforced by compare() ─────────────────────

def _budget_run(
    stage_totals: list[float],
    usage: dict | None = None,
    *,
    precision: float = 0.46,
    recall: float | None = None,
    name: str = "run",
    timed: bool = True,
) -> EvalResult:
    """A run with per-sample latency, and optionally per-model tokens.

    `stage_totals` is one end-to-end figure per sample; it is split across two
    stages so the result exercises the same summing the reporter does.
    """
    scores: dict[str, float] = {"context_precision": precision}
    if recall is not None:
        scores["context_recall"] = recall
    samples = [
        SampleResult(
            sample_id=f"s{i}", question="q", generated_answer="a",
            retrieved_chunk_ids=["c1"],
            metrics=[MetricScore(metric_name=k, score=v) for k, v in scores.items()],
            stage_ms=(
                {"retrieval": total * 0.6, "generation": total * 0.4} if timed else {}
            ),
        )
        for i, total in enumerate(stage_totals)
    ]
    return EvalResult(
        pipeline_config=PipelineConfig(name=name),
        sample_results=samples,
        aggregate_scores=scores,
        dataset_fingerprint="fp",
        token_usage=usage or {},
        total_tokens_used=sum(
            u.prompt_tokens + u.completion_tokens for u in (usage or {}).values()
        ),
    )


def _at(ms: float) -> list[float]:
    """Sixteen samples all at the same latency, so p50 == p95 == ms and a
    test says which threshold it is about."""
    return [ms] * 16


class TestBudgetLatency:
    def test_a_run_inside_the_ceilings_keeps_its_winner(self) -> None:
        result = compare(
            _budget_run(_at(10_000), precision=0.40),
            _budget_run(_at(10_500), precision=0.46),
        )
        assert result.budget_breaches == []
        assert result.overall_winner == "B"
        assert "**Overall winner: B**" in result.as_markdown()

    def test_p95_rising_past_the_allowance_withholds_the_winner(self) -> None:
        """+15% is the agreed allowance. The quality win is real and still
        reported — it is the word "winner" that is withheld, because that is
        the sentence a regression ships quoted as."""
        result = compare(
            _budget_run(_at(10_000), precision=0.40),
            _budget_run(_at(11_600), precision=0.46),   # +16%
        )
        assert result.overall_winner == "B"             # quality verdict unchanged
        assert any("rose +16.0%" in b for b in result.budget_breaches)

        md = result.as_markdown()
        assert "**Overall winner: withheld**" in md
        assert "B wins on quality" in md
        assert "**Overall winner: B**" not in md

    def test_the_absolute_ceiling_bites_even_inside_the_allowance(self) -> None:
        """A run already near the ceiling can regress by less than 15% and
        still land outside the budget, so both are checked."""
        result = compare(_budget_run(_at(19_000)), _budget_run(_at(20_900)))  # +10%
        assert any("over the 20,000 ms ceiling" in b for b in result.budget_breaches)

    def test_p50_has_its_own_ceiling_and_no_allowance(self) -> None:
        p50 = next(d for d in compare(
            _budget_run(_at(9_000)), _budget_run(_at(12_500))
        ).budget if d.name == "warm p50 latency")
        assert p50.limit is None
        assert "over the 12,000 ms ceiling" in p50.breach

    def test_getting_faster_is_never_a_breach(self) -> None:
        assert compare(_budget_run(_at(17_000)), _budget_run(_at(9_000))).budget_breaches == []

    def test_the_p95_is_the_one_the_report_prints(self) -> None:
        """The budget check and the latency table have to agree, or a change
        is judged on a number nobody can see. Nearest-rank, both sides."""
        from atlas.evaluation.reporter import percentile

        totals = [6_457, 8_173, 10_053, 10_566, 15_671, 17_072]
        run = _budget_run(totals)
        measured = next(
            d for d in compare(run, run).budget if d.name == "warm p95 latency"
        )
        assert measured.value_b == pytest.approx(percentile(totals, 95))
        assert f"{percentile(totals, 95):.0f}" in _md_latency(run)

    def test_a_run_without_stage_ms_is_not_a_compliant_run(self) -> None:
        """Several stored reports predate the field. An unmeasurable budget
        must read as unmeasured, not as passed."""
        result = compare(_result("A", {"faithfulness": 0.8}),
                         _result("B", {"faithfulness": 0.9}))
        assert not [d for d in result.budget if d.unit == "ms"]
        assert any("latency half of the budget is unchecked" in n
                   for n in result.budget_notes)

    def test_one_run_missing_it_is_named(self) -> None:
        """The common case: a new run compared against a stored baseline from
        before `stage_ms` existed."""
        result = compare(_budget_run(_at(9_000), precision=0.40, timed=False),
                         _budget_run(_at(9_000), precision=0.46))
        assert not [d for d in result.budget if d.unit == "ms"]
        assert any("Run A did not record" in n for n in result.budget_notes)


class TestBudgetCost:
    def test_run_cost_is_priced_from_the_per_model_breakdown(self) -> None:
        cost = next(d for d in compare(
            _budget_run(_at(9_000), _CHAT_AND_EMBED),
            _budget_run(_at(9_000), _CHAT_AND_EMBED),
        ).budget if d.unit == "USD")
        assert cost.value_b == pytest.approx(estimate_usage_cost(_CHAT_AND_EMBED), abs=1e-4)

    def test_cost_rising_past_the_allowance_withholds_the_winner(self) -> None:
        cheap = {"gemini-3.1-flash-lite": ModelUsage(
            kind="chat", calls=75, prompt_tokens=100_000, completion_tokens=5_000)}
        dear = {"gemini-3.1-flash-lite": ModelUsage(
            kind="chat", calls=75, prompt_tokens=130_000, completion_tokens=6_500)}
        result = compare(
            _budget_run(_at(9_000), cheap, precision=0.40),
            _budget_run(_at(9_000), dear, precision=0.46),
        )
        assert any("eval run cost rose +30.0%" in b for b in result.budget_breaches)
        assert "**Overall winner: withheld**" in result.as_markdown()

    def test_the_run_ceiling_is_checked_too(self) -> None:
        huge = {"gemini-3.1-flash-lite": ModelUsage(
            kind="chat", calls=900, prompt_tokens=4_000_000, completion_tokens=100_000)}
        result = compare(_budget_run(_at(9_000), huge), _budget_run(_at(9_000), huge))
        assert any("over the $0.1000 ceiling" in b for b in result.budget_breaches)

    def test_it_says_the_figure_is_a_run_and_not_a_query(self) -> None:
        """An eval run pays the metric judges as well — ~7.8 chat calls a
        sample against production's ~4 — so this is not cost per query, and
        a reader who takes it for one will under-budget production."""
        notes = compare(
            _budget_run(_at(9_000), _CHAT), _budget_run(_at(9_000), _CHAT)
        ).budget_notes
        assert any("not the production cost per query" in n for n in notes)

    def test_different_metric_sets_make_the_cost_unjudgeable(self) -> None:
        """The judges spend tokens. A run carrying a fifth metric costs more
        for that reason alone, so there is no cost verdict to give."""
        result = compare(
            _budget_run(_at(9_000), _CHAT, recall=None),
            _budget_run(_at(9_000), _CHAT, recall=0.93),
        )
        assert not [d for d in result.budget if d.unit == "USD"]
        assert any("did not measure the same metrics" in n for n in result.budget_notes)

    def test_a_legacy_report_cannot_be_priced(self) -> None:
        result = compare(_budget_run(_at(9_000)), _budget_run(_at(9_000), _CHAT))
        assert not [d for d in result.budget if d.unit == "USD"]
        assert any("Run A carries" in n for n in result.budget_notes)


class TestBudgetRendering:
    def test_a_breach_names_what_it_needs_to_ship(self) -> None:
        md = compare(
            _budget_run(_at(10_000), precision=0.40),
            _budget_run(_at(12_000), precision=0.46),
        ).as_markdown()
        assert "planning/DECISIONS.md" in md
        assert "breached" in md

    def test_the_table_shows_both_runs_and_the_verdict(self) -> None:
        md = compare(
            _budget_run(_at(10_000), name="before"),
            _budget_run(_at(10_000), name="after"),
        ).as_markdown()
        assert "### Budget (planning/BUDGET.md)" in md
        assert "| warm p95 latency | 10,000 ms | 10,000 ms | +0.0% | +15% | 20,000 ms | ok |" in md

    def test_breaches_are_distinguishable_from_an_unchecked_budget(self) -> None:
        """No breaches and no budget are the same empty list, so the notes
        are the only thing that tells them apart."""
        unchecked = compare(_result("A", {"faithfulness": 0.8}),
                            _result("B", {"faithfulness": 0.8}))
        assert unchecked.budget_breaches == []
        assert unchecked.budget == []
        assert unchecked.budget_notes

    def test_the_table_and_the_breach_quote_the_same_percentage(self) -> None:
        """One measurement, one number. Rounding after formatting gave
        +21.2% in the table and +21.3% in the sentence beneath it."""
        md = compare(_budget_run(_at(17_072)), _budget_run(_at(20_700))).as_markdown()
        percentages = {line.split("rose ")[1].split(" ")[0]
                       for line in md.splitlines() if "rose " in line}
        assert len(percentages) == 1
        assert percentages.pop() in md.split("### Budget")[1].split("**Overall")[0]
