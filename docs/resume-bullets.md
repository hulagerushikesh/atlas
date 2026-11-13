# Resume bullets

Text to paste into the resume, which lives in another project. Numbers are
from the 2026-11-03 evaluation of the live DuckDB 2.0 corpus; the test suite
checks the headline ones. Last checked 2026-11-13. In LaTeX, write `\$`,
`\%` and `\textrupee{}` (or "Rs.") for the symbols.

## Project line

**Atlas — agentic RAG with measured trust** · Python, FastAPI, Qdrant, Gemini,
Cloud Run · live at atlas.hulage.in · github.com/hulagerushikesh/atlas

## Four bullets (recommended)

- Built and deployed an agentic RAG platform that cites the exact passage
  behind every sentence and grades its own answer; measured on 16 labelled
  questions at 0.99 groundedness and 0.77 answer correctness against
  hand-written references.
- Designed hybrid retrieval (dense vectors + BM25, Reciprocal Rank Fusion,
  cross-encoder rerank) with a bounded router → grader → retry graph; finds
  every labelled page (recall 1.00) at 7.4 s median latency.
- Built the evaluation harness first — five metrics, A/B comparison with
  significance and cost/latency budget gates; it reverted a plausible
  "bug fix" that cut recall from 0.94 to 0.88 and rejected HyDE for a 56%
  slow-case latency rise.
- Runs at ₹0 idle and about ₹0.20 (~$0.002) a question on scale-to-zero Cloud
  Run, with a daily spend cap enforced before every paid call and a CI gate
  with a 90% coverage floor.

## Swap-ins

- Added deterministic section headers to every indexed passage at ingest —
  precision +0.08 and recall up to 0.96 in a paired A/B run, for one
  re-ingest and no per-query cost.
- Found six defects in the first live run that 252 green unit tests had
  missed, each between two correct components, and added end-to-end checks
  for them.

## One line, for a crowded resume

Agentic RAG with per-sentence citations and a self-graded trust verdict;
0.99 groundedness, 0.77 correctness on 16 labelled questions; live, ₹0.20 a
question.

## Do not write

- "Users" or "customers" — it has none yet. Say "built and deployed".
- "No hallucinations" — say groundedness 0.99, and pair it with 0.77.
- An accuracy figure without "16 questions" when there is room for it.
