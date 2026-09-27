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

    Both checks run before any model is called, so a broken dataset fails for
    free rather than after an eval run has been paid for.

What this cannot check:
    Whether a label set is *complete*. `fq-012` named one real page when its
    answer rested on five; every one of those labels resolved. Whether a
    reference answer is *supported*. `fq-010` prescribed two APIs that appear
    nowhere in the corpus, in prose no checker parses. Both need a person to
    read the row against the pages. See planning/DECISIONS.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from atlas.interfaces.document import document_id
from atlas.interfaces.evaluator import EvalDataset

# The metadata flag a row sets to say its empty label set is deliberate.
OUT_OF_SCOPE_FLAG = "out_of_scope"


class DatasetError(ValueError):
    """A dataset that would silently mis-score if it were run."""


def corpus_doc_keys(corpus_root: Path) -> set[str]:
    """Every id a chunk of this corpus can present to `doc_match`.

    Deliberately built the same way `doc_match.chunk_doc_keys` builds a
    chunk's keys, because agreeing with the matcher is the whole point: a
    label outside this set cannot match any chunk, whatever it looks like.
    """
    keys: set[str] = set()
    for path in sorted(corpus_root.rglob("*")):
        if not path.is_file():
            continue
        source = str(path)
        no_ext = path.with_suffix("") if path.suffix else path
        keys |= {
            document_id(source),
            source,
            no_ext.name,
            str(no_ext),
            no_ext.relative_to(corpus_root).as_posix(),
        }
    return keys


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
