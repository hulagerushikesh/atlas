# Interview sheet

The twelve questions an interviewer will ask about Atlas, each with a
three-sentence answer and the number behind it. Numbers come from the
2026-11-03 evaluation of the live DuckDB 2.0 corpus unless marked as FastAPI
history; the test suite checks the headline ones. Last checked 2026-11-13.

---

**1. What is Atlas, in one breath?**
You give it documents and ask questions; every sentence of the answer
carries a marker pointing to the exact passage it came from. Then it grades
its own answer, so you can see how far to trust it. It is live at
atlas.hulage.in on the DuckDB 2.0 manual, released after today's models were
trained, so an answer cannot come from a model's memory.
**Number:** 226 pages, 3,975 passages, 16 labelled questions.

**2. Why hybrid retrieval and not just vectors?**
Embeddings are good at paraphrase and bad at exact tokens such as function
names; BM25 keyword search has the opposite strengths. Atlas runs both and
fuses the two ranked lists with Reciprocal Rank Fusion, which needs no score
calibration. A small cross-encoder then rereads each candidate together with
the question and reorders them.
**Number:** widening the rerank window from 5 to 15 took recall from 0.778
to 0.900 (FastAPI history).

**3. Why "agentic", and why not a free-roaming agent?**
It is a fixed graph: a router sorts the question into simple, complex or out
of scope, complex ones are split into sub-questions, and a grader checks
whether the retrieved passages are enough before anything is written. If
they are not, it retrieves again and adds to what it has rather than
replacing it. A fixed graph keeps speed and cost predictable, which a free
agent does not.
**Number:** 7.4 s median, 13.7 s at p95.

**4. How do you know the answers are any good?**
An evaluation harness runs 16 hand-labelled questions, each with the pages
that answer it and a reference answer written by hand. It scores five
things: did retrieval find the right pages, how much of what it found was
noise, are the claims backed, is the answer on topic, and does it match the
reference. Every change is an A/B run that must also stay inside a written
speed and cost budget.
**Number:** recall 1.00, faithfulness 0.99, relevance 0.87, precision 0.51,
correctness 0.77.

**5. Groundedness is 0.99 but correctness is 0.77 — what does that gap mean?**
Nearly every sentence was traceable to a passage the system really
retrieved, yet about a quarter of the substance still did not match the
reference. Grounded only means nothing was invented; it says nothing about
whether the right passage was found or the right conclusion drawn. Most RAG
projects stop at groundedness and call hallucination solved, which is why
the fifth metric exists.
**Number:** 0.99 against 0.77, in the same run.

**6. What is your weakest number?**
Context precision: about half of what retrieval hands the generator is not
from a labelled page. Part of that is how it is counted — most questions
have one labelled page against fifteen slots, so a perfect run scores 0.067
on such a question. The rest is real noise, and the cross-encoder rerank is
what keeps it from reaching the answer.
**Number:** context precision 0.51.

**7. Tell me about a decision the measurements overturned.**
The grader saw only the top 5 passages while the generator got 15, which
looked like an obvious bug, so I widened the grader to 15. The A/B run put it
straight back: recall fell, all of it on questions whose answer spans several
pages. A grader shown a slice is pessimistic, pessimism triggers a retry,
and the retry is what collected the extra pages — the bug was the mechanism.
**Number:** recall 0.9378 to 0.8778 (FastAPI history).

**8. Something you tried that did not work?**
HyDE — writing a hypothetical answer first and searching with it — was
predicted in writing, then measured in both of its variants. It raised
precision but lowered correctness and pushed slow-case latency past the
budget. It stays off, and the prediction and both runs are on record.
**Number:** p95 13,692 ms to 21,400 ms, correctness −0.024 (FastAPI history).

**9. What does it cost to run, and what stops a runaway bill?**
About ₹0.20 a question and ₹0 while idle: the server scales to zero and the
vector store is on a free tier. A daily spend cap is checked before every
paid call and charged after it, including calls that fail, because tokens
are spent before a failure, not instead of it. The spend counter was checked
against the real invoice.
**Number:** ₹0.20 a question, ₹5.08 for a full evaluation run.

**10. What did your tests miss?**
The first live run found six defects that 252 green unit tests could not,
because each one lived between two components that were individually
correct. The worst: the router refused every real question about the
documents as "general coding help", because nothing had told it what the
documents covered. The lesson I kept is that a green suite says the parts work,
not that the path does.
**Number:** 6 defects, 252 green tests.

**11. How is this different from Copilot?**
On a subject a model was trained on, Copilot is as right and faster — I
concede that first. The difference is that every Atlas answer can be
audited: each claim points at a character range in a named file, the
rejected passages are shown, and a second model gives a verdict. On DuckDB
2.0, asked what `X'CAFE'` produces, a model answering from memory is wrong
and Atlas is right with a citation.
**Number:** one sample answer: 38 passages found, 5 cited, 33 rejected shown.

**12. What are its limits, and what would you do next?**
It has no regular users yet, the evaluation set is 16 questions, and the
public site serves one document set. Next is outside people using it and
reporting what confused them, then a larger question set so smaller
differences become measurable. I say "built, deployed and measured", never
"people use it".
**Number:** 16 questions; 6 questions from 2 invited people so far.
