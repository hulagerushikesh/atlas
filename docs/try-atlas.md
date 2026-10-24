# Try Atlas

A guide for someone who has never seen this project. Written for engineers —
it assumes you know what an HTTP API is and nothing about this codebase.

Reading time ~5 minutes. Trying it takes about ten.

---

## What Atlas is

Atlas answers questions about a body of documents, with a citation on every
claim, and then tells you how much to trust its own answer.

The first half of that is retrieval-augmented generation (RAG) and is not
interesting — everybody builds one. The second half is the point. A RAG
system that is confidently wrong looks exactly like one that is right: same
fluent paragraph, same citation markers, same tone. Most of them ship with no
instrument for telling those two cases apart, so nobody finds out which one
they have until a user does.

Atlas is built around that instrument. Every run tells you:

- which passages were retrieved, **including the ones it rejected**;
- whether the retrieved context was even sufficient, scored *before* the
  answer was written;
- whether each sentence of the answer is actually supported by the passages
  the model was given;
- how long each stage took and what the call cost in tokens.

The corpus on the live instance is the **FastAPI documentation** — 155 pages,
4,020 chunks. That is a deliberate choice: it is a real corpus, it is large
enough to be hard, and as an engineer you can check the answers yourself.

---

## 1. Get in

Open **<https://atlas.hulage.in/app>**.

The console loads without a key. Asking a question needs one, because every
question costs real money in model calls. Ask Rushikesh for a key — it looks
like `atlas_…`.

Then: **Settings** (the gear, top right) → paste the key into **API key** →
Save.

> **First request is slow.** The service scales to zero when idle, so the
> first query after a quiet spell waits ~12 s for the container and the
> cross-encoder model to load. Everything after that is normal speed. This is
> a cost decision, not a bug — idle costs ₹0.

---

## 2. Ask something

Type into the box in the middle and press Enter. Try:

```
How does dependency injection work in FastAPI?
```

Four things are now on screen:

| Where | What it is |
|---|---|
| **Left — corpus** | The documents in the current sheet. A "sheet" is a namespace: one isolated corpus. |
| **Middle — answer** | The answer, with a numbered reference on each claim. |
| **Right — evidence** | Every passage that was retrieved, with its scores. |
| **Bottom — survey** | The pipeline, stage by stage, with timings. |

Below `1100px` the evidence pane becomes a drawer — open it from the layers
button in the header.

---

## 3. The part worth your attention

### The verdict badge

Next to the answer is one of:

| Badge | Means |
|---|---|
| **Supported** | Faithfulness check passed, score ≥ 0.8, no retries needed. |
| **Mixed** | Passed, but weakly — or it needed to re-retrieve before it could answer. |
| **Weak** | Score 0.3–0.5. Treat the answer as a draft. |
| **Unsupported** | The answer makes claims the retrieved passages do not support. |
| **Out of scope** | The router decided the question is not about this corpus, and refused before spending anything on it. |
| **Unchecked** | You used the streaming path, which skips the faithfulness check. Not a pass — an absence. |

**This is the feature.** Most RAG demos have no equivalent, which means they
report "Supported" for every answer by saying nothing at all.

### The evidence pane

It lists everything retrieved, not just what got cited. Passages the reranker
cut are shown greyed, and the generator never saw them. That is half of what
makes a run reviewable: you can see what Atlas considered *and rejected*, so a
bad answer can be diagnosed as a retrieval failure rather than guessed at.

Each passage carries its whole score trail — `dense`, `bm25`, `rrf`, `rerank`.
Dense is vector similarity, BM25 is lexical, RRF fuses the two rankings, and
the cross-encoder reranks the survivors. A passage that scores high on BM25
and low on dense is an exact-match hit; the reverse is a paraphrase.

### The survey bar

`route → decompose → retrieve → grade → generate → check`, with per-stage
milliseconds. Blue stages are retrieval, amber are model calls. A stage that
never ran is drawn dashed — a simple question skips `decompose`.

`grade` is the one to watch. It scores whether the retrieved context is
sufficient **before** generation, and if it is not, the pipeline retrieves
again with an accumulated context rather than answering from what it has.

