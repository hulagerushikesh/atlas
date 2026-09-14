# 03 — Lexical Search & BM25

Sparse retrieval: match the words the user typed. Forty years old and still
half of every serious retrieval stack.

## From TF-IDF to BM25

**TF** (term frequency): a document that mentions `Depends` five times is
probably more about `Depends` than one that mentions it once.

**IDF** (inverse document frequency): `the` appears everywhere, so matching it
means nothing; `lifespan` appears in a handful of docs, so matching it means a
lot. `idf(t) = log((N − n_t + 0.5) / (n_t + 0.5) + 1)`.

**BM25** fixes two things TF-IDF gets wrong:

1. *Saturation.* The fifth mention of a word should matter less than the
   second. BM25 uses `tf·(k₁+1) / (tf + k₁)` — it asymptotes instead of
   growing linearly. `k₁ ≈ 1.2–2.0`.
2. *Length normalisation.* Long documents mention everything more often. BM25
   scales `tf` by document length relative to the average, controlled by
   `b ∈ [0,1]` (`b = 0.75` is standard).

```
score(q, d) = Σ_{t∈q} idf(t) · tf(t,d)·(k₁+1) / (tf(t,d) + k₁·(1 − b + b·|d|/avgdl))
```

That is the whole algorithm. Scores are unbounded and corpus-relative — a
score of 11.2 in one corpus means nothing in another. Remember this for
module 04.

## In Atlas

- `ingestion/sparse.py` — `BM25SparseIndex`: wraps `rank-bm25`, tokenises with a
  simple lowercase + split, persists the corpus to `bm25_index.json` so the
  index survives restarts. `sources()` groups the corpus by document for the
  console's Corpus pane.
- `retrieval/sparse.py` — `BM25SparseRetriever`: scores every chunk against the
  query, returns the top `top_k`. It is O(N) per query — fine for thousands
  of chunks, and one of the first things to replace at scale (see below).
- Known bug (planning/BACKLOG.md): every namespace currently shares the same
  default `bm25_index.json` path.

## Tokenisation matters more than the formula

`item_id` vs `item id` vs `itemId`. `HTTPException` vs `http exception`.
Whether you stem (`validating` → `valid`) or not. Whether you keep
punctuation in code identifiers. Atlas's tokeniser is deliberately simple;
improving it is a cheap, measurable win — the eval harness (module 07) is how
you would measure it.

## Why keep BM25 when you have embeddings

- Exact matches: identifiers, error strings, product codes, names.
- Zero training, zero API cost, explainable ("matched `lifespan` and
  `startup`").
- Complementary failure modes. The DPR paper itself found that BM25 and dense
  retrievers get *different* questions right, which is the entire argument for
  hybrid.

## Learned sparse: the modern middle

**SPLADE** trains a transformer to output a sparse vector over the
vocabulary — like BM25 but with learned term weights and *expansion* (the
document about "cars" also gets weight on "vehicle"). Runs on an inverted
index like BM25, competitive with dense on BEIR. Qdrant supports sparse
vectors natively, so Atlas could swap `rank-bm25` for SPLADE weights in Qdrant
and drop the O(N) Python scoring loop.

## Scaling the sparse side

`rank-bm25` is a teaching library. Production options: Qdrant sparse vectors,
Elasticsearch/OpenSearch, Tantivy (Rust, Python bindings), Pyserini/Lucene.
The interface in `interfaces/retriever.py` does not care which.

## Read

1. Robertson & Zaragoza, *The Probabilistic Relevance Framework: BM25 and
   Beyond* (2009) — the definitive write-up; §3 for the formula's derivation.
2. Formal et al., *SPLADE* (2021), arXiv:2107.05663 — learned sparse
   retrieval; read the intro and the expansion examples.
3. Thakur et al., *BEIR* (2021), arXiv:2104.08663 — the zero-shot benchmark
   where BM25 turned out embarrassingly hard to beat. Read the results table.
4. `rank-bm25` source — it is ~200 lines; read `BM25Okapi.get_scores`.

## Exercise

[exercises.md → 03](exercises.md#03-lexical-search--bm25)
