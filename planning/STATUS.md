# Status — 2026-09-27 (v0.1.0, M2 done, M3 in progress)

## One line

**M2 is done: https://atlas.hulage.in is live** — Cloud Run rev 00004 in
`asia-south1` behind a Vercel rewrite, Qdrant Cloud with 4,020 chunks,
Firestore for keys and the spend counter, four Secret Manager secrets, ₹200/mo
budget alert. M3 has started: the BM25 tokeniser is the first measured change.

## Blocked on you

- [x] ~~Add OpenAI credits~~ → switched to Gemini (2026-09-20). Same AI Studio
      key as sextant, in `atlas/.env` only. Daily spend cap: ₹50–100 across
      both projects — state ₹ before every paid step.
- [x] ~~Revoke the compromised OpenAI key~~ → all keys on the account
      revoked 2026-09-20.
- [x] ~~Revoke the compromised Qdrant Cloud key~~ → cluster deleted
      2026-09-20; key died with it. `.env` uses local Docker Qdrant.
- [x] ~~Resume bullets~~ → applied 2026-09-23 to `resume_v5a.tex`: four
      bullets, GitHub + atlas.hulage.in links, deployed numbers (P 0.43 ·
      R 0.78 · F 1.00, 4,020 chunks, 340 tests). Compiled with tectonic,
      still 2 pages; `resume_v5a_preview_5.pdf`.
- [x] ~~Run the Cloud Run deploy~~ → four revisions rolled 2026-09-23; the
      sandbox blocks `gcloud run deploy`, so every deploy is
      `scripts/deploy_gcp.sh` run by hand.
- [x] ~~Billing budget alert~~ → ₹200/mo on `atlas-rag-rush`, alerts at
      50/90/100%.
- [x] ~~DNS~~ → Cloudflare CNAME `atlas` → `<hash>.vercel-dns-017.com`,
      DNS-only. Certificate issued; all four routes 200.
- [x] ~~Full eval run~~ → run 2026-09-23 (₹0.3, 83 s, 15,341 tokens).
      P 0.431 · R 0.778 · F 1.000 · AR 0.825; every delta from the relabelled
      baseline below the 0.02 floor. README carries it as the "Deployed"
      column.

## Where things stand

| Area | State | Evidence |
|---|---|---|
| Ingestion (A) | Done, **proven idempotent live** (uuid5 ids, skip-before-embed) | 6c52438; 155 docs / 4,021 chunks, re-run 0.3 s |
| Hybrid retrieval (B) | Done, dense path proven against real Qdrant local mode | `tests/integration/test_qdrant_roundtrip.py` (90b3432) |
| Orchestration (C) | Done; evidence provenance + per-stage timings exposed | f17a28e |
| Evaluation (D) | **Run live x11.** Best measured (`headers` namespace): P 0.467 - R 0.938 - F 1.000 - AR 0.833 over all 15 rows, ~Rs.0.77 a run, all on `gemini-3.1-flash-lite`. Live `default` namespace is one change behind (P 0.387 - R 0.933). Context metrics skip a row only when it has no relevant document, and after the 2026-09-27 audit no row does. Reports carry per-stage p50/p95 and the model that served the run. **The retrieval-only harness has mispredicted four times running** - no grader, no retry, no decomposition; use it only to ask whether a document is reachable at all | `eval_data/reports/ctx-headers_20260927-120939.json` |
| API & observability (E) | Done; **daily spend cap** (`BUDGET_DAILY_USD`, 429 past it, `/health.budget`); keys in SQLite or **Firestore** (`AUTH_STORE`) | auth, rate limit, cache, Prometheus, streaming |
| Console | Rebuilt as React app (Vite + shadcn + Motion), cartographic design | baabc6e; `DESIGN.md` |
| Landing | Rebuilt in the same app, served at `/` | 2475b45 |
| Quality gate | ruff + mypy clean, **340 tests** green, 90% cov | `make lint typecheck test` |
| Corpus | Full FastAPI docs: 155 markdown files, ingested into `atlas_default` + `data/index/default/bm25_index.json` | fetch with `--max-files 1000` |
| Deploy | **LIVE: https://atlas.hulage.in** (Cloud Run rev 00004 `d280006`, Vercel rewrite, Let's Encrypt cert); `/`, `/app`, `/docs`, `/health` all 200; budget ₹200/mo | `docs/deploy.md`, `scripts/deploy_gcp.sh`, `proxy/` |
| LLM provider | Gemini via OpenAI-compatible endpoint, verified: embed 1536-d, JSON chat, streaming | `OPENAI_BASE_URL`, 2026-09-20 |

