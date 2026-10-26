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

- ~~**`compare()` calls a winner without reading latency or cost.**~~ **done
  2026-10-09.** It builds a `budget` list beside the metric deltas — warm p50
  and p95 from per-sample `stage_ms`, run cost from per-model `token_usage`
  priced by `atlas.cost` — checks each against both its ceiling and its
  regression allowance from `planning/BUDGET.md`, and on a breach renders
  **Overall winner: withheld** with the breach named and a pointer to the
  DECISIONS entry a breach needs. Percentiles come from
  `reporter.percentile`, now public for that reason, so a change is judged on
  the number its own report prints. 18 tests; `comparator.py` at 100%.

  Writing it found two defects in BUDGET.md: the accepted figures were
  interpolated percentiles where the project's reporter is nearest-rank
  (p50 10,062 → 10,053, p95 16,859 → 17,072 — inside the ceilings either
  way), and the `decompose` stage had no sub-ceiling at all. Both corrected.

  **Still open, and the reason cost/query stays hand-checked:** `EvalResult`
  carries run-wide `token_usage` only. It is contaminated by the metric
  graders' own calls — ~7.8 chat calls a sample against production's ~4 — so
  it cannot be divided by sample count to get a production cost per query.
  The comparator therefore judges the *run* against the $0.100 run ceiling
  and the run-to-run regression, says so in its own output, and skips the
  cost line entirely when the two runs measured different metrics. Per-sample
  `token_usage` on `SampleResult` would close it; no stored report has it, so
  requiring it would have made the check unusable against every baseline on
  disk. Firm up the n=1 production figure the cheap way first: record it on
  the next eval run that happens for another reason.

  **Half done 2026-10-14.** `SampleResult.token_usage` now carries the
  pipeline's own calls, separated from the judges' by a nested usage scope
  and merged back into the run meter so the run-wide total is unchanged. The
  report prints **Cost per query** from it, naming what the judges added, and
  omits the line entirely on a report that predates the field rather than
  computing it from a total that means something else. **Still open:** the
  comparator consuming it — meaningless until two reports carry it, so it
  waits for the next two paid runs.

  Writing it found a real defect in `usage.counted()`: it folded the inner
  scope into the caller's meter only on success, so a call that spent its
  prompt and then raised contributed nothing. In `/query` that is the daily
  spend cap under-counting exactly the requests that went wrong. The merge is
  in a `finally` now.

  **Closed 2026-10-17.** Two reports now carry the field, so the comparator
  reads it: **cost per query** is a budget line checked against the $0.005
  ceiling and the +20% regression allowance, beside the run-cost line it does
  not replace. The part worth keeping is which samples count — a sample that
  dies partway has already paid for the calls it made, so averaging it in
  reports a query as cheaper than one costs. `stage_ms` is the test, because
  the pipeline records a stage when it finishes one. On the pair that
  prompted this, that is the difference between +4.7% and **+15.2%**.
- ~~**A streamed answer claims a faithfulness check it never ran.**~~
  **Fixed 2026-10-13.** Option (1) as filed: the `done` event now sends
  `is_faithful: null`. **Two sites, not the one filed** — the success branch
  and the `out_of_scope` early return, which asserted `true` for a canned
  refusal that grounds and cites nothing. Null is sent rather than the field
  omitted, because a missing key reads as `undefined` in JS, which is falsey
  and would flip the error to "not faithful". Verified harmless to the
  console: `strengthFrom()` returns "Unchecked" off a null *score*, so it
  never consulted this field on the streaming path — which is exactly why the
  UI was more honest than the API for six days. `docs/api.md` now states the
  field is always null there, and the non-streaming response is untouched
  (`QueryResponse.is_faithful: bool` is computed, and stays `bool`).

- ~~**A console upload into the namespace `ROUTER_DOMAIN` describes is refused
  before retrieval.**~~ **Fixed 2026-10-26.** Refused at the *write* instead,
  where the cause can still be named: both ingest endpoints return **409** for
  the described namespace, quoting the claim the router is given and saying
  which corpus to use instead. The condition is `RouterConfig.describes()` —
  the target is `domain_namespace` **and** `domain` is not `GENERIC_DOMAIN`.
  Keying it on the namespace name alone would have refused `default` on every
  checkout that never set `ROUTER_DOMAIN`, where the description claims
  nothing and so cannot be contradicted; a mutant that drops that half is
  killed by seven pre-existing tests. `scripts/ingest.py` bypasses the API and
  is untouched, which is how the described corpus is built.

  The console learns it without a failed request: `/namespaces/{ns}/sources`
  now carries `writable` and `description`, the corpus pane turns the drop
  zone and the server-path form off for a read-only sheet, and says which
  sentence it is protecting. A 409 that only arrives after the file is chosen
  is the same silence one step later.

  8 tests; five mutants each killed (refuse on name alone, refuse everywhere,
  guard dropped from `/ingest`, guard moved after indexing, `writable` pinned
  true). Not fixed here: uploads are still per-instance — the entry below.

  Original entry: Found 2026-10-25 by uploading a PDF through the console
  and asking about it: `1 stage · 987 ms`, `Routed out of scope`, nothing
  retrieved. The chain is `deploy_gcp.sh:118` setting
  `ROUTER_DOMAIN=the FastAPI web framework documentation`, `domain_namespace`
  defaulting to `default` (`config.py:103`), and `domain_for()` therefore
  handing the router that sentence for the one namespace the console uploads
  into. The router classified correctly against the description it was given;
  the description was false the moment a non-FastAPI document landed there.

  **This is the 2026-10-13 defect with a hole in its fix.** `domain_namespace`
  was added precisely so an uploaded corpus would not be refused for not
  being `ROUTER_DOMAIN`, and it works — for every namespace *except* the one
  named, which is also the console's default target. The guard protects
  everywhere the problem does not occur.

  Workaround, no code: upload to a new sheet. `domain_for()` returns
  `GENERIC_DOMAIN` for any other namespace and the router stays neutral.
  Proposed fix: refuse the upload when the target namespace is
  `domain_namespace`, naming the cause, rather than accepting it and failing
  silently at query time three steps later.

