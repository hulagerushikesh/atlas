"""The reranker that loads behind the server instead of in front of it.

A Cloud Run cold start measured 36.9 s on 2026-10-21. 12.41 s of it was the
import graph — measured inside the container with the image already local,
so no pull is in that number — and almost all of it was torch arriving via
`atlas.api.namespaces` importing `CrossEncoderReranker` at module scope.
Nothing but `/query` needs that model, so everyone loading the landing page
waited for it.

The wrapper's value is entirely in what it does *not* do at import, so the
first test here runs a subprocess and checks `sys.modules`. Asserting on the
behaviour of the wrapper in a process where another test has already
imported torch would pass forever while the regression shipped.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from atlas.config import RerankerConfig
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievedChunk
from atlas.retrieval.lazy import LazyCrossEncoderReranker


def _chunk(chunk_id: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        content="c",
        score=score,
        metadata=ChunkMetadata(
            doc_id="doc1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=1,
        ),
    )


class _CountingDelegate:
    """Stands in for the real CrossEncoder without importing one."""

    def __init__(self) -> None:
        self.calls = 0

    async def rerank(
        self, query: str, candidates: list[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        self.calls += 1
        return list(reversed(candidates))[:top_k]


class TestTheServerStartsWithoutTorch:
    def test_importing_the_asgi_app_does_not_import_torch(self) -> None:
        # A subprocess, because this assertion is about a module graph and
        # the test process has already imported torch for other tests.
        probe = (
            "import sys; import atlas.api.asgi; "
            "heavy = [m for m in ('torch', 'transformers', 'sentence_transformers') "
            "if m in sys.modules]; "
            "print('HEAVY=' + ','.join(heavy))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=180,
            env={"PATH": "/usr/bin:/bin", "OPENAI_API_KEY": "dummy", "HOME": "/tmp"},
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert "HEAVY=" in result.stdout, result.stdout
        heavy = result.stdout.split("HEAVY=")[1].strip()
        assert heavy == "", f"the cold-start fix regressed: {heavy} imported at startup"

    def test_constructing_the_wrapper_builds_no_model(self) -> None:
        built = []
        lazy = LazyCrossEncoderReranker(RerankerConfig())
        object.__setattr__(lazy, "_build", lambda: built.append(1))
        assert not lazy.is_loaded
        assert built == []


class TestItLoadsOnceAndOnlyWhenNeeded:
    async def test_the_first_rerank_builds_the_model(self) -> None:
        delegate = _CountingDelegate()
        lazy = LazyCrossEncoderReranker(RerankerConfig())
        lazy._build = lambda: delegate  # type: ignore[method-assign]

        out = await lazy.rerank("q", [_chunk("a", 0.1), _chunk("b", 0.2)], top_k=1)

        assert lazy.is_loaded
        assert [c.chunk_id for c in out] == ["b"]

    async def test_a_burst_of_first_queries_builds_one_model(self) -> None:
        # Without the lock each concurrent caller would load its own copy of
        # a ~100 MB model on an instance sized for one.
        builds = 0
        delegate = _CountingDelegate()

        def build() -> _CountingDelegate:
            nonlocal builds
            builds += 1
            return delegate

        lazy = LazyCrossEncoderReranker(RerankerConfig())
        lazy._build = build  # type: ignore[method-assign]

        await asyncio.gather(
            *(lazy.rerank("q", [_chunk("a", 0.1)], top_k=1) for _ in range(8))
        )
        assert builds == 1
        assert delegate.calls == 8

    async def test_warm_loads_it_off_the_request_path(self) -> None:
        lazy = LazyCrossEncoderReranker(RerankerConfig())
        lazy._build = lambda: _CountingDelegate()  # type: ignore[method-assign]

        assert not lazy.is_loaded
        await lazy.warm()
        assert lazy.is_loaded


class TestAFailedLoadIsNeverSilentlyAnUnrerankedAnswer:
    async def test_warm_swallows_the_failure_so_the_api_still_serves(self) -> None:
        lazy = LazyCrossEncoderReranker(RerankerConfig())

        def boom() -> object:
            raise RuntimeError("no weights on disk")

        lazy._build = boom  # type: ignore[method-assign]

        # The landing page and /health do not need a reranker; a model that
        # cannot load must not take the whole service down at startup.
        await lazy.warm()
        assert not lazy.is_loaded

    async def test_but_a_query_raises_rather_than_returning_the_fused_order(self) -> None:
        lazy = LazyCrossEncoderReranker(RerankerConfig())

        def boom() -> object:
            raise RuntimeError("no weights on disk")

        lazy._build = boom  # type: ignore[method-assign]
        await lazy.warm()

        # Returning `candidates` unreranked here would answer the query with
        # measurably worse retrieval and no sign anything differed.
        with pytest.raises(RuntimeError, match="no weights on disk"):
            await lazy.rerank("q", [_chunk("a", 0.1)], top_k=1)

    async def test_a_load_that_failed_at_warm_is_retried_by_the_next_query(self) -> None:
        attempts = 0
        delegate = _CountingDelegate()

        def flaky() -> _CountingDelegate:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient")
            return delegate

        lazy = LazyCrossEncoderReranker(RerankerConfig())
        lazy._build = flaky  # type: ignore[method-assign]

        await lazy.warm()
        assert not lazy.is_loaded

        out = await lazy.rerank("q", [_chunk("a", 0.1)], top_k=1)
        assert attempts == 2
        assert [c.chunk_id for c in out] == ["a"]
