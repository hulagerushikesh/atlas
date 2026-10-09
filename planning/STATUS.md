# Status — 2026-10-09 (v0.1.0, M2 done, M3 at 3 of 4)

## One line

**M2 is done and shipped: https://atlas.hulage.in is live and current** —
Cloud Run rev **00011-xcm** (image `58e4e00`, deployed 2026-10-07) in
`asia-south1` behind a Vercel rewrite, Qdrant Cloud with 4,020 chunks,
Firestore for keys and the spend counter, four Secret Manager secrets,
₹200/mo budget alert, and a `*/10` keep-warm job. `main` and production
agree. **M3 is at three of four exit criteria**; the two that are open fail
on form rather than substance, and the one that is objectively met is still
unticked — see *M3 exit criteria* below.

## Blocked on you

- [ ] **Two M3 criteria need a wording call, not work (₹0 either way).**
      Criterion 1 asks for "≥ 2 changes merged, each with `eval-compare` in
      the PR" and criterion 4 for a "`learning/` module 09 exercise" per
      change. Both are met in substance and neither in form: this repo has
      **zero merge commits — no pull request has ever existed** — and no
      DECISIONS entry cross-references `learning/09`. The evidence the
      criteria wanted is there and stronger than a PR body (16 stored
      before/after eval reports in `eval_data/reports/`, ~20 dated write-ups
      in DECISIONS.md). Three options: reword both criteria to match how this
      project actually works, add the module-09 cross-references, or leave
      M3 at 3 of 4. Criterion 2 is objectively met (recall 0.667 → 0.9378)
      and is still unticked for the same reason — nobody has said so.

- [ ] **Re-ingest `default` — ≈₹6.45, needs a spend go-ahead.** It lands
      `eccc01d` (the `fq-002` chunk is dated three years stale without it)
      and turns the deploy's index gate green. Until then every deploy needs
      `SKIP_VERIFY=1`, which is correct but is a standing exception — see
      *the index gate* below.

- [ ] **HyDE arm — ≈₹6.24, needs a spend go-ahead.** Built, off, and still
      the only unmeasured thing in M3. Run at `--concurrency 1` (4 hangs the
      laptop) and pass the mode explicitly, because both the code and
      `.env.example` default to `concat`:

      ```
      .venv/bin/python scripts/run_eval.py \
        --dataset eval_data/fastapi_dataset.json --namespace default \
        --run-name hyde-on --set hyde.enabled=true --set hyde.mode=replace \
        --concurrency 1 \
        --compare eval_data/reports/baseline-16_20261003-182853.json
      ```

- [x] ~~**Keep-warm ping for the cold start**~~ **done 2026-10-07.** Job
      `atlas-keepwarm`, `*/10 * * * *` against `/health`, created and
      verified firing. Chosen 2026-09-29 over `min-instances=1`
      (Rs.650-700/month) at roughly Rs.0-20/month: the service has no
      `cpu-throttling: false` annotation, so an idle instance is not billed
      for CPU and the ping costs only the requests. The cold path it hides
      measured **49 s** (`atlas_startup` → `atlas_ready` is 2.9 s of it; the
      rest is image pull plus the torch/transformers import into a 2.15 GB
      image that bakes the reranker weights). **The 60 s cold-start budget is
      conditional on this job staying enabled** — delete it and that ceiling
      stops being a budget and becomes the normal user experience.

- [x] ~~**Deploy — `main` was 25 commits ahead of the live image**~~ **done
      2026-10-07.** Image `58e4e00`, rev `atlas-api-00011-xcm`, build 3m1s,
      serving 100% of traffic. Everything listed as unshipped is now live:
      the per-model spend cap, the SSE error event, and the `ca94db8`
      `str(exc)` redaction — that last one is **in the image but unproven in
      production**, because forcing it needs a broken upstream key. Verified
      live on one query (₹0.31): faithfulness 1.0, `unsupported_claims: []`,
      grader 1.0 with 0 retries, 15 chunks, 11 citations, HyDE confirmed off
      (`hypotheses: []`, `hyde_ms: null`), warm `/query` 13.7 s, warm
      `/health` 1.15 s. Needed `SKIP_VERIFY=1`; see *the index gate*.
      **`POST /query` takes `query`, not `question`** — `question` returns
      422 with the body echoed back.