- **Console uploads are per-instance, so they are neither durable nor
  consistent.** Found 2026-10-25 while clearing uploaded PDFs. The dense half
  goes to Qdrant and persists; the sparse half goes to
  `sparse_index_path(namespace)` on the container's own filesystem
  (`namespaces.py:149`), which Cloud Run discards on recycle. With `max 2`
  instances an upload lands on **one** of them, so whether a document is
  keyword-retrievable depends on which instance serves the request.

  Observed directly: two PDFs uploaded in one session, both present in
  Qdrant, only one in the live container's source listing — the other
  instance had already recycled.

  Second consequence, worth stating because it bit this session: deleting a
  document's points from Qdrant does **not** remove it, because
  `BM25SparseIndex` stores `content` itself (`sparse.py:49`), not just term
  statistics. A keyword hit can still return the full chunk text from the
  surviving instance until it recycles. Clearing an uploaded document today
  means deleting from Qdrant *and* rolling a revision.

## Debts

- ~~**`/namespaces/{ns}/sources` can advertise documents the vector store does
  not have.**~~ **done 2026-10-19.** Took the first of the three options —
  cross-check the collection's point count on the read — because the other
  two either hide the disagreement or make the sparse side authoritative.
  `NamespaceRegistry.dense_chunk_count()` reads the collection's point count
  (absent collection → 0, unreachable Qdrant → `None`, never 0 for "could not
  read"), and the response carries `dense_chunks`, `consistent` and a plain
  `warning` beside the sparse `total_chunks`. The console threads the warning
  into the store and shows it twice: a triangle beside the totals in the top
  bar, where the phantom "155 sources / 4,020 refs" was read, and a banner
  above the source list. 9 new tests. The rejected shape was returning 0 for
  an unreadable count, which is the same silencing that produced the bug.

  Original entry: It reads the in-memory BM25 corpus, which is persisted
  separately from Qdrant, so the two can disagree — and when they do the
  console shows a populated corpus for a namespace that answers nothing.
  Found on 2026-10-13 with a local Qdrant holding only `atlas_quickstart`
  while the console cheerfully reported **155 sources / 4,020 refs** on
  `default`, because the sparse index on disk still held the full FastAPI
  corpus from earlier work. Harmless locally; in production it would mean a
  corpus listing that survives a collection being dropped or recreated. The
  endpoint's own docstring says the BM25 corpus "mirrors the dense index",
  which is the assumption, not a guarantee. Options: cross-check the
  collection's point count on this read, rebuild the sparse index from Qdrant
  at startup, or state plainly in the response that the number is the sparse
  side's.

- ~~**Turning the faithfulness check off would report a perfect score, not an
  absent one.**~~ **done 2026-10-19.** `FaithfulnessResult.score` /
  `.is_faithful` are now `float | None` / `bool | None`, and the disabled
  branch returns `None` for both. Two more instances of the same silencing
  turned up in the same file while widening the type and were fixed with it:
  the **refusal** branch returned `1.0`/`True`, which had the console award
  "Supported 1.00" — its strongest badge — to an answer that said it did not
  know, and that one was *live*, not a loaded gun; and
  `parsed.get("faithfulness_score", 1.0)` gave a perfect score to a judge
  whose JSON omitted the number it was asked for. The unparseable-judge
  branch deliberately keeps `0.0`/`False`: there an audit ran and failed,
  which a human should triage, rather than nobody having looked. Ripple:
  `PipelineResult.is_faithful` (was `True` when no check ran), the flag log
  now reads `is False` rather than `not` (so `None` is not warned about),
  `QueryResponse.is_faithful: bool | None`, the console's `is_faithful` type
  and `scripts/seed_demo.py`. `strengthFrom()` needed no change — it already
  rendered a null score as "Unchecked", which is now reachable. No config
  flag was added; the gun stays unloaded. 6 new tests, 692 passing.

  Original entry: `FaithfulnessChecker.check` opens with
  `if not self.enabled: return FaithfulnessResult(score=1.0, is_faithful=True,
  summary="check disabled")` (`orchestration/faithfulness.py:107`). Nothing
  reaches it today — `namespaces.py:156` constructs
  `FaithfulnessChecker(s.llm)` and never passes `enabled`, there is no
  `FAITHFULNESS_ENABLED` in config or `.env.example` — so this is a loaded
  gun rather than a live defect, which is why it is filed and not fixed. The
  moment someone wires a flag to it, **every answer reports
  `faithfulness_score: 1.0`**, and the console renders "Supported 1.00",
  because `strengthFrom()` only renders "Unchecked" when the score is *null*.
  That is strictly worse than the streaming bug fixed on 2026-10-13: there
  the UI stayed honest by accident, here it would be actively misled. The
  honest values are null, which needs `FaithfulnessResult.score` /
  `.is_faithful` widened to `float | None` / `bool | None` and the ripple
  checked through `QueryResponse.is_faithful: bool` and the eval metrics —
  not a three-line change, hence its own item. The refusal branch below it
  (`score=1.0` for `is_refusal(answer)`) is argued in a comment and is a
  separate question: a refusal asserting nothing is defensible, but 1.00
  still means "Supported" to the console for any refusal not classified
  `out_of_scope`.

- ~~**The offline faithfulness metric defaults a missing judge score to
  1.0.**~~ **done 2026-10-19.** The entry below prescribed the check, so it
  was run first: all 289 faithfulness rows in the 19 stored report JSONs were
  scanned for the two shapes the default can produce — a score over zero
  claims, and a 1.0 alongside claims the judge marked unsupported. **0 rows
  matched.** No stored report ever took the default, so **the published
  1.000 stands as measured** and no re-run is owed. (The third shape — a
  missing key where every claim *was* supported — needs no scan: there the
  default and the real computation both give 1.0.) The fix then: a missing
  `faithfulness_score` now **raises**, which the runner already records as
  `score=-1.0, applicable=True`, dropped from the mean and printed in bold
  by `_failed_counts`. A score over an **empty claims list** returns
  `applicable=False` — supported/total with total 0 is not a number the
  judge could have computed — matching `AnswerCorrectnessMetric`'s no-facts
  branch and counted by `_inapplicable_counts`. Both reuse conventions the
  harness already had; nothing new was invented. The refusal branch keeps
  `score=1.0, applicable=False`: `MetricScore.score` is a required `float`,
  so null would mean widening the pydantic model through reporter and
  comparator, and that branch is already excluded from the mean *and*
  published in the skipped counts, so it cannot flatter the headline. 2 new
  tests, 694 passing. Siblings checked in the same pass:
  `answer_relevance` and `answer_correctness` both fail a missing key to
  0.0, not 1.0. `grader.py:136` defaults to `0.5`, a midpoint rather than a
  flattering value, and is left alone.

  Original entry: `evaluation/metrics/faithfulness.py:117` reads
  `float(parsed.get("faithfulness_score", 1.0))`, so a judge that returns
  valid JSON without the number it was asked for scores that sample
  **perfect**. The inference-time checker had the identical line and it was
  fixed on 2026-10-19; this copy was left because it feeds a **published**
  number — the measured faithfulness **1.000** quoted in the README and in
  resume bullets — and changing how that number is computed should be a
  re-run with the before and after stated, not a silent edit buried in an
  unrelated commit. Cheap to settle: count how many samples in the stored
  report JSONs took the default. If none did, the 1.000 stands as measured
  and the fix is free; if any did, the number is wrong and needs saying so.

- ~~**The correctness judge's run-to-run spread is wider than the
  comparator's significance floor.**~~ **done 2026-10-21, ₹0.** Measured off
  the stored reports instead of paying for repeat runs, and the measurement
  corrected the entry below on two counts.

  *The title was wrong about the mechanism.* The judges are **deterministic**:
  across every paired row where the two runs produced byte-identical answer
  text, `answer_correctness` and `faithfulness` moved **0.0000**. The variance
  enters earlier — the *generator* writes a different answer from the same
  chunks, and correctness grades facts-present over a handful of facts, so one
  reworded sentence swings a row by 0.5. "Judge noise" was the wrong name for
  it.

  *The floor was wrong in both directions, not one.* One blanket 0.02 served
  five metrics with very different behaviour. Measured aggregate movement
  between reruns on identical evidence:

  | metric | measured | floor now | note |
  |---|---|---|---|
  | `context_precision` | 0.0000 | 0.01 | deterministic; floor is resolution, not noise |
  | `context_recall` | 0.0000 | 0.01 | same |
  | `faithfulness` | 0.0000 | 0.05 | **unvaried** — every observation was 1.00, so this is an assumption |
  | `answer_relevance` | 0.0020 | 0.01 | per-row jitter ±0.04 cancels in the mean |
  | `answer_correctness` | 0.0565 | 0.08 | three pairs only, hence the headroom |

  So 0.02 was ten times too lax for `answer_relevance` and three times too
  tight for `answer_correctness`. Re-running the comparison that prompted
  this, `baseline-17` vs `router-scope`, flips `context_precision` +0.0134
  from "ns" to a win and the overall verdict from tie to **B** — the gain was
  always real, because that metric has no rerun noise at all.

  `scripts/measure_noise_floor.py` is new and re-derives the table for free;
  it exits non-zero if any floor has fallen under its measured noise, so this
  cannot quietly rot. Two things it had to learn the hard way: a `-replayed`
  report is a corrected copy of one run and pairing it against its source
  reports the correction as noise (which put correctness at 1.0000 and would
  have set the floor from a bug fix — `replay_non_answer_metrics.py` now
  stamps `replayed_from` so this is detectable rather than a filename
  convention), and a metric that never left one value has to be printed as
  **unvaried** rather than deterministic, because those read identically in a
  column of zeroes and mean opposite things.

  Not fixed, and now clearer: a floor answers "is this bigger than a rerun",
  not "is this more than one sample". That +0.0134 precision win is one row,
  `fq-013`. The item below this one is the instrument for that question.

  Original entry: between `baseline-17` and
  `router-scope` — two runs where only `fq-013` and `fq-016` changed code
  path at all — `answer_correctness` moved on three rows that ran an
  identical pipeline over identical retrieved chunks: `fq-012` 0.50 → 0.00,
  `fq-014` 1.00 → 0.83, `fq-015` 1.00 → 0.88, totalling **0.79 points, or
  0.0494 of the 16-row mean**. The judge runs at temperature 0.0, so this is
  the model's own non-determinism, not a setting. The comparator calls a
  delta insignificant below **0.02**, which this evidence says is roughly
  half the real floor for this metric on this set, and it printed "Overall
  winner: A" off exactly that noise before the declined rows were replayed.
  Free to settle: run the same dataset twice with no change at all and read
  the spread directly (≈₹6.3 a run, so ≈₹12.6 for the pair), or compute it
  retrospectively from the stored reports that share a fingerprint. Until
  then, read any correctness delta under ~0.05 on this set as a tie whatever
  the table says.

- ~~**The comparator decides a winner from two means, when it has the paired
  per-sample scores to do better.**~~ **done 2026-10-21, Rs.0.**
  `atlas/evaluation/significance.py` runs an exact two-sided Wilcoxon
  signed-rank test over the paired per-sample scores, and `compare` now
  needs *both* gates: the delta clears the metric's rerun floor **and** the
  test rejects at alpha=0.05. Re-running `baseline-17` vs `router-scope`
  under it retracts the claim that prompted this entry — `context_precision
  +0.0134` is carried by one row of fifteen, where the smallest p the test
  can return is 1.000 — and the overall verdict goes back from **B** to
  **tie**.

  Three things the entry got wrong or did not foresee:

  - **`scipy` is not a dependency.** It is a transitive install under
    `sentence-transformers`. Importing it from `src/atlas` would have made
    the comparator — which ships inside the API image — depend on a
    reranker's private requirements. The test is implemented in-repo and
    checked against `scipy.stats.wilcoxon` in the suite, with scipy added to
    the `dev` extra so the oracle is declared rather than assumed.
  - **Ties are the common case, not a corner.** scipy's exact method is
    derived for distinct ranks; metric scores tie constantly. The
    implementation here conditions on the observed rank vector, which stays
    exact under ties, and the cross-check is restricted to tie-free input
    where both must agree to the last bit.
  - **"Not significant" was the wrong word for most of this dataset.** With
    n differing rows the smallest achievable two-sided p is 2^(1-n), so
    below six differing rows the test cannot reject however the rows fall.
    That is reported as **underpowered** in its own column and its own notes
    block, never as a tie: absence of evidence and evidence of absence are
    the distinction this whole line of work keeps rediscovering.

  Original entry: the comparator decided a winner from two means when it had
  the paired per-sample scores to do better; its own docstring had said
  since v1 that a proper significance test was the right instrument, and the
  measured noise floors answered "is this bigger than a rerun" and nothing
  about "is this more than one sample".

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

- ~~**An exception mid-stream on `/query` truncates the SSE body silently.**~~
  **The code was fixed earlier; the test gap this entry describes closed
  2026-10-13.** `_stream_query` emits an `error` event plus the `[DONE]`
  sentinel, logs before emitting, charges the cap for what the failed request
  spent, and re-raises `CancelledError`/`GeneratorExit` untouched. But the
  only failure test broke the stream at **grading** — *before* a single token
  of answer is sent — while the recovery's whole reason for existing is "an
  exception raised after the first byte cannot become a 500". The hard side of
  that boundary had no test. It does now: a generator that yields one delta
  and then raises must produce the partial text, an `error` event naming
  **generation** (the stage is read back off `status: "start"` events, so a
  missing announcement silently misattributes the failure), the sentinel, no
  `done`, and no leaked internals.
  **The fixture flaw in the original entry was still live, and worse than
  filed.** `tests/unit/api/conftest.py` left `_grader.grade` an auto-MagicMock,
  which is not awaitable, so **every streamed request in the suite died at
  stage 4 and became an `error` event**. An existing test comment already said
  so and worked around it locally. A shared fixture that cannot reach `done`
  makes every success-path assertion under it a comment — the same shape as
  the `importorskip` finding on 2026-10-12. The fixture now grades
  successfully by default; tests wanting the failure opt in with a
  `side_effect`, as `_break_at_grading` already did. Four of the seven new
  tests fail if that one line is reverted.
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

- ~~**The baseline is broken and the next run resets it.**~~ **done
  2026-10-17, ₹6.26** — `baseline-17_20261017-175634`, measured on the
  16-row set and named so the label says which column is which. The 24
  earlier reports in `eval_data/reports/` are the fifteen-row set and stay
  incomparable with anything after `fq-016`; the comparator refuses them by
  fingerprint rather than quietly diffing them, which is the behaviour this
  entry was relying on.

  Original entry: every report in `eval_data/reports/` was measured on the
  fifteen-row set, so a fresh baseline had to be paid for regardless.

- ~~**The router does not treat a Stripe question as out of scope.**~~
  **done 2026-10-19, ₹7.01.** Two changes, because the first one alone would
  have made the published numbers worse.

  *The prompt.* `out_of_scope` was defined as "clearly unrelated to the
  domain", which only ever catches a question about something else entirely —
  the lone example was "What is the capital of France?". The case that failed
  is the near miss, and the model said so itself: it called `fq-016` a pattern
  "documented in the FastAPI **ecosystem**". The definition is now about what
  a correct answer would have to be *about*, with a second example — exporting
  financial records to QuickBooks — that reuses the subject of the first
  simple example so the contrast is the scope rule rather than the topic, and
  names no product in any eval row. The "when in doubt prefer simple"
  tie-break is kept, because it exists for the 2026-10-13 over-refusal, and
  narrowed to subjects the domain plausibly owns.

  *The harness.* The run that proved the prompt works also showed the eval
  could not see it. The generator refuses with `REFUSAL`; the router refuses
  with the pipeline's own out-of-scope message, and all four readers of a
  refusal tested only the first string. `answer_correctness` scored `fq-016`
  **0.000** with the reasoning "the pipeline answered instead of refusing",
  `answer_relevance` averaged its 0.41 into the headline, and `faithfulness`
  audited "This question appears to be outside the scope..." as two supported
  claims and returned **1.0**. Making the router correct made three published
  numbers worse. Both strings now live beside each other with one predicate,
  `is_non_answer`, and a test asserts the pipeline emits the very constant the
  metrics check, since separate strings in separate modules is how they
  drifted apart silently.

  *Measured, not asserted.* `scripts/probe_router.py` is new — the router
  alone, 16 dataset rows plus 6 controls, ≈₹0.3 a run instead of ≈₹6, which
  exists because the last router-prompt change measured at exactly zero.
  Scope accuracy **19/21 → 21/21**, over-refusals **0 → 0**; the two it fixed
  are `fq-016` and an Amazon S3 question that appears in no prompt and no
  dataset, so the rule generalised rather than the answer being recalled. Full
  eval `router-scope_20261019-202434` against `baseline-17`: after replaying
  the three declined-row metrics for ₹0
  (`scripts/replay_non_answer_metrics.py`), the comparator says **tie** on
  every metric — correctness 0.7452 → 0.7583, relevance 0.8382 → 0.8380 over
  the 15 shared rows, recall 0.9378 unchanged — with **p50 latency −12.8%**
  because an out-of-scope query now skips the whole pipeline. `baseline-17`
  stays the published baseline; nothing in README or STATUS needed restating.

  One prediction from the entry below was wrong and worth recording: `fq-013`
  stopped decomposing as a side effect, which looked like a recall risk
  because it needs two pages. It kept recall 1.000 and its precision went
  **0.73 → 0.93**. Only two rows changed path at all, which is what made the
  rest of the diff readable as noise.

  Original entry: the router **does not treat a Stripe question as out of
  scope**, though its own `domain` string names the boundary. It returned
  `complex`. The
  same "When in doubt, prefer 'simple'" sentence that misrouted `fq-012` is
  the likely cause, now visible in a second, different way. **Deliberately
  not fixed yet:** the last router-prompt fix looked just as obvious and
  measured at exactly zero, so this waited on the next full run confirming
  the prediction above before anything was touched.

  **That run happened on 2026-10-17, so this is unblocked — and the
  prediction it was waiting on did not hold.** `fq-016` does score
  correctness **0.000** on `baseline-17` with recall 1.000, which confirms
  the router answering rather than refusing; but the aggregate correctness
  the prediction put at **0.6975** measured **0.7452**. The entry was right
  about the mechanism and wrong about the number, which is the same shape as
  the HyDE predictions scored below. Nothing here is paid work: the fix is a
  router-prompt change, and the honest way to judge it is against
  `baseline-17`, which now exists.

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

- ~~**Should the generator date a claim it takes from a changelog?**~~
  **Measured and shipped 2026-10-23, Rs.6.05 — it moves no metric, and the
  reason for trying it was wrong.** Rule 6 is in `_SYSTEM_PROMPT`. The text
  changed exactly as designed — `fq-002` now answers "**As of 0.104.0
  (2023-10-18),** FastAPI requires Python 3.8 or above [2]." — but the
  predicted *contradicted* → *missing* move did not happen: `0.0`,
  `1 contradicted`, **byte-identical judge reasoning** in both runs.

  The run's +0.1227 on `answer_correctness` belongs to four rows (fq-010,
  fq-012, fq-014, fq-016), **none of them changelog rows** — fq-016 is the
  router refusing where it answered last time, fq-012 the known routing
  flake. The comparator called a tie (4 of 16 paired rows differ, minimum
  reachable p = 0.125) and was right twice over.

  Kept on the half the suite does not score: the deployed site stops stating
  a three-year-old fact in the present tense. Faithfulness unmoved at 1.0,
  cost per query +1.5%. The p95 breach the comparator reported is an
  endpoint slowdown in the back half of the run, not the change — retrieval
  runs before generation and cannot see a system prompt. See DECISIONS
  2026-10-23.

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

