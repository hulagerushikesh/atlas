# Backlog

Unscheduled work. Move an item into a milestone file when it gets a slot.
Newest at the bottom of each section.

## Bugs

- **BM25 index shared across namespaces.** `api/namespaces.py` constructs
  `BM25SparseIndex()` with the default `bm25_index.json` for every
  namespace, so all sheets share one sparse index. Breaks tenancy for the
  lexical half. Fix: per-namespace persist path + integration test.
  *Scheduled: M1 step 6.*
- **Reranker download on first request.** `CrossEncoderReranker` loads the
  model lazily at construction inside lifespan — first cold start pays
  ~90 MB download. Pre-bake into the Docker image.
- **Eval metrics in README are placeholders.** Never quote until M1 step 7.

## Debts

- `rank-bm25` scores every chunk in Python per query (O(N)). Fine to ~50k
  chunks; replace with Qdrant sparse vectors or Tantivy after that.
- SQLite key store is single-node. M2 moves it to Firestore.
- Fly.io config (`fly.toml`, `docs/deploy.md` §Fly) will be dead after M2.
- `console/README.md` is the Vite template default — replace with the two
  paragraphs from `CLAUDE.md`.
- `out/` directory is empty and untracked — delete.
- PDF loader is `pypdf` text-only; tables and multi-column layouts degrade.
- Cache is not invalidated on ingest (verify — exercise 08.1).
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
