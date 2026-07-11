# Module B — Hybrid Retrieval

## What it does

Combines dense (semantic) and sparse (keyword) retrieval into a single ranked
list, then reranks the top candidates with a cross-encoder for maximum accuracy.

## Pipeline

```
Query string
    │
    ├──▶ QdrantDenseRetriever  ──┐
    │    (ANN cosine search)      │
    │                             ▼
    └──▶ BM25Retriever  ─────▶ RRF Fusion ──▶ CrossEncoderReranker ──▶ top-k chunks
         (keyword scoring)    (rank merge)    (pairwise relevance)
```

All three stages run in one `HybridRetriever.retrieve(query)` call.

## Stages

### 1. Concurrent retrieval
`asyncio.gather()` fires both retrievers simultaneously. Dense ANN (~10ms) and
BM25 scoring (~5ms) overlap, saving ~30–50% latency vs sequential.

### 2. Reciprocal Rank Fusion
```
RRF(d) = Σ_{r ∈ retrievers} 1 / (k + rank_r(d))
```
- **k = 60** (Cormack et al. standard). Higher k flattens rank differences; lower k amplifies them.
- Score-free: works regardless of cosine vs BM25 scale incompatibility.
- A chunk appearing in only one retriever still gets a partial score.

### 3. Cross-encoder reranking
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (configurable via `RERANKER_MODEL`).
- Input: all fused candidates (up to `RETRIEVAL_TOP_K`).
- Output: top `RERANKER_TOP_K` chunks re-scored by query-document interaction.
- Reranker is **optional** — pass `reranker=None` to skip (useful for A/B eval).

### Why MiniLM?
~95% quality of BERT-large cross-encoder at ~8× the inference speed. The
2-stage architecture (fast ANN → accurate cross-encoder on small pool) delivers
cross-encoder accuracy at ANN latency.

## Configuration

```env
RETRIEVAL_TOP_K=20         # candidates fetched from each retriever
RERANKER_TOP_K=5           # final documents returned to the caller
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
```

## Usage

```python
from atlas.config import get_settings
from atlas.ingestion.embedder import OpenAIEmbedder
from atlas.ingestion.sparse import BM25SparseIndex
from atlas.retrieval import BM25Retriever, CrossEncoderReranker, HybridRetriever, QdrantDenseRetriever

settings = get_settings()
embedder = OpenAIEmbedder(settings.openai)

hybrid = HybridRetriever(
    retrievers=[
        QdrantDenseRetriever(settings.qdrant, embedder),
        BM25Retriever(BM25SparseIndex()),
    ],
    config=settings.retrieval,
    reranker=CrossEncoderReranker(settings.reranker),
    reranker_top_k=settings.reranker.top_k,
)

result = await hybrid.retrieve("What is Atlas?")
for chunk in result.chunks:
    print(chunk.score, chunk.content[:80])

# Full provenance for eval harness:
result.per_retriever   # [RetrievalResult(dense), RetrievalResult(bm25)]
result.fused           # after RRF, before reranking
result.reranked        # final output (= result.chunks)
```

## Tests

```bash
pytest tests/unit/retrieval/ -v
```

All tests are hermetic. Qdrant is mocked for dense retriever tests. Cross-encoder
is mocked via `unittest.mock.patch`. BM25 retriever tests use the real in-memory
index.

## Provenance for eval

`HybridRetrievalResult.per_retriever` lets Module D compute:
- Which fraction of relevant chunks dense-only found vs BM25-only found
- Whether a specific relevant chunk was retrieved by one, both, or neither
- Context precision/recall before and after reranking (A/B comparison)
