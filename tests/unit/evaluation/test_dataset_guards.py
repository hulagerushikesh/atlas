"""Guards that refuse to run a dataset that would silently mis-score.

Sibling to test_dataset.py, which asserts the shipped sample set is
well-formed. This file is about the checker rather than any one dataset.

Both of these exist because the fault they catch is invisible in a report: a
label naming nothing and a genuine retrieval miss produce the same zeros, and
an undeclared empty label set removes a row from the aggregate without saying
so. See atlas.evaluation.dataset for the two cases that motivated them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.evaluation.dataset import (
    DatasetError,
    check_dataset,
    check_dataset_is_ingested,
    corpus_doc_keys,
    indexed_doc_keys,
    load_dataset,
)
from atlas.interfaces.evaluator import EvalDataset, EvalSample


def _sample(sid: str, doc_ids: list[str], **metadata: object) -> EvalSample:
    return EvalSample(
        id=sid,
        question="Does it?",
        ground_truth_answer="It does.",
        relevant_doc_ids=doc_ids,
        metadata=dict(metadata),
    )


def _corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    (root / "tutorial").mkdir(parents=True)
    (root / "async.md").write_text("# Async")
    (root / "tutorial" / "path-params.md").write_text("# Path Parameters")
    return root


class TestCorpusDocKeys:
    def test_offers_the_forms_a_dataset_is_written_in(self, tmp_path: Path) -> None:
        keys = corpus_doc_keys(_corpus(tmp_path))
        assert "tutorial/path-params" in keys  # corpus-relative, no extension
        assert "path-params" in keys  # bare stem
        assert "async" in keys

    def test_excludes_the_extension(self, tmp_path: Path) -> None:
        # A label written with .md would match no chunk, so the checker has to
        # call it unresolved rather than being helpful about it.
        assert "tutorial/path-params.md" not in corpus_doc_keys(_corpus(tmp_path))


class TestLabelsResolve:
    def test_a_real_label_passes(self, tmp_path: Path) -> None:
        dataset = EvalDataset(name="d", samples=[_sample("s1", ["tutorial/path-params"])])
        assert check_dataset(dataset, _corpus(tmp_path)) == []

    def test_a_typo_is_reported_with_the_row_it_is_in(self, tmp_path: Path) -> None:
        dataset = EvalDataset(name="d", samples=[_sample("s1", ["tutorial/path-param"])])
        problems = check_dataset(dataset, _corpus(tmp_path))
        assert len(problems) == 1
        assert "s1" in problems[0] and "tutorial/path-param" in problems[0]

    def test_one_bad_label_among_good_ones_still_reports(self, tmp_path: Path) -> None:
        dataset = EvalDataset(
            name="d", samples=[_sample("s1", ["async", "advanced/websockets"])]
        )
        problems = check_dataset(dataset, _corpus(tmp_path))
        assert len(problems) == 1
        assert "advanced/websockets" in problems[0]
        assert "async" not in problems[0]

    def test_without_a_corpus_the_check_is_skipped_not_passed(self) -> None:
        # Skipping silently is how this class of fault survives, so the caller
        # gets a note; check_dataset itself just does not look.
        dataset = EvalDataset(name="d", samples=[_sample("s1", ["nowhere/at/all"])])
        assert check_dataset(dataset, None) == []

    def test_a_corpus_root_that_is_not_there_is_a_problem(self, tmp_path: Path) -> None:
        dataset = EvalDataset(name="d", samples=[_sample("s1", ["async"])])
        problems = check_dataset(dataset, tmp_path / "missing")
        assert len(problems) == 1 and "not a directory" in problems[0]


class TestEmptyLabelsMustBeDeliberate:
    def test_an_undeclared_empty_row_is_reported(self) -> None:
        dataset = EvalDataset(name="d", samples=[_sample("s1", [])])
        problems = check_dataset(dataset, None)
        assert len(problems) == 1 and "out_of_scope" in problems[0]

    def test_declaring_it_is_enough(self) -> None:
        dataset = EvalDataset(name="d", samples=[_sample("s1", [], out_of_scope=True)])
        assert check_dataset(dataset, None) == []

    def test_a_falsey_flag_does_not_count_as_declaring_it(self) -> None:
        # `"out_of_scope": false` is someone saying the row is *not* out of
        # scope while leaving it unlabelled, which is the fq-015 shape exactly.
        dataset = EvalDataset(name="d", samples=[_sample("s1", [], out_of_scope=False)])
        assert len(check_dataset(dataset, None)) == 1


class TestDuplicateLabels:
    def test_repeats_are_reported(self) -> None:
        dataset = EvalDataset(name="d", samples=[_sample("s1", ["a", "b", "a"])])
        problems = check_dataset(dataset, None)
        assert len(problems) == 1 and "'a'" in problems[0]


class TestLoadDataset:
    def _write(self, tmp_path: Path, payload: dict) -> Path:
        path = tmp_path / "ds.json"
        path.write_text(json.dumps(payload))
        return path

    def test_strict_refuses_before_anything_is_spent(self, tmp_path: Path) -> None:
        corpus = _corpus(tmp_path)
        path = self._write(
            tmp_path,
            {
                "name": "d",
                "samples": [
                    {
                        "id": "s1",
                        "question": "q",
                        "ground_truth_answer": "a",
                        "relevant_doc_ids": ["tutorial/nope"],
                    }
                ],
            },
        )
        with pytest.raises(DatasetError, match="s1"):
            load_dataset(path, corpus)

    def test_non_strict_returns_the_problems_instead(self, tmp_path: Path) -> None:
        corpus = _corpus(tmp_path)
        path = self._write(
            tmp_path,
            {
                "name": "d",
                "samples": [
                    {
                        "id": "s1",
                        "question": "q",
                        "ground_truth_answer": "a",
                        "relevant_doc_ids": ["tutorial/nope"],
                    }
                ],
            },
        )
        dataset, notes = load_dataset(path, corpus, strict=False)
        assert len(dataset.samples) == 1
        assert any("tutorial/nope" in n for n in notes)

    def test_no_corpus_anywhere_yields_a_note_and_still_loads(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path,
            {
                "name": "d",
                "samples": [
                    {
                        "id": "s1",
                        "question": "q",
                        "ground_truth_answer": "a",
                        "relevant_doc_ids": ["whatever"],
                    }
                ],
            },
        )
        _, notes = load_dataset(path)
        assert len(notes) == 1 and "not checked" in notes[0]

    def test_the_dataset_can_name_its_own_corpus(self, tmp_path: Path) -> None:
        corpus = _corpus(tmp_path)
        path = self._write(
            tmp_path,
            {
                "name": "d",
                "corpus_root": str(corpus),
                "samples": [
                    {
                        "id": "s1",
                        "question": "q",
                        "ground_truth_answer": "a",
                        "relevant_doc_ids": ["tutorial/path-params"],
                    }
                ],
            },
        )
        dataset, notes = load_dataset(path)
        assert notes == []
        assert dataset.corpus_root == str(corpus)


class TestTheShippedDataset:
    def test_the_fastapi_set_passes_its_own_guards(self) -> None:
        # The set this project's every published number is measured against.
        # It failed both halves of this on 2026-09-27.
        dataset, notes = load_dataset(Path("eval_data/fastapi_dataset.json"))
        assert notes == []
        assert len(dataset.samples) == 15

    def test_the_sample_set_loads_with_only_the_no_corpus_note(self) -> None:
        # Its doc ids are synthetic (doc-hr-leave-policy), so there is nothing
        # on disk to resolve them against and the checker must say so rather
        # than pass quietly.
        dataset, notes = load_dataset(Path("eval_data/sample_dataset.json"))
        assert len(dataset.samples) == 30
        assert len(notes) == 1 and "not checked" in notes[0]


def _bm25_file(tmp_path: Path, sources: list[str]) -> Path:
    """A BM25 persistence file holding one chunk per source.

    Shaped the way `BM25SparseIndex._save_to_disk` writes it, because the
    checker reads that file directly rather than through the class — so a
    convenient stand-in shape would test nothing about the real one.
    """
    path = tmp_path / "index" / "bm25_index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "chunk_id": f"c{i}",
                    "content": "text",
                    "content_hash": f"h{i}",
                    "metadata": {"source": source, "doc_id": f"d{i}", "chunk_index": 0},
                }
                for i, source in enumerate(sources)
            ]
        )
    )
    return path


class TestIndexedDocKeys:
    def test_a_missing_index_is_none_not_empty(self, tmp_path: Path) -> None:
        """Different statements: nothing ingested here, versus a namespace
        that holds documents this dataset does not name. Only the second is
        a problem, so they cannot collapse to the same value."""
        assert indexed_doc_keys(tmp_path / "nope" / "bm25_index.json") is None

    def test_a_corrupt_index_is_none_rather_than_a_crash(self, tmp_path: Path) -> None:
        path = tmp_path / "bm25_index.json"
        path.write_text("{ not json")
        assert indexed_doc_keys(path) is None

    def test_keys_match_what_a_label_is_written_as(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        path = _bm25_file(tmp_path, [str(root / "tutorial" / "path-params.md")])
        keys = indexed_doc_keys(path, root)
        assert keys is not None
        # The corpus-relative form is what datasets actually use.
        assert "tutorial/path-params" in keys

    def test_the_index_and_the_corpus_agree(self, tmp_path: Path) -> None:
        """The checker is only worth anything if its key set matches the one
        built from disk; otherwise it rejects labels that would have scored."""
        root = _corpus(tmp_path)
        sources = [str(p) for p in sorted(root.rglob("*")) if p.is_file()]
        assert indexed_doc_keys(_bm25_file(tmp_path, sources), root) == corpus_doc_keys(root)


class TestDatasetMatchesTheNamespace:
    """The trap: `run_eval.py` defaulted --dataset to the 30-question HR set,
    so a bare run in this repo scored those against the FastAPI index and
    printed a full report of zeros with a confident overall winner."""

    def test_a_completely_different_corpus_is_refused(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        index = _bm25_file(tmp_path, [str(root / "async.md")])
        dataset = EvalDataset(
            name="hr",
            samples=[_sample("hr-1", ["policies/leave"]), _sample("hr-2", ["policies/pay"])],
        )

        problems = check_dataset_is_ingested(
            dataset, indexed_doc_keys(index, root), "namespace 'default'"
        )

        assert len(problems) == 1
        assert "none of the 2 labelled samples" in problems[0]

    def test_a_matching_corpus_is_clean(self, tmp_path: Path) -> None:
        root = _corpus(tmp_path)
        sources = [str(p) for p in sorted(root.rglob("*")) if p.is_file()]
        dataset = EvalDataset(name="ok", samples=[_sample("a", ["tutorial/path-params"])])

        assert (
            check_dataset_is_ingested(
                dataset, indexed_doc_keys(_bm25_file(tmp_path, sources), root), "ns"
            )
            == []
        )

    def test_a_partly_ingested_corpus_names_the_rows(self, tmp_path: Path) -> None:
        """Distinct from the wrong corpus: those rows score a miss whatever
        retrieval does, but the rest of the run is still meaningful."""
        root = _corpus(tmp_path)
        index = _bm25_file(tmp_path, [str(root / "async.md")])
        dataset = EvalDataset(
            name="partial",
            samples=[_sample("a", ["async"]), _sample("b", ["tutorial/path-params"])],
        )

        problems = check_dataset_is_ingested(
            dataset, indexed_doc_keys(index, root), "namespace 'default'"
        )

        assert len(problems) == 1
        assert "1 of 2 labelled samples" in problems[0]
        assert "b" in problems[0]

    def test_no_index_means_no_opinion(self, tmp_path: Path) -> None:
        dataset = EvalDataset(name="x", samples=[_sample("a", ["anything"])])
        assert check_dataset_is_ingested(dataset, None, "ns") == []

    def test_an_all_out_of_scope_dataset_is_not_a_mismatch(self, tmp_path: Path) -> None:
        """No labelled rows to disagree with, so there is nothing to say."""
        root = _corpus(tmp_path)
        index = _bm25_file(tmp_path, [str(root / "async.md")])
        dataset = EvalDataset(name="oos", samples=[_sample("a", [], out_of_scope=True)])

        assert check_dataset_is_ingested(dataset, indexed_doc_keys(index, root), "ns") == []
