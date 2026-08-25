"""The statistical helpers. Small enough to check by hand, which is the point."""

from decimal import Decimal

from hippo_pipeline.metrics._stats import percentile, rate, wilson_lower_bound

VALUES = [Decimal(str(v)) for v in (1, 2, 3, 4, 5, 6, 7, 8)]


def test_percentile_is_nearest_rank_at_floor_n_times_q():
    """Stated because percentile definitions differ and are not interchangeable."""
    assert percentile(VALUES, Decimal("0.25")) == Decimal("3")  # index floor(8*0.25) = 2
    assert percentile(VALUES, Decimal("0.50")) == Decimal("5")  # index 4
    assert percentile(VALUES, Decimal("0.75")) == Decimal("7")  # index 6


def test_percentile_of_the_top_never_runs_off_the_end():
    assert percentile(VALUES, Decimal("1.0")) == Decimal("8")


def test_percentile_of_nothing_is_none_not_zero():
    assert percentile([], Decimal("0.5")) is None


def test_a_rate_with_no_denominator_is_unknown_not_zero():
    assert rate(0, 0) is None
    assert rate(3, 0) is None


def test_a_rate_is_rounded_so_it_is_stable_across_runs():
    assert rate(1, 3) == Decimal("0.333333")


def test_the_wilson_bound_is_below_the_raw_rate():
    bound = wilson_lower_bound(20, 1236)
    raw = rate(20, 1236)

    assert bound is not None and raw is not None
    assert bound < raw


def test_the_wilson_bound_punishes_a_small_sample_much_harder():
    """The whole reason the column exists: 1-in-10 must not outrank 40-in-1000."""
    small = wilson_lower_bound(1, 10)  # raw rate 0.10
    large = wilson_lower_bound(40, 1000)  # raw rate 0.04
    small_rate = rate(1, 10)
    large_rate = rate(40, 1000)

    assert None not in (small, large, small_rate, large_rate)
    assert small_rate > large_rate  # type: ignore[operator]
    assert small < large  # type: ignore[operator]


def test_the_wilson_bound_of_zero_successes_is_zero_not_negative():
    assert wilson_lower_bound(0, 100) == Decimal("0")


def test_the_wilson_bound_with_no_trials_is_unknown():
    assert wilson_lower_bound(0, 0) is None


def test_the_wilson_bound_is_exact_decimal_not_float():
    assert isinstance(wilson_lower_bound(20, 1236), Decimal)
