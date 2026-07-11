# Module E — API & Observability

FastAPI application that exposes the Atlas RAG pipeline over HTTP with per-request
tracing, Prometheus metrics, a two-level query cache, and streaming responses.

---

## Why a separate API module?

Modules A–D are pure Python — no HTTP, no middleware, no serialisation. Module E is
the only layer that knows about HTTP verbs, status codes, and JSON shapes. Keeping
this separation means the orchestration pipeline can be tested without spinning up a
web server, and the API tests can mock the pipeline without constructing real Qdrant
or OpenAI clients.

---

## Architecture

```
Request
  └── PrometheusMiddleware        (outermost — records true end-to-end latency)
        └── TracingMiddleware     (binds request_id to structlog context)
              └── CORSMiddleware
                    └── Route handlers
                          ├── /query    (cache check → pipeline → cache write)
                          ├── /ingest   (path check → DocumentIndexer)
                          ├── /health   (probe Qdrant + Redis)
                          └── /metrics  (Prometheus text exposition)
```

Middleware registration in Starlette is **last-registered = outermost**. We register
`PrometheusMiddleware` last so it wraps everything and records true end-to-end latency,
including time spent in tracing and CORS middleware.

---

## Application Factory

`create_app(settings=None) -> FastAPI` in [`app.py`](../src/atlas/api/app.py)

The app is a **factory function**, not a module-level singleton. This matters for
testing: each test can call `create_app(settings=overridden_settings)` to get a fresh
app with a different config, without monkey-patching globals.

A module-level `app = create_app()` is provided at the bottom of `app.py` for uvicorn:

```bash
uvicorn atlas.api.app:app --reload
```

### Lifespan handler

All heavy I/O (Qdrant client, Redis connection, cross-encoder model load) happens in
the `_lifespan` async context manager, not at import time. This ensures:

1. `import atlas.api.app` is cheap — no network calls, no model weights loaded.
2. All components are shut down gracefully on SIGTERM.
3. Tests that don't need the full stack inject a mock `AppState` directly onto
   `app.state.atlas` without triggering the lifespan.

The lifespan stores everything in `app.state.atlas: AppState`:

```python
@dataclass
class AppState:
    pipeline: RAGPipeline
    indexer: DocumentIndexer
    cache: QueryCache
    embedding_model: str
```

FastAPI dependency functions (`get_pipeline`, `get_cache`, etc.) extract the relevant
field from `request.app.state.atlas`, so route handlers never import singletons.

---

## Endpoints

### `POST /query`

Full RAG pipeline for a user question. Two response modes, one endpoint path,
distinguished by `body.stream`.

**Request**

```json
{
  "query": "What is the vacation policy?",
  "stream": false,
  "top_k": 5
}
```

**Non-streaming response** (`stream: false`, default)

1. Hash the lower-cased query; check L1 (memory) then L2 (Redis) cache.
2. On cache miss: run `RAGPipeline.run(query)`.
3. Serialise `PipelineResult` → `QueryResponse`.
4. Emit Prometheus counters (`TOKEN_USAGE`, `COST_USD`).
5. Write result to cache as a background task (fire-and-forget; doesn't block response).

```json
{
  "query": "What is the vacation policy?",
  "answer": "Employees receive 15 days of PTO per year [1].",
  "classification": "simple",
  "citations": [
    {"number": 1, "chunk_id": "hr-policy-p3-c2", "source": "hr_policy.pdf", "page_number": 3}
  ],
  "is_faithful": true,
  "faithfulness_score": 0.92,
  "retrieved_chunk_ids": ["hr-policy-p3-c2", "hr-policy-p3-c5"],
  "timings": {"total_ms": 843.2},
  "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0},
  "cached": false
}
```

> **Known gap**: `token_usage` is populated with zeros in the current implementation.
> `PipelineResult` doesn't thread raw token counts from sub-calls (router, grader,
> generator, faithfulness). Threading token counts through `PipelineResult` is the
> next iteration — the schema and cost estimator are already in place.

