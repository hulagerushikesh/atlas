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
