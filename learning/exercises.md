# Exercises

Hands-on, against the real code. Most need no API key — they use the test
doubles or local Qdrant mode. Where a key is needed it says so. Do them in
order with the matching module; each should take 30–90 minutes.

Setup once:

```bash
make install && make test
```

Work in `.venv/bin/python` or `.venv/bin/ipython`.

---

## 01 — Foundations

1. **Concurrency you can feel.** In a REPL, `await asyncio.gather(sleep(1),
   sleep(1))` and time it. Then read `retrieval/hybrid.py` and find the
   `gather` that runs dense and sparse together. What would the latency be
   if they ran sequentially? Check against the `retrieve` figure in
   `docs/orchestration.md`.
2. **Config surface.** Print `Settings().model_dump()` (set a dummy
   `OPENAI_API_KEY` env var). Change `ATLAS_RETRIEVAL__TOP_K` via env and
   confirm it lands. Now you know every knob.
3. **Follow one request.** Start with `api/routes/query.py: query`, and write
   down every function it calls until you reach an OpenAI or Qdrant call.
   Ten lines of notes. This is the map for everything below.

## 02 — Embeddings & vector search

1. **Cosine by hand.** Two 3-d vectors, compute cosine with numpy, then
   normalise both and take the dot product. Same number.
2. **Real Qdrant, no key.** Read `tests/integration/test_qdrant_roundtrip.py`.
   Copy its setup into a script: `AsyncQdrantClient(":memory:")`, the
   `StubEmbedder`, three chunks. Query for each chunk's own text; confirm it
   ranks first with score ≈ 1.0. Query for nonsense; look at the scores.
3. **Failure mode.** With a real key (`OpenAIEmbedder`), embed
   "endpoint requires authentication" and "endpoint does not require
   authentication". Cosine them. Now you know why the reranker exists.
4. **(Stretch)** Swap in a local embedder: subclass `BaseEmbedder` around
   `sentence-transformers` `all-MiniLM-L6-v2` (384-d). Set
   `embedding_dimensions=384`. Run the roundtrip test against it.

## 03 — Lexical search & BM25

1. **BM25 by hand.** Three toy "documents", one query term. Compute IDF and
   the BM25 score with `k1=1.5, b=0.75` on paper. Check against
   `rank_bm25.BM25Okapi([...]).get_scores([...])`.
2. **Tokeniser audit.** Read `ingestion/sparse.py: _tokenize`. Feed it
   `"HTTPException(status_code=404)"`, `"item_id: int"`, `"FastAPI's"`. Which
   of these would a user's query actually match? Propose a better tokeniser
   in five lines (keep identifiers whole, split camelCase, lowercase).
3. **Saturation.** One document repeats a term 1, 2, 5, 50 times. Plot
   `get_scores` vs count. Where does it flatten? Change `k1` and re-plot.

## 04 — Hybrid fusion & reranking

1. **RRF by hand.** Two ranked lists of five chunk ids with two overlaps.
   Compute RRF with k=60 on paper. Then build two `RetrievalResult`s and call
   `reciprocal_rank_fusion(results, top_k=5)`. Match.
2. **Why k=60?** Re-run with `k=1` and `k=1000`. Describe in one sentence what
   each does to the influence of rank 1 vs rank 5.
3. **Cross-encoder, no key.** `CrossEncoderReranker(RerankerConfig())` loads
   MiniLM locally (~90 MB download, once). Score
   `("does the endpoint require auth?", "This endpoint requires no
   authentication.")` vs `(..., "This endpoint requires authentication.")`.
   Compare with cosine from exercise 02.3.
4. **Provenance.** Read `HybridRetrievalResult` in `retrieval/hybrid.py` and
   `_collect_evidence` in `orchestration/pipeline.py`. For a chunk that BM25
   found at rank 2, dense missed, RRF placed 4th, rerank cut: write out the
   exact `EvidenceChunk.scores` dict it would carry. Then find it in the
   console's Evidence pane rendering (`console/src/components/EvidencePane.tsx`).

