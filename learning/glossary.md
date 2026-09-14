# Glossary

**ANN** — Approximate nearest neighbour. Trades a little recall for large
speed-ups when searching vectors. HNSW is the common algorithm.

**Bi-encoder** — Model that embeds query and document separately; enables
pre-computing document vectors. Fast, approximate.

**BM25** — Lexical ranking function: TF with saturation × IDF × length
normalisation. Scores are corpus-relative and unbounded.

**Chunk** — A span of a document small enough to embed and cite. Carries
`source`, `chunk_index`, `start_char`, `end_char`, `page_number`.

**Citation** — `[n]` marker in the answer bound to a specific chunk id.

**Claim** — Atomic factual statement extracted from an answer for
verification.

**Context precision / recall** — Retrieval metrics: fraction of retrieved
chunks that are relevant / fraction of relevant docs that were retrieved.

**Cosine similarity** — Dot product of unit-normalised vectors. Qdrant
returns it as a similarity (higher = closer).

**CRAG** — Corrective RAG: grade retrieval, retry or fall back on failure.

**Cross-encoder** — Model that reads query and document together and outputs
a relevance score. Accurate, ~100× slower than a bi-encoder; used to rerank.

**Decomposition** — Splitting a complex question into sub-questions retrieved
independently.

**Dense retrieval** — Retrieval by embedding similarity.

**Embedding** — Fixed-size float vector representing text meaning.

**Evidence** — In Atlas, every chunk seen by any retrieval stage, with
per-stage scores and `selected` flag.

**Faithfulness** — Fraction of answer claims supported by the evidence.

**Grader** — LLM call that scores whether retrieved context can answer the
question; triggers reformulate-and-retry below threshold (0.5).

**HNSW** — Hierarchical Navigable Small World graph; Qdrant's ANN index.

**Hybrid retrieval** — Dense + sparse, fused.

**HyDE** — Hypothetical Document Embeddings: embed an LLM-written guess at
the answer instead of the question.

**IDF** — Inverse document frequency; rare terms weigh more.

**Idempotent ingestion** — Re-running ingest on unchanged content does
nothing; content hashes (xxhash) decide.

**L1 / L2 cache** — In-process LRU / shared Redis.

**LLM-as-judge** — Using a model to score outputs; biased, needs
calibration.

**MTEB / BEIR** — Embedding benchmark / zero-shot retrieval benchmark.

**Namespace** — Isolated corpus; one Qdrant collection. "Sheet" in the
console.

**nDCG@k** — Ranking metric rewarding relevant items near the top.

**Out-of-scope** — Router class for questions the corpus cannot answer;
refused without retrieval.

**Reranker** — Second-stage model (cross-encoder) that re-scores fused
candidates.

**RRF** — Reciprocal Rank Fusion: `Σ 1/(k + rank)`, k=60. Merges ranked lists
without score calibration.

**Router** — First LLM call: `simple | complex | out_of_scope`.

**Self-RAG** — Model trained to emit reflection tokens deciding when to
retrieve and whether output is supported.

**Sparse retrieval** — Lexical (BM25) or learned-sparse (SPLADE) retrieval on
an inverted index.

**SSE** — Server-Sent Events; Atlas streams pipeline stages over it.

**Stage timings (`stage_ms`)** — Per-stage wall time in every response.

**Strength badge** — Console label from faithfulness: SUPPORTED / PARTIAL /
WEAK / UNCHECKED.

**TF** — Term frequency.

**Top-k** — Candidates kept: 20 per retriever before fusion, 5 after rerank.
