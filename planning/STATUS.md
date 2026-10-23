# Status — 2026-10-21 (v0.1.0, all four milestones done, 16 of 17, CI green)

**16 of the 17 ROADMAP exit criteria are ticked (≈94%), and all four
milestones are marked done as of 2026-10-14.** That fraction is the project's
progress number; count it from `planning/ROADMAP.md` rather than quoting it
from anywhere else. The one criterion still open is M1's resume-bullets line,
which is yours.

**There is no M5, on purpose.** Opening one is a decision, not a backlog
item. The pool to pick from is *Parked* at the bottom of ROADMAP.md, the
unbuilt M4 scope items listed there (key management UI, usage page per key,
dataset upload for per-corpus eval, layout-aware PDF, evidence export), and
[BACKLOG.md](BACKLOG.md). Until one is opened, what's next is *Blocked on
you* below.

How to explain the project to someone else — what gap it addresses, in prose
rather than bullets — is [PITCH.md](PITCH.md). Its numbers are a snapshot and
say so; this file is where they are current.

**HyDE is measured and closed — both arms, both rejected.** `concat`
2026-10-17, `replace` 2026-10-18. It was the last
unmeasured idea in M3 and the one M3's reworded criterion 4 was reserved
for, so the prediction was written down and committed before the run was
paid for (`9eed3f2`), then scored against the result. The verdict held and
three of eight numbers did not. Its other clause — that `replace` would do
worse than `concat` — held, and for the mechanism it named. See DECISIONS
2026-10-17 and 2026-10-18. Cost: **₹12.55** on the 17th, **₹6.94** on the
18th, **₹19.49** total.

## One line

**M2 is done and shipped: https://atlas.hulage.in is live and current** —
Cloud Run rev **00016-ckx** (image `2190db6`, deployed 2026-10-19) in
`asia-south1` behind a Vercel rewrite, Qdrant Cloud with 4,020 chunks,
Firestore for keys and the spend counter, four Secret Manager secrets,
₹200/mo budget alert, and a `*/10` keep-warm job. `main` and production
agree. **All four milestones are marked done as of 2026-10-14.** M3 closed at
four of four once the two criteria that were failing on form rather than
substance were reworded to ask for what this repo actually produces — see
*M3 exit criteria* below. M4 closed at three of three, earned on 2026-10-13
and marked a day later; most of its *scope* was never built and ROADMAP.md
says which parts and why that still counts. The single remaining open
criterion in the whole roadmap is M1's resume-bullets line, which is yours.

## Blocked on you

- [x] ~~**Re-ingest `default`**~~ **done 2026-10-17, ≈₹0.005.** Not ≈₹6.45:
      the indexer skips on `content_hash`, so the job was 4 chunks and 433
      tokens, not 4020. `eccc01d` is landed, the gate is green 4020/4020, and
      `SKIP_VERIFY=1` is no longer a standing exception. ~~A redeploy is now
      owed~~ — **discharged 2026-10-18**: revision `atlas-api-00014-5vp`
      carries image `ac132a9`, so the two halves agree in production again.
      See *the index gate*.

- [x] ~~**HyDE arm**~~ **`concat` measured 2026-10-17, ₹12.54; verdict: stays
      off.** +0.0619 context precision against −0.0238 answer correctness, so
      nobody wins on quality, and warm p95 21,400 ms against a 20,000 ms
      ceiling (+56.3% on a +15% allowance). The comparator withholds the
      winner. Full numbers and the scored prediction are in DECISIONS
      2026-10-17.

- [x] ~~**HyDE `replace`**~~ **measured 2026-10-18, ₹6.94; worse than
      `concat`, and HyDE is now closed.** Ran clean in 5 min once Chrome was
      actually quit. +0.0845 context precision but **−0.0245 recall** (over
      the floor, where `concat` stayed under it), warm p50 **+41.2%** and
      p95 **+138.6%** — both ceilings breached. Head to head against
      `concat` it is a **tie on all five metrics** and +40.4% p95, so it
      buys nothing and costs 8.6 s of p95 not buying it. The recall loss is
      `HyDEConfig`'s own argument confirmed: a bare hypothesis strips the
      question's rare terms out of the BM25 half. **Both arms measured, both
      rejected.**

- [x] ~~**Keep-warm ping for the cold start**~~ **done 2026-10-07.** Job
      `atlas-keepwarm`, `*/10 * * * *`, created and verified firing.
      Retargeted from `/health` to `/warm` 2026-10-21, with
      `--attempt-deadline=120s`; the recreate command is in
      `docs/deploy.md` because the job is hand-made and the gcloud default
      deadline is 60 s, which is under the load it has to wait for. Chosen 2026-09-29 over `min-instances=1`
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
| Evaluation (D) | **Run live x16.** Current baseline (`default`, 16 rows, 2026-10-03): P 0.4667 - R 0.9378 - F 1.000 - AR 0.8377 - **AC 0.7105**, $0.0709 (~Rs.6.24) a run, all on `gemini-3.1-flash-lite`. The `default` namespace is **not** behind any more — context headers are live in it (4016/4020 chunks, verified 2026-10-07), which is why this run reproduces the old `headers` experiment's precision exactly. Context metrics skip a row only when it has no relevant document: `fq-016`, added 2026-09-29, is the first declared out-of-scope row, so the `applicable=False` guards are reachable again. The dataset is checked before a run is paid for (`atlas.evaluation.dataset`): every label must resolve to something the matcher could match, and an empty label set must carry `metadata.out_of_scope: true`. Reports carry per-stage p50/p95 and the model that served the run. **The retrieval-only harness has mispredicted four times running** - no grader, no retry, no decomposition; use it only to ask whether a document is reachable at all | `eval_data/reports/baseline-16_20261003-182853.json` |
| API & observability (E) | Done; **daily spend cap** (`BUDGET_DAILY_USD`, 429 past it, `/health.budget`); keys in SQLite or **Firestore** (`AUTH_STORE`) | auth, rate limit, cache, Prometheus, streaming |
| Console | Rebuilt as React app (Vite + shadcn + Motion), cartographic design | baabc6e; `DESIGN.md` |
| Landing | Rebuilt in the same app, served at `/` | 2475b45 |
| Quality gate | ruff + mypy clean, **773 tests** green locally (CI runs the same target with no corpus on disk, so the one listing-staleness guard skips there and says so; the other two dataset guards run, off a tracked file listing. Last confirmed green: run `39548535057` on `d0828d8`, 713 + 1 skip), 93% cov. **CI since 2026-10-10, green since 2026-10-12** (`.github/workflows/ci.yml`): runs the three make targets on a pinned `ubuntu-26.04` / Python 3.11, plus the console's `npm run lint` and `npm run build`, plus a check that the committed `static/` matches a fresh build. Five claims, each `if: always()` so one failure does not hide the rest | `make lint typecheck test` |
| Corpus | Full FastAPI docs: 155 markdown files, ingested into `atlas_default` + `data/index/default/bm25_index.json` | fetch with `--max-files 1000` |
| Deploy | **LIVE and current: https://atlas.hulage.in** (Cloud Run rev **00025-bnj**, image `87caf12`, **startup probe on `/warm`**, Vercel rewrite, Let's Encrypt cert); keep-warm `*/10` **on `/warm`** (verified 2026-10-21, GET, ENABLED); budget ₹200/mo. Production reads **Secret Manager, not `.env`** — and `:latest` resolves when a revision is created, so adding a secret version does nothing until a `gcloud run services update` forces a new one | `docs/deploy.md`, `scripts/deploy_gcp.sh`, `proxy/` |
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
| Answer relevance | 0.8277 | 0.8253 | 0.8271 | 0.8328 | 0.8347 | **0.8276** ‡ |
| **Answer correctness** | — | — | — | — | — | **0.7440** ‡ |
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

‡ **Fifteen rows — not the current figure for these two metrics.**
`correctness-first_20260928-211522.json`, dataset fingerprint
`486ff3dab9b597b5`. Answer relevance and answer correctness are the only
metrics `fq-016` moves, and the 16-row baseline below reads AR **0.8377** /
AC **0.7105** (`baseline-16_20261003-182853.json`, fingerprint
`80c1a625bc7b7533`). Precision 0.4667, recall 0.9378 and faithfulness 1.0000
are identical to four decimals in both reports, which is why only these two
cells carry the mark. Quote 0.8276 / 0.7440 as history, 0.8377 / 0.7105 as
current.

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

**All four are ticked as of 2026-10-14.** Two of them were reworded that day
rather than newly earned, and that is recorded in ROADMAP.md on the criteria
themselves, not only here.

