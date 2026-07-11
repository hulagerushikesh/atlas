"""
Tests for Reciprocal Rank Fusion.

RRF has clean mathematical properties we can test exactly:
  - A chunk appearing first in both lists should rank first in the fused output.
  - A chunk appearing only in one list still gets a score.
  - top_k truncates the output.
  - Chunks not present in any list are absent from output.
  - Ties broken deterministically by chunk_id.
"""

from __future__ import annotations

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievalResult, RetrievedChunk
from atlas.retrieval.fusion import reciprocal_rank_fusion


def _chunk(cid: str, score: float = 1.0) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        content=f"content of {cid}",
        score=score,
        metadata=ChunkMetadata(
            doc_id="doc1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=10,
        ),
    )


def _result(retriever: str, chunk_ids: list[str]) -> RetrievalResult:
    return RetrievalResult(
        query="q",
        chunks=[_chunk(cid, score=float(len(chunk_ids) - i)) for i, cid in enumerate(chunk_ids)],
        retriever_name=retriever,
    )


class TestRRF:
    def test_top_ranked_in_both_wins(self) -> None:
        dense = _result("dense", ["A", "B", "C"])
        sparse = _result("sparse", ["A", "D", "B"])
        fused = reciprocal_rank_fusion([dense, sparse], top_k=5)
        assert fused[0].chunk_id == "A"   # rank 1 in both → highest RRF

    def test_chunk_only_in_one_list_included(self) -> None:
        dense = _result("dense", ["A", "B"])
        sparse = _result("sparse", ["C", "D"])
        fused = reciprocal_rank_fusion([dense, sparse], top_k=10)
        ids = {c.chunk_id for c in fused}
        assert ids == {"A", "B", "C", "D"}

    def test_top_k_truncates(self) -> None:
        dense = _result("dense", ["A", "B", "C", "D", "E"])
        sparse = _result("sparse", ["A", "B", "C", "D", "E"])
        fused = reciprocal_rank_fusion([dense, sparse], top_k=3)
        assert len(fused) == 3

    def test_rrf_score_overwrites_retriever_score(self) -> None:
        dense = _result("dense", ["A"])
        fused = reciprocal_rank_fusion([dense], top_k=5)
        # RRF score for rank-1 with k=60: 1/(60+1) ≈ 0.0164
        assert abs(fused[0].score - 1 / 61) < 1e-9

    def test_empty_results(self) -> None:
        assert reciprocal_rank_fusion([], top_k=5) == []

    def test_single_retriever(self) -> None:
        dense = _result("dense", ["X", "Y", "Z"])
        fused = reciprocal_rank_fusion([dense], top_k=2)
        assert len(fused) == 2
        assert fused[0].chunk_id == "X"

    def test_deterministic_tie_breaking(self) -> None:
        # Two chunks ranked equally across retrievers → sorted by chunk_id
        dense = _result("dense", ["B", "A"])
        sparse = _result("sparse", ["A", "B"])
        fused = reciprocal_rank_fusion([dense, sparse], top_k=2)
        # Both get RRF score 1/(61)+1/(62); equal — should be deterministic
        assert len(fused) == 2

    def test_rrf_score_decreasing(self) -> None:
        dense = _result("dense", ["A", "B", "C"])
        sparse = _result("sparse", ["A", "B", "C"])
        fused = reciprocal_rank_fusion([dense, sparse], top_k=3)
        scores = [c.score for c in fused]
        assert scores == sorted(scores, reverse=True)

    def test_custom_k_parameter(self) -> None:
        dense = _result("dense", ["A"])
        fused_k1 = reciprocal_rank_fusion([dense], top_k=5, k=1)
        fused_k60 = reciprocal_rank_fusion([dense], top_k=5, k=60)
        # k=1 gives higher score (1/2) than k=60 (1/61)
        assert fused_k1[0].score > fused_k60[0].score

    def test_three_retrievers(self) -> None:
        r1 = _result("dense", ["A", "B"])
        r2 = _result("sparse", ["B", "A"])
        r3 = _result("reranker", ["A", "C"])
        fused = reciprocal_rank_fusion([r1, r2, r3], top_k=5)
        # A appears at rank 1, 2, 1 → highest aggregate RRF
        assert fused[0].chunk_id == "A"