## Measured (2026-09-20, v0.1.0)

| Metric | Value |
|---|---|
| Context precision @5 | 0.309 |
| Context recall | 0.667 (5/15 misses; 2 are dataset labels, 3 genuine) |
| Faithfulness | 1.000 |
| Answer relevance | 0.815 / 0.826 (two runs) |
| Latency | p50 ≈7 s uncached (Gemini flash-lite, 5–7 LLM calls); <1 ms cache hit; reranker cold start +5 s |
| Cost | ≈₹0.03 per uncached query; ≈₹1.5 per 15-sample eval |

## Measured (2026-09-27, `top_k` 15, additive retry + capped merge + context headers)

Context metrics are over **all 15 rows**. They used to exclude `fq-015` as
out of scope; it is not out of scope, and the exclusion was hiding a good
retrieval — see below.

**Every context number below was recomputed after the dataset audit of
2026-09-27.** All fifteen reference answers were read back against the corpus,
claim by claim, and nine rows needed something. They are not the figures
quoted earlier today, twice. The recomputation is offline and exact —
`scripts/replay_context_metrics.py` replays a stored report's chunk ids
against any label set for Rs.0 — so no run was repeated to produce this.

| Metric | 09-24 | retry fix | capped merge | **+ headers** |
|---|---|---|---|---|
| Context precision | 0.3733 | 0.3477 | 0.3867 | **0.4667** |
| Context recall | 0.9244 | 0.9333 | 0.9333 | **0.9378** |
| Faithfulness | 1.0000 | 1.0000 | 1.0000 | **1.0000** |
| Answer relevance | 0.8277 | 0.8253 | 0.8271 | **0.8328** |
| Tokens / eval | 37,599 | 44,224 | 35,928 | **39,461** |
| Cost / eval | ~Rs.0.73 | ~Rs.0.86 | ~Rs.0.70 | **~Rs.0.77** |
| Latency p50 | 15.0 s | 11.0 s | 10.0 s | **9.7 s** |

All four runs served entirely by `gemini-3.1-flash-lite`, so the deltas are
changes in the pipeline and not in the model.

**Precision is still the day's result, +0.093, and it is no longer monotone.**
The retry fix *costs* precision, 0.3733 → 0.3477: it widens the window, and
two rows that the old labels scored as structural zeros or near-zeros —
`fq-015` at 0.5333 → 0.3158 and `fq-007` at 0.4667 → 0.3659 — are now visible
paying for it. The cap gets it back (0.3867) and the headers take it to
0.4667. The ordering claim "three changes, each positive on precision" is
withdrawn; the shape is cost, refund, gain.

**Recall did not move all day: 0.9244 → 0.9378, +0.013, inside the 0.02
floor.** Third restatement of this figure and the third time it has come out
below the floor.

**`fq-015` was never out of scope.** `advanced/websockets.md` is in the corpus
and its "WebSockets client" section names React. The pipeline answers the
question from it, with citations and faithfulness 1.000 — the run that was
being discarded as a structural zero was scoring 0.4667 precision and 1.000
recall. The `applicable=False` guards in both context metrics are now
unreachable from this dataset; they stay for a dataset that does carry an
unanswerable row, and this one no longer has one (BACKLOG).

`fq-007` recall is 0.6667 in the headers run, not 0.5 — it has three labelled
documents now, not two, because `OAuth2PasswordBearer` is defined on
`tutorial/security/first-steps` and neither old label carried it.

**The headers are not deployed and not even in the default namespace.** They
were ingested into `headers` so the live collection was never touched;
shipping them is another ~Rs.6.45 re-ingest. See BACKLOG. Precision is the
case for shipping; recall is not.

The "~7 s" in older notes is from 2026-09-20, measured differently, and is not
a baseline this can be diffed against.

## Known defects

See [BACKLOG.md](BACKLOG.md). Nothing blocks M2. Post-M1 sweep closed six
items: stale tail chunks, manifest noise, eval labels, `--set` overrides,
daily spend cap, console markdown.

## Last three sessions