| Criterion | State |
|---|---|
| ≥ 2 research-backed changes shipped, each with a stored report pair and a dated write-up | **ticked 2026-10-14** — reworded from "merged … in the PR" |
| Faithfulness or context recall up beyond the noise floor | **ticked 2026-10-12** (0.667 → 0.9378, more than ten times the 0.02 floor) |
| p95 latency and $/query inside an agreed budget | **ticked 2026-10-08**, and enforced in code 2026-10-09 |
| Each change traced to its `learning/` module 09 item, with before/after | **ticked 2026-10-14** — reworded, and it asks for less than the original |

What the two rewordings changed, so a reader can disagree with them:

- **Criterion 1 lost the PR.** It asked for changes *merged* with
  `eval-compare` *in the PR*. This repo has **zero merge commits and no pull
  request has ever existed**; it is one person committing to `main`. The PR
  was a venue, not the evidence, and the evidence is better than a PR body
  would be: 16 stored before/after reports in `eval_data/reports/` plus
  ~20 dated write-ups in DECISIONS.md, all still checkable. Qualifying
  changes: `reranker.top_k` 5 → 15 (recall 0.778 → 0.900) and deterministic
  context headers (P 0.3762 → 0.4524, R 0.9286 → 0.9643, `fq-012` recalled
  for the first time). A third, identifier-aware BM25 tokenisation, shipped
  and `e095c7b` records it as worth nothing end to end — a result, and the
  reason the bar is two.
- **Criterion 4 lost the prediction, which is a genuinely lower bar.**
  `learning/exercises.md` §09 asks for a paper write-up ending in "the
  `make eval-compare` result you would expect" — made *before* paying. The
  criterion now asks only that each shipped change name the module 09 item
  it came from and carry its measured before/after. Both cross-references
  were added to DECISIONS.md the same day: `top_k` → §1 *Long context vs
  RAG*, which names the change by hand; context headers → §5 *Ingestion
  quality*, shipped as the deterministic cousin of the LLM-written version
  that section lists. The honest reason for dropping the prediction half is
  that this project's predictions kept being wrong — the cheap harness
  mispredicted four times running, and the mechanism argued for the context
  headers was not the one that worked — so writing predictions after the
  fact for shipped changes would be worth less than the corrections already
  are. The exercise as written stands for HyDE, which is module 09 §4,
  built, off, and still the only unmeasured thing in M3.

## The index gate — green since 2026-10-17

`scripts/deploy_gcp.sh` runs `scripts/verify_index.py` before building and
refuses on a mismatch. It exists because of two real incidents: a
wrong-namespace ingest on 2026-09-27, and 37 of 155 files lost to Qdrant
timeouts on 2026-09-28 (dense 2090/4020 against sparse 3950/4020).

It passed clean on 2026-10-17: counts agree, no id drift, **4020 of 4020
content hashes agree**, and **4020 of 4020 headers** match what current code
writes, on both halves. `SKIP_VERIFY=1` is no longer a standing exception and
the next deploy should not pass it.

What cleared it was re-ingesting `data/corpus/fastapi/release-notes.md`
alone, with `--source-root data/corpus/fastapi`. **433 tokens, ≈₹0.005.**
This file priced that job at ≈₹6.45 for months and the figure was wrong: it
is the price of re-embedding all 4020 chunks, and `DocumentIndexer` asks
`unchanged_ids()` before it embeds anything, so only the 4 chunks `eccc01d`
changed were ever going to be paid for. `eccc01d` said so in its own commit
message — "a re-ingest re-embeds those four and skips the rest on
content_hash, so shipping is free" — and the estimate here was written
without reading it.

**One consequence, and it pointed at you. Resolved 2026-10-18.**
`Dockerfile:34` bakes `data/index/` into the image, so production's sparse
half came from image `58e4e00`, built 2026-10-07, while its dense half is
Qdrant Cloud, which the re-ingest updated on the 17th. For those 4 chunks of
`release-notes.md` the two halves disagreed in production for a day: BM25
matched the undated text, dense matched the dated one. The chunk ids are
unchanged so fusion still worked and nothing errored, which is precisely why
it needed writing down rather than noticing later. Revision
`atlas-api-00014-5vp` closed it. `verify_index` will not catch this state,
and correctly so — it checks the index a build is about to bake, not the one
already serving, and the window between those two is exactly this.

## Known defects

See [BACKLOG.md](BACKLOG.md). Nothing blocks M2. Post-M1 sweep closed six
items: stale tail chunks, manifest noise, eval labels, `--set` overrides,
daily spend cap, console markdown.

## Recent sessions

- 2026-10-23 (streaming usage accounting; **₹0**) — a streamed `/query`
  charged the daily cap and incremented **none** of `COST_USD`,
  `TOKEN_USAGE` or `log_usage`. It hid for 90 days because the one sink that
  worked is the only one whose failure looks like money going missing; the
  rest fail quietly and flatteringly, as a smaller `/metrics` total and a
  `cost / query` mean taken over the non-streaming subset only. The same gap
  was on the **non-streaming failure path**, so a failing deployment's spend
  was real, capped and invisible everywhere else.

  All four sinks now live in one function, `_charge`, called by all three
  sites. Adding the missing calls to each path separately would have left
  two hand-maintained copies of the list that caused this. Streaming also
  logs `query_complete` under the **same event name** as the standard path,
  with `stream` and `failed` fields — a different name would rebuild the
  same blind spot in the logs.

  Four mutations checked, **the first being the pre-fix code restored
  exactly**; all four fail the new tests. Found on the way: no test had ever
  asserted the route writes a per-key usage record — the fixture disables
  auth, so the sink BUDGET's `cost / query` is computed from was entirely
  uncovered. Pinned directly now. 766 → **773 tests**, 93.70%. Not yet
  deployed: live is still `atlas-api-00025-bnj`. See DECISIONS 2026-10-23.

- 2026-10-22 (`cost / query`, n=1 → n=34; **₹0**) — BUDGET's plan for this
  said to recompute from the next eval run, and that plan was wrong: an eval
  sample pays two LLM judges a production query never calls, so it answers a
  different question. The right source was already stored and had never been
  read — `FirestoreKeyStore.log_usage` has been accumulating per-key
  `usage.{total_queries,cache_hits,prompt_tokens,completion_tokens}` across
  instances and restarts since the store shipped. 37 queries, 3 cache hits,
  **n=34 paid**, 207,212 tokens → **$0.0022564 ≈ ₹0.199 a query**. The n=1
  figure was **1.54x the mean**; headroom under the $0.005 ceiling goes from
  +44% to +122% and no budget decision changes.

  Trusted only after a cross-check: the live instance's `/metrics` token
  counters, priced through `atlas.cost`, reproduce its
  `atlas_estimated_cost_usd_total` to ten decimals.

  **The distribution is still missing** — Firestore stores sums, so a
  per-query ceiling is being judged against a mean. Five slices bound it at
  $0.000474 … $0.0034677, 7.3x, all under the ceiling. `query_complete` now
  logs tokens and cost per query so Cloud Logging yields a real p95 later for
  nothing; 3 mutations of those fields each fail the new tests. Two
  accounting gaps filed, not fixed: a streamed query charges the spend cap
  but no usage counter, and `log_usage` is fire-and-forget. 764 → **766
  tests**. See DECISIONS 2026-10-22.

  Deployed the same day as `atlas-api-00025-bnj` (image `87caf12`, build
  `ceee4593`, 2m34s) and **confirmed live** with one query (₹0.20, approved):
  the logged line read 6911 / 1095 / **0.00336865**, matching the response
  body exactly and the Firestore spend delta ($0.003369) to six significant
  figures — body, log and cap all agree, which is the whole accounting chain
  checked end to end. That query took the counters to **n=35**, mean
  **$0.0022882 ≈ ₹0.201**, and is the second-dearest ever observed, so the
  expensive end of the distribution is a real region and not one odd draw.
  The startup probe logged exactly one `reranker_loaded_lazily` (44.25 s)
  inside startup, as designed.

