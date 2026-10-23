# Roadmap

Four milestones. Each has exit criteria; a milestone is not done until every
one is ticked. Order is fixed — M2 without M1's numbers would deploy something
unmeasured.

**All four are done as of 2026-10-14, and as of 2026-10-22 all 17 exit
criteria are ticked** — the last one, M1's resume-bullets line, closed when
the Atlas block in `customise resume/resume_v5a.tex` was rewritten against
this repo's own figures. There is deliberately **no M5 yet**: picking one is a decision, not a
backlog item, and the pool to pick it from is *Parked* at the bottom of this
file plus `planning/BACKLOG.md`. Until one is opened, "what's next" is
whatever `planning/STATUS.md` lists under *Blocked on you* — mostly two paid
runs waiting on a spend go-ahead.

## M1 — First live run  ✅ done 2026-09-20 (v0.1.0)

**Goal:** Atlas answers real questions over the real FastAPI corpus with
a live LLM (ended up Gemini, not OpenAI), and we have measured numbers.

Exit criteria:
- [x] `make ingest` completes on `data/corpus/fastapi/` (155 files, 4,021 chunks), re-run is idempotent (0.3 s, 0 re-embeds) — after fixing uuid4 ids
- [x] `make eval` produces a report; four metrics recorded in STATUS.md (p50 ≈7 s uncached, ≈₹0.03/query)
- [x] Console `/app` and landing `/` verified against the live API
- [x] BM25 per-namespace bug fixed with a test (plus the collection-name mismatch nobody knew about)
- [x] README placeholders replaced with measured numbers; landing has a Measured section
- [x] ~~Resume bullets updated with the same numbers~~ **done 2026-10-22.** `customise resume/resume_v5a.tex`, Atlas block rewritten against the repo's own figures and typeset to check it still fits (2 pages before, 2 after). Four numbers in the old bullets had gone stale: recall 0.78 → **0.9378**, 340 tests at 90% → **764 at 93.68%**, 7,400 LOC → **11,541**, and `~$0.0005 per query`, which was wrong by about 7x — replaced with the **$0.005 enforced ceiling** rather than the measured $0.0035, because BUDGET.md records that figure as n=1 and names it the weakest number in the file. Backup at `resume_v5a.tex.bak-20261022`; wording is the user's to adjust

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

## M3 — Retrieval quality, measured  ✅ done 2026-10-14

**Goal:** Beat the M1 baseline on `make eval-compare` with at least two
research-backed changes, each with a stored before/after report.

Candidates, in expected value-per-effort order:
1. Tokeniser fix for BM25 (identifiers, camelCase) — free
2. HyDE for dense retrieval — one file, one LLM call *(built; both arms
   measured 2026-10-17/18, both rejected on budget — see DECISIONS)*
3. Contextual retrieval at ingest — one LLM call per chunk, re-ingest
4. Rerank top_k 5 → 10–15, generation context reordered (lost-in-the-middle)
5. Local embedding model option (bge / e5) — cost to zero, quality measured
6. SPLADE via Qdrant sparse vectors — replaces the O(N) BM25 loop