- ~~**Measure HyDE, and re-establish the baseline, in one pass.**~~ **done
  2026-10-17/18, ₹18.80 across three runs. HyDE is closed: both arms
  measured, both rejected on the latency budget.** `concat` warm p95 +56.3%,
  `replace` +138.6% (40,778 ms), and head to head the two tie on all five
  quality metrics — so `replace` buys nothing `concat` does not. The
  comparator withheld the winner in both comparisons and the knob stays off.
  Full numbers in DECISIONS 2026-10-17 and 2026-10-18.

  **The three predictions this entry registered on 2026-09-29, scored.**
  They are scored here because they were written down, not because they
  were flattering — two are wrong and the third cannot be settled.

  1. *"`fq-012` doc-recall rises from 0.400; this is the whole thesis and
     the only row HyDE was built for."* **Wrong, and wrong in the direction
     that matters.** `fq-012` recall **fell to 0.200 in both arms**. The one
     row HyDE existed to fix is the row it broke, which is a cleaner verdict
     on the intervention than the aggregate was.
  2. *"Precision falls somewhere, because a probe retrieves pages about the
     topic rather than pages answering the question."* **Wrong.** Context
     precision **rose** in both arms — +0.0619 `concat`, +0.0845 `replace`,
     the largest single movement either run produced — and `fq-012`'s own
     precision rose under `replace` (0.1333 → 0.2000). The mechanism was
     backwards: a hypothesis written in documentation register *concentrates*
     the retrieved set rather than diffusing it. DECISIONS 2026-10-17 records
     the same error being made twice independently.
  3. *"`fq-016` gets worse, not better."* **Unsettled, and it cannot be
     settled from these runs.** `fq-016` scored the failure sentinel in both
     HyDE arms — an MPS out-of-memory in `concat`, "Request timed out" in
     `replace` — so it has no score to compare. Its baseline reading is
     correctness **0.000** with recall 1.000, which does confirm the earlier
     half of the prediction above it: the router answers `fq-016` rather
     than refusing it. The aggregate correctness that prediction put at
     **0.6975** measured **0.7452**.

  Original entry: Both are
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

