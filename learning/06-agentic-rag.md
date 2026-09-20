# 06 — Agentic RAG

Naive RAG: embed query → top-k → stuff into prompt → answer. It fails
silently: wrong routing, questions that need three lookups, empty retrievals
that still get answered confidently. "Agentic" means the pipeline *decides*
things and can *loop*.

## Atlas's pipeline (`orchestration/pipeline.py`)

```
route ──► decompose? ──► retrieve ──► grade ──┐
                              ▲               │ insufficient (< 0.5, ≤ 2 retries)
                              └── reformulate ◄┘
                                              │ sufficient
                                              ▼
                                         generate ──► check faithfulness ──► result
```

Each stage is a class with one LLM call and one job. `PipelineResult` carries
the answer, citations, `evidence` (every chunk with per-stage scores and
whether it was selected), `stage_ms`, tokens and cost.

### QueryRouter (`router.py`)
Classifies `simple | complex | out_of_scope` at temperature 0.
`out_of_scope` → refuse without retrieving (saves cost, avoids hallucinating
an answer to "what's the weather"). This is the cheapest and highest-leverage
call in the system.

### QueryDecomposer (`decomposer.py`)
`complex` → up to 4 sub-questions, each retrieved independently, results
merged. "Compare `Depends` and middleware for auth" becomes two retrievals
that each find the right chunks, where one retrieval finds neither.

### RetrievalGrader (`grader.py`)
Scores 0–1 whether the retrieved context can answer the question. Below
`_THRESHOLD = 0.5` → reformulates the query and retries (max 2). This is the
**Corrective RAG** idea: detect a bad retrieval *before* generating.
`stage_ms["retrieval"]` and `["grading"]` accumulate across retries so the
console shows the true cost of a hard question.

### AnswerGenerator (`generator.py`)
Writes the answer with inline `[n]` citations bound to specific chunks. The
prompt forbids using knowledge outside the context — the faithfulness check
enforces it.

### FaithfulnessChecker (`faithfulness.py`)
Splits the answer into claims; checks each against the evidence; returns a
score and `unsupported_claims`. Failures *flag* the answer rather than
suppress it — the caller (and the console's strength badge) decides. Module
07 goes deeper.

### OpenAILLMProvider (`llm.py`)
Primary `gpt-4o-mini`, fallback `gpt-3.5-turbo` by default (live: Gemini
`gemini-3.1-flash-lite` / `gemini-3.5-flash-lite` via `OPENAI_BASE_URL`), retry with backoff on
rate-limit/quota (`retry_policy.py`). Every call reports tokens for
`api/cost.py`.

## The design decisions, and the alternatives

**Fixed pipeline vs free agent.** Atlas is a *fixed* DAG with bounded loops.
A ReAct-style agent (LLM picks the next tool each step) is more flexible and
far less predictable in latency, cost and failure. For a product with a
p95 budget, the fixed pipeline wins; the router gives you most of the
adaptivity.

**Where to spend LLM calls.** Atlas makes 3–5 calls per query (route, grade,
generate, check, + decompose). Each adds latency (`docs/orchestration.md`
has the profile). The research question is always: which calls pay for
themselves? Adaptive-RAG's answer: route by *difficulty* and skip stages for
easy questions — Atlas's router already does the crude version.

**Retry vs give up.** Two grader retries is a budget, not a guarantee. After
that Atlas generates anyway with a low `grader_score`; the console renders
UNCHECKED/WEAK. Refusing outright is the other valid choice.

## Research lineage

- **ReAct** (2022): interleave reasoning and tool calls. The general agent
  loop; Atlas deliberately constrains it.
- **Self-RAG** (2023): fine-tune the model to emit *reflection tokens* —
  "should I retrieve?", "is this passage relevant?", "is my answer
  supported?". Atlas does the same with separate prompted calls instead of
  fine-tuning.
- **CRAG** (2024): grade retrievals, and on failure fall back to web search
  or refine. Atlas's grader-retry loop is CRAG without the web fallback.
- **FLARE** (2023): retrieve *during* generation whenever the model's next
  sentence has low confidence. Multi-hop by construction.
- **Adaptive-RAG** (2024): a small classifier routes to no-retrieval /
  single-step / multi-step. Atlas's router is this, prompted rather than
  trained.
- **HyDE** (2022): have the LLM write a hypothetical answer, embed *that*,
  retrieve with it. Cheap, often a large gain for dense retrieval on
  question-shaped queries. One-file addition to Atlas's retrieval step.
- **Chain-of-Verification** (2023): draft → generate verification questions
  → answer them independently → revise. Atlas's faithfulness check is the
  "verify" half.

## Read (in order)

1. Lewis et al., *Retrieval-Augmented Generation for Knowledge-Intensive NLP*
   (2020), arXiv:2005.11401 — where the term comes from.
2. Yao et al., *ReAct* (2022), arXiv:2210.03629.
3. Asai et al., *Self-RAG* (2023), arXiv:2310.11511 — read §3 and figure 1.
4. Yan et al., *Corrective RAG* (2024), arXiv:2401.15884.
5. Jeong et al., *Adaptive-RAG* (2024), arXiv:2403.14403.
6. Gao et al., *HyDE — Precise Zero-Shot Dense Retrieval without Relevance
   Labels* (2022), arXiv:2212.10496.
7. Jiang et al., *FLARE — Active Retrieval Augmented Generation* (2023),
   arXiv:2305.06983.
8. Dhuliawala et al., *Chain-of-Verification* (2023), arXiv:2309.11495.

## Exercise

[exercises.md → 06](exercises.md#06-agentic-rag)
