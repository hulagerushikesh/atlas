# Module C — Agentic Orchestration

End-to-end pipeline that routes, decomposes, retrieves, grades, generates, and
fact-checks a single user query using a chain of LLM-driven agents.

---

## Why "agentic"?

A naive RAG pipeline is: embed query → retrieve chunks → stuff into prompt → call LLM.
That breaks on three common failure modes:

1. **Out-of-scope queries** — the LLM hallucinates an answer from training data instead
   of saying "I don't know."
2. **Complex multi-hop questions** — a single retrieval pass misses the second and third
   facts the question needs.
3. **Weak retrieval** — the top-k chunks don't contain the answer; a static pipeline
   generates a hallucination anyway.

Module C addresses all three with an agentic decision tree: each step either delegates
to the next or takes a corrective action (retry with a reformulated query, flag as
out-of-scope, mark as unfaithful).

---

## Pipeline Decision Tree

```
query
  │
  ▼
QueryRouter ──→ "out_of_scope" ──→ return fixed refusal message
  │
  ├──→ "simple"  ──→ retrieve once
  │
  └──→ "complex" ──→ QueryDecomposer
                          │
                          └──→ retrieve per sub-query (concurrent)
                                      │
                                      ▼
                          merge + deduplicate by chunk_id
                                      │
                                      ▼
                           RetrievalGrader
                              │            └──→ score < threshold → reformulate
                              │                  │
                              │                  └── retry (≤ MAX_RETRIES=2)
                              │
                              ▼ (sufficient context)
                          AnswerGenerator
                              │
                              ▼
                          FaithfulnessChecker
                              │
                              └──→ is_faithful=False → warning logged (not rejected)
```

---

## Components

### QueryRouter ([`router.py`](../src/atlas/orchestration/router.py))

Classifies a query into one of three categories using a single zero-temperature LLM
call (max 128 tokens — cheap and fast):

| Classification | Meaning | Action |
|---|---|---|
| `simple` | Single-fact question answerable from one retrieval | Retrieve once |
| `complex` | Multi-hop, comparative, or requires synthesis across documents | Decompose → retrieve per sub-query |
| `out_of_scope` | Question unrelated to the knowledge base | Return fixed refusal; skip LLM generation |