- 2026-09-23 (M2 done + M3 opened, ≈₹1.1) — four Cloud Run revisions. Three
  defects only the cloud could find: missing Qdrant payload indexes, the
  missing `.gcloudignore`, and a Redis client cached before its ping (the
  service reported `degraded` forever). Two more only the proxy could find: the
  catch-all rewrite does not match `/`, and the StaticFiles mount's 307 for
  `/app` leaked the run.app host. Spend moved to Firestore after the live
  service reported `spent_today_usd: 0.0` for a query it had just charged.
  `atlas.hulage.in` fronted by a Vercel rewrite because Cloud Run refuses
  domain mappings in `asia-south1`. M3 started: identifier-aware BM25
  tokeniser, recall 0.726 → 0.798 and precision 0.529 → 0.486 on the new
  retrieval-only harness — but the full eval then showed it is worth nothing
  end to end (recall 0.778 either way, `fq-005` won and `fq-012` lost), because
  query decomposition already recovers what better tokenisation recovers. Kept
  for the router's non-decomposing "simple" branch.
- 2026-09-23 (M2 infra, ≈₹1) — GCP project `atlas-rag-rush` created and
  billed, five APIs on, Artifact Registry + Firestore in `asia-south1`, four
  Secret Manager secrets (all piped from `.env`, none typed), IAM for the
  compute SA. Image `0fdd0b2` built by Cloud Build (~3 min). Corpus ingested
  into the Qdrant Cloud cluster: **4,020 chunks** (one stale `index.md` tail
  chunk pruned, so cloud and BM25 now agree exactly). Two defects the cloud
  found that local could not: missing payload indexes (Qdrant Cloud 400s
  filtered deletes) and the missing `.gcloudignore` (build lost `data/index/`).
  313 tests. Left to do: `gcloud run deploy`.
- 2026-09-20 (M2 prep, ₹0) — `KeyStore` protocol: SQLite + Firestore
  backends (`AUTH_STORE`), `/keys` reachable before the first key exists
  (was a chicken-and-egg with auth on — found by the image smoke test);
  production Dockerfile (CPU torch, reranker weights + BM25 baked in, `PORT`),
  `scripts/deploy_gcp.sh` + `make deploy-gcp`, Fly config removed,
  `docs/deploy.md` rewritten for Cloud Run. Auth middleware got its first
  tests. Image builds and boots locally (2.15 GB arm64). GCP project not
  yet created — needs a yes.
- 2026-09-20 (later) — **Post-M1 sweep**, ₹0 except two console queries:
  `prune_document` for shrinking docs; unsupported files skipped at ingest;
  fq-002 → `release-notes`, fq-008 += `stream-data`; `run_eval.py --set`
  applies `PipelineConfig.overrides` (`reranker.enabled=false` now exists);
  `BUDGET_DAILY_USD` cap (0.60 locally); console renders answer markdown.
  Eval re-run on relabelled set: P 0.31→0.42, R 0.67→0.78, F 1.0, AR 0.83
  (₹0.3, 156 s). Three genuine misses remain: `tutorial/body`,
  `tutorial/response-model`, `tutorial/security/*` → M3.
- 2026-09-20 — **M1 done.** Gemini via `OPENAI_BASE_URL`; fixed ingest
  idempotency (uuid5), namespace collection/BM25 mismatch, router domain,
  Qdrant image, eval doc-id matching, judge truncation. Full corpus, three
  eval runs, numbers into README/landing/STATUS. Tagged v0.1.0.
- 2026-09-13 — DESIGN.md (cartographic), console rebuilt twice (static HTML
  rejected → React/shadcn/Motion), landing rebuilt, API gained
  evidence/timings/sources endpoints.
- 2026-08-15 — Dense path proven against real Qdrant; `search()` →
  `query_points()`.
- 2026-08-07 / 14 — Dense retrieval repaired, ingest CLI made runnable, lint
  and types cleaned.

## Next

- ~~`retrieval.top_k` 20 → 40~~ run 2026-09-24 and **rejected**: recall
  0.9000 → 0.9333 in aggregate, but per sample `fq-012` and `fq-007` were
  bought with `fq-005` breaking outright, and precision fell 0.3022 → 0.2711
  at an unchanged window width. Still rejected after the 2026-09-27 relabel,
  though `fq-012`'s gain there was larger than anyone knew: 0.200 → 0.600,
  the best that sample has ever scored. A broken question still vetoes it.
