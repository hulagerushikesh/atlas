"""Verify the sample evaluation dataset is valid and well-formed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.interfaces.evaluator import EvalDataset


DATASET_PATH = Path(__file__).parents[3] / "eval_data" / "sample_dataset.json"


@pytest.fixture(scope="module")
def dataset() -> EvalDataset:
    raw = json.loads(DATASET_PATH.read_text())
    return EvalDataset.model_validate(raw)


class TestSampleDataset:

    def test_file_exists(self) -> None:
        assert DATASET_PATH.exists()

    def test_has_thirty_samples(self, dataset: EvalDataset) -> None:
        assert len(dataset.samples) == 30

    def test_all_ids_unique(self, dataset: EvalDataset) -> None:
        ids = [s.id for s in dataset.samples]
        assert len(ids) == len(set(ids))

    def test_all_questions_non_empty(self, dataset: EvalDataset) -> None:
        for s in dataset.samples:
            assert s.question.strip(), f"Empty question in sample {s.id}"

    def test_all_ground_truths_non_empty(self, dataset: EvalDataset) -> None:
        for s in dataset.samples:
            assert s.ground_truth_answer.strip(), f"Empty ground truth in {s.id}"

    def test_cross_functional_samples_have_multiple_doc_ids(self, dataset: EvalDataset) -> None:
        cross = [s for s in dataset.samples if s.metadata.get("category") == "cross-functional"]
        assert len(cross) >= 2
        for s in cross:
            assert len(s.relevant_doc_ids) >= 2, f"{s.id} should reference multiple docs"

    def test_out_of_scope_sample_exists(self, dataset: EvalDataset) -> None:
        oos = [s for s in dataset.samples if s.metadata.get("category") == "out_of_scope"]
        assert len(oos) >= 1

    def test_categories_covered(self, dataset: EvalDataset) -> None:
        categories = {s.metadata.get("category") for s in dataset.samples}
        expected = {"hr", "it", "finance", "product", "legal", "security", "cross-functional", "out_of_scope"}
        assert expected.issubset(categories)

    def test_difficulty_levels_present(self, dataset: EvalDataset) -> None:
        difficulties = {s.metadata.get("difficulty") for s in dataset.samples}
        assert {"easy", "medium", "hard"}.issubset(difficulties)

    def test_dataset_roundtrips_json(self, dataset: EvalDataset) -> None:
        restored = EvalDataset.model_validate_json(dataset.model_dump_json())
        assert len(restored.samples) == len(dataset.samples)
