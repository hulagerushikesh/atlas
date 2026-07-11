#!/usr/bin/env python3
"""
seed_demo.py — generate sample documents and run end-to-end demo queries.

This script:
  1. Writes a small set of synthetic enterprise documents to a temp directory.
  2. Indexes them into Qdrant + BM25 via DocumentIndexer.
  3. Runs a handful of demo queries through the full RAG pipeline and prints
     answers with citations, faithfulness scores, and latency.

Purpose: verify the end-to-end stack works (infra up, keys valid, pipeline runs)
without needing real proprietary documents.

Usage:
    python scripts/seed_demo.py
    python scripts/seed_demo.py --queries-only   # skip ingest, just run queries
    python scripts/seed_demo.py --keep-docs      # don't delete temp docs after
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, "src")

# ---------------------------------------------------------------------------
# Synthetic enterprise documents — representative of real KB content
# ---------------------------------------------------------------------------

SAMPLE_DOCS: dict[str, str] = {
    "hr_leave_policy.md": dedent("""\
        # Leave Policy

        ## Annual Leave
        Full-time employees are entitled to 20 days of annual leave per year.
        After 5 years of service this increases to 25 days. Leave must be
        approved by your line manager at least 2 weeks in advance via the HR
        portal.

        ## Parental Leave
        Primary carers receive 16 weeks of fully paid parental leave.
        Secondary carers receive 4 weeks. Leave requests must be submitted to
        HR at least 8 weeks before the expected start date with supporting
        documentation provided within 4 weeks of the child's arrival.

        ## Sick Leave
        Employees are entitled to 10 days of paid sick leave per year.
        A medical certificate is required for absences of 3 or more consecutive
        days. Sick leave does not carry over to the following year.
    """),

    "it_security_policy.md": dedent("""\
        # IT Security Policy

        ## Password Requirements
        All corporate accounts must use passwords of at least 14 characters
        containing uppercase letters, lowercase letters, numbers, and symbols.
        Passwords must be rotated every 90 days. Password reuse within the
        last 12 cycles is prohibited.

        ## Multi-Factor Authentication
        MFA is mandatory for all corporate systems. Employees must enrol an
        authenticator app (Google Authenticator or Microsoft Authenticator)
        within 48 hours of account creation. SMS-based MFA is not permitted
        for systems handling financial or personal data.

        ## Acceptable Use
        Corporate devices may not be used for personal cryptocurrency mining,
        illegal downloads, or accessing material that violates the company's
        code of conduct. Violations are subject to disciplinary action up to
        and including termination.
    """),

    "finance_expense_policy.md": dedent("""\
        # Expense Reimbursement Policy

        ## Submission Deadline
        All expenses must be submitted within 30 days of being incurred.
        Expenses older than 30 days will not be reimbursed unless accompanied
        by a written exception approved by Finance.

        ## Meal Limits
        Business meals are reimbursable up to $75 per person per meal.
        Alcohol is reimbursable up to $25 per person when accompanying a
        business meal. Standalone alcohol purchases are not reimbursable.

        ## Travel
        Economy class is required for flights under 6 hours. Business class
        may be approved for flights over 6 hours with VP-level sign-off.
        Hotel accommodation must not exceed $250 per night without Finance
        approval. All travel must be booked through the corporate travel portal.

        ## Software & Subscriptions
        Software purchases under $500 per year can be approved by your
        direct manager. Purchases between $500 and $5000 require Finance
        approval. Purchases over $5000 require VP and Finance approval.
    """),

    "product_atlas_overview.md": dedent("""\
        # Atlas — Product Overview

        Atlas is a production-grade agentic RAG (Retrieval-Augmented Generation)
        platform designed for enterprise knowledge bases.

        ## Core Capabilities
        - Hybrid retrieval: dense vector search (Qdrant) combined with BM25
          sparse retrieval, fused via Reciprocal Rank Fusion.
        - Agentic orchestration: query routing, automatic decomposition of
          complex multi-hop questions, retrieval grading with re-query retry,
          and faithfulness checking.
        - Evaluation harness: four built-in metrics (context precision, context
          recall, faithfulness, answer relevance) with A/B comparison support.
        - Observability: per-request tracing, Prometheus metrics, structured
          JSON logging via structlog.

        ## Supported Document Types
        Atlas can index PDF, Markdown, plain text, and HTML documents.
        Three chunking strategies are available: fixed-size, recursive
        (hierarchy-aware), and semantic (embedding-based boundary detection).

        ## Architecture
        The system is organised into five modules: ingestion (A), retrieval (B),
        orchestration (C), evaluation (D), and API (E). All modules share a
        common interfaces package with abstract base classes and Pydantic models
        to enable independent development and testing.
    """),
}

DEMO_QUERIES = [
    "How many days of annual leave do employees get?",
    "What are the password requirements for corporate accounts?",
    "What is the meal reimbursement limit per person?",
    "What retrieval strategy does Atlas use and why?",
    "Can I fly business class on a 4-hour flight?",
]


def _write_docs(directory: Path) -> None:
    for filename, content in SAMPLE_DOCS.items():
        (directory / filename).write_text(content, encoding="utf-8")
    print(f"Wrote {len(SAMPLE_DOCS)} documents to {directory}")


def _build_components(settings):
    from atlas.ingestion.chunkers import get_chunker
    from atlas.ingestion.dense import QdrantDenseIndex
    from atlas.ingestion.embedder import OpenAIEmbedder
    from atlas.ingestion.indexer import DocumentIndexer
    from atlas.ingestion.sparse import BM25SparseIndex
    from atlas.orchestration.decomposer import QueryDecomposer
    from atlas.orchestration.faithfulness import FaithfulnessChecker
    from atlas.orchestration.generator import AnswerGenerator
    from atlas.orchestration.grader import RetrievalGrader
    from atlas.orchestration.llm import OpenAILLMProvider
    from atlas.orchestration.pipeline import RAGPipeline
    from atlas.orchestration.router import QueryRouter
    from atlas.retrieval.dense import QdrantDenseRetriever
    from atlas.retrieval.hybrid import HybridRetriever
    from atlas.retrieval.reranker import CrossEncoderReranker
    from atlas.retrieval.sparse import BM25Retriever

    embedder = OpenAIEmbedder(settings.openai)
    llm = OpenAILLMProvider(settings.openai)
    sparse_index = BM25SparseIndex()

    hybrid = HybridRetriever(
        retrievers=[
            QdrantDenseRetriever(settings.qdrant, embedder),
            BM25Retriever(sparse_index),
        ],
        config=settings.retrieval,
        reranker=CrossEncoderReranker(settings.reranker),
        reranker_top_k=settings.reranker.top_k,
    )

    pipeline = RAGPipeline(
        retriever=hybrid,
        router=QueryRouter(llm),
        decomposer=QueryDecomposer(llm),
        grader=RetrievalGrader(llm),
        generator=AnswerGenerator(llm),
        faithfulness=FaithfulnessChecker(llm),
    )

    indexer = DocumentIndexer(
        chunker=get_chunker(settings, embedder=embedder),
        embedder=embedder,
        dense_index=QdrantDenseIndex(settings.qdrant, embedder.dimensions),
        sparse_index=sparse_index,
    )

    return pipeline, indexer


async def run_ingest(indexer, doc_dir: Path) -> None:
    print("\nIndexing documents…")
    result = await indexer.index_path(doc_dir)
    print(f"  Documents processed : {result.documents_processed}")
    print(f"  Chunks indexed      : {result.chunks_indexed}")
    print(f"  Total tokens        : {result.total_tokens:,}")


async def run_queries(pipeline, queries: list[str]) -> None:
    print("\nRunning demo queries")
    print("═" * 60)

    for i, query in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] {query}")
        print("─" * 60)

        t0 = time.perf_counter()
        result = await pipeline.run(query)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        print(f"Answer     : {result.answer}")

        if result.generation and result.generation.citations:
            sources = sorted(
                {ref.source for ref in result.generation.citations.values()}
            )
            print(f"Sources    : {', '.join(sources)}")

        faithful_str = "✓" if result.is_faithful else "✗ (unfaithful)"
        faith_score = (
            f"{result.faithfulness.score:.2f}" if result.faithfulness else "n/a"
        )
        print(f"Faithful   : {faithful_str}  score={faith_score}")
        print(f"Route      : {result.classification}")
        print(f"Chunks     : {len(result.retrieved_chunks)}")
        print(f"Latency    : {elapsed_ms:.0f}ms")


async def main(args: argparse.Namespace) -> int:
    from atlas.config import get_settings
    from atlas.logging import configure_logging

    configure_logging(level="WARNING", json=False)
    settings = get_settings()

    print("Atlas end-to-end demo")
    print("=" * 60)

    pipeline, indexer = _build_components(settings)

    if not args.queries_only:
        if args.keep_docs:
            doc_dir = Path("eval_data/demo_docs")
            doc_dir.mkdir(parents=True, exist_ok=True)
            _write_docs(doc_dir)
            await run_ingest(indexer, doc_dir)
        else:
            with tempfile.TemporaryDirectory(prefix="atlas_demo_") as tmpdir:
                doc_dir = Path(tmpdir)
                _write_docs(doc_dir)
                await run_ingest(indexer, doc_dir)

    await run_queries(pipeline, DEMO_QUERIES)
    print("\n" + "=" * 60)
    print("Demo complete.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Atlas with demo docs and run example queries.")
    parser.add_argument(
        "--queries-only",
        action="store_true",
        help="Skip ingestion — run demo queries against the existing index.",
    )
    parser.add_argument(
        "--keep-docs",
        action="store_true",
        help="Write demo docs to eval_data/demo_docs/ instead of a temp dir.",
    )
    sys.exit(asyncio.run(main(parser.parse_args())))
