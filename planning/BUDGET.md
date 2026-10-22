# Latency and cost budget

The missing half of M3's exit criteria. Three of the four are met; the fourth
reads "p95 latency and $/query not worse by more than an agreed budget" and
there was no agreed budget, so it could not be evaluated either way.

This file is that budget. **Accepted 2026-10-08**, and the M3 criterion is
ticked on it: every measured value sat inside its ceiling at acceptance
(warm p50 10,053 / p95 17,072 ms against 12,000 / 20,000; $0.0034677 a query
against $0.005; $0.0709 an eval run against $0.100). It was a decision, not a
measurement — the measurements are below it, and every ceiling says which
number it was derived from.

## The baseline question, answered first

The obvious reading is "not worse than M1". That reading is rejected, and
the reason matters more than the numbers.

M1 measured p50 ≈7 s and ≈₹0.03 a query on 2026-09-20. That pipeline had
`reranker.top_k` 5, no retrieval grader, and no faithfulness check. It scored
context recall **0.667**. The pipeline measured below scores **0.938**.

So the M1 figures describe a cheaper, faster system that was wrong three times
as often. Holding M3 to them would mean either failing the criterion
permanently or reverting accuracy that was bought deliberately, one measured
PR at a time, each one already written up in DECISIONS.md.

The increase from M1 to now is therefore **ratified, not hidden**:

| | M1 (2026-09-20) | now (2026-10-03/07) | change |
|---|---|---|---|
| context recall | 0.667 | **0.938** | +0.271 |
| p50 latency | ≈7,000 ms | 10,053 ms | +44% |
| cost / query | ≈₹0.03 | **₹0.201** ‡ | ≈6.7x |

‡ **Was ₹0.31, from a single query.** Recomputed 2026-10-22 as the mean over
**n=35** paid production queries — see *Weakest number* below. The old figure
was not wrong, it was one draw: it sits 1.54x above the mean of the
population it was drawn from.

Six times the cost for 0.27 recall was the right trade at this corpus size and
this traffic — ₹0.201 a query against a ₹50–100 daily cap is roughly 250
queries a day, far past what Atlas serves. The budget below starts from the current
measurement and governs **what happens next**.

## Measured baseline

Warm, 16 rows, `baseline-16_20261003-182853`, `default` namespace, rev
`00011-xcm` / image `58e4e00`. Stage timings are the production pipeline, so
they transfer; the report's token count does not, because an eval run also pays
for metric graders.

| Stage | p50 ms | p95 ms |
|---|---|---|
| retrieval | 3,287 | 8,298 |
| faithfulness | 1,952 | 2,974 |
| generation | 1,609 | 2,608 |
| grading | 1,322 | 4,236 |
| routing | 1,126 | 2,179 |
| decompose | 1,049 | 1,323 |
| **total** | **10,053** | **17,072** |

**Percentiles are nearest-rank**, as `atlas.evaluation.reporter.percentile`
computes them and as `baseline-16_20261003-182853.md` prints them — the
comparator's budget check imports that same function, so the number a change
is judged on is the number the report shows. The first draft of this file
quoted interpolated values (p50 10,062 / p95 16,859) from a one-off script,
which is two conventions under one name; the project's own choice is
nearest-rank, on the stated grounds that interpolating between two of sixteen
samples implies a precision the sample size has not got. Every ceiling below
held under both readings, so the correction moves the figures and not the
decision.

At n=16, nearest-rank p95 *is* the slowest sample, for the total and for every
stage. That is a conservative read of the budget, not a lenient one, and it
stops being true once the dataset passes 20 rows.

Cost, mean over **n=35** paid production queries, lifetime to 2026-10-22:
**$0.0022882 ≈ ₹0.201**, 6,149 tokens a query. Source is the Firestore
per-key usage counters (`atlas_api_keys/*.usage`), which accumulate across
instances and survive restarts. The single query on `58e4e00` (2026-10-07,
7,986 tokens, **$0.0034677 ≈ ₹0.31**) is still the highest single-query value
anyone has recorded, and is kept for that reason. Eval run, 16 rows:
**$0.0709 ≈ ₹6.24** — not comparable to either, because an eval run pays for
two LLM judges a sample that a production query never calls.

