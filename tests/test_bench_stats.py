"""Phase 4 Task 6: bootstrap CIs and the paired Wilcoxon signed-rank test (spec §11 E2 rigor)."""

import math

import pytest

from cairn.bench.stats import bootstrap_ci, wilcoxon


def test_all_positive_differences_exact() -> None:
    # W- = 0 of 2^5 sign patterns: p = 2 * 1/32
    result = wilcoxon([2, 3, 4, 5, 6], [1, 1, 1, 1, 1])
    assert result.n == 5 and result.w_minus == 0 and result.p_value == pytest.approx(0.0625)


def test_one_negative_difference_exact() -> None:
    # diffs 1,-2,3,4,5: W- = 2; subsets of {1..5} summing to <= 2: {}, {1}, {2} -> p = 2 * 3/32
    result = wilcoxon([1, -2, 3, 4, 5], [0, 0, 0, 0, 0])
    assert result.w_minus == 2 and result.p_value == pytest.approx(0.1875)


def test_zero_differences_are_dropped_and_ties_share_ranks() -> None:
    # diffs 0, 1, 1, -1, 2: drop 0; |1| x3 share rank 2, |2| rank 4: W+ = 8, W- = 2.
    # Doubled ranks {4,4,4,8}: subsets with sum <= 4 are {}, and each single 4 -> p = 2 * 4/16
    result = wilcoxon([0, 1, 1, -1, 2], [0, 0, 0, 0, 0])
    assert result.n == 4 and result.w_plus == 8 and result.w_minus == 2
    assert result.p_value == pytest.approx(0.5)


def test_no_differences_mean_no_evidence() -> None:
    result = wilcoxon([1, 2, 3], [1, 2, 3])
    assert result.n == 0 and result.p_value == 1.0


def test_large_samples_use_the_normal_approximation() -> None:
    result = wilcoxon([i + 1 for i in range(30)], [0] * 30)
    # z = (0 - 232.5 + 0.5) / sqrt(30*31*61/24) ~ -4.77
    assert result.n == 30 and result.p_value < 1e-5 and result.p_value > 1e-7


def test_lengths_must_match() -> None:
    with pytest.raises(ValueError):
        wilcoxon([1, 2], [1])


def test_bootstrap_ci_is_seeded_and_brackets_the_mean() -> None:
    values = [0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    low, high = bootstrap_ci(values, seed=7)
    assert (low, high) == bootstrap_ci(values, seed=7)
    assert low <= sum(values) / len(values) <= high and 0.0 <= low < high <= 1.0


def test_bootstrap_ci_of_a_constant_is_that_constant() -> None:
    assert bootstrap_ci([0.25] * 8) == (0.25, 0.25)


def test_bootstrap_ci_of_nothing_is_nan() -> None:
    low, high = bootstrap_ci([])
    assert math.isnan(low) and math.isnan(high)