The system prompt includes few-shot examples for each category. The LLM returns JSON
with a `"classification"` key; missing or malformed JSON defaults to `"simple"` (safe
fallback — we'd rather over-retrieve than refuse a valid question).

**Why temperature=0?** Routing is a classification task, not a generation task. We want
deterministic output, not creative variation.

---

### QueryDecomposer ([`decomposer.py`](../src/atlas/orchestration/decomposer.py))

Breaks a complex query into at most **4 independent sub-questions**, each retrievable
on its own. Returns a `list[str]`.

**Fallback**: if the LLM returns fewer than 2 sub-questions, the original query is used
as-is. This handles the case where the router over-classifies a simple question as
complex — the decomposer effectively no-ops.

Sub-queries are retrieved concurrently via `asyncio.gather()`. Results are merged and
deduplicated by `chunk_id` before grading, so the same chunk surfaced by two sub-queries
appears only once in the context window.

---

### RetrievalGrader ([`grader.py`](../src/atlas/orchestration/grader.py))

Assesses whether the top-5 retrieved chunks contain sufficient information to answer
the original question. Returns `(sufficient: bool, score: float, reformulated_query: str)`.

- **Score**: LLM-assigned float in `[0, 1]`. Threshold `≥ 0.5` = sufficient.
- **Reformulated query**: the grader's best guess at a better query if context is
  insufficient (e.g. adding synonyms, removing ambiguity).
- **Empty chunks**: immediate `(False, 0.0, original_query)` without an LLM call.

The retry loop in `RAGPipeline._retrieve_with_retry()` calls the grader after each
retrieval attempt and retries up to `MAX_RETRIES=2` times with the reformulated query.
After 2 retries the best available chunks are passed to the generator regardless.

**Why cap at 2 retries?** Each retry adds one LLM call and one retrieval pass (~500ms
each). Three retrieval attempts (initial + 2 retries) cover the vast majority of
reformulation benefit; additional attempts have diminishing returns and measurable latency
cost.

---

### AnswerGenerator ([`generator.py`](../src/atlas/orchestration/generator.py))

Generates an answer grounded in the retrieved chunks with **inline citation markers**
(`[1]`, `[2]`, …). Returns a `GeneratorResult` with `.answer` (full text) and
`.citations` (dict mapping citation number → `CitationRef`).

```python
@dataclass
class CitationRef:
    chunk_id: str
    source: str       # filename or URL
    page_number: int | None
```

**Citation extraction**: `re.compile(r"\[(\d+)\]")` scans the answer; only numbers
referenced in the text appear in the citations dict (unreferenced chunks are dropped).
Citation numbers are 1-indexed and match the order chunks were presented to the LLM.

**Streaming variant**: `AnswerGenerator.stream(query, chunks)` is an `AsyncIterator[str]`
that yields delta tokens. Used by the `/query?stream=true` path. The streaming path
bypasses the faithfulness check (see Module E docs for rationale).

---

### FaithfulnessChecker ([`faithfulness.py`](../src/atlas/orchestration/faithfulness.py))

Checks whether the generated answer is **grounded in the retrieved chunks** using a
claim-decompose-then-verify pattern:

1. **Decompose**: ask the LLM to list all factual claims in the answer as a JSON array.
2. **Verify**: for each claim, ask the LLM whether it is supported by the chunks.
3. **Score**: `supported_claims / total_claims` (float in `[0, 1]`).

Returns `FaithfulnessResult(score, is_faithful, summary, unsupported_claims)`.
`is_faithful = score >= 0.5`.

**Fast path**: if `enabled=False` (configurable), returns `is_faithful=True` instantly
without any LLM calls. Useful for development or when latency is more important than
faithfulness guarantees.

**Non-blocking flag**: a faithfulness failure does **not** suppress the answer. The
result carries `is_faithful=False` and the API response includes the flag. This is
intentional — callers decide what to do with unfaithful answers (display a warning,
log for review, trigger human-in-the-loop). Silently suppressing answers would degrade
user experience for borderline cases.

---

### OpenAILLMProvider ([`llm.py`](../src/atlas/orchestration/llm.py))

Concrete LLM backend implementing `BaseLLMProvider`. Key behaviours:

**Retry on rate limits**: `@retry` decorator (tenacity) with exponential backoff,
triggered on `openai.RateLimitError`. Retries up to 3 times before raising.

**Primary → fallback model**: if the primary model (e.g. `gpt-4o`) raises an error,
the provider falls back to `settings.openai.fallback_model` (e.g. `gpt-4o-mini`)
automatically. This prevents a single model outage from taking down the entire pipeline.

**JSON mode**: `json_mode=True` sets `response_format={"type": "json_object"}` and
appends a JSON instruction to the system prompt. The static method `parse_json_response()`
strips markdown code fences (` ```json `) that some models add before the `json.loads()` call.

**Streaming**: `stream()` opens an OpenAI streaming completion and yields string deltas
via `async for chunk in response`. The caller (AnswerGenerator) is responsible for
assembling the full answer and parsing citations if needed after streaming completes.

---

### PipelineResult ([`pipeline.py`](../src/atlas/orchestration/pipeline.py))

Dataclass carrying **full provenance** from one pipeline run:

```python
@dataclass
class PipelineResult:
    query: str
    classification: str           # "simple" | "complex" | "out_of_scope"
    sub_queries: list[str]        # [query] for simple; decomposed for complex
    retrieved_chunks: list[RetrievedChunk]
    grader_score: float           # 0.0–1.0
    grader_retries: int           # 0–MAX_RETRIES
    generation: GeneratorResult | None
    faithfulness: FaithfulnessResult | None
    # Computed on __post_init__:
    answer: str
    is_faithful: bool
```

Module D's eval harness reads `retrieved_chunks`, `generation`, and `faithfulness` to
compute all four metrics without re-running the pipeline.

---

## Latency Profile

Typical wall-clock times on a simple query (gpt-4o-mini, Qdrant local):

| Stage | Time |
|---|---|
| Router classify | ~200ms |
| Dense + BM25 retrieve + rerank | ~150ms |
| Grader (first pass) | ~300ms |
| Generator | ~600ms |
| Faithfulness check | ~400ms |
| **Total** | **~1.6s** |

For complex queries with decomposition and one grader retry, expect 2.5–4s.
Streaming removes the faithfulness check and returns first tokens within ~300ms.

---

## Configuration

All orchestration settings flow from `atlas.config.Settings`:

```env
OPENAI__API_KEY=sk-...
OPENAI__MODEL=gpt-4o-mini
OPENAI__FALLBACK_MODEL=gpt-3.5-turbo
OPENAI__EMBEDDING_MODEL=text-embedding-3-small
RETRIEVAL__TOP_K=20
RETRIEVAL__RRF_K=60
RERANKER__TOP_K=5
```

Faithfulness checking is always enabled in the current config. Add
`ORCHESTRATION__FAITHFULNESS_ENABLED=false` to the settings model to expose a
dev-time fast path if needed.

---

## Testing

Tests in [`tests/unit/orchestration/`](../tests/unit/orchestration/) mock the
`BaseLLMProvider` interface. Each component is tested in isolation:

```python
mock_llm = AsyncMock(spec=BaseLLMProvider)
mock_llm.generate.return_value = GenerationResponse(
    content='{"classification": "simple"}',
    model="gpt-4o-mini",
    usage={"prompt_tokens": 50, "completion_tokens": 10},
)
router = QueryRouter(mock_llm)
result = await router.classify("What is the expense limit?")
assert result == "simple"
```

`RAGPipeline` tests mock both the retriever and LLM provider, exercising the full
decision tree including the retry loop and out-of-scope path.
