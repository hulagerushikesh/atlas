# 08 — Production & Serving

What turns a pipeline into a service: multi-tenancy, auth, caching, limits,
observability, cost. Module E in Atlas's terms.

## Multi-tenancy (`api/namespaces.py`)

One Qdrant collection per namespace ("sheet" in the console). A
`NamespaceComponents(pipeline, indexer, sparse_index)` bundle is built per
namespace and cached. Isolation is at the collection level — a query for
`fastapi` cannot see `hr-policies`. The BM25 side currently shares one file
across namespaces (BACKLOG) — an example of how tenancy bugs hide in the
"other" index.

## Auth and keys (`api/auth.py`, `routes/keys.py`, `middleware/auth_mw.py`)

API keys are SHA-256 hashed at rest; the plaintext is shown once at creation.
Each key carries a name, email, and rate limit. `auth_enabled=False` by
default for local dev; `admin_secret` gates key creation. Never log the
plaintext key, never put it in a URL.

## Rate limiting

Per-key sliding window in Redis, in-memory fallback if Redis is down. Sliding
window (count requests in the last 60s) is fairer than fixed window (reset on
the minute) and simpler than token bucket. The fallback means a Redis outage
degrades to per-process limits rather than a 500.

## Caching (`api/cache.py`)

Two levels: L1 in-process LRU (microseconds, per worker), L2 Redis (ms,
shared across workers, TTL 3600s). Key = hash of (namespace, query,
config). RAG answers are expensive and questions repeat; cache hit rate is a
first-class metric. Invalidate on ingest.

## Streaming (`routes/query.py`)

SSE events per stage: `route`, `retrieval-done` (with evidence), `answer`
tokens, `citations`, `done`. Users see progress in <100ms instead of a
spinner for 2s. The console's Survey bar is drawn from these events. Cost:
you cannot set an HTTP status after the first byte, so errors become events.

## Observability

- **Tracing** (`middleware/tracing.py`): a request id per call, on every log
  line and in the response header. Structured logs via `logging.py`.
- **Metrics** (`middleware/metrics_mw.py`): Prometheus histograms for latency
  (p50/p95/p99), counters for tokens and cost, cache hits. `/metrics` route.
  Grafana dashboard in `monitoring/`.
- **Stage timings**: `stage_ms` in every response — the same data the
  console's Survey bar shows, so the user and the operator see the same
  truth.
- **Errors**: optional Sentry via `sentry_dsn`.

## Cost control (`api/cost.py`)

Every LLM and embedding call is priced from a table and summed per request.
Guard rails that matter in practice: the router refusing out-of-scope,
caching, the grader retry cap, and `max_tokens` on generation. Watch
embedding cost at ingest — it is the bill that surprises.

## Resilience (`retry_policy.py`, `orchestration/llm.py`)

Exponential backoff with jitter on 429/5xx; fallback model on persistent
failure; fail fast on auth/quota errors instead of retrying into a wall
(the quota-retry fix on the landing page's field notes). Timeouts on every
external call.

## Deployment (`docs/deploy.md`, `Dockerfile`, `fly.toml`)

Docker Compose locally (Qdrant + Redis + API). Fly.io config exists; the
plan is Cloud Run + managed Qdrant + Firestore for keys + Secret Manager
(planning/ROADMAP.md M2). The console is built to `src/atlas/api/static/`
and committed so the image needs no Node.

## Read

- Google SRE Book, ch. 4 (SLOs) and ch. 6 (Monitoring distributed systems).
- Redis docs: "Rate limiting patterns" (sliding window).
- Prometheus docs: "Histograms and summaries" — why histograms for latency.
- Martin Kleppmann, *Designing Data-Intensive Applications*, ch. 1 and 8 —
  reliability and the trouble with distributed systems.
- OpenAI docs: rate limits, error codes and the retry guidance.

## Exercise

[exercises.md → 08](exercises.md#08-production--serving)
