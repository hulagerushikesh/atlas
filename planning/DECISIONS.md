# Decisions

Short log. One entry per decision that someone might later ask "why?" about.
Format: date — decision — alternatives — reason.

- **2026-07** — Fixed pipeline DAG with bounded retry loops, not a free
  ReAct agent. *Alt:* tool-calling agent. *Why:* predictable latency and
  cost; the router gives most of the adaptivity. Sextant explores the other
  shape.
- **2026-07** — RRF for fusion, k=60. *Alt:* min-max score normalisation,
  learned fusion. *Why:* no calibration, no training, robust to one bad
  retriever; the original paper's default.
- **2026-07** — Cross-encoder MiniLM-L-6 as reranker. *Alt:* bigger
  rerankers, Cohere. *Why:* CPU-friendly, ~95% of the quality, no API
  dependency.
- **2026-07** — Faithfulness failures flag, not suppress. *Alt:* refuse on
  low score. *Why:* an honest answer with a warning is more useful than a
  refusal; the caller decides.
- **2026-07** — Recursive chunker, 512/64, as default. *Alt:* semantic.
  *Why:* free, structure-aware, good on docs; semantic costs embeddings per
  document.
- **2026-08-15** — Prove the dense path against real Qdrant local mode
  rather than mocks. *Why:* mocks hid the removed `search()` API for weeks.
- **2026-09-13** — Cartographic design direction. *Alt:* dark dev-tool
  teal/violet, warm-cream serif. *Why:* both alternatives are the category
  default now; the name is Atlas; metaphor in structure and vocabulary, not
  decoration. See `DESIGN.md`.
- **2026-09-13** — Console as a React app (Vite + Tailwind v4 + shadcn +
  Motion), built output committed to `static/`. *Alt:* static HTML/CSS.
  *Why:* static version rejected as amateur; real component primitives and
  motion needed; committing the build keeps the Python image Node-free.
- **2026-09-13** — Hero entrance via CSS keyframes, not Motion. *Why:*
  rAF-driven entrances stall under load; CSS runs off the main thread.
- **2026-09-14** — `learning/` and `planning/` folders; `SUMMARY.md` archived,
  `DEPLOY.md` → `docs/deploy.md`. *Why:* one place for progress that survives
  context loss; one place for study material separate from reference docs.
- **2026-09-20** — Gemini via OpenAI-compatible endpoint instead of OpenAI.
  *Alt:* buy OpenAI credits; write a native Gemini provider. *Why:* credits
  already exist on the AI Studio account shared with sextant; one config knob
  (`OPENAI_BASE_URL`) keeps the OpenAI SDK, retry ladder and tests unchanged.
  Models: `gemini-3.1-flash-lite` primary (same as sextant), `gemini-3.5-flash-lite`
  fallback, `gemini-embedding-001` at 1536-d. Verified: embeddings, JSON mode,
  streaming. Gemini omits `usage` on embeddings → embedder tolerates `None`.
- **2026-09-20** — Deterministic ids: `Document.id = uuid5(source)`,
  `Chunk.id = uuid5(doc_id:chunk_index)`. *Alt:* keep uuid4 and dedupe on
  content_hash via a payload index. *Why:* the dedupe already keyed on id;
  stable ids make it work with zero extra queries and keep Qdrant point ids
  valid. Cost: a shrinking doc leaves tail chunks (backlog).
- **2026-09-20** — Router gets a one-line domain description
  (`ROUTER_DOMAIN`) and prefers "simple" when unsure. *Alt:* drop the
  out-of-scope class. *Why:* refusal is a designed state on the landing page;
  it just needs to know what "in scope" means. Per-namespace domains later.
- **2026-09-20** — Eval matches `relevant_doc_ids` on corpus-relative path,
  not ingester id. *Why:* datasets are written by humans naming pages; ids
  are an implementation detail that just changed once.
- **2026-09-20** — Ship v0.1.0 with precision 0.31 on the landing page.
  *Alt:* tune first, publish later. *Why:* the honest number plus the
  per-miss diagnosis is the portfolio story; M3 is measured against it.
- **2026-09-20** — Daily spend cap in the API (`BUDGET_DAILY_USD`), enforced
  before each metered call, charged after, shared via Redis. *Alt:* rely on
  the AI Studio monthly cap. *Why:* that cap is shared with sextant and is
  monthly; a runaway client could burn a month in an hour. 429 + Retry-After
  is honest to callers; cache hits stay free. CLI scripts stay unmetered —
  a human runs them and states ₹ first.
- **2026-09-20** — Eval overrides are dotted paths into `Settings`
  (`--set reranker.top_k=10`), applied once, then the pipeline is built the
  normal way. *Alt:* a second, eval-only builder with kwargs. *Why:* one
  construction path; a typo fails loudly instead of running the baseline
  twice.
- **2026-09-20** — Console answer markdown is a ~40-line subset renderer
  (bold, code, lists, headings), not a markdown library. *Why:* the chips
  need to own `[n]`; a library would either escape them or need a plugin,
  and the generator prompt never emits more than this subset.
- **2026-09-20** — Relabelled eval numbers (P 0.42 / R 0.78) replace the
  first-run ones on README and landing. Same pipeline, same index; the change
  is two corrected labels. README keeps all three columns so the relabelling
  is visible rather than a silent bump.
- **2026-09-20** — Cloud Run topology for M2: scale-to-zero API, Qdrant
  Cloud free tier, Firestore for keys, no Redis, BM25 + reranker weights
  baked into the image. *Alt:* a small VM with docker-compose (sextant's
  route). *Why:* the demo must cost ≈₹0 idle; a VM is ₹270/mo parked and
  needs a static IP. Cold start (~15 s) is the price and is stated on the
  landing page. Redis returns when there is a second instance to share.
- **2026-09-20** — `sentence-transformers<6`. *Why:* 6.x cannot load the
  MiniLM cross-encoder tokenizer ("Unrecognized processing class"); the
  pin keeps the image build deterministic until upstream settles.
- **2026-09-23** — Payload indexes (`doc_id` keyword, `chunk_index` integer)
  are created in `ensure_collection`, not left to Qdrant defaults. *Why:*
  Qdrant Cloud rejects a filtered scroll or delete on an unindexed key with
  400 "Index required but not found"; local Qdrant answers the same filter
  happily, so `prune_document` passed every local test and failed on the
  first cloud ingest for all 155 documents. The roundtrip test asserts the
  index requests are made, because local mode accepts them and reports no
  schema back.
- **2026-09-23** — `.gcloudignore` in the repo, including `.dockerignore`.
  *Why:* with no `.gcloudignore`, `gcloud builds submit` uses `.gitignore`
  to pick the upload, which drops the gitignored `data/index/` the image
  bakes in — the build fails at `COPY data/index/`, and the failure names
  Docker, not gcloud.
- **2026-09-23** — `REDIS_URL=""` means "no Redis on purpose", and a client
  that fails its ping is discarded rather than passed to the cache. *Why:*
  the first Cloud Run revision reported `degraded` forever — the startup code
  assigned the client before pinging it, so every request then retried a
  refused connection on localhost. Absent Redis is the M2 design, not a
  fault, and `/health` has to say so or the signal is worthless.
