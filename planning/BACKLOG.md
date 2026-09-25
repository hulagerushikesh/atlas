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
- **`reranker.top_k` is a per-sub-query cap, not a window size.**
  `RAGPipeline._retrieve_all` deduplicates the sub-query results by chunk_id
  and merges them, but never truncates, so a question the router calls
  complex hands the generator up to `sub_queries x top_k` chunks.
  `fq-013` sent 30 on the 2026-09-24 run. At `top_k` 5 the worst case was 15
  and nobody noticed; at 15 it is 45. Two things to decide together: whether
  to cap the merged list, and whether to rerank across sub-queries — the
  merge is in sub-query order, so the best chunk for the second sub-question
  sits below the worst chunk for the first, which is exactly the position
  lost-in-the-middle says is worst. Needs a full eval, not a guess.

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