- 2026-10-22 (AR/AC labelling; **₹0**) — the BACKLOG item saying STATUS
  contradicts itself on answer relevance and correctness was **wrong about
  the kind of problem**, and acting on its prescription would have destroyed
  a real measurement. 0.8276 / 0.7440 is `correctness-first_20260928-211522`
  over fifteen rows; 0.8377 / 0.7105 is `baseline-16_20261003-182853` over
  sixteen. Different dataset fingerprints, so neither is stale and the
  comparator refuses to diff them. They read as interchangeable because the
  other three metrics — 0.4667 / 0.9378 / 1.0000 — are identical to four
  decimals in both reports, `fq-016` being inapplicable to the context
  metrics and not refused by the pipeline.

  The defect sitting beside them was real: the Evaluation (D) evidence cell
  quoted the 16-row figures and cited `ctx-headers_20260927-120939.json`, a
  retrieval-only report from six days earlier that contains none of them.
  Both AR and AC cells in the progression table now carry a ‡ naming their
  report, row count, fingerprint and current replacement; the evidence cell
  points at the baseline it quotes. See DECISIONS 2026-10-22.

- 2026-10-21 (cold start; **₹0**) — the 36.9 s cold start was attributed,
  never measured, and the attribution was a third wrong. Two parts of the
  BACKLOG entry were also simply stale: `atlas-keepwarm` (`*/10` → `/health`)
  has been ENABLED since 2026-09-29 with an unbroken run of 200s, and Cloud
  Run logged three container starts in two days, all deploys, none from
  scaling to zero — **no ordinary visitor has paid a cold start for weeks**.
  "~2.15 GB" was the uncompressed size; the pull is **554.6 MB**.

  `atlas_boot_profile` now splits the block Cloud Run reports as one. The
  timestamp lives in `atlas/__init__.py`, not `asgi.py`, because
  `atlas.api.__init__` imports `create_app` eagerly — the first attempt
  timed from `asgi.py` and reported **0.00 s** for the import it existed to
  measure. Split, in-container with the image already local: ~21 s image
  pull and **12.41 s of imports**.

  Both halves fixed. `LazyCrossEncoderReranker` defers torch, transformers
  and sentence-transformers until something reranks and warms the model
  behind the bound port — **12.41 s → 2.55 s**, model arriving 8.1 s later
  in the background, landing page served in 7 ms meanwhile. A query that
  arrives early waits rather than being answered with the fused order and
  no sign the reranker was missing. And the trailing `chown -R` was
  **81.9 MB of the 554.6 MB image** — chown rewrites every inode, so the
  baked-weights tree shipped twice; ownership is set at creation now and
  that layer is gone. Verified by building and running the image locally,
  not by reasoning about the Dockerfile.

  **Deployed as `atlas-api-00018-zfc`, and the deploy refuted two of my own
  claims.** Measured: **36.9 s → 11.7 s** instance start → `atlas_ready`,
  against a predicted ~26 s. There is no ~21 s image pull —
  `pull_and_interpreter` is **0.72 s** and only ~0.64 s separates "Starting
  new instance" from the fork, because Cloud Run streams image blocks on
  demand rather than pulling up front. The 12.41 s in-container figure came
  from a warm local image where no streaming happens, so the pull/import
  split I derived from it was an inference stated too firmly: the old
  33.9 s was almost entirely the torch import. Removing the duplicated
  81.9 MB layer is still right, just not where the seconds were.

  And the background warm **does not run on Cloud Run**: the service uses
  default request-scoped CPU allocation, so a thread loading the model
  between requests is frozen the moment a response is sent — three requests
  in 4.6 minutes and no `reranker_loaded_lazily`. `POST /warm` does it
  inside a request instead, with `atlas-keepwarm` retargeted from `/health`
  to `/warm`; separate from `/health` because a health check that blocks
  once per cold start trips alarms. (The 8.08 s I quoted for that load was
  a local container on a laptop; on Cloud Run's one vCPU it is ~37 s — see
  the 2026-10-21 verification entry.)

  **And `/warm` shipped behind the auth middleware.** Rev
  `atlas-api-00019-qrn` answered `atlas-keepwarm`'s own unauthenticated URL
  with **401** — an endpoint written to fix a cold start, unreachable by the
  one caller it exists for. Nothing in the suite caught it because nothing
  asserted which paths the middleware lets through; it does now. `/warm` is
  public for the same reason `/health` is, and it cannot spend: it makes no
  model calls and every call after the first returns immediately.

  Cold start across three measured starts: **36.9 s before, 11.7 s and
  14.1 s after**.

  **761 tests at 93.68%**, gate green, `static/` untouched. BACKLOG: one
  closed, open drops to **2**.

- 2026-10-22 (M1 resume bullets — **the last exit criterion**; **Rs.0**) —
  the Atlas block in `customise resume/resume_v5a.tex` rewritten against this
  repo's figures instead of remembered ones, typeset with `tectonic` to check
  it still fits (2 pages before, 2 after, Atlas still on page 1), backup at
  `resume_v5a.tex.bak-20261022`. **All 17 ROADMAP exit criteria are now
  ticked.**

  Four numbers in the old bullets had gone stale, and sourcing them properly
  is most of what this task was:

  | claim | was | now |
  |---|---|---|
  | context recall | 0.78 | **0.9378** (from 0.667) |
  | tests | 340 at 90% | **764 at 93.68%** |
  | `src` LOC | 7,400 | **11,541** |
  | cost / query | `~$0.0005` | **$0.005 enforced ceiling** |

  The cost line was wrong by about **7x** and is the one worth dwelling on.
  The honest measured figure is $0.0034677 — but BUDGET.md records that as
  **n=1**, one production query with a 1,178-token answer, and names it the
  weakest number in the file. A single-sample number does not belong on a
  resume as though it were an average, so the bullet cites the ceiling that
  is actually enforced in code instead. Same for answer relevance and
  correctness: STATUS gives two different current values for both (see
  BACKLOG), so neither was used. Precision, recall and faithfulness agree
  across every source and carried the bullet.

  Also added: the cold-start and significance work, which did not exist when
  these bullets were last written — 36.9 s → 11.7 s, the startup probe, and
  the exact paired Wilcoxon test rejecting a +0.013 "win" that rested on 1 of
  15 rows.

- 2026-10-22 (startup probe on `/warm`; ~Rs.6) — an instance is no longer
  routed traffic until its cross-encoder is loaded. Cloud Run's default is
  a TCP check, so readiness used to mean "uvicorn bound" (~11 s) with 43 s
  of model still to come, charged to whichever request arrived first.

  | | before (`00023-486`) | after (`00024-5ht`) |
  |---|---|---|
  | first `/query` on a fresh revision | 48.82 s | **12.21 s** |
  | where the load happens | inside a request | inside startup (38.08 s) |
  | revision ready in | ~15-20 s | **73 s** |

  A 12-query burst forced the scale-up case. The second instance took five
  requests, logged **exactly one** load (34.81 s) during startup, and
  completed all five only after it — no query ran against an unloaded
  model, which was the defect. **What that does not buy:** those five
  requests were routed to the instance the moment it was created and
  waited 66-116 s regardless. For a request arriving *during* a scale-up,
  waiting on the probe and paying the load in-request are roughly the same
  wall clock. The deploy-path win is real and measured; a burst-latency
  win is not claimed.

  **The cost is scale-to-zero.** A visitor arriving with no instance
  running now waits ~73 s for the landing page against the 11 s the lazy
  loading bought. `atlas-keepwarm` is the only thing preventing it, which
  makes that job load-bearing for a second, independent reason — if it is
  ever disabled the probe has to come off with it. Recorded in
  `docs/deploy.md` and DECISIONS.

  Three tests added for a property that was previously unpinned and is now
  load-bearing: `/warm` answers **200** when the model fails to load, when
  the reranker is disabled, and on GET. The failure goes in the body, not
  the status — an error status would stop the instance ever becoming ready,
  and with `--max-instances 2` that is the service. Verified by mutation:
  changing the endpoint to 503-on-failure fails exactly the new test.
  **766 tests.**