- **2026-09-23** — The daily spend total moves to Firestore on Cloud Run
  (`BUDGET_STORE=firestore`, one document per UTC day, `Increment`).
  *Alt:* leave it in-process. *Why:* the live service reported
  `spent_today_usd: 0.0` right after a charged query — the instance that
  recorded it had already scaled to zero. In-process capped a container's
  lifetime, not a day, which is precisely the case a runaway client
  produces. Firestore is already a dependency for keys and one doc a day is
  free. The meter keeps a per-process mirror as the floor, so a counter
  outage cannot uncap the spend either.
- **2026-09-23** — `atlas.hulage.in` is fronted by a Vercel rewrite, not a
  Cloud Run domain mapping. *Why:* mappings are not offered in `asia-south1`
  (501 UNIMPLEMENTED). The alternatives were a global external load balancer
  (~₹1,500/mo for a forwarding rule, more than the whole service costs) or
  moving the service to a mapping-capable region and paying ~200 ms on every
  Indian request. A Vercel rewrite costs ₹0 and one hop, and Finertia already
  runs this shape.
- **2026-09-23** — Identifier pieces are indexed for BM25 even though context
  precision drops. Measured with `scripts/eval_retrieval.py` on the same 14
  labelled questions: recall 0.726 → 0.798, precision 0.529 → 0.486, one more
  question fully recalled (fq-005 `tutorial/body`). *Why:* a document the
  retriever never returns cannot be recovered downstream, while an extra
  chunk in a window of five is something the reranker and the generator
  already handle — faithfulness has stayed at 1.00. A variant that counted
  each piece once per chunk was tried and rejected: it kept the precision
  cost and lost the recall gain.

  **Corrected 2026-09-23 (same day), after the full eval.** End to end the
  change is worth nothing: recall 0.778 → 0.778, precision 0.416 → 0.431,
  faithfulness 1.000, answer relevance 0.832 → 0.825 — every delta under the
  0.02 floor. Per sample it is a swap: `fq-005` 0 → 1.0, `fq-012` 1.0 → 0,
  both flipping at the rank-5 boundary. Query decomposition was already
  recovering what the tokeniser recovers, so they compete for the same five
  slots rather than compounding. Kept regardless, because the router's
  "simple" branch retrieves once without decomposing, and the retrieval-only
  numbers are exactly that branch. The claim this entry originally made — that
  the tokeniser buys recall — is true only there.
- **2026-09-23** — Retrieval changes are measured with a retrieval-only
  harness (`scripts/eval_retrieval.py`, ≈₹0.01) before the full eval
  (≈₹0.3). *Why:* a tokeniser cannot move faithfulness or answer relevance,
  so paying four LLM calls a question to see context metrics is waste. Its
  numbers are not comparable with run_eval.py's — it does not decompose
  complex questions — so it is a before/after instrument, not a scoreboard.

  **Amended 2026-09-23:** it is also systematically optimistic. It measures
  the un-decomposed path, where retrieval carries the whole question alone, so
  any retrieval improvement looks larger there than it will through a pipeline
  whose decomposition is already compensating. Use it to reject changes
  cheaply; confirm anything it likes with the full eval before publishing a
  number.
- **2026-09-23** — `reranker.top_k` 5 → 15. *Alt:* 10, or leave it at 5 and
  chase the misses with HyDE and contextual headers. *Why:* measured, end to
  end, on the labelled set: context recall 0.778 → 0.900 (+0.122, six times
  the 0.02 floor), faithfulness 1.000 → 1.000, answer relevance 0.825 → 0.819.
  `advanced/custom-response` and `tutorial/response-model` recovered outright
  and `tutorial/security/oauth2-jwt` went 0 → 0.5 — three documents that had
  survived every M1 attempt and turned out to be in the candidate set all
  along, below rank 5. Context precision falls 0.431 → 0.302, which is the
  denominator rather than a regression: one relevant document per question
  cannot fill fifteen slots. The cost is 2.45x generator tokens
  (~$0.0005 → ~$0.0012 a query), accepted because faithfulness — the thing
  more context actually threatens — did not move. 10 was not run end to end:
  the cheap harness ranked 15 above it on recall, and buying second-best for
  another ₹0.3 is not worth it.
- **2026-09-23** — `retrieval.top_k` stays 20 for now, though the reranker
  keeps 15 of those 20 and so barely filters. Retrieval-only recall at 40 is
  0.964 against 0.929 at 20. *Why not ship it:* that is the harness this same
  day showed to be systematically optimistic, and the discipline that caught
  the tokeniser is worth more than one experiment. It is the next thing to
  confirm with a full run.
- **2026-09-24** — Eval reports record per-sample `stage_ms` and print a
  p50/p95 table per stage. *Why:* `reranker.top_k` 5 → 15 was shipped on
  quality numbers alone, and nothing in the harness could have caught a
  latency cost. A run's `duration_seconds` is wall clock over the whole set at
  concurrency 4, which is throughput, not what one caller waits for — the two
  move in opposite directions when work per query grows. The first live query
  after that deploy took 23 s against ~11 s before, and the harness had no
  opinion about it. p50/p95 are nearest-rank: 15 samples do not support
  interpolating between two of them.
- **2026-09-24** — The 23 s live query is not attributed to `reranker.top_k`.
  The first run with per-stage timings put p50 at 19.9 s against ~7 s measured
  on 2026-09-20, which looks like the `top_k` 5 → 15 deploy tripling latency.
  It is not, and the report says why: **routing** is a single LLM call with a
  fixed prompt that runs *before* retrieval, so it cannot depend on `top_k` by
  construction, and its p50 is 2,570 ms. Retrieval (2,668 ms) and grading
  (3,184 ms, truncated to five chunks at `grader.py:82`) are equally
  independent, and the two stages that *are* sensitive to window width —
  generation 3,136 ms and faithfulness 3,518 ms — are no slower than the ones
  that are not. Every stage costs roughly one LLM round trip and they are all
  about 2.5–3.5 s. That is a per-call cost, not a context-size cost. The
  proximate cause was visible in the logs: the primary model returned 503
  throughout and every call paid a failed request plus a fallback. *Not
  concluded:* what p50 is on an undegraded provider. The run that answers it
  has to report which model served it, which is the next entry.
- **2026-09-24** — A run reports which chat model actually served its calls,
  and the report refuses to compare quietly when more than one did. *Why:*
  `GenerationResponse.model_used` and `fallback_triggered` had existed since
  Module C and were read by nothing; the only trace of a fallback was a log
  warning. The 2026-09-24 eval ran largely on `gemini-3.5-flash-lite` after
  503s on the primary, and was diffed against a run that had not — recall
  moved 0.900 → 0.967 and faithfulness 1.000 → 0.933 on an unchanged config,
  deltas well past the 0.02 floor that were being read as noise. A different
  model is not noise. The counter lives on the provider and is summed across
  the pipeline and the judges, because they may or may not share an instance.
