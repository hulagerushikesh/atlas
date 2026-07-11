"""
Tests for shared interface contracts.

These tests verify:
  1. Data models round-trip through JSON (important for caching and eval storage).
  2. ABCs enforce the required abstract methods.
  3. Default field values match documented intent.
"""

from __future__ import annotations

import pytest

from atlas.interfaces.document import Chunk, ChunkMetadata, Document, DocumentType
from atlas.interfaces.embedder import BaseEmbedder, EmbeddingResult
from atlas.interfaces.evaluator import EvalDataset, EvalSample, PipelineConfig
from atlas.interfaces.llm import GenerationRequest, Message
from atlas.interfaces.retriever import BaseRetriever, RetrievalResult, RetrievedChunk


# ── Document models ───────────────────────────────────────────────────────────

class TestDocumentModels:
    def test_document_defaults(self, sample_document: Document) -> None:
        assert sample_document.doc_type == DocumentType.MARKDOWN
        assert sample_document.metadata == {}

    def test_document_json_roundtrip(self, sample_document: Document) -> None:
        restored = Document.model_validate_json(sample_document.model_dump_json())
        assert restored == sample_document

    def test_chunk_json_roundtrip(self, sample_chunk: Chunk) -> None:
        restored = Chunk.model_validate_json(sample_chunk.model_dump_json())
        assert restored == sample_chunk

    def test_chunk_metadata_char_positions(self, sample_chunk: Chunk) -> None:
        meta = sample_chunk.metadata
        assert meta.end_char > meta.start_char


# ── ABC enforcement ───────────────────────────────────────────────────────────

class TestABCEnforcement:
    def test_retriever_abc_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            BaseRetriever()  # type: ignore[abstract]

    def test_embedder_abc_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            BaseEmbedder()  # type: ignore[abstract]


# ── Concrete ABC implementation ───────────────────────────────────────────────

class _StubRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "stub"

    async def retrieve(self, query: str, top_k: int) -> RetrievalResult:
        return RetrievalResult(query=query, chunks=[], retriever_name=self.name)


class TestStubRetriever:
    @pytest.mark.asyncio
    async def test_retrieve_returns_result(self) -> None:
        retriever = _StubRetriever()
        result = await retriever.retrieve("test query", top_k=5)
        assert result.query == "test query"
        assert result.retriever_name == "stub"
        assert result.chunks == []


# ── Eval models ───────────────────────────────────────────────────────────────

class TestEvalModels:
    def test_eval_dataset_roundtrip(self) -> None:
        dataset = EvalDataset(
            name="smoke",
            samples=[
                EvalSample(
                    id="s1",
                    question="What is Atlas?",
                    ground_truth_answer="A RAG platform.",
                    relevant_doc_ids=["doc-001"],
                )
            ],
        )
        restored = EvalDataset.model_validate_json(dataset.model_dump_json())
        assert restored.samples[0].id == "s1"

    def test_pipeline_config_empty_overrides(self) -> None:
        cfg = PipelineConfig(name="baseline")
        assert cfg.overrides == {}


# ── LLM request ───────────────────────────────────────────────────────────────

class TestGenerationRequest:
    def test_default_temperature(self) -> None:
        req = GenerationRequest(
            messages=[Message(role="user", content="hello")]
        )
        assert req.temperature == 0.0
        assert req.json_mode is False
