"""
Tests for CrossEncoderReranker.

The cross-encoder model is mocked so tests run without downloading weights.
We test that the reranker:
  - calls the model with the correct (query, content) pairs
  - returns chunks sorted by the model's scores (descending)
  - truncates to top_k
  - overwrites the original score with the cross-encoder score
  - handles empty candidate lists gracefully
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from atlas.config import RerankerConfig
from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievedChunk
from atlas.retrieval.reranker import CrossEncoderReranker


def _chunk(cid: str, content: str, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        content=content,
        score=score,
        metadata=ChunkMetadata(
            doc_id="doc1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=len(content),
        ),
    )


@pytest.fixture
def reranker() -> CrossEncoderReranker:
    config = RerankerConfig(model="cross-encoder/ms-marco-MiniLM-L-6-v2", top_k=3)
    with patch("atlas.retrieval.reranker.CrossEncoder") as MockCE:
        mock_model = MagicMock()
        MockCE.return_value = mock_model
        r = CrossEncoderReranker(config)
        r._model = mock_model  # keep reference for test assertions
        return r


class TestCrossEncoderReranker:
    @pytest.mark.asyncio
    async def test_reranks_by_model_score(self, reranker: CrossEncoderReranker) -> None:
        candidates = [
            _chunk("c1", "Atlas is a RAG platform", score=0.9),
            _chunk("c2", "Qdrant is a vector database", score=0.8),
            _chunk("c3", "BM25 is a sparse method", score=0.7),
        ]
        # Model assigns c2 the highest score
        reranker._model.predict.return_value = [0.3, 0.9, 0.5]

        result = await reranker.rerank("vector database", candidates, top_k=3)

        assert result[0].chunk_id == "c2"
        assert result[1].chunk_id == "c3"
        assert result[2].chunk_id == "c1"

    @pytest.mark.asyncio
    async def test_top_k_truncates(self, reranker: CrossEncoderReranker) -> None:
        candidates = [_chunk(f"c{i}", f"content {i}") for i in range(5)]
        reranker._model.predict.return_value = [0.1, 0.5, 0.3, 0.9, 0.2]

        result = await reranker.rerank("query", candidates, top_k=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_score_overwritten_with_cross_encoder_score(
        self, reranker: CrossEncoderReranker
    ) -> None:
        candidates = [_chunk("c1", "text", score=999.0)]
        reranker._model.predict.return_value = [0.42]

        result = await reranker.rerank("q", candidates, top_k=1)
        assert abs(result[0].score - 0.42) < 1e-6

    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self, reranker: CrossEncoderReranker) -> None:
        result = await reranker.rerank("q", [], top_k=5)
        assert result == []

    @pytest.mark.asyncio
    async def test_predict_called_with_correct_pairs(self, reranker: CrossEncoderReranker) -> None:
        candidates = [_chunk("c1", "alpha"), _chunk("c2", "beta")]
        reranker._model.predict.return_value = [0.5, 0.7]

        await reranker.rerank("my query", candidates, top_k=2)

        call_args = reranker._model.predict.call_args[0][0]
        assert call_args == [("my query", "alpha"), ("my query", "beta")]

    @pytest.mark.asyncio
    async def test_original_chunks_not_mutated(self, reranker: CrossEncoderReranker) -> None:
        original_score = 0.99
        candidates = [_chunk("c1", "text", score=original_score)]
        reranker._model.predict.return_value = [0.1]

        await reranker.rerank("q", candidates, top_k=1)
        # The original candidate object should be unchanged
        assert candidates[0].score == original_score


# ── Memory: batching and the CPU fallback, 2026-10-17 ─────────────────────────
#
# A HyDE eval died on two of sixteen samples with "MPS backend out of memory"
# while the baseline run that preceded it on the same machine and the same
# corpus finished clean. HyDE's `concat` mode puts a hypothesis of up to 220
# tokens in front of every query, which lengthens every pair in the batch at
# once, and sentence-transformers batches 32 at a time by default. Both dead
# samples were then scored at the failure sentinel and dropped from the mean,
# and the report printed sixteen.

class TestRerankerMemory:
    def _rr(self, **kw: object) -> tuple[CrossEncoderReranker, MagicMock]:
        config = RerankerConfig(model="m", top_k=3, **kw)  # type: ignore[arg-type]
        with patch("atlas.retrieval.reranker.CrossEncoder") as MockCE:
            model = MagicMock()
            MockCE.return_value = model
            return CrossEncoderReranker(config), MockCE

    @pytest.mark.asyncio
    async def test_batch_size_is_passed_and_is_not_the_library_default(self) -> None:
        rr, MockCE = self._rr()
        MockCE.return_value.predict.return_value = [0.9, 0.1]
        await rr.rerank("q", [_chunk("c1", "a"), _chunk("c2", "b")], top_k=2)
        _, kwargs = MockCE.return_value.predict.call_args
        assert kwargs["batch_size"] == 16

    def test_device_defaults_to_the_library_choice(self) -> None:
        _, MockCE = self._rr()
        assert MockCE.call_args.kwargs["device"] is None

    def test_device_can_be_pinned(self) -> None:
        _, MockCE = self._rr(device="cpu")
        assert MockCE.call_args.kwargs["device"] == "cpu"

    @pytest.mark.asyncio
    async def test_out_of_memory_falls_back_to_cpu_rather_than_killing_the_sample(
        self,
    ) -> None:
        config = RerankerConfig(model="m", top_k=2)
        with patch("atlas.retrieval.reranker.CrossEncoder") as MockCE:
            gpu, cpu = MagicMock(), MagicMock()
            gpu.predict.side_effect = RuntimeError(
                "MPS backend out of memory (MPS allocated: 2.02 GiB...)"
            )
            cpu.predict.return_value = [0.2, 0.8]
            MockCE.side_effect = [gpu, cpu]
            rr = CrossEncoderReranker(config)
            out = await rr.rerank("q", [_chunk("c1", "a"), _chunk("c2", "b")], top_k=2)
        assert [c.chunk_id for c in out] == ["c2", "c1"]
        assert MockCE.call_args_list[-1].kwargs["device"] == "cpu"

    @pytest.mark.asyncio
    async def test_the_cpu_model_is_built_once_across_repeated_failures(self) -> None:
        config = RerankerConfig(model="m", top_k=1)
        with patch("atlas.retrieval.reranker.CrossEncoder") as MockCE:
            gpu, cpu = MagicMock(), MagicMock()
            gpu.predict.side_effect = RuntimeError("CUDA out of memory")
            cpu.predict.return_value = [0.5]
            MockCE.side_effect = [gpu, cpu]
            rr = CrossEncoderReranker(config)
            await rr.rerank("q", [_chunk("c1", "a")], top_k=1)
            await rr.rerank("q", [_chunk("c1", "a")], top_k=1)
        # One construction for the accelerator, one for the fallback. A third
        # would mean reloading the model on every slow sample.
        assert MockCE.call_count == 2
        assert cpu.predict.call_count == 2

    @pytest.mark.asyncio
    async def test_any_other_runtime_error_is_re_raised(self) -> None:
        # The fallback matches on a message because torch gives no typed
        # exception for this. Anything it does not recognise has to surface:
        # a reranker that swallows errors returns an unranked candidate set
        # that looks exactly like a ranked one.
        rr, MockCE = self._rr()
        MockCE.return_value.predict.side_effect = RuntimeError("shape mismatch")
        with pytest.raises(RuntimeError, match="shape mismatch"):
            await rr.rerank("q", [_chunk("c1", "a")], top_k=1)