Cold start: **49,000 ms** measured 2026-10-07, before `atlas-keepwarm` existed.

## Ceilings

Set above the measured p95 with headroom, not at it. A budget pinned to
today's number fails on noise and teaches everyone to ignore it.

| What | Ceiling | Measured | Headroom |
|---|---|---|---|
| warm p50, total | **12,000 ms** | 10,053 | +19% |
| warm p95, total | **20,000 ms** | 17,072 | +17% |
| cold start | **60,000 ms** | 49,000 | +22% |
| cost / query | **$0.005** (≈₹0.44) | $0.0022882 (n=35 mean) | +119% |
| eval run, 16 rows | **$0.100** (≈₹8.80) | $0.0709 | +41% |
| daily spend | **$0.60** | enforced in prod, 429 past it | — |

Per-stage p95 sub-ceilings, so a breach of the total says where to look:

| Stage | p95 ceiling | Measured |
|---|---|---|
| retrieval | 9,000 ms | 8,298 |
| grading | 5,000 ms | 4,236 |
| faithfulness | 3,500 ms | 2,974 |
| generation | 3,000 ms | 2,608 |
| routing | 2,500 ms | 2,179 |
| decompose | 2,000 ms | 1,323 |

`decompose` was missing from the first draft of this file — it is a stage the
pipeline runs and the report prints, so leaving it out meant a slowdown there
had no line to breach.

These sum to 25,000 ms against a 20,000 ms total ceiling. That is deliberate,
not an arithmetic slip: the stages do not peak on the same query, and the
measured per-stage p95s sum to 21,618 against a measured total p95 of 17,072
for the same reason.

## Cold start is budgeted separately, and conditionally

Cold is excluded from the warm p95 because mixing them makes the headline
number a function of traffic rather than of the code. It gets its own ceiling
and one condition: **`atlas-keepwarm` stays ENABLED, on `/warm`, with an
attempt deadline above the model load**. The `*/10` schedule is what makes
cold rare rather than typical. If that job is ever deleted, the 60,000 ms
line is not a budget, it is the normal user experience, and this section has
to be rewritten rather than quietly inherited.

The deadline is part of the condition as of 2026-10-21 and was not before.
The job pinged `/health`, which answers in about a second, so the gcloud
default `attemptDeadline` of 60 s was never near anything. It now pings
`/warm`, which loads the cross-encoder and measured **37.0 s in-handler and
54.1 s wall** on `atlas-api-00020-pcg` — so the default would have been a
60 s budget for a 54 s job, failing first on exactly the cold instance the
job exists for. Set to **120 s**, matching the service's own
`timeoutSeconds`, so the scheduler gives up no earlier than Cloud Run does.

## Regression rule

For a change to merge during M3 and after:

- **p95 total** may rise at most **+15%** against the comparison baseline.
- **cost / query** may rise at most **+20%**.
- A breach is not a block. It needs a DECISIONS.md entry naming the quality
  gain that bought it and the measurement that shows the gain — the same bar
  the M1-to-now increase above was held to.

Faithfulness is pinned at 1.000 and cannot go up, so "quality gain" in
practice means context recall, context precision, answer relevance or answer
correctness, each against the 0.02 significance floor.

## Enforcement: the comparator, since 2026-10-09

`atlas.evaluation.comparator.compare()` was **metric-only** when this file was
accepted: it ended in "**Overall winner**" computed from aggregate scores
alone and never read `stage_ms` or token usage, so a change buying +0.03
recall while doubling p95 and tripling cost would have been declared the
winner with the regression printed nowhere. The budget was hand-checked by
reading the latency table in the report, which was the weakest part of this
document.

It now measures both. `compare()` builds a `budget` list from the two reports
— warm p50 and p95 from per-sample `stage_ms`, run cost from per-model
`token_usage` priced by `atlas.cost` — checks each against its ceiling **and**
its regression allowance above, and on a breach **withholds the winner**:

