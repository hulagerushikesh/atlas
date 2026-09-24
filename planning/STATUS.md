# Status — 2026-09-24 (v0.1.0, M2 done, M3 in progress)

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
| Evaluation (D) | **Run live ×8.** Deployed (`top_k` 15): P 0.302 · R **0.900** · F 1.000 · AR 0.828. **Replicated 2026-09-24:** the identical config a day later reproduced precision, recall and faithfulness to four decimal places. Reports now carry per-stage p50/p95 and the model that served the run. Retrieval-only harness at ≈₹0.01 for cheap rejection | `eval_data/reports/topk15-clean_*.json` |
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

## Measured (2026-09-24, `top_k` 15)

| Metric | Value |
|---|---|
| Context precision | 0.3022 (one relevant doc cannot fill a 15-slot window) |
| Context recall | 0.9000 (`fq-012` misses outright, `fq-007` partial at 0.5) |
| Faithfulness | 1.0000 |
| Answer relevance | 0.8277 |
| Latency | **p50 15.0 s / p95 24.7 s** per sample; slowest stage is grading (3.5 s), which is `top_k`-independent. Live production query the same hour: 15.7 s wall clock |
| Cost | ≈₹0.085 per uncached query; ≈₹0.73 per 15-sample eval (37.6k tokens) |

The ≈7 s above is from 2026-09-20 and was measured differently — it is not a
baseline this can be diffed against. Latency is six sequential LLM round trips
at ~2.5 s each; reducing it means removing a call, not narrowing the window.

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

- `retrieval.top_k` 20 → 40, confirmed end to end (≈₹0.73). Measured 0.964 vs
  0.929 on the cheap harness; unshipped on purpose.
- Cap and rerank the sub-query merge — `_retrieve_all` never truncates, so a
  complex question can hand the generator `sub_queries x top_k` chunks
  (`fq-013` sent 30). See BACKLOG.
- `fq-012` is the last outright miss. Contextual chunk headers, ~₹15, needs a
  re-ingest — ask before starting.

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
