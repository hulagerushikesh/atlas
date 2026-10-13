"""
Namespace isolation for the sparse index.

Found on the first live run: every namespace shared one bm25_index.json, so
chunks ingested into one tenant were retrievable from another, and the CLI
ingest wrote to a collection the API never read.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from atlas.api.namespaces import NamespaceRegistry, namespace_to_collection, sparse_index_path
from atlas.config import GENERIC_DOMAIN, OpenAIConfig, RouterConfig, Settings


def test_sparse_index_path_is_per_namespace(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("ATLAS_INDEX_DIR", raising=False)
    a = sparse_index_path("tenant-a")
    b = sparse_index_path("tenant-b")
    assert a != b
    assert a == Path("data/index/tenant-a/bm25_index.json")


def test_sparse_index_root_is_overridable(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ATLAS_INDEX_DIR", str(tmp_path))
    assert sparse_index_path("x") == tmp_path / "x" / "bm25_index.json"


def test_collection_follows_namespace() -> None:
    assert namespace_to_collection("default") == "atlas_default"


class TestTheRouterIsBuiltPerNamespace:
    """ROUTER_DOMAIN describes one corpus, and a namespace is another corpus.

    Shipped with one router config for the whole process: a corpus uploaded
    through the console on 2026-10-13 was classified out_of_scope -- "not
    concepts defined by the FastAPI framework" -- before retrieval ran, and
    the console then reported that the sheet held no references covering the
    question. It held exactly those references.
    """

    @staticmethod
    def _registry(monkeypatch, tmp_path: Path, settings: Settings) -> NamespaceRegistry:  # type: ignore[no-untyped-def]
        monkeypatch.setenv("ATLAS_INDEX_DIR", str(tmp_path))
        shared = MagicMock()
        shared.settings = settings
        shared.reranker = None
        return NamespaceRegistry(shared)

    @staticmethod
    def _settings() -> Settings:
        # _env_file=None throughout: the claim is about the shipped resolution,
        # not about whichever ROUTER_DOMAIN this developer's .env holds.
        return Settings(
            _env_file=None,
            openai=OpenAIConfig(_env_file=None, api_key="test"),
            router=RouterConfig(
                _env_file=None,
                domain="the FastAPI docs",
                domain_namespace="default",
            ),
        )

    def test_the_described_namespace_keeps_its_domain(self, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        registry = self._registry(monkeypatch, tmp_path, self._settings())
        prompt = registry.get("default").pipeline._router._system_prompt
        assert "the FastAPI docs" in prompt

    def test_another_namespace_is_not_judged_against_it(self, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        registry = self._registry(monkeypatch, tmp_path, self._settings())
        prompt = registry.get("console-demo").pipeline._router._system_prompt
        assert "FastAPI" not in prompt
        assert GENERIC_DOMAIN in prompt

    def test_the_shared_config_is_not_mutated(self, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        # model_copy, not assignment: building one namespace must not change
        # what the next one is told.
        settings = self._settings()
        registry = self._registry(monkeypatch, tmp_path, settings)
        registry.get("console-demo")
        assert settings.router.domain == "the FastAPI docs"
        assert "the FastAPI docs" in registry.get("default").pipeline._router._system_prompt
