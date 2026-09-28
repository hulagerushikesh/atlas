"""
Answer correctness: is the answer *right*, judged against the reference?

Why this exists:
    Until 2026-09-28 no metric read `ground_truth_answer`. Precision and
    recall scored the retrieved documents, faithfulness scored the answer
    against the chunks it was handed, and answer relevance scored the
    question against questions regenerated from the answer. All four can be
    perfect on an answer that is grounded, on-topic and wrong — and the
    README said so, because the alternative was a table that looked like it
    measured correctness and did not.

What it measures, exactly:
    The reference answer is decomposed into distinct facts, and each one is
    marked `present`, `missing` or `contradicted` in the generated answer.

        score = (present - contradicted) / total facts, clamped to [0, 1]

    A contradiction costs twice what an omission does: you lose the credit
    and pay a penalty. That ordering is the point — an answer that leaves a
    fact out is incomplete, an answer that states the opposite is wrong, and
    a metric that scored them alike would be no use for deciding whether a
    configuration is safe to ship.

What it deliberately does NOT measure:
    **Extra material in the answer that the reference does not mention is
    not penalised at all.** The usual formulation (RAGAS answer_correctness)
    counts it as a false positive and takes an F1 over the three counts.
    That is wrong for this corpus: these reference answers are hand-written
    summaries, and `fq-012`'s correct answer legitimately spans five pages
    where the reference names one. Penalising extra detail would measure
    "did it match the length of my summary", not correctness. A verbose
    answer padded with true-but-useless content is `answer_relevance`'s
    problem; one metric, one claim.

    It also does not check grounding. An answer can agree with the reference
    while citing nothing — faithfulness is the metric that objects.

The refusal path, which nothing else can score:
    A row with no `relevant_doc_ids` is a declared out-of-scope row (the
    dataset guard requires the flag to be explicit, so an empty label set
    here means someone meant it). The right answer there is the refusal
    sentence, and this is the only metric that can say whether the pipeline
    produced one: precision and recall skip the row, faithfulness marks a
    refusal inapplicable, and answer relevance scores a refusal against the
    question and returns noise. Scored here without an LLM call, in both
    directions — refusing is 1.0, answering anyway is 0.0.

Cost: one judge call per applicable sample, and the prompt carries two
answers rather than an answer plus fifteen chunks, so it is the cheapest of
the three judged metrics. About +15% on a run.
"""

from __future__ import annotations

import structlog

from atlas.evaluation.metrics.base import BaseMetric
from atlas.interfaces.evaluator import MetricScore
from atlas.interfaces.llm import BaseLLMProvider, GenerationRequest, Message
from atlas.interfaces.retriever import RetrievedChunk
from atlas.orchestration.generator import is_refusal
from atlas.orchestration.llm import parse_json_response

logger = structlog.get_logger(__name__)

_JUDGE_PROMPT = """\
You are grading a generated answer against a reference answer written by a \
domain expert. The reference is the standard; the generated answer is what a \
system produced.

Steps:
1. List every distinct fact the REFERENCE answer asserts. Ignore phrasing, \
ordering, and any hedging — only the substance counts.
2. For each fact, judge it against the GENERATED answer:
   - "present": the generated answer states it, or states something \
equivalent in different words
   - "missing": the generated answer neither states nor denies it
   - "contradicted": the generated answer states something incompatible with it

Do NOT penalise the generated answer for containing additional correct \
information that the reference does not mention. Extra material is only a \
problem if it contradicts a reference fact.

Return valid JSON:
{
  "facts": [{"fact": "...", "verdict": "present|missing|contradicted"}]
}"""


class AnswerCorrectnessMetric(BaseMetric):
    """LLM-as-judge: how much of the reference answer the generated one gets right."""

    def __init__(self, llm: BaseLLMProvider) -> None:
        self._llm = llm

    @property
    def name(self) -> str:
        return "answer_correctness"

    async def score(
        self,
        question: str,
        ground_truth_answer: str,
        generated_answer: str,
        retrieved_chunks: list[RetrievedChunk],
        relevant_doc_ids: list[str],
    ) -> MetricScore:
        refused = is_refusal(generated_answer)

        if not relevant_doc_ids:
            # A declared out-of-scope row: the refusal *is* the correct
            # answer, and this is the only metric that can say so. No model
            # call — the verdict is a string comparison.
            return MetricScore(
                metric_name=self.name,
                score=1.0 if refused else 0.0,
                reasoning=(
                    "Out-of-scope row: the pipeline refused, which is correct."
                    if refused else
                    "Out-of-scope row: the pipeline answered instead of refusing."
                ),
            )

        if not ground_truth_answer.strip():
            # Nothing to grade against. Inapplicable rather than 0.0: the
            # dataset is incomplete here, and that is not the pipeline's
            # failure to absorb into the mean.
            return MetricScore(
                metric_name=self.name,
                score=0.0,
                reasoning="No reference answer on this sample; nothing to compare against.",
                applicable=False,
            )

        if refused:
            # A refusal covers none of the reference's facts, and that is a
            # real failure on an answerable row — unlike faithfulness, which
            # has nothing to audit and abstains. Scored without a judge
            # because the answer is a known constant sentence.
            return MetricScore(
                metric_name=self.name,
                score=0.0,
                reasoning="Pipeline refused a question the dataset says is answerable.",
            )

        request = GenerationRequest(
            messages=[
                Message(role="system", content=_JUDGE_PROMPT),
                Message(
                    role="user",
                    content=(
                        f"Question:\n{question}\n\n"
                        f"REFERENCE answer:\n{ground_truth_answer}\n\n"
                        f"GENERATED answer:\n{generated_answer}"
                    ),
                ),
            ],
            temperature=0.0,
            # Same lesson as the faithfulness judge: a long reference yields
            # ten or more facts, and a truncated JSON list fails the sample
            # rather than scoring it low.
            max_tokens=2048,
            json_mode=True,
        )
        response = await self._llm.generate(request)
        parsed = parse_json_response(response.content)

        facts = parsed.get("facts", [])
        if not facts:
            return MetricScore(
                metric_name=self.name,
                score=0.0,
                reasoning="Judge extracted no facts from the reference answer.",
                applicable=False,
            )

        present = sum(1 for f in facts if f.get("verdict") == "present")
        contradicted = sum(1 for f in facts if f.get("verdict") == "contradicted")
        score = max(0.0, min(1.0, (present - contradicted) / len(facts)))

        missed = [f["fact"] for f in facts if f.get("verdict") == "missing"]
        wrong = [f["fact"] for f in facts if f.get("verdict") == "contradicted"]
        reasoning = (
            f"{present}/{len(facts)} reference facts present, "
            f"{len(missed)} missing, {contradicted} contradicted."
            + (f" Contradicted: {wrong}" if wrong else "")
            + (f" Missing: {missed}" if missed else "")
        )
        logger.debug(
            "answer_correctness_metric",
            score=score,
            facts=len(facts),
            present=present,
            contradicted=contradicted,
        )
        return MetricScore(
            metric_name=self.name, score=round(score, 4), reasoning=reasoning
        )
