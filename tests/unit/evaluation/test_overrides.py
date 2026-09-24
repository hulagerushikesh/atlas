"""PipelineConfig.overrides → Settings, the A/B knob for run_eval.py --set."""

from __future__ import annotations

import pytest

from atlas.config import OpenAIConfig, Settings
from atlas.evaluation.overrides import apply_overrides, coerce, parse_override


@pytest.fixture
def settings() -> Settings:
    return Settings(openai=OpenAIConfig(api_key="test"))  # type: ignore[call-arg]


class TestParse:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("10", 10),
            ("0.5", 0.5),
            ("true", True),
            ("False", False),
            ("cross-encoder/ms-marco", "cross-encoder/ms-marco"),
            ('"quoted"', "quoted"),
        ],
    )
    def test_coerce(self, raw: str, expected: object) -> None:
        assert coerce(raw) == expected

    def test_parse_override(self) -> None:
        assert parse_override("reranker.top_k=10") == ("reranker.top_k", 10)
        assert parse_override(" reranker.enabled = false ") == ("reranker.enabled", False)

    @pytest.mark.parametrize("spec", ["reranker.top_k", "=5", ""])
    def test_rejects_malformed(self, spec: str) -> None:
        with pytest.raises(ValueError, match="section.field=value"):
            parse_override(spec)


class TestApply:
    def test_nested_override_does_not_touch_siblings(self, settings: Settings) -> None:
        # Captured, not hardcoded: this asserts apply_overrides leaves the
        # original alone, and pinning the literal 5 made it fail the day the
        # default became 15 for an unrelated reason.
        before = settings.reranker.top_k
        patched = apply_overrides(settings, {"reranker.top_k": 10})
        assert patched.reranker.top_k == 10
        assert patched.reranker.model == settings.reranker.model
        assert patched.retrieval.top_k == settings.retrieval.top_k
        assert settings.reranker.top_k == before  # original untouched
        assert before != 10  # or the assertion above proves nothing

    def test_reranker_off(self, settings: Settings) -> None:
        patched = apply_overrides(settings, {"reranker.enabled": False})
        assert patched.reranker.enabled is False
        assert settings.reranker.enabled is True

    def test_several_overrides(self, settings: Settings) -> None:
        patched = apply_overrides(
            settings, {"retrieval.top_k": 30, "chunking.size": 256, "log_level": "DEBUG"}
        )
        assert (patched.retrieval.top_k, patched.chunking.size, patched.log_level) == (
            30, 256, "DEBUG"
        )

    def test_secret_survives_copy(self, settings: Settings) -> None:
        patched = apply_overrides(settings, {"openai.primary_model": "gemini-3.5-flash-lite"})
        assert patched.openai.primary_model == "gemini-3.5-flash-lite"
        assert patched.openai.api_key.get_secret_value() == "test"

    def test_unknown_field_raises(self, settings: Settings) -> None:
        with pytest.raises(ValueError, match="unknown settings field 'topk'"):
            apply_overrides(settings, {"reranker.topk": 10})

    def test_descending_into_leaf_raises(self, settings: Settings) -> None:
        with pytest.raises(ValueError, match="leaf field"):
            apply_overrides(settings, {"reranker.top_k.deeper": 1})

    def test_bad_value_type_raises(self, settings: Settings) -> None:
        with pytest.raises(ValueError):
            apply_overrides(settings, {"reranker.top_k": "abc"})