- **2026-09-24** — A refusal is excluded from faithfulness, not scored zero.
  *Alt:* score it 1.0; leave it alone. *Why:* the generator is instructed to
  emit one exact sentence when the context cannot support an answer. Both
  auditors — the pipeline's `FaithfulnessChecker` and the eval's
  `FaithfulnessMetric` — enumerated that sentence as a factual claim, found no
  passage supporting it, and returned 0.0. In the harness one such sample took
  the headline from 1.000 to 0.933; in production the API attached a
  possible-fabrication warning to the one answer that cannot be fabricated.
  Scoring 1.0 instead would reward refusing everything, so the sample is
  marked inapplicable and dropped from the mean, and the report prints
  "over 14 of 15; 1 n/a" next to any score that had one. The refusal sentence
  is now a shared constant (`generator.REFUSAL`) so the prompt and the two
  readers cannot drift apart, and detection is equality after normalisation,
  never substring: "I don't have sufficient information about X, but Y"
  asserts Y and must still be audited.
- **2026-09-24 (closing the previous three entries)** — Re-ran the identical
  `top_k` 15 config on a healthy provider. Context precision 0.3022, recall
  0.9000, faithfulness 1.0000 — the first three reproduce the 2026-09-23 run
  **to four decimal places**; only answer relevance moved, 0.8193 → 0.8277,
  inside the floor. So the degraded run's recall +0.067 and faithfulness
  −0.067 were entirely the model swap and the refusal artifact, not variance,
  and the 0.02 significance floor is if anything generous: with the model held
  constant these metrics are near-deterministic. `model_calls` recorded
  `{gemini-3.1-flash-lite: 102}`, which is how the run can say so.
- **2026-09-24** — `reranker.top_k` 15 costs no measurable latency, and the
  question opened by the 23 s live query is closed. p50 per sample is 15.0 s,
  and the stage table shows why that is not about window width: **grading**
  (3,478 ms) is the slowest stage and truncates to five chunks regardless of
  `top_k`, while **generation** (2,866 ms) and **faithfulness** (2,975 ms) —
  the only two stages that see all fifteen — rank third and second behind it.
  Every stage lands between 2,280 and 3,478 ms. That is six sequential LLM
  round trips at roughly 2.5 s each, which is the pipeline's shape, not the
  window's size. A live production query the same hour took 15.7 s wall clock
  with grading at 2,370 ms, against 23.1 s and 11,050 ms during the outage.
  *Not comparable:* the "p50 ≈7 s" in STATUS is from 2026-09-20 and was
  measured differently; it is not evidence of a regression in either
  direction. If latency is to be reduced, the target is the number of
  sequential calls, not `top_k`.
- **2026-09-24** — `retrieval.top_k` stays 20. Measured end to end at 40 and
  **not shipped**, for the second time and now on better evidence. The
  aggregate looks like a pass: recall 0.9000 → 0.9333, +0.033 against a 0.02
  floor, faithfulness unchanged at 1.000. Per sample it is a three-way swap —
  `fq-007` 0.5 → 1.0 and `fq-012` 0 → **1.0**, the long-standing last miss,
  paid for by `fq-005` going **1.0 → 0**, a question that had worked in every
  run since the labels were fixed. Context precision fell 0.3022 → 0.2711, and
  unlike the `reranker.top_k` change this one is *not* a denominator effect:
  the window is still fifteen slots, so a lower fraction means the reranker
  put worse chunks in them. That is the finding. At 20 candidates the reranker
  kept 15 and barely filtered; at 40 it keeps 15 of 40, and MiniLM-L-6 starts
  making mistakes a wider net cannot compensate for. **The binding constraint
  has moved from the retriever to the reranker**, which is a different
  experiment from this one.
- **2026-09-24** — Next candidate is `retrieval.top_k=30` with
  `reranker.top_k=20`, not 40. The cheap harness swept six configurations for
  about ₹0.06: 20/15 recall 0.929 (misses `fq-012`), 30/15 and 40/15 both
  0.964 (miss `fq-007`), and 30/20, 40/20, 40/25 all reach **1.000** with
  precision 0.332, 0.314, 0.291 respectively. So 40 buys nothing over 30 at
  the same window and costs precision, and the widest window costs most.
  Unconfirmed on purpose: this is the harness that does not decompose, and it
  already mispredicted this run — it had `fq-007` missing at 40/15 where the
  full eval recovered it, and said nothing about `fq-005` breaking. It picks
  the candidate; the full eval decides. 30/20 would also raise generator
  context by a third, so the confirming run is ≈₹0.9, not ₹0.73.
- **2026-09-24** — `eval_retrieval.py --json` sends logs to stderr. *Why:*
  structlog defaults to stdout, so the flag that exists to be piped into a
  parser emitted log lines with a JSON object buried at the end. A six-config
  sweep failed to parse after every run had already been paid for.
- **2026-09-25** — `cross-encoder/ms-marco-MiniLM-L-12-v2` rejected, and with
  it the whole reranker-tuning direction. The cheap harness liked it: at 25,
  30 and 40 candidates it reached retrieval-only recall **1.000** where L-6
  managed 0.929–0.964, with the window left at 15 so nothing downstream got
  more expensive. End to end it bought **nothing**: recall 0.9000 → 0.9000,
  precision 0.3022 → 0.2667, faithfulness flat. Latency was the real verdict —
  retrieval p50 went 2,366 → **18,158 ms** and p95 to 50,335 ms. L-12 is only
  1.6x slower per pair in isolation (332 ms vs 210 ms for 40 pairs), so most
  of that is CPU contention: at concurrency 4, with decomposed questions
  reranking once per sub-query, four torch forward passes fight for the same
  cores. The same harness ran L-6 over *more* candidates (40) at 3,230 ms.
  Also measured and rejected: `BAAI/bge-reranker-base`, 278M parameters, which
  scored **worse** than L-6 at 40 candidates (0.929, and it lost `fq-001`
  instead). Bigger reranker is not better here.
- **2026-09-25** — **`fq-005` and `fq-012` are one slot, not two problems.**
  Three unrelated changes have now produced the identical trade: the BM25
  tokeniser, `retrieval.top_k` 40, and the L-12 reranker each recovered
  `fq-012` and lost `fq-005`, which had been solid since the labels were
  fixed. The questions explain it — *"How does FastAPI validate request body
  data?"* wants `tutorial/body`, and *"Does FastAPI require you to use Pydantic
  for input validation, or can you skip it entirely?"* wants
  `tutorial/query-params-str-validations`. Both are about validation, both
  target pages discuss validation, and the chunks carry nothing that says
  which kind. So this is a **chunk representation** problem, not a ranking
  one: no ordering of indistinguishable chunks separates them, which is why
  three ranking changes all moved the same 1.0 from one question to the other.
  Ranking tuning is closed until the chunks can be told apart.

  **Retracted 2026-09-25, same day, on ₹0.06 of evidence that should have been
  bought before the entry was written.** Dumping what is actually retrieved
  refutes it. For `fq-005`, `tutorial/body` sits at ranks 5, 6, 8, 10 and 13 —
  five chunks, comfortably inside the window. For `fq-012`,
  `tutorial/query-params-str-validations` does not appear at all. They are not
  competing for one slot: one target is abundant and the other is absent. The
  common factor across the three experiments is real, but the mechanism is the
  next entry, not this one. The lesson is the obvious one — three experiments
  sharing a symptom invited a story, and the story was cheaper to write than
  the dump that disproved it.
