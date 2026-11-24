# Atlas at company scale — reuse the evidence, not the question

Written 2026-11-19, after the first real visit. The question: what breaks
when Atlas serves a 10,000-person company instead of one demo manual, and
what to build first. Nothing here is built yet; section 6 is the order.

## 1. What tonight showed

Two people asked the same five questions. Three repeats came back instantly
from the answer cache. Two more did not: the copies pasted from WhatsApp
carried an invisible character (U+2060), so the cache saw different text and
paid for the same answer twice. A one-character difference costs a full
answer because **the cache is keyed on the exact question text**.

That is the narrow bug. The wider point, raised by the owner: in a company,
people rarely type the same sentence. "Is my wife's delivery covered?",
"maternity cover for spouse", "does the policy pay for childbirth" are three
cache misses that all read the same two paragraphs of the health policy.
The question text is the wrong thing to remember. **What repeats is the
evidence — which passages an answer needs.**

## 1b. How the answer cache works today

1. A question arrives. Its text is cleaned (since S0: invisible characters,
   look-alike letters, spacing, case and end punctuation ignored) and turned
   into a short fingerprint, prefixed by the sheet it was asked about.
2. **Memory first:** each server keeps the last 256 answers in its own
   memory. A match is returned in about a millisecond, at no cost.
3. **Shared store second:** a Redis copy shared by all servers, kept for one
   hour. Supported in the code, **switched off live**.
4. **Miss:** the full pipeline runs (four model calls, 8–11 s, ≈₹0.18). Only
   a finished answer that passed its faithfulness check is stored; a failed
   or half-streamed answer never is.
5. **Forgetting:** the oldest unused answer drops out when 256 is full;
   anything older than an hour expires; adding a document to a sheet drops
   every saved answer for that sheet.

What it cannot do: match a reworded question, share between the two live
servers, or forget only the answers a changed paragraph affects.