- ~~**Ship the context headers to the `default` namespace.**~~ **done
  2026-10-17, ≈₹0.005** — `verify_index.py` reports `default` at **4020/4020
  on both halves**, 0 dense-only, 0 sparse-only, 0 differing content hashes,
  and header coverage 4020/4020 dense and sparse. The last gap was 4 chunks
  of `release-notes.md`, not the ~1930 this entry priced at ₹3.10: the
  indexer skips on `content_hash`, so the job cost 433 tokens. The matching
  deploy landed 2026-10-18 as `atlas-api-00014-5vp`, which is what put the
  baked BM25 half back in agreement with Qdrant. `headers` was brought level
  the same day and the three namespaces that had a sparse half and no dense
  one at all — `quickstart`, `field-notes`, `console-demo` — were deleted
  rather than shipped. See DECISIONS 2026-10-18.

  Original entry, kept for the ordering rule, which still holds — **re-ingest
  first, deploy second**, because `Dockerfile:34` bakes the BM25 index:
  PARTIALLY DONE and currently inconsistent. Cost approved 2026-09-27; the
  auto-mode classifier
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

- ~~**The live site takes ~36 s to answer its first request.**~~ **done
  2026-10-21, Rs.0.** Two parts of the entry were already out of date and
  the remaining 36 s is now measured rather than attributed.

  **Stale:** "Cloud Scheduler is not enabled on the project yet" — the
  `atlas-keepwarm` job (`*/10` against `/health`) has existed since
  2026-09-29, is ENABLED, and the scheduler log shows an unbroken run of
  HTTP 200s. Cloud Run recorded three container starts in two days, all
  deploys, none from scaling to zero. A normal visitor has not paid a cold
  start for weeks. "~2.15 GB" was the uncompressed size; what Cloud Run
  actually pulls is **554.6 MB** compressed.

  **Still real, and measured on rev `atlas-api-00017-x5r`:** instance start
  → Python's first log line **33.9 s**, then 2.9 s of startup, **36.9 s**
  total. That 33.9 s was one opaque block, so the entry had to guess what
  was in it. It is now split by `atlas_boot_profile`, printed from
  `atlas.api.asgi`, and measured in-container with the image already local:
  **12.41 s of it was the import graph**, leaving roughly 21 s of pull. The
  imports were a third of the problem and nobody knew.

  **Fixed, both halves:**
    - `LazyCrossEncoderReranker` defers torch, transformers and
      sentence-transformers until something reranks, and the lifespan warms
      the model behind the bound port. Only `/query` needs it; the landing
      page and the console never did. In-container import cost **12.41 s →
      2.55 s**, with the model finishing 8.1 s later in the background.
    - The final `chown -R atlasuser /app /opt/hf` was **81.9 MB of the
      554.6 MB image**: chown rewrites every inode, so the whole baked-
      weights tree shipped twice. Ownership is now set as files are created
      and that layer is gone — 73.7 kB and 20.5 kB in its place.

  **Measured in production on rev `atlas-api-00018-zfc`: 36.9 s → 11.7 s**
  (instance start → `atlas_ready`), against a predicted ~26 s. Two things in
  the prediction were wrong and the deploy is what showed it:

  - **There is no ~21 s image pull.** `pull_and_interpreter` came back at
    **0.72 s**, and only ~0.64 s passed between "Starting new instance" and
    the process forking. Cloud Run streams image blocks on demand rather
    than pulling the whole image first, so the old 33.9 s was almost
    entirely the torch import graph, not pull. The in-container figure that
    suggested otherwise was measured on a warm local image, where no
    streaming happens — the split it implied was an inference and the
    inference was wrong. The 81.9 MB layer fix is still right; it is just
    not where the seconds were.
  - **The background warm does not run on Cloud Run.** The service uses the
    default request-scoped CPU allocation (no
    `run.googleapis.com/cpu-throttling: false`), so a thread loading the
    model between requests gets almost no CPU. `atlas-api-00018-zfc` served
    three requests in 4.6 minutes and never logged
    `reranker_loaded_lazily`, for a load that takes 8.08 s on a host with
    continuous CPU. Fixed by `POST /warm`, which does the load inside a
    request — the only time CPU is allocated — with `atlas-keepwarm`
    retargeted from `/health` to `/warm`. It is a separate route because a
    health check that blocks for twenty seconds once per cold start is a
    health check that trips alarms.

  `--min-instances=1` stays rejected at Rs.650-700/month standing for a
  portfolio site.

