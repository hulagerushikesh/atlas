# Atlas — Agentic RAG Platform

A production-grade, self-improving retrieval-augmented generation system for
enterprise knowledge bases. Built as a portfolio centerpiece demonstrating
clean architecture, type safety, full observability, and reproducible evaluation.

---

## Architecture

```mermaid
flowchart TD
    subgraph Ingestion["Module A — Ingestion & Indexing"]
        L[Document Loaders\nPDF · MD · HTML · TXT]
        C[Chunkers\nfixed · recursive · semantic]
        E[OpenAI Embedder]
        DI[Dense Index\nQdrant]
        SI[Sparse Index\nBM25]
        L --> C --> E --> DI
        C --> SI
    end

    subgraph Retrieval["Module B — Hybrid Retrieval"]
        DR[Dense Retriever\nQdrant ANN]
        SR[Sparse Retriever\nBM25]
        RRF[Reciprocal Rank Fusion]
        RR[Cross-Encoder Reranker]
        DR --> RRF
        SR --> RRF
        RRF --> RR
    end

    subgraph Orchestration["Module C — Agentic Orchestration"]
        QR[Query Router\nsimple · complex · oos]
        QD[Query Decomposer]
        RG[Retrieval Grader\nre-query if weak]
        GEN[Generator\nanswer + citations]
        FC[Faithfulness Checker]
        QR -->|complex| QD --> RR
        QR -->|simple| RR
        RR --> RG --> GEN --> FC
    end

    subgraph Evaluation["Module D — Eval Harness"]
        M[Metrics\nfaithfulness · relevance\nprecision · recall]
        RUN[Dataset Runner]
        RPT[Report\nJSON + Markdown]
        AB[A/B Comparator]
        RUN --> M --> RPT
        RPT --> AB
    end

    subgraph API["Module E — API & Observability"]
        FA[FastAPI\n/query · /ingest\n/health · /metrics]
        TR[Per-request Tracing]
        CA[Cache\nin-memory + Redis]
        STR[Streaming Response]
    end

    DI --> DR
    SI --> SR
    FC --> FA
    Evaluation -.->|validates| Orchestration
```

## Design Rationale

### Why a single shared `interfaces/` package?
Modules A–D are built independently. Defining shared ABCs and Pydantic models
in one place means no circular imports and each module can be tested in
isolation with a stub that satisfies the same contract.

### Why BM25 + dense (hybrid)?
Dense-only retrieval misses exact-match queries (product codes, proper nouns).
BM25-only misses semantic paraphrases. Reciprocal Rank Fusion combines both
without requiring score normalisation — empirically, RRF consistently
outperforms any single retriever on heterogeneous enterprise corpora.

### Why a two-stage retrieve → rerank pipeline?
ANN search scales to millions of vectors in milliseconds but uses bi-encoder
similarity, which is less accurate than cross-encoder scoring. The cross-
encoder is too slow for full-index search (~200 ms per pair) but fast on a
small candidate pool (20–50 chunks). Two stages gives accuracy close to
exhaustive cross-encoder search at ANN latency.

### Why evaluate first?
The eval harness (Module D) is built alongside the retrieval and orchestration
modules, not after. This means every architectural decision is validated against
real metrics before shipping. The `A/B comparator` provides empirical evidence
for claims like "reranking improved context precision by 18%."

---

## Project Layout

```
atlas/
├── src/atlas/
│   ├── interfaces/       # Shared ABCs and Pydantic models (no logic)
│   │   ├── document.py   # Document, Chunk, ChunkMetadata
│   │   ├── loader.py     # BaseDocumentLoader ABC
│   │   ├── chunker.py    # BaseChunker ABC
│   │   ├── embedder.py   # BaseEmbedder ABC + EmbeddingResult
│   │   ├── index.py      # BaseIndex ABC + IndexStats
│   │   ├── retriever.py  # BaseRetriever + RetrievedChunk + RetrievalResult
│   │   ├── reranker.py   # BaseReranker ABC
│   │   ├── llm.py        # BaseLLMProvider + Message + GenerationRequest/Response
│   │   └── evaluator.py  # EvalSample, EvalDataset, MetricScore, EvalResult
│   ├── config.py         # pydantic-settings config (never hardcoded keys)
│   ├── logging.py        # structlog configuration
│   ├── ingestion/        # Module A
│   ├── retrieval/        # Module B
│   ├── orchestration/    # Module C
│   ├── evaluation/       # Module D
│   └── api/              # Module E
├── tests/
│   ├── conftest.py       # Shared fixtures (Documents, Chunks, etc.)
│   ├── unit/             # Pure unit tests, no I/O
│   └── integration/      # Tests against real Qdrant/Redis (docker-compose up first)
├── eval_data/            # Evaluation datasets (JSON) and reports
├── docs/                 # Per-module design docs
├── docker-compose.yml    # Qdrant + Redis + Atlas API
├── Dockerfile
└── pyproject.toml
```

---

## Quick Start

```bash
# 1. Copy env and fill in your OpenAI key
cp .env.example .env && $EDITOR .env

# 2. Start infrastructure
docker-compose up qdrant redis -d

# 3. Install the package (editable)
uv pip install -e ".[dev]"

# 4. Run tests
pytest

# 5. Start the API
uvicorn atlas.api.app:app --reload
```

### Docker (all-in-one)
```bash
docker-compose up --build
```

---

## Key Dependencies

| Concern | Library |
|---|---|
| Web framework | FastAPI + uvicorn |
| Config | pydantic-settings |
| Vector store | Qdrant |
| Sparse retrieval | rank-bm25 |
| Embeddings | OpenAI text-embedding-3-small |
| Reranking | sentence-transformers cross-encoder |
| Caching | Redis |
| Logging | structlog |
| Metrics | prometheus-client |
| Dependency management | uv |

---

## Modules

| Module | Status | README |
|---|---|---|
| A — Ingestion & Indexing | ✅ | [docs/ingestion.md](docs/ingestion.md) |
| B — Hybrid Retrieval | ✅ | [docs/retrieval.md](docs/retrieval.md) |
| C — Agentic Orchestration | ✅ | [docs/orchestration.md](docs/orchestration.md) |
| D — Evaluation Harness | ✅ | [docs/evaluation.md](docs/evaluation.md) |
| E — API & Observability | ✅ | [docs/api.md](docs/api.md) |
| Shared Interfaces | ✅ | This file |
