"""
Tests for reporter (JSON + markdown output) and A/B comparator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.cost import estimate_usage_cost
from atlas.evaluation.comparator import (
    ComparisonResult,
    DatasetMismatch,
    compare,
    noise_floor,
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

# Enough rows for a delta to be provable. `compare` now gates a winner on a
# paired signed-rank test as well as the rerun floor, and that test cannot
# reject below six differing rows whatever they say — so a one-row fixture
# can express a delta but not a result, and every "B wins" assertion built on
# one was asserting something the comparator should refuse. Eight unanimous
# rows give p=0.0078, comfortably inside alpha with room to flip one.
_ROWS = 8


def _ids(count: int = _ROWS) -> list[str]:
    return [f"s{i + 1}" for i in range(count)]


def _result(name: str, scores: dict) -> EvalResult:
    # Every row carries the run's mean, so `aggregate_scores` stays the mean
    # of the rows and the fixture says one thing rather than two.
    samples = [
        SampleResult(
            sample_id=sid, question="q", generated_answer="a",
            retrieved_chunk_ids=["c1"],
            metrics=[MetricScore(metric_name=k, score=v) for k, v in scores.items()],
        )
        for sid in _ids()
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
        assert f"{_ROWS} samples" in md

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
        tiny = noise_floor("faithfulness") / 2
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
        a = _provenance("a", {"m": 0.30}, _ids(), fingerprint="same")
        b = _provenance("b", {"m": 0.50}, _ids(), fingerprint="same")

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


class TestCostPerQuery:
    """The run total cannot answer "what does a production query cost?" --
    it includes the judges. Before per-sample usage existed the figure was
    hand-checked, and the comparator said so in its own output.
    """

    @staticmethod
    def _run(per_sample: dict[str, ModelUsage] | None, samples: int = 2) -> EvalResult:
        # Run total = 4x the pipeline's chat tokens, i.e. the judges spent as
        # much again as the pipeline did, per sample.
        run_usage = {"m": ModelUsage(kind="chat", calls=4 * samples,
                                     prompt_tokens=400 * samples,
                                     completion_tokens=40 * samples)}
        return EvalResult(
            pipeline_config=PipelineConfig(name="run"),
            sample_results=[
                SampleResult(
                    sample_id=f"s{i}", question="q", generated_answer="a",
                    retrieved_chunk_ids=["c1"],
                    metrics=[MetricScore(metric_name="faithfulness", score=1.0)],
                    token_usage=per_sample or {},
                )
                for i in range(samples)
            ],
            aggregate_scores={"faithfulness": 1.0},
            token_usage=run_usage,
            total_tokens_used=440 * samples,
            dataset_fingerprint="fp",
            duration_seconds=1.0,
        )

    def test_it_prices_the_pipeline_not_the_run(self) -> None:
        pipeline = {"m": ModelUsage(kind="chat", calls=2,
                                    prompt_tokens=100, completion_tokens=10)}
        md = _md_table(self._run(pipeline))

        expected = estimate_usage_cost(pipeline)
        assert f"${expected:.5f}" in md
        assert "Cost per query" in md
        assert "judges excluded" in md

    def test_it_is_not_the_run_total_divided_by_samples(self) -> None:
        """The failure this exists to prevent: dividing a contaminated total
        by sample count and calling it a production figure."""
        pipeline = {"m": ModelUsage(kind="chat", calls=2,
                                    prompt_tokens=100, completion_tokens=10)}
        result = self._run(pipeline)
        md = _md_table(result)

        naive = estimate_usage_cost(result.token_usage) / len(result.sample_results)
        honest = estimate_usage_cost(pipeline)
        assert naive > honest, "the fixture must actually have judge contamination"
        assert f"${naive:.5f}" not in md

    def test_an_old_report_omits_the_line_entirely(self) -> None:
        """Every report on disk predates per-sample usage. Computing the line
        from the run total would print exactly the wrong number."""
        md = _md_table(self._run(None))
        assert "Cost per query" not in md
        # The per-model breakdown is still there -- only the derived line goes.
        assert "| Model | Calls |" in md

    def test_the_judges_share_is_named(self) -> None:
        pipeline = {"m": ModelUsage(kind="chat", calls=2,
                                    prompt_tokens=100, completion_tokens=10)}
        result = self._run(pipeline)
        judged = estimate_usage_cost(result.token_usage) - 2 * estimate_usage_cost(pipeline)
        assert f"${judged:.4f}" in _md_table(result)


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
                sample_id=sid, question="q", generated_answer="a",
                retrieved_chunk_ids=["c1"],
                metrics=[MetricScore(metric_name=k, score=v) for k, v in scores.items()],
            )
            for sid in _ids()
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
        assert (
            "| answer_correctness | — | 0.8500 | — | — | not measured in A |"
            in md
        )

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
        # 0.95, not 0.85: +0.05 sits inside answer_correctness's measured
        # rerun noise and is correctly a tie now. The subject here is that
        # the guard lets the comparison through at all.
        assert compare(_graded(0.80), _graded(0.95)).overall_winner == "B"

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
        assert compare(old, _graded(0.95)).overall_winner == "B"


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


# ── Failed samples: a mean over fewer rows, 2026-10-17 ────────────────────────
#
# A sample that errors is recorded applicable with score=-1.0 and dropped from
# the run's mean. Neither the report nor the comparator said so, so a run that
# lost two of sixteen rows rendered as a clean sixteen and was compared,
# mean-for-mean, against a run that had scored all of them. That flipped
# answer_correctness from a reported +0.0113 tie to a real -0.0238 regression
# and halved a measured latency breach. These tests are that run, shrunk.

_FAILED = -1.0


def _scored(
    name: str,
    per_sample: dict[str, dict[str, float]],
    *,
    stage_ms: dict[str, dict[str, float]] | None = None,
    usage: dict | None = None,
) -> EvalResult:
    """A run whose per-sample scores are given explicitly, aggregated the way
    `runner` aggregates: the sentinel is left out of the mean."""
    samples = [
        SampleResult(
            sample_id=sid, question="q", generated_answer="a",
            retrieved_chunk_ids=["c1"],
            metrics=[MetricScore(metric_name=k, score=v) for k, v in scores.items()],
            stage_ms=(stage_ms or {}).get(sid, {}),
        )
        for sid, scores in per_sample.items()
    ]
    metric_names = {k for s in per_sample.values() for k in s}
    aggregate = {}
    for metric in metric_names:
        valid = [
            s[metric] for s in per_sample.values()
            if metric in s and s[metric] != _FAILED
        ]
        aggregate[metric] = round(sum(valid) / len(valid), 4) if valid else 0.0
    return EvalResult(
        pipeline_config=PipelineConfig(name=name),
        sample_results=samples,
        aggregate_scores=aggregate,
        total_tokens_used=0,
        duration_seconds=1.0,
        token_usage=usage or {},
    )


class TestFailedSamplesInReport:
    def test_failed_sample_is_named_in_the_table(self) -> None:
        # The bug: this rendered "1.0000" with no qualifier at all, because
        # _inapplicable_counts only ever saw applicable=False.
        result = _scored("run", {
            "s1": {"faithfulness": 1.0},
            "s2": {"faithfulness": _FAILED},
        })
        md = _md_table(result)
        assert "1 failed" in md
        assert "over 1 of 2" in md

    def test_refusal_and_crash_are_counted_apart(self) -> None:
        result = EvalResult(
            pipeline_config=PipelineConfig(name="run"),
            sample_results=[
                SampleResult(
                    sample_id="s1", question="q", generated_answer="a",
                    retrieved_chunk_ids=[],
                    metrics=[MetricScore(metric_name="faithfulness", score=1.0)],
                ),
                SampleResult(
                    sample_id="s2", question="q", generated_answer="a",
                    retrieved_chunk_ids=[],
                    metrics=[MetricScore(
                        metric_name="faithfulness", score=0.0, applicable=False)],
                ),
                SampleResult(
                    sample_id="s3", question="q", generated_answer="a",
                    retrieved_chunk_ids=[],
                    metrics=[MetricScore(metric_name="faithfulness", score=_FAILED)],
                ),
            ],
            aggregate_scores={"faithfulness": 1.0},
            total_tokens_used=0, duration_seconds=1.0,
        )
        md = _md_table(result)
        assert "1 n/a" in md
        assert "1 failed" in md
        assert "over 1 of 3" in md

    def test_clean_run_gets_no_qualifier(self) -> None:
        md = _md_table(_scored("run", {"s1": {"faithfulness": 1.0}}))
        assert "failed" not in md
        assert "n/a" not in md


class TestPairedMetricComparison:
    def _runs(self) -> tuple[EvalResult, EvalResult]:
        # A scores every row; B loses s3, which is A's best row. A's stored
        # mean is over three rows, B's over two.
        a = _scored("A", {
            "s1": {"answer_correctness": 0.60},
            "s2": {"answer_correctness": 0.60},
            "s3": {"answer_correctness": 1.00},
        })
        b = _scored("B", {
            "s1": {"answer_correctness": 0.66},
            "s2": {"answer_correctness": 0.66},
            "s3": {"answer_correctness": _FAILED},
        })
        return a, b

    def test_unpaired_means_would_have_called_it_a_regression(self) -> None:
        a, b = self._runs()
        # The stored aggregates: A 0.7333 over 3, B 0.6600 over 2. Comparing
        # those says B lost by 0.0733. On the rows they share, B won by 0.06.
        assert a.aggregate_scores["answer_correctness"] == pytest.approx(0.7333)
        assert b.aggregate_scores["answer_correctness"] == pytest.approx(0.66)

    def test_means_are_recomputed_over_the_shared_rows(self) -> None:
        a, b = self._runs()
        c = compare(a, b)
        delta = next(d for d in c.deltas if d.metric == "answer_correctness")
        assert delta.score_a == pytest.approx(0.60)
        assert delta.score_b == pytest.approx(0.66)
        assert delta.delta == pytest.approx(0.06)
        assert delta.paired_n == 2
        # Sign, not winner. Pairing is what this class is about, and pairing
        # turns an apparent -0.0733 regression into a +0.06 improvement. The
        # winner label is a separate judgement: +0.06 is inside
        # answer_correctness's measured rerun noise of 0.0565, so the
        # comparator calls it a tie, and that is correct. Before the floors
        # were measured this asserted "B", which is how a delta smaller than
        # noise used to win a column.
        assert delta.delta > 0
        assert delta.winner == "tie"

    def test_the_pairing_is_stated_not_silent(self) -> None:
        a, b = self._runs()
        c = compare(a, b)
        note = " ".join(c.notes)
        assert "B did not score s3" in note
        assert "recomputed over the 2 they share" in note
        assert "paired n=2" in c.as_markdown()

    def test_matching_denominators_use_the_stored_aggregates(self) -> None:
        a = _scored("A", {"s1": {"faithfulness": 0.80}, "s2": {"faithfulness": 0.80}})
        b = _scored("B", {"s1": {"faithfulness": 0.90}, "s2": {"faithfulness": 0.90}})
        c = compare(a, b)
        delta = next(d for d in c.deltas if d.metric == "faithfulness")
        assert delta.paired_n is None
        assert "recomputed" not in " ".join(c.notes)

    def test_no_shared_scored_row_yields_no_winner(self) -> None:
        a = _scored("A", {
            "s1": {"faithfulness": 1.0}, "s2": {"faithfulness": _FAILED}})
        b = _scored("B", {
            "s1": {"faithfulness": _FAILED}, "s2": {"faithfulness": 1.0}})
        c = compare(a, b)
        delta = next(d for d in c.deltas if d.metric == "faithfulness")
        assert delta.winner == "n/a"
        assert "on no sample in common" in " ".join(c.notes)


class TestPairedBudget:
    def _runs(self) -> tuple[EvalResult, EvalResult]:
        # s3 is by far A's slowest row and B never timed it. Unpaired, A's p95
        # is s3 and B looks barely worse; paired, B is half again as slow.
        a = _scored(
            "A",
            {"s1": {"faithfulness": 1.0}, "s2": {"faithfulness": 1.0},
             "s3": {"faithfulness": 1.0}},
            stage_ms={
                "s1": {"total_stage": 1000.0},
                "s2": {"total_stage": 1000.0},
                "s3": {"total_stage": 9000.0},
            },
        )
        b = _scored(
            "B",
            {"s1": {"faithfulness": 1.0}, "s2": {"faithfulness": 1.0},
             "s3": {"faithfulness": _FAILED}},
            stage_ms={
                "s1": {"total_stage": 3000.0},
                "s2": {"total_stage": 3000.0},
            },
        )
        return a, b

    def test_latency_is_measured_on_the_rows_both_runs_timed(self) -> None:
        a, b = self._runs()
        c = compare(a, b)
        p95 = next(d for d in c.budget if d.name == "warm p95 latency")
        # Not 9000: that row is A's alone.
        assert p95.value_a == pytest.approx(1000.0)
        assert p95.value_b == pytest.approx(3000.0)
        assert p95.ratio == pytest.approx(2.0)

    def test_the_dropped_rows_are_named(self) -> None:
        a, b = self._runs()
        c = compare(a, b)
        assert "B is missing s3" in " ".join(c.budget_notes)

    def test_equal_timing_sets_are_left_alone(self) -> None:
        a, b = self._runs()
        a.sample_results[2].stage_ms = {}
        c = compare(a, b)
        assert "timed different samples" not in " ".join(c.budget_notes)


# ── Cost per query against its own ceiling, 2026-10-17 ───────────────────────
#
# BUDGET.md sets $0.005 a query and the comparator could not check it: a run
# total pays for the metric judges as well, and per-sample usage landed on
# 2026-10-14, so there was one report carrying it and a comparison needs two.
# There are two now.

def _priced(name: str, per_sample_usd: list[float], run_usd: float) -> EvalResult:
    """A run whose samples each report what they spent.

    `ModelUsage` is priced by `atlas.cost`, so the test works backwards from
    the dollar figure it wants rather than asserting a hard-coded token count.
    """
    def usage(usd: float) -> dict:
        one = ModelUsage(
            model="gemini-3.1-flash-lite", call_type="chat",
            calls=1, prompt_tokens=1_000_000, completion_tokens=0,
        )
        unit = estimate_usage_cost({"m": one})
        scale = usd / unit
        return {"m": ModelUsage(
            model="gemini-3.1-flash-lite", call_type="chat", calls=1,
            prompt_tokens=int(1_000_000 * scale), completion_tokens=0,
        )}

    samples = [
        SampleResult(
            sample_id=f"s{i}", question="q", generated_answer="a",
            retrieved_chunk_ids=[],
            metrics=[MetricScore(metric_name="faithfulness", score=1.0)],
            stage_ms={"total_stage": 1000.0},
            token_usage=usage(usd),
        )
        for i, usd in enumerate(per_sample_usd)
    ]
    return EvalResult(
        pipeline_config=PipelineConfig(name=name),
        sample_results=samples,
        aggregate_scores={"faithfulness": 1.0},
        total_tokens_used=0, duration_seconds=1.0,
        token_usage=usage(run_usd),
    )


class TestCostPerQueryBudget:
    """The budget line, as distinct from `TestCostPerQuery` above, which
    covers the figure the reporter prints for a single run."""

    def test_checked_when_both_runs_price_their_samples(self) -> None:
        a = _priced("A", [0.0030, 0.0030], run_usd=0.07)
        b = _priced("B", [0.0031, 0.0031], run_usd=0.07)
        line = next(
            d for d in compare(a, b).budget if d.name == "cost per query"
        )
        assert line.value_a == pytest.approx(0.0030, rel=1e-3)
        assert line.value_b == pytest.approx(0.0031, rel=1e-3)
        assert line.ceiling == pytest.approx(0.005)
        assert line.breach == ""

    def test_breaches_its_own_ceiling_independently_of_the_run_total(self) -> None:
        # The run total is well inside $0.100; the per-query figure is not
        # inside $0.005. Before this line existed, that shipped unremarked.
        a = _priced("A", [0.0030, 0.0030], run_usd=0.07)
        b = _priced("B", [0.0060, 0.0060], run_usd=0.08)
        comparison = compare(a, b)
        run = next(d for d in comparison.budget if d.name == "eval run cost")
        query = next(d for d in comparison.budget if d.name == "cost per query")
        assert run.breach == ""
        assert query.breach != ""
        assert "withheld" in comparison.as_markdown()

    def test_named_as_unchecked_when_a_report_predates_the_field(self) -> None:
        a = _priced("A", [0.0030, 0.0030], run_usd=0.07)
        b = _priced("B", [0.0030, 0.0030], run_usd=0.07)
        for sample in b.sample_results:
            sample.token_usage = {}
        comparison = compare(a, b)
        assert not any(d.name == "cost per query" for d in comparison.budget)
        assert "unchecked against its $0.005 ceiling" in " ".join(
            comparison.budget_notes
        )

    def test_a_sample_that_died_partway_is_not_priced_as_a_query(self) -> None:
        # It spent, so it has usage; it never finished, so it is not a query.
        # Averaging it in reports a query as cheaper than one costs.
        a = _priced("A", [0.0030, 0.0030], run_usd=0.07)
        b = _priced("B", [0.0040, 0.0040], run_usd=0.07)
        b.sample_results[1].stage_ms = {}     # died mid-pipeline
        b.sample_results[1].token_usage = _priced(
            "x", [0.0005], run_usd=0.01
        ).sample_results[0].token_usage
        line = next(d for d in compare(a, b).budget if d.name == "cost per query")
        assert line.value_b == pytest.approx(0.0040, rel=1e-3)
        assert "died partway is excluded" in " ".join(compare(a, b).budget_notes)


class TestTheNoiseFloorIsPerMetricAndMeasured:
    """One blanket 0.02 was wrong in both directions on the same report.

    Measured 2026-10-21 by `scripts/measure_noise_floor.py` over reruns of
    the same pipeline on identical evidence: answer_relevance moves 0.0020 in
    the aggregate and answer_correctness moves 0.0565. At a flat 0.02 the
    first could not win below 0.02 — ten times its real floor — while the
    second declared "Overall winner: A" off pure rerun movement, which is
    what the 2026-10-19 router run printed before its declined rows were
    replayed.
    """

    def test_an_unmeasured_metric_keeps_the_old_blanket_value(self) -> None:
        # Honest default: 0.02 is what we can say about a number nobody has
        # characterised, and silently treating it as precise would be worse.
        assert noise_floor("some_future_metric") == pytest.approx(0.02)

    def test_the_coarse_judged_metric_has_the_widest_floor(self) -> None:
        assert noise_floor("answer_correctness") > noise_floor("answer_relevance")
        assert noise_floor("answer_correctness") > noise_floor("context_recall")

    def test_the_same_delta_is_a_tie_for_one_metric_and_a_win_for_another(self) -> None:
        # The entire point, in one assertion pair. 0.06 is inside what
        # answer_correctness does on a rerun and far outside what
        # answer_relevance does.
        correctness = compare(
            _result("A", {"answer_correctness": 0.70}),
            _result("B", {"answer_correctness": 0.76}),
        ).deltas[0]
        relevance = compare(
            _result("A", {"answer_relevance": 0.70}),
            _result("B", {"answer_relevance": 0.76}),
        ).deltas[0]
        assert correctness.delta == pytest.approx(relevance.delta)
        assert correctness.winner == "tie"
        assert relevance.winner == "B"

    def test_every_floor_clears_the_noise_the_script_measured(self) -> None:
        # Guards the direction that caused the bug. If someone lowers a floor
        # under the measured figure, noise starts winning columns again.
        # These are the numbers in `scripts/measure_noise_floor.py`'s output
        # on the reports committed with this change.
        measured = {
            "context_precision": 0.0000,
            "context_recall": 0.0000,
            "answer_relevance": 0.0020,
            "answer_correctness": 0.0565,
        }
        for metric, noise in measured.items():
            assert noise_floor(metric) >= noise, f"{metric} floor is under its measured noise"

    def test_the_report_names_the_floor_it_applied(self) -> None:
        # A reader who cannot see which floor applied cannot tell "smaller
        # than rerun noise" from "smaller than a number somebody picked".
        md = compare(
            _result("A", {"answer_correctness": 0.70}),
            _result("B", {"answer_correctness": 0.76}),
        ).as_markdown()
        assert "answer_correctness 0.08" in md
        assert "measure_noise_floor.py" in md


class TestAWinnerNeedsMoreThanOneRow:
    """The gap the measured noise floors left open, closed 2026-10-21.

    A floor answers "is this delta bigger than rerunning the same pipeline".
    It cannot answer "is this delta bigger than one sample", and on
    `baseline-17` vs `router-scope` the two answers differed: a
    `context_precision` move of +0.0134 cleared the 0.01 floor honestly while
    resting entirely on `fq-013`. `compare` now also runs an exact paired
    signed-rank test over the per-sample scores, and a winner needs both.
    """

    @staticmethod
    def _one_row_moved(metric: str, base: float, moved: float) -> ComparisonResult:
        """Fifteen rows, fourteen identical, one different — the real shape."""
        a = _scored("A", {f"s{i}": {metric: base} for i in range(15)})
        b = _scored(
            "B",
            {
                f"s{i}": {metric: moved if i == 13 else base}
                for i in range(15)
            },
        )
        return compare(a, b)

    def test_a_delta_over_the_floor_carried_by_one_row_is_not_a_win(self) -> None:
        result = self._one_row_moved("context_precision", 0.45, 0.65)
        delta = result.deltas[0]

        # The delta is real and clears the 0.01 floor — this is not a case of
        # the floor being raised until the problem went away.
        assert delta.delta == pytest.approx(0.0133, abs=1e-4)
        assert abs(delta.delta) >= noise_floor("context_precision")
        assert delta.winner == "tie"
        assert not delta.is_significant
        assert result.overall_winner == "tie"

    def test_it_says_the_delta_cleared_the_floor_and_still_failed(self) -> None:
        result = self._one_row_moved("context_precision", 0.45, 0.65)
        assert result.notes == [] or all(
            "context_precision" not in n for n in result.notes
        )
        note = " ".join(result.power_notes)
        assert "clearing its 0.01 rerun floor" in note
        assert "only 1 of 15 paired rows differ" in note

    def test_the_same_delta_spread_over_every_row_is_a_win(self) -> None:
        # Same metric, same floor, a delta of the same order — but carried by
        # all fifteen rows instead of one. This is what the test is for: it
        # distinguishes the two, and the floor alone cannot.
        a = _scored("A", {f"s{i}": {"context_precision": 0.45} for i in range(15)})
        b = _scored("B", {f"s{i}": {"context_precision": 0.47} for i in range(15)})
        result = compare(a, b)

        assert result.deltas[0].winner == "B"
        assert result.deltas[0].is_significant
        assert result.overall_winner == "B"

    def test_an_underpowered_row_is_not_reported_as_a_measured_null(self) -> None:
        md = self._one_row_moved("context_precision", 0.45, 0.65).as_markdown()
        # "underpowered" and "p=0.9" both end in a tie and mean opposite
        # things. The table has to say which one happened.
        assert "**underpowered** (1/15 differ)" in md
        assert "Too few rows:" in md

    def test_identical_rows_are_not_called_underpowered(self) -> None:
        a = _scored("A", {f"s{i}": {"faithfulness": 1.0} for i in range(15)})
        result = compare(a, _scored("B", {f"s{i}": {"faithfulness": 1.0} for i in range(15)}))

        assert result.deltas[0].test is not None
        assert result.deltas[0].test.verdict == "identical"
        assert "— (all 15 rows equal)" in result.as_markdown()
        # Nothing to warn about: the runs agreed, which is a measurement.
        assert result.power_notes == []

    def test_a_tiny_delta_consistent_across_every_row_still_needs_the_floor(self) -> None:
        # The test alone would reject this: fifteen rows all moving the same
        # way is p=0.0001. It is 0.002 of answer_relevance, which is inside
        # what a rerun does. Both gates, in the other direction.
        a = _scored("A", {f"s{i}": {"answer_relevance": 0.800} for i in range(15)})
        b = _scored("B", {f"s{i}": {"answer_relevance": 0.802} for i in range(15)})
        result = compare(a, b)

        assert result.deltas[0].test is not None
        assert result.deltas[0].test.is_significant
        assert abs(result.deltas[0].delta) < noise_floor("answer_relevance")
        assert result.deltas[0].winner == "tie"

    def test_the_footnote_names_both_gates(self) -> None:
        md = self._one_row_moved("context_precision", 0.45, 0.65).as_markdown()
        assert "Wilcoxon" in md
        assert "measure_noise_floor.py" in md
        assert "absence of evidence, not evidence of absence" in md


class TestAnUntestableMetricSaysSo:
    """A delta the paired test could not reach must not render like one it passed."""

    @staticmethod
    def _unscorable(name: str, aggregate: float) -> EvalResult:
        """A run that stored an aggregate but no usable per-sample score.

        `applicable=False` on every row: the metric declined each sample, so
        the mean has no rows under it to pair. Reports from before the
        three-state vocabulary can look like this.
        """
        return EvalResult(
            pipeline_config=PipelineConfig(name=name),
            sample_results=[
                SampleResult(
                    sample_id=f"s{i}", question="q", generated_answer="a",
                    retrieved_chunk_ids=["c1"],
                    metrics=[
                        MetricScore(
                            metric_name="faithfulness", score=aggregate, applicable=False
                        )
                    ],
                )
                for i in range(15)
            ],
            aggregate_scores={"faithfulness": aggregate},
        )

    def test_it_falls_back_to_the_floor_and_names_the_fallback(self) -> None:
        result = compare(self._unscorable("A", 0.60), self._unscorable("B", 0.90))

        assert result.deltas[0].test is None
        # The floor alone still decides, because refusing every verdict on an
        # old report would make the comparator useless against the baselines
        # already on disk. What it must not do is stay quiet about it.
        assert result.deltas[0].winner == "B"
        assert any("could not be tested pairwise" in n for n in result.notes)

    def test_the_table_marks_the_test_as_not_run(self) -> None:
        md = compare(self._unscorable("A", 0.60), self._unscorable("B", 0.90)).as_markdown()
        assert "**not run** (no paired rows)" in md