- 2026-10-22 (does a second vCPU help the cold start? **no**; ~Rs.2.2) —
  measured instead of assumed, with `atlas-keepwarm` paused so nothing
  could warm an instance behind the test, and reverted afterwards.

  | | cpu=1 (`00021-pk7`) | cpu=2 (`00022-snb`) |
  |---|---|---|
  | `atlas_imports_and_app` | 10.24 s | 9.72 s |
  | `reranker_loaded_lazily` | **43.38 s** | **43.49 s** |
  | unwarmed `/query` | 48.82 s | 46.29 s |
  | warm `/query` | 12.07, 10.15 s | 8.77, 10.11, 9.12 s |

  The model load moved **0.11 s** — it is a sequential torch import and a
  weight load, so a second core has nothing to do — while doubling the
  billing rate on every request-second. The warm column looks better at
  cpu=2 and is not evidence: n is two and three, the ranges overlap, and
  the Gemini call dominates. **Reverted to `cpu: '1'`**, probe env var
  removed, live config byte-for-byte what it was before.

  **The second-instance case stopped being hypothetical.** Rev
  `atlas-api-00023-486` logged `reranker_loaded_lazily` twice — 39.68 s for
  the instance `/warm` reached and **49.76 s** on a second instance Cloud
  Run started by itself, under four sequential requests. A real `/query`
  took **44.6 s** against it. The keep-warm warms one instance; it cannot
  warm the one that does not exist yet. See DECISIONS 2026-10-22 for the
  startup-probe option that would fix it and why it is not taken yet.

  Two caches also showed themselves: the first two queries of a batch
  returned in **0.13 s and 0.11 s** because they repeated earlier
  questions, which is the cache working and would have been read as a
  cpu=2 win if I had not noticed the questions were duplicates.

  Spend for the whole experiment: **$0.0256** of the $0.60 daily budget.

- 2026-10-21 (verifying `/warm` in production; **₹0**) — `atlas-api-00020-pcg`
  answers `POST /warm` with `{"reranker":"loaded","was_already_loaded":false,
  "seconds":37.04}` instead of 401, and every call after it returns in
  0.15–0.40 s. `atlas-keepwarm` is ENABLED, `*/10`, already on `/warm`. The
  cold-start fix is live end to end.

  **The 37.04 s is the part worth keeping.** `startup-cpu-boost` is `true`
  on this service and the container has **one vCPU**, and the boost only
  applies while the instance is *starting* — so moving the model load off
  the startup path also moved it out of the boost. The load costs ~37 s in a
  request against the ~25 s it cost inside the old 36.9 s eager start. The
  landing page is up in 11 s either way, which is the trade `/warm` exists
  to make, but **an instance that takes a `/query` before anything warms it
  now waits longer than it used to**: ~11 s boot + up to ~37 s load against
  a flat ~37 s before. The keep-warm covers the steady state; it does not
  cover a second instance spun up by a burst (`maxScale: 2`,
  `containerConcurrency: 8`).

  Logs also corrected a claim I had written into the code. `reranker_loaded_lazily`
  reported **54.1 s** while the handler reported 37.04 s, because the lifespan
  background task had started the load 17 s earlier and got nowhere until my
  request woke the instance. So the background warm is not inert on Cloud
  Run — it is a head start that cannot cash in without traffic. The comments
  in `app.py` and `health.py` said "never completes"; they now say what was
  measured.

- 2026-10-21 (paired Wilcoxon test; **₹0**) — a metric delta now has to clear
  two gates to be called a result: its measured rerun floor **and** an exact
  two-sided Wilcoxon signed-rank test over the per-sample scores every report
  has always stored (`src/atlas/evaluation/significance.py`). The two answer
  different questions and each is wrong alone. Re-running `baseline-17` vs
  `router-scope` under both **retracts yesterday's own headline**:
  `context_precision +0.0134` cleared the 0.01 floor honestly and is carried
  by a single row of fifteen, where the smallest p the test can return is
  1.000, so the overall verdict goes from **B** back to **tie**. The other
  direction is gated too — 0.800 → 0.802 across all fifteen rows is p=0.0001
  and still inside `answer_relevance`'s rerun noise, so the floor vetoes it.

  **Three corrections to the entry that asked for this.** `scipy` is *not* a
  dependency; it installs transitively under `sentence-transformers`, and the
  comparator ships inside the API image, so the test is implemented in-repo
  and scipy is declared in the `dev` extra as an independent oracle instead
  (2,000 random tie-free cases must agree to 1e-12). Tie-free only, because
  scipy's exact method is derived for distinct ranks while metric scores tie
  constantly — the implementation here conditions on the observed rank
  vector and stays exact either way. And "not significant" was the wrong
  word for most of this dataset: below six differing rows the smallest
  achievable p is above 0.05, so those are reported as **underpowered**, in
  their own table column and their own `Too few rows:` notes block, rather
  than as ties.

  **739 tests at 93.82%**, gate green, `static/` untouched. BACKLOG: one
  closed, open drops to **3**. **Nothing to deploy** — the comparator is an
  offline tool and is not in the serving path; production stays on rev
  `atlas-api-00017-x5r`.

- 2026-10-21 (per-metric noise floors; **₹0**) — the comparator's one
  significance threshold is now five measured ones, and measuring it
  corrected the item that asked for it.

  **The mechanism was not what the name said.** Across every paired row where
  two runs produced byte-identical answer text, `answer_correctness` and
  `faithfulness` moved **0.0000**. The judges are deterministic. The variance
  enters earlier: the *generator* writes a different answer from the same
  chunks, and correctness grades facts-present over a handful of facts, so
  one reworded sentence swings a row by 0.5. I had filed this as the judge's
  non-determinism. It is the generator's, amplified by a coarse metric.

  **0.02 was wrong in both directions at once**, measured off stored reports
  for ₹0 by restricting to rows where two runs retrieved byte-identical
  evidence — same input twice, so the movement between them is the floor:

  | metric | measured | floor | note |
  |---|---|---|---|
  | `context_precision` | 0.0000 | 0.01 | deterministic; floor is resolution, not noise |
  | `context_recall` | 0.0000 | 0.01 | same |
  | `faithfulness` | 0.0000 | 0.05 | **unvaried** — every observation 1.00, so an assumption |
  | `answer_relevance` | 0.0020 | 0.01 | per-row jitter ±0.04 cancels in the mean |
  | `answer_correctness` | 0.0565 | 0.08 | three pairs only, hence headroom |

  Ten times too lax for relevance, three times too tight for correctness.
  Re-running `baseline-17` vs `router-scope` under the new floors flips
  `context_precision` +0.0134 from "ns" to a **win** and the overall verdict
  from tie to **B** — that gain was always real, because the metric has no
  rerun noise at all.

  **New `scripts/measure_noise_floor.py`** re-derives the table free and
  exits non-zero if a floor has fallen under its measured noise, so this
  cannot rot quietly. Two things it had to learn: a `-replayed` report is a
  corrected copy of one run, and pairing it against its source reports the
  correction as noise — that alone put correctness at 1.0000 and would have
  set a floor from a bug fix, so `replay_non_answer_metrics.py` now stamps
  `replayed_from` and the measurement skips superseded runs; and a metric
  that never left one value prints as **unvaried**, not deterministic,
  because a column of zeroes means opposite things in those two cases.

  **Honest limit:** a floor answers "is this bigger than a rerun", not "is
  this more than one sample". That +0.0134 precision win rests on one row,
  `fq-013`. The paired Wilcoxon test the comparator's docstring has always
  pointed at is now filed as its own item — 16 paired rows is enough for the
  exact test and `scipy` is already a dependency.

  **714 tests at 93.66%**, gate green, `static/` untouched. BACKLOG: one
  closed, one filed, open stays at **4**. **Nothing to deploy** — the
  comparator is an offline tool and is not in the serving path; production
  stays on rev `atlas-api-00017-x5r`.