### Export

The download button in the evidence header (or `⌘K` → "Export this run as
JSON") writes the whole run to a file: question, answer, verdict, every
retrieved passage with scores, stage timings, token usage. Nothing is
uploaded — the file is built in your browser.

If something looks wrong, **export it and send me the file**. That is far
more useful than a screenshot, because it contains what the model was
actually given.

---

## 4. Things worth trying

The interesting questions are the ones designed to make it fail honestly.

1. **Something outside the corpus** — "What is the capital of France?" It
   should refuse with *Out of scope* and spend nothing on retrieval.
2. **Something adjacent but absent** — ask about a FastAPI feature released
   after the corpus snapshot. Watch whether it admits the gap or invents.
3. **A multi-part question** — "What is the difference between a dependency
   and middleware, and when would I use each?" Watch `decompose` light up.
4. **An exact identifier** — a class or parameter name such as
   `use_cache=False`. This is where BM25 earns its place; dense-only
   retrieval tends to miss literal tokens.
5. **Something ambiguous** — "How do I make it faster?" See whether the
   grader catches the insufficient context before the generator papers over
   it.

What I want back: cases where the **badge is wrong**. An answer marked
*Supported* that is not, or marked *Weak* that is fine. The badge being wrong
is a much more serious bug than the answer being wrong.

---

## 5. Using the API instead

Same key, `Authorization: Bearer`. OpenAPI at
<https://atlas.hulage.in/docs>.

```bash
curl -s https://atlas.hulage.in/query \
  -H "Authorization: Bearer $ATLAS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "How does dependency caching work?", "namespace": "default", "top_k": 5}'
```

Response carries `answer`, `citations`, `evidence` (with the full score
trail), `faithfulness_score`, `is_faithful`, `grader_score`, `timings` and
`token_usage`.

Token-by-token streaming — note this path skips the faithfulness check:

```bash
curl -N https://atlas.hulage.in/query \
  -H "Authorization: Bearer $ATLAS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is a sub-dependency?", "stream": true}'
```

Unauthenticated and free: `/health`, `/namespaces`,
`/namespaces/{sheet}/sources`, `/metrics` (Prometheus), `/docs`.

---

## 6. Limits, stated up front

- **One corpus live.** Multi-corpus is built and tested; the public instance
  serves the FastAPI docs only.
- **60 requests/minute** per key, and a **daily spend cap** on the whole
  service. If you hit the cap, queries stop until the next day. This is
  intentional — it is my credit card.
- **Cold start ~12 s** after idle.
- **Accuracy: 0.71** against human-written reference answers, on a 16-question
  set. Small set. It is a real number, which is more than most such systems
  can produce at all.
- **Groundedness: 1.000** — every claim traces to a source. That is not the
  same as being correct, and the gap between those two numbers is the whole
  reason the project exists.
- **No users yet.** You are among the first. That is why I am asking.

---

## 7. What I want from you

Ten minutes, five or six questions, and honest answers to three things:

1. **Did you trust it?** At which exact moment did you stop or start?
2. **Was the evidence pane useful, or noise?** It is the thing I have spent
   the most on. If you ignored it, say so — that is the most valuable thing
   you could tell me.
3. **Where would you actually use this?** Not "this is cool" — a real place
   in your own work where "is this answer grounded?" is a question somebody
   has to answer today.

Bugs, confusing copy, anything that looked broken: export the run and send
the JSON.

---

## If you want to read the code

<https://github.com/hulagerushikesh/atlas> — Python 3.11, FastAPI, Qdrant,
React console. Starting points:

| You want | Read |
|---|---|
| The shape of the thing | `README.md` |
| Why it is built this way | `planning/PITCH.md` |
| Retrieval internals | `docs/retrieval.md` |
| The agent graph | `docs/orchestration.md` |
| How accuracy is measured | `docs/evaluation.md` |
| Decisions and the ones that were reversed | `planning/DECISIONS.md` |

`planning/DECISIONS.md` is the honest one — it records the things that were
measured and then thrown away, including a HyDE implementation that did not
earn its cost.
