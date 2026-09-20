# M1 — First live run

**Status:** Step 0 done 2026-09-20 (Gemini, not OpenAI). Steps 1–9 open.
**Owner:** you (step 0), Claude (steps 1–9).

## Why this milestone

252 tests are green and every one of them mocks the LLM. The console was
verified against a mock API. The README quotes placeholder metrics. Until
this milestone is done, Atlas is an unverified claim. After it, every number
on the landing page and resume is real.

## Step 0 — Keys and credits — DONE 2026-09-20

Switched provider to Gemini (AI Studio key shared with sextant) via
`OPENAI_BASE_URL`; see DECISIONS 2026-09-20. `.env` points at local Docker
Qdrant, no cloud key. Verified live: 1536-d embeddings, JSON chat, streaming.

Budget: ₹50–100/day across atlas + sextant. Estimate for M1 at
`gemini-3.1-flash-lite` ($0.25/$1.50 per Mtok) + `gemini-embedding-001`
($0.15/Mtok): ingest 120 files ≈ ₹1; 30-sample eval run ≈ ₹10–20; two runs
+ smoke ≈ ₹30–45 total. State ₹ before each paid step.

Still open (security, not blocking): revoke the compromised OpenAI key and
Qdrant JWT — tracked in STATUS.

## Step 1 — Preflight (~5 min)

```bash
make docker-up            # Qdrant :6333 + Redis :6379
make lint && make typecheck && make test
.venv/bin/python scripts/check_health.py
```

Expect: 252 passed; health reports Qdrant + Redis reachable; Gemini key
accepted (a one-token embedding call, ≈₹0).

## Step 2 — Ingest (~5–10 min)

```bash
make ingest-dry           # lists 120 files, no API calls
make ingest               # recursive chunker, verbose
```

Record: files, chunks, embedding tokens, $ spent, wall time.
Then `make ingest` **again** — expect 0 chunks re-embedded (idempotency
proven live). If not, that is the first bug.

## Step 3 — Smoke the pipeline (~10 min)

```bash
make serve
```

Five questions via `curl` against `/query` — one simple, one complex (should
decompose), one out-of-scope (should refuse without retrieval), one that
needs exact identifiers (BM25 should carry it), one deliberately vague
(grader should retry). Check `stage_ms`, `evidence`, `grader_score`,
`faithfulness` on each. Then the streaming endpoint with `curl -N`.

Known first-run risks: JSON-mode responses not parsing (router/grader), the
reranker model download on first call (~90 MB, adds ~10 s once), cosine
overshoot warnings (harmless), quota errors (fail fast, not retry).

## Step 4 — Console against the live API (~15 min)

Open `/app`, point Settings at `:8010`, run the same five questions. Verify
the survey bar shows real timings, the evidence pane shows real
per-retriever scores with rerank cuts, citation chips deep-link, the strength
badge matches the faithfulness score. Then `/` — the landing hero is a
recorded loop, so only links and copy need checking. Fix any shape mismatch
between the mock and the real API here.

## Step 5 — Eval, twice (~10 min + API time)

```bash
make eval                 # run 1 → eval_data/reports/...
make eval                 # run 2, same config → noise floor
make eval-compare BASELINE=<run 1 report>
```

Record: context_precision, context_recall, faithfulness, answer_relevance,
p50/p95 latency, $/query, and the run-to-run spread. The spread is the
smallest improvement M3 is allowed to claim.

## Step 6 — Fix the BM25 tenancy bug (~30 min)

`api/namespaces.py` builds `BM25SparseIndex()` with the default
`bm25_index.json` path for every namespace. Give each namespace
`data/index/<namespace>/bm25_index.json`, add an integration test that
ingests into two namespaces and proves neither sees the other's chunks.
Re-run ingest into a second small namespace to prove it live.

## Step 7 — Write the numbers down (~20 min)

- `planning/STATUS.md` — measured table replaces "never run".
- `README.md` — placeholders → real metrics, with the date and config.
- Landing stats line and field notes if any number changed
  (`console/src/landing/Landing.tsx`, then `make console-build`).
- Resume bullets (in the resume-customiser project) — same numbers.

## Step 8 — Commit and tag

Secret scan on staged contents, then:

```bash
git tag -a v0.1.0 -m "First measured end-to-end run"
git push origin main --tags
```

## Step 9 — Close out

Tick every M1 exit criterion in `ROADMAP.md`. Write one DECISIONS.md entry:
baseline config, numbers, and what surprised you. Open M2 in a new chat.

## Checklist

- [ ] 0 keys revoked, new key in `.env`, credits added
- [ ] 1 preflight green
- [ ] 2 ingest done + idempotent re-run
- [ ] 3 five smoke questions behave
- [ ] 4 console + landing verified live
- [ ] 5 eval ×2, noise floor recorded
- [ ] 6 BM25 tenancy fixed + tested
- [ ] 7 numbers written everywhere
- [ ] 8 tagged v0.1.0
- [ ] 9 ROADMAP ticked, DECISIONS entry