- 2026-10-19 (router out-of-scope; **₹7.01**) — the Stripe row refuses, and
  the harness can finally see that it did. Two changes, because the first
  alone made the published numbers *worse*.

  **The prompt.** `out_of_scope` meant "clearly unrelated to the domain",
  with one example — "What is the capital of France?" — which teaches the far
  case and nothing about the near one. The near one is what failed, and the
  model named the mechanism itself: it called `fq-016` a pattern "documented
  in the FastAPI **ecosystem**". True of the ecosystem, false of the corpus.
  The rule is now about what a correct answer would have to be *about*, with
  a second example (exporting financial records to QuickBooks) that reuses
  the subject of the first simple example, so the contrast carries the scope
  rule rather than a topic, and names no product in any eval row. The "when
  in doubt prefer simple" tie-break stays — it exists for the 2026-10-13
  over-refusal — narrowed to subjects the domain plausibly owns.

  **The harness.** The run that proved the prompt works also showed the eval
  could not score it. The generator refuses with `REFUSAL`; the router
  refuses with the pipeline's out-of-scope message; all four readers of a
  refusal checked only the first string. On `fq-016`:

  | metric | as run | why | replayed |
  |---|---|---|---|
  | `answer_correctness` | **0.000** | reasoning read "the pipeline answered instead of refusing" — it refused | **1.000** |
  | `answer_relevance` | 0.408, counted | relevance of a refusal is undefined | excluded |
  | `faithfulness` | **1.000**, counted | audited "This question appears to be outside the scope..." as two supported claims | excluded |

  Both strings now sit together behind `is_non_answer`, with a test asserting
  the pipeline emits the very constant the metrics check — two private copies
  in two modules is how they drifted silently.

  **Measured, not asserted.** New `scripts/probe_router.py` runs the router
  alone — 16 dataset rows plus 6 controls, ≈₹0.3 against the full harness's
  ≈₹6.3 — and exists because the last router-prompt change measured at
  exactly zero. Scope **19/21 → 21/21**, over-refusals **0 → 0**. The two it
  fixed are `fq-016` and an Amazon S3 question present in no prompt and no
  dataset, so the rule generalised rather than an answer being recalled.
  Full eval `router-scope_20261019-202434` vs `baseline-17`, after replaying
  the three declined-row metrics for ₹0 (new
  `scripts/replay_non_answer_metrics.py`, whose metrics are built with a
  provider that raises on any call, so the ₹0 is enforced):

  | metric | baseline-17 | router-scope | verdict |
  |---|---|---|---|
  | answer_correctness | 0.7452 | 0.7583 | tie |
  | answer_relevance | 0.8382 | 0.8380 | tie *(15 shared rows)* |
  | context_precision | 0.4533 | 0.4667 | tie |
  | context_recall | 0.9378 | 0.9378 | tie |
  | faithfulness | 1.0000 | 1.0000 | tie *(15 shared rows)* |
  | warm p50 | 10,338 ms | **9,016 ms** | −12.8% |

  **`baseline-17` stays the published baseline** and no figure in README or
  STATUS needed restating. The +0.0131 on correctness is not a gain: it nets
  `fq-016`'s +0.0625 against **0.0494 of judge noise on three rows that ran
  an identical pipeline over identical chunks** (`fq-012` 0.50 → 0.00,
  `fq-014` 1.00 → 0.83, `fq-015` 1.00 → 0.88). That spread is filed — it is
  more than twice the comparator's 0.02 significance floor, and it is what
  printed "Overall winner: A" before the replay. Read any correctness delta
  under ~0.05 on this set as a tie.

  One prediction of mine was wrong and is worth the record: `fq-013` stopped
  decomposing as a side effect, which looked like a recall risk because it
  needs two pages. Recall held at 1.000 and its precision rose **0.73 →
  0.93**. Only two rows changed code path at all, which is what made the rest
  of the diff legible as noise.

  **709 tests at 93.65%**, gate green, `static/` untouched. BACKLOG: one
  closed, one filed, open stays at **4**.

  **Shipped 2026-10-21: rev `atlas-api-00017-x5r`, image `bda328e`, ≈₹0**
  (2m54s build, free tier, no re-ingest). The pre-build index check passed
  clean on both namespaces — 4020 dense / 4020 sparse, 0 id-only on either
  side, 0 content hashes differing, headers on 4020/4020. Verified free:
  `/app` 200, `/query` 401 unauthenticated, `/health` qdrant ok, and
  `/namespaces/default/sources` returning `dense_chunks: 4020`,
  `consistent: true`, `warning: null` — the 19 Oct cross-check live.

  **The router change itself cost ₹0.02 to prove** and is the cheapest live
  verification this project has done, because the thing being verified is a
  refusal and a refusal skips retrieval, generation and the judge:

  ```
  classification      : out_of_scope        (production returned "simple" before)
  answer              : the out-of-scope message
  is_faithful         : null
  faithfulness_score  : null
  ```

  Metered at `$0.000195` on `/health`'s own budget counter. The nulls are
  the 19 Oct faithfulness fix holding in the same call, so that change now
  has a second live witness. **Still unverified live: the generator's
  `REFUSAL` branch** — this query refused at the router, which is a
  different path and emits a different string.

- 2026-10-19 (offline faithfulness default; **₹0**) — the twin filed earlier
  the same day is closed, and the published number was checked **before** the
  code changed rather than after. The filed entry prescribed the check, so it
  ran first: all **289 faithfulness rows across the 19 stored report JSONs**
  were scanned for the two shapes `parsed.get("faithfulness_score", 1.0)` can
  produce — a score over zero claims, and a 1.0 printed beside claims the
  judge marked unsupported. **0 matched.** The third shape, a missing key
  where every claim *was* supported, needs no scan: the default and the real
  computation both give 1.0 there. So **the published faithfulness 1.000
  stands as measured**, README and resume bullets need no footnote, and no
  re-run is owed. The fix: a missing `faithfulness_score` now **raises**, and
  the runner's existing `except` records `score=-1.0, applicable=True`, which
  the mean drops and `_failed_counts` prints in bold — the harness already
  had a word for "this sample produced no verdict" and it was never `1.0`. A
  score over an **empty claims list** returns `applicable=False` instead, the
  same shape as `AnswerCorrectnessMetric`'s no-facts branch, because
  supported/total with total 0 is not a number the judge could have computed.
  The refusal branch keeps `1.0`/`applicable=False`: `MetricScore.score` is a
  required `float`, so a null would ripple through reporter and comparator,
  and unlike the console no report reader sees that 1.0 without the skipped
  count beside it. Siblings swept in the same pass — `answer_relevance` and
  `answer_correctness` already fail a missing key to **0.0**, and
  `grader.py:136` defaults to `0.5`, a midpoint rather than a flattering
  value, so neither was touched. **694 tests at 93.64%**, gate green,
  `static/` untouched (no console change). BACKLOG open drops **5 → 4**.
  Not deployed: the offline eval harness is not in the serving path, so
  production stays on rev `atlas-api-00016-ckx`.

- 2026-10-19 (faithfulness "no verdict"; **₹0**) — `FaithfulnessResult`
  carries `float | None` / `bool | None`, and the two branches where nothing
  was audited — check disabled, and a refusal — return `None` instead of
  `1.0`/`True`. The disabled branch was a loaded gun (no flag is wired to
  it); **the refusal branch was live**: every refusal not classified
  `out_of_scope` had been rendering as **"Supported 1.00"**, the console's
  strongest badge, for an answer that said it did not know. A third instance
  surfaced in the same file while widening the type —
  `parsed.get("faithfulness_score", 1.0)` scored a judge perfect for omitting
  the number it was asked for — and was fixed with it. The unparseable-judge
  branch keeps `0.0`/`False` on purpose: an audit that ran and failed is a
  triage item, not a blank. Ripple through `PipelineResult.is_faithful` (was
  `True` when no check ran), the flag log (`is False`, not `not`),
  `QueryResponse.is_faithful: bool | None`, the console type and
  `seed_demo.py`. `strengthFrom()` needed no change — it already rendered a
  null score as "Unchecked"; that branch is now reachable. **692 tests at
  93.63%**, gate green, `static/` byte-identical (type-only console change).
  BACKLOG: one closed, one filed (the same default in the *offline* metric,
  left deliberately because it feeds the published faithfulness 1.000), so
  open stays at **5**.

  **Shipped: rev `atlas-api-00016-ckx`, image `2190db6`, ≈₹0** (2m59s
  build). Verified free: `/app` 200, `/query` 401 unauthenticated,
  `SourceListResponse` in the live `openapi.json` carries `dense_chunks`,
  `consistent` and `warning`. `QueryResponse` is **not** in `openapi.json`
  — `/query` is declared `response_model=None` — so the nulls could only be
  seen by paying for a query. Two were run, **₹0.26 total**:

  | query | classification | `is_faithful` | score | cost |
  |---|---|---|---|---|
  | airspeed velocity of an unladen swallow | `out_of_scope` | **null** | null | $0.00013 |
  | retry failed Stripe webhook deliveries | `simple` | true | 1.0 | $0.0029893 |

  The first **proves the `PipelineResult` half live**: `faithfulness is
  None` used to yield `True`, so every out-of-scope refusal reported as
  audited and passed; it is now null. The second did **not** reach the
  refusal branch, and correctly so — `is_refusal()` is an equality check,
  not a substring one, and that answer opened with the refusal sentence and
  then made cited claims, so it got a real audit and earned its 1.0. **The
  refusal branch is therefore still unverified live** (it needs the
  generator to emit the refusal sentence and nothing else, which two
  attempts did not produce); it rests on
  `test_refusal_is_neither_unfaithful_nor_perfectly_supported`. The second
  query also re-confirms the open router debt: a Stripe question was
  classified `simple`, not `out_of_scope`.

