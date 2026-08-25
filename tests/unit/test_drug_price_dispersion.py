"""ADR-016: lead with the quantiles, keep min/max because real data needs them."""

from dataclasses import replace
from decimal import Decimal

from hippo_pipeline.domain.models import Dataset
from hippo_pipeline.metrics.drug_price_dispersion import drug_price_dispersion

from .conftest import claim


def run(claims):
    return drug_price_dispersion(Dataset(claims=tuple(claims), reverts=(), pharmacies={}))


def prices(*unit_prices):
    return [claim(f"C{i}", price=str(p), quantity="1") for i, p in enumerate(unit_prices)]


def test_quantiles_use_nearest_rank_on_the_sorted_unit_prices():
    rows = run(prices(1, 2, 3, 4, 5, 6, 7, 8))

    assert rows[0]["fills"] == 8
    assert rows[0]["min_unit_price"] == Decimal("1.0000")
    assert rows[0]["p25_unit_price"] == Decimal("3.0000")
    assert rows[0]["median_unit_price"] == Decimal("5.0000")
    assert rows[0]["p75_unit_price"] == Decimal("7.0000")
    assert rows[0]["max_unit_price"] == Decimal("8.0000")


def test_unit_price_is_price_over_quantity_not_price():
    rows = run([claim("C1", price="100.00", quantity="10")])

    assert rows[0]["median_unit_price"] == Decimal("10.0000")


def test_the_spread_ratio_is_max_over_min():
    rows = run(prices(2, 4, 8))

    assert rows[0]["max_over_min"] == Decimal("4.0000")


def test_reverted_fills_are_excluded_because_nobody_paid_that_price():
    rows = run(
        [
            claim("C1", price="10.00", quantity="1"),
            replace(claim("C2", price="9999.00", quantity="1"), reverted=True),
        ]
    )

    assert rows[0]["fills"] == 1
    assert rows[0]["max_unit_price"] == Decimal("10.0000")


def test_a_drug_with_no_completed_fill_does_not_appear_rather_than_dividing_by_zero():
    rows = run([replace(claim("C1"), reverted=True)])

    assert rows == []


def test_rows_are_one_per_drug_sorted_by_ndc():
    rows = run([claim("C1", ndc="99999999999"), claim("C2", ndc="00054027225")])

    assert [r["ndc"] for r in rows] == ["00054027225", "99999999999"]