- [x] ~~Add OpenAI credits~~ → switched to Gemini (2026-09-20). Same AI Studio
      key as sextant, in `atlas/.env` only. Daily spend cap: ₹50–100 across
      both projects — state ₹ before every paid step.
- [x] ~~Revoke the compromised OpenAI key~~ → all keys on the account
      revoked 2026-09-20.
- [x] ~~Revoke the compromised Qdrant Cloud key~~ → cluster deleted
      2026-09-20; key died with it. `.env` uses local Docker Qdrant.
- [x] ~~Resume bullets~~ → applied 2026-09-23 to `resume_v5a.tex`: four
      bullets, GitHub + atlas.hulage.in links, deployed numbers (P 0.43 ·
      R 0.78 · F 1.00, 4,020 chunks, 340 tests). Compiled with tectonic,
      still 2 pages; `resume_v5a_preview_5.pdf`.
- [x] ~~Run the Cloud Run deploy~~ → four revisions rolled 2026-09-23; the
      sandbox blocks `gcloud run deploy`, so every deploy is
      `scripts/deploy_gcp.sh` run by hand.
- [x] ~~Billing budget alert~~ → ₹200/mo on `atlas-rag-rush`, alerts at
      50/90/100%.
- [x] ~~DNS~~ → Cloudflare CNAME `atlas` → `<hash>.vercel-dns-017.com`,
      DNS-only. Certificate issued; all four routes 200.
- [x] ~~Full eval run~~ → run 2026-09-23 (₹0.3, 83 s, 15,341 tokens).
      P 0.431 · R 0.778 · F 1.000 · AR 0.825; every delta from the relabelled
      baseline below the 0.02 floor. README carries it as the "Deployed"
      column.

## Where things stand

| Area | State | Evidence |
|---|---|---|
| Ingestion (A) | Done, **proven idempotent live** (uuid5 ids, skip-before-embed) | 6c52438; 155 docs / 4,021 chunks, re-run 0.3 s |
| Hybrid retrieval (B) | Done, dense path proven against real Qdrant local mode | `tests/integration/test_qdrant_roundtrip.py` (90b3432) |
| Orchestration (C) | Done; evidence provenance + per-stage timings exposed | f17a28e |
| Evaluation (D) | **Run live x16.** Current baseline (`default`, 16 rows, 2026-10-03): P 0.4667 - R 0.9378 - F 1.000 - AR 0.8377 - **AC 0.7105**, $0.0709 (~Rs.6.24) a run, all on `gemini-3.1-flash-lite`. The `default` namespace is **not** behind any more — context headers are live in it (4016/4020 chunks, verified 2026-10-07), which is why this run reproduces the old `headers` experiment's precision exactly. Context metrics skip a row only when it has no relevant document: `fq-016`, added 2026-09-29, is the first declared out-of-scope row, so the `applicable=False` guards are reachable again. The dataset is checked before a run is paid for (`atlas.evaluation.dataset`): every label must resolve to something the matcher could match, and an empty label set must carry `metadata.out_of_scope: true`. Reports carry per-stage p50/p95 and the model that served the run. **The retrieval-only harness has mispredicted four times running** - no grader, no retry, no decomposition; use it only to ask whether a document is reachable at all | `eval_data/reports/ctx-headers_20260927-120939.json` |
| API & observability (E) | Done; **daily spend cap** (`BUDGET_DAILY_USD`, 429 past it, `/health.budget`); keys in SQLite or **Firestore** (`AUTH_STORE`) | auth, rate limit, cache, Prometheus, streaming |
| Console | Rebuilt as React app (Vite + shadcn + Motion), cartographic design | baabc6e; `DESIGN.md` |
| Landing | Rebuilt in the same app, served at `/` | 2475b45 |
| Quality gate | ruff + mypy clean, **583 tests** green, 93% cov. **There is no CI** — `.github/workflows` does not exist, so this local gate is the only gate and "green" is only ever a claim about one laptop | `make lint typecheck test` |
| Corpus | Full FastAPI docs: 155 markdown files, ingested into `atlas_default` + `data/index/default/bm25_index.json` | fetch with `--max-files 1000` |
| Deploy | **LIVE and current: https://atlas.hulage.in** (Cloud Run rev **00011-xcm**, image `58e4e00`, Vercel rewrite, Let's Encrypt cert); keep-warm `*/10`; budget ₹200/mo. Production reads **Secret Manager, not `.env`** — and `:latest` resolves when a revision is created, so adding a secret version does nothing until a `gcloud run services update` forces a new one | `docs/deploy.md`, `scripts/deploy_gcp.sh`, `proxy/` |
| Latency & cost budget | **Agreed 2026-10-08 (`planning/BUDGET.md`) and enforced in code 2026-10-09.** `comparator.compare()` measures warm p50/p95 and run cost against ceilings *and* regression allowances, and withholds "Overall winner" on a breach | `6f8f039`; BUDGET.md |
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