Exit criteria:
- [x] ≥ 2 research-backed changes shipped to `main`, each with a stored
      `eval-compare` report pair and a dated write-up in DECISIONS.md
      → **`reranker.top_k` 5 → 15** (context recall 0.778 → 0.900, +0.122
      against a 0.02 floor; DECISIONS 2026-09-23) and **deterministic context
      headers** (context precision 0.3762 → 0.4524, recall 0.9286 → 0.9643,
      and `fq-012` recalled for the first time at 0.000 → 1.000; DECISIONS
      2026-09-27). A third change shipped too — identifier-aware BM25
      tokenisation — and is written up as worth **nothing** end to end
      (recall 0.778 → 0.778, every delta under the floor), which is a result
      and is why the bar here is two rather than "all of them".
      **Reworded 2026-10-14.** The original read "≥ 2 changes merged, each
      with `eval-compare` in the PR". This repo has **zero merge commits and
      no pull request has ever existed** — it is one person committing to
      `main` — so the PR was a venue, never the evidence. The evidence is 16
      stored before/after reports in `eval_data/reports/` and the dated
      entries, which a reader can still check long after a PR thread would
      have scrolled away. The bar did not move; the place it is met did.
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
- [x] Each of those changes traced in DECISIONS.md to the `learning/`
      module 09 item it came from, with its measured before/after
      → `reranker.top_k` 5 → 15 is module 09 **§1 (Long context vs RAG)**,
      which names this exact change: "raise `RerankerConfig.top_k` from 5 to
      ~15 and measure faithfulness vs cost". Context headers are **§5
      (Ingestion quality)**, shipped as the deterministic cousin of the
      LLM-written contextual retrieval that section lists — path and heading
      trail, no LLM call per chunk. Both cross-references were added to the
      DECISIONS entries on 2026-10-14.
      **Reworded 2026-10-14, and this asks for less than the original did.**
      The original read "`learning/` module 09 exercise written up for each",
      and `learning/exercises.md` §09 defines that exercise as a paper
      write-up ending in "the `make eval-compare` result you would expect" —
      a prediction, made before paying. What DECISIONS holds instead is the
      measurement and, for both of these changes, a correction: the cheap
      retrieval-only harness mispredicted four times running, and the
      mechanism argued for the context headers turned out to be the wrong one
      (`fq-012` was recovered by decomposition and the additive retry, not by
      path tokens). Keeping the original wording would mean inventing
      predictions after the fact for changes already shipped, which is worth
      less than the corrections are. The exercise as written stands for the
      *next* change: HyDE is module 09 §4, built, off by default, and still
      the only unmeasured thing in M3 at ≈₹6.24.
      **Discharged 2026-10-17.** The prediction was written, committed
      (`9eed3f2`) and only then paid for, which is the exercise as
      `learning/exercises.md` §09 describes it. HyDE `concat` measured
      +0.0619 context precision against −0.0238 answer correctness and warm
      p95 21,400 ms against a 20,000 ms ceiling; the comparator withheld the
      winner and the knob stays off. The prediction's verdict was right and
      three of its eight numbers were wrong, context precision worst — it
      was predicted to fall and it rose the most of anything in the table.
      Both the result and the scoring are in DECISIONS 2026-10-17. `replace`
      was measured 2026-10-18 and is worse: +0.0845 precision but −0.0245
      recall, warm p95 +138.6%, and a tie with `concat` on every metric
      head to head. **Both arms measured, both rejected, HyDE closed.**

## M4 — Product hardening  ✅ done 2026-10-13 (marked 2026-10-14)

**Goal:** Something a second person could use without you in the room.

Scope: per-namespace ingest from the console (upload, progress, errors);
key management UI; usage page per key; unanswerable-question handling
polished (refusal copy, suggestions); dataset upload for per-corpus eval;
PDF quality (layout-aware parser); export of a query's evidence as JSON.

Exit criteria:
- [x] A new corpus can be created, ingested and queried entirely from the console —
      **demonstrated end to end 2026-10-13, Rs.0.07.** Named `field-notes` in the
      sheet picker, dropped a markdown file on the upload zone, asked a question
      about it: "The default write quorum (`ATLAS_WRITE_QUORUM`) is 3" and "the
      orphan sweep (`chunk_reaper`) runs every 17 minutes", both cited to
      `field-notes.md`, 5 stages in 6.9s. The file held invented facts, so an
      answer could not have come from the model's own knowledge.
      The first attempt failed twice and both were real: the router judged the
      question out of scope before retrieval ran, because ROUTER_DOMAIN
      described the FastAPI corpus and every namespace was handed it; and the
      stored source was the server's temp directory, so the citation read
      `/var/folders/nt/.../atlas-upload-g154heox/field-notes.md`. Fixed in the
      same commit. See DECISIONS 2026-10-13.