**Streaming response** (`stream: true`)

Returns `text/event-stream` (Server-Sent Events). The faithfulness check is **skipped**
on the streaming path because it requires the full answer before running — buffering
defeats the purpose of streaming. A `X-Faithfulness: skipped-streaming` response header
signals this to clients.

```
data: {"delta": "Employees"}
data: {"delta": " receive"}
data: {"delta": " 15 days"}
...
data: [DONE]
```

Clients concatenate `delta` values to reconstruct the answer. The final `[DONE]` event
signals end-of-stream. Citation metadata is not yet sent in the final SSE event
(future iteration: add a `{"citations": [...]}` event before `[DONE]`).

**Error responses**

| Status | Condition |
|--------|-----------|
| 422 | `query` is empty or exceeds 4096 chars |
| 500 | Pipeline raised an unhandled exception (detail included) |

---

### `POST /ingest`

Index a file or directory into Qdrant + BM25.

**Request**

```json
{
  "path": "/data/hr_docs",
  "glob": "**/*.pdf"
}
```

**Response**

```json
{
  "documents_processed": 12,
  "documents_skipped": 3,
  "chunks_indexed": 147,
  "total_tokens": 42800,
  "duration_seconds": 18.3
}
```

`documents_skipped` counts files whose content hash matched the stored hash — no
re-embedding was performed. This is the idempotency guarantee from Module A.

**Error responses**

| Status | Condition |
|--------|-----------|
| 404 | `path` does not exist on the filesystem |
| 500 | Indexing failed (partial results possible) |

---

### `GET /health`

Probes Qdrant and Redis; returns 200 if all components are healthy, 503 if any
component is degraded or down.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "components": {
    "qdrant": {"status": "ok", "latency_ms": 2.1, "detail": ""},
    "redis":  {"status": "ok", "latency_ms": 0.4, "detail": ""}
  }
}
```

Status values: `"ok"` | `"degraded"` | `"down"`.

The health check is suitable for Kubernetes liveness and readiness probes. Use the
readiness probe (`/health` returning 200) to gate traffic, not the liveness probe —
Qdrant or Redis being temporarily unreachable should not restart the pod.

---

### `GET /metrics`

Prometheus text exposition format. Scraped by a Prometheus server or compatible
agent (Datadog, Victoria Metrics, etc.).

```
# HELP atlas_requests_total Total HTTP requests
# TYPE atlas_requests_total counter
atlas_requests_total{method="POST",path="/query",status="200"} 142.0
...
```

**Tracked metrics**

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `atlas_requests_total` | Counter | method, path, status | HTTP request count |
| `atlas_request_latency_seconds` | Histogram | method, path | End-to-end latency (buckets tuned for RAG: 0.05s–30s) |
| `atlas_token_usage_total` | Counter | model, type | Tokens consumed |
| `atlas_cache_hits_total` | Counter | — | Cache hit count |
| `atlas_cost_usd_total` | Counter | — | Estimated LLM cost |

---

## Two-Level Cache

[`cache.py`](../src/atlas/api/cache.py)

```
Query → _make_key() → "atlas:query:{xxh3_64(lower_stripped_query)}"
         │
         ├── L1: in-memory OrderedDict (LRU, max_size=256)   sub-ms
         │
         └── L2: Redis (optional, TTL=1h)                    ~1ms