- **2026-09-25** — The retrieval-only harness has now mispredicted three
  consecutive full evals and its guidance is downgraded accordingly. It said
  the tokeniser bought recall (worth nothing end to end), it said
  `retrieval.top_k` 40 would miss `fq-007` (the full run recovered it and
  broke `fq-005` instead), and it said L-12 reached 1.000 (the full run stayed
  at 0.900). The pattern is consistent rather than random: it retrieves once
  per question where the pipeline decomposes and retrieves per sub-query, so
  it measures whether a document is *reachable*, never whether the pipeline
  will *keep* it once the sub-queries compete for the window. It also cannot
  see latency, which is what actually rejected L-12. Use it to confirm a
  document is in the index at all. Do not use it to predict a score, and do
  not let a 1.000 on it justify skipping the ₹0.73.
- **2026-09-25** — **The grader-driven retry can destroy a good retrieval, and
  that is what broke `fq-005`.** Traced by running the one question through
  the full pipeline under both configurations. At the baseline it is
  classified `simple`, retrieves once, the grader scores 0.9, and
  `tutorial/body` lands at ranks 5, 6, 8, 10 and 13. Under L-12 with 30
  candidates the same first retrieval happens — the retrieval-only harness
  confirms the target is in that window — but the grader returns **0.4,
  insufficient**, the pipeline reformulates to "What is the underlying
  mechanism FastAPI uses to perform req…", retrieves again, and the
  replacement window contains **no `tutorial/body` at all** (five chunks of
  `alternatives`, two of `release-notes`). The grader then scores that
  strictly worse set **0.9** and the pipeline returns it.

  Two defects compound. First, `grader.py:82` grades `chunks[:5]`, with the
  comment "more adds noise" — written when `reranker.top_k` was 5, so it saw
  the whole window. At 15 it judges a third of it and calls a window
  insufficient while the answer sits at rank 6. Second,
  `pipeline.py:_retrieve_with_retry` does `current_queries = [reformulated]`
  and the next pass **replaces** the accumulated context rather than adding to
  it, so a false "insufficient" does not merely fail to help — it throws away
  documents the pipeline already had. Either alone is survivable. Together
  they lose the answer.

  This also corrects the previous entry's account of the cheap harness. For
  `fq-005` the harness was not optimistic because it skips decomposition —
  the question is `simple` and never decomposes. It was optimistic because it
  has no grader and therefore no retry. The harness measures the pipeline
  without the stage that did the damage.
- **2026-09-27** — **The non-destructive retry is confirmed end to end: recall
  0.900 → 0.933, and the two samples that moved are exactly the two that
  retry.** Full eval on `eval_data/fastapi_dataset.json`, 15 samples, 44,224
  tokens, ≈₹0.86, compared against the `topk15-clean` replication. Both runs
  were served entirely by `gemini-3.1-flash-lite` (102 calls each), so the
  comparison is clean in the sense the 2026-09-24 outage taught us to check.

  | Metric | topk15-clean | retry-union | Delta |
  |---|---|---|---|
  | context_recall | 0.9000 | 0.9333 | **+0.0333** |
  | context_precision | 0.3022 | 0.3185 | +0.0163 *(ns)* |
  | faithfulness | 1.0000 | 1.0000 | tie |
  | answer_relevance | 0.8277 | 0.8253 | tie |

  Precision rising *with* recall is the part worth noting: every earlier
  attempt to raise recall paid for it in precision. Here the union is
  re-ranked against the original query before it is cut, so the extra chunks
  are ordered rather than merely appended.

  Only `fq-007` changed score, 0.500 → 1.000 recall, and the trace says why:

  ```
  classification=complex  sub_queries=3   → attempt 1 returns 41 chunks
  retrieval_graded  score=0.3  sufficient=False
  retrieval_retry   attempt=1 … attempt=2
  retry_union_reranked  kept=41  union=53
  pipeline_complete  chunks=41  retries=2
  ```

  At the baseline that 41-chunk decomposed window was **replaced** by a single
  reformulated query's 15 chunks, which is where the missing half of the
  recall went. `fq-015` shows the same signature (15 → 38 chunks, score
  unchanged). No other sample retries and no other sample moved, which is the
  cleanest attribution available: the fix touches only the retry path and only
  the retry path changed.

- **2026-09-27** — **`window` is the first attempt's width, and for a
  decomposed query that is 41 chunks, not 15.** Found while explaining the
  chunk counts above, not by reading the code. `_retrieve_all` fuses
  `sub_queries × top_k` and never truncates, so "one window" means whatever
  attempt one happened to return. The generator was handed 41 chunks for
  `fq-007`; tokens for the run rose 37,599 → 44,224 (+18%), which is the whole
  of the cost increase. This is the uncapped-merge backlog item, now with a
  price on it. Capping it is its own experiment: the cap is also what would
  have kept `fq-007` at 15 chunks and, on this evidence, at 0.5 recall.

- **2026-09-27** — **Context precision and recall were scoring an out-of-scope
  row.** `fq-015` has `relevant_doc_ids: []` — the row whose correct answer is
  a refusal. Precision counted 0/38 and recall counted a free 1.0, and both
  reached the mean. That is the same defect as the refusal-faithfulness one
  fixed two days earlier, in two more metrics: the number describes the shape
  of the dataset, not the behaviour of the pipeline. Both are now
  `applicable=False`, so the reporter annotates them `over 14 of 15; 1 n/a`.
  Corrected headlines, recomputed over the 14 answerable rows:

  | Metric | baseline | retry-union | Delta |
  |---|---|---|---|
  | context_precision | 0.3238 | 0.3412 | +0.0174 *(ns)* |
  | context_recall | 0.8929 | 0.9286 | **+0.0357** |

  The verdict is unchanged under either rule, which is the point of writing
  both down rather than silently restating the headline.

- **2026-09-27** — **The comparator will happily compare two different
  datasets.** The first run today used the default `sample_dataset.json` (30
  HR questions) against a FastAPI corpus by forgetting `--dataset`. Every
  sample was routed out of scope, retrieved 0 chunks and scored 0. The
  comparator then printed a confident `Overall winner: A` against a 15-sample
  FastAPI baseline. Cost of the mistake was small (8,341 tokens, ≈₹0.16) but
  the report it produced was not obviously wrong at a glance — only the token
  count gave it away. A comparison across datasets is meaningless and the
  comparator should refuse it. Logged in BACKLOG.
