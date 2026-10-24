# Pitch

How to explain Atlas to another engineer, in prose, out loud.

**The numbers below go stale.** They were true on 2026-10-14. Before quoting
any of them, check `planning/STATUS.md` for the current figures and
`planning/ROADMAP.md` for what is actually done — a pitch that quotes a
number the project has moved past is worse than one that quotes none.

---

## The long version

**The problem.** Retrieval-augmented generation is the standard trick for
making a language model answer questions about documents it was never trained
on: you chop the documents into chunks, embed them into vectors, and when a
question comes in you fetch the chunks that look closest and paste them into
the prompt. Everybody builds one, because you can get something working in an
afternoon. Almost nobody's survives contact with real use, and the reason is
specific: **a RAG system that is confidently wrong looks exactly like one that
is right.** There is no stack trace, no exception, no red build. The answer is
fluent, plausible, and carries a citation — and a meaningful fraction of the
time the substance is wrong. You find out when somebody acts on it. That is
the gap I cared about. Not "can I retrieve documents", which is solved, but
"can I tell when this thing is lying to me", which mostly is not.

**What I set out to build.** Atlas is an agentic RAG platform where that
question has an answer backed by a number. Three goals: every claim in an
answer traceable to the exact paragraph it came from; the system's actual
accuracy measured against human-written reference answers rather than assumed;
and every query's cost accounted to the paisa, so the thing cannot quietly run
up a bill. It is live at atlas.hulage.in — Cloud Run behind a Vercel rewrite,
Qdrant Cloud holding about 4,000 chunks from 155 pages of documentation.

**Retrieval, and why vector search alone is not enough.** Embeddings are
excellent at paraphrase and bad at exact tokens. Ask "how do I add string
validation to a query parameter" and a pure vector search will cheerfully hand
you a page about validation *in general*, while the page that actually answers
it — the one that says `Query`, `Annotated`, `min_length` — sits below the cut
because the question did not use any of those words. BM25, the old keyword
ranking algorithm, has exactly the opposite strengths. So Atlas runs both,
fuses the two ranked lists with Reciprocal Rank Fusion, and then reranks the
survivors with a cross-encoder — a smaller model that reads the question and
each candidate chunk *together* rather than comparing two vectors made
independently. Widening that rerank window from 5 to 15 moved context recall
from 0.778 to 0.900 with no loss in groundedness, which is the kind of thing
you only know if you measure it.

**The agentic part, and the bug that turned out to be the mechanism.** The
pipeline is not a free-roaming agent — it is a bounded graph, because I wanted
predictable latency and cost. A router first classifies the question as
simple, complex, or out of scope. Complex ones get decomposed into
sub-questions. Then retrieval runs, and here is the part I like: **a grader
scores whether the retrieved context is even sufficient to answer before
anything is generated**, and if it is not, the system retries and
*accumulates* more context rather than replacing what it had. Only then does
it generate, with inline citations, and afterwards a separate pass extracts
every claim in the answer and checks it against the retrieved text.

Now the interesting bit. The grader only sees the top 5 chunks while the
generator gets all 15. That looks like an obvious off-by-one — the grader is
answering "is the top 5 enough?" while the pipeline treats the answer as "is
the context enough?". I "fixed" it to 15, ran the A/B, and the numbers put it
straight back: recall dropped from 0.9378 to 0.8778, and all of the loss was
in the multi-document questions. The explanation is that a grader shown a
slice is *pessimistic*, pessimism triggers a retry, and a retry unions more
context in — so the narrow window was the only reason a question whose answer
spans five pages ever collected five pages. Widening it suppressed the retries
and the union never formed. **The bug was the mechanism**, and I would never
have known without an eval harness to run the comparison through.

**The number that actually matters.** The eval set runs five metrics. Four of
them look great: context recall 0.94, groundedness 1.000, answer relevance
0.84. The fifth is answer correctness, scored against a human-written
reference, and it reads **0.71**. Groundedness at a perfect 1.000 and
correctness at 0.71 **in the same column is the entire point of running the
fifth metric.** Every sentence the system produced was traceable to text it
had actually retrieved — and roughly a quarter of the substance still did not
survive the trip. One of the failures was a cited, grounded, confidently wrong
answer about a Python version. That is the gap I keep pointing at: most RAG
projects measure groundedness, see 1.0, and conclude they have solved
hallucination. Groundedness tells you the model did not invent anything. It
tells you nothing about whether the right thing was retrieved in the first
place, or whether the model drew the right conclusion from it.

