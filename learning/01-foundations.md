# 01 — Foundations

What you need before retrieval makes sense. Skim what you know, slow down on
what you don't.

## 1. Async Python

Atlas is I/O-bound: every query waits on OpenAI, Qdrant, and Redis. Async lets
one process keep many of those waits in flight.

- `async def` / `await` — a coroutine yields control at every `await`; the
  event loop runs another coroutine meanwhile.
- `asyncio.gather` — run several awaits concurrently. Atlas uses it to hit the
  dense and sparse retrievers at the same time (`retrieval/hybrid.py`).
- `asyncio.to_thread` / `run_in_executor` — push CPU-bound or blocking work
  (the cross-encoder model, BM25 scoring) off the loop so it does not stall
  every other request. See `retrieval/reranker.py`.
- Async generators (`async def ... yield`) — the streaming endpoint in
  `api/routes/query.py` yields Server-Sent Events as stages finish.

Try: `python -c "import asyncio; ..."` — time `gather` on two `asyncio.sleep(1)`
calls. It should take ~1s, not 2.

## 2. Typing and Pydantic

Atlas is strict-`mypy` clean. That is not ceremony — the types are the contract
between modules.

- `interfaces/` defines abstract base classes (`BaseRetriever`, `BaseChunker`,
  `BaseLLMProvider`, ...). Every concrete implementation subclasses one. This
  is why a test can swap in a stub embedder and why a new vector DB is one
  file, not a refactor.
- Pydantic models (`interfaces/document.py`, `api/schemas.py`) validate at the
  boundary: bad JSON never reaches business logic. `model_copy(update=...)`
  is how immutable-ish chunks get new scores attached.
- `config.py` uses `pydantic-settings`: every knob is an env var with a typed
  default. `OpenAIConfig.primary_model = "gpt-4o-mini"`,
  `RetrievalConfig.top_k = 20`, `RerankerConfig.top_k = 5`. Read that file
  once; it is the whole tunable surface of the system.

## 3. FastAPI

- App factory (`api/app.py: create_app`) — build the app in a function so tests
  can build it with different settings.
- Lifespan — heavy objects (reranker model, Qdrant client) are created once at
  startup, not per request. See `docs/api.md`.
- Dependency injection (`api/dependencies.py`) — routes ask for a
  `NamespaceComponents` and FastAPI resolves it. Tests override the dependency.
- Middleware order matters: tracing → metrics → auth. Read
  `api/middleware/` top to bottom.
- Streaming: `StreamingResponse` with `text/event-stream`. Each SSE frame is
  `event: <name>\ndata: <json>\n\n`. The console's `streamQuery()` in
  `console/src/lib/api.ts` is the other half.

## 4. Tokens, models, cost

- LLMs bill per token, in and out. `text-embedding-3-small` is ~$0.02 / 1M
  tokens; `gpt-4o-mini` is cheap but not free. `api/cost.py` prices every
  call so the console can show `$0.0004` next to an answer.
- Temperature 0 for anything that must be deterministic-ish (routing,
  grading). Atlas does this everywhere except generation.
- JSON mode / structured output: the router, grader and faithfulness checker
  all ask for JSON and parse it defensively (`parsed.get("score", 0.5)`).
  Assume the model will occasionally not comply.

## 5. Vectors, in one page

- A vector is a list of floats. An embedding model maps text → a vector of
  fixed size (1536 for `text-embedding-3-small`).
- Dot product `a·b = Σ aᵢbᵢ`. Cosine similarity `a·b / (‖a‖‖b‖)` — the dot
  product after normalising both to length 1. Range [−1, 1]; for text
  embeddings almost always in [0, 1].
- Float rounding: a cosine of `1.0000000240112157` is not a bug, it is
  `float32` arithmetic. Atlas's integration test allows `±1e-6`.
- Distance vs similarity: Qdrant returns similarity (higher = closer) for
  cosine collections. Don't mix conventions.

## 6. Infrastructure vocabulary

- **Qdrant** — vector database. Stores points (id, vector, payload). Atlas has
  one collection per namespace. Local mode `AsyncQdrantClient(":memory:")`
  runs the real engine in-process — used by
  `tests/integration/test_qdrant_roundtrip.py`.
- **Redis** — key/value store used for the L2 cache and rate-limit counters.
  Atlas degrades to in-memory if Redis is absent.
- **Docker Compose** — `make docker-up` brings Qdrant + Redis up locally.
- **Prometheus / Grafana** — metrics scrape + dashboard. `metrics_mw.py`
  emits histograms; `monitoring/` has the dashboard JSON.

## Read

- FastAPI docs: "Bigger Applications", "Lifespan Events", "Dependencies".
- Real Python: "Async IO in Python: A Complete Walkthrough".
- Pydantic v2 docs: "Models", "Settings Management".
- 3Blue1Brown, *Essence of Linear Algebra*, chapters 1–3 and the dot-product
  chapter — one evening, worth it.

## Exercise

See [exercises.md → 01](exercises.md#01-foundations).
