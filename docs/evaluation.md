# Module D — Evaluation Harness

## What it does

Runs the complete RAG pipeline over a labelled Q&A dataset, scores each answer
on four orthogonal metrics, saves a JSON + markdown report, and can diff two
pipeline configurations to produce an A/B comparison.

## Metrics

| Metric | Type | What it measures |
|---|---|---|
| `context_precision` | Programmatic | Fraction of retrieved chunks from relevant documents |
| `context_recall` | Programmatic | Fraction of relevant documents that were retrieved |
| `faithfulness` | LLM-as-judge | Fraction of answer claims grounded in context |
| `answer_relevance` | LLM + embeddings | Semantic similarity of answer to original question |

### Why these four?

They form a 2×2 grid covering retrieval and generation, each axis:

```
              Retrieval          Generation
Precision     context_precision  faithfulness
Recall        context_recall     answer_relevance
```

A pipeline can fail in any quadrant independently. Reporting all four makes
failure mode diagnosis unambiguous.

### Faithfulness (LLM-as-judge)
Claim-decompose-then-verify: the judge lists discrete factual claims, then
verifies each against the context. More reliable than whole-answer grading.
`score = supported_claims / total_claims`

### Answer Relevance (reverse-question technique, RAGAS-style)
Generate N=3 synthetic questions the answer would address. Embed them and
compute mean cosine similarity to the original question. A drifting answer
produces dissimilar synthetic questions.

## Dataset format

```json
{
  "name": "atlas_enterprise_kb_v1",
  "samples": [
    {
      "id": "hr-001",
      "question": "How many days of annual leave are employees entitled to?",
      "ground_truth_answer": "Full-time employees are entitled to 20 days...",
      "relevant_doc_ids": ["doc-hr-leave-policy"],
      "metadata": {"category": "hr", "difficulty": "easy"}
    }
  ]
}
```

`relevant_doc_ids` are document-level IDs matching `Chunk.metadata.doc_id`.
The runner matches retrieved chunks' doc IDs against this set for precision and recall.

## Sample dataset

`eval_data/sample_dataset.json` — 30 samples covering:
- 8 categories: hr, it, finance, product, legal, security, cross-functional, out_of_scope
- 3 difficulty levels: easy, medium, hard
- Multi-document samples (cross-functional) test retrieval fusion quality
- 1 out-of-scope sample tests router classification

## Usage

### Single run

```python
from atlas.evaluation import (
    ContextPrecisionMetric, ContextRecallMetric,
    FaithfulnessMetric, AnswerRelevanceMetric,
    EvalRunner, save_report, print_report,
)
from atlas.interfaces.evaluator import EvalDataset, PipelineConfig
import json

dataset = EvalDataset.model_validate(json.loads(Path("eval_data/sample_dataset.json").read_text()))

metrics = [
    ContextPrecisionMetric(),
    ContextRecallMetric(),
    FaithfulnessMetric(llm),
    AnswerRelevanceMetric(llm, embedder),
]
runner = EvalRunner(pipeline, metrics, concurrency=4)
config = PipelineConfig(name="baseline_recursive_top20")

result = await runner.run(dataset, config)
print_report(result)
save_report(result, Path("eval_data/reports"), "baseline")
```

### A/B comparison

```python
from atlas.evaluation import compare, save_comparison

result_a = ...  # EvalResult from baseline run
result_b = ...  # EvalResult from reranked run

comparison = compare(result_a, result_b)
print(comparison.as_markdown())
save_comparison(comparison, Path("eval_data/reports/ab_reranking.md"))
```

**Example output:**

| Metric | baseline | with-reranker | Delta | Winner |
| --- | --- | --- | --- | --- |
| context_precision | 0.6200 | 0.7800 | +0.1600 | B |
| context_recall | 0.8100 | 0.7900 | -0.0200 | tie *(ns)* |
| faithfulness | 0.7300 | 0.8100 | +0.0800 | B |
| answer_relevance | 0.7800 | 0.8200 | +0.0400 | B |

**Overall winner: B**

## Tests

```bash
pytest tests/unit/evaluation/ -v
```

Dataset integrity, all four metrics, runner fault-isolation, reporter output,
and comparator deltas — all hermetic, no API calls.
