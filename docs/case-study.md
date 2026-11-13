# Atlas — case study

*Last checked 2026-11-13. Headline numbers are from the 2026-11-03
evaluation of the live DuckDB 2.0 corpus and are checked by the test suite.
"FastAPI history" marks numbers from the earlier demo corpus.*

## The problem

A system that answers from documents can be wrong in two ways that look the
same from outside. It can miss the passage that holds the answer, or it can
find that passage and still write something it does not say. Most retrieval
demos report one number, usually groundedness, which only catches the second.

Atlas makes both visible on every answer. Each sentence carries a marker
pointing to the passage it came from, the passages it rejected are shown, and
a second model grades the answer before the reader sees it.

The rule from the start was that nothing ships on argument. An evaluation
harness runs 16 labelled questions, each with the pages that answer it and a
reference answer written by hand, and scores five things. Every change is an
A/B run that must also stay inside a written speed and cost budget. The three
decisions below were made on reasoning, and the measurements reversed them.

## Decision 1: the "bug" that was the mechanism

The grader that decides whether retrieval found enough saw only the top 5
passages, while the writer was handed 15. That looked like an obvious bug, so
the grader's window was widened to 15.

The A/B run put it straight back. Recall fell from 0.94 to 0.88, three times
the significance floor, and all of the loss came from the two questions whose
answers span several pages. A grader shown a slice is pessimistic, pessimism
triggers a second retrieval, and that second retrieval adds to the passages
already collected instead of replacing them. The narrow window was how a
five-page answer ever got five pages in front of the writer. The change was
reverted. (FastAPI history; the pair of
runs cost ₹1.57.)

## Decision 2: HyDE, predicted and then measured

HyDE writes a hypothetical answer first and searches with it. Before running it, the
expected result was written down and committed: no net gain, and the verdict
would turn on slow-case latency rather than quality.

Both variants were measured. The better one raised precision by 0.06 but
lowered answer correctness by 0.024, and pushed p95 latency from 13,692 ms to
21,400 ms, past the 20-second ceiling. The variant from the original paper
was worse still: p95 reached 40,778 ms, and it bought nothing the first did
not. HyDE stays off. The prediction got the verdict right and three of its
eight numbers wrong, and that score is on record too. (FastAPI history.)

## Decision 3: the documents every model already knew

The demo first ran on the FastAPI documentation. The first outside person to
try it said GitHub Copilot answered the same questions just as well, and he
was right. Those pages are in the training data of every frontier model, so
retrieval could not show that it added anything.

The demo moved to the DuckDB 2.0 manual, released on 2026-10-21, after the
training cutoff of the models that serve Atlas. Its pages record behaviour
that changed: `X'CAFE'` is now binary data where it used to be text. A model
answering from memory does not refuse; it answers the old way, with full
confidence. Atlas answers the new way, with a citation. Indexing all 226
pages, 3,975 passages, cost ₹0.83.

## Where it stands

On 16 labelled questions, retrieval found every labelled page (recall 1.00),
and faithfulness is 0.99: nearly every claim is backed by a passage the system
really retrieved. Answer correctness against the hand-written references is
0.77. The gap is the point: grounded means nothing was invented, not that the
right conclusion was drawn.

Context precision is 0.51. About half of what reaches the writer is not from
a labelled page, partly because most questions have one labelled page against
fifteen slots. A question takes 7.4 s median end to end, 13.7 s at p95.

## What it costs to run

About ₹0.20 a question, and ₹0 while idle: the server scales to zero and the
vector store sits on a free tier. A full evaluation run costs ₹5.08.

A daily spend cap is checked before every paid call and charged after it,
including calls that fail, because the tokens are spent before a failure,
not instead of it.
When the model provider's prepaid credit runs out, the site says "Demo
paused" instead of failing.

## Limits

Sixteen questions can only detect large differences; smaller ones need a
bigger set. Atlas has no regular users yet: it is built, deployed and
measured, not adopted. Every report and decision, with its numbers, is in the
[repository](https://github.com/hulagerushikesh/atlas).