- ~~A stronger reranker~~ run 2026-09-25 and **rejected**. L-12 bought no
  recall end to end and put retrieval p50 at 18 s under concurrency;
  `bge-reranker-base` (278M) scored worse than the 23M model it would replace.
- ~~"`fq-005` and `fq-012` are the same slot"~~ **retracted 2026-09-25.** It
  was a story told over three experiments that shared a symptom, and ₹0.06 of
  retrieval dumps refuted it: `tutorial/body` sits at ranks 5, 6, 8, 10 and 13
  for `fq-005`, while `tutorial/query-params-str-validations` never appears at
  all for `fq-012`. One target is abundant, the other absent. The real cause
  was a retry that replaced context instead of adding to it — fixed in
  `68e1810` and **confirmed 2026-09-27**: recall 0.9000 → 0.9333, precision
  also up, only the retrying samples moved.
- ~~Cap and globally rerank the sub-query merge~~ **shipped 2026-09-27.**
  Round-robin across sub-queries, then cut to one window re-ranked against the
  original question. Precision 0.3477 → 0.3867, recall unchanged at 0.9333,
  tokens 44,224 → 35,928 (Rs.0.86 → Rs.0.70). The predicted risk — that the cap
  would take `fq-007` back to 0.5 recall — did not happen.
- ~~Grader window~~ **de-prioritised 2026-09-27.** `grader.py:82` still grades
  `chunks[:5]` of 15, but once the top five are ranked against the original
  question it stopped mis-grading: `fq-007` went from three grader calls to
  one. It is a small latency item now, not a quality one.
- ~~Deterministic chunk headers~~ **built and measured 2026-09-27, not
  shipped.** Source path in words plus the heading trail, prepended to each
  chunk's indexed text. Re-ingested into a `headers` namespace for Rs.6.45
  (priced at Rs.6.42 beforehand by chunking locally). Precision 0.3867 →
  0.4667, the largest single gain of the milestone. Recall 0.9333 → 0.9378,
  a move inside the noise floor. **Shipping it to the live namespace is another
  ~Rs.6.45 re-ingest and needs a go-ahead.** Two things sold it that did not
  hold: BM25's rank for `fq-012` got *worse*, 11 → 15, and the recall gain
  and the "`fq-012` recalled for the first time" headline were both artifacts
  of that sample's one-document label. Precision is what it actually bought.
  See DECISIONS.
- ~~Relabel `fq-012`~~ **done 2026-09-27**, and then the whole set was
  audited the same way: read each reference answer's claims back against the
  corpus, `grep` for each one. Nine of fifteen rows needed something —
  `fq-012` widened 1 → 5, `fq-006`/`fq-007`/`fq-014` widened by one page each,
  `fq-008` *narrowed* (a required page supported none of its claims),
  `fq-003`/`fq-004`/`fq-005`/`fq-009`/`fq-010` reworded off APIs and status
  codes the corpus does not contain, and `fq-015` found not to be out of scope
  at all. Every context number in STATUS and README recomputed offline with
  `scripts/replay_context_metrics.py` (Rs.0, no model calls). Nothing was
  re-run. `metadata.label_rationale` on each changed row records why.
- LLM-written contextual headers — **re-price before starting.** The ~₹15
  figure in earlier notes does not survive arithmetic: 4,020 chunks x ~2.5k
  input tokens is ~10M tokens, nearer ₹200 without prompt caching.

## Earlier plan (M3 as opened)

M3 — retrieval quality. Three questions miss end to end
(`fq-007 tutorial/security/oauth2-jwt`, `fq-011 tutorial/response-model`,
`fq-012 tutorial/query-params-str-validations`) and `fq-008
advanced/custom-response` is partial at 0.67.

The tokeniser result says the constraint is the **five slots**, not the
retriever's ability to find the document: `fq-005` and `fq-012` traded places
at the rank-5 boundary rather than both fitting. So the next experiment is the
rerank `top_k` sweep (5 / 10 / 15, `run_eval.py --set reranker.top_k=10`),
which changes the number of slots directly. Then profiling the retrieval
stage, ~5.1 s of the six.

Measure with `scripts/eval_retrieval.py` (≈₹0.01) to reject, then confirm with
the full eval (≈₹0.3) before publishing — the cheap harness runs the
un-decomposed path and flatters retrieval changes. Ask before anything
billable; budget in INR.