- **2026-09-27** — **Capping and re-ranking the sub-query merge is shipped:
  precision +0.035, recall unchanged, tokens −19%.** `_retrieve_all` now
  round-robins across sub-queries and cuts the result back to one window,
  re-ranked against the original query when a reranker exists. Full eval
  against the `retry-union` run of the same morning, both served entirely by
  `gemini-3.1-flash-lite`.

  The printed A/B is **not** the comparison to read: this run excludes
  `fq-015` from the context metrics and the stored baseline does not, so its
  `recall −0.0047` is a change of denominator, not of retrieval. Like for
  like, over the 14 answerable rows:

  | Metric | retry-union | merge-capped | Delta |
  |---|---|---|---|
  | context_precision | 0.3412 | **0.3762** | **+0.0350** |
  | context_recall | 0.9286 | 0.9286 | **0.0000** |
  | faithfulness | 1.0000 | 1.0000 | tie |
  | answer_relevance | 0.8253 | 0.8271 | tie |
  | tokens | 44,224 | **35,928** | −19% (Rs.0.86 → Rs.0.70) |
  | latency p50 | 11.0 s | 10.0 s | — |

  Every sample now returns exactly 15 chunks. The risk stated before the run
  was that the cap would take `fq-007` back to 0.5 recall, since its 41-chunk
  window was what recovered it two hours earlier. It did not: recall held at
  1.000 on 15 chunks while precision went 0.244 → 0.400, because the union is
  ordered against the original question before being cut rather than
  truncated in sub-query order. `fq-013` moved 0.467 → 0.800 the same way.
  Recall is identical on every one of the fifteen samples.

- **2026-09-27** — **The cap stopped `fq-007` retrying at all, which is a
  second-order argument about the grader's 5-chunk window.** Not predicted;
  found in the per-sample `stage_ms`. `fq-007` grading fell 5052 ms → 1158 ms,
  three grader calls to one, and that is exactly the 102 → 100 model calls for
  the run. The grader reads `chunks[:5]`; when those five are the best five
  against the original question instead of the first five of sub-query one, it
  accepts a window it previously called insufficient twice. So the grader
  window (`grader.py:82`) is now doing much less damage than it was when it
  was logged, and the case for widening it is weaker, not stronger. Leave it;
  it stays a latency item and a low one.
- **2026-09-27** — **Deterministic context headers are the largest single
  quality gain of the milestone, and my stated mechanism for them was wrong.**
  Every chunk's indexed text now opens with its source path in words and the
  heading trail above it (`tutorial query params str validations` /
  `Query Parameters and String Validations > Default values`). Re-ingested
  into a separate `headers` namespace so the live collection was never
  touched: 4,020 chunks, 488,690 embedding tokens, **Rs.6.45**, against a
  Rs.6.42 estimate priced beforehand by chunking locally.

  | Metric | merge-capped | ctx-headers | Delta |
  |---|---|---|---|
  | context_precision | 0.3762 | **0.4524** | **+0.0762** |
  | context_recall | 0.9286 | **0.9643** | **+0.0357** |
  | faithfulness | 1.0000 | 1.0000 | tie |
  | answer_relevance | 0.8271 | 0.8328 | tie |
  | tokens | 35,928 | 39,461 | +10% (Rs.0.70 → Rs.0.77) |

  Both runs exclude `fq-015`, so this A/B needs no restating. Nine of fifteen
  samples improved precision. **`fq-012` is recalled for the first time**,
  0.000 → 1.000 — the last outright miss in the set.

  **The mechanism was not the one I argued for.** I predicted BM25 would find
  `fq-012` because the sparse tokenizer splits `/` and `-`, so the path would
  index as tutorial, query, params, str, validations. Measured: the target's
  BM25 rank went the *wrong* way, 11 → 15, and it stayed absent from the
  top 15 in the cheap harness on both namespaces. The question is "Does
  FastAPI require you to use Pydantic for input validation, or can you skip
  it entirely?" — it shares essentially no vocabulary with that path, so a
  path-token argument never applied to it. What recovered `fq-012` was the
  full pipeline: decomposition and the now-additive retry reaching the page
  the cheap harness never sees. I bought the re-ingest partly on a reason
  that turned out not to hold, and it paid off for a different one.

- **2026-09-27** — **The retrieval-only harness has now mispredicted four
  times running, and this time in both directions at once.** On the `headers`
  namespace it reported recall *down* 0.9286 → 0.8929 and `fq-012` still
  missing. The full eval returned recall *up* to 0.9643 with `fq-012`
  recalled. It has no grader, no retry and no decomposition, so for anything
  a complex or retried query touches it is not a cheap approximation of the
  pipeline — it is a measurement of a different system. Keep it for one job
  only: asking whether a document is reachable at all by a single-shot
  retrieval. Do not let it veto or justify a change.

- **2026-09-27** — **This is a swap, and it is worth saying why it is not the
  swap that got `retrieval.top_k` 40 rejected.** `fq-007` fell 1.000 → 0.500
  recall while `fq-012` rose 0.000 → 1.000. On 2026-09-24 an aggregate gain
  of the same shape was rejected because it hid `fq-005` **breaking
  outright**, 1.0 → 0.0, and precision fell at an unchanged window. Here the
  losing sample still retrieves one of its two labelled documents and its own
  precision rises 0.400 → 0.733, the gaining sample goes from nothing to
  complete, and precision rises on nine of fifteen. The rule that rejected 40
  was "do not buy an aggregate with a broken question", and no question is
  broken here.

- **2026-09-27** — **`fq-012`'s label is too narrow and has been steering
  spend.** Its ground truth spans plain type hints, `Query()`/`Path()`/`Body()`
  with basic constraints, *and* the claim that Pydantic models are needed only
  for nested bodies. That is at least three pages —
  `tutorial/query-params`, `tutorial/query-params-str-validations` and
  `tutorial/body` — and it is labelled with one. It has been called "the last
  outright miss" in three sessions of planning and was part of the case for
  this Rs.6.45 re-ingest. Same class as the two labelling errors the
  "Relabelled" column already fixed. Relabel before quoting it again.

- **2026-09-27** — **`fq-012` relabelled to five documents, and it costs the
  headers their recall gain.** The new set is `tutorial/query-params` (plain
  type hints are stated there to parse *and validate* without a model),
  `tutorial/query-params-str-validations`, `tutorial/path-params-numeric-validations`
  and `tutorial/body-multiple-params` (`Query()`, `Path()` and singular-value
  `Body()` respectively), and `tutorial/body` (where Pydantic genuinely is
  required). Each is the page a claim in the ground-truth answer rests on;
  none was added to move a number.

  What it does to the record, recomputed offline from the stored reports:

  | run | `fq-012` recall, old label | corrected |
  |---|---|---|
  | v1, `top_k` 5 | 1.000 | 0.400 |
  | BM25 tokeniser | 0.000 | 0.200 |
  | `top_k` 15 | 0.000 | 0.200 |
  | `top_k` 40 (rejected) | 1.000 | 0.600 |
  | retry fix | 0.000 | 0.000 |
  | capped merge (`main`) | 0.000 | 0.000 |
  | **+ headers** | **1.000** | **0.400** |

  So `fq-012` was never the outright miss it was described as, and the
  headers did not recover it — they took it from nothing to two of its five
  pages. Aggregate recall for the headers run falls 0.9643 → 0.9214, which
  puts it *below* `main`'s 0.9286. **The headers' recall gain was the label
  artifact; only the precision gain survives** (0.3762 → 0.4571, still the
  largest of the day and still well over the 0.02 floor). Recall across the
  whole day is now 0.9071 → 0.9214, inside the floor: no significant
  movement.

  This does not reverse the Rs.6.45 spend — precision is a real gain and the
  money is spent either way — but the headline it was sold on is withdrawn.

