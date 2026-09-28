"""
Loading an eval dataset, and refusing to run one that is broken.

Why this exists:
    On 2026-09-27 all fifteen rows of the FastAPI set were read back against
    the corpus and nine needed a change. Most of those faults only a human
    reading the pages can find, and nothing here pretends otherwise. But two
    of them are mechanical, and both were silent:

      - A label that names nothing. `relevant_doc_ids` are corpus-relative
        paths, matched against the retrieved chunks by `doc_match`. A typo, a
        renamed page, or a path written with the wrong root matches no chunk
        ever, so the row scores precision 0.0 and recall 0.0 — exactly what a
        genuine retrieval failure looks like. Three sessions of planning read
        one of those as a retrieval problem.

      - An empty label set that nobody meant. An empty `relevant_doc_ids`
        tells both context metrics the row is unanswerable, and they return
        `applicable=False` and drop it from the aggregate. That is the right
        behaviour for a deliberately out-of-scope row and a silent hole for
        any other. `fq-015` sat in that hole: it was answerable from
        `advanced/websockets.md` all along, its retrieval was scoring 0.467
        precision, and the aggregate never saw it. A row with no labels is
        unfalsifiable by construction — precision and recall have nothing to
        disagree with — so the *intent* has to be stated, not inferred.

      - A dataset run against a namespace that does not hold its corpus.
        `run_eval.py` used to default `--dataset` to the 30-question HR set,
        so a bare invocation in this repo scored those questions against the
        FastAPI index and printed a full, well-formatted report of zeros —
        then a confident `Overall winner` against a 15-sample FastAPI
        baseline. Nothing about the report looked broken. Only the token
        count did. The namespace's own index says which documents it holds,
        so this is answerable locally and for nothing.

    All three checks run before any model is called, so a broken dataset
    fails for free rather than after an eval run has been paid for.

What this cannot check:
    Whether a label set is *complete*. `fq-012` named one real page when its
    answer rested on five; every one of those labels resolved. Whether a
    reference answer is *supported*. `fq-010` prescribed two APIs that appear
    nowhere in the corpus, in prose no checker parses. Both need a person to
    read the row against the pages. See planning/DECISIONS.md.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from atlas.ingestion.hashing import hash_text
from atlas.interfaces.document import document_id
from atlas.interfaces.evaluator import EvalDataset

# The metadata flag a row sets to say its empty label set is deliberate.
OUT_OF_SCOPE_FLAG = "out_of_scope"


class DatasetError(ValueError):
    """A dataset that would silently mis-score if it were run."""


def dataset_fingerprint(dataset: EvalDataset) -> str:
    """Identity of a dataset *as a measurement*, not as a file.

    Two runs are comparable when they asked the same questions and judged
    them against the same labels. Neither the filename nor the sample ids
    establish that: on 2026-09-27 nine of fifteen rows in
    `fastapi_dataset.json` were relabelled, and the file kept its name and
    every one of its ids. Every precision and recall number recorded before
    that edit became incomparable with every one after it, and nothing in a
    report said so.

    Covers the dataset name, and per sample the id, the question text, the
    label set and whether the row is declared out of scope — the inputs the
    four metrics actually read.

    Deliberately excludes `ground_truth_answer`, and still does now that
    `answer_correctness` reads it. Four of the five metrics do not, so
    folding the reference answers in here would declare every stored report
    incomparable with every future one over a field their scores cannot
    depend on — a guard that cries wolf is one that gets bypassed. The
    reference answers have their own fingerprint, `dataset_answers_fingerprint`,
    which the comparator checks only between two runs that both measured
    correctness.
    """
    parts = [dataset.name]
    for sample in sorted(dataset.samples, key=lambda s: s.id):
        parts.append(sample.id)
        parts.append(sample.question)
        # Sorted and deduplicated: recall works on a set, so a reordered or
        # repeated label is the same measurement.
        parts.extend(sorted(set(sample.relevant_doc_ids)))
        parts.append(str(sample.metadata.get(OUT_OF_SCOPE_FLAG) is True))
    # \x1f (unit separator) cannot occur in a path, an id or a question, so
    # no arrangement of fields can be made to collide with another.
    return hash_text("\x1f".join(parts))


def dataset_answers_fingerprint(dataset: EvalDataset) -> str:
    """Identity of the dataset's *reference answers*.

    Separate from `dataset_fingerprint` because it answers a different
    question. That one asks "were these the same questions and labels?",
    which is what the four retrieval-and-grounding metrics depend on. This
    one asks "were these the same reference answers?", which only
    `answer_correctness` depends on.

    Keeping them apart is what lets the 2026-09-27 rewrite of `fq-010` stay
    irrelevant to a precision comparison while being decisive for a
    correctness one. Folding both into a single value would have made every
    report in `eval_data/reports/` incomparable with everything written
    after today, over a field that could not have moved any of their scores.
    """
    parts = [dataset.name]
    for sample in sorted(dataset.samples, key=lambda s: s.id):
        parts.append(sample.id)
        parts.append(sample.ground_truth_answer)
    return hash_text("\x1f".join(parts))


def doc_keys(source: str, corpus_root: Path | None = None) -> set[str]:
    """Every id a chunk of *source* can present to `doc_match`.

    Deliberately built the same way `doc_match.chunk_doc_keys` builds a
    chunk's keys, because agreeing with the matcher is the whole point: a
    label outside this set cannot match any chunk, whatever it looks like.
    """
    path = Path(source)
    no_ext = path.with_suffix("") if path.suffix else path
    keys = {document_id(source), source, no_ext.name, str(no_ext)}
    if corpus_root is not None:
        # A source from outside the root has no corpus-relative form; the
        # other four keys still stand, so this is skipped rather than fatal.
        with contextlib.suppress(ValueError):
            keys.add(no_ext.relative_to(corpus_root).as_posix())
    return keys


def corpus_doc_keys(corpus_root: Path) -> set[str]:
    """Keys for every document on disk under *corpus_root*."""
    keys: set[str] = set()
    for path in sorted(corpus_root.rglob("*")):
        if path.is_file():
            keys |= doc_keys(str(path), corpus_root)
    return keys


def indexed_doc_keys(sparse_index: Path, corpus_root: Path | None = None) -> set[str] | None:
    """Keys for the documents a namespace's BM25 index actually holds.

    `None` when there is no index file, which is a different statement from
    an empty set: nothing has been ingested into this namespace *here*, as
    opposed to a namespace holding documents the dataset does not name.

    Read straight off the JSON rather than through `BM25SparseIndex`, whose
    constructor re-tokenises every chunk to rebuild the ranker. This needs
    the `source` field and nothing else, and it runs before an eval has spent
    anything, so it should not cost seconds of CPU to answer.
    """
    if not sparse_index.is_file():
        return None
    try:
        entries = json.loads(sparse_index.read_text())
    except json.JSONDecodeError:
        return None
    keys: set[str] = set()
    for source in {e.get("metadata", {}).get("source", "") for e in entries}:
        if source:
            keys |= doc_keys(source, corpus_root)
    return keys


def check_dataset_is_ingested(
    dataset: EvalDataset, known: set[str] | None, where: str
) -> list[str]:
    """Problems from running *dataset* against an index that lacks its corpus.

    Separate from `check_dataset` because it asks a different question. That
    one asks whether the labels name real files; this one asks whether those
    files are in the thing about to be queried. A dataset can be perfect and
    still be pointed at the wrong namespace.
    """
    labelled = [s for s in dataset.samples if s.relevant_doc_ids]
    if not labelled or known is None:
        return []

    missing = [s.id for s in labelled if not any(i in known for i in s.relevant_doc_ids)]
    if not missing:
        return []

    if len(missing) == len(labelled):
        # Every labelled row. Not a corpus with gaps — the wrong corpus.
        return [
            f"none of the {len(labelled)} labelled samples name a document in {where}. "
            f"This dataset and this namespace are about different corpora, and the run "
            f"would score every row a miss and report it as a retrieval failure."
        ]
    return [
        f"{len(missing)} of {len(labelled)} labelled samples name no document in "
        f"{where} ({', '.join(missing[:5])}"
        f"{', …' if len(missing) > 5 else ''}), so those rows score a miss whatever "
        f"retrieval does. Ingest the missing pages or drop the rows."
    ]


def check_dataset(dataset: EvalDataset, corpus_root: Path | None = None) -> list[str]:
    """Return every problem found, as sentences. Empty list means clean."""
    problems: list[str] = []

    for sample in dataset.samples:
        if sample.relevant_doc_ids:
            duplicates = sorted(
                {i for i in sample.relevant_doc_ids if sample.relevant_doc_ids.count(i) > 1}
            )
            if duplicates:
                # Harmless to recall, which works on a set, but it inflates
                # nothing and means someone edited the row twice.
                problems.append(f"{sample.id}: relevant_doc_ids repeats {duplicates}.")
            continue

        if sample.metadata.get(OUT_OF_SCOPE_FLAG) is not True:
            problems.append(
                f"{sample.id}: relevant_doc_ids is empty, which tells both context "
                f"metrics the row is unanswerable and drops it from the aggregate. "
                f'Set metadata.{OUT_OF_SCOPE_FLAG} to true if that is intended, '
                f"after checking the corpus really cannot answer it."
            )

    if corpus_root is None:
        return problems

    if not corpus_root.is_dir():
        problems.append(f"corpus_root {corpus_root} is not a directory.")
        return problems

    known = corpus_doc_keys(corpus_root)
    for sample in dataset.samples:
        unresolved = [i for i in sample.relevant_doc_ids if i not in known]
        if unresolved:
            problems.append(
                f"{sample.id}: {unresolved} match no document in {corpus_root}, so they "
                f"can never match a retrieved chunk and score the row as a miss."
            )
    return problems


def load_dataset(
    path: Path, corpus_root: Path | None = None, *, strict: bool = True
) -> tuple[EvalDataset, list[str]]:
    """Load, validate, and check a dataset.

    `corpus_root` overrides the dataset's own field, for the case where the
    corpus lives somewhere else on this machine. When neither is available the
    label-resolution check is skipped and says so in the returned notes, since
    silently not checking is how this class of fault survives.

    Returns the dataset and any notes worth printing. Raises `DatasetError`
    under `strict` if there were problems.
    """
    dataset = EvalDataset.model_validate(json.loads(path.read_text()))

    root = corpus_root
    if root is None and dataset.corpus_root:
        candidate = Path(dataset.corpus_root)
        if candidate.is_absolute():
            root = candidate
        else:
            # Relative to the working directory, which is how every other path
            # in this repo is written (`data/corpus/fastapi`,
            # `eval_data/reports`). Falling back to the dataset's own directory
            # covers a dataset invoked from somewhere else, and picking the one
            # that exists beats guessing: an unresolvable root is reported, not
            # silently skipped.
            beside = path.parent / candidate
            root = candidate if candidate.is_dir() or not beside.is_dir() else beside

    notes: list[str] = []
    if root is None:
        notes.append(
            "No corpus_root on the dataset and none given, so labels were not checked "
            "against any corpus. A label naming a page that does not exist scores the "
            "row as a retrieval miss."
        )

    problems = check_dataset(dataset, root)
    if problems and strict:
        raise DatasetError(
            f"{path} has {len(problems)} problem(s):\n  - " + "\n  - ".join(problems)
        )
    notes.extend(problems)
    return dataset, notes