- [x] An outsider follows README from clone to first answer in < 15 minutes —
      **demonstrated end to end 2026-10-13, about 3.5 minutes, Rs.0.18.** Done
      by being the outsider: a real clone of public `main`, then every
      documented step. Measured: clone 1.3s, `make install` 59s,
      `make docker-up` 13s to healthy, `make fetch-corpus` 55s/155 files,
      one-page ingest 8s (Rs.0.01), API healthy 10s, query 7s (Rs.0.17) —
      about 2m 33s of machine time plus the minute spent pasting a key. The
      answer carried faithfulness 1.0 and citations resolving to the page
      indexed two steps earlier. The audit that got here (`212157c`) found the
      quick start could never reach an answer at all and that `make docker-up`
      had been failing for everyone, so the criterion was never close to
      passing on time -- it was failing on structure.
- [x] 300+ tests, still ruff/mypy clean — **656 tests**, 93.38% coverage
      against a `--cov-fail-under=90` floor the gate defends (2026-10-14;
      before that the figure was printed and never checked), ruff and mypy
      strict both clean, and since 2026-10-10 all three are checked by CI
      rather than asserted from one laptop. Met well before M4
      was opened, so this is the one M4 criterion that came free; the two
      above it are the actual work.

The last of these three was earned on 2026-10-13 and the milestone was marked
on 2026-10-14, the same met-but-unticked gap M2 carried — recorded rather than
tidied away, because it is the second time it has happened.

**Most of M4's *scope* was not built, and the milestone is still done.** The
scope paragraph above lists key management UI, a usage page per key, dataset
upload for per-corpus eval, layout-aware PDF parsing and evidence export as
JSON; none of those exist. The exit criteria are what close a milestone here,
and they were chosen to mean "a second person could use this without you in
the room" — a corpus they can build from a browser, a README that gets them
to an answer, and a suite that defends the whole thing. Those are met and
measured. The unbuilt scope items are features, not gaps in that claim, and
they are the strongest candidates for an M5.

## M5 — Operable by whoever is on call  🟡 opened 2026-10-24

**Goal:** The person running Atlas can see what the keys are doing and stop
one, without a terminal and without editing the key store by hand. M4 asked
whether a second person could *use* it; this asks whether a second person
could *operate* it.

Picked from the unbuilt-M4-scope list above rather than from *Parked*: the
parked items are research directions and this is the gap that a live service
with real keys actually has.

Exit criteria:
- [x] A key can be revoked, and the revoke is shown to produce a 401 —
      **done 2026-10-24, ₹0.** `is_active` existed in both key stores and
      `lookup_key` honoured it, and **nothing in the codebase could write
      it**: the only revocation was editing Firestore by hand, and the two
      tests that covered the branch set the field themselves. Now
      `list_keys` / `set_key_active` on the `KeyStore` protocol and both
      backends, `GET /keys` and `PATCH /keys/{key_id}` behind
      `X-Admin-Secret`, and `scripts/manage_keys.py list|revoke|restore`.
      Proven end to end over HTTP — mint, query, revoke, 401, restore, 200 —
      and the writer is mutation-checked: stop the UPDATE and three tests
      fail across both layers. See DECISIONS 2026-10-24.
- [ ] Per-key usage is visible without SSH or a script — the console shows
      the listing and the counters, and can revoke from there
- [ ] A query's evidence can be exported as JSON from the console — the last
      M4 scope item that is about the product rather than about operating it,
      kept here because it is the other thing that needs the console touched

Out of scope on purpose: dataset upload for per-corpus eval and layout-aware
PDF parsing, both on the M4 scope list. Neither is an operations gap, and
each is a milestone's worth of work on its own.

## Parked (not scheduled)

GraphRAG / RAPTOR; multimodal (ColPali); MCP tool exposure (that is
Sextant's job); fine-tuned embeddings — the labelled set M3 was going to
start producing now exists, at 16 samples, which is far short of the few
thousand pairs this needs.
