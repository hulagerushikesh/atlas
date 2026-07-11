# Module A — Ingestion & Indexing

## What it does

Takes raw files (PDF, Markdown, HTML, text), extracts text, splits into chunks,
embeds them, and writes to two parallel indexes: a **dense vector index** (Qdrant)
for semantic search and a **sparse BM25 index** for keyword search.

## Pipeline

```
File path
   │
   ▼
LoaderRegistry          picks loader by file extension
   │
   ▼
BaseDocumentLoader      extracts text, computes content_hash
   │
   ▼  (skip if hash unchanged ← idempotency)
   │
   ▼
BaseChunker             splits Document → list[Chunk]
   │   fixed-size / recursive / semantic
   │
   ▼
OpenAIEmbedder          batch embeds all chunks in one API call
   │
   ├──▶ QdrantDenseIndex    upsert with skip-if-hash-unchanged
   └──▶ BM25SparseIndex     upsert + rebuild + persist to disk
```

## Components

### Loaders (`ingestion/loaders/`)

| Loader | Extensions | Notes |
|---|---|---|
| `PDFLoader` | `.pdf` | pypdf; raises on scan-only PDFs |
| `MarkdownLoader` | `.md` `.markdown` | Preserves raw markup for better chunker signals |
| `TextLoader` | `.txt` `.rst` | UTF-8 with error replacement |
| `HTMLLoader` | `.html` `.htm` | Strips script/style; captures title + h1 in metadata |

Register a custom loader: `registry.register(MyLoader())`.

### Chunkers (`ingestion/chunkers/`)

| Strategy | `CHUNK_STRATEGY=` | Best for |
|---|---|---|
| `FixedSizeChunker` | `fixed` | Baseline evaluation; predictable token budgets |
| `RecursiveChunker` | `recursive` | Mixed documents (default); respects paragraph/heading structure |
| `SemanticChunker` | `semantic` | Long multi-topic docs; adds one embedding call per document |

**RecursiveChunker separator hierarchy:**
`\f` → `\n## ` → `\n### ` → `\n\n` → `\n` → `. ` → ` ` → char

### Idempotent re-indexing

Every `Document` and `Chunk` carries a `content_hash` (xxh3_64 of raw bytes).
On upsert, both indexes check the stored hash before writing. Unchanged chunks
are skipped with zero API calls. This makes scheduled re-indexing safe to run
continuously without wasteful re-embedding.

### Dual-index rationale

Dense (ANN) retrieval misses exact matches; BM25 misses paraphrases.
Running both and fusing in Module B consistently outperforms either alone on
heterogeneous enterprise corpora (see Module D eval reports).

### BM25 persistence tradeoff

`rank-bm25` has no incremental update API. The full corpus is tokenised and the
index rebuilt on each upsert. For ≤100k chunks this takes <1s. For larger
corpora, replace with Elasticsearch or Qdrant sparse vectors. The JSON
persistence format is intentionally portable — no pickle compatibility risk.

## Configuration

```env
CHUNK_STRATEGY=recursive    # fixed | recursive | semantic
CHUNK_SIZE=512
CHUNK_OVERLAP=64
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSIONS=1536
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION_NAME=atlas_chunks
```

## Usage

```python
from atlas.config import get_settings
from atlas.ingestion.chunkers import get_chunker
from atlas.ingestion.dense import QdrantDenseIndex
from atlas.ingestion.embedder import OpenAIEmbedder
from atlas.ingestion.indexer import DocumentIndexer
from atlas.ingestion.sparse import BM25SparseIndex

settings = get_settings()
embedder = OpenAIEmbedder(settings.openai)
chunker  = get_chunker(settings, embedder=embedder)
indexer  = DocumentIndexer(
    chunker=chunker,
    embedder=embedder,
    dense_index=QdrantDenseIndex(settings.qdrant, embedder.dimensions),
    sparse_index=BM25SparseIndex(),
)

result = await indexer.index_directory(Path("./docs"))
print(result)  # IndexResult(docs_processed=12, chunks=340, tokens=28400)
```

## Tests

```bash
pytest tests/unit/ingestion/ -v
```

All tests are hermetic (no network, no Qdrant). The indexer tests mock the
embedder and both indexes. The BM25 tests use `tmp_path` for persistence.
