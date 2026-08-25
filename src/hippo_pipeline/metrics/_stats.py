"""Small statistical helpers shared by metrics.

Underscore-prefixed so `discover()` skips it: it registers nothing.

Everything here is `Decimal`. `math.sqrt` would be simpler and would put a float in the
middle of a number the pipeline promises to reproduce byte for byte across machines
(charter 1.3.4). `Decimal.sqrt()` is exact to the context precision and platform
independent.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

RATE_PRECISION = Decimal("0.000001")

# 95% two-sided normal quantile. Written out rather than computed: it is a constant, and a
# constant with a name is easier to audit than a call to an inverse CDF.
Z_95 = Decimal("1.959964")


def percentile(values: Sequence[Decimal], q: Decimal) -> Decimal | None:
    """Nearest-rank percentile: the value at index floor(n * q) of the sorted input.

    The method is stated because percentile definitions differ, and a p75 computed one way
    is not comparable to a p75 computed another (ADR-015). Callers pass sorted values.
    """
    if not values:
        return None
    index = int(len(values) * q)
    return values[min(index, len(values) - 1)]


def wilson_lower_bound(successes: int, trials: int) -> Decimal | None:
    """Lower bound of the Wilson score interval at 95%.

    Why this rather than the raw proportion: with unequal denominators the raw rate ranks
    a pharmacy with 1 reversal in 10 fills above one with 40 in 1,000. The lower bound
    answers "what is the smallest rate consistent with this evidence", which is the
    question a business team ranking underperformers is actually asking (ADR-016).

    Returns None for zero trials - a rate with no denominator is not zero, it is unknown.
    """
    if trials <= 0:
        return None

    n = Decimal(trials)
    p = Decimal(successes) / n
    z2 = Z_95 * Z_95

    denominator = Decimal(1) + z2 / n
    centre = p + z2 / (2 * n)
    margin = Z_95 * (p * (Decimal(1) - p) / n + z2 / (4 * n * n)).sqrt()
    lower = (centre - margin) / denominator

    return max(Decimal(0), lower).quantize(RATE_PRECISION, ROUND_HALF_UP)


def rate(numerator: int, denominator: int) -> Decimal | None:
    """A proportion, rounded so it is stable across runs. None when there is no denominator."""
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(RATE_PRECISION, ROUND_HALF_UP)
