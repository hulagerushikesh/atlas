# Status — 2026-09-20 (v0.1.0)

## One line

M1 done 2026-09-20 (v0.1.0): Atlas ran end-to-end on the full FastAPI docs
with Gemini and has measured numbers. Six real defects surfaced and were
fixed on the way. Next is M2, the GCP deploy — separate chat, ask before
anything billable.

## Blocked on you

- [x] ~~Add OpenAI credits~~ → switched to Gemini (2026-09-20). Same AI Studio
      key as sextant, in `atlas/.env` only. Daily spend cap: ₹50–100 across
      both projects — state ₹ before every paid step.
- [ ] **Revoke the compromised OpenAI key** (the one pasted in an earlier
      chat). No longer used by Atlas, still live on the OpenAI account.
- [ ] **Revoke the compromised Qdrant Cloud key** (the JWT pasted earlier).
      `.env` now points at local Docker Qdrant; do this before any cloud use.

## Where things stand

| Area | State | Evidence |
|---|---|---|
| Ingestion (A) | Done, **proven idempotent live** (uuid5 ids, skip-before-embed) | 6c52438; 155 docs / 4,021 chunks, re-run 0.3 s |
| Hybrid retrieval (B) | Done, dense path proven against real Qdrant local mode | `tests/integration/test_qdrant_roundtrip.py` (90b3432) |
| Orchestration (C) | Done; evidence provenance + per-stage timings exposed | f17a28e |
| Evaluation (D) | **Run live ×4.** Relabelled: P 0.42 · R 0.78 · F 1.00 · AR 0.83 (was 0.31/0.67 with two mislabelled questions; same code, same index) | `eval_data/reports/fastapi-v2-relabel_*.json` |
| API & observability (E) | Done; **daily spend cap** (`BUDGET_DAILY_USD`, 429 past it, `/health.budget`) | auth, rate limit, cache, Prometheus, streaming |
| Console | Rebuilt as React app (Vite + shadcn + Motion), cartographic design | baabc6e; `DESIGN.md` |
| Landing | Rebuilt in the same app, served at `/` | 2475b45 |
| Quality gate | ruff + mypy clean, **295 tests** green, 86% cov | `make lint typecheck test` |
| Corpus | Full FastAPI docs: 155 markdown files, ingested into `atlas_default` + `data/index/default/bm25_index.json` | fetch with `--max-files 1000` |
| Deploy | Docker Compose local; Fly config exists; GCP planned | `docs/deploy.md` |
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

## Known defects

See [BACKLOG.md](BACKLOG.md). Nothing blocks M2. Post-M1 sweep closed six
items: stale tail chunks, manifest noise, eval labels, `--set` overrides,
daily spend cap, console markdown.

## Last three sessions

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

[M2 — Cloud deploy (GCP)](ROADMAP.md#m2--cloud-deploy-gcp). Separate chat.
Ask before anything billable; budget in INR. Before M2, user updates resume
bullets with the M1 numbers (`customise resume/`).
