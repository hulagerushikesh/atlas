"""The paired signed-rank test, and the two non-answers it can give.

The arithmetic is checked against `scipy.stats.wilcoxon` rather than against
hand-computed p-values, because a hand-computed expectation written by the
same person who wrote the implementation tests that they are consistent, not
that either is right. scipy is an independent implementation of the same
published test.

It is checked only on tie-free magnitudes. scipy's exact method is derived
for distinct ranks; ours conditions on the observed rank vector and stays
exact when ranks are shared. Where they disagree it is because scipy is
approximating and says so, so forcing agreement there would be copying a
known limitation rather than finding a bug.
"""

from __future__ import annotations

import random

import pytest

from atlas.evaluation.significance import (
    DEFAULT_ALPHA,
    min_pairs_for,
    signed_rank_test,
)


def _pairs(diffs: list[float]) -> list[tuple[float, float]]:
    """Score pairs with the given b - a differences, from a 0.5 baseline."""
    return [(0.5, 0.5 + d) for d in diffs]


class TestTheExactTestAgreesWithAnIndependentImplementation:
    """Our p-values are scipy's p-values, to the last bit, where both are exact."""

    def test_two_thousand_tie_free_samples_match_scipy_exactly(self) -> None:
        # Imported here, not at module scope. A module-level importorskip
        # would skip this file's other twelve tests along with the oracle,
        # and a suite that goes quiet when a dependency is missing is the
        # failure mode this project keeps finding in its own measurements.
        # scipy is in the dev extra, so a skip here means that broke.
        scipy_stats = pytest.importorskip("scipy.stats")
        rng = random.Random(11)
        magnitudes = [0.1 * i for i in range(1, 40)]
        for _ in range(2000):
            n = rng.randint(min_pairs_for(DEFAULT_ALPHA), 11)
            diffs = [m * rng.choice([-1, 1]) for m in rng.sample(magnitudes, n)]
            ours = signed_rank_test(_pairs(diffs))
            theirs = scipy_stats.wilcoxon(
                diffs, zero_method="wilcox", alternative="two-sided", method="exact"
            )
            assert ours.p_value == pytest.approx(theirs.pvalue, abs=1e-12), diffs
            assert ours.statistic == pytest.approx(theirs.statistic), diffs

    def test_tied_magnitudes_are_ranked_as_their_shared_average(self) -> None:
        # |d| = 1, 1, 2, 2, 3, 3 -> ranks 1.5, 1.5, 3.5, 3.5, 5.5, 5.5.
        # All six positive, so W+ is the whole rank sum and W- is 0; the only
        # two sign patterns that extreme are all-up and all-down, out of 2^6.
        result = signed_rank_test(_pairs([1, 1, 2, 2, 3, 3]))
        assert result.verdict == "tested"
        assert result.statistic == 0.0
        assert result.p_value == pytest.approx(2 / 64)

    def test_a_unanimous_difference_is_the_most_extreme_p_available(self) -> None:
        n = 8
        result = signed_rank_test(_pairs([0.1 * (i + 1) for i in range(n)]))
        assert result.p_value == pytest.approx(2.0 ** (1 - n))
        assert result.is_significant


