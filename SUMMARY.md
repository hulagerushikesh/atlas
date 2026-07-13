# Atlas — Project Summary

A production-grade agentic RAG (Retrieval-Augmented Generation) platform. You give it a folder of company documents, it indexes them, and answers questions in plain English with source citations — checking its own answers for accuracy before responding.

**Stack:** Python 3.11 · FastAPI · Qdrant · OpenAI · Redis · Docker  
**Repo:** https://github.com/hulagerushikesh/atlas  
**Stats:** 68 source files · 213 tests passing · 87% coverage

---

## What Was Built

### Module A — Ingestion & Indexing
Reads PDF, Markdown, HTML, and plain text files. Splits them into chunks, converts each chunk into a vector embedding via OpenAI, and stores them in two indexes:
- **Qdrant** (vector DB) for semantic/meaning-based search
- **BM25** (in-memory) for exact keyword search

Content is fingerprinted with xxhash — unchanged documents are skipped on re-run (idempotent). Three chunking strategies: fixed-size, recursive (splits at headings → paragraphs → sentences), and semantic (embedding-based boundary detection).

### Module B — Hybrid Retrieval
Searches both indexes simultaneously and merges results using **Reciprocal Rank Fusion (RRF)** — a rank-based formula that works even though BM25 scores and cosine similarity scores are on completely different scales.

After fusion, a **cross-encoder reranker** (sentence-transformers MiniLM) re-scores the top 20 candidates and keeps the best 5. Two-stage pipeline: fast ANN search narrows the field, slow cross-encoder picks the winner.

### Module C — Agentic Orchestration
A chain of LLM-driven agents that handle a query end-to-end:

1. **QueryRouter** — classifies as `simple`, `complex`, or `out_of_scope` (one LLM call, temp=0)
2. **QueryDecomposer** — breaks complex questions into up to 4 sub-questions, each retrieved independently
3. **RetrievalGrader** — scores whether retrieved chunks contain enough info; reformulates and retries up to 2× if not
4. **AnswerGenerator** — writes the answer with inline citations `[1]`, `[2]` linked to source documents
5. **FaithfulnessChecker** — decomposes the answer into individual claims and verifies each against the retrieved chunks

Faithfulness failures flag the response but don't suppress it — the caller decides what to do.

### Module D — Evaluation Harness
Measures how good the pipeline actually is. Runs 30 pre-written Q&A pairs through the live pipeline and scores on four metrics:

| Metric | How |
|---|---|
| Context Precision | hits / total retrieved (programmatic) |
| Context Recall | recalled docs / relevant docs (programmatic) |
| Faithfulness | LLM decomposes claims → verifies each against chunks |
| Answer Relevance | generate 3 synthetic questions from answer → cosine sim to original |

Saves JSON + Markdown reports. Has an A/B comparator with a 0.02 significance threshold.

The 30-sample dataset covers HR, IT, Finance, Product, Legal, Security, cross-functional (multi-hop), and one out-of-scope question.

### Module E — API & Observability
FastAPI application exposing the full pipeline over HTTP:

- `POST /query` — run the RAG pipeline; supports streaming (SSE)
- `POST /ingest` — index a file or directory
- `GET /health` — probes Qdrant + Redis; returns 200 or 503
- `GET /metrics` — Prometheus metrics (requests, latency, tokens, cost, cache hits)

**Two-level cache:** in-memory LRU (256 entries) + Redis (1h TTL). Repeated queries answered in <1ms without touching OpenAI.

**Per-request tracing:** every request gets a UUID bound to structlog's context — appears in every log line from that request across all pipeline stages.

**Prometheus middleware** wraps the entire stack outermost, recording true end-to-end latency.

---

## Infrastructure

```bash
docker-compose up qdrant redis -d
```

- **Qdrant v1.9.4** — vector store
- **Redis 7.2** — query cache
- **atlas_api** — the FastAPI server (also runs locally without Docker)

---

## CLI Scripts

| Script | Purpose |
|---|---|
| `scripts/check_health.py` | Verify OpenAI key, Qdrant, Redis are all reachable |
| `scripts/ingest.py <path>` | Index a file or directory from the terminal |
| `scripts/run_eval.py` | Run the 30-sample eval, print metric scores, save reports |
| `scripts/seed_demo.py` | Write 4 synthetic docs, index them, run 5 live demo queries |

---

## How to Run

```bash
# 1. Add your OpenAI key
cp .env.example .env   # then set OPENAI_API_KEY=sk-...

# 2. Start infra
docker-compose up qdrant redis -d

# 3. Install
uv pip install -e ".[dev]"

# 4. Check everything is connected
python scripts/check_health.py

# 5. Run end-to-end demo
python scripts/seed_demo.py

# 6. Start the API
uvicorn atlas.api.asgi:app --reload --port 8010
# Swagger UI → http://localhost:8010/docs
```

---

## What Works

- All 213 tests pass
- API starts, all 4 endpoints respond correctly
- `/health` confirms Qdrant + Redis connected
- `/query` validates input, returns proper errors
- `/metrics` returns live Prometheus data
- Swagger UI at `/docs` with full schema documentation
- Per-request tracing headers on every response
- Config resolves `.env` by absolute path (works from any directory)
- Tests don't require `OPENAI_API_KEY` at import time (fixed via `asgi.py`)

## What's Still Missing

- **No `.env` file** — must be created before live queries work
- **Token usage shows 0** in API responses — not wired through PipelineResult yet
- **No eval report with real numbers** — `run_eval.py` is ready but hasn't run against a real index
- **No authentication** — API is open, needs API key middleware before sharing the URL
- **Integration tests folder is empty** — `tests/integration/` exists but has no tests
- **No web UI** — interaction is via curl, Swagger, or CLI scripts only
- **BM25 full rebuild on each new doc** — fine for small indexes, slow at scale

---

## Key Files

```
src/atlas/
├── interfaces/        # shared ABCs + Pydantic models (no logic)
├── config.py          # pydantic-settings, all env vars
├── ingestion/         # Module A — loaders, chunkers, embedder, dense/sparse index
├── retrieval/         # Module B — dense, sparse, RRF fusion, reranker, hybrid
├── orchestration/     # Module C — router, decomposer, grader, generator, faithfulness, pipeline
├── evaluation/        # Module D — metrics, runner, reporter, comparator
└── api/               # Module E — app, routes, middleware, cache, schemas
tests/unit/            # 213 tests, all mocked, no network I/O
scripts/               # check_health, ingest, run_eval, seed_demo
eval_data/             # sample_dataset.json (30 samples)
docs/                  # one .md per module explaining design decisions
docker-compose.yml
Dockerfile
.env.example
```
