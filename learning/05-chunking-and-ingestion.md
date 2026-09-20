# 05 — Chunking & Ingestion

Retrieval quality is decided before any query runs. What you put in the index
is what you can get out.

## Why chunk at all

- Embedding models have a context limit (8,191 tokens for OpenAI v3) and
  their quality degrades long before it — one vector for a 30-page PDF is
  mush.
- The LLM's context window is finite and costs money per token. You want to
  hand it the five paragraphs that answer the question, not five documents.
- Citations. A chunk with `start_char`/`end_char`/`page_number` can be
  pointed at. A whole document cannot.

## The three strategies in Atlas (`ingestion/chunkers/`)

| Strategy | How | Good for | Cost |
|---|---|---|---|
| `fixed` | Every `size` tokens with `overlap` | Baseline; homogeneous text | free |
| `recursive` | Split at headings → paragraphs → sentences → words until under `size` | Docs, markdown, code (default) | free |
| `semantic` | Embed sentences, split where adjacent similarity drops | Prose without structure | embedding calls per doc |

`config.py`: `ChunkingConfig.size = 512`, `overlap = 64`, `strategy = "recursive"`.
`factory.py` maps the string to a class; `interfaces/chunker.py` is the ABC.

Overlap is insurance: a sentence that straddles a boundary appears whole in
at least one chunk.

## Chunk size is a real hyperparameter

Small chunks (128–256): precise, more of them, each vector is specific, but
loses surrounding context ("it" refers to what?). Large chunks (1024+):
context-rich, fewer vectors, but each vector is vaguer and the LLM pays for
more filler. 512 with 64 overlap is a defensible default; the eval harness
(module 07) is how you find *your* corpus's answer. Expect context precision
to rise as chunks shrink and context recall to rise as they grow.

## Metadata is retrieval

Every chunk carries `source`, `doc_type`, `chunk_index`, `page_number`,
`start_char`, `end_char` (`interfaces/document.py`). This is what makes
citations deep-linkable, what lets the console list sources, and what filtered
retrieval ("only in `tutorial/`") would use via Qdrant payload filters.

## Idempotent ingestion (`ingestion/hashing.py`, `indexer.py`)

Content is fingerprinted with xxhash. Re-running ingest on an unchanged file
skips it; a changed file re-embeds only its chunks. Without this every
re-index costs the full embedding bill and duplicates points. The
`Indexer` orchestrates load → chunk → **ask the dense index which chunk ids
are unchanged** → embed only the rest → upsert dense → add sparse, and
reports counts.

The hash check only works if ids are stable. `Document.id` is
`uuid5(source)` and `Chunk.id` is `uuid5(doc_id:chunk_index)`
(`interfaces/document.py`). Until 2026-09-20 they were `uuid4()` per run, so
the hash lookup never found anything and three ingests produced 8,278 points
for a 3,427-chunk corpus — the tests were green because every test built
the ids once. Lesson: idempotency is a property of the *key*, not the hash.
Remaining gap: a document that shrinks leaves its old tail chunks behind.

## Loaders (`ingestion/loaders/`)

PDF (pypdf, page-aware), Markdown, HTML (strips tags, keeps text), plain
text. `registry.py` maps extension → loader. PDF is where quality varies most:
tables, two-column layouts and scanned pages need better tooling
(`unstructured`, `marker`, `docling`) — a known upgrade path.

## Research-level chunking

- **Contextual retrieval** (Anthropic, 2024): before embedding each chunk,
  have an LLM prepend a one-sentence summary of where it sits in the
  document ("This chunk is from the FastAPI path-parameters tutorial, section
  on type validation"). Reported ~35% fewer retrieval failures; ~50% combined
  with BM25 + rerank. Costs one cheap LLM call per chunk at ingest.
- **Late chunking** (Günther et al., 2024): embed the *whole* document with a
  long-context model, *then* pool token embeddings per chunk. Each chunk
  vector knows its neighbours. No LLM cost, needs a long-context embedder.
- **Proposition chunking**: split into atomic factual statements rather than
  spans. Very precise retrieval; expensive to produce.
- **Parent-child**: retrieve small chunks, return their larger parent to the
  LLM. Best of both sizes; easy to add to Atlas via metadata.
- **RAPTOR**: recursively cluster and summarise chunks into a tree; retrieve
  from every level. Helps questions that need the whole document.

## Read

1. Anthropic, *Introducing Contextual Retrieval* (blog, Sep 2024).
2. Günther et al., *Late Chunking* (2024), arXiv:2409.04701.
3. Sarthi et al., *RAPTOR* (2024), arXiv:2401.18059.
4. Barnett et al., *Seven Failure Points When Engineering a RAG System*
   (2024), arXiv:2401.05856 — half the failures are ingestion.
5. LangChain / LlamaIndex docs on text splitters — for the catalogue of
   strategies, not the code.

## Exercise

[exercises.md → 05](exercises.md#05-chunking--ingestion)
