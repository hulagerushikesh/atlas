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

## M2 — Cloud deploy (GCP)  ✅ done 2026-09-23 (current in prod 2026-10-07)

**Goal:** A public URL that stays up, costs a known amount, and holds no
secrets in code.

Scope: Cloud Run (asia-south1, like Finertia) for the API; Qdrant — managed
free tier or a small VM; Firestore replacing the SQLite key store; Secret
Manager for OpenAI/Qdrant keys; Redis via Memorystore or dropped in favour
of in-memory fallback at first; custom domain `atlas.hulage.in`; cost cap
and budget alert in INR.

Exit criteria:
- [x] Public URL answers a query end-to-end with a real API key —
      `https://atlas.hulage.in` via a Vercel rewrite to Cloud Run
      `atlas-api` in `asia-south1`. Verified live on rev **00011-xcm**
      (image `58e4e00`) 2026-10-07: warm `/query` 13.7 s, faithfulness 1.0,
      and citation [1] came back as `query-params-str-validations.md` — the
      page `fq-012` could never retrieve before context headers, so the
      answer also proved the index was the current one.
- [x] No secret in the repo, image, or env file in git (scan) — `.env` is
      gitignored and only `.env.example` is tracked, carrying placeholders
      and comments with every sensitive value empty (`QDRANT_API_KEY`,
      `ADMIN_SECRET`, `SENTRY_DSN`) and `OPENAI_API_KEY` a six-character
      placeholder. A `git grep` over the whole tracked tree at HEAD for
      Gemini/OpenAI/AWS/GitHub key shapes, JWTs and private-key blocks
      returns nothing (re-run 2026-10-12). Production reads **Secret
      Manager**, not a file.
- [x] Monthly cost estimate written down and a budget alert set — ₹200/mo
      alert on the GCP project; the estimate and the scale-to-zero reasoning
      are in `docs/deploy.md`, and the daily `$0.60` cap is enforced in the
      app with a 429 past it.
- [x] `docs/deploy.md` updated; Fly config removed or marked legacy —
      `docs/deploy.md` is 240 lines of the real GCP path; no Fly file is
      tracked anywhere in the repo.

These were met across 2026-09-23 → 10-07 but left unticked here until
2026-10-12, which is the same staleness `planning/STATUS.md` carried: the
work was done and the document still said it was next.

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
- [x] Faithfulness or context recall up by more than the measured noise floor
      → **context recall 0.667 → 0.9378**, +0.271 against a 0.02 significance
      floor, more than ten times it. Faithfulness is pinned at 1.000 and
      cannot rise, so recall is the live half of this criterion. Measured on
      `baseline-16_20261003-182853`; the M1 figure is from
      2026-09-20 at `reranker.top_k` 5 with no grader and no faithfulness
      check. Ticked 2026-10-12 — it had been objectively met and unticked,
      which is a bookkeeping gap, not a measurement one.
- [x] p95 latency and $/query not worse by more than an agreed budget
      → **budget agreed and accepted 2026-10-08: `planning/BUDGET.md`**
      (warm p95 ≤ 20 s, cost ≤ $0.005/query, +15% / +20% regression rule).
      Measured at acceptance, all inside the ceilings: warm p50 10,053 ms /
      p95 17,072 ms against 12,000 / 20,000; cost $0.0034677 against $0.005;
      eval run $0.0709 against $0.100. (Nearest-rank, as the reporter prints
      them — the figures first recorded here were interpolated, and inside
      the ceilings under either reading.) **Enforced since 2026-10-09:**
      `comparator.compare()` measures latency and run cost against the
      budget and withholds "Overall winner" on a breach. Cost per *query*
      stays hand-checked — an eval run also pays the metric judges.
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
- [x] 300+ tests, still ruff/mypy clean — **583 tests**, 92–93% coverage,
      ruff and mypy strict both clean, and since 2026-10-10 all three are
      checked by CI rather than asserted from one laptop. Met well before M4
      was opened, so this is the one M4 criterion that came free; the two
      above it are the actual work.

## Parked (not scheduled)

GraphRAG / RAPTOR; multimodal (ColPali); MCP tool exposure (that is
Sextant's job); fine-tuned embeddings (needs a labelled set M3 will start
producing).
