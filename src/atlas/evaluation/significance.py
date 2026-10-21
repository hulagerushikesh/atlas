"""
Exact Wilcoxon signed-rank test over paired per-sample scores.

Why this exists:
    `comparator` decided a winner by asking whether two run means differed by
    more than a measured noise floor. That answers "is this bigger than a
    rerun" and says nothing at all about "is this more than one sample". On
    2026-10-21 it reported `context_precision +0.0134` as a win for the
    router-scope arm. Fifteen rows were paired; fourteen scored identically
    and one moved, `fq-013` by +0.20. A verdict resting on a single row had
    cleared a floor honestly and been printed as a result.

    The reports have carried the per-sample scores since the first one was
    written, so the paired test was always available. The comparator's own
    docstring has said since v1 that "with larger datasets you'd use a proper
    significance test (Wilcoxon signed-rank, etc.)" — this is that test, and
    the dataset was never too small for it. It was too small for the test to
    *reject*, which is a different statement and the useful one.

Why the test is implemented here rather than called from scipy:
    BACKLOG recorded "scipy is already a dependency". It is not a declared
    one. It arrives transitively under `sentence-transformers`, so importing
    it from shipped package code would make the comparator depend on a
    reranker's private requirements — and the comparator is inside the image
    the API runs from. The test is a few dozen lines, it is exact rather than
    approximate at these sizes, and `tests/unit/evaluation/test_significance.py`
    checks it against `scipy.stats.wilcoxon` on tie-free input, where the two
    must agree to the last bit.

    Where magnitudes tie they deliberately do not agree. scipy's exact method
    is derived for distinct ranks and is approximate once ranks are shared;
    the enumeration here conditions on the observed rank vector, which is
    exact either way. Metric scores tie constantly — a metric that grades in
    quarters produces almost nothing but ties — so this is the common case,
    not the corner.

How the null distribution is counted:
    Under the null, each nonzero difference is equally likely to carry its
    sign or the opposite one, so the null distribution of W+ is the
    distribution of subset sums of the ranks. Enumerating all 2^n sign
    patterns is exact and costs 2^n; a subset-sum DP over the ranks is the
    same number and costs O(n * sum of ranks). Ranks are multiples of 0.5,
    so they are doubled into integers first. The DP is what runs: 0.15 ms at
    n=16, and still exact at n=200, where enumeration would not finish.

What underpowered means, and why it is not "not significant":
    With n nonzero pairs the most extreme outcome possible is every
    difference sharing a sign, which has two-sided p = 2^(1-n). Below six
    pairs that smallest achievable p is above 0.05, so the test cannot reject
    whatever the data does. Reporting that as "not significant" would state
    an absence of effect where the honest finding is an absence of evidence,
    and those two are the failure this whole module exists to stop. They are
    returned as different verdicts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

# Two-sided, and the conventional line. Nothing in this project needs it
# configurable yet; when something does, pass it rather than widening it.
DEFAULT_ALPHA = 0.05

Verdict = Literal["tested", "underpowered", "identical"]


@dataclass(frozen=True)
class SignedRankResult:
    """The outcome of one paired test, including the cases with no outcome."""

    verdict: Verdict
    # Pairs whose difference was not exactly zero. The test's denominator:
    # tied pairs carry no sign and are dropped, which is Wilcoxon's own
    # treatment of them.
    n_nonzero: int
    # Pairs compared, tied ones included. Printed because `n_nonzero` alone
    # cannot distinguish a small dataset from a large one that barely moved.
    n_pairs: int
    # None exactly when `verdict == "identical"`: with no signed difference
    # there is no statistic, and returning 1.0 would read as a test that ran.
    p_value: float | None
    statistic: float | None
    alpha: float

    @property
    def is_significant(self) -> bool:
        """True only when a test actually ran and rejected.

        An underpowered comparison is not significant, but it is also not
        evidence of no difference — read `verdict` before quoting this.
        """
        return self.verdict == "tested" and self.p_value is not None \
            and self.p_value < self.alpha

    def describe(self) -> str:
        """One clause, for a table cell or a note."""
        if self.verdict == "identical":
            return f"every one of {self.n_pairs} paired rows scored the same"
        if self.verdict == "underpowered":
            floor_p = 2.0 ** (1 - self.n_nonzero)
            return (
                f"only {self.n_nonzero} of {self.n_pairs} paired rows differ, "
                f"so the smallest p this test could return is {floor_p:.3f} — "
                f"it cannot reach {self.alpha:g} however they fell"
            )
        assert self.p_value is not None
        return (
            f"p={self.p_value:.4f} over {self.n_nonzero} differing of "
            f"{self.n_pairs} paired rows"
        )


def min_pairs_for(alpha: float = DEFAULT_ALPHA) -> int:
    """Fewest differing pairs at which the test could reject at *alpha*.

    The best case is unanimity: every difference the same sign, two-sided
    p = 2^(1-n). Below the n this returns, a significant result is
    arithmetically unreachable and a "not significant" verdict carries no
    information about the data.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    return max(1, math.ceil(1 - math.log2(alpha)))


