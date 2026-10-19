"""Tests for QueryRouter — mocks the LLM, tests classification logic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from atlas.config import GENERIC_DOMAIN, RouterConfig
from atlas.interfaces.llm import GenerationResponse
from atlas.orchestration.router import QueryRouter


def _mock_llm(classification: str) -> AsyncMock:
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=GenerationResponse(
            content=f'{{"classification": "{classification}", "reasoning": "test"}}',
            model_used="gpt-4o-mini",
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
        )
    )
    return llm


class TestQueryRouter:
    @pytest.mark.asyncio
    async def test_classifies_simple(self) -> None:
        router = QueryRouter(_mock_llm("simple"))
        result = await router.classify("What is the refund policy?")
        assert result == "simple"

    @pytest.mark.asyncio
    async def test_classifies_complex(self) -> None:
        router = QueryRouter(_mock_llm("complex"))
        result = await router.classify("Compare Q3 and Q4 revenue and explain the delta.")
        assert result == "complex"

    @pytest.mark.asyncio
    async def test_classifies_out_of_scope(self) -> None:
        router = QueryRouter(_mock_llm("out_of_scope"))
        result = await router.classify("Write me a sorting algorithm in Python.")
        assert result == "out_of_scope"

    @pytest.mark.asyncio
    async def test_llm_called_once(self) -> None:
        llm = _mock_llm("simple")
        router = QueryRouter(llm)
        await router.classify("any query")
        llm.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_classification_defaults_to_simple(self) -> None:
        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value=GenerationResponse(
                content='{"reasoning": "no classification key"}',
                model_used="gpt-4o-mini",
                prompt_tokens=10, completion_tokens=5, total_tokens=15,
            )
        )
        router = QueryRouter(llm)
        result = await router.classify("some query")
        assert result == "simple"


class TestTheDomainBelongsToACorpusNotTheProcess:
    """A namespace is a separate corpus; one prose description cannot be true
    of all of them.

    On 2026-10-13 a corpus uploaded through the console was refused at the
    router -- "not concepts defined by the FastAPI framework" -- because
    ROUTER_DOMAIN described the FastAPI docs and every namespace was handed
    the same sentence. Nothing had looked at the corpus when that was decided.
    """

    def test_the_named_namespace_gets_the_configured_domain(self) -> None:
        cfg = RouterConfig(domain="the FastAPI docs", domain_namespace="default")
        assert cfg.domain_for("default") == "the FastAPI docs"

    def test_every_other_namespace_gets_the_generic_domain(self) -> None:
        cfg = RouterConfig(domain="the FastAPI docs", domain_namespace="default")
        assert cfg.domain_for("console-demo") == GENERIC_DOMAIN
        assert "FastAPI" not in cfg.domain_for("console-demo")

    def test_the_scope_is_configurable_not_hardcoded_to_default(self) -> None:
        # A single-corpus deployment need not call its namespace "default".
        cfg = RouterConfig(domain="our internal runbooks", domain_namespace="ops")
        assert cfg.domain_for("ops") == "our internal runbooks"
        assert cfg.domain_for("default") == GENERIC_DOMAIN

    def test_an_unconfigured_domain_is_generic_everywhere(self) -> None:
        # _env_file=None, because the shipped default is the claim under test
        # and this developer's .env sets ROUTER_DOMAIN. Without it the test
        # asserts what one machine happens to hold and passes in CI for a
        # different reason than it passes here.
        cfg = RouterConfig(_env_file=None)
        assert cfg.domain_for("default") == GENERIC_DOMAIN
        assert cfg.domain_for("anything") == GENERIC_DOMAIN

    def test_the_prompt_carries_the_domain_it_was_built_with(self) -> None:
        cfg = RouterConfig(domain="the FastAPI docs", domain_namespace="default")
        for namespace, expected in (("default", "the FastAPI docs"), ("other", GENERIC_DOMAIN)):
            scoped = cfg.model_copy(update={"domain": cfg.domain_for(namespace)})
            router = QueryRouter(_mock_llm("simple"), scoped)
            assert expected in router._system_prompt


class TestTheClassifierPromptIsWellFormed:
    """The prompt is the router's whole behaviour, and it is a format string.

    Its JSON examples are written with doubled braces so `.format(domain=...)`
    leaves them intact. Get that wrong and the prompt still builds, still
    sends, and still classifies — just with examples that are no longer valid
    JSON, which is the kind of break no mocked classification test can see.
    These assert the prompt's shape rather than any verdict, because a mocked
    LLM returns whatever it was told to and can prove nothing about quality.
    Quality is measured by `scripts/probe_router.py` against a real model.
    """

    def _examples(self, prompt: str) -> list[dict[str, str]]:
        import json
        return [
            json.loads(line.removeprefix("Response: "))
            for line in prompt.splitlines()
            if line.startswith("Response: ")
        ]

    def test_every_example_response_is_valid_json(self) -> None:
        router = QueryRouter(_mock_llm("simple"), RouterConfig(domain="the FastAPI docs"))
        examples = self._examples(router._system_prompt)
        assert examples, "no Response: examples found — the prompt lost its few-shot block"
        for example in examples:
            assert set(example) == {"classification", "reasoning"}

    def test_every_example_uses_a_label_the_router_can_return(self) -> None:
        # An example teaching "outofscope" or "OUT_OF_SCOPE" would be copied
        # faithfully by the model and then fall through `parsed.get` to
        # "simple", refusing nothing and reporting nothing.
        router = QueryRouter(_mock_llm("simple"), RouterConfig(domain="the FastAPI docs"))
        for example in self._examples(router._system_prompt):
            assert example["classification"] in {"simple", "complex", "out_of_scope"}

    def test_both_out_of_scope_examples_survive(self) -> None:
        # Two, deliberately: the unrelated question and the near miss. Until
        # 2026-10-19 there was only the first, and fq-016 — a Stripe webhook
        # question naming FastAPI — classified `simple`. Dropping either one
        # back out is the regression this guards.
        router = QueryRouter(_mock_llm("simple"), RouterConfig(domain="the FastAPI docs"))
        refusals = [
            e for e in self._examples(router._system_prompt)
            if e["classification"] == "out_of_scope"
        ]
        assert len(refusals) >= 2

    def test_the_doubt_tie_break_still_favours_answering(self) -> None:
        # The counterweight to the near-miss rule. On 2026-10-13 an uploaded
        # corpus was refused at the router before retrieval ran; the fix for
        # under-refusal must not cost that guard.
        router = QueryRouter(_mock_llm("simple"), RouterConfig(domain="the FastAPI docs"))
        assert "unsure" in router._system_prompt
        assert "let retrieval decide" in router._system_prompt