**Proposed (S3): reuse by evidence.** Search runs first, because it is cheap
(one embedding, ≈₹0.0001). If the top passages largely match a stored
answer's passages *and* the two questions are close in meaning, the stored
answer is a candidate. A small check ("does this answer fit this
question?", ≈₹0.02) confirms it before it is served; only a miss pays the
full ≈₹0.18. Entries point at passages, so a changed passage drops exactly
the answers that read it, and a reader must be allowed every cited passage.

## 2. Assumed load (to size the problem, not a forecast)

| Input | Value |
|---|---|
| Employees | 10,000 |
| Questions per employee per working day | 2 |
| Questions per day | 20,000 |
| Busiest two hours | ~30% of the day → ~0.8 questions/second |
| Time per fresh answer today | 8–11 s → ~8–10 answers in flight at peak |
| Cost per fresh answer today | ≈ ₹0.18 (≈ 6,000 tokens read, ≈ 400 written) |
| **Cost per month with no reuse** | **≈ ₹1.1 lakh** (20,000 × ₹0.18 × 30) |
| Model tokens read at peak | ≈ 300,000 a minute — provider rate limits matter |

Every percentage point of reuse is about ₹1,100 a month at this load. The
deciding number is **how often a new question needs evidence already seen**.
We have never measured it.

## 3. Where the money goes in one answer

An answer makes four model calls: classify the question (small), grade the
retrieved passages (medium), write the answer (largest — it reads ~5–6k
tokens of passages), check the answer against the passages (medium).
Finding the passages (embedding + vector + keyword search) is cheap and
fast by comparison. So caching *search results* alone saves little; the
saving is in not re-reading and re-writing over the same passages.

## 4. On "storing millions of questions or passages"

The worry is right in spirit, but storage is not the binding constraint:

- **The passages are already stored once**, in the search database. A
  cache stores *pointers* to them (passage IDs), plus the answer — about
  2 KB per entry. A million entries is ~2 GB of Redis, which is small.
- **The cache is bounded today** (256 answers in memory, 1-hour expiry) and
  should stay bounded. Company traffic is heavily skewed: a small set of
  passages (leave, insurance, payroll, travel) serves most questions. A
  bounded cache that keeps the *frequently* used entries (LFU / TinyLFU
  admission, not plain LRU) captures most of the value in a small space.
- **What actually limits us** is hit rate, correctness and permissions, not
  bytes. A wrong reused answer about insurance is worse than a slow one.

## 5. What else breaks at company scale (ranked by harm)

1. **Permissions — the blocker.** Today any valid key reads any sheet, and
   the list of sheets is public. A company needs per-document access (HR
   files, salary bands, legal). Any shared cache must then check that the
   person asking may read **every passage the cached answer cites** —
   otherwise the cache becomes a leak.
2. **Freshness.** When the policy changes, today we drop every cached
   answer for the whole sheet. At scale, drop only answers that cited a
   changed passage (a passage → answers reverse index; passages are
   already content-hashed at ingest).
3. **Privacy.** The server logs the first 80 characters of every question.
   Employees will type health and family details. Company mode needs those
   logs off or redacted, with a retention limit.
4. **Shared state across servers.** The answer cache lives inside each
   server's memory; with two servers, one can serve an answer the other
   already dropped. Company mode needs the shared Redis layer (supported,
   switched off live).
5. **Cost and rate limits per team.** One daily cap for everyone does not
   work; spend and limits need to be per team, with an alert before the
   cap.
6. **Ingestion volume.** Thousands of PDFs, scans and tables; incremental
   re-indexing; the keyword index is rebuilt in memory and will not hold
   millions of passages.
7. **Quality by department.** One "answers correct" number hides a weak
   area; the test set needs questions from each document family.

## 6. Proposed order — measure before building

| Step | What | Cost | Done when |
|---|---|---|---|
| S0 | Clean question text before the cache lookup (Unicode NFKC, strip invisible characters, collapse spaces) | ₹0 | tonight's two misses become hits in a test |
| S1 | Record, per answer, the IDs of the passages it used and a fingerprint of that set — no question text | ₹0 | visible in logs |
| ~~S2~~ | Measure reuse: rewrite the 16 test questions three ways each; see how often paraphrases pull the same passages | ≈ ₹0.01 (search only) | **done 2026-11-19, section 7** |
| S3 | If S2 is worth it: an **evidence-keyed answer cache** — key = passage-set fingerprint + corpus version; reuse only when the new question is close in meaning to the stored one, and only for readers allowed every cited passage | ₹0 to build | paraphrase hit rate measured live |
| S4 | Per-document permissions | ₹0 | a reader without access gets "not found", even from the cache |
| S5 | Precompute per-passage work once at ingest (short summaries) so answers read less text; check the provider's discount for repeated prompt text | priced first | tokens per answer down, quality unchanged |

S0 is a real-user fix and fits the plan now. S1–S5 together are a new
milestone and need the owner to open it.

## 7. Measured 2026-11-19 (S2)

16 questions (the test set's 15 in-scope ones plus the invitation's CSV
question), each reworded three ways — casual, bare keywords, long with
context — searched against the live sheet. No answers generated; ≈₹0.01.
Negative control: the 120 pairs of *different* originals.

| Rule for "same evidence" | Rewordings caught | Different questions wrongly matched |
|---|---|---|
| Exact same top-5 passages (a plain fingerprint key) | 12.5% | 0 of 120 |
| Same top passage | 46% | 1 of 120 |
| 4 of top 5 shared | 46% | 1 of 120 |
| 3 of top 5 shared | 71% | 3 of 120 |
| **3 of 5 shared + questions close in meaning (≥ 0.85)** | **69%** | **1 of 120** |
| 3 of 5 shared + meaning ≥ 0.90 | 50% | 0 of 120 |

What it says:
- **An exact passage fingerprint is too strict** — rewording shuffles the
  ranking, so only 1 in 8 would be caught. Overlap, not identity, is the key.
- **Passages alone are not safe.** "Install and load an extension in one
  statement?" and "Is new syntax available right after LOAD?" share three
  passages and read as similar, yet need different answers. That is why S3
  needs the fit check before serving.
- **Rewording changes what the answer reads.** In 14 of 48 rewordings fewer
  than 3 of the top 5 passages survived, so answers to one question can
  differ by phrasing — a quality issue in its own right.

Report: `eval_data/reports/paraphrase-reuse_*.json`; rerun with
`scripts/measure_evidence_reuse.py`.

## 8. What this note does not claim

Section 7 is measured, but small: 16 questions, rewordings written by Claude
rather than by real employees, one technical manual. How often real people
re-ask something already answered is still unknown until the S1 logs run
live, so the cost saving is still an estimate. Atlas today serves
one public manual to a handful of visitors.

## 9. Built and measured 2026-11-24 (E2.5, T27)

S3 is built as `atlas.api.reuse`, behind `REUSE_ENABLED` (off live). A
stored answer is served to a new question only if the two searches share 3
of their top 5 passages, the questions are close in meaning, the asker may
read every passage the answer was built from, and a short model check says
the answer fits. Measured with `scripts/measure_reuse_hits.py` against the
live demo sheet: 15 test questions stored with their reference answers, 45
rewordings asking, and every other original asked against each stored one
(210 unrelated pairs). About ₹1.5 for three runs.

| Run | Change | Rewordings reused | Unrelated pairs served wrongly |
|---|---|---|---|
| 1 | first fit check | 44% | 0 of 210 |
| 2 | fit check told not to judge truth | 67% | 1 of 210 |
| 3 | fit check writes what is asked and what is given | 62% | 1 of 210 |
| 3 replayed at meaning ≥ 0.88 (shipped) | — | **53%** | **0 of 210** |

- **The fit check judged truth from its own memory.** It turned down
  correct answers about DuckDB 2.0 as "hallucinated" because 2.0 is newer
  than the model. Told that the answer was already checked against the
  documents, it stopped.
- **The fit check alone does not catch the hard pair.** "Install and load
  in one statement?" and "is new syntax available right after LOAD?"
  (§7's warning, meaning 0.871) got each other's answer in runs 2 and 3.
  A model judge cannot be the only lock.
- **So the meaning bar went from 0.85 to 0.88.** The last row is run 3's
  logged checks with every candidate below 0.88 dropped: a higher bar only
  removes candidates, so no new spend was needed. Four rewordings are lost.
- The 0.88 is tuned on this one set, which is the weakness: the next pair
  that fools the judge may sit at 0.89. Reuse stays off live until real
  questions exist to measure on, and permissions never depend on the judge:
  the access rule is checked on every stored passage first, and the
  permission suite passes with reuse on and the judge always saying yes.
