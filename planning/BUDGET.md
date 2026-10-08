# Latency and cost budget

The missing half of M3's exit criteria. Three of the four are met; the fourth
reads "p95 latency and $/query not worse by more than an agreed budget" and
there was no agreed budget, so it could not be evaluated either way.

This file is that budget. It is a decision to accept or move, not a
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
| p50 latency | ≈7,000 ms | 10,062 ms | +44% |
| cost / query | ≈₹0.03 | ₹0.31 | ≈10x |

Ten times the cost for 0.27 recall was the right trade at this corpus size and
this traffic — ₹0.31 a query against a ₹50–100 daily cap is roughly 160 queries
a day, far past what Atlas serves. The budget below starts from the current
measurement and governs **what happens next**.

## Measured baseline

Warm, 16 rows, `baseline-16_20261003-182853`, `default` namespace, rev
`00011-xcm` / image `58e4e00`. Stage timings are the production pipeline, so
they transfer; the report's token count does not, because an eval run also pays
for metric graders.

| Stage | p50 ms | p95 ms | max ms |
|---|---|---|---|
| routing | 1,130 | 1,783 | 2,179 |
| retrieval | 3,288 | 7,225 | 8,298 |
| grading | 1,378 | 3,773 | 4,236 |
| generation | 1,639 | 2,100 | 2,608 |
| faithfulness | 1,974 | 2,495 | 2,974 |
| **total** | **10,062** | **16,859** | **17,072** |

Cost, live production query on `58e4e00` (2026-10-07): 7,986 tokens,
**$0.0034677 ≈ ₹0.31**. Eval run, 16 rows: **$0.0709 ≈ ₹6.24**.

Cold start: **49,000 ms** measured 2026-10-07, before `atlas-keepwarm` existed.

## Ceilings

Set above the measured p95 with headroom, not at it. A budget pinned to
today's number fails on noise and teaches everyone to ignore it.

| What | Ceiling | Measured | Headroom |
|---|---|---|---|
| warm p50, total | **12,000 ms** | 10,062 | +19% |
| warm p95, total | **20,000 ms** | 16,859 | +19% |
| cold start | **60,000 ms** | 49,000 | +22% |
| cost / query | **$0.005** (≈₹0.44) | $0.0034677 | +44% |
| eval run, 16 rows | **$0.100** (≈₹8.80) | $0.0709 | +41% |
| daily spend | **$0.60** | enforced in prod, 429 past it | — |

Per-stage p95 sub-ceilings, so a breach of the total says where to look:

| Stage | p95 ceiling | Measured |
|---|---|---|
| retrieval | 9,000 ms | 7,225 |
| grading | 5,000 ms | 3,773 |
| faithfulness | 3,500 ms | 2,495 |
| generation | 3,000 ms | 2,100 |
| routing | 2,500 ms | 1,783 |

These sum to 23,000 ms against a 20,000 ms total ceiling. That is deliberate,
not an arithmetic slip: the stages do not peak on the same query, and the
measured per-stage p95s sum to 17,376 against a measured total p95 of 16,859
for the same reason.

## Cold start is budgeted separately, and conditionally

Cold is excluded from the warm p95 because mixing them makes the headline
number a function of traffic rather than of the code. It gets its own ceiling
and one condition: **`atlas-keepwarm` stays ENABLED**. The `*/10` schedule is
what makes cold rare rather than typical. If that job is ever deleted, the
60,000 ms line is not a budget, it is the normal user experience, and this
section has to be rewritten rather than quietly inherited.

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

## Enforcement: manual today, and that is a gap

`atlas.evaluation.comparator.compare()` is **metric-only**. It ends in
"**Overall winner**" computed from aggregate scores alone and never reads
`stage_ms` or token usage. A change that bought +0.03 recall while doubling
p95 and tripling cost would be declared the winner, with the regression
printed nowhere.

So until the comparator learns these two numbers, this budget is checked by
reading the latency table in the report by hand. That is the weakest part of
this document and the obvious next piece of work: teach `compare()` the two
thresholds above and have it refuse the word "winner" when either is breached.

## Weakest number

`cost / query` rests on **one** production query, n=1, with a 1,178-token
answer — likely toward the expensive end, since cost scales with answer
length. The +44% headroom is wider than the latency lines for exactly that
reason. Firming it up costs nothing extra: record `token_usage` per sample on
the next eval run that happens for another purpose, and recompute from n=16.