- 2026-10-19 (`/namespaces/{ns}/sources` cross-check; **₹0**) — the endpoint
  no longer lets the sparse half speak for both. It reads the BM25 corpus as
  before (the only half carrying per-source rows) and now also reads the
  collection's point count, returning `dense_chunks`, `consistent` and a
  plain-language `warning` beside `total_chunks`. An unreachable Qdrant
  returns `None`, never `0` — the shape that would have reinstated the bug,
  and now a test. The console threads the warning through the store and
  shows it in the two places the wrong number was displayed: a triangle
  beside the totals in the top bar and a banner above the source list.
  9 new tests, **686 passing at 93.55%**, gate green on all three targets.
  BACKLOG open items **6 → 5**.

  **Shipped the same day: rev `atlas-api-00015-gd7`, image `ed2cb69`,
  ≈₹0** (3m01s build, Cloud Build free tier; no re-ingest, neither index
  changed). The gate passed both namespaces unchanged — 4,020/4,020 on
  `default` and `headers`, ids and hashes agreeing. Verified live:
  `/namespaces/default/sources` and `/namespaces/headers/sources` both
  return `dense_chunks 4020, consistent true, warning null`, `/app` 200,
  `/query` still 401 unauthenticated. The mismatch path cannot be
  reproduced on the live service any more — the three orphan index
  directories were deleted on the 18th, so `quickstart` now answers
  `0 / 0 / consistent true`, which is the honest answer for a namespace
  that holds nothing on either side.

