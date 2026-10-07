# Backlog

Unscheduled work. Move an item into a milestone file when it gets a slot.
Newest at the bottom of each section.

## Bugs

- ~~BM25 index shared across namespaces~~ fixed 00a682b (M1).
- ~~Stale chunks after a document shrinks~~ `prune_document()` after upsert (post-M1).
- ~~Console renders answers as raw markdown~~ both paths render bold/code/lists (post-M1).
- ~~Eval dataset labels fq-002 / fq-008~~ re-labelled (post-M1); fq-002 now
  points at `release-notes` — the only page in the corpus that states a
  Python floor (`index` only carries a badge). Not yet re-run.
- ~~`manifest.json` reported as an ingest error~~ unsupported extensions skipped (post-M1).
- ~~Reranker download on first request~~ the production image bakes the
  weights (`Dockerfile` step 7) and sets `HF_HUB_OFFLINE=1`, so a cold start
  loads from `/opt/hf` and never reaches the Hub (M2).
- ~~Eval metrics in README are placeholders~~ replaced with measured numbers (M1).
- **A streamed answer claims a faithfulness check it never ran.** The SSE
  `done` event hardcodes `"is_faithful": True` (`routes/query.py`, the
  success branch), on the path whose own module docstring says it "skips the
  faithfulness check because we don't have the full answer until the stream
  ends". The console happens to render `UNCHECKED` because no score arrives,
  so the UI is more honest than the API — but any other client reading the
  field is told a never-checked answer was verified. Observed live on
  2026-10-07 at atlas.hulage.in. This is the one field the project's whole
  claim rests on, so it must not assert what was not computed. Options, in
  order of preference: (1) send `is_faithful: null` and let clients render
  "unchecked"; (2) run the check once the stream completes and emit a second
  event; (3) drop the field from the streaming contract entirely. (1) is the
  smallest honest fix and matches what the console already shows.

## Debts

- `rank-bm25` scores every chunk in Python per query (O(N)). Fine to ~50k
  chunks; replace with Qdrant sparse vectors or Tantivy after that.
- ~~SQLite key store is single-node~~ `AUTH_STORE=firestore` on Cloud Run;
  SQLite stays the local default (M2).
- ~~Fly.io config~~ removed; `docs/deploy.md` is Cloud Run only (M2).
- ~~`console/README.md` is the Vite template default~~ replaced (M2).
- PDF loader is `pypdf` text-only; tables and multi-column layouts degrade.
- Cache is not invalidated on ingest (verify — exercise 08.1). Also the
  API loads the BM25 file once at namespace build; CLI ingest after startup
  is invisible until restart.
- ~~Eval script cannot apply `PipelineConfig.overrides`~~ `--set section.field=value` (post-M1).
- ~~No daily spend cap~~ `BUDGET_DAILY_USD` → 429 + Retry-After (post-M1).
- ~~Streaming errors after first byte become events; document the event
  schema in `docs/api.md`.~~ **Shipped 2026-09-29, Rs.0.** `{"type":"error",
  "error":…,"stage":…}` plus the `[DONE]` sentinel, which the success path
  was also missing, so all three endings now agree. The failed request is
  charged for what it spent — the same hole the non-streaming path had until
  2026-09-28. `docs/api.md` gained the full event table; it had been
  documenting `{"delta": "..."}`, a shape the server stopped sending some
  time ago, and no stage events at all. Console handles the event and, more
  importantly, handles a stream that ends with neither `done` nor `error` —
  a dropped connection, which no server change can announce.
- ~~**The grader reads a third of the window it is judging.**~~ **measured
  2026-09-28, and the slice was right.** Grading all 15 instead of the top 5
  cost 0.060 context recall and 0.033 faithfulness; precision and answer
  relevance did not move. The entire recall loss was `fq-006` and `fq-012`,
  the two multi-document questions.

  The mechanism the "fix" had backwards: a grader shown a slice is
  pessimistic, pessimism triggers a retry, and since the retry union shipped
  on 2026-09-27 a retry *accumulates* context. The narrow window is how a
  five-document question ends up with five documents. Reverted to 5,
  `grader.context_chunks` keeps the knob, `--set grader.context_chunks=15`
  re-runs the experiment. See DECISIONS 2026-09-28.

  Left open by this: the retry is doing retrieval work that retrieval should
  arguably be doing directly, and it only fires when the grader happens to
  be pessimistic about a slice. If multi-document questions need more than
  one window, the honest fix is in `_retrieve_all`, not in how much the
  grader is allowed to see.