## 05 — Chunking & ingestion

1. **Three chunkers, one doc.** Take `data/corpus/fastapi/` (run
   `make fetch-corpus` if empty) and chunk one markdown file with `fixed`,
   `recursive` and (with a key) `semantic`. Print chunk count and the first
   80 chars of each chunk. Which one cuts mid-sentence?
2. **Overlap.** Set `overlap=0` and find a sentence that got split across a
   boundary. Set it back to 64 and confirm it appears whole somewhere.
3. **Idempotency.** `make ingest-dry` twice; read `ingestion/hashing.py` and
   `indexer.py` and explain what makes the second real run cheap.
4. **(Stretch, key)** Implement contextual retrieval: before embedding,
   prepend an LLM-written one-sentence context to each chunk (keep the
   original text for citation offsets). Ingest into a new namespace. Compare
   `make eval-compare`.

## 06 — Agentic RAG

1. **Read the pipeline.** `orchestration/pipeline.py: run` top to bottom with
   `docs/orchestration.md`'s decision tree beside it. Mark every LLM call.
   Count them for a `simple` question and a `complex` one that needs one
   grader retry.
2. **Router at the edge.** Read `router.py`'s prompt. Write five questions
   that you think will misroute (a FastAPI question phrased casually; a
   non-FastAPI Python question; a question about FastAPI's history). With a
   key, run them through `QueryRouter` and see.
3. **Grader loop, no key.** `tests/integration/test_pipeline_integration.py`
   stubs the LLM. Write a test where the grader returns 0.3, 0.3, then 0.8
   and assert `retries == 2` and `stage_ms["grading"]` accumulated three
   timings.
4. **HyDE in one file.** Add a `HyDERetriever` wrapper: LLM writes a
   hypothetical answer, embed it, dense-retrieve with that vector, keep BM25
   on the original query. Gate it behind a config flag. `make eval-compare`.

## 07 — Faithfulness & evaluation

1. **Claims.** Take an Atlas answer (from the landing hero or a mock run)
   and decompose it into atomic claims by hand. Compare with what
   `faithfulness.py`'s prompt asks for.
2. **Noise floor (key).** Run `make eval` twice with the same config. Diff
   the reports. That spread is the smallest change you can trust.
3. **Dataset.** Add five questions to `eval_data/fastapi_dataset.json`: one
   multi-hop, one phrased nothing like the docs, one unanswerable, two easy.
   Label `relevant_doc_ids` honestly. Run eval; look at the per-sample rows.
4. **Judge bias.** Give the faithfulness judge a fluent, confident, wrong
   answer and a terse, correct one. Does it score them right? If not, tighten
   the rubric in the prompt.

## 08 — Production & serving

1. **Cache key.** Read `api/cache.py`. What is in the key? Change
   `top_k` in config — does the cache correctly miss? Should ingest
   invalidate? Does it?
2. **Rate limit.** With `auth_enabled=True`, create a key with `RPM=3`, hit
   `/query` four times in a minute, see the 429. Kill Redis, repeat; confirm
   the in-memory fallback still limits.
3. **Stream it.** `curl -N` the streaming endpoint and watch the events
   arrive. Match each to a stage in `console/src/lib/store.ts: STAGES`.
4. **Fix the tenancy bug.** `BM25SparseIndex()` shares `bm25_index.json`
   across namespaces (`api/namespaces.py`). Give each namespace its own
   path, add a test proving two namespaces don't see each other's chunks.
   This one is real — see `planning/BACKLOG.md`.

## 09 — Research

Pick one paper from module 09's canon. Write a half-page: the idea, the
figure, the baseline it beats and by how much, the Atlas file it would
change, and the `make eval-compare` result you would expect. Put it in
`planning/DECISIONS.md` if you decide to build it.