- ~~**Re-check Artifact Registry size.**~~ **Checked 2026-09-29, Rs.0: 2,196
  MB**, down from 4,342 MB. The cleanup policy is doing its job — `keep
  recent 3` plus `delete older than 7 days` leaves four images
  (`25058e6`, `e095c7b`, `6443bb6` from 09-23 and `d21a922` from 09-27),
  sharing layers. Nothing to do.

- ~~**Production is 17 commits behind `main`.**~~ **done** — twice. The
  spend-cap fix this entry was actually about shipped on 2026-10-07 as
  `atlas-api-00011-xcm` / image `58e4e00`, and the drift that reopened
  afterwards closed on 2026-10-18 as **`atlas-api-00014-5vp` / image
  `ac132a9`**, which carried 23 further commits plus the corrected BM25
  index. Production and `main` agree.

  Original entry: the live revision `atlas-api-00008-v9g` ran image
  `d21a922` ("give every chunk its source path and heading trail",
  2026-09-27). Everything since was unshipped, including the spend-cap fix —
  so **the deployed cap was still being charged the generation call alone
  and admitting roughly twice its budget**. The user runs deploys.

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

- ~~**`pytest.importorskip` hides four tests behind an optional extra.**~~ Fixed 2026-10-12.
  `tests/unit/api/test_keystore.py:117` gates the `firestore_store` fixture
  on `importorskip("google.cloud.firestore_v1")`, so all four
  `TestFirestoreKeyStore` tests skip when the `gcp` extra is absent — which
  is exactly what CI's first run did on 2026-10-12, silently, while two
  neighbouring tests that import `google.cloud` at module level failed loudly
  and got the attention. `make install` now installs `.[dev,gcp]`, so they
  run; nothing *pins* that. Drop the `importorskip` and let the import fail,
  or assert the extra is present in a conftest check: Firestore is the
  production key store, so a skip there is not a graceful degradation, it is
  the gate declining to test shipped code. The generalisable half: an
  optional dependency plus `importorskip` reports success for code it never
  ran, and the test count stays reassuring either way (583 both ways; only
  the skip line moved).
  *Done:* the `importorskip` is gone and `test_the_gcp_extra_is_installed`
  pins the requirement in one line, because the alternative symptom is
  illegible — `log_usage` catches every exception, ImportError included, and
  logs `usage_log_failed` at warning level, so a missing extra shows up only
  as `assert 0 == 2` in `test_usage_counters`. Verified by blocking
  `google.cloud` at import: 0 skipped, the pin fails naming the module, and
  the other three tests pass because they never needed google — only
  `log_usage` does, via `Increment`. 584 tests.