- ~~**`total_tokens_used` counts only the generation call.**~~ **Shipped
  2026-09-28.** Counting now happens on the provider, per model, inside a
  scope: `atlas/usage.py`. A report carries `token_usage` per model with an
  estimated cost; the `/query` response and the daily spend cap carry the
  whole request rather than its generation call. The same defect was
  charging the cap about half of what a request cost. See DECISIONS
  2026-09-28. **Every rupee figure recorded before that date is
  generation-only**; the next paid run prints the real one.

- **An exception mid-stream on `/query` truncates the SSE body silently.**
  No error event, no status change — the client sees the stream stop and has
  no way to tell a finished answer from a dead one. Found while testing the
  streaming spend path: the fixture's grader was not awaitable and the
  response simply ended at stage 4, with every assertion about the earlier
  stages still passing. The fix is an `{"type":"error"}` event plus a log,
  which is small; the reason it is filed rather than done is that it wants
  its own test for each stage boundary.
- ~~**Cap and rerank the sub-query merge.**~~ **Shipped 2026-09-27.**
  `_retrieve_all` now round-robins across sub-queries and cuts back to one
  window, re-ranked against the original question when a reranker exists.
  Both halves went in together because they are the same decision: the cap
  without the rerank would have truncated in sub-query order and deleted the
  later sub-questions outright. Precision 0.3412 -> 0.3762, recall unchanged,
  tokens -19%. See DECISIONS 2026-09-27.

- ~~**The `--dataset` default is a trap.**~~ **fixed 2026-09-28.** The flag
  is required on both `run_eval.py` and `eval_retrieval.py`, and the error
  lists what is in `eval_data/`. Pointing the default at
  `fastapi_dataset.json` would have moved the trap, not removed it: which set
  is right depends on what was ingested. On top of that the dataset is now
  checked against the namespace's own BM25 index before the pipeline is
  built — zero labelled rows resolving is a hard error, some resolving is a
  warning naming the rows. `eval_retrieval.py` also had the ordering wrong
  and loaded the cross-encoder before reading the dataset; fixed.

- ~~**Make the comparator refuse two different datasets.**~~ **done
  2026-09-28.** `compare()` raises `DatasetMismatch` on differing sample ids
  (derived from `sample_results`, so it works on the twelve stored reports),
  on a differing `dataset_fingerprint`, and on a differing `dataset_name`.
  The fingerprint is the one that matters: it catches a *relabelling*, which
  neither the file name nor the sample ids do, and which is exactly what the
  2026-09-27 audit did to every number recorded before it. A report written
  before the field existed carries an empty fingerprint and gets an
  **Unverified** note under the table rather than a refusal.

  The module docstring had claimed this check existed since M1. It did not.
  See DECISIONS 2026-09-28.

- ~~Relabel `fq-012`~~ **done 2026-09-27.** One document → five, one per
  claim its ground-truth answer makes. STATUS, README and DECISIONS restated
  from an offline replay of all twelve stored reports; the headers' recall
  gain and the "last outright miss" framing were both withdrawn.

- ~~Re-read the other fourteen labels for the same fault.~~ **done
  2026-09-27.** Nine of fifteen rows needed a change; see DECISIONS for the
  table and `metadata.label_rationale` on each row for the reason. Every
  figure in STATUS and README restated from an offline replay, Rs.0.

- ~~**The set has no out-of-scope row, so the refusal path is
  unmeasured.**~~ **Added 2026-09-29, Rs.0.015.** `fq-016`, a Stripe webhook
  signature question — a hard negative, because `advanced/openapi-webhooks.md`
  exists and its worked example is named `new-subscription`, so retrieval
  returns a confident-looking wrong page rather than nothing. Absence
  verified by grep (`stripe` 0, `billing` 0, `signature verif` 0). Both
  fingerprints changed, as they should. A router probe says the pipeline
  will **not** refuse it — `complex`, not `out_of_scope` — so the first run
  will score it 0.000 and correctness will read **0.6975**, predicted. See
  DECISIONS 2026-09-29. Successors below.