def _average_ranks(values: list[float]) -> list[float]:
    """Ascending ranks, ties sharing the mean of the positions they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1  # positions are 1-based
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def _two_sided_p(doubled_ranks: list[int], w_plus_doubled: int) -> float:
    """Exact two-sided p by counting sign patterns at least as extreme.

    Counts subsets of the ranks whose sum puts them no closer to the centre
    than the observed W+, over all 2^n subsets. Ranks arrive doubled so that
    half-integer tied ranks stay exact integers and the DP indexes cleanly.
    """
    total = sum(doubled_ranks)
    observed = min(w_plus_doubled, total - w_plus_doubled)
    # counts[s] = how many sign patterns put W+ at s.
    counts = [0] * (total + 1)
    counts[0] = 1
    for rank in doubled_ranks:
        for s in range(total - rank, -1, -1):
            if counts[s]:
                counts[s + rank] += counts[s]
    extreme = sum(c for s, c in enumerate(counts) if min(s, total - s) <= observed)
    # `1 << n` rather than `2 ** n`: both are the same integer, but `**` is
    # typed as returning Any because a negative exponent would give a float.
    return extreme / (1 << len(doubled_ranks))


def signed_rank_test(
    pairs: list[tuple[float, float]],
    *,
    alpha: float = DEFAULT_ALPHA,
) -> SignedRankResult:
    """Exact two-sided Wilcoxon signed-rank test on (a, b) score pairs.

    Differences are taken as `b - a`, so this tests whether B's scores are
    drawn from the same distribution as A's — the same direction as the
    comparator's deltas.

    Pairs must already be matched by sample: this function cannot tell a
    mismatched zip from a real result, and a mismatched one looks like noise.
    """
    minimum = min_pairs_for(alpha)
    diffs = [b - a for a, b in pairs]
    nonzero = [d for d in diffs if d != 0.0]

    if not nonzero:
        return SignedRankResult(
            verdict="identical",
            n_nonzero=0,
            n_pairs=len(pairs),
            p_value=None,
            statistic=None,
            alpha=alpha,
        )

    ranks = _average_ranks([abs(d) for d in nonzero])
    # Ranks are integers or half-integers; doubling makes them exact ints and
    # avoids a float-keyed DP whose indices would drift.
    doubled = [round(2 * r) for r in ranks]
    w_plus_doubled = sum(r for d, r in zip(nonzero, doubled, strict=True) if d > 0)
    statistic = min(w_plus_doubled, sum(doubled) - w_plus_doubled) / 2

    if len(nonzero) < minimum:
        # Report the shape of the evidence and refuse the verdict. The p this
        # would return is real arithmetic but says nothing: it is bounded
        # below by 2^(1-n), which is already above alpha.
        return SignedRankResult(
            verdict="underpowered",
            n_nonzero=len(nonzero),
            n_pairs=len(pairs),
            p_value=_two_sided_p(doubled, w_plus_doubled),
            statistic=statistic,
            alpha=alpha,
        )

    return SignedRankResult(
        verdict="tested",
        n_nonzero=len(nonzero),
        n_pairs=len(pairs),
        p_value=_two_sided_p(doubled, w_plus_doubled),
        statistic=statistic,
        alpha=alpha,
    )