- ~~**`tiktoken` is a declared dependency that nothing imports.**~~
  **Removed 2026-10-14.** Proved rather than grepped: with a module that
  raises on `import tiktoken` ahead of it on `PYTHONPATH`, all 644 tests
  passed, so nothing reaches it by any name. Original entry follows.
- ~~**`tiktoken` is a declared dependency that nothing imports.**~~ **done
  `eae63f0`** — dropped from `[project.dependencies]`; `grep -c tiktoken
  pyproject.toml` returns 0. It was residue: token counts come from the
  provider's reported usage, which is also what `usage.py` prices against.

  Original entry: found while auditing what CI would download (2026-10-10).

- ~~**The `gcp` extra is never type-checked.**~~ **This entry was wrong**,
  filed 2026-10-10 and withdrawn 2026-10-12. It rested on `.venv/bin/pip
  list` returning nothing for Firestore — but this venv was built by `uv`,
  which installs no `pip` shim, so the command never ran and its failure was
  hidden behind a `2>/dev/null`. `python -m pip list` shows
  `google-cloud-firestore 2.31.0` installed with full metadata, and mypy has
  therefore been strict-checking the real Firestore types all along, green.
  What was *actually* wrong is now fixed: `make install` asked for `.[dev]`
  while the local venv carried `[gcp]`, so CI's first run failed
  `test_spendstore.py::TestFirestore` on `ModuleNotFoundError: No module
  named 'google.cloud'`. `make install` now installs `.[dev,gcp]`. The
  lesson is the method, not the dependency: **a check whose own failure is
  silenced reports whatever you expected.**

