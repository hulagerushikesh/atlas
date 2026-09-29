"""
Tests for RAGPipeline — the orchestration wiring.

All components are mocked. We test:
  - out_of_scope path: no retrieval, no generation
  - simple path: one retrieval, generate, check faithfulness
  - complex path: decompose → multi-retrieval → merge → generate
  - grader retry: insufficient context triggers re-query (capped at MAX_RETRIES)
  - deduplication: same chunk across sub-queries appears once
  - faithfulness flag propagates to PipelineResult
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from atlas.interfaces.document import ChunkMetadata, DocumentType
from atlas.interfaces.retriever import RetrievalResult, RetrievedChunk
from atlas.orchestration.faithfulness import FaithfulnessResult
from atlas.orchestration.generator import CitationRef, GeneratorResult
from atlas.orchestration.pipeline import RAGPipeline
from atlas.retrieval.hybrid import HybridRetrievalResult

# ── Helpers ───────────────────────────────────────────────────────────────────

def _chunk(cid: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, content=f"content {cid}", score=0.8,
        metadata=ChunkMetadata(
            doc_id="d1", source="t.md", doc_type=DocumentType.TEXT,
            chunk_index=0, start_char=0, end_char=10,
        ),
    )


def _mock_retriever(chunks: list[RetrievedChunk]) -> MagicMock:
    r = MagicMock()
    result = MagicMock()
    result.chunks = chunks
    r.retrieve = AsyncMock(return_value=result)
    return r


def _mock_router(classification: str) -> MagicMock:
    r = MagicMock()
    r.classify = AsyncMock(return_value=classification)
    return r


def _mock_decomposer(sub_queries: list[str]) -> MagicMock:
    d = MagicMock()
    d.decompose = AsyncMock(return_value=sub_queries)
    return d


def _mock_grader(responses: list[tuple[bool, float, str]]) -> MagicMock:
    g = MagicMock()
    g.grade = AsyncMock(side_effect=responses)
    return g


def _mock_generator(answer: str = "The answer [1].") -> MagicMock:
    gen = MagicMock()
    gen.generate = AsyncMock(
        return_value=GeneratorResult(
            answer=answer,
            citations={1: CitationRef(chunk_id="c1", source="t.md", page_number=None)},
        )
    )
    return gen


def _mock_faithfulness(faithful: bool = True, score: float = 0.95) -> MagicMock:
    f = MagicMock()
    f.check = AsyncMock(
        return_value=FaithfulnessResult(
            score=score, is_faithful=faithful, summary="ok"
        )
    )
    return f


def _mock_hyde(prefix: str = "PASSAGE about ") -> MagicMock:
    """An expander that returns a recognisable passage per query."""
    from atlas.orchestration.hyde import Expansion

    h = MagicMock()

    async def expand(queries: list[str]) -> list[Expansion]:
        return [
            Expansion(query=q, hypothesis=f"{prefix}{q}", text=f"{prefix}{q}")
            for q in queries
        ]

    h.expand = AsyncMock(side_effect=expand)
    return h


def _pipeline(
    retriever=None, router=None, decomposer=None,
    grader=None, generator=None, faithfulness=None,
    chunks=None, reranker=None, hyde=None,
) -> RAGPipeline:
    if chunks is None:
        chunks = [_chunk("c1")]
    return RAGPipeline(
        retriever=retriever or _mock_retriever(chunks),
        router=router or _mock_router("simple"),
        decomposer=decomposer or _mock_decomposer(["q1", "q2"]),
        grader=grader or _mock_grader([(True, 0.9, "q")]),
        generator=generator or _mock_generator(),
        faithfulness=faithfulness or _mock_faithfulness(),
        reranker=reranker,
        hyde=hyde,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRAGPipeline:
    @pytest.mark.asyncio
    async def test_out_of_scope_returns_early(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        p = _pipeline(router=_mock_router("out_of_scope"), retriever=retriever)
        result = await p.run("write a poem")
        assert result.classification == "out_of_scope"
        assert result.generation is None
        assert result.faithfulness is None
        retriever.retrieve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_simple_path_single_retrieval(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        p = _pipeline(router=_mock_router("simple"), retriever=retriever)
        result = await p.run("simple question")
        assert result.classification == "simple"
        assert result.sub_queries == ["simple question"]
        retriever.retrieve.assert_awaited_once_with("simple question")

    @pytest.mark.asyncio
    async def test_complex_path_decomposes(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        decomposer = _mock_decomposer(["sub1", "sub2"])
        p = _pipeline(
            router=_mock_router("complex"),
            decomposer=decomposer,
            retriever=retriever,
        )
        result = await p.run("complex multi-part question")
        assert result.sub_queries == ["sub1", "sub2"]
        assert retriever.retrieve.await_count == 2

    @pytest.mark.asyncio
    async def test_grader_retry_on_insufficient(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        # First grade: insufficient → retry; second: sufficient → proceed
        grader = _mock_grader([
            (False, 0.3, "reformulated"),
            (True, 0.8, "reformulated"),
        ])
        p = _pipeline(retriever=retriever, grader=grader)
        result = await p.run("q")
        assert result.grader_retries == 1
        # Retriever called twice: once for original, once for reformulated
        assert retriever.retrieve.await_count == 2

    @pytest.mark.asyncio
    async def test_grader_retry_cap(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        # Always insufficient — should cap at 2 retries
        grader = _mock_grader([
            (False, 0.1, "r1"),
            (False, 0.1, "r2"),
            (False, 0.1, "r3"),  # this would be a third retry if uncapped
        ])
        p = _pipeline(retriever=retriever, grader=grader)
        result = await p.run("q")
        assert result.grader_retries == 2
        # 3 total retrieves: original + 2 retries
        assert retriever.retrieve.await_count == 3

    @pytest.mark.asyncio
    async def test_deduplication_across_sub_queries(self) -> None:
        # Both sub-queries return the same chunk
        retriever = _mock_retriever([_chunk("c1")])
        decomposer = _mock_decomposer(["sub1", "sub2"])
        p = _pipeline(
            router=_mock_router("complex"),
            decomposer=decomposer,
            retriever=retriever,
        )
        result = await p.run("q")
        chunk_ids = [c.chunk_id for c in result.retrieved_chunks]
        assert chunk_ids.count("c1") == 1  # deduplicated

    @pytest.mark.asyncio
    async def test_faithfulness_flag_in_result(self) -> None:
        faithfulness = _mock_faithfulness(faithful=False, score=0.3)
        p = _pipeline(faithfulness=faithfulness)
        result = await p.run("q")
        assert result.is_faithful is False

    @pytest.mark.asyncio
    async def test_answer_accessible_on_result(self) -> None:
        generator = _mock_generator("My detailed answer [1].")
        p = _pipeline(generator=generator)
        result = await p.run("q")
        assert result.answer == "My detailed answer [1]."

    @pytest.mark.asyncio
    async def test_out_of_scope_answer_is_fixed_message(self) -> None:
        p = _pipeline(router=_mock_router("out_of_scope"))
        result = await p.run("q")
        assert "outside the scope" in result.answer


# ── Evidence and timing provenance ────────────────────────────────────────────

def _scored(cid: str, score: float) -> RetrievedChunk:
    c = _chunk(cid)
    c.score = score
    return c


def _hybrid_result(
    dense: list[RetrievedChunk],
    sparse: list[RetrievedChunk],
    fused: list[RetrievedChunk],
    reranked: list[RetrievedChunk],
) -> HybridRetrievalResult:
    """A real HybridRetrievalResult, not a mock — the provenance shape is the contract."""
    return HybridRetrievalResult(
        query="q",
        per_retriever=[
            RetrievalResult(query="q", chunks=dense, retriever_name="qdrant_dense"),
            RetrievalResult(query="q", chunks=sparse, retriever_name="bm25_sparse"),
        ],
        fused=fused,
        reranked=reranked,
    )


class TestEvidenceProvenance:
    async def test_evidence_carries_score_per_stage(self) -> None:
        """
        Every stage the chunk passed through leaves its score on the trail.
        The hybrid retriever already computes these and used to discard them.
        """
        hybrid = _hybrid_result(
            dense=[_scored("c1", 0.81)],
            sparse=[_scored("c1", 12.4)],
            fused=[_scored("c1", 0.032)],
            reranked=[_scored("c1", 0.94)],
        )
        retriever = MagicMock()
        retriever.retrieve = AsyncMock(return_value=hybrid)

        result = await _pipeline(retriever=retriever).run("q")

        [ev] = result.evidence
        assert ev.chunk.chunk_id == "c1"
        assert ev.selected is True
        assert ev.scores == {"dense": 0.81, "bm25": 12.4, "rrf": 0.032, "rerank": 0.94}
        # The chunk handed on is the reranked copy — its score is the final one.
        assert ev.chunk.score == 0.94

    async def test_rerank_rejects_are_kept_but_not_selected(self) -> None:
        """A chunk cut by the reranker is still evidence: it explains what was considered."""
        hybrid = _hybrid_result(
            dense=[_scored("c1", 0.8), _scored("c2", 0.7)],
            sparse=[],
            fused=[_scored("c1", 0.03), _scored("c2", 0.02)],
            reranked=[_scored("c1", 0.9)],
        )
        retriever = MagicMock()
        retriever.retrieve = AsyncMock(return_value=hybrid)

        result = await _pipeline(retriever=retriever).run("q")

        assert [c.chunk_id for c in result.retrieved_chunks] == ["c1"]
        assert [(e.chunk.chunk_id, e.selected) for e in result.evidence] == [
            ("c1", True),
            ("c2", False),
        ]
        assert "rerank" not in result.evidence[1].scores

    async def test_evidence_across_sub_queries_keeps_best_score(self) -> None:
        """The same chunk found by two sub-queries is one trail with its best scores."""
        first = _hybrid_result(
            dense=[_scored("c1", 0.5)], sparse=[], fused=[_scored("c1", 0.01)],
            reranked=[_scored("c1", 0.6)],
        )
        second = _hybrid_result(
            dense=[_scored("c1", 0.9)], sparse=[], fused=[_scored("c1", 0.03)],
            reranked=[_scored("c1", 0.95)],
        )
        retriever = MagicMock()
        retriever.retrieve = AsyncMock(side_effect=[first, second])

        result = await _pipeline(
            retriever=retriever,
            router=_mock_router("complex"),
            decomposer=_mock_decomposer(["a", "b"]),
        ).run("q")

        [ev] = result.evidence
        assert ev.scores["dense"] == 0.9
        assert ev.scores["rerank"] == 0.95

    async def test_plain_retriever_still_yields_evidence(self) -> None:
        """A non-hybrid retriever has one score and no stages; evidence degrades, not breaks."""
        result = await _pipeline(chunks=[_scored("c1", 0.77)]).run("q")
        [ev] = result.evidence
        assert ev.selected is True
        assert ev.scores == {"score": 0.77}

    async def test_stage_timings_recorded(self) -> None:
        result = await _pipeline().run("q")
        assert set(result.stage_ms) == {
            "routing", "retrieval", "grading", "generation", "faithfulness",
        }
        assert all(v >= 0 for v in result.stage_ms.values())

    async def test_decompose_timed_only_on_complex(self) -> None:
        simple = await _pipeline(router=_mock_router("simple")).run("q")
        complex_ = await _pipeline(router=_mock_router("complex")).run("q")
        assert "decompose" not in simple.stage_ms
        assert "decompose" in complex_.stage_ms

    async def test_retry_accumulates_retrieval_time(self) -> None:
        """Two retrieval passes must both count; the trace shows the retry's cost."""
        grader = _mock_grader([(False, 0.2, "reformulated"), (True, 0.9, "q")])
        retriever = _mock_retriever([_chunk("c1")])
        result = await _pipeline(retriever=retriever, grader=grader).run("q")
        assert result.grader_retries == 1
        assert retriever.retrieve.await_count == 2
        assert "retrieval" in result.stage_ms

    async def test_out_of_scope_has_routing_time_only(self) -> None:
        result = await _pipeline(router=_mock_router("out_of_scope")).run("q")
        assert set(result.stage_ms) == {"routing"}
        assert result.evidence == []