- **2026-09-27** — **A relabel must never again be priced as an eval run.**
  Both context metrics are pure set arithmetic over doc ids, chunk ids are
  `uuid5(document_id(source), chunk_index)`, and every report already stores
  its retrieved chunk ids. So any label set can be replayed against every run
  ever recorded for Rs.0 and no model calls: `scripts/replay_context_metrics.py`.
  It checks itself by reproducing the stored scores for samples whose labels
  did not change — it reproduced all twelve reports back to 2026-09-20 exactly,
  which is why the table above can be trusted without re-running anything.
  What it cannot replay is `faithfulness` and `answer_relevance`, and a label
  change does not touch those.

- **2026-09-27** — **`fq-010`'s reference answer prescribed two APIs the
  corpus does not contain.** It told the reader to reach for
  `asyncio.run_in_executor` or Starlette's `run_in_threadpool`. Neither
  string occurs anywhere in `data/corpus/fastapi` — nor does `motor`,
  `AsyncSession` or `aiosqlite`; `asyncpg` appears once, in a changelog line
  in `release-notes.md`. The answer was written from general FastAPI
  knowledge rather than from the 155 pages the system is actually allowed to
  read, which makes it a standard no retrieval over this corpus can meet.

  Rewritten to what `async.md` actually says, which is a different and better
  answer: the fix is the **function declaration**, not a helper called from
  inside the coroutine. Declare the path operation with plain `def` and
  FastAPI moves it to an external threadpool and awaits it (`async.md:418`,
  "as it would block the server"); the TL;DR recommends exactly that for
  database libraries, "most" of which have no `await` support; `def`
  dependencies and sub-dependencies get the same treatment (`:426`, `:430`);
  and AnyIO is the documented route for mixing blocking code into async code
  you write yourself (`:364`). The label stays `async` alone, and is now
  right rather than right by luck — every claim is on that one page.

  Opposite fault to `fq-012`, same root: nobody had read the reference
  answers back against the corpus.

- **2026-09-27** — **Nothing scores against `ground_truth_answer`.** Found
  while fixing `fq-010`, by asking which metric the fix would move. Answer:
  none. `runner.py:171` passes it into every `score()` call and all four
  metrics take it in their signature and never read it — one occurrence each,
  the parameter itself. Precision and recall use `relevant_doc_ids`;
  faithfulness checks the generated answer against the *retrieved chunks*;
  answer relevance compares the question against questions regenerated from
  the generated answer. So a wrong reference answer is invisible to the
  harness, which is exactly why `fq-010` survived this long, and **the eval
  has no correctness metric at all.** Four metrics can be perfect on a
  confidently wrong answer as long as it is grounded in whatever was
  retrieved. The reference answers are there for a human reading a report.
  Worth saying out loud in the README next to the table.

- **2026-09-27** — **The whole eval set audited; nine of fifteen rows were
  wrong.** Method, after `fq-012` and `fq-010` showed there were two distinct
  faults: read a row's reference answer, list the claims it makes, `grep` the
  corpus for each one, then check the label set against the result — no page
  missing that a claim rests on, no page present that nothing rests on.

  | row | fault | fix |
  |---|---|---|
  | `fq-003` | wrote `Optional[str] = None`; that spelling is not on the labelled page | reworded to `str \| None = None` |
  | `fq-004` | "the router equivalents are `@router.post()`" — `router.post` occurs nowhere in the corpus | clause dropped |
  | `fq-005` | named a "422 Unprocessable Entity"; `422` is not in `tutorial/body.md` | reworded to the error the page describes |
  | `fq-006` | promised yield-based cleanup; `yield` occurs 0 times on the labelled page | added `dependencies/dependencies-with-yield` |
  | `fq-007` | `OAuth2PasswordBearer` is on neither labelled page | added `security/first-steps` |
  | `fq-008` | `tutorial/stream-json-lines` was required and has no `StreamingResponse`, no `Response`, no `media_type` | removed |
  | `fq-009` | quoted `@app.on_event('startup')`; that string is in the included code, not the page | reworded |
  | `fq-012` | three claims, one labelled page | 1 → 5 |
  | `fq-015` | categorised out-of-scope | relabelled, see below |

  `fq-001`, `fq-002`, `fq-011`, `fq-013`, `fq-014` were read and left alone
  except `fq-014`, which gained `tutorial/static-files` for its StaticFiles
  claim. Corrected figures, all from an offline replay: precision
  0.3733 → 0.3477 → 0.3867 → **0.4667**, recall 0.9244 → 0.9333 → 0.9333 →
  **0.9378**, over all fifteen rows.

  **This withdraws "three changes, each positive on precision."** The retry
  fix *costs* precision, 0.3733 → 0.3477. It widens the window and two rows
  the old labels could not see — `fq-015` and `fq-007` — are now visible
  paying for it. The cap refunds it and the headers gain on top. The fix is
  still right on the merits, and the day's net is still +0.093 precision, but
  the monotone story was an artifact of the labels.

- **2026-09-27** — **`fq-015` was not out of scope, and the metric change it
  motivated has no row left to act on.** `advanced/websockets.md` is in the
  corpus, and line 23 of it — the "WebSockets client" section — names React
  by name, which is the half of the question the row was supposed to be
  unanswerable on. Checking what the pipeline actually returned settles it:
  it answered with citations, faithfulness 1.000, and a paraphrase of that
  very line. Its context precision was 0.4667 and its recall 1.000, and both
  were being recorded as "structurally meaningless" and discarded.

  So the reasoning written into both context metrics two days ago — "an
  out-of-scope row: nothing in the corpus is relevant, so the correct answer
  is a refusal" — was sound as a rule and false about the only row it was
  applied to. The guards stay, because a dataset may legitimately carry an
  unanswerable row, and their comments now say plainly that this one does
  not. The lesson is narrower than "the guard was wrong": **nobody checked
  whether the corpus could answer the question before declaring it
  out-of-scope, and the harness cannot check it for you** — a row with no
  labels is unfalsifiable by construction, since precision and recall have
  nothing to disagree with.

  Cost of the set no longer having an out-of-scope row: the refusal path is
  unmeasured end to end. It was already unmeasured — `fq-015` never triggered
  it — but that is now visible instead of assumed. BACKLOG.

- **2026-09-27** — **The dataset checker agrees with the matcher by
  construction, not by comment.** `atlas.evaluation.dataset.corpus_doc_keys`
  builds the set of ids a corpus can present using the same four forms
  `doc_match.chunk_doc_keys` builds them from — uuid, full source, stem,
  corpus-relative-without-extension. Written any other way the checker would
  drift from the matcher and start rejecting labels that score fine, or
  passing labels that never match, which is worse than no checker. A label
  outside that set cannot match any chunk, so calling it unresolved is exactly
  true rather than a heuristic.