- **The baseline is broken and the next run resets it.** Every report in
  `eval_data/reports/` was measured on the fifteen-row set. The comparator
  will refuse to diff any of them against a run made from today, which is
  correct. Worth doing at the next paid pass: re-measure once, label the
  report clearly as the new baseline, and say in STATUS which column is
  which. Until then the 2026-09-28 numbers stand as the last comparable set
  among themselves.

- **The router does not treat a Stripe question as out of scope**, though
  its own `domain` string names the boundary. It returned `complex`. The
  same "When in doubt, prefer 'simple'" sentence that misrouted `fq-012` is
  the likely cause, now visible in a second, different way. **Deliberately
  not fixed yet:** the last router-prompt fix looked just as obvious and
  measured at exactly zero, so this waits on the next full run confirming
  the prediction above before anything is touched.

- ~~Guard against the fault the audit found, in the dataset loader.~~
  **done 2026-09-27**, `atlas.evaluation.dataset`. Every label must resolve to
  something `doc_match` could actually match — the checker builds its key set
  the same way the matcher does, so the two cannot drift — and a row with an
  empty `relevant_doc_ids` must carry `metadata.out_of_scope: true`.
  `category: "out_of_scope"` deliberately does not count: `fq-015` carried
  exactly that string while being answerable, so the category was the thing
  that was wrong. `EvalDataset` gained a `corpus_root` field so a dataset says
  what its paths are relative to; without one the resolution check is skipped
  and says so, because skipping quietly is how this survives. Wired into
  `run_eval.py` (before the pipeline is built, so a broken dataset costs
  nothing), `eval_retrieval.py` and `replay_context_metrics.py`; override with
  `--corpus`, bypass with `--allow-broken-dataset`.

  It found one on the first run: `oos-001` in `sample_dataset.json` was
  genuinely out of scope and had never said so. Declared.

  Still not caught, and still needs a person: a label set that is *incomplete*
  (`fq-012` named one real page of five) and a reference answer that names
  things the corpus lacks (`fq-010`). Both resolve fine.

- ~~**Add a correctness metric, or say in the README that there isn't
  one.**~~ **Shipped 2026-09-28** — both halves. `AnswerCorrectnessMetric`
  grades the generated answer against the reference (facts present, missing
  or contradicted; a contradiction costs twice an omission), and the README
  states that no correctness *number* exists yet. **Wired but never run: a
  first figure costs a full eval pass.** Reference answers are fingerprinted
  separately from the rest of the dataset, because only this metric reads
  them. See DECISIONS 2026-09-28.

- ~~**Run the harness once with the correctness metric in it.**~~ **Done
  2026-09-28, Rs.5.92:** correctness **0.7440** against faithfulness 1.0000,
  and the first true cost figure — 167,740 tokens, 4.3x what was being
  reported. See DECISIONS.

- ~~**A superseded fact in a reverse-chronological document outranks the
  current one.**~~ **Diagnosed 2026-09-29, Rs.0 — the premise was wrong.**
  The current chunks were never retrieved, so nothing about ranking or
  ordering was ever going to fix `fq-002`, and no chunk in the corpus states
  the current Python floor at all. The row needs aggregation, not retrieval.
  A real but small bug turned up underneath it (`heading_trail` dropping the
  release heading from a flat changelog) and is fixed. See DECISIONS
  2026-09-29 for the forensics. What it leaves open is below.

- **Nothing in the corpus states the current state of a changelog, and
  nothing derives it.** `fq-002`'s answer exists only as a subtraction over
  three entries 3,100 lines apart. Two shapes of fix, both real work:
  *(a)* at ingest, synthesise a "current state" chunk per changelog — an LLM
  pass over the file, corpus-shaped, and it re-prices the ingest; *(b)* at
  query time, let the pipeline scan a document rather than retrieve from it,
  which is a second retrieval mode and touches `_retrieve_all`. Neither is
  worth starting before something else in the dataset needs the same
  capability — as of now `fq-002` is the only row that does, which is an
  argument for leaving it scored 0.000 and honest.