- ~~**`fetch_corpus.py` writes a `commit_sha` it never reads.**~~ Fixed 2026-10-12. The manifest
  records which FastAPI commit the 155 markdown files came from, but the
  fetcher always pulls `master`, so `make fetch-corpus` tomorrow gives a
  different corpus than the one `eval_data/fastapi_dataset.json` was
  relabelled against on 2026-09-27 — when 9 of 15 rows turned out wrong. The
  `.gitignore` says the corpus is "reproducible from the manifest"; today it
  is reproducible only from `master`.

  This is the prerequisite for the three `TestTheShippedDataset` guards
  running in CI at all. They are skipped there (loudly, with a reason, since
  2026-10-12) because the corpus is gitignored; fetching it in CI instead
  would resolve our pinned labels against upstream's current docs and turn
  the gate red on someone else's commit. Pin the fetch to `commit_sha`, then
  CI can fetch and cache it and the guard becomes real everywhere. Until
  then, the guard that caught the 2026-09-27 mislabels runs **only on a
  machine that has already run `make fetch-corpus`.**

  *Done, and the filed plan was wrong about the fix.* The entry says to pin
  the fetch to the manifest's `commit_sha` — which cannot work, because
  `manifest.json` is written *inside* the gitignored corpus directory, so a
  clean clone has no manifest and the pin would be read from the file the
  fetch itself produces. The pin is now a tracked constant in the script.
  And pinning turned out not to be enough on its own: CI fetching 155 files
  from GitHub on every run makes the gate fail on GitHub's outages instead of
  on our commits. The guards never needed the documents — `check_dataset`
  resolves labels through `doc_keys`, which is pure string work over
  *names* — so the names are committed in `data/corpus/fastapi.files.json`
  (5 KB, a file, so `data/corpus/*/` does not match it) and the three guards
  now run everywhere with no corpus and no network: **594 passed, 1 skipped**
  with the corpus hidden, where it was 580 passed, 3 skipped. Two further
  defects fell out of reading the fetcher: `--max-files` defaulted to **120**
  against a 155-file corpus, so the documented command reproduced a corpus 35
  files short and 7 of 16 rows then named missing documents; and a failed
  download printed `SKIP` to stderr and exited 0. Nine tests now cover the
  fetcher — it had none, though `make lint` had always linted it.

- ~~**No coverage floor.**~~ **Done 2026-10-14:** `--cov-fail-under=90`
  against 93.38% today, so CI defends it too. 90 and not 93 because deleting
  a well-covered module lowers the percentage without removing a test, and
  that should be a conversation rather than a red build. Verified the floor
  can fail — at 99 it reports `FAIL Required test coverage of 99% not
  reached` — because a floor that cannot fail is a comment.

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
- Console: per-key usage page; ~~ingest-from-console~~ shipped b0af497, with
  progress events still open (an upload is one blocking request today).
