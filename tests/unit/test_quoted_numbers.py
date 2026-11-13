"""Every headline number quoted in prose is checked against one eval report.

README, landing page, pitch and tour sit outside the code and drift in the
project's favour. A new measurement means changing SOURCE, then fixing
whatever this test names.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from atlas.cost import USD_TO_INR, estimate_usage_cost
from atlas.evaluation.reporter import percentile
from atlas.interfaces.evaluator import EvalResult

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "eval_data/reports/duckdb-v1_20261103-213709.json"

NUM = r"(\d+(?:\.\d+)?)"
LANDING = "console/src/landing/Sections.tsx"
PITCH = "planning/PITCH.md"
SHEET = "learning/interview-sheet.md"
RESUME = "docs/resume-bullets.md"
CASE = "docs/case-study.md"


def _headline() -> dict[str, float]:
    result = EvalResult.model_validate_json(SOURCE.read_text())
    scores = result.aggregate_scores
    priced = [s for s in result.sample_results if s.token_usage]
    per_query = sum(estimate_usage_cost(s.token_usage) for s in priced) / len(priced)
    totals = [sum(s.stage_ms.values()) for s in result.sample_results if s.stage_ms]
    return {
        "precision": scores["context_precision"],
        "recall": scores["context_recall"],
        "faithfulness": scores["faithfulness"],
        "relevance": scores["answer_relevance"],
        "correctness": scores["answer_correctness"],
        "questions": len(result.sample_results),
        "run_rupees": estimate_usage_cost(result.token_usage) * USD_TO_INR,
        "query_rupees": per_query * USD_TO_INR,
        "median_s": percentile(totals, 50) / 1000,
        "p95_s": percentile(totals, 95) / 1000,
    }


def _fmt(value: float, style: str) -> str:
    if style == "pct":
        return f"{value * 100:.0f}"
    if style == "int":
        return f"{value:.0f}"
    return f"{value:.{int(style)}f}"


# (file, pattern with one number group, headline key, decimals | "pct" | "int")
QUOTES: list[tuple[str, str, str, str]] = [
    # README — first screen
    ("README.md", rf"Measured on {NUM} labelled questions", "questions", "int"),
    ("README.md", rf"^\| \*\*{NUM}\*\* \| \*\*[\d.]+\*\* \| \*\*₹", "correctness", "2"),
    ("README.md", rf"^\| \*\*[\d.]+\*\* \| \*\*{NUM}\*\* \| \*\*₹", "faithfulness", "2"),
    ("README.md", rf"\| \*\*₹{NUM}\*\* \|$", "query_rupees", "2"),
    # README — results
    ("README.md", rf"\| Context precision \| \*\*{NUM}\*\*", "precision", "4"),
    ("README.md", rf"\| Context recall \| \*\*{NUM}\*\*", "recall", "4"),
    ("README.md", rf"\| Faithfulness \| \*\*{NUM}\*\* \| 15", "faithfulness", "4"),
    ("README.md", rf"\| Answer relevance \| \*\*{NUM}\*\*", "relevance", "4"),
    ("README.md", rf"\| Answer correctness \| \*\*{NUM}\*\* \| graded", "correctness", "4"),
    ("README.md", rf"{NUM}-question set,\s+`eval_data/duckdb", "questions", "int"),
    ("README.md", rf"₹{NUM} for the run", "run_rupees", "2"),
    ("README.md", rf"₹{NUM} a query for the pipeline", "query_rupees", "2"),
    ("README.md", rf"{NUM} s median end-to-end", "median_s", "1"),
    ("README.md", rf"{NUM} s at p95", "p95_s", "1"),
    # Landing page
    (LANDING, rf'k: "Answer correctness", v: "{NUM}"', "correctness", "2"),
    (LANDING, rf'k: "Faithfulness", v: "{NUM}"', "faithfulness", "2"),
    (LANDING, rf'k: "Context recall", v: "{NUM}"', "recall", "2"),
    (LANDING, rf'k: "Context precision", v: "{NUM}"', "precision", "2"),
    (LANDING, rf"answer relevance sits\s+at {NUM}", "relevance", "2"),
    (LANDING, rf"run cost ₹{NUM}", "run_rupees", "2"),
    (LANDING, rf"— ₹{NUM} a query", "query_rupees", "2"),
    # Pitch
    (PITCH, rf"context recall {NUM}, groundedness", "recall", "2"),
    (PITCH, rf"groundedness {NUM}, answer relevance", "faithfulness", "2"),
    (PITCH, rf"answer relevance\s+{NUM}\. The other two", "relevance", "2"),
    (PITCH, rf"Context precision is\s+\**{NUM}", "precision", "2"),
    (PITCH, rf"it reads \*\*{NUM}\*\*", "correctness", "2"),
    (PITCH, rf"Groundedness at {NUM} and", "faithfulness", "2"),
    (PITCH, rf"correctness at {NUM} \*\*in the same", "correctness", "2"),
    (PITCH, rf"roughly {NUM}% of the substance", "correctness", "pct"),
    (PITCH, rf"about ₹{NUM} a question", "query_rupees", "2"),
    (PITCH, rf"accuracy number — {NUM} against", "correctness", "2"),
    (PITCH, rf"groundedness is[\s>]+{NUM}\. That gap", "faithfulness", "2"),
    (PITCH, rf"{NUM} faithfulness and [\d.]+ answer correctness", "faithfulness", "4"),
    (PITCH, rf"faithfulness and {NUM} answer correctness", "correctness", "4"),
    (PITCH, rf"\*\*{NUM} is a real number on", "correctness", "2"),
    (PITCH, rf"real number on {NUM} questions", "questions", "int"),
    (PITCH, rf"scores {NUM} on that", "faithfulness", "2"),
    # Tour and recording script
    ("docs/try-atlas.md", rf"\*\*Accuracy: {NUM}\*\*", "correctness", "2"),
    ("docs/try-atlas.md", rf"\*\*Groundedness: {NUM}\*\*", "faithfulness", "2"),
    ("docs/try-atlas.md", rf"on a {NUM}-question\s+set", "questions", "int"),
    ("docs/demo-script.md", rf"about ₹{NUM}", "query_rupees", "2"),
    # Interview sheet
    (SHEET, rf"{NUM} labelled questions\.", "questions", "int"),
    (SHEET, rf"{NUM} s median, ", "median_s", "1"),
    (SHEET, rf"median, {NUM} s at p95", "p95_s", "1"),
    (SHEET, rf"recall {NUM}, faithfulness", "recall", "2"),
    (SHEET, rf"faithfulness {NUM}, relevance", "faithfulness", "2"),
    (SHEET, rf"relevance {NUM}, precision", "relevance", "2"),
    (SHEET, rf"precision {NUM},\s+correctness", "precision", "2"),
    (SHEET, rf"\s+correctness {NUM}\.", "correctness", "2"),
    (SHEET, rf"\*\*Number:\*\* {NUM} against", "faithfulness", "2"),
    (SHEET, rf"against {NUM}, in the same run", "correctness", "2"),
    (SHEET, rf"context precision {NUM}\.", "precision", "2"),
    (SHEET, rf"₹{NUM} a question", "query_rupees", "2"),
    (SHEET, rf"₹{NUM} for a full evaluation run", "run_rupees", "2"),
    # Resume bullets
    (RESUME, rf"{NUM} groundedness", "faithfulness", "2"),
    (RESUME, rf"groundedness {NUM}", "faithfulness", "2"),
    (RESUME, rf"{NUM} (?:answer )?correctness", "correctness", "2"),
    (RESUME, rf"{NUM} labelled\s+questions", "questions", "int"),
    (RESUME, rf"recall {NUM}\)", "recall", "2"),
    (RESUME, rf"{NUM} s median", "median_s", "1"),
    (RESUME, rf"about ₹{NUM} \(~", "query_rupees", "2"),
    (RESUME, rf"live, ₹{NUM} a\s+question", "query_rupees", "2"),
    # Case study
    (CASE, rf"harness runs {NUM} labelled questions", "questions", "int"),
    (CASE, rf"On {NUM} labelled questions", "questions", "int"),
    (CASE, rf"\(recall {NUM}\)", "recall", "2"),
    (CASE, rf"faithfulness is {NUM}:", "faithfulness", "2"),
    (CASE, rf"hand-written references is\s+{NUM}\.", "correctness", "2"),
    (CASE, rf"Context precision is {NUM}\.", "precision", "2"),
    (CASE, rf"{NUM} s median end to end", "median_s", "1"),
    (CASE, rf"end to end, {NUM} s at p95", "p95_s", "1"),
    (CASE, rf"About ₹{NUM} a question", "query_rupees", "2"),
    (CASE, rf"evaluation run costs ₹{NUM}\.", "run_rupees", "2"),
]


@pytest.fixture(scope="module")
def headline() -> dict[str, float]:
    return _headline()


@pytest.mark.parametrize(
    ("path", "pattern", "key", "style"),
    QUOTES,
    ids=[f"{q[0].rsplit('/', 1)[-1]}:{q[2]}:{i}" for i, q in enumerate(QUOTES)],
)
def test_quoted_number_matches_the_report(
    headline: dict[str, float], path: str, pattern: str, key: str, style: str
) -> None:
    text = (ROOT / path).read_text()
    found = re.findall(pattern, text, flags=re.MULTILINE)
    assert found, f"{path}: the quote for {key} is gone or reworded — update QUOTES"
    expected = _fmt(headline[key], style)
    assert set(found) == {expected}, f"{path} says {found} for {key}; {SOURCE.name} says {expected}"


def test_a_changed_number_is_caught(headline: dict[str, float]) -> None:
    """The check must fail on drift, not merely pass on today's text."""
    readme = (ROOT / "README.md").read_text().replace("| **0.77** |", "| **0.80** |", 1)
    pattern = QUOTES[1][1]
    assert re.findall(pattern, readme, flags=re.MULTILINE) != [_fmt(headline["correctness"], "2")]