- **Should the generator date a claim it takes from a changelog?** Now
  possible, since the release heading reaches the chunk text. One line in
  the generator prompt would turn "FastAPI requires Python 3.8 or above"
  into "as of 0.104.0 (2023-10-18), ...". It would not raise `fq-002`'s
  correctness — the reference says 3.10 — but it would move the judge's
  verdict on that fact from *contradicted* to *missing*, which is the exact
  distinction the metric was built to draw, and it stops the deployed site
  stating a stale fact in the present tense. Costs one eval pass (~Rs.6) to
  measure, and should not ship unmeasured.

- ~~**`fq-012` retrieves the wrong pages and then answers them
  faithfully.**~~ **Diagnosed 2026-09-29, Rs.0 — it is a routing failure.**
  The router called it `simple`, so the decomposer never ran (`decompose`
  appears on 3 of 15 rows, and not on either multi-document row). Probing
  the local BM25 index, two sub-queries take the row from chunk-precision
  0.0667 / doc-recall 0.200 to 0.6667 / 1.000, on BM25 alone. The corpus can
  answer this; the query as written cannot reach it. See DECISIONS
  2026-09-29. Successors below.

- ~~**The router is told to prefer `simple` when in doubt, and does.**~~
  **Closed 2026-09-29, Rs.0.023 — the fix does nothing.** The router does
  say `simple`, but running the decomposer on `fq-012` anyway returns three
  paraphrases that all still lead with "Pydantic", and retrieving on them
  reproduces the live numbers exactly: chunk-precision 0.1333, doc-recall
  0.400. The prompt edit would have cost Rs.6 for a zero delta. Cause is in
  the decomposer's own prompt — it splits a question, it does not translate
  one, so every shard inherits the vocabulary that was already missing the
  target. See DECISIONS 2026-09-29.

- ~~**HyDE, now the only candidate left standing on `fq-012`.**~~ **Built
  2026-09-29, Rs.0 — unmeasured.** `HYDE_ENABLED=false` by default;
  `--set hyde.enabled=true` turns it on, `--set hyde.mode=replace` runs the
  paper's variant instead of the default concat. One extra LLM call per
  retrieval query, expanded inside `_retrieve_all` so a grader-driven retry
  gets the same treatment as the first attempt. `timings.hyde_ms` and
  `hypotheses` are on the response, so a search run on text the caller never
  wrote is still debuggable. **Nothing is measured yet** — building it is not
  evidence it works, and the last two interventions aimed at this row both
  measured at zero. The pass that measures it is below.

  Original entry, kept because it is the argument: The
  sub-query that hit 5/5 labels — "add Query and Path constraints to
  singular values" — reads like a sentence from the answer, not a narrower
  question, and the only reason I could write it is that I had read the
  labels. Generating a plausible answer and retrieving with that is HyDE.
  Its competitor (decomposition, via the router) was measured on
  2026-09-29 and moves this row by zero, which is a stronger argument for
  HyDE than the original paper is. Cheap to build: the hypothetical comes
  from the same model already on the critical path, one extra call, and it
  can go behind a config flag so `--set` re-runs the experiment. Price a
  measured pass at ~Rs.6 plus the extra call per row.

- **Measure HyDE, and re-establish the baseline, in one pass.** Both are
  now unavoidable and they are the same run: adding `fq-016` moved both
  dataset fingerprints on 2026-09-29, so every stored report is already
  incomparable with anything run after it and a fresh baseline has to be
  paid for regardless. Running it twice — once bare, once `--set
  hyde.enabled=true` — costs roughly Rs.6 for the baseline plus the HyDE
  pass's extra call per retrieval query, and answers three questions at
  once: what the new 16-row baseline is, whether HyDE moves `fq-012`, and
  whether the correctness prediction of 0.6975 (the router answering
  `fq-016` instead of refusing it) holds.

  Three predictions worth writing down before paying, because a prediction
  made afterwards is not one. (1) `fq-012` doc-recall rises from 0.400;
  this is the whole thesis and the only row HyDE was built for. (2)
  Precision falls somewhere, because a probe retrieves pages about the
  topic rather than pages answering the question, and the corpus has many
  of the former. (3) `fq-016` gets *worse*, not better: the router already
  calls it `complex`, and asked to write a passage about verifying a Stripe
  webhook signature the model will write a confident one, which is a
  stronger pull toward `advanced/openapi-webhooks.md` than the bare
  question was. If HyDE nets positive it will be by trading (2) and (3)
  against (1).