```

**Cache key**: `xxh3_64` of the lower-cased, stripped query string. Case-insensitive
matching without storing PII in the key.

**LRU eviction**: `OrderedDict.move_to_end()` on every hit; `popitem(last=False)` when
over capacity. O(1) for all operations.

**Redis degradation**: Redis failures (connection refused, timeout) are caught and
logged as warnings. The cache continues to work at L1 only — the pipeline is never
blocked by a Redis outage.

**What is NOT cached**: streaming responses (buffering defeats streaming) and ingest
results (cheap to recompute, idempotent).

**Cache invalidation**: TTL-based only (default 1 hour). For content changes that
should immediately invalidate cached answers, call `cache.clear()` or add an ingest
completion hook.

---

## Middleware

### TracingMiddleware

[`middleware/tracing.py`](../src/atlas/api/middleware/tracing.py)

Assigns a `uuid4` request ID to every request and binds it into structlog's
`contextvars` store. Every log line emitted anywhere in the call stack for this
request automatically carries `request_id`, `method`, and `path` — no plumbing
required in route handlers or pipeline code.

Response headers set per request:
- `X-Request-ID: <uuid4>` — correlate with logs
- `X-Response-Time-Ms: <float>` — load balancer / client visibility

**OpenTelemetry upgrade path**: replace `uuid4()` with `otel.generate_trace_id()` and
bind span context; the rest of the structlog integration stays unchanged.

### PrometheusMiddleware

[`middleware/metrics_mw.py`](../src/atlas/api/middleware/metrics_mw.py)

Wraps every request (except `/metrics` itself) with timing and counting. Registered
outermost so it records true end-to-end latency including CORS and tracing overhead.

Latency histogram buckets are tuned for RAG workloads:
`0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0` seconds.
A typical non-cached query takes 1–3 seconds; streaming queries may run longer.

---

## Cost Estimation

[`cost.py`](../src/atlas/api/cost.py)

`estimate_cost(model, prompt_tokens, completion_tokens, embedding_model, embedding_tokens) -> float`

Price table (per 1M tokens, as of the initial implementation):

| Model | Input | Output |
|-------|-------|--------|
| gpt-4o | $2.50 | $10.00 |
| gpt-4o-mini | $0.15 | $0.60 |
| gpt-3.5-turbo | $0.50 | $1.50 |
| text-embedding-3-small | $0.02 | — |
| text-embedding-3-large | $0.13 | — |

Update the price table in `cost.py` as OpenAI adjusts pricing — no other changes needed.

---

## Request / Response Schemas

[`schemas.py`](../src/atlas/api/schemas.py)

API schemas are **intentionally separate** from internal interfaces (`atlas.interfaces.*`).
Internal models carry operational detail (chunk vectors, raw metadata dicts) that should
never appear in the public contract. Separation lets each side evolve independently.

Key schema decisions:
- Citations rendered as a flat ordered list (not a dict keyed by number) — more
  ergonomic for frontend consumers rendering a reference list.
- `StageTimings` exposes per-stage millisecond breakdowns for frontend latency displays
  and performance debugging.
- `QueryResponse.cached: bool` lets clients display a "served from cache" indicator and
  exclude cached responses from latency SLO measurements.

---

## Running Locally

```bash
# Start infrastructure
docker-compose up qdrant redis -d

# Start the API with hot reload
uvicorn atlas.api.app:app --reload --port 8000

# Query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the expense policy?"}'

# Ingest a directory
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/docs"}'

# Health check
curl http://localhost:8000/health

# Prometheus metrics
curl http://localhost:8000/metrics
```

### Interactive docs

`http://localhost:8000/docs` — Swagger UI  
`http://localhost:8000/redoc` — ReDoc

---

## Test Strategy

Tests in [`tests/unit/api/`](../tests/unit/api/) construct the app **without the
lifespan** (no real Qdrant/Redis/OpenAI) and inject a mock `AppState` directly:

```python
app = FastAPI()
app.state.atlas = AppState(
    pipeline=mock_pipeline,
    indexer=MagicMock(),
    cache=QueryCache(max_memory_size=10),
    embedding_model="text-embedding-3-small",
)
client = TestClient(app, raise_server_exceptions=False)
```

This gives realistic HTTP-layer coverage (request parsing, status codes, response
schemas, middleware headers) without any network I/O. The cache hit test populates
`cache._mem` directly to avoid requiring an async event loop in synchronous TestClient.