# ── Retry must not lose context ───────────────────────────────────────────────

def _retriever_per_attempt(batches: list[list[RetrievedChunk]]) -> MagicMock:
    """A retriever returning a different chunk set on each successive call."""
    r = MagicMock()

    def _result(chunks: list[RetrievedChunk]) -> MagicMock:
        res = MagicMock()
        res.chunks = chunks
        return res

    r.retrieve = AsyncMock(side_effect=[_result(b) for b in batches])
    return r


def _reranker_keeping(order: list[str]) -> MagicMock:
    """Reranker that ranks by a fixed chunk_id preference, then truncates."""
    rr = MagicMock()

    async def _rerank(query: str, candidates: list[RetrievedChunk], top_k: int):
        rank = {cid: i for i, cid in enumerate(order)}
        return sorted(candidates, key=lambda c: rank.get(c.chunk_id, 99))[:top_k]

    rr.rerank = AsyncMock(side_effect=_rerank)
    return rr


class TestRetryKeepsEarlierChunks:
    """A retry used to overwrite the window, so a grader that wrongly called it
    insufficient threw away documents already retrieved. fq-005 lost
    tutorial/body exactly that way."""

    @pytest.mark.asyncio
    async def test_chunk_from_first_attempt_survives_a_retry(self) -> None:
        good, filler, junk = _chunk("good"), _chunk("filler"), _chunk("junk")
        result = await _pipeline(
            retriever=_retriever_per_attempt([[good, filler], [junk, filler]]),
            router=_mock_router("simple"),
            grader=_mock_grader([(False, 0.4, "reformulated"), (True, 0.9, "q")]),
            reranker=_reranker_keeping(["good", "junk", "filler"]),
        ).run("q")
        assert result.grader_retries == 1
        assert "good" in [c.chunk_id for c in result.retrieved_chunks]

    @pytest.mark.asyncio
    async def test_window_width_is_preserved_across_the_union(self) -> None:
        # Two attempts of two chunks each must still hand the generator two,
        # not four: the retry widens what is considered, not what is sent.
        a, b, c, d = _chunk("a"), _chunk("b"), _chunk("c"), _chunk("d")
        result = await _pipeline(
            retriever=_retriever_per_attempt([[a, b], [c, d]]),
            router=_mock_router("simple"),
            grader=_mock_grader([(False, 0.4, "r"), (True, 0.9, "q")]),
            reranker=_reranker_keeping(["c", "a", "b", "d"]),
        ).run("q")
        assert len(result.retrieved_chunks) == 2
        assert [x.chunk_id for x in result.retrieved_chunks] == ["c", "a"]

    @pytest.mark.asyncio
    async def test_union_is_scored_against_the_original_query(self) -> None:
        # Not the reformulation: the two attempts' scores are each relative to
        # a different question, and the caller's is the only one both sets can
        # be compared on.
        rr = _reranker_keeping(["b", "a"])
        await _pipeline(
            retriever=_retriever_per_attempt([[_chunk("a")], [_chunk("b")]]),
            router=_mock_router("simple"),
            grader=_mock_grader([(False, 0.4, "reformulated"), (True, 0.9, "q")]),
            reranker=rr,
        ).run("the original question")
        assert rr.rerank.await_args.args[0] == "the original question"

    @pytest.mark.asyncio
    async def test_no_retry_means_no_extra_rerank(self) -> None:
        # The common path must not pay for the merge.
        rr = _reranker_keeping(["a"])
        await _pipeline(
            retriever=_retriever_per_attempt([[_chunk("a")]]),
            router=_mock_router("simple"),
            grader=_mock_grader([(True, 0.9, "q")]),
            reranker=rr,
        ).run("q")
        rr.rerank.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_without_a_reranker_the_old_behaviour_is_kept(self) -> None:
        # Nothing can compare two attempts' scores without one, so the merge
        # is skipped rather than guessed at. reranker.enabled=false is an
        # ablation setting; production always has one.
        result = await _pipeline(
            retriever=_retriever_per_attempt([[_chunk("old")], [_chunk("new")]]),
            router=_mock_router("simple"),
            grader=_mock_grader([(False, 0.4, "r"), (True, 0.9, "q")]),
        ).run("q")
        assert [c.chunk_id for c in result.retrieved_chunks] == ["new"]


