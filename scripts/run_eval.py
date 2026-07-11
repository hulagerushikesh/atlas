#!/usr/bin/env python3
"""
run_eval.py — run the Atlas evaluation harness against a dataset.

Loads an EvalDataset from a JSON file, runs every sample through the live
RAG pipeline (requires Qdrant + Redis + OpenAI), scores on all four metrics,
saves a JSON + Markdown report to eval_data/reports/, and prints a summary table.

Usage:
    python scripts/run_eval.py
    python scripts/run_eval.py --dataset eval_data/sample_dataset.json
    python scripts/run_eval.py --run-name my_experiment --concurrency 2
    python scripts/run_eval.py --compare eval_data/reports/baseline.json

Exit code 0 = run completed (even if scores are low).
Exit code 1 = setup error (missing file, infra unreachable).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

DEFAULT_DATASET = Path("eval_data/sample_dataset.json")
REPORTS_DIR = Path("eval_data/reports")


def _build_pipeline(settings):
    from atlas.ingestion.chunkers import get_chunker
    from atlas.ingestion.dense import QdrantDenseIndex
    from atlas.ingestion.embedder import OpenAIEmbedder
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

    return RAGPipeline(
        retriever=hybrid,
        router=QueryRouter(llm),
        decomposer=QueryDecomposer(llm),
        grader=RetrievalGrader(llm),
        generator=AnswerGenerator(llm),
        faithfulness=FaithfulnessChecker(llm),
    )


def _build_metrics(settings):
    from atlas.evaluation.metrics.answer_relevance import AnswerRelevanceMetric
    from atlas.evaluation.metrics.context_precision import ContextPrecisionMetric
    from atlas.evaluation.metrics.context_recall import ContextRecallMetric
    from atlas.evaluation.metrics.faithfulness import FaithfulnessMetric
    from atlas.orchestration.llm import OpenAILLMProvider
    from atlas.ingestion.embedder import OpenAIEmbedder

    llm = OpenAILLMProvider(settings.openai)
    embedder = OpenAIEmbedder(settings.openai)

    return [
        ContextPrecisionMetric(),
        ContextRecallMetric(),
        FaithfulnessMetric(llm),
        AnswerRelevanceMetric(llm, embedder),
    ]


async def main(args: argparse.Namespace) -> int:
    from atlas.config import get_settings
    from atlas.evaluation.comparator import compare
    from atlas.evaluation.reporter import print_report, save_report
    from atlas.evaluation.runner import EvalRunner
    from atlas.interfaces.evaluator import EvalDataset
    from atlas.logging import configure_logging

    configure_logging(level="WARNING", json=False)
    settings = get_settings()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Error: dataset not found: {dataset_path}", file=sys.stderr)
        return 1

    print(f"Atlas evaluation harness")
    print(f"Dataset     : {dataset_path}")
    print(f"Run name    : {args.run_name}")
    print(f"Concurrency : {args.concurrency}")
    print("─" * 55)

    with open(dataset_path) as f:
        raw = json.load(f)
    dataset = EvalDataset.model_validate(raw)
    print(f"Samples     : {len(dataset.samples)}")

    pipeline = _build_pipeline(settings)
    metrics = _build_metrics(settings)

    runner = EvalRunner(pipeline=pipeline, metrics=metrics, concurrency=args.concurrency)

    print(f"\nRunning {len(dataset.samples)} samples…")
    result = await runner.run(dataset, run_name=args.run_name)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = save_report(result, output_dir=REPORTS_DIR, run_name=args.run_name)

    print()
    print_report(result)
    print(f"\nReport saved:")
    for p in paths:
        print(f"  {p}")

    # Optional A/B comparison against a baseline run
    if args.compare:
        baseline_path = Path(args.compare)
        if not baseline_path.exists():
            print(f"\nWarning: baseline report not found: {baseline_path}", file=sys.stderr)
        else:
            from atlas.interfaces.evaluator import EvalResult
            with open(baseline_path) as f:
                baseline_raw = json.load(f)
            baseline = EvalResult.model_validate(baseline_raw)
            comparison = compare(baseline, result)
            print("\nA/B comparison (baseline → this run):")
            print(comparison.as_markdown())

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Atlas evaluation harness.")
    parser.add_argument(
        "--dataset",
        default=str(DEFAULT_DATASET),
        help=f"Path to EvalDataset JSON (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--run-name",
        default="eval",
        help="Name for this run (used in report filenames and the run ID).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max concurrent pipeline calls (default: 4).",
    )
    parser.add_argument(
        "--compare",
        metavar="BASELINE_JSON",
        help="Path to a previous run's JSON report for A/B comparison.",
    )
    sys.exit(asyncio.run(main(parser.parse_args())))
