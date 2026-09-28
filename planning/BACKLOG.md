# Backlog

Unscheduled work. Move an item into a milestone file when it gets a slot.
Newest at the bottom of each section.

## Bugs

- ~~BM25 index shared across namespaces~~ fixed 00a682b (M1).
- ~~Stale chunks after a document shrinks~~ `prune_document()` after upsert (post-M1).
- ~~Console renders answers as raw markdown~~ both paths render bold/code/lists (post-M1).
- ~~Eval dataset labels fq-002 / fq-008~~ re-labelled (post-M1); fq-002 now
  points at `release-notes` — the only page in the corpus that states a
  Python floor (`index` only carries a badge). Not yet re-run.
- ~~`manifest.json` reported as an ingest error~~ unsupported extensions skipped (post-M1).
- ~~Reranker download on first request~~ the production image bakes the
  weights (`Dockerfile` step 7) and sets `HF_HUB_OFFLINE=1`, so a cold start
  loads from `/opt/hf` and never reaches the Hub (M2).
- ~~Eval metrics in README are placeholders~~ replaced with measured numbers (M1).

## Debts

- `rank-bm25` scores every chunk in Python per query (O(N)). Fine to ~50k
  chunks; replace with Qdrant sparse vectors or Tantivy after that.
- ~~SQLite key store is single-node~~ `AUTH_STORE=firestore` on Cloud Run;
  SQLite stays the local default (M2).
- ~~Fly.io config~~ removed; `docs/deploy.md` is Cloud Run only (M2).
- ~~`console/README.md` is the Vite template default~~ replaced (M2).
- PDF loader is `pypdf` text-only; tables and multi-column layouts degrade.
- Cache is not invalidated on ingest (verify — exercise 08.1). Also the
  API loads the BM25 file once at namespace build; CLI ingest after startup
  is invisible until restart.
- ~~Eval script cannot apply `PipelineConfig.overrides`~~ `--set section.field=value` (post-M1).
- ~~No daily spend cap~~ `BUDGET_DAILY_USD` → 429 + Retry-After (post-M1).
- Streaming errors after first byte become events; document the event
  schema in `docs/api.md`.
- **The grader reads a third of the window it is judging.**
  `grader.py:82` is `_format_context(chunks[:5])`, commented "more adds
  noise" — true when `reranker.top_k` was 5 and the slice was the whole
  window. At 15 the grader calls a retrieval insufficient while the answer
  sits at rank 6, which is how `fq-005` triggered the retry that lost it.
  Now that a retry can no longer discard context the consequence is only a
  wasted round trip, so this is a cost and latency item rather than a
  correctness one. Grading all 15 triples the grader prompt; grading the
  top 10 might be the trade. Needs a full eval either way.
- ~~**Cap and rerank the sub-query merge.**~~ **Shipped 2026-09-27.**
  `_retrieve_all` now round-robins across sub-queries and cuts back to one
  window, re-ranked against the original question when a reranker exists.
  Both halves went in together because they are the same decision: the cap
  without the rerank would have truncated in sub-query order and deleted the
  later sub-questions outright. Precision 0.3412 -> 0.3762, recall unchanged,
  tokens -19%. See DECISIONS 2026-09-27.

- **Make the comparator refuse two different datasets.** `run_eval.py`
  defaults `--dataset` to `sample_dataset.json` (30 HR questions). Running it
  in a FastAPI-corpus repo produces a full, well-formatted report of zeros and
  then a confident `Overall winner` against a 15-sample FastAPI baseline. The
  report does not look broken; only the token count does. Record the dataset
  name and sample ids in `EvalResult` and have `compare()` refuse when they
  disagree. Free, and it removes a whole class of wasted run.

- **The `--dataset` default is a trap.** Same root cause as above, cheaper
  fix: `make eval` passes `$(EVAL_DATA)` correctly, but a bare
  `python scripts/run_eval.py` silently picks the wrong corpus. Either drop
  the default and require the flag, or point it at `fastapi_dataset.json`.

- ~~Relabel `fq-012`~~ **done 2026-09-27.** One document → five, one per
  claim its ground-truth answer makes. STATUS, README and DECISIONS restated
  from an offline replay of all twelve stored reports; the headers' recall
  gain and the "last outright miss" framing were both withdrawn.

- ~~Re-read the other fourteen labels for the same fault.~~ **done
  2026-09-27.** Nine of fifteen rows needed a change; see DECISIONS for the
  table and `metadata.label_rationale` on each row for the reason. Every
  figure in STATUS and README restated from an offline replay, Rs.0.

- **The set has no out-of-scope row, so the refusal path is unmeasured.**
  `fq-015` was the only candidate and it turned out to be answerable from
  `advanced/websockets.md`. Write one that the corpus genuinely cannot
  answer — it has to be plausible enough that the retriever returns
  something, or it tests nothing. Two shapes that would work against this
  corpus: a question about a framework the docs only name in passing
  (`alternatives.md` mentions plenty), or a FastAPI question whose answer
  post-dates the snapshot. Note the cost asymmetry: a new row is free to
  write but cannot be replayed into the existing reports, so the first
  measurement of it needs a paid eval run (~Rs.0.77). Adding it also changes
  the denominator of every aggregate, so do it at a milestone boundary, not
  mid-comparison.

