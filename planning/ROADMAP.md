# Roadmap

Four milestones. Each has exit criteria; a milestone is not done until every
one is ticked. Order is fixed — M2 without M1's numbers would deploy something
unmeasured.

## M1 — First live run  ✅ done 2026-09-20 (v0.1.0)

**Goal:** Atlas answers real questions over the real FastAPI corpus with
a live LLM (ended up Gemini, not OpenAI), and we have measured numbers.

Exit criteria:
- [x] `make ingest` completes on `data/corpus/fastapi/` (155 files, 4,021 chunks), re-run is idempotent (0.3 s, 0 re-embeds) — after fixing uuid4 ids
- [x] `make eval` produces a report; four metrics recorded in STATUS.md (p50 ≈7 s uncached, ≈₹0.03/query)
- [x] Console `/app` and landing `/` verified against the live API
- [x] BM25 per-namespace bug fixed with a test (plus the collection-name mismatch nobody knew about)
- [x] README placeholders replaced with measured numbers; landing has a Measured section
- [ ] Resume bullets updated with the same numbers — **user's job**, resume lives in `customise resume/`

Plan: [milestones/M1-first-live-run.md](milestones/M1-first-live-run.md)

## M2 — Cloud deploy (GCP)  ◄ next

**Goal:** A public URL that stays up, costs a known amount, and holds no
secrets in code.

Scope: Cloud Run (asia-south1, like Finertia) for the API; Qdrant — managed
free tier or a small VM; Firestore replacing the SQLite key store; Secret
Manager for OpenAI/Qdrant keys; Redis via Memorystore or dropped in favour
of in-memory fallback at first; custom domain `atlas.hulage.in`; cost cap
and budget alert in INR.

Exit criteria:
- [ ] Public URL answers a query end-to-end with a real API key
- [ ] No secret in the repo, image, or env file in git (scan)
- [ ] Monthly cost estimate written down and a budget alert set
- [ ] `docs/deploy.md` updated; Fly config removed or marked legacy

Do this in a separate chat, after M1. Ask before turning on anything billable.

## M3 — Retrieval quality, measured

**Goal:** Beat the M1 baseline on `make eval-compare` with at least two
research-backed changes, each one PR, each with a before/after report.

Candidates, in expected value-per-effort order:
1. Tokeniser fix for BM25 (identifiers, camelCase) — free
2. HyDE for dense retrieval — one file, one LLM call
3. Contextual retrieval at ingest — one LLM call per chunk, re-ingest
4. Rerank top_k 5 → 10–15, generation context reordered (lost-in-the-middle)
5. Local embedding model option (bge / e5) — cost to zero, quality measured
6. SPLADE via Qdrant sparse vectors — replaces the O(N) BM25 loop

Exit criteria:
- [ ] ≥ 2 changes merged, each with `eval-compare` in the PR
- [ ] Faithfulness or context recall up by more than the measured noise floor
- [ ] p95 latency and $/query not worse by more than an agreed budget
- [ ] `learning/` module 09 exercise written up for each in DECISIONS.md

## M4 — Product hardening

**Goal:** Something a second person could use without you in the room.

Scope: per-namespace ingest from the console (upload, progress, errors);
key management UI; usage page per key; unanswerable-question handling
polished (refusal copy, suggestions); dataset upload for per-corpus eval;
PDF quality (layout-aware parser); export of a query's evidence as JSON.

Exit criteria:
- [ ] A new corpus can be created, ingested and queried entirely from the console
- [ ] An outsider follows README from clone to first answer in < 15 minutes
- [ ] 300+ tests, still ruff/mypy clean

## Parked (not scheduled)

GraphRAG / RAPTOR; multimodal (ColPali); MCP tool exposure (that is
Sextant's job); fine-tuned embeddings (needs a labelled set M3 will start
producing).