class TestSubQueryMergeFitsOneWindow:
    """A decomposed question used to hand the generator `sub_queries x top_k`.

    fq-007 sent 41 chunks against a configured window of 15 and fq-013 sent
    30. That was never a decision to widen the window; it was the absence of
    one about what a window means after a query is split.
    """

    @staticmethod
    def _subquery_retriever(per_query: list[list[RetrievedChunk]]) -> MagicMock:
        """One distinct result list per sub-query, in decomposition order."""
        r = MagicMock()

        def _result(chunks: list[RetrievedChunk]) -> MagicMock:
            res = MagicMock()
            res.chunks = chunks
            return res

        r.retrieve = AsyncMock(side_effect=[_result(b) for b in per_query])
        return r

    @pytest.mark.asyncio
    async def test_merge_is_cut_back_to_one_window(self) -> None:
        a = [_chunk(f"a{i}") for i in range(3)]
        b = [_chunk(f"b{i}") for i in range(3)]
        p = _pipeline(
            router=_mock_router("complex"),
            decomposer=_mock_decomposer(["s1", "s2"]),
            retriever=self._subquery_retriever([a, b]),
            reranker=_reranker_keeping(["a0", "b0", "a1"]),
        )
        result = await p.run("two-part question")
        # Six distinct chunks retrieved, one window is three.
        assert len(result.retrieved_chunks) == 3
        assert [c.chunk_id for c in result.retrieved_chunks] == ["a0", "b0", "a1"]

    @pytest.mark.asyncio
    async def test_cut_is_scored_against_the_original_question(self) -> None:
        # Not against a sub-query: each sub-query's scores are relative to a
        # different question and cannot be interleaved as they stand.
        reranker = _reranker_keeping(["a0"])
        p = _pipeline(
            router=_mock_router("complex"),
            decomposer=_mock_decomposer(["sub one", "sub two"]),
            retriever=self._subquery_retriever(
                [[_chunk("a0"), _chunk("a1")], [_chunk("b0"), _chunk("b1")]]
            ),
            reranker=reranker,
        )
        await p.run("the original question")
        assert reranker.rerank.await_args.args[0] == "the original question"

    @pytest.mark.asyncio
    async def test_every_subquery_survives_the_cut_without_a_reranker(self) -> None:
        # Concatenating and truncating deleted the later sub-questions
        # outright; round-robin keeps each one's best chunks.
        a = [_chunk(f"a{i}") for i in range(4)]
        b = [_chunk(f"b{i}") for i in range(4)]
        c = [_chunk(f"c{i}") for i in range(4)]
        p = _pipeline(
            router=_mock_router("complex"),
            decomposer=_mock_decomposer(["s1", "s2", "s3"]),
            retriever=self._subquery_retriever([a, b, c]),
            reranker=None,
        )
        result = await p.run("three-part question")
        kept = [x.chunk_id for x in result.retrieved_chunks]
        assert len(kept) == 4
        assert {k[0] for k in kept} == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_single_query_is_untouched(self) -> None:
        chunks = [_chunk(f"c{i}") for i in range(5)]
        reranker = _reranker_keeping(["c0"])
        p = _pipeline(
            router=_mock_router("simple"),
            retriever=self._subquery_retriever([chunks]),
            reranker=reranker,
        )
        result = await p.run("simple question")
        assert [c.chunk_id for c in result.retrieved_chunks] == [c.chunk_id for c in chunks]
        reranker.rerank.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_overlapping_subqueries_below_the_window_are_not_reranked(self) -> None:
        # Heavy overlap already fits; paying for a rerank would buy nothing.
        shared = [_chunk("x0"), _chunk("x1"), _chunk("x2")]
        reranker = _reranker_keeping(["x0"])
        p = _pipeline(
            router=_mock_router("complex"),
            decomposer=_mock_decomposer(["s1", "s2"]),
            retriever=self._subquery_retriever([shared, list(shared)]),
            reranker=reranker,
        )
        result = await p.run("two-part question")
        assert len(result.retrieved_chunks) == 3
        reranker.rerank.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_evidence_marks_only_the_kept_chunks_selected(self) -> None:
        # The console's "selected" flag used to mark every merged chunk, which
        # after a cut would claim the generator saw chunks it never got.
        a = [_chunk(f"a{i}") for i in range(2)]
        b = [_chunk(f"b{i}") for i in range(2)]
        p = _pipeline(
            router=_mock_router("complex"),
            decomposer=_mock_decomposer(["s1", "s2"]),
            retriever=self._subquery_retriever([a, b]),
            reranker=_reranker_keeping(["a0", "b0"]),
        )
        result = await p.run("two-part question")
        kept = {c.chunk_id for c in result.retrieved_chunks}
        selected = {e.chunk.chunk_id for e in result.evidence if e.selected}
        assert selected == kept