- ~~Guard against the fault the audit found, in the dataset loader.~~
  **done 2026-09-27**, `atlas.evaluation.dataset`. Every label must resolve to
  something `doc_match` could actually match — the checker builds its key set
  the same way the matcher does, so the two cannot drift — and a row with an
  empty `relevant_doc_ids` must carry `metadata.out_of_scope: true`.
  `category: "out_of_scope"` deliberately does not count: `fq-015` carried
  exactly that string while being answerable, so the category was the thing
  that was wrong. `EvalDataset` gained a `corpus_root` field so a dataset says
  what its paths are relative to; without one the resolution check is skipped
  and says so, because skipping quietly is how this survives. Wired into
  `run_eval.py` (before the pipeline is built, so a broken dataset costs
  nothing), `eval_retrieval.py` and `replay_context_metrics.py`; override with
  `--corpus`, bypass with `--allow-broken-dataset`.

  It found one on the first run: `oos-001` in `sample_dataset.json` was
  genuinely out of scope and had never said so. Declared.

  Still not caught, and still needs a person: a label set that is *incomplete*
  (`fq-012` named one real page of five) and a reference answer that names
  things the corpus lacks (`fq-010`). Both resolve fine.

- **Add a correctness metric, or say in the README that there isn't one.**
  `ground_truth_answer` is passed to every metric by `runner.py:171` and read
  by none of them — precision and recall score `relevant_doc_ids`,
  faithfulness scores the answer against the retrieved chunks, answer
  relevance scores the question against questions regenerated from the
  answer. So the harness cannot tell a right answer from a confidently wrong
  one that cites its sources correctly, and a wrong reference answer is
  invisible to it, which is how `fq-010` survived three milestones. Either
  wire up an answer-correctness judge (reference vs generated, one extra LLM
  call per sample, ~+15% eval cost) or state the gap next to the table.
  Stating it is free and honest; the judge is the real fix.

- ~~**Verify what is actually in an index.**~~ **done 2026-09-28**,
  `scripts/verify_index.py`. Reads both halves of every namespace and compares
  chunk counts, chunk ids, content hashes, and header coverage against what
  `chunking.context_headers` asks for. Read-only and free, so it can run
  before and after every ingest. Found a half-finished ingest on its first
  run; see DECISIONS 2026-09-28.

- ~~**A single file ingest baked the whole path into its context headers.**~~
  **fixed 2026-09-28.** `scripts/ingest.py` and the `/ingest` route default a
  bare file's source root to its parent instead of passing `None`;
  `index_directory` gained a `source_root` override for re-indexing a subtree
  of a corpus rooted higher up; `--source-root` and an always-printed
  `Source root:` line make the choice visible. The real hazard was not the
  wasted tokens but the `content_hash` change: a re-ingest of one file gave
  it headers its neighbours lacked. Also fixed `seed_demo.py`, which passed a
  directory to `index_path` and raised before indexing anything.

- ~~**Nothing retried a Qdrant fault, and the client had no timeout.**~~
  **fixed 2026-09-28.** `QdrantConfig.timeout_seconds` (default 60) is passed
  to every `AsyncQdrantClient`; before this qdrant-client handed httpx no
  timeout at all, so the default was 5s. `is_transient_qdrant_error` plus a
  tenacity ladder now covers the write path (5 attempts, 1-20s) and the query
  path (3 attempts, 0.5-4s). The retry sits on the private single-call methods
  so a resend never repeats an upsert batch that already landed.

- **Ship the context headers to the `default` namespace — PARTIALLY DONE and
  currently inconsistent.** Cost approved 2026-09-27; the auto-mode classifier
  refused the write to the live collection, correctly, so the user runs it.
  The 2026-09-28 run landed 3950/4020 sparse chunks but only 2090/4020 dense,
  leaving 1860 content hashes differing between the two halves — a mismatched
  hybrid serving production now. Re-run the same ingest; the content-hash
  dedupe means only the ~1930 missing dense chunks are re-embedded, so it is
  roughly Rs.3.10 rather than Rs.6.45. Confirm with `verify_index.py` before
  deploying. Two steps, and the order matters:

      cd <repo root> && .venv/bin/python scripts/ingest.py data/corpus/fastapi --namespace default
      cd <repo root> && ./scripts/deploy_gcp.sh

  **Re-ingest first, deploy second.** The BM25 index is baked into the image
  (`Dockerfile:34`, `ATLAS_INDEX_DIR=/app/data/index`), so the ingest has to
  rewrite `data/index/default/bm25_index.json` *before* the build copies it.
  Between the two steps production runs headers in the dense index, which is
  live the moment the ingest finishes, against the old sparse index — a
  mismatched hybrid until the deploy lands.

  Rollback without re-embedding is only partial: the pre-header BM25 file is
  kept at `data/index-backup/bm25_index.json` (gitignored, and outside the
  path the image bakes), but the dense vectors are overwritten in place. A
  full revert is `CHUNK_CONTEXT_HEADERS=false` plus another ~Rs.6.45 ingest.

## Ideas (research-backed, see learning/09)

- HyDE retriever behind a config flag.
- Contextual retrieval at ingest (LLM-written chunk context).
- ~~BM25 tokeniser: keep identifiers, split camelCase~~ shipped cb4e28d;
  measured neutral end to end, see DECISIONS 2026-09-23.
- ~~Rerank top_k 5 → 10–15~~ shipped 6443bb6 at 15; recall 0.778 → 0.900.
  The **lost-in-the-middle ordering** half is still open and matters more now
  that the window is three times wider.
- Local embedding model option (bge-small / e5-small) for zero-cost dev.
- Parent-child chunks: retrieve small, hand the LLM the parent.
- Unanswerable-question samples in the eval set to measure refusal.
  **Now cheap:** refusals are detected and excluded from faithfulness
  (2026-09-24), so such samples would score the refusal rate directly
  instead of poisoning the mean.
- Citation precision metric: does the cited chunk support *that* sentence.
- Console: per-key usage page; ingest-from-console with progress events.

## Nice to have

- `make demo` — seed a tiny corpus and open the console.
- Keyboard shortcut cheat-sheet in the console (`?`).
- Export a query's full evidence as JSON from the Evidence pane.
