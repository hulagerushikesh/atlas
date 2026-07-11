"""
Reciprocal Rank Fusion (RRF) for combining dense and sparse retrieval results.

Design rationale:
    RRF was chosen over score-based fusion (linear combination, CombSUM) for
    two reasons:

    1. Score incompatibility: dense scores are cosine similarities ∈ [-1, 1];
       BM25 scores are unbounded term-frequency sums. Normalising both to [0, 1]
       requires knowing the corpus-wide min/max, which changes with every index
       update. RRF uses only rank position — immune to score scale differences.

    2. Robustness: empirical results (Cormack et al., 2009) show RRF matches or
       beats more complex fusion methods across a wide range of IR tasks without
       any tuning. The only hyperparameter, k (default 60), smooths rank
       differences; changing it rarely moves the needle.

    Formula per document d across retrievers R:
        RRF(d) = Σ_{r ∈ R} 1 / (k + rank_r(d))

    where rank_r(d) is 1-indexed position of d in retriever r's result list.
    Documents not retrieved by a retriever contribute 0 to the sum (absent from
    that retriever's list).

    The fused list is re-sorted by RRF score descending and truncated to
    *top_k* before being passed to the reranker.
"""

from __future__ import annotations

from atlas.interfaces.retriever import RetrievalResult, RetrievedChunk

_DEFAULT_K = 60


def reciprocal_rank_fusion(
    results: list[RetrievalResult],
    top_k: int,
    k: int = _DEFAULT_K,
) -> list[RetrievedChunk]:
    """
    Fuse multiple ranked lists into a single list via RRF.

    Args:
        results:  One RetrievalResult per retriever (order doesn't matter).
        top_k:    Maximum number of chunks to return.
        k:        RRF smoothing constant (60 is the standard default).

    Returns:
        Merged list sorted by RRF score descending, length ≤ top_k.
    """
    rrf_scores: dict[str, float] = {}
    # Keep the first-seen RetrievedChunk object for each chunk_id
    chunk_store: dict[str, RetrievedChunk] = {}

    for result in results:
        for rank, chunk in enumerate(result.chunks, start=1):
            cid = chunk.chunk_id
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank)
            if cid not in chunk_store:
                chunk_store[cid] = chunk

    # Sort by RRF score descending; break ties by chunk_id for determinism
    ranked_ids = sorted(rrf_scores, key=lambda cid: (-rrf_scores[cid], cid))

    fused: list[RetrievedChunk] = []
    for cid in ranked_ids[:top_k]:
        chunk = chunk_store[cid].model_copy()
        chunk.score = rrf_scores[cid]  # overwrite retriever score with RRF score
        fused.append(chunk)

    return fused