- ~~**Verify what is actually in an index.**~~ **done 2026-09-28**,
  `scripts/verify_index.py`. Reads both halves of every namespace and compares
  chunk counts, chunk ids, content hashes, and header coverage against what
  `chunking.context_headers` asks for. Read-only and free, so it can run
  before and after every ingest. Found a half-finished ingest on its first
  run; see DECISIONS 2026-09-28.

- ~~**Nothing stopped a deploy from baking a stale index.**~~
  **fixed 2026-09-28.** `deploy_gcp.sh` runs `verify_index.py` over every
  namespace under `data/index/` before `gcloud builds submit` and refuses on
  a mismatch. Gates the build rather than the deploy, because `SKIP_BUILD=1`
  cannot see inside an image built earlier and says so. `SKIP_VERIFY=1`
  overrides, loudly.

- ~~**A single file ingest baked the whole path into its context headers.**~~
  **fixed 2026-09-28.** `scripts/ingest.py` and the `/ingest` route default a
  bare file's source root to its parent instead of passing `None`;
  `index_directory` gained a `source_root` override for re-indexing a subtree
  of a corpus rooted higher up; `--source-root` and an always-printed
  `Source root:` line make the choice visible. The real hazard was not the
  wasted tokens but the `content_hash` change: a re-ingest of one file gave
  it headers its neighbours lacked. Also fixed `seed_demo.py`, which passed a
  directory to `index_path` and raised before indexing anything.

- ~~**Nothing retried a Qdrant fault, and the client had no timeout.**~~
  **fixed 2026-09-28.** `QdrantConfig.timeout_seconds` (default 60) is passed
  to every `AsyncQdrantClient`; before this qdrant-client handed httpx no
  timeout at all, so the default was 5s. `is_transient_qdrant_error` plus a
  tenacity ladder now covers the write path (5 attempts, 1-20s) and the query
  path (3 attempts, 0.5-4s). The retry sits on the private single-call methods
  so a resend never repeats an upsert batch that already landed.

- **Ship the context headers to the `default` namespace — PARTIALLY DONE and
  currently inconsistent.** Cost approved 2026-09-27; the auto-mode classifier
  refused the write to the live collection, correctly, so the user runs it.
  The 2026-09-28 run landed 3950/4020 sparse chunks but only 2090/4020 dense,
  leaving 1860 content hashes differing between the two halves — a mismatched
  hybrid serving production now. Re-run the same ingest; the content-hash
  dedupe means only the ~1930 missing dense chunks are re-embedded, so it is
  roughly Rs.3.10 rather than Rs.6.45. Confirm with `verify_index.py` before
  deploying. Two steps, and the order matters:

      cd <repo root> && .venv/bin/python scripts/ingest.py data/corpus/fastapi --namespace default
      cd <repo root> && ./scripts/deploy_gcp.sh

  **Re-ingest first, deploy second.** The BM25 index is baked into the image
  (`Dockerfile:34`, `ATLAS_INDEX_DIR=/app/data/index`), so the ingest has to
  rewrite `data/index/default/bm25_index.json` *before* the build copies it.
  Between the two steps production runs headers in the dense index, which is
  live the moment the ingest finishes, against the old sparse index — a
  mismatched hybrid until the deploy lands.

  Rollback without re-embedding is only partial: the pre-header BM25 file is
  kept at `data/index-backup/bm25_index.json` (gitignored, and outside the
  path the image bakes), but the dense vectors are overwritten in place. A
  full revert is `CHUNK_CONTEXT_HEADERS=false` plus another ~Rs.6.45 ingest.