## Measured (2026-09-27, `top_k` 15, additive retry + capped merge + context headers)

Context metrics are over **all 15 rows**. They used to exclude `fq-015` as
out of scope; it is not out of scope, and the exclusion was hiding a good
retrieval — see below.

**Every context number below was recomputed after the dataset audit of
2026-09-27.** All fifteen reference answers were read back against the corpus,
claim by claim, and nine rows needed something. They are not the figures
quoted earlier today, twice. The recomputation is offline and exact —
`scripts/replay_context_metrics.py` replays a stored report's chunk ids
against any label set for Rs.0 — so no run was repeated to produce this.

| Metric | 09-24 | retry fix | capped merge | + headers | live 09-28 | **+ correctness** |
|---|---|---|---|---|---|---|
| Context precision | 0.3733 | 0.3477 | 0.3867 | 0.4667 | 0.4667 | **0.4667** |
| Context recall | 0.9244 | 0.9333 | 0.9333 | 0.9378 | 0.9378 | **0.9378** |
| Faithfulness | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | **1.0000** |
| Answer relevance | 0.8277 | 0.8253 | 0.8271 | 0.8328 | 0.8347 | **0.8276** |
| **Answer correctness** | — | — | — | — | — | **0.7440** |
| Tokens / eval | 37,599 † | 44,224 † | 35,928 † | 39,461 † | 39,319 † | **167,740** |
| Cost / eval | ~Rs.0.73 † | ~Rs.0.86 † | ~Rs.0.70 † | ~Rs.0.77 † | ~Rs.0.77 † | **~Rs.5.92** |
| Latency p50 | 15.0 s | 11.0 s | 10.0 s | 9.7 s | 10.3 s | **10.8 s** |

The `live 09-28` column is the first **measured** run against the audited
dataset on the shipped `default` namespace —
`eval_data/reports/grader-window-5_20260928-160041.json`. It reproduces the
replayed precision and recall to four decimals, which is the strongest
available check on the replay method: an offline recomputation predicted
0.4667 / 0.9378 and a paid run returned 0.4667 / 0.9378. Every figure in the
`+ headers` column was earned without spending anything, and now it is
confirmed. It is also the first report to carry a dataset fingerprint, so
every future comparison against it is checked rather than assumed.

The `+ correctness` column is the same pipeline again
(`correctness-first_20260928-211522.json`), with the fifth metric added and
nothing else changed. Precision, recall and faithfulness came back
identical to four decimals for the third time; answer relevance moved
-0.0071, inside its own noise. That makes it a clean baseline for the
correctness number rather than a second variable.

**Faithfulness 1.0000 and correctness 0.7440 in the same column is the whole
point of the fifth metric.** Every answer stayed inside the context it was
given; roughly a quarter of what the references assert did not survive the
trip. Four metrics said this pipeline was doing well and one says a quarter
of the substance is missing or wrong — see DECISIONS 2026-09-28 for the two
rows that scored 0.000, one of which is a cited, grounded, confidently wrong
answer about a Python version.