class TestHyDEInThePipeline:
    """HyDE changes the text that reaches the retriever, and nothing else.

    The generator must still see the user's question and the retrieved
    chunks, never the invented passage — that separation is what makes a
    wrong hypothesis cost a worse search rather than a wrong answer.
    """

    @pytest.mark.asyncio
    async def test_off_by_default_the_retriever_sees_the_query(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        p = _pipeline(retriever=retriever)
        result = await p.run("what is a query parameter?")
        retriever.retrieve.assert_awaited_once_with("what is a query parameter?")
        assert result.hypotheses == []

    @pytest.mark.asyncio
    async def test_on_the_retriever_searches_with_the_passage(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        p = _pipeline(retriever=retriever, hyde=_mock_hyde())
        await p.run("what is a query parameter?")
        retriever.retrieve.assert_awaited_once_with(
            "PASSAGE about what is a query parameter?"
        )

    @pytest.mark.asyncio
    async def test_the_generator_still_sees_the_users_question(self) -> None:
        generator = _mock_generator()
        p = _pipeline(generator=generator, hyde=_mock_hyde())
        await p.run("what is a query parameter?")
        assert generator.generate.await_args.args[0] == "what is a query parameter?"

    @pytest.mark.asyncio
    async def test_every_sub_query_is_expanded(self) -> None:
        retriever = _mock_retriever([_chunk("c1")])
        p = _pipeline(
            router=_mock_router("complex"),
            decomposer=_mock_decomposer(["sub1", "sub2"]),
            retriever=retriever,
            hyde=_mock_hyde(),
        )
        result = await p.run("two-part question")
        searched = [c.args[0] for c in retriever.retrieve.await_args_list]
        assert searched == ["PASSAGE about sub1", "PASSAGE about sub2"]
        assert len(result.hypotheses) == 2

    @pytest.mark.asyncio
    async def test_a_grader_retry_expands_the_reformulation_too(self) -> None:
        # The retry exists because the first search missed. Handing the
        # second one unexpanded text would turn the feature off at the one
        # point it is most needed.
        retriever = _mock_retriever([_chunk("c1")])
        p = _pipeline(
            retriever=retriever,
            grader=_mock_grader([(False, 0.2, "reformulated"), (True, 0.9, "q")]),
            hyde=_mock_hyde(),
        )
        result = await p.run("original")
        searched = [c.args[0] for c in retriever.retrieve.await_args_list]
        assert searched == ["PASSAGE about original", "PASSAGE about reformulated"]
        assert result.hypotheses == [
            "PASSAGE about original",
            "PASSAGE about reformulated",
        ]

    @pytest.mark.asyncio
    async def test_hyde_time_is_not_charged_to_retrieval(self) -> None:
        p = _pipeline(hyde=_mock_hyde())
        result = await p.run("q")
        assert "hyde" in result.stage_ms
        assert result.stage_ms["retrieval"] >= 0.0

    @pytest.mark.asyncio
    async def test_no_hyde_stage_when_it_is_off(self) -> None:
        result = await _pipeline().run("q")
        assert "hyde" not in result.stage_ms

    @pytest.mark.asyncio
    async def test_a_failed_expansion_still_retrieves(self) -> None:
        # The expander degrades to the raw query on its own; the pipeline
        # must not add a second failure mode on top of that.
        from atlas.orchestration.hyde import Expansion

        hyde = MagicMock()
        hyde.expand = AsyncMock(
            side_effect=lambda qs: [Expansion(query=q, hypothesis="", text=q) for q in qs]
        )
        retriever = _mock_retriever([_chunk("c1")])
        p = _pipeline(retriever=retriever, hyde=hyde)
        result = await p.run("q")
        retriever.retrieve.assert_awaited_once_with("q")
        assert result.hypotheses == []
        assert result.answer == "The answer [1]."