```
| Budgeted | baseline-16 | candidate | Change | Allowed | Ceiling | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| warm p95 latency | 17,072 ms | 20,700 ms | +21.2% | +15% | 20,000 ms | **BREACH** |

**Overall winner: withheld** — B wins on quality, but the agreed budget is breached:

- warm p95 latency is 20,700 ms, over the 20,000 ms ceiling; warm p95 latency
  rose +21.2% (17,072 ms → 20,700 ms) against an allowed +15%
```

Four things it deliberately does not do, each for a reason:

- **It does not block.** A breach is still shippable with a DECISIONS.md
  entry, exactly as the rule above says. The markdown says so in the same
  breath as the breach.
- **It judges cost per *run*, not per query.** An eval run pays for the metric
  judges too — ~7.8 chat calls a sample against production's ~4 — so it checks
  the $0.100 run ceiling and the run-to-run regression. The $0.005 per-query
  ceiling stays hand-checked against production, and would need per-sample
  token accounting to automate. See the next section.
- **It skips the cost line when the two runs measured different metrics**, and
  says so. The judges spend tokens, so the run carrying an extra metric looks
  more expensive for that reason alone.
- **It skips what it cannot measure and names it** rather than passing it. A
  report written before `stage_ms` existed gets a note, not a green line: an
  unmeasurable run must not read as a compliant one.

Percentiles come from `reporter.percentile`, the same function the report
prints with, so the number a change is judged on is the number on the page.

## Weakest number

**Closed 2026-10-22, and for ₹0 — the plan written here was the wrong one.**
It said to recompute from the next eval run. An eval run is the wrong
population: it pays two LLM judges a sample that a production query never
calls, so its per-sample cost answers a different question. The right source
was already stored and never read — `FirestoreKeyStore.log_usage` has been
accumulating `usage.{total_queries,cache_hits,prompt_tokens,completion_tokens}`
on each key document since the store shipped, across instances and across
restarts.

| | value |
|---|---|
| queries recorded, lifetime | 38 |
| cache hits (cost $0) | 3 |
| **paid queries, n** | **35** |
| prompt tokens (embeddings flattened in) | 194,192 |
| completion tokens | 21,026 |
| **cost / query, mean** | **$0.0022882 ≈ ₹0.201** |
| tokens / query, mean | 6,149 |

The n=1 figure was **1.52x the mean** — the suspicion recorded here, that a
1,178-token answer sat toward the expensive end, was right in direction and
roughly right in size. A second long answer landed on 2026-10-22 at
**$0.00336865** for a 1,095-token completion, so the expensive end is a
real, repeatable region of the distribution and not one odd draw.

**What is still missing is the distribution, not the mean.** Firestore stores
sums, not rows, so there is no p95 and a ceiling is being judged against a
mean, which is the weaker comparison. Three independent slices bound the
spread:

| slice | n | $/query | how |
|---|---|---|---|
| `demo` key | 2 | 0.0004740 | per-key counters |
| all but the live instance | 26 | 0.0020125 | by subtraction |
| the live instance's own queries | 8 | 0.0030488 | `/metrics`, exact |
| one query, 2026-10-22 | 1 | 0.0033686 | body, log line and spend delta, agreeing |
| one query, 2026-10-07 | 1 | 0.0034677 | response body |

7.3x between the cheapest and dearest slice mean, and **every one of them is
under the $0.005 ceiling**, including the single most expensive query ever
observed. That is the strongest statement the stored data supports. A real
p95 needs per-query rows; `query_complete` logs `prompt_tokens`,
`completion_tokens` and `cost_usd` as of `87caf12`, live on
`atlas-api-00025-bnj` and **confirmed in production 2026-10-22**: the logged
line read 6911 / 1095 / 0.00336865, matching the response body exactly and
the Firestore spend delta ($0.003369) to six significant figures. The next
few dozen production queries produce a p95 from Cloud Logging for nothing.

Two accounting gaps found while measuring, both recorded in BACKLOG:
a **streamed** query charges the spend cap but increments none of
`log_usage`, `COST_USD` or `TOKEN_USAGE`, so it is invisible to every figure
above (one such query exists in 90 days, so the mean is over 34 of 35);
and `log_usage` is fired with `asyncio.create_task`, so a count can be lost
if an instance is torn down in the same moment.
