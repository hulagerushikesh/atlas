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
| S2 | Measure reuse: rewrite the 40 test questions three ways each; see how often paraphrases pull the same passages | ≈ ₹2–3 (search only) | a "would have reused" % |
| S3 | If S2 is worth it: an **evidence-keyed answer cache** — key = passage-set fingerprint + corpus version; reuse only when the new question is close in meaning to the stored one, and only for readers allowed every cited passage | ₹0 to build | paraphrase hit rate measured live |
| S4 | Per-document permissions | ₹0 | a reader without access gets "not found", even from the cache |
| S5 | Precompute per-passage work once at ingest (short summaries) so answers read less text; check the provider's discount for repeated prompt text | priced first | tokens per answer down, quality unchanged |

S0 is a real-user fix and fits the plan now. S1–S5 together are a new
milestone and need the owner to open it.

## 7. What this note does not claim

No number above is measured at scale. The reuse rate, the skew of passage
use and the cost saving are all unknown until S1–S2 run. Atlas today serves
one public manual to a handful of visitors.