- Surface the router's `reasoning` to the caller. It is logged and thrown away,
  so a refusal can only say *that* the question was judged out of scope, never
  *why* — and the one useful action ("your ROUTER_DOMAIN describes a different
  corpus") is exactly what the reasoning string says. Needs carrying through
  `PipelineResult`, `QueryResponse` and both SSE paths.
- Per-namespace router domains as a map, so a deployment with several corpora
  can describe each one instead of falling back to the generic sentence for all
  but one. `ROUTER_DOMAIN_NAMESPACE` (2026-10-13) is the one-corpus version.

- ~~**`log_usage` is fire-and-forget, so a count can be lost.**~~ **done
  2026-10-23, Rs.0.** `atlas.api.background` owns the three un-awaited
  writes on `/query` — the per-key record and both cache writes. `spawn()`
  holds a strong reference until the task ends, so a garbage collection
  can no longer drop one mid-flight, and logs its exception against the
  task's name instead of letting asyncio print an unattributed traceback at
  collection time. `drain()` runs first in the lifespan's shutdown, bounded
  at 5s because Cloud Run allows ten between SIGTERM and SIGKILL and the
  redis close still has to happen; what it could not wait for is logged as
  a count, since that is the only evidence the budget is too small. No
  Firestore round trip was added to any response.

  Writing it found two bugs in `ed9dbd0`, both in the same nine lines and
  both fatal, caught before the commit was pushed or deployed. See
  DECISIONS 2026-10-23.

- ~~**The shutdown drain cannot be shown to run in production, and probably
  does not.**~~ **Measured 2026-10-23, Rs.0 — the loss is zero.** Option (c)
  ran as `scripts/reconcile_usage.py`, and the answer is that nothing has
  been lost: **37 of 37** queries attributable to the live key have a
  Firestore record.

      served (Cloud Run POST /query -> 200)   38
      - streamed before 2026-10-23             1   (no per-key record by design)
      = expected                              37
      firestore usage.total_queries           37   difference +0

  `usage_log_failed` 0, `background_task_failed` 0, drains observed 0. The
  drain still never runs, and after this it does not need to: at this
  traffic the un-awaited write finishes long before the instance is scaled
  in. (a) always-allocated CPU and (b) a synchronous Firestore round trip
  both stay unbought. Re-run the script if traffic ever becomes bursty
  enough to make the question live again.

  **The method changed on contact, and that is the finding worth keeping.**
  This item proposed reconciling `query_complete` log lines against the
  counters. Both halves of that were wrong:

  * `query_complete` only started carrying tokens and cost on 2026-10-22.
    **33 of the 35 retained lines have neither field**, so the p95 those
    lines were going to make recoverable begins accumulating from that date,
    not from launch.
  * Application stdout is the **lossier** of the two sources. Of 39
    successful requests, one produced no application log line at all and one
    more lost its `request_complete` — about 2.5%, all of it during a single
    twelve-way concurrent burst — while the Firestore counters, written by
    the un-awaited task this whole item was worried about, lost nothing. The
    denominator had to become Cloud Run's own **request** log, which the
    infrastructure writes and the application cannot drop.

  Two corrections separate history from loss, both encoded in the script: a
  key created and exercised locally against production Firestore before the
  first revision booted (`demo`, 2 queries, outside the request log), and
  streamed queries before 2026-10-23, which charged the cap and nothing
  else. There has been exactly **one** streamed query in production, on
  2026-10-07; it is visible only as `query_stream_start`, because streaming
  and non-streaming share one URL and the middleware closes a streamed
  request in 43 ms while the body writes for ten seconds.

  Log retention is 30 days and the counters are lifetime, so a key older
  than the retained log is reported as not reconcilable rather than as loss.
  The boundary moved during this very session — a 2026-09-23 request that
  was in the window at the start of the measurement had aged out by the end.

  The original filing, for the record:

- **(filed 2026-10-23) The shutdown drain cannot be shown to run in
  production, and probably does not.** `drain()` is correct, tested and free, but in 30 days of
  Cloud Logging **no Atlas instance has ever logged `atlas_shutdown`** —
  nor uvicorn's "Shutting down" / "Application shutdown complete" /
  "Finished server process". The lifespan shutdown path has never been
  observed to execute at all.

  Most likely cause: the service has no `run.googleapis.com/cpu-throttling:
  'false'` annotation, so CPU is request-scoped. SIGTERM handling happens
  outside any request, so the container is throttled to near-zero CPU and
  cannot make progress before SIGKILL. This is the same configuration fact
  already documented in `app.py` for the reranker warm task — "this thread
  only advances while the instance happens to be serving something" — with
  a different symptom.

  What this does *not* invalidate: `spawn()`'s other two effects are
  unconditional and hold either way — the strong reference that stops a
  task being collected mid-write, and the failure logging. Only the
  shutdown flush is in question, and an unexecuted drain costs nothing.

  Three ways out, none free of a trade:
  *(a)* CPU always-allocated (`--no-cpu-throttling`) — bills for the
  instance's whole lifetime, not just requests, and `atlas-keepwarm` pings
  every ten minutes, so this is a standing cost increase. Needs a Rs.
  estimate before it is even proposed.
  *(b)* Write the per-key record synchronously — one Firestore round trip
  on every response, the cost the whole design was avoiding.
  *(c)* Accept the loss and quantify it instead: `query_complete` in Cloud
  Logging already carries every query's tokens and cost, written inline on
  the response path. Reconciling that line count against Firestore
  `total_queries` measures the loss directly, for Rs.0, and if it is small
  the counters stay trustworthy without changing anything.

  (c) first — it is the only one that produces a number, and the other two
  are only worth pricing once the number is known.

## Nice to have

- `make demo` — seed a tiny corpus and open the console.
- Keyboard shortcut cheat-sheet in the console (`?`).
- Export a query's full evidence as JSON from the Evidence pane.