> **The table above is the last comparable set. Read this first.**
> On 2026-09-29 the dataset gained a sixteenth row, `fq-016`, the first
> declared out-of-scope question. Both fingerprints moved —
> `486ff3dab9b597b5` → `80c1a625bc7b7533` and `5c60f37e17520115` →
> `c9c564cc06b1eb3d` — so the comparator will refuse to diff anything above
> against anything measured from now on, correctly: a mean over sixteen rows
> is not a mean over fifteen. Precision and recall are unaffected in
> arithmetic (the row is inapplicable to both), faithfulness and answer
> relevance only if the pipeline refuses, and `answer_correctness` moves
> either way. A router probe says it will not refuse, so the next run should
> read **0.6975**; that is a prediction, written down to be checked.
>
> **Checked 2026-10-03: it read 0.7105**, 0.013 above the prediction, and
> the router did not refuse. See the 16-row baseline below.

**`fq-002`, that Python row, was chased on 2026-09-29 and is not a retrieval
failure.** The chunks carrying the current facts were never in the candidate
set, and no chunk in the corpus states FastAPI's current Python floor at
all — the reference answer is a subtraction over three changelog entries
3,100 lines apart. It was labelled `simple_factual` / `easy`, which is why it
read as a ranking bug; it is now `multi_hop` / `hard`. Neither fingerprint
moved, so the report above stays comparable. A real bug did surface
underneath it — `heading_trail` dropped the release heading from the four
chunks of the flat-H2 `0.104.0` block, including the one that was cited — and
is fixed. See DECISIONS 2026-09-29.

The last column's token and rupee figures are **real**. Every other column's
are marked †.

† **Generation calls only.**
The same report records **101 model calls** for those 15 samples; fifteen
were generation and the other eighty-six had their tokens dropped on the
floor. The router, decomposer, grader, faithfulness checker, both judges and
every embedding are missing from both rows, so the real cost of a run is
several times what is written here. The ratios between columns hold — they
all counted the same wrong thing — which is why nobody caught it.

Fixed on 2026-09-28 (`atlas/usage.py`): tokens are counted on the provider,
per model, and a report now carries a per-model breakdown with a price. The
first run under it measured **167,740 tokens across 160 calls — 4.3x the
generation-only figure** — so a run costs about Rs.5.9, not Rs.0.77. Every
rupee figure recorded in this repo before 2026-09-28 understates by roughly
that factor. The stage latencies in these reports are the honest per-sample
p50, not the run's concurrency-wide wall clock.

All four runs served entirely by `gemini-3.1-flash-lite`, so the deltas are
changes in the pipeline and not in the model.

`answer_correctness` grades the generated answer against the reference and
is the first metric to read `ground_truth_answer`. First run 2026-09-28:
**0.7440**, on a run whose other four numbers reproduced the baseline
exactly.

**Precision is still the day's result, +0.093, and it is no longer monotone.**
The retry fix *costs* precision, 0.3733 → 0.3477: it widens the window, and
two rows that the old labels scored as structural zeros or near-zeros —
`fq-015` at 0.5333 → 0.3158 and `fq-007` at 0.4667 → 0.3659 — are now visible
paying for it. The cap gets it back (0.3867) and the headers take it to
0.4667. The ordering claim "three changes, each positive on precision" is
withdrawn; the shape is cost, refund, gain.

**Recall did not move all day: 0.9244 → 0.9378, +0.013, inside the 0.02
floor.** Third restatement of this figure and the third time it has come out
below the floor.

**`fq-015` was never out of scope.** `advanced/websockets.md` is in the corpus
and its "WebSockets client" section names React. The pipeline answers the
question from it, with citations and faithfulness 1.000 — the run that was
being discarded as a structural zero was scoring 0.4667 precision and 1.000
recall. The `applicable=False` guards in both context metrics were
unreachable from the dataset as it stood that day. They are reachable again:
`fq-016`, added 2026-09-29, is a declared out-of-scope row, which is exactly
what the guards are for.

`fq-007` recall is 0.6667 in the headers run, not 0.5 — it has three labelled
documents now, not two, because `OAuth2PasswordBearer` is defined on
`tutorial/security/first-steps` and neither old label carried it.

