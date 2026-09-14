# Status — 2026-09-14

## One line

Atlas is feature-complete and UI-complete, verified against mocks and local
Qdrant only. It has never run end-to-end against live OpenAI. The next
milestone is that run.

## Blocked on you

- [ ] **Add OpenAI credits.** Nothing below moves without this.
- [ ] **Revoke the compromised OpenAI key** (the one pasted
      in an earlier chat). Generate a fresh one, put it in `.env` only.
- [ ] **Revoke the compromised Qdrant Cloud key** (the JWT pasted
      earlier). Local Docker Qdrant needs no key; do this before any cloud use.

## Where things stand

| Area | State | Evidence |
|---|---|---|
| Ingestion (A) | Done | `docs/ingestion.md`; ingest path fixed 7e05e0e |
| Hybrid retrieval (B) | Done, dense path proven against real Qdrant local mode | `tests/integration/test_qdrant_roundtrip.py` (90b3432) |
| Orchestration (C) | Done; evidence provenance + per-stage timings exposed | f17a28e |
| Evaluation (D) | Harness done, **never run live** — no numbers exist | README metrics are placeholders |
| API & observability (E) | Done | auth, rate limit, cache, Prometheus, streaming |
| Console | Rebuilt as React app (Vite + shadcn + Motion), cartographic design | baabc6e; `DESIGN.md` |
| Landing | Rebuilt in the same app, served at `/` | 2475b45 |
| Quality gate | ruff + mypy clean, **252 tests** green | `make lint typecheck test` |
| Corpus | FastAPI docs fetched: 120 markdown files in `data/corpus/fastapi/` | not yet ingested |
| Deploy | Docker Compose local; Fly config exists; GCP planned | `docs/deploy.md` |

## Known defects

See [BACKLOG.md](BACKLOG.md). The one that matters before multi-tenant use:
every namespace shares one `bm25_index.json`.

## Last three sessions

- 2026-09-13 — DESIGN.md (cartographic), console rebuilt twice (static HTML
  rejected → React/shadcn/Motion), landing rebuilt, API gained
  evidence/timings/sources endpoints.
- 2026-08-15 — Dense path proven against real Qdrant; `search()` →
  `query_points()`.
- 2026-08-07 / 14 — Dense retrieval repaired, ingest CLI made runnable, lint
  and types cleaned.

## Next

[M1 — First live run](milestones/M1-first-live-run.md). Start the moment
credits are in.