- **2026-09-27** — **`category: "out_of_scope"` does not authorise an empty
  label set; a separate flag does.** The obvious design was to accept the
  category string already on the row, which would have let `oos-001` pass
  untouched. Rejected: `fq-015` carried `category: "out_of_scope"` for three
  milestones *while being fully answerable*, so the category was precisely the
  field that was wrong. A category is a description of a row; the flag is an
  assertion that someone checked the corpus. Making it a second, separate act
  is the whole value. The cost is one line per genuinely out-of-scope row,
  and there is currently one such row in the whole project.

- **2026-09-27** — **The check runs before the pipeline is built.** In
  `run_eval.py` the dataset is loaded and checked ahead of `_build_pipeline`,
  so a broken dataset returns 1 having spent nothing. That ordering is the
  point of the feature: the fault it catches is one whose symptom is a report
  full of plausible zeros, which is only visible after the run is paid for.
  `--allow-broken-dataset` exists for the case where someone wants the numbers
  anyway, and says in its help what is wrong with them.

- **2026-09-28** — **An index's state is a thing you check, not a thing you
  infer.** `scripts/verify_index.py` reads both halves of a namespace and
  compares them: chunk counts, chunk ids, content hashes, and whether each
  chunk carries the context header the current config asks for, recomputed
  from the corpus with the same `context_header()` the ingest calls.

  Built because an ingest reported success and changed nothing. Every
  content hash matched, both indexes skipped every chunk, the run finished
  in seconds looking exactly like a fast success, and the only evidence
  against it was a file mtime. An ingest cannot tell you it wrote the wrong
  namespace, because from inside the run nothing went wrong.

  Three properties made it worth writing rather than re-doing by hand:

  1. **It costs nothing.** Qdrant scrolls and a local JSON read; no
     embeddings, no LLM. So there is no reason not to run it, which is the
     only way a check actually gets run.
  2. **It names the mismatched hybrid.** Between `ingest.py` and
     `deploy_gcp.sh` production serves new dense vectors against the
     pre-header BM25 file baked into the live image. That state answers
     queries and scores badly instead of erroring. Comparing content hashes
     across the two halves is the only thing that sees it.
  3. **`chunking.context_headers` decides what passing means**, in both
     directions. Headers missing when the config says on, and headers left
     behind when it says off, are the same drift.

  The corpus root is inferred from the common prefix of the indexed sources,
  because that is what `index_directory` strips. Guessing is safe here: a
  wrong root predicts a wrong header and fails loudly, rather than passing a
  wrong index.

- **2026-09-28** — **First run found a half-finished ingest, live.** Against
  `default`: dense 2090/4020 chunks with headers, sparse 3950/4020, and 1860
  content hashes differing between the two halves. Both counts are 4020 and
  the id sets match exactly, so every cheaper check — point count, file
  size, "did it run today" — reports this as fine. It is not fine: it is a
  mismatched hybrid serving production, and roughly half the dense index is
  still pre-header. See STATUS for the re-run.

- **2026-09-28** — **The 5-second timeout nobody chose.** `qdrant-client`
  only forwards a timeout to httpx when it is given one, and Atlas never gave
  it one, so every Qdrant call in the project ran on httpx's 5s default. An
  upsert batch is 100 points of 1536 floats, four documents go concurrently,
  and the cluster is a region away — 5s is under the honest round trip rather
  than a margin over it. `QdrantConfig.timeout_seconds` defaults to 60.

  The visible cost was the 2026-09-28 ingest: 37 of 155 files lost to
  WriteTimeout, ReadTimeout, ConnectTimeout and `[Errno 8] nodename nor
  servname provided`. The chunks had already been embedded when the write
  failed, so the tokens were spent and nothing was stored, and the run
  reported the whole thing as warnings and a non-zero exit while writing 118
  files successfully. Partial, plausible, and unnoticed until
  `verify_index.py` compared the two halves.

- **2026-09-28** — **The retry goes on the single-call method, not the public
  one.** `QdrantDenseIndex.upsert` loops over batches of 100. Decorating it
  would have made one timed-out batch resend every batch that already landed
  — correct, because upserts are idempotent, but it multiplies the write
  under exactly the conditions that made it fail. So `_upsert_batch`,
  `_retrieve_hashes`, `_scroll_page`, `_create_collection` and friends exist
  as private one-call methods purely to give the decorator something with the
  right granularity. `reraise=True` so the indexer still logs `WriteTimeout`
  per file rather than tenacity's `RetryError`, since that text is the
  diagnosis.

  The query path gets a shorter ladder — 3 attempts, 0.5-4s against the
  ingest's 5 and 1-20s — because a query has someone waiting on it. Surviving
  a DNS blip is worth one retry; a cluster that is down should fail the
  request.

- **2026-09-28** — **What is retryable is decided by whether the server
  answered.** `UnexpectedResponse` means Qdrant replied, so it is judged on
  status: 429 and 5xx retry, 4xx does not, because a malformed request will
  be malformed again. Everything else — `ResponseHandlingException`,
  `httpx.TransportError`, `OSError` — is a transport fault and retries. The
  `OSError` arm is there for `socket.gaierror`, which arrives unwrapped and
  is what a home resolver does when several TLS connections open at once.

- **2026-09-28** — **A single file cannot work out its own corpus root, so
  the callers pass one.** `index_path(path)` with no `source_root` puts the
  whole path into every context header: a file ingested on its own got
  "data corpus fastapi tutorial body" where the same file ingested with its
  directory got "tutorial body".

  The wasted tokens are not the problem. A different header is a different
  `content_hash`, so re-ingesting one file of an existing corpus re-embeds it
  with headers none of its neighbours have, and the corpus quietly disagrees
  with itself. From the ingest's side it looks like a file that changed.

  `index_path` still honours `None`, because a caller that means it should
  get it — the fix belongs in the two places that passed `None` only because
  there was nothing else to pass. `scripts/ingest.py` and the `/ingest` route
  now default a bare file to its parent, `index_directory` takes a
  `source_root` override for the case where a subtree is being re-indexed
  into a corpus rooted higher up, and the script prints the root it chose on
  every run including `--dry-run`. Printing it is the actual fix: the default
  is right for a file that stands alone and wrong for one deep in a tree, and
  only the person running it knows which.

- **2026-09-28** — **`seed_demo.py` handed a directory to `index_path`.**
  `index_path` calls `get_loader`, which dispatches on suffix, and a
  directory has none — so `make demo` raised `No loader registered for ''`
  before indexing anything. Now `index_directory`. Found while auditing the
  other `index_path` call sites for the source-root fault; unrelated bug,
  same line of code.

