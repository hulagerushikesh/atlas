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

- **Relabel `fq-012`, and re-read the rest of the set for the same fault.**
  Its ground truth spans plain type hints, `Query()`/`Path()`/`Body()`
  constraints and nested bodies; its `relevant_doc_ids` names one page. It has
  been quoted as "the last outright miss" for three sessions and was part of
  the case for a Rs.6.45 re-ingest. Free to fix, and every precision number in
  the README depends on these labels being right.

- **Ship the context headers to the `default` namespace — BLOCKED, user must
  run it.** Cost approved 2026-09-27; the auto-mode classifier refused the
  write to the live collection, correctly. Two steps, and the order matters:

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