~~**The headers are not deployed and not even in the default namespace.**~~
**That was wrong and is retired.** `scripts/verify_index.py` showed on
2026-10-07 that `default` carries them on **4016 of 4020 chunks**, baked by
the 2026-09-28 ingest — so no re-ingest was ever owed for the headers, and
the ₹6.45 carried in these notes was for work already done. It also explains
a coincidence that was not one: the 16-row baseline scores P 0.4667 against
the headers experiment's P 0.467 because it is the same treatment. The
`headers` namespace is a redundant second copy of the same 4,020 chunks;
both are baked into the image.

**Production confirmed it independently.** The single verification query on
`58e4e00` returned citation [1] = `tutorial/query-params-str-validations.md`
— the page this project documented as *never retrieved at all* before
headers ("not ranked low, absent") — at rank 1, on the question that could
not find it. Precision was the case for shipping and recall was not; that
still holds, and the page being reachable at all is the mechanism.

The "~7 s" in older notes is from 2026-09-20, measured differently, and is not
a baseline this can be diffed against.

## Measured (2026-10-03) — the current baseline, 16 rows

`eval_data/reports/baseline-16_20261003-182853`, `default` namespace, ₹6.24.
**Every report older than this one is incomparable**: `fq-016` moved both
dataset fingerprints on 2026-09-29, and the comparator refuses the diff
rather than printing a meaningless one.

| Metric | Value |
|---|---|
| Context precision | **0.4667** |
| Context recall | **0.9378** |
| Faithfulness | **1.0000** |
| Answer relevance | **0.8377** |
| Answer correctness | **0.7105** |
| Cost / run | **$0.0709 ≈ ₹6.24** |

Precision and recall reproduce the 15-row `grader-window-5` run to four
decimals, for the third time. The 0.6975 correctness prediction filed before
`fq-016` was added came back **0.7105** — the prediction was written down to
be checked, and it was within 0.013.

Per-sample latency from the same run, **nearest-rank** percentiles as
`reporter.percentile` computes them:

| Stage | p50 ms | p95 ms |
|---|---|---|
| retrieval | 3,287 | 8,298 |
| faithfulness | 1,952 | 2,974 |
| generation | 1,609 | 2,608 |
| grading | 1,322 | 4,236 |
| routing | 1,126 | 2,179 |
| decompose | 1,049 | 1,323 |
| **total** | **10,053** | **17,072** |

Production, one live query on `58e4e00` (2026-10-07): 7,986 tokens,
**$0.0034677 ≈ ₹0.31**, warm `/query` 13.7 s. That cost figure is **n=1** and
is the weakest number in the budget; firming it up is free on the next eval
run that happens anyway.

## M3 exit criteria

| Criterion | State |
|---|---|
| ≥ 2 changes merged, each with `eval-compare` **in the PR** | substance yes, **form no** — zero merge commits, no PR has ever existed |
| Faithfulness or context recall up beyond the noise floor | **met** (0.667 → 0.9378) and still unticked |
| p95 latency and $/query inside an agreed budget | **ticked 2026-10-08**, and enforced in code 2026-10-09 |
| `learning/` module 09 exercise written up for each | substance yes, **form no** — no DECISIONS entry cites `learning/09` |

The two "form no" rows are the *Blocked on you* wording call at the top. The
substance behind them: 16 stored before/after reports, and of the three
shipped retrieval changes two carry real measured gains (`top_k` 5→15,
recall 0.778→0.900; context headers, P 0.387→0.467) while `e095c7b` records
that the tokeniser was worth nothing end to end — which is a result, and
still leaves ≥ 2.

## The index gate, and why every deploy currently overrides it

`scripts/deploy_gcp.sh` runs `scripts/verify_index.py` before building and
refuses on a mismatch. It exists because of two real incidents: a
wrong-namespace ingest on 2026-09-27, and 37 of 155 files lost to Qdrant
timeouts on 2026-09-28 (dense 2090/4020 against sparse 3950/4020).

It fails on `main` today, and the override is the right call:

- dense and sparse agree perfectly in both namespaces — 4020 = 4020, 0 id
  drift, **0 of 4020 content hashes differ**;
- the only failing check is the third, header text against what current code
  would write: **4 chunks** of `release-notes.md` lack the
  `0.104.0 (2023-10-18) > Upgrades > Internal` heading that unshipped commit
  `eccc01d` adds to the heading trail;