- **2026-09-28** — **The deploy refuses to bake an index it has not
  checked.** `scripts/deploy_gcp.sh` runs `verify_index.py` over every
  namespace under `data/index/` before `gcloud builds submit`, and exits
  non-zero if any of them disagrees with its Qdrant collection.

  The build is the last moment this is checkable. The BM25 file travels
  inside the image; the dense vectors do not — they are live the instant an
  ingest finishes. Two halves of one corpus, deployed by different mechanisms
  at different times, and the state in between answers every query and scores
  badly rather than failing. Twice now: an ingest to the wrong namespace on
  the 27th, and 37 files lost to Qdrant timeouts on the 28th. Both looked
  like successful runs.

  It gates the build, not the deploy, because a deploy of an existing tag
  cannot see inside that image — `SKIP_BUILD=1` therefore says the index was
  not checked instead of pretending it was. `SKIP_VERIFY=1` exists and
  announces itself. The check costs nothing to run, so the escape hatch is
  for a reason, not for a hurry.

- **2026-09-28** — **`--dataset` has no default, because no default is
  correct.** `run_eval.py` defaulted to `eval_data/sample_dataset.json`, the
  30-question HR set. A bare run in this repo scored those questions against
  the FastAPI index and produced a full, well-formatted report of zeros, then
  a confident `Overall winner` against a 15-sample FastAPI baseline. Nothing
  in the output looked broken. Only the token count did.

  Pointing the default at `fastapi_dataset.json` instead would have moved the
  trap rather than removed it — the right dataset depends on what was
  ingested into the namespace, which a default cannot know. So the flag is
  required, and the error lists the datasets in `eval_data/`: the fault was
  someone getting the wrong one without ever choosing.

- **2026-09-28** — **The dataset is checked against the namespace, not just
  against a corpus.** `check_dataset` asks whether labels name real files.
  That is a different question from whether those files are in the index
  about to be queried, and a dataset can pass the first perfectly while being
  pointed at the wrong namespace.

  `indexed_doc_keys` reads the namespace's BM25 file and builds the same key
  set `corpus_doc_keys` builds from disk — there is a test asserting the two
  agree, because a checker that disagrees with the matcher rejects labels
  that would have scored. Zero labelled rows resolving is a hard error: that
  is the wrong corpus, not a corpus with gaps. Some resolving is a warning
  naming the rows, because a partly-ingested corpus still measures something.

  It reads the JSON rather than constructing `BM25SparseIndex`, whose
  constructor re-tokenises every chunk to rebuild the ranker. The check needs
  one field and runs before anything is spent; it should not cost seconds of
  CPU to answer. `None` for a missing file is deliberately distinct from an
  empty set — nothing ingested here is not the same claim as a namespace that
  holds other documents.

- **2026-09-28** — **`eval_retrieval.py` loaded the cross-encoder before it
  read the dataset.** `NamespaceRegistry(SharedComponents(settings))` was
  built first, which pulls the reranker weights into memory, and only then
  was the dataset opened and checked. Same ordering principle as `run_eval.py`
  and the same fix: dataset first, registry second. A dataset that cannot
  score is worth finding out about before seconds of CPU, not after.

- **2026-09-28** — **The comparator's docstring claimed a check that did not
  exist.** `comparator.py` said "If the datasets differ, the comparison is
  invalid and we raise ValueError." There was no check of any kind, and
  `compare()` would declare an **Overall winner** between a 30-question HR
  run and a 15-question FastAPI one. Worth recording separately from the fix:
  the comment was the reason nobody looked, and a false comment is worse than
  no comment because it answers the question that would have found the bug.

- **2026-09-28** — **Three comparability checks, ordered by what they
  prove.** `compare()` now raises `DatasetMismatch` on:

  1. **Different sample ids.** Derived from `sample_results`, so it needs no
     new field and applies to all twelve reports already in
     `eval_data/reports`. Different rows means different denominators.
  2. **Different dataset fingerprint.** The only one that catches a
     *relabelling*. On 2026-09-27 nine of fifteen rows were relabelled while
     the file kept its name and all fifteen ids — every number before that
     edit stopped being comparable with every one after, and neither the
     name nor the ids showed it.
  3. **Different dataset name.** Weakest, and only used to make the error
     message name the two files.

  `dataset_fingerprint` covers the dataset name and, per sample, the id, the
  question, the label set and the out-of-scope flag — the inputs the metrics
  read. It excludes `ground_truth_answer` because no metric reads it, so
  `fq-010`'s rewrite changed no score and must not invalidate a comparison.
  There is a test asserting that exclusion, and it is the test that has to
  change first if an answer-correctness judge is ever added.

  The runner fills both fields rather than the caller, because a caller that
  forgets produces a report that looks complete and compares wrongly.

- **2026-09-28** — **A report that predates the fingerprint gets a note, not
  a refusal.** Refusing would break comparison against all twelve stored
  reports, none of which can be re-run for free. So an empty fingerprint
  produces a note carried on `ComparisonResult` and printed under the table
  as **Unverified**. Not knowing whether two runs match is a different state
  from knowing they do, and this whole class of fault is the second being
  assumed from the first — so it is said out loud in the artefact itself,
  where the number gets quoted from, rather than in a log.

- **2026-09-28** — **The grader now judges what the generator will be
  handed.** `grader.py` sliced `chunks[:5]` under the comment "more adds
  noise", which was true when `reranker.top_k` was also 5 and the slice was
  the whole window. `top_k` went to 15 on 2026-09-23 and the slice did not,
  so for five days the grader answered "is the top 5 sufficient?" while the
  pipeline acted on the answer as though it were "is the context
  sufficient?" — and the generator received all 15 either way.

  The asymmetry is the argument. A grader shown less than the generator
  cannot call a window sufficient that is not, because everything it saw is
  really there. It calls a window insufficient whenever the answer sits
  below the slice, which is a retry the pipeline did not need. `fq-005`
  triggered one while `tutorial/body` was already in the window. Since the
  retry union shipped on 2026-09-27 that costs a round trip rather than a
  document, so this is a cost and latency item, not a correctness one.

  `grader.context_chunks` defaults to None, meaning the whole window.
  `--set grader.context_chunks=5` reproduces the old behaviour exactly, and
  there is a test asserting it does, because that flag is the A/B.

- **2026-09-28** — **Widening it is not obviously cheaper, so it has to be
  measured.** At this corpus's mean chunk length (484 characters, ≈121
  tokens over 4,020 chunks) going from 5 chunks to 15 adds roughly 1,200
  prompt tokens per grade call. Against that, every prevented retry saves a
  full retrieval plus another grade call — 2 to 6 seconds of the grading
  stage in the stored reports, which accumulate across retries.

  There is also a real risk in the other direction: a grader shown fifteen
  chunks of which one is relevant may score *lower* through dilution than
  the same grader shown five. That is an empirical question about the
  prompt, and arguing it from first principles is how the original `[:5]`
  got its comment. Default changed, A/B flag provided, run it.

- **2026-09-28** — **`total_tokens_used` only counts the generation call.**
  Noticed while pricing the above: `runner.py:206` stashes
  `generation.prompt_tokens + completion_tokens` and nothing else, so the
  router, decomposer, grader and both judges have never appeared in a
  report's token figure. Every "tokens" number in STATUS and DECISIONS is
  therefore a generation-only number, which is consistent across runs and so
  still valid for comparison — but it is not the run's cost, and it was read
  as one. Filed in BACKLOG rather than fixed here.