- **The live site takes ~36 s to answer its first request.** Reported
  2026-09-29 as "atlas.hulage.in is just loading", and it is real: a cold
  `/` timed out at 30 s with zero bytes, `/health` then took 6.2 s, and
  every request after that was fast (`/` 0.43 s, `/app` 0.15 s, all three
  bundles 200). Nothing is broken — both pages render and the console logs
  no errors.

  Cloud Run `atlas-api` has no `minScale` annotation, so it scales to zero
  and the container is gone about fifteen minutes after the last visitor.
  The app itself is not the problem: the startup log puts `atlas_startup` →
  `atlas_ready` at **2.9 s**. The other ~33 s is everything before Python's
  first log line — image pull and importing torch and transformers. The
  image is ~2.15 GB because the reranker weights are baked in, which was the
  right call for query latency and is what makes the first boot slow.

  Options, and neither is mine to run:
    - `--min-instances=1`: removes the cold start entirely. Idle billing on
      1 vCPU + 2 GiB is roughly **Rs.650-700/month**, standing, which is a
      lot for a portfolio site.
    - A ping every ~10 minutes to keep one instance warm. Cloud Run bills
      CPU only during requests, so ~4,300 pings/month of a few hundred ms
      sits inside the free tier — call it **Rs.0-20/month**. Cloud Scheduler
      is not enabled on the project yet. This is the cheap answer.
  Doing nothing is also defensible for a demo, as long as the README says
  the first load is slow instead of leaving a visitor watching a spinner.

- ~~**Re-check Artifact Registry size.**~~ **Checked 2026-09-29, Rs.0: 2,196
  MB**, down from 4,342 MB. The cleanup policy is doing its job — `keep
  recent 3` plus `delete older than 7 days` leaves four images
  (`25058e6`, `e095c7b`, `6443bb6` from 09-23 and `d21a922` from 09-27),
  sharing layers. Nothing to do.

- **Production is 17 commits behind `main`.** The live revision
  `atlas-api-00008-v9g` runs image `d21a922` ("give every chunk its source
  path and heading trail", 2026-09-27). Everything since is unshipped,
  including the spend-cap fix — so **the deployed cap is still being charged
  the generation call alone and admitting roughly twice its budget**. The
  user runs deploys.

- ~~**Both error paths hand the client `str(exc)`.**~~ **Fixed 2026-09-29,
  Rs.0.** `_public_error()` returns one fixed sentence naming the request
  id; the full exception and its type go to the log under that same id. Both
  paths moved together, because the SSE event had copied the 500's leak on
  purpose for consistency. `stage` survives redaction (one word, fixed set,
  and the field that makes the failure card useful) and `request_id` is in
  the event body as well as the header. See DECISIONS 2026-09-29.

  Original entry: The non-streaming 500
  puts it in `detail` and, as of 2026-09-29, the streaming `error` event
  carries the same string — deliberately, so the two agree. Whether a public
  deployment should be returning raw exception text at all is the open
  question: a Qdrant client error can carry a host, and a provider error can
  carry a request id or a fragment of configuration. The shape of a fix is a
  single helper both paths call, returning a short public message plus the
  `X-Request-ID` already on every response, with the detail left in the log.
  One decision, one convention, both endpoints.

## Ideas (research-backed, see learning/09)

- ~~HyDE retriever behind a config flag~~ built 2026-09-29, off by default,
  not yet measured.
- Contextual retrieval at ingest (LLM-written chunk context).
- ~~BM25 tokeniser: keep identifiers, split camelCase~~ shipped cb4e28d;
  measured neutral end to end, see DECISIONS 2026-09-23.
- ~~Rerank top_k 5 → 10–15~~ shipped 6443bb6 at 15; recall 0.778 → 0.900.
  The **lost-in-the-middle ordering** half is still open and matters more now
  that the window is three times wider.
- Local embedding model option (bge-small / e5-small) for zero-cost dev.
- Parent-child chunks: retrieve small, hand the LLM the parent.
- Unanswerable-question samples in the eval set to measure refusal.
  **Now cheap:** refusals are detected and excluded from faithfulness
  (2026-09-24), so such samples would score the refusal rate directly
  instead of poisoning the mean.
- Citation precision metric: does the cited chunk support *that* sentence.
- Console: per-key usage page; ingest-from-console with progress events.

## Nice to have

- `make demo` — seed a tiny corpus and open the console.
- Keyboard shortcut cheat-sheet in the console (`?`).
- Export a query's full evidence as JSON from the Evidence pane.