- `apply_context_headers` is imported by **`ingestion/indexer.py` only** and
  is never on the query path, so this cannot affect serving.

That is drift between code and an already-baked index, which is exactly what
the gate's own "if you know why the two differ" clause is for. Only the
≈₹6.45 re-ingest clears it, and until then `eccc01d`'s `fq-002` date fix stays
dormant in the tree.

## Known defects

See [BACKLOG.md](BACKLOG.md). Nothing blocks M2. Post-M1 sweep closed six
items: stale tail chunks, manifest noise, eval labels, `--set` overrides,
daily spend cap, console markdown.

## Recent sessions

- 2026-10-09 (budget made enforceable, ₹0) — `compare()` was metric-only: it
  printed **Overall winner** from `aggregate_scores` and never read
  `stage_ms` or `token_usage`, both of which the report already stored, so a
  change buying +0.03 recall at twice the p95 would have won with the
  regression printed nowhere. It now measures warm p50/p95 and run cost
  against both a ceiling and a regression allowance and renders **Overall
  winner: withheld** on a breach, naming the breach and the DECISIONS entry
  it needs. Writing it found two defects in the budget accepted the day
  before, both mine: every percentile in BUDGET.md was *interpolated* where
  the reporter is nearest-rank (p50 10,062 → 10,053, p95 16,859 → 17,072,
  inside the ceilings either way, so the M3 tick stands), and the per-stage
  sub-ceiling table had no row for `decompose` at all. 583 tests, 93%,
  `comparator.py` at 100%. `6f8f039`.
- 2026-10-08 (budget drafted and accepted, ₹0) — the hard question was what
  "not worse" measures against. Taking M1 literally (≈7 s, ≈₹0.03) would
  make M3 uncloseable or force reverting accuracy one measured PR at a time,
  because that pipeline scored recall 0.667 against today's 0.938. So the
  M1→now increase (+44% p50, ≈10x cost, +0.271 recall) is ratified in
  writing and the budget runs forward from the 2026-10-03 measurement.
  `planning/BUDGET.md`, M3 criterion 3 ticked. `18d7882`, `e649122`.
- 2026-10-07 (deploy + keep-warm + key rotation, ≈₹0.31) — rev 00011-xcm,
  image `58e4e00`, `main` and production finally in agreement after a
  25-commit backlog. The Gemini key was dead and had been 401ing every live
  query with `ACCESS_TOKEN_TYPE_UNSUPPORTED`; rotated to secret version 3,
  which required a `services update` afterwards because `:latest` resolves at
  revision creation. Keep-warm job created and verified. Two findings worth
  more than the deploy: the headers *were* already live in `default` (the
  note saying otherwise was wrong for over a week), and **Atlas has no CI**,
  so every "gate green" in this file is a claim about one laptop.
- 2026-10-03 (new 16-row baseline, ₹6.24) — `baseline-16`. AC came back
  0.7105 against the 0.6975 filed in advance. HyDE did not run: it is
  CPU-heavy enough to hang the laptop at the default `--concurrency 4`.
- 2026-09-23 (M2 done + M3 opened, ≈₹1.1) — four Cloud Run revisions. Three
  defects only the cloud could find: missing Qdrant payload indexes, the
  missing `.gcloudignore`, and a Redis client cached before its ping (the
  service reported `degraded` forever). Two more only the proxy could find: the
  catch-all rewrite does not match `/`, and the StaticFiles mount's 307 for
  `/app` leaked the run.app host. Spend moved to Firestore after the live
  service reported `spent_today_usd: 0.0` for a query it had just charged.
  `atlas.hulage.in` fronted by a Vercel rewrite because Cloud Run refuses
  domain mappings in `asia-south1`. M3 started: identifier-aware BM25
  tokeniser, recall 0.726 → 0.798 and precision 0.529 → 0.486 on the new
  retrieval-only harness — but the full eval then showed it is worth nothing
  end to end (recall 0.778 either way, `fq-005` won and `fq-012` lost), because
  query decomposition already recovers what better tokenisation recovers. Kept
  for the router's non-decomposing "simple" branch.
