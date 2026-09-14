# 02 — Embeddings & Vector Search

Dense retrieval: turn text into vectors, find the nearest ones.

## The idea

An embedding model is trained so that texts with similar *meaning* land close
together in vector space. "How are path params validated?" and "FastAPI
converts and checks `item_id: int`" share few words but sit near each other.
Lexical search cannot see that; embeddings can.

Two-tower / **bi-encoder**: query and document are embedded *independently*,
so documents can be embedded once at ingest time and only the query is
embedded at query time. This is what makes dense retrieval fast enough to use.
The price is that the model never sees query and document together — that is
what the reranker (module 04) fixes.

## In Atlas

- `ingestion/embedder.py` — `OpenAIEmbedder`, batches texts to the embeddings
  API, retries via `retry_policy.py`. `interfaces/embedder.py` is the ABC; tests
  use a deterministic stub.
- `ingestion/dense.py` — `QdrantDenseIndex`: creates the collection (cosine,
  1536 dims), upserts points with the chunk as payload.
- `retrieval/dense.py` — `QdrantDenseRetriever`: embeds the query, calls
  `query_points()` (not the removed `search()`), returns `RetrievalResult`s.
- `config.py` — `embedding_model`, `embedding_dimensions`, `top_k = 20`.

## Approximate nearest neighbour (ANN)

Exact nearest neighbour over N vectors is O(N·d). Fine for 10k chunks,
unusable at 10M. ANN indexes trade a little recall for orders of magnitude of
speed.

**HNSW** (Hierarchical Navigable Small World) is what Qdrant uses. Picture a
skip-list of graphs: a sparse top layer for coarse jumps, denser lower layers
for refinement. Search greedily walks toward the query at each layer. Two
knobs: `M` (edges per node — memory vs recall) and `ef` (beam width at search
time — latency vs recall). Qdrant's defaults are fine until you measure
otherwise.

Other families worth knowing the names of: IVF (cluster then search a few
clusters), PQ (compress vectors to bytes), DiskANN (SSD-resident graphs).

## Choosing an embedding model

- **MTEB** is the leaderboard. Look at the *retrieval* column, not the
  average — Atlas cares about retrieval.
- Dimensions: 1536 (OpenAI small) vs 3072 (large) vs 768/1024 (most open
  models). More dims ≠ better; check MTEB retrieval and the cost of storing them.
- **Matryoshka** embeddings can be truncated (1536 → 256) with graceful
  degradation. OpenAI's v3 models support this via the `dimensions` param.
- Open alternatives that run locally: `bge-*`, `e5-*`, `nomic-embed`,
  `gte-*`. Same interface, no API bill — a good first Atlas experiment.

## Where dense retrieval fails

- Exact identifiers: error codes, function names, version numbers. The model
  smooths them into "something technical". BM25 nails them.
- Out-of-domain vocabulary the model never saw.
- Long chunks: one vector for 2,000 tokens averages away the specifics.
- Negation: "without authentication" embeds close to "with authentication".

Every one of these is why Atlas is *hybrid*, not dense-only.

## Read (in order)

1. Reimers & Gurevych, *Sentence-BERT* (2019), arXiv:1908.10084 — where
   bi-encoders for semantic search come from.
2. Karpukhin et al., *Dense Passage Retrieval* (2020), arXiv:2004.04906 —
   dense retrieval beating BM25 on open-domain QA; read the negatives section.
3. Malkov & Yashunin, *HNSW* (2016), arXiv:1603.09320 — skim §3–4 for the
   layered graph picture.
4. Muennighoff et al., *MTEB* (2022), arXiv:2210.07316 — how models are
   compared; know the task categories.
5. Kusupati et al., *Matryoshka Representation Learning* (2022),
   arXiv:2205.13147 — why truncating embeddings works.
6. Wang et al., *E5* (2022), arXiv:2212.03533 — how a strong open embedding
   model is trained (weak supervision at scale).

## Exercise

[exercises.md → 02](exercises.md#02-embeddings-and-vector-search)
