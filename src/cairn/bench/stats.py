"""Statistics for benchmark reports (spec §11 E2 rigor), in pure Python.

- `bootstrap_ci`: percentile bootstrap of the mean, seeded so a report is reproducible.
- `wilcoxon`: two-sided paired Wilcoxon signed-rank test. Zero differences are dropped and tied
  magnitudes share their average rank. For n <= 25 the p-value is exact (the permutation
  distribution of the observed ranks, ties included); above that the normal approximation with
  continuity and tie corrections is used.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

EXACT_MAX_N = 25
BOOTSTRAP_RESAMPLES = 5000


@dataclass(frozen=True)
class WilcoxonResult:
    n: int  # pairs with a non-zero difference
    w_plus: float
    w_minus: float
    p_value: float


def bootstrap_ci(
    values: Sequence[float],
    *,
    alpha: float = 0.05,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = 0,
) -> tuple[float, float]:
    """(low, high) of the mean's (1 - alpha) percentile interval; NaNs when there's no data."""
    if not values:
        return math.nan, math.nan
    rng = random.Random(seed)
    data = list(values)
    size = len(data)
    means = sorted(fmean(rng.choices(data, k=size)) for _ in range(resamples))
    low = means[int(math.floor(alpha / 2 * (resamples - 1)))]
    high = means[int(math.ceil((1 - alpha / 2) * (resamples - 1)))]
    return low, high


def wilcoxon(x: Sequence[float], y: Sequence[float]) -> WilcoxonResult:
    if len(x) != len(y):
        raise ValueError("wilcoxon needs paired samples of equal length")
    diffs = [a - b for a, b in zip(x, y, strict=True) if a - b != 0]
    n = len(diffs)
    if n == 0:
        return WilcoxonResult(0, 0.0, 0.0, 1.0)
    ranks = _average_ranks([abs(d) for d in diffs])
    w_plus = sum(r for r, d in zip(ranks, diffs, strict=True) if d > 0)
    w_minus = sum(r for r, d in zip(ranks, diffs, strict=True) if d < 0)
    statistic = min(w_plus, w_minus)
    p = _exact_p(ranks, statistic) if n <= EXACT_MAX_N else _normal_p(ranks, statistic)
    return WilcoxonResult(n, w_plus, w_minus, min(1.0, p))


def _average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and values[order[end + 1]] == values[order[start]]:
            end += 1
        rank = (start + end) / 2 + 1  # positions start..end share the average 1-based rank
        for k in range(start, end + 1):
            ranks[order[k]] = rank
        start = end + 1
    return ranks


def _exact_p(ranks: Sequence[float], statistic: float) -> float:
    """Two-sided P(T <= statistic) under the null, counting all 2^n sign assignments."""
    doubled = [round(r * 2) for r in ranks]  # average ranks are whole or half: double them
    total = sum(doubled)
    counts = [0] * (total + 1)
    counts[0] = 1
    for weight in doubled:
        for s in range(total, weight - 1, -1):
            counts[s] += counts[s - weight]
    limit = round(statistic * 2)
    tail = sum(counts[: limit + 1])
    return 2 * tail / (2 ** len(ranks))


def _normal_p(ranks: Sequence[float], statistic: float) -> float:
    n = len(ranks)
    mean = n * (n + 1) / 4
    tie_groups: dict[float, int] = {}
    for r in ranks:
        tie_groups[r] = tie_groups.get(r, 0) + 1
    tie_term = sum(t**3 - t for t in tie_groups.values()) / 48
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24 - tie_term)
    if sd == 0:
        return 1.0
    z = (statistic - mean + 0.5) / sd  # continuity correction toward the mean
    return 2 * _phi(z)


def _phi(z: float) -> float:
    return 0.5 * math.erfc(-z / math.sqrt(2))
