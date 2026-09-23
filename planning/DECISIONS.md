# Decisions

Short log. One entry per decision that someone might later ask "why?" about.
Format: date — decision — alternatives — reason.

- **2026-07** — Fixed pipeline DAG with bounded retry loops, not a free
  ReAct agent. *Alt:* tool-calling agent. *Why:* predictable latency and
  cost; the router gives most of the adaptivity. Sextant explores the other
  shape.
- **2026-07** — RRF for fusion, k=60. *Alt:* min-max score normalisation,
  learned fusion. *Why:* no calibration, no training, robust to one bad
  retriever; the original paper's default.
- **2026-07** — Cross-encoder MiniLM-L-6 as reranker. *Alt:* bigger
  rerankers, Cohere. *Why:* CPU-friendly, ~95% of the quality, no API
  dependency.
- **2026-07** — Faithfulness failures flag, not suppress. *Alt:* refuse on
  low score. *Why:* an honest answer with a warning is more useful than a
  refusal; the caller decides.
- **2026-07** — Recursive chunker, 512/64, as default. *Alt:* semantic.
  *Why:* free, structure-aware, good on docs; semantic costs embeddings per
  document.
- **2026-08-15** — Prove the dense path against real Qdrant local mode
  rather than mocks. *Why:* mocks hid the removed `search()` API for weeks.
- **2026-09-13** — Cartographic design direction. *Alt:* dark dev-tool
  teal/violet, warm-cream serif. *Why:* both alternatives are the category
  default now; the name is Atlas; metaphor in structure and vocabulary, not
  decoration. See `DESIGN.md`.
- **2026-09-13** — Console as a React app (Vite + Tailwind v4 + shadcn +
  Motion), built output committed to `static/`. *Alt:* static HTML/CSS.
  *Why:* static version rejected as amateur; real component primitives and
  motion needed; committing the build keeps the Python image Node-free.
- **2026-09-13** — Hero entrance via CSS keyframes, not Motion. *Why:*
  rAF-driven entrances stall under load; CSS runs off the main thread.
- **2026-09-14** — `learning/` and `planning/` folders; `SUMMARY.md` archived,
  `DEPLOY.md` → `docs/deploy.md`. *Why:* one place for progress that survives
  context loss; one place for study material separate from reference docs.
- **2026-09-20** — Gemini via OpenAI-compatible endpoint instead of OpenAI.
  *Alt:* buy OpenAI credits; write a native Gemini provider. *Why:* credits
  already exist on the AI Studio account shared with sextant; one config knob
  (`OPENAI_BASE_URL`) keeps the OpenAI SDK, retry ladder and tests unchanged.
  Models: `gemini-3.1-flash-lite` primary (same as sextant), `gemini-3.5-flash-lite`
  fallback, `gemini-embedding-001` at 1536-d. Verified: embeddings, JSON mode,
  streaming. Gemini omits `usage` on embeddings → embedder tolerates `None`.
- **2026-09-20** — Deterministic ids: `Document.id = uuid5(source)`,
  `Chunk.id = uuid5(doc_id:chunk_index)`. *Alt:* keep uuid4 and dedupe on
  content_hash via a payload index. *Why:* the dedupe already keyed on id;
  stable ids make it work with zero extra queries and keep Qdrant point ids
  valid. Cost: a shrinking doc leaves tail chunks (backlog).
- **2026-09-20** — Router gets a one-line domain description
  (`ROUTER_DOMAIN`) and prefers "simple" when unsure. *Alt:* drop the
  out-of-scope class. *Why:* refusal is a designed state on the landing page;
  it just needs to know what "in scope" means. Per-namespace domains later.
- **2026-09-20** — Eval matches `relevant_doc_ids` on corpus-relative path,
  not ingester id. *Why:* datasets are written by humans naming pages; ids
  are an implementation detail that just changed once.
- **2026-09-20** — Ship v0.1.0 with precision 0.31 on the landing page.
  *Alt:* tune first, publish later. *Why:* the honest number plus the
  per-miss diagnosis is the portfolio story; M3 is measured against it.
- **2026-09-20** — Daily spend cap in the API (`BUDGET_DAILY_USD`), enforced
  before each metered call, charged after, shared via Redis. *Alt:* rely on
  the AI Studio monthly cap. *Why:* that cap is shared with sextant and is
  monthly; a runaway client could burn a month in an hour. 429 + Retry-After
  is honest to callers; cache hits stay free. CLI scripts stay unmetered —
  a human runs them and states ₹ first.
- **2026-09-20** — Eval overrides are dotted paths into `Settings`
  (`--set reranker.top_k=10`), applied once, then the pipeline is built the
  normal way. *Alt:* a second, eval-only builder with kwargs. *Why:* one
  construction path; a typo fails loudly instead of running the baseline
  twice.
- **2026-09-20** — Console answer markdown is a ~40-line subset renderer
  (bold, code, lists, headings), not a markdown library. *Why:* the chips
  need to own `[n]`; a library would either escape them or need a plugin,
  and the generator prompt never emits more than this subset.
- **2026-09-20** — Relabelled eval numbers (P 0.42 / R 0.78) replace the
  first-run ones on README and landing. Same pipeline, same index; the change
  is two corrected labels. README keeps all three columns so the relabelling
  is visible rather than a silent bump.
- **2026-09-20** — Cloud Run topology for M2: scale-to-zero API, Qdrant
  Cloud free tier, Firestore for keys, no Redis, BM25 + reranker weights
  baked into the image. *Alt:* a small VM with docker-compose (sextant's
  route). *Why:* the demo must cost ≈₹0 idle; a VM is ₹270/mo parked and
  needs a static IP. Cold start (~15 s) is the price and is stated on the
  landing page. Redis returns when there is a second instance to share.
- **2026-09-20** — `sentence-transformers<6`. *Why:* 6.x cannot load the
  MiniLM cross-encoder tokenizer ("Unrecognized processing class"); the
  pin keeps the image build deterministic until upstream settles.
- **2026-09-23** — Payload indexes (`doc_id` keyword, `chunk_index` integer)
  are created in `ensure_collection`, not left to Qdrant defaults. *Why:*
  Qdrant Cloud rejects a filtered scroll or delete on an unindexed key with
  400 "Index required but not found"; local Qdrant answers the same filter
  happily, so `prune_document` passed every local test and failed on the
  first cloud ingest for all 155 documents. The roundtrip test asserts the
  index requests are made, because local mode accepts them and reports no
  schema back.
- **2026-09-23** — `.gcloudignore` in the repo, including `.dockerignore`.
  *Why:* with no `.gcloudignore`, `gcloud builds submit` uses `.gitignore`
  to pick the upload, which drops the gitignored `data/index/` the image
  bakes in — the build fails at `COPY data/index/`, and the failure names
  Docker, not gcloud.
- **2026-09-23** — `REDIS_URL=""` means "no Redis on purpose", and a client
  that fails its ping is discarded rather than passed to the cache. *Why:*
  the first Cloud Run revision reported `degraded` forever — the startup code
  assigned the client before pinging it, so every request then retried a
  refused connection on localhost. Absent Redis is the M2 design, not a
  fault, and `/health` has to say so or the signal is worthless.
