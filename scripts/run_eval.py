#!/usr/bin/env python3
"""
run_eval.py — run the Atlas evaluation harness against a dataset.

Loads an EvalDataset from a JSON file, runs every sample through the live
RAG pipeline (requires Qdrant + Redis + OpenAI), scores on all four metrics,
saves a JSON + Markdown report to eval_data/reports/, and prints a summary table.

--dataset is required and deliberately has no default. It used to default
to the 30-question HR set, so a bare run in this repo scored those questions
against the FastAPI index and printed a full report of zeros, then a confident
`Overall winner` against a 15-sample FastAPI baseline. Nothing in the output
looked broken; only the token count did. No default is correct here, because
which dataset is right depends on what was ingested into the namespace — so
the script asks, and then checks the answer against the namespace's index.

Usage:
    python scripts/run_eval.py --dataset eval_data/fastapi_dataset.json
    python scripts/run_eval.py --dataset eval_data/sample_dataset.json
    python scripts/run_eval.py --run-name my_experiment --concurrency 2
    python scripts/run_eval.py --compare eval_data/reports/baseline.json
    python scripts/run_eval.py --set reranker.enabled=false --run-name no-rerank
    python scripts/run_eval.py --set reranker.top_k=10 --set retrieval.top_k=30
    python scripts/run_eval.py --set hyde.enabled=true --run-name hyde
    python scripts/run_eval.py --set hyde.enabled=true --set hyde.mode=replace

Exit code 0 = run completed (even if scores are low).
Exit code 1 = setup error (missing file, infra unreachable).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

REPORTS_DIR = Path("eval_data/reports")


def _print_available_datasets() -> None:
    """Naming the alternatives is the point: the fault this replaces was
    someone getting the wrong one without ever choosing."""
    found = sorted(Path("eval_data").glob("*.json"))
    if not found:
        print("No datasets found under eval_data/.", file=sys.stderr)
        return
    print("\nAvailable datasets:", file=sys.stderr)
    for path in found:
        print(f"  --dataset {path}", file=sys.stderr)


def _dataset_corpus_root(dataset) -> Path | None:
    """The root the dataset writes its labels relative to, if it says."""
    return Path(dataset.corpus_root) if dataset.corpus_root else None


def _build_pipeline(settings, namespace: str = "default"):
    from atlas.api.namespaces import namespace_to_collection, sparse_index_path
    from atlas.ingestion.embedder import OpenAIEmbedder
    from atlas.ingestion.sparse import BM25SparseIndex
    from atlas.orchestration.decomposer import QueryDecomposer
    from atlas.orchestration.faithfulness import FaithfulnessChecker
    from atlas.orchestration.generator import AnswerGenerator
    from atlas.orchestration.grader import RetrievalGrader
    from atlas.orchestration.hyde import HyDEExpander
    from atlas.orchestration.llm import OpenAILLMProvider
    from atlas.orchestration.pipeline import RAGPipeline
    from atlas.orchestration.router import QueryRouter
    from atlas.retrieval.dense import QdrantDenseRetriever
    from atlas.retrieval.hybrid import HybridRetriever
    from atlas.retrieval.reranker import CrossEncoderReranker
    from atlas.retrieval.sparse import BM25Retriever

    settings = settings.model_copy(
        update={"qdrant": settings.qdrant.model_copy(
            update={"collection_name": namespace_to_collection(namespace)})}
    )
    embedder = OpenAIEmbedder(settings.openai)
    llm = OpenAILLMProvider(settings.openai)
    sparse_index = BM25SparseIndex(persist_path=sparse_index_path(namespace))

    # One instance, shared: the pipeline re-ranks a retried union with the same
    # model the retriever used, and loading it twice would cost a second copy
    # of the weights for nothing.
    reranker = CrossEncoderReranker(settings.reranker) if settings.reranker.enabled else None
    hybrid = HybridRetriever(
        retrievers=[
            QdrantDenseRetriever(settings.qdrant, embedder),
            BM25Retriever(sparse_index),
        ],
        config=settings.retrieval,
        reranker=reranker,
        reranker_top_k=settings.reranker.top_k,
    )

    return RAGPipeline(
        retriever=hybrid,
        router=QueryRouter(llm, settings.router),
        decomposer=QueryDecomposer(llm),
        grader=RetrievalGrader(llm, settings.grader),
        generator=AnswerGenerator(llm),
        faithfulness=FaithfulnessChecker(llm),
        reranker=reranker,
        hyde=HyDEExpander(llm, settings.hyde) if settings.hyde.enabled else None,
    )


def _build_metrics(settings):
    from atlas.evaluation.metrics.answer_correctness import AnswerCorrectnessMetric
    from atlas.evaluation.metrics.answer_relevance import AnswerRelevanceMetric
    from atlas.evaluation.metrics.context_precision import ContextPrecisionMetric
    from atlas.evaluation.metrics.context_recall import ContextRecallMetric
    from atlas.evaluation.metrics.faithfulness import FaithfulnessMetric
    from atlas.ingestion.embedder import OpenAIEmbedder
    from atlas.orchestration.llm import OpenAILLMProvider

    llm = OpenAILLMProvider(settings.openai)
    embedder = OpenAIEmbedder(settings.openai)

    # Cheap and deterministic first, judged last. AnswerCorrectnessMetric is
    # the only one that reads the reference answer; a run carrying it is not
    # comparable with one graded against different reference answers, which
    # the comparator checks on `answers_fingerprint`.
    return [
        ContextPrecisionMetric(),
        ContextRecallMetric(),
        FaithfulnessMetric(llm),
        AnswerRelevanceMetric(llm, embedder),
        AnswerCorrectnessMetric(llm),
    ]


async def main(args: argparse.Namespace) -> int:
    from atlas.api.namespaces import sparse_index_path
    from atlas.config import get_settings
    from atlas.evaluation.comparator import DatasetMismatch, compare
    from atlas.evaluation.dataset import (
        DatasetError,
        check_dataset_is_ingested,
        indexed_doc_keys,
        load_dataset,
    )
    from atlas.evaluation.reporter import print_report, save_report
    from atlas.evaluation.runner import EvalRunner
    from atlas.logging import configure_logging

    configure_logging(level="WARNING", json=False)
    settings = get_settings()

    from atlas.evaluation.overrides import apply_overrides, parse_override

    overrides = dict(parse_override(spec) for spec in args.set)
    try:
        settings = apply_overrides(settings, overrides)
    except ValueError as exc:
        print(f"Error: bad --set: {exc}", file=sys.stderr)
        return 1

    if not args.dataset:
        print("Error: --dataset is required.", file=sys.stderr)
        _print_available_datasets()
        return 1

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Error: dataset not found: {dataset_path}", file=sys.stderr)
        _print_available_datasets()
        return 1

    print("Atlas evaluation harness")
    print(f"Dataset     : {dataset_path}")
    print(f"Run name    : {args.run_name}")
    print(f"Concurrency : {args.concurrency}")
    if overrides:
        print(f"Overrides   : {overrides}")
    print("─" * 55)

    # Before anything is spent: a label that resolves to nothing, or an empty
    # label set nobody declared, scores a row as a miss and looks exactly like
    # one. Both are free to catch and cost an eval run to notice.
    try:
        dataset, notes = load_dataset(
            dataset_path,
            Path(args.corpus) if args.corpus else None,
            strict=not args.allow_broken_dataset,
        )
    except DatasetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("\nRe-run with --allow-broken-dataset to measure anyway.", file=sys.stderr)
        return 1
    # The dataset can be internally perfect and still be pointed at a
    # namespace holding a different corpus, which is the shape the old
    # default produced. The namespace's own BM25 file names every document
    # it holds, so this is answerable here, locally, before anything is spent.
    mismatch = check_dataset_is_ingested(
        dataset,
        indexed_doc_keys(
            sparse_index_path(args.namespace),
            Path(args.corpus) if args.corpus else _dataset_corpus_root(dataset),
        ),
        f"namespace '{args.namespace}'",
    )
    if mismatch and not args.allow_broken_dataset:
        for problem in mismatch:
            print(f"Error: {problem}", file=sys.stderr)
        print(
            "\nCheck --dataset and --namespace agree, or ingest the corpus:\n"
            "  .venv/bin/python scripts/verify_index.py "
            f"--namespace {args.namespace}\n"
            "Re-run with --allow-broken-dataset to measure anyway.",
            file=sys.stderr,
        )
        return 1
    notes.extend(mismatch)

    for note in notes:
        print(f"Warning     : {note}")
    print(f"Samples     : {len(dataset.samples)}")

    pipeline = _build_pipeline(settings, args.namespace)
    metrics = _build_metrics(settings)

    runner = EvalRunner(pipeline=pipeline, metrics=metrics, concurrency=args.concurrency)

    from atlas.interfaces.evaluator import PipelineConfig

    o = settings.openai
    config = PipelineConfig(
        name=args.run_name,
        description=(
            f"chat={o.primary_model} embed={o.embedding_model}@{o.embedding_dimensions} "
            f"retrieval.top_k={settings.retrieval.top_k} "
            f"reranker={'on' if settings.reranker.enabled else 'off'}"
            f"/top_k={settings.reranker.top_k} "
            f"chunk={settings.chunking.strategy}/{settings.chunking.size}"
            f"/{settings.chunking.overlap} "
            f"namespace={args.namespace}"
        ),
        overrides=overrides,
    )

    print(f"\nRunning {len(dataset.samples)} samples…")
    result = await runner.run(dataset, config)

    # Timestamped so repeated runs of the same name never overwrite each
    # other — you need two runs to see the noise floor.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    paths = save_report(result, output_dir=REPORTS_DIR, run_name=f"{args.run_name}_{stamp}")

    print()
    print_report(result)
    print("\nReport saved:")
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
            try:
                comparison = compare(baseline, result)
            except DatasetMismatch as exc:
                # The run itself is finished and saved; only the comparison is
                # refused. Exit 0 — nothing about the measurement went wrong.
                print(f"\nNo A/B comparison: {exc}", file=sys.stderr)
            else:
                print("\nA/B comparison (baseline → this run):")
                print(comparison.as_markdown())

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Atlas evaluation harness.")
    parser.add_argument(
        "--dataset",
        help=(
            "Path to EvalDataset JSON. Required, and no default on purpose — "
            "which set is right depends on what is in the namespace."
        ),
    )
    parser.add_argument(
        "--namespace",
        default="default",
        help="Corpus namespace to evaluate against (default: default).",
    )
    parser.add_argument(
        "--corpus",
        help=(
            "Directory the dataset's relevant_doc_ids are relative to, for checking "
            "they resolve. Overrides the dataset's own corpus_root."
        ),
    )
    parser.add_argument(
        "--allow-broken-dataset",
        action="store_true",
        help=(
            "Run even though the dataset failed its checks. The scores will be wrong "
            "in the direction of looking like retrieval failures."
        ),
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
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="SECTION.FIELD=VALUE",
        help="Override a setting for this run, e.g. reranker.enabled=false or "
             "retrieval.top_k=30. Repeatable. Recorded in the report.",
    )
    sys.exit(asyncio.run(main(parser.parse_args())))
