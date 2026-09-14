# Atlas — Learning Path

Everything you need to understand *why* Atlas is built the way it is, from the
ground up to the research frontier. Each module says what to learn, how it
shows up in the Atlas code, what to try, and what to read next.

The path is ordered. Modules 01–05 are "how retrieval works", 06–08 are "how
Atlas turns retrieval into an agent and a product", 09 is where the field is
going. Skim 01 if you already know async Python and FastAPI.

| # | Module | Level | Atlas code it explains |
|---|---|---|---|
| 01 | [Foundations](01-foundations.md) | basics | `api/`, `config.py`, `interfaces/` |
| 02 | [Embeddings & vector search](02-embeddings-and-vector-search.md) | basics → intermediate | `ingestion/embedder.py`, `ingestion/dense.py`, `retrieval/dense.py` |
| 03 | [Lexical search & BM25](03-lexical-search-bm25.md) | intermediate | `ingestion/sparse.py`, `retrieval/sparse.py` |
| 04 | [Hybrid fusion & reranking](04-hybrid-and-rerank.md) | intermediate | `retrieval/fusion.py`, `retrieval/hybrid.py`, `retrieval/reranker.py` |
| 05 | [Chunking & ingestion](05-chunking-and-ingestion.md) | intermediate | `ingestion/chunkers/`, `ingestion/indexer.py`, `ingestion/hashing.py` |
| 06 | [Agentic RAG](06-agentic-rag.md) | intermediate → research | `orchestration/` |
| 07 | [Faithfulness & evaluation](07-faithfulness-and-eval.md) | intermediate → research | `orchestration/faithfulness.py`, `evaluation/` |
| 08 | [Production & serving](08-production-and-serving.md) | intermediate | `api/cache.py`, `api/auth.py`, `api/middleware/`, `api/cost.py` |
| 09 | [Research frontier](09-research-frontier.md) | research | what Atlas could become |
| — | [Exercises](exercises.md) | all | hands-on tasks against the real code |
| — | [Glossary](glossary.md) | all | terms used across the modules |

## How to use this

1. Read the module. Every one is short on purpose — the depth is in the
   linked papers and in the Atlas code itself.
2. Open the Atlas files named in the module and read them with the concept
   in mind. The docstrings were written to be read this way.
3. Do the exercise for that module in [exercises.md](exercises.md). Most run
   in a REPL against the local test doubles, no API key needed.
4. Read one paper from the module's list. Read the abstract, the figure
   that explains the method, the main results table, and the limitations.
   That is 80% of the value in 20% of the time.

## Prerequisites

- Python 3.11 — comfortable with classes, type hints, generators.
- Basic linear algebra — vectors, dot product, what a norm is.
- Basic probability — what a conditional probability is.
- Have run `make install && make test` once so the code is on disk and green.

Project-level reference docs live in [`../docs/`](../docs/) — those describe
*what Atlas does*; this folder explains *why it works*.