class TestTheTestSeparatesNoEvidenceFromEvidenceOfNoDifference:
    """The distinction the noise floors could not make, and the reason for this module."""

    def test_one_differing_row_is_underpowered_not_a_tie(self) -> None:
        # The 2026-10-21 case in miniature: context_precision moved on
        # fq-013 and on nothing else, and the floor called it a win.
        result = signed_rank_test(_pairs([0.0] * 14 + [0.2]))
        assert result.verdict == "underpowered"
        assert result.n_nonzero == 1
        assert result.n_pairs == 15
        assert not result.is_significant

    def test_an_underpowered_result_still_reports_what_it_saw(self) -> None:
        result = signed_rank_test(_pairs([0.0] * 14 + [0.2]))
        # Not None. The count is the finding — a reader has to be able to
        # see it was one row, which is the fact the old verdict hid.
        assert result.p_value is not None
        assert "1 of 15 paired rows differ" in result.describe()

    def test_identical_rows_are_their_own_verdict_with_no_p_value(self) -> None:
        result = signed_rank_test(_pairs([0.0] * 15))
        assert result.verdict == "identical"
        # A p of 1.0 would read as a test that ran and found nothing. No
        # test ran: there was no signed difference to rank.
        assert result.p_value is None
        assert result.statistic is None
        assert not result.is_significant

    def test_the_power_threshold_is_where_the_smallest_p_reaches_alpha(self) -> None:
        minimum = min_pairs_for(DEFAULT_ALPHA)
        assert 2.0 ** (1 - minimum) <= DEFAULT_ALPHA
        assert 2.0 ** (1 - (minimum - 1)) > DEFAULT_ALPHA

    def test_just_under_the_threshold_cannot_reject_however_the_rows_fall(self) -> None:
        n = min_pairs_for(DEFAULT_ALPHA) - 1
        # Every difference the same sign and distinct: the strongest evidence
        # n rows can carry. Still not enough.
        result = signed_rank_test(_pairs([0.1 * (i + 1) for i in range(n)]))
        assert result.verdict == "underpowered"
        assert result.p_value is not None
        assert result.p_value > DEFAULT_ALPHA

    def test_one_more_row_of_the_same_evidence_does_reject(self) -> None:
        n = min_pairs_for(DEFAULT_ALPHA)
        result = signed_rank_test(_pairs([0.1 * (i + 1) for i in range(n)]))
        assert result.verdict == "tested"
        assert result.is_significant


class TestTheTestIsNotFooledByTheShapeOfTheInput:
    def test_direction_follows_b_minus_a(self) -> None:
        up = signed_rank_test([(0.2, 0.9)] * 3 + [(0.1, 0.8), (0.3, 0.7), (0.0, 0.6)])
        down = signed_rank_test([(0.9, 0.2)] * 3 + [(0.8, 0.1), (0.7, 0.3), (0.6, 0.0)])
        # The test is two-sided, so the p is the same either way; what must
        # not happen is one of them silently reading as no difference.
        assert up.p_value == down.p_value
        assert up.verdict == down.verdict == "tested"

    def test_zero_differences_are_dropped_not_counted_as_agreement(self) -> None:
        # Wilcoxon's own treatment: a tied pair carries no sign. Six real
        # differences reject whether or not fifty ties sit beside them.
        bare = signed_rank_test(_pairs([0.1, 0.2, 0.3, 0.4, 0.5, 0.6]))
        padded = signed_rank_test(_pairs([0.1, 0.2, 0.3, 0.4, 0.5, 0.6] + [0.0] * 50))
        assert bare.p_value == padded.p_value
        assert padded.n_pairs == 56
        assert padded.n_nonzero == 6

    def test_an_empty_comparison_is_identical_rather_than_an_error(self) -> None:
        result = signed_rank_test([])
        assert result.verdict == "identical"
        assert result.n_pairs == 0

    def test_alpha_outside_zero_to_one_is_refused(self) -> None:
        for bad in (0.0, 1.0, -0.1, 2.0):
            with pytest.raises(ValueError, match="alpha must be in"):
                min_pairs_for(bad)


class TestEachVerdictSaysWhichOneItIs:
    """`describe()` is what reaches a reader, so each state needs its own words."""

    def test_identical_names_the_row_count_it_agreed_over(self) -> None:
        assert signed_rank_test(_pairs([0.0] * 12)).describe() == (
            "every one of 12 paired rows scored the same"
        )

    def test_underpowered_quotes_the_p_it_could_never_beat(self) -> None:
        described = signed_rank_test(_pairs([0.0] * 12 + [0.3, -0.1])).describe()
        assert "only 2 of 14 paired rows differ" in described
        assert "smallest p this test could return is 0.500" in described

    def test_tested_quotes_the_p_it_got(self) -> None:
        described = signed_rank_test(_pairs([0.1 * (i + 1) for i in range(8)])).describe()
        assert "p=0.0078" in described
        assert "8 differing of 8 paired rows" in described