- 2026-09-23 (M2 infra, ≈₹1) — GCP project `atlas-rag-rush` created and
  billed, five APIs on, Artifact Registry + Firestore in `asia-south1`, four
  Secret Manager secrets (all piped from `.env`, none typed), IAM for the
  compute SA. Image `0fdd0b2` built by Cloud Build (~3 min). Corpus ingested
  into the Qdrant Cloud cluster: **4,020 chunks** (one stale `index.md` tail
  chunk pruned, so cloud and BM25 now agree exactly). Two defects the cloud
  found that local could not: missing payload indexes (Qdrant Cloud 400s
  filtered deletes) and the missing `.gcloudignore` (build lost `data/index/`).
  313 tests. Left to do: `gcloud run deploy`.
- 2026-09-20 (M2 prep, ₹0) — `KeyStore` protocol: SQLite + Firestore
  backends (`AUTH_STORE`), `/keys` reachable before the first key exists
  (was a chicken-and-egg with auth on — found by the image smoke test);
  production Dockerfile (CPU torch, reranker weights + BM25 baked in, `PORT`),
  `scripts/deploy_gcp.sh` + `make deploy-gcp`, Fly config removed,
  `docs/deploy.md` rewritten for Cloud Run. Auth middleware got its first
  tests. Image builds and boots locally (2.15 GB arm64). GCP project not
  yet created — needs a yes.
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

- ~~**One paid pass, two arms**~~ **half done 2026-10-03.** The baseline arm
  ran (`baseline-16`, ₹6.24) and settled two of the three questions: the
  16-row baseline exists, and the 0.6975 correctness prediction came back
  0.7105. **The HyDE arm did not run** — it is CPU-heavy enough to hang the
  laptop at the default `--concurrency 4` — so it is still the only
  unmeasured thing in M3, at ≈₹6.24 and `--concurrency 1`. The pre-filed
  predictions in BACKLOG, including the one saying HyDE should make `fq-016`
  worse, are still unchecked.
