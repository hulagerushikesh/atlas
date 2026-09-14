# 04 — Hybrid Fusion & Reranking

Two retrievers with incompatible scores → one ranked list → a slow, accurate
model picks the winners.

## The scale problem

BM25 gives `11.2`. Cosine gives `0.83`. You cannot add them, average them, or
threshold them together. Anything that tries (min-max normalisation, z-scores)
depends on the score distribution of *that corpus for that query* and breaks
the moment either changes.

## Reciprocal Rank Fusion

Throw the scores away. Keep only the *ranks*.

```
RRF(d) = Σ_{r ∈ retrievers} 1 / (k + rank_r(d))        k = 60
```

A document ranked 1st by BM25 and 3rd by dense gets `1/61 + 1/63`. A document
only BM25 found at rank 2 gets `1/62`. Being near the top of *both* lists
beats being first in one. `k` smooths how much the top rank dominates; 60 is
the value from the original paper and nobody has found a reason to change it.

Properties that matter:
- No training, no tuning, no score calibration.
- Robust to one retriever being bad on a given query.
- Cheap: one pass over ≤ 2·top_k items.

## In Atlas

- `retrieval/fusion.py` — `reciprocal_rank_fusion(results_by_retriever, top_k,
  k=60)`. Read the docstring; it is the explanation above in code.
- `retrieval/hybrid.py` — `HybridRetriever`: runs dense + sparse concurrently
  (`asyncio.gather`), fuses, reranks, and returns a `HybridRetrievalResult`
  with `per_retriever`, `fused`, `reranked` so the console can show
  provenance for every chunk (which stage found it, which stage cut it).
- `config.py` — `RetrievalConfig.top_k = 20` candidates per retriever →
  fusion → `RerankerConfig.top_k = 5` survive.

## Reranking: cross-encoders

A **bi-encoder** embeds query and document separately (fast, approximate).
A **cross-encoder** feeds `[CLS] query [SEP] document [SEP]` through one
transformer and outputs a relevance score. It sees query and document
*together* — it can tell "not authenticated" from "authenticated", can match
a question to an answer that shares no words, can weigh which sentence
actually answers.

It is also ~100× slower per pair, which is why it only runs on the 20–40
fused candidates, never the whole corpus. This two-stage shape (cheap
recall → expensive precision) is the standard pattern across search,
recommendation and ads.

Atlas uses `cross-encoder/ms-marco-MiniLM-L-6-v2` via `sentence-transformers`:
22M params, CPU-friendly, fine-tuned on MS MARCO passage ranking. Bigger
rerankers (`bge-reranker-v2-m3`, Cohere Rerank, `mxbai-rerank`) give a few
points more at several × the latency. `retrieval/reranker.py` loads the model
once and runs `predict` in a thread.

Rejects are kept with `selected=False` — the console shows them as
"cut at rerank" so you can see what almost made it.

## Beyond cross-encoders

- **ColBERT** (late interaction): embed every *token* of query and document,
  score by MaxSim. Bi-encoder speed with most of cross-encoder accuracy;
  needs ~100× the storage. Qdrant supports multi-vectors, so this is
  implementable.
- **LLM rerankers** (RankGPT): ask an LLM to sort passages. Strong, slow,
  expensive; used for building training data more than for serving.
- **Listwise vs pointwise**: Atlas scores each (query, chunk) pair
  independently (pointwise). Listwise models see all candidates at once and
  can de-duplicate.

## Read

1. Cormack, Clarke & Buettcher, *Reciprocal Rank Fusion outperforms
   Condorcet and individual rank learning methods* (SIGIR 2009) — four pages.
2. Nogueira & Cho, *Passage Re-ranking with BERT* (2019), arXiv:1901.04085 —
   the cross-encoder reranker, born.
3. Khattab & Zaharia, *ColBERT* (2020), arXiv:2004.12832 — late interaction;
   figure 1 is the whole idea.
4. Sun et al., *Is ChatGPT Good at Search? (RankGPT)* (2023),
   arXiv:2304.09542 — LLMs as listwise rerankers.
5. `sentence-transformers` docs → "Cross-Encoders" and "Retrieve & Re-Rank".

## Exercise

[exercises.md → 04](exercises.md#04-hybrid-fusion--reranking)
