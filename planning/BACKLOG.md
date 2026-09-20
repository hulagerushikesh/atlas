# Backlog

Unscheduled work. Move an item into a milestone file when it gets a slot.
Newest at the bottom of each section.

## Bugs

- ~~BM25 index shared across namespaces~~ fixed 00a682b (M1).
- **Stale chunks after a document shrinks.** Ids are `(doc, chunk_index)`;
  if a re-ingested doc produces fewer chunks, the tail chunks from the old
  version stay in both indexes. Fix: after upsert, delete ids for that doc
  with `chunk_index >= len(chunks)`.
- **Console renders streamed answers as raw markdown** (`**`, backticks
  visible). Non-streamed path is fine. Render markdown in the stream path.
- **Eval dataset labels.** fq-008 should point at `advanced/stream-data`;
  fq-002 at `features` (Python version). Re-label before M3 so recall moves
  for real reasons.
- **`manifest.json` in the corpus dir** is reported as an ingest error every
  run. Ignore non-loader extensions silently, or move the manifest.
- **Reranker download on first request.** `CrossEncoderReranker` loads the
  model lazily at construction inside lifespan — first cold start pays
  ~90 MB download. Pre-bake into the Docker image.
- ~~Eval metrics in README are placeholders~~ replaced with measured numbers (M1).

## Debts

- `rank-bm25` scores every chunk in Python per query (O(N)). Fine to ~50k
  chunks; replace with Qdrant sparse vectors or Tantivy after that.
- SQLite key store is single-node. M2 moves it to Firestore.
- Fly.io config (`fly.toml`, `docs/deploy.md` §Fly) will be dead after M2.
- `console/README.md` is the Vite template default — replace with the two
  paragraphs from `CLAUDE.md`.
- PDF loader is `pypdf` text-only; tables and multi-column layouts degrade.
- Cache is not invalidated on ingest (verify — exercise 08.1). Also the
  API loads the BM25 file once at namespace build; CLI ingest after startup
  is invisible until restart.
- Eval script cannot apply `PipelineConfig.overrides` yet (reranker off A/B
  needs it). Wire overrides → Settings before M3.
- No daily spend cap like sextant's `SEXTANT_DAILY_BUDGET_USD`. Add one
  before M2 exposes the API publicly.
- Streaming errors after first byte become events; document the event
  schema in `docs/api.md`.

## Ideas (research-backed, see learning/09)

- HyDE retriever behind a config flag.
- Contextual retrieval at ingest (LLM-written chunk context).
- BM25 tokeniser: keep identifiers, split camelCase.
- Rerank top_k 5 → 10–15 with lost-in-the-middle ordering.
- Local embedding model option (bge-small / e5-small) for zero-cost dev.
- Parent-child chunks: retrieve small, hand the LLM the parent.
- Unanswerable-question samples in the eval set to measure refusal.
- Citation precision metric: does the cited chunk support *that* sentence.
- Console: per-key usage page; ingest-from-console with progress events.

## Nice to have

- `make demo` — seed a tiny corpus and open the console.
- Keyboard shortcut cheat-sheet in the console (`?`).
- Export a query's full evidence as JSON from the Evidence pane.