**What only running it finds.** The defects I am proudest of catching are the
ones that live *between* components, where every part is individually tested
and green. The router is given a one-sentence description of what the
knowledge base covers, so it can reject off-topic questions — except that
description was global to the process, while a corpus is per-namespace. So the
moment anyone uploaded their own documents, every question about them got
refused by a classifier that had never looked at them, and the UI then told
the user their documents did not cover it. Shipped with a fully green test
suite; found in the first end-to-end run. Separately, the token meter folded a
call's usage into the daily spend cap only on success — but tokens are spent
*before* a call fails, not instead of failing, so the cap was under-counting
exactly the requests that went wrong. And a citation was leaking the server's
temp directory path to the browser. None of these are findable by unit tests,
because every unit involved was behaving correctly.

**What it is and is not.** 656 tests, 93% coverage against a floor the build
defends, CI running the whole gate on every push, about 20 paise per query,
and a spend counter that matched the actual invoice to four decimal places. It
is **not** a product with users — it is a deployed, measured system, and I
would rather say that plainly than dress it up. The line to lead with: *most
RAG projects can report four metrics that all say they are doing great; the
fifth one is the one that tells you the truth, and I compute it.*

---

## If a non-engineer is in the room

It reads a pile of documents and answers questions about them, and every
sentence it writes comes with a receipt showing which paragraph it came from.
The hard part is not getting an answer — it is knowing when the answer is
wrong, because a wrong one sounds exactly as confident as a right one. So I
measure that: roughly 71% of the substance matches a human-written reference.
Most people building these never check, which is why they all sound like they
are at 100%.

---

## The 30-second spoken version

> "Atlas is an agentic RAG system — you give it documents, it answers
> questions with a citation on every claim. The part I care about is that it
> grades itself: it scores whether the retrieved context was even sufficient
> before answering, then checks every sentence of the answer against that
> context. It is live, it is about 20 paise a question, and I can tell you its
> accuracy number — 0.71 against reference answers — while its groundedness is
> a perfect 1.0. That gap is the interesting part, and almost nobody measures
> it."

---

## Asking an engineer friend to try it

A different job from the pitch above. That one is for someone deciding
whether to be impressed. This one is for someone deciding whether to spend
ten minutes, which is a smaller ask and a harder sell — they owe you nothing
and a demo link is a chore.

Three rules. **Lead with the ask, not the architecture**: say what you want
before you say what it is, so they can decide while they are still reading.
**Name the flaw yourself** — "no users, that's why I'm asking" buys more
credibility than any number. **Ask one question, not five**; five questions
get zero answers.

Spoken:

> "I built a thing that answers questions about a documentation set — but
> that part is boring, everyone's built one. The bit I care about is that it
> tells you when not to trust it: it scores whether the retrieved context was
> even sufficient before it writes anything, then checks every sentence of
> the answer against the passages it was given, and shows you the passages it
> *rejected* too. Ten minutes, six questions? The thing I actually need to
> know is whether the evidence panel is useful or whether you ignored it —
> I've spent the most on it and I have no users, so I genuinely don't know."

Written, with the link — same shape, shorter. Send
[`docs/try-atlas.md`](../docs/try-atlas.md) rather than explaining in the
message; it is the tour, and it states the limits up front so they are not
discovered as disappointments.

The question to actually ask, once they have used it: **where in your own
work does someone have to answer "is this answer grounded?" today.** Not
"what did you think". The first is a market signal; the second is politeness.

---

## What not to claim

Stay on the right side of these when the follow-ups come.

- **No users.** Say "built and deployed", never "people use it".
- **One corpus live.** Multi-corpus works and is tested; the public instance
  serves one.
- **0.71 is a real number on 16 questions.** Small set. Say "sixteen
  questions" if pressed — it is honest, and it is more than most can say.
- **Never say "it never hallucinates."** Say "every claim is traceable to a
  source, and it scores 1.000 on that — but traceable is not the same as
  correct, which is why I measure both." That distinction *is* the
  differentiator; lead with it rather than hiding it.
