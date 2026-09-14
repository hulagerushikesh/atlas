# 07 — Faithfulness & Evaluation

A RAG system without an eval harness is a demo. This module is how you know
whether a change helped.

## Hallucination in RAG, precisely

The model is given evidence and still says something the evidence does not
support. Three flavours:

1. **Extrinsic** — a claim from the model's parametric memory, not the
   context. Usually plausible, sometimes wrong, never citable.
2. **Intrinsic** — the model misreads the context (swaps a number, negates a
   condition).
3. **Unsupported synthesis** — each half is in the context but the
   conclusion joining them is not.

Retrieval quality causes most of it: if the answer is not in the context, the
model fills in. Hence "grade before generate" (module 06).

## Claim-level checking (`orchestration/faithfulness.py`)

Whole-answer "is this faithful, yes/no?" is unreliable — a judge model
anchors on fluency. Atlas does what FActScore does: decompose the answer into
atomic claims, verify each against the evidence independently, score =
supported / total. `unsupported_claims` are returned so the console can mark
exactly which spans are unsourced (dashed underline) and which are cited.

Strength badge thresholds in the console (`console/src/lib/store.ts:
strengthFrom`): SUPPORTED / PARTIAL / WEAK / UNCHECKED. A failure *flags*, it
does not suppress — the honest answer with a warning beats a refusal for most
products.

## The four metrics (`evaluation/metrics/`)

```
               Retrieval            Generation
Precision      context_precision    faithfulness
Recall         context_recall       answer_relevance
```

- **context_precision** — of the chunks retrieved, what fraction came from
  documents labelled relevant. Programmatic; needs `relevant_doc_ids`.
- **context_recall** — of the documents labelled relevant, what fraction
  showed up. Programmatic.
- **faithfulness** — LLM-as-judge, claim-level (above).
- **answer_relevance** — RAGAS-style: generate 3 questions the answer would
  answer, embed them, mean cosine to the original question. Catches answers
  that are true but off-topic.

Two are free, two cost LLM calls. Run the free ones on every change; the
judged ones on candidates.

## Building a dataset (`eval_data/`)

`fastapi_dataset.json`: `{name, description, samples[]}` with
`question`, `ground_truth_answer`, `relevant_doc_ids`, `metadata`. Good
datasets have: a range of difficulty, questions phrased unlike the source
text, some multi-hop, some *unanswerable* (to test refusal), and labels you
would defend in a code review. 30 samples is enough to see a 10-point
change; it is not enough to see a 2-point change — know your noise floor by
running the same config twice.

Synthetic generation (LLM writes Q/A pairs from chunks) is fast and biased
toward the chunking you already have. Use it to bootstrap, then hand-edit.

## Running it (`evaluation/runner.py`, `reporter.py`, `comparator.py`)

`make eval` → JSON + markdown report per run. `make eval-compare
BASELINE=path` diffs two reports, metric by metric, sample by sample. Every
retrieval experiment in this learning path ends with that command.

## Judge reliability

LLM judges are biased: toward longer answers, toward their own style,
toward position (first candidate wins). Mitigations: temperature 0, claim
decomposition, a rubric in the prompt, occasionally re-judge with a second
model, and a human-labelled subset to calibrate. Never trust a judge you
have not spot-checked against 20 hand-labelled cases.

## Latency and cost are metrics too

`stage_ms` per stage and `$` per query are in every `QueryResponse`. An eval
that improves faithfulness by 3 points and doubles p95 is a trade-off, not a
win. `docs/orchestration.md` has the latency profile.

## Read

1. Es et al., *RAGAS* (2023), arXiv:2309.15217 — the metric definitions
   Atlas adapts.
2. Min et al., *FActScore* (2023), arXiv:2305.14251 — atomic-claim
   verification.
3. Liu et al., *Lost in the Middle* (2023), arXiv:2307.03172 — LLMs ignore
   evidence placed mid-context; order your chunks.
4. Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*
   (2023), arXiv:2306.05685 — judge biases, measured.
5. Thakur et al., *BEIR* (2021), arXiv:2104.08663 — retrieval-only
   evaluation, nDCG@10 and why.

## Exercise

[exercises.md → 07](exercises.md#07-faithfulness--evaluation)