- 2026-10-18 (redeploy; **≈₹0**) — rev **`atlas-api-00014-5vp`**, image
  `ac132a9`, so the owed redeploy is discharged and the two halves of the
  hybrid agree in production again. It carried 23 commits and 11 days as
  well as the index: browser-corpus upload, the reranker's `batch_size=16`
  and CPU fallback, the comparator and reporter fixes. Checked before
  shipping that `HYDE_ENABLED` defaults to False (a rejected knob does not
  switch itself on in production) and that `/ingest` and `/ingest/upload`
  are outside `_PUBLIC_PATHS`; both answer **401** unauthenticated on the
  live service, as does `/query`, and `/app` serves 200.

  **The gate refused first, and was right to.** Four namespaces had a BM25
  file, so four were checked: `quickstart`, `field-notes` and `console-demo`
  had **no dense half at all** in the production cluster, and `headers` was
  4 `release-notes.md` chunks behind on context headers — the same 4 that
  `default` had fixed on the 17th. The three orphans were local-only
  leftovers dated 2026-10-13, so they had never shipped; baking them would
  have made `/namespaces/{ns}/sources` advertise 39 sources that answer
  nothing, which is the BACKLOG debt about that endpoint reading BM25 rather
  than Qdrant. They were deleted. `headers` was re-ingested for 4 chunks and
  433 tokens, and the gate then passed on both remaining namespaces.

  **Two things went wrong in the running, both worth keeping.** The deploy
  was started twice within 51 seconds — once in the background, once from
  the terminal — so two builds ran, succeeded, and raced for the same tag;
  harmless, and inside Cloud Build's free tier, but two `gcloud builds
  submit` clients then hung after their builds had finished and neither ever
  reached `gcloud run deploy`. Killing them also killed the run in the
  user's own terminal, which was not the intent. And **the monitor armed to
  watch the build reported nothing for 15 minutes**: it polled with
  `gcloud ... || true`, so a failing check and a still-running build
  produced identical silence. Same family as the stall detector below — a
  check whose own failure is swallowed reports whatever you assumed. The
  deploy finally went out with `SKIP_BUILD=1 IMAGE_TAG=ac132a9`, which is
  honest here only because `verify_index` had passed minutes earlier against
  the same on-disk index the build copied.

- 2026-10-18 (HyDE `replace` measured; HyDE closed; **₹6.94**) — ran clean
  in 5 minutes once Chrome was genuinely quit, with **zero** CPU fallbacks,
  so the 17th's `batch_size` fix held and the latency below is HyDE's own
  rather than the fallback's wearing its name. +0.0845 context precision,
  **−0.0245 recall**, warm p50 +41.2% and p95 **+138.6%** (40,778 ms), both
  ceilings breached. Head to head with `concat`: tie on all five metrics,
  +40.4% p95. So `replace` buys nothing `concat` does not and costs 8.6 s of
  p95 to not buy it, and **HyDE is closed with both arms measured.** The
  recall loss is `HyDEConfig`'s own argument confirmed by measurement — a
  bare hypothesis deletes the question's rare terms from the BM25 query.
  `fq-016` scored nothing, on **"Request timed out"** — a third distinct
  failure mode, and one that is visible instead of silent only because of
  the 17th's reporter and comparator work.

  Also corrected, because it changes how to read the 17th: **the stall
  detector used on the two killed attempts was reading the wrong process.**
  It took the first `ps` match, which is the zsh wrapper at ~1 MB, not the
  Python process. The second kill was therefore probably premature. The
  first still stands — there the Python process itself was identified, at
  7.6 MB and 0% CPU after 23 minutes against a ~4 minute run. The real
  lesson is that **CPU is a bad liveness signal for this workload**: at
  `--concurrency 1` the process is blocked on Gemini for most of its wall
  time, so 0% CPU is its normal state. Resident memory growth is the signal
  that worked — 59 → 86 → 140 MB on the run that finished.

- 2026-10-17 (HyDE measured and rejected; three defects found doing it;
  **₹12.55**) — the index gate went green for ≈₹0.005, not the ≈₹6.45 this
  file had been quoting: the job was 4 chunks and 433 tokens because the
  indexer skips on `content_hash`, which `eccc01d` had said in its own commit
  message. **A redeploy was owed** from here, since the image bakes the BM25
  index and production's two halves disagreed on those 4 chunks until one
  happened; it happened on the 18th as `atlas-api-00014-5vp`.

  HyDE's prediction was committed before the run was paid for (`9eed3f2`),
  which is what M3's reworded criterion 4 reserved the paper exercise for.
  `concat` then measured +0.0619 context precision against −0.0238 answer
  correctness — one metric each way, nobody wins — and warm p95 21,400 ms
  against a 20,000 ms ceiling, so the comparator withheld the winner and the
  knob stays off. `replace` is still unmeasured: two attempts stalled on a
  laptop with 10 GB of 11 in swap and were killed before either reached
  sample one, so neither spent anything.

  The run that was supposed to answer one question found three defects
  instead, all of the same family — **a measurement whose own gaps are
  silenced reports whatever you expected**:

  - Two samples died in the reranker with "MPS backend out of memory". They
    were scored at the failure sentinel, dropped from every mean, and the
    report printed "16 samples" with no qualifier, because the reporter only
    counted *refusals* as excluded and a crash is not a refusal.
  - The comparator's sample-id guard passed, because both runs **covered**
    the same 16 rows. They did not **score** the same rows. Comparing means
    over different denominators turned a real −0.0238 regression in answer
    correctness into a reported +0.0113 tie.
  - The budget had the same hole and it mattered more: the dropped rows were
    the baseline's two slowest, so its p95 was measured on samples the
    candidate never ran. Reported +25.2%; real **+56.3%**.

  Fixed, with tests that are those runs shrunk: paired means, paired latency,
  failed samples named in bold, `RerankerConfig.batch_size`/`device`, and a
  CPU fallback on an out-of-memory that logs rather than killing the sample.
  `scripts/compare_reports.py` re-judges two stored reports for free — until
  today, seeing a corrected verdict meant buying the measurement again, which
  is a bad incentive to leave in front of a comparator fix. And the
  comparator now checks **cost per query** against its own $0.005 ceiling,
  closing the BACKLOG item that was waiting for two reports to carry
  per-sample usage; pricing only the samples that finished moved HyDE's cost
  from a reported +4.7% to +15.2%.

- 2026-10-14 (M3's last two criteria reworded and closed, ₹0) — both had been
  met in substance and failing on form since the milestone opened, and the
  call was yours to make. **Criterion 1 lost the PR.** It asked for changes
  "merged, each with `eval-compare` in the PR"; this repo has zero merge
  commits and no pull request has ever existed, so the PR was a venue and
  never the evidence. It now asks for a stored report pair and a dated
  DECISIONS write-up, which is what 16 reports in `eval_data/reports/` and
  ~20 entries already are, and is still readable in a year. Qualifying:
  `reranker.top_k` 5 → 15 (recall 0.778 → 0.900) and deterministic context
  headers (P 0.3762 → 0.4524, R 0.9286 → 0.9643, `fq-012` recalled for the
  first time). **Criterion 4 lost the prediction, and that is a lower bar —
  said so in the criterion itself rather than only here.**
  `learning/exercises.md` §09 defines the exercise as a paper write-up ending
  in "the `make eval-compare` result you would expect", made before paying.
  It now asks only that each shipped change name its module 09 item and carry
  its measured before/after, and the two cross-references were added to
  DECISIONS.md the same day: `top_k` → §1 *Long context vs RAG*, which names
  the change by hand ("raise `RerankerConfig.top_k` from 5 to ~15 and measure
  faithfulness vs cost"); context headers → §5 *Ingestion quality*, shipped
  as the deterministic cousin of the LLM-written version that section lists.
  The reason for dropping the prediction half is the honest one: this
  project's predictions kept being wrong — the cheap retrieval harness
  mispredicted four times running, and the path-token mechanism argued for
  the context headers was not what recovered `fq-012` — so predictions
  invented after the fact for shipped changes would be worth less than the
  recorded corrections are. **M3 is 4 of 4 and the roadmap is 16 of 17.** The
  one still open is M1's resume-bullets line, which is yours. No code changed
  and no metric moved; what changed is that two criteria now describe a
  one-person repo instead of a team's. The exercise as written stands for
  HyDE — module 09 §4, built, off, ≈₹6.24 to measure, and the only
  unmeasured thing left in M3.
- 2026-10-14 (three ₹0 backlog items, and a spend-cap defect one of them
  found, ₹0) — **a coverage floor the gate defends** (`--cov-fail-under=90`
  against 93.38%; verified it fails at 99 before trusting that it passes at
  90), **`tiktoken` removed** — proved rather than grepped, by putting a
  module that raises on `import tiktoken` ahead of it on `PYTHONPATH` and
  watching all 644 tests pass — and **per-sample token usage on
  `SampleResult`**, which is what finally separates "what did this run cost"
  from "what does a production query cost". The judges make roughly twice the
  chat calls a real query does, so the run total divided by sample count was
  never the production figure; a nested usage scope separates them and a
  merge back into the run meter keeps the run-wide total identical. The
  report now prints **Cost per query** and names what the judges added, and
  omits the line on any report predating the field rather than computing it
  from a total that means something else.
  **The defect that fell out of it:** `usage.counted()` folded its inner
  scope into the caller's meter *only on success*. So a call that spent its
  prompt and then raised contributed nothing — and in `/query` that is the
  daily spend cap under-counting exactly the requests that went wrong. The
  merge is in a `finally` now. Found by a test asserting a failed eval sample
  still reports what it spent, which is the second time this week a test
  written for one thing caught a different live defect.
  **656 tests**; five plants, each reddening its own pins: folding only on
  success reddens 2, dropping the merge-back reddens 7, recording the run
  scope instead of the sample's reddens 2, pricing cost/query off the run
  total reddens 2, printing the line with nothing measured reddens 1.
  **Still open:** the comparator consuming per-sample usage — meaningless
  until two reports carry it, so it waits for the next two paid runs.
- 2026-10-13 (console ingest: the corpus can now be built from a browser, and
  the endpoint it used stops being a file-read channel, ₹0 so far) — M4's
  first criterion asks for a corpus *created, ingested and queried entirely
  from the console*, and three things were in the way. (1) A namespace is a
  Qdrant collection and a collection does not exist until something is
  indexed, so `/namespaces` could never list a corpus you had only named —
  the picker had no way to select the thing you were about to create. The
  store now holds a named corpus locally until the first upload makes it
  real. (2) **`/ingest` takes a path on the server**, which a browser cannot
  supply; the console's existing path box only ever worked when the API ran
  on the same laptop, and means nothing against Cloud Run. New
  `POST /ingest/upload` takes multipart bytes, indexes them from a temp dir
  deleted in a `finally`, and uses that dir as the `source_root` so headers
  are not machine-specific. (3) The path endpoint was **unsandboxed**: since
  anything indexed is retrievable through `/query`, any caller with a key
  could index `/etc/...` or a mounted secret and read it back. It is confined
  to `INGEST_ROOT` (default `data`) with a resolve-then-compare check that
  refuses `..` and symlinks, running *before* the existence check so 403-vs-404
  cannot be used to probe the filesystem.
  Every refusal is reported by name — unsupported extension, empty, oversized,
  past the file count, over the request total — and a request where everything
  was refused is a 422 carrying the reasons, because an upload that drops 3 of
  10 files and reports "7 indexed" is how a corpus goes quietly short.
  **Verified in the browser at ₹0:** created the `console-demo` corpus from
  the UI (top bar went to `CONSOLE-DEMO · 0 SOURCES · 0 REFS`), and an
  unsupported file produced the toast *"nothing could be indexed — notes.exe:
  no loader handles '.exe'"*, which is the structured 422 rendered readably.
  **656 tests**; seven planted defects each redden exactly their own pins,
  including the one that proves `.resolve()` is what stops `..` and symlinks.
  `python-multipart` is now a declared dependency — FastAPI raises at request
  time without it, not at import, so an undeclared one would be a 500 on a
  single route with a green suite everywhere else.
  **Also found, filed not fixed:** `/namespaces/{ns}/sources` reads the BM25
  index, not Qdrant, so it advertised **155 sources / 4,020 refs** on a local
  `default` whose Qdrant collection does not exist.
  **Still open on this criterion:** the end-to-end *upload → query* run, which
  costs ≈₹0.2 and needs a go-ahead.
- 2026-10-13 (the end-to-end run, and the two defects it found, ₹0.07) —
  **M4's first criterion is met.** A corpus named `field-notes` in the sheet
  picker, a markdown file dropped on the upload zone, a question answered from
  it: *"The default write quorum (`ATLAS_WRITE_QUORUM`) is 3"* and *"the orphan
  sweep (`chunk_reaper` task) runs every 17 minutes"*, both cited to
  `field-notes.md`, 5 stages in 6.9 s. The file held invented facts, so the
  answer could not have come from the model's own knowledge.
  The first attempt failed twice, and the demo is the only thing that would
  have found either.
  **The router judged the question out of scope before retrieval ran.**
  `ROUTER_DOMAIN` described the FastAPI docs and every namespace was handed the
  same sentence, so the moment anyone uploads their own corpus every question
  about it is refused — the feature shipped unusable for its only purpose, with
  a green suite. Resolved per namespace now (`ROUTER_DOMAIN_NAMESPACE` names
  the one corpus the sentence describes; everything else gets the generic
  default). This is the shape worth remembering: *a setting that was correct
  when there was one corpus becomes a silent refusal when there are many.*
  **And the console then blamed the sheet.** The refusal copy read "the
  `console-demo` sheet has no references covering this" — about a sheet holding
  exactly those references, and asserted at a point where nothing had looked.
  **The stored source was the server's temp directory.** `source_root` governed
  only the context header, so the citation read
  `/var/folders/nt/.../T/atlas-upload-g154heox/field-notes.md`: a path deleted
  before the reader sees it, and a published map of the server's filesystem.
  Uploads now store the name relative to the temp root; ingest from disk is
  unchanged, so no existing index starts citing two ways.
  Fourteen new tests, each planted: the global-domain revert reddens 3 of 5
  router pins and 1 registry pin; ignoring `relative_sources` reddens 4; not
  threading it through `index_directory` reddens exactly 1.
  One of my own tests could not fail for the reason it named — a symlink case
  where both sides were spelled the same way, so it passed with and without
  the `.resolve()` it claimed to pin. Rewritten to hand the two sides different
  spellings of the same directory, which is what macOS temp dirs actually do.
  Another read this laptop's `.env`: `RouterConfig()` picked up the real
  `ROUTER_DOMAIN` and asserted what one machine happens to hold. Pinned with
  `_env_file=None`.
  **Filed, not fixed:** the router's `reasoning` is logged but never leaves the
  server, so the console cannot say *why* a question was refused — it needs
  carrying through `PipelineResult`, the response schema and both SSE paths.
- 2026-10-13 (the SSE pair: a claim nothing checked, and a fixture that
  could not succeed, ₹0) — the `done` event hardcoded `"is_faithful": true` on
  a path whose own docstring says it skips the faithfulness check. Live at
  atlas.hulage.in since at least 2026-10-07. **Two sites, not the one filed**:
  the success branch and the `out_of_scope` refusal, which claimed a check had
  passed for a canned string that grounds and cites nothing. Both send `null`
  now — not an omitted field, because `undefined` is falsey in JS and would
  flip the error to "not faithful". The console was never misled (it renders
  "Unchecked" off a null *score*), which is precisely why this survived: **the
  UI was more honest than the API**, so nothing on screen ever looked wrong.
  The second half of the pair was filed as a code defect and was already
  fixed — `_stream_query` emits an `error` event and the `[DONE]` sentinel,
  logs first, charges the cap for a failed request, re-raises
  `CancelledError`. What was *not* done was the test the entry asked for: the
  only failure test broke the stream at **grading**, before any answer text is
  sent, while the recovery exists for "an exception raised after the first
  byte". That case is tested now — one delta, then a raise, must yield the
  partial text, an `error` naming **generation**, the sentinel, no `done`, and
  nothing leaked.
  **Finding the test needed exposed a worse one.** The shared API fixture left
  `_grader.grade` an auto-MagicMock, which is not awaitable, so **every
  streamed request in the suite died at stage 4 and became an error event** —
  no success-path streaming assertion in the repo was testing what it said.
  An existing test comment already described this and worked around it
  locally instead of fixing the fixture. Same shape as the `importorskip`
  finding the day before: *a fixture that cannot reach the end makes every
  assertion past the break a comment.* The fixture grades by default now and
  failure is opt-in; reverting that one line reddens 4 of the 7 new tests.
  **610 tests.** Also filed, not fixed: `FaithfulnessChecker` returns
  `score=1.0, is_faithful=True` when disabled, which would render "Supported
  1.00" for every answer — unreachable today (nothing passes `enabled`), but
  it needs the dataclass widened to nullable rather than a three-line edit.
- 2026-10-13 (`make docker-up` was broken for everyone, and the quick start
  could never reach an answer, ₹0) — audited M4's "outsider follows the README
  from clone to first answer in < 15 minutes" by being the outsider: a real
  clone of public `main`, then every documented step. Three faults, none about
  time. (1) The Quick Start had no `make fetch-corpus` and no ingest step, so
  an outsider queries an empty index; it ended at "start the API" with no
  example query, and told them to `uv pip install -e ".[dev]"` — assumes `uv`,
  creates no venv, wrong extras. (2) **`make docker-up` failed for everyone,
  always**: the qdrant healthcheck ran `curl -f .../readyz` and the qdrant
  image ships neither `curl` nor `wget` (`docker exec atlas_qdrant curl
  --version` → `executable file not found in $PATH`), so the container could
  never be healthy and `api` waits on `service_healthy` — 53 s to
  `dependency failed to start: container atlas_qdrant is unhealthy` while the
  service answered 200 on `/readyz` from the host the whole time. `bash` *is*
  in the image, so the check now speaks HTTP over `/dev/tcp`; verified exit 0
  against the live service and non-zero against a closed port. (3)
  `make docker-up` also ran a bare `docker compose up -d`, which starts and
  builds `api` — contradicting its own help; it names `qdrant redis` now.
  And a defect in the previous commit's own work, visible only from a clean
  clone: the committed listing said `"repo": "tiangolo/fastapi"` (inherited
  from this machine's older manifest) while the fetcher writes
  `fastapi/fastapi`, so `make fetch-corpus` **dirtied a clean tree**. The
  dataset guards read only `files`, so nothing there could have caught it;
  `test_the_committed_listing_agrees_with_this_script` now pins the listing
  against the script's constants. Measured on the clean clone: clone 1.3 s,
  `make install` 59 s, `make docker-up` 0.4 s + 12 s to healthy,
  `make fetch-corpus` 55 s / 155 files, `make test` with no corpus
  **594 passed, 1 skipped** — ≈2 m 15 s of setup at ₹0, leaving ~12 of the 15
  minutes for the two paid steps.
- 2026-10-13 (the M4 outsider criterion **MET**, ₹0.18) — ran the two paid
  steps the audit above stopped short of, and the criterion is now ticked in
  ROADMAP: **about 3.5 minutes, ₹0.18, from clone to a cited answer.** The
  one-page ingest took 8 s for 35 chunks / 4,610 tokens (**₹0.01**); the API
  was healthy 10 s after `make serve`; the documented query answered in 7 s
  for **₹0.17** ($0.0019647, which `/health` then reported as the day's spend,
  so budget accounting agrees with the invoice). The answer — "instructs you
  to import `FastAPI` [1][4]" — carried **faithfulness 1.0**, grader 1.0, no
  unsupported claims, and citations resolving to
  `tutorial/first-steps.md`, the page indexed two steps earlier. Machine time
  2 m 33 s; the README's step-6 "~5s" was wrong (10 s) and is corrected along
  with the measured costs.
  **Found by doing it: `scripts/ingest.py` never said which Qdrant it writes
  to.** A developer's `.env` points at the managed cluster as soon as they
  have deployed, while the `.env.example` the README describes points at the
  local container — so the documented quick-start ingest writes a new
  namespace **straight into production** with nothing on screen to say so. I
  caught it only by checking `QDRANT_URL` before spending. The banner and the
  dry run now print `host:port/collection`, flagged `<-- NOT local` when it is
  not, built from `hostname`/`port` and never from `netloc` — which my own
  test caught carrying `user:password@` in the first draft. Each of the three
  pins was proved by planting the defect back.
- 2026-10-12 (CI's first run read, both causes fixed, ₹0) — run
  `38220215949` failed with 11 of 12 steps green and `make test` at exit 2:
  `5 failed, 574 passed, 4 skipped`. Two real causes. (1) `make install`
  asked for `.[dev]`, but `tests/unit/api/test_spendstore.py::TestFirestore`
  imports `google.cloud` directly — and Firestore is what production
  actually uses (`AUTH_STORE=firestore`), so the extra is optional at runtime
  and not for the gate. `make install` now takes `.[dev,gcp]`. (2) Three
  `test_dataset_guards.py` tests need `data/corpus/fastapi`, which is
  gitignored, so they fail on **every clean clone**; they now skip with a
  reason ending `this guard DID NOT RUN`, and `-rs` is in `addopts` so the
  reason prints. Run `38223889425` on `9ba1fd5` is green: 13 of 13 steps,
  `580 passed, 3 skipped`, 93%.
  **The louder failure was not the bigger one.** Fixing the extra turned 2
  errors into passes and also un-skipped **4 more** tests —
  `TestFirestoreKeyStore` is gated by `pytest.importorskip` on
  `google.cloud.firestore_v1`, so the entire Firestore *key store* had been
  skipping with nothing red to show it. An optional dependency plus
  `importorskip` is a test suite that reports success for code it never ran.
- 2026-10-10 (CI, ₹0) — Atlas had no `.github/` at all, so "the gate is
  green" had always been a claim about one laptop. The workflow calls
  `make install`/`lint`/`typecheck`/`test` instead of re-spelling the
  commands, pins `ubuntu-26.04` and Python 3.11, and pre-seeds the venv with
  the CPU-only torch wheel so the default build does not drag ~2.5 GB of
  unusable `nvidia-*` packages into every run. Three things only an attempt
  at CI could find: the suite **fails without `.env`** because
  `OpenAIConfig.api_key` is required (`test_keys_endpoint_needs_no_bearer`
  goes first), which is the environment difference that kept sextant's CI red
  for 17 days — a dummy key in the workflow env settles it, verified by
  hiding `.env` locally and getting 583 passed; `npm run lint` had **never
  once run** in this repo and reported a real error in
  `console/src/lib/api.ts`; and nothing checked that the committed
  `src/atlas/api/static/` matches `console/src`, which CLAUDE.md requires
  because the image carries no Node. That last check uses `git status`, not
  `git diff` — planting a changed string literal showed vite's content-hashed
  filenames land as *untracked*, which `git diff` does not see.
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
  so every "gate green" in this file is a claim about one laptop. (The second
  of those was fixed 2026-10-10 — see the entry at the top of this section.)
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
- ~~**Atlas has no CI.**~~ Done 2026-10-10, ₹0, and **green on GitHub since
  2026-10-12** (run `38223889425`, commit `9ba1fd5`): all 13 steps success,
  `580 passed, 3 skipped`, 93% coverage. `.github/workflows/ci.yml` runs the
  make targets rather than re-spelling ruff/mypy/pytest, so the gate keeps one
  definition. The first run (`38220215949`) failed, as it should have — it
  found two things that had been invisible for months, and the fix for them is
  what went green. Confirmed green again on `3667e88`. The three
  corpus-dependent dataset guards skipped for two days and **run in CI as of
  2026-10-12**: label resolution only ever needed the documents' *names*, so
  the names are tracked in `data/corpus/fastapi.files.json` while the
  documents stay unvendored. One skip remains, the listing-versus-disk
  comparison, which has no second operand on a machine with no corpus.
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