- **Teach `EvalResult` per-sample `token_usage`, ₹0 to write.** It is the
  last gap in budget enforcement: run-wide totals are contaminated by the
  metric judges (~7.8 chat calls a sample against production's ~4), so cost
  *per query* stays hand-checked while latency and run cost are automatic.
  Piggyback the measurement on whichever eval run happens next.
- **Atlas has no CI.** Adding it is ₹0 and would turn "the gate is green"
  from a claim about this laptop into a checked fact. Every gate command has
  to run there, not three of four — that is how sextant's CI was red for 17
  days while five commits reported green.
- **HyDE is built and off** (2026-09-29, Rs.0). `HYDE_ENABLED=false`;
  `--set hyde.enabled=true`, `--set hyde.mode=replace` for the paper's
  variant. Nothing about it is measured. Two previous interventions aimed
  at `fq-012` — context headers and decomposition — both measured at zero
  on that row, so a third one existing is not evidence.
- ~~`retrieval.top_k` 20 → 40~~ run 2026-09-24 and **rejected**: recall
  0.9000 → 0.9333 in aggregate, but per sample `fq-012` and `fq-007` were
  bought with `fq-005` breaking outright, and precision fell 0.3022 → 0.2711
  at an unchanged window width. Still rejected after the 2026-09-27 relabel,
  though `fq-012`'s gain there was larger than anyone knew: 0.200 → 0.600,
  the best that sample has ever scored. A broken question still vetoes it.
- ~~A stronger reranker~~ run 2026-09-25 and **rejected**. L-12 bought no
  recall end to end and put retrieval p50 at 18 s under concurrency;
  `bge-reranker-base` (278M) scored worse than the 23M model it would replace.
- ~~"`fq-005` and `fq-012` are the same slot"~~ **retracted 2026-09-25.** It
  was a story told over three experiments that shared a symptom, and ₹0.06 of
  retrieval dumps refuted it: `tutorial/body` sits at ranks 5, 6, 8, 10 and 13
  for `fq-005`, while `tutorial/query-params-str-validations` never appears at
  all for `fq-012`. One target is abundant, the other absent. The real cause
  was a retry that replaced context instead of adding to it — fixed in
  `68e1810` and **confirmed 2026-09-27**: recall 0.9000 → 0.9333, precision
  also up, only the retrying samples moved.
- ~~Cap and globally rerank the sub-query merge~~ **shipped 2026-09-27.**
  Round-robin across sub-queries, then cut to one window re-ranked against the
  original question. Precision 0.3477 → 0.3867, recall unchanged at 0.9333,
  tokens 44,224 → 35,928 (Rs.0.86 → Rs.0.70). The predicted risk — that the cap
  would take `fq-007` back to 0.5 recall — did not happen.
- ~~Grader window~~ **de-prioritised 2026-09-27.** `grader.py:82` still grades
  `chunks[:5]` of 15, but once the top five are ranked against the original
  question it stopped mis-grading: `fq-007` went from three grader calls to
  one. It is a small latency item now, not a quality one.
- ~~Deterministic chunk headers~~ **built and measured 2026-09-27, not
  shipped.** Source path in words plus the heading trail, prepended to each
  chunk's indexed text. Re-ingested into a `headers` namespace for Rs.6.45
  (priced at Rs.6.42 beforehand by chunking locally). Precision 0.3867 →
  0.4667, the largest single gain of the milestone. Recall 0.9333 → 0.9378,
  a move inside the noise floor. **Shipping it to the live namespace is another
  ~Rs.6.45 re-ingest and needs a go-ahead.** Two things sold it that did not
  hold: BM25's rank for `fq-012` got *worse*, 11 → 15, and the recall gain
  and the "`fq-012` recalled for the first time" headline were both artifacts
  of that sample's one-document label. Precision is what it actually bought.
  See DECISIONS.
- ~~Dataset loader guards~~ **done 2026-09-27.** `atlas.evaluation.dataset`
  refuses a dataset whose labels resolve to nothing, or whose empty label set
  nobody declared, before `run_eval.py` builds the pipeline — so the fault
  whose only symptom is a report full of plausible zeros now costs Rs.0 to
  find. Caught one on its first run (`oos-001` in the HR sample set, real but
  undeclared). Does not catch an incomplete label set or an unsupported
  answer; those still need reading.
- ~~Relabel `fq-012`~~ **done 2026-09-27**, and then the whole set was
  audited the same way: read each reference answer's claims back against the
  corpus, `grep` for each one. Nine of fifteen rows needed something —
  `fq-012` widened 1 → 5, `fq-006`/`fq-007`/`fq-014` widened by one page each,
  `fq-008` *narrowed* (a required page supported none of its claims),
  `fq-003`/`fq-004`/`fq-005`/`fq-009`/`fq-010` reworded off APIs and status
  codes the corpus does not contain, and `fq-015` found not to be out of scope
  at all. Every context number in STATUS and README recomputed offline with
  `scripts/replay_context_metrics.py` (Rs.0, no model calls). Nothing was
  re-run. `metadata.label_rationale` on each changed row records why.
- LLM-written contextual headers — **re-price before starting.** The ~₹15
  figure in earlier notes does not survive arithmetic: 4,020 chunks x ~2.5k
  input tokens is ~10M tokens, nearer ₹200 without prompt caching.

## Earlier plan (M3 as opened)

M3 — retrieval quality. Three questions miss end to end
(`fq-007 tutorial/security/oauth2-jwt`, `fq-011 tutorial/response-model`,
`fq-012 tutorial/query-params-str-validations`) and `fq-008
advanced/custom-response` is partial at 0.67.

The tokeniser result says the constraint is the **five slots**, not the
retriever's ability to find the document: `fq-005` and `fq-012` traded places
at the rank-5 boundary rather than both fitting. So the next experiment is the
rerank `top_k` sweep (5 / 10 / 15, `run_eval.py --set reranker.top_k=10`),
which changes the number of slots directly. Then profiling the retrieval
stage, ~5.1 s of the six.

Measure with `scripts/eval_retrieval.py` (≈₹0.01) to reject, then confirm with
the full eval (≈₹0.3) before publishing — the cheap harness runs the
un-decomposed path and flatters retrieval changes. Ask before anything
billable; budget in INR.
