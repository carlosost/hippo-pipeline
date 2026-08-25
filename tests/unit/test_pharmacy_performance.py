"""ADR-016: rank by the bound, not the rate."""

from dataclasses import replace
from decimal import Decimal

from hippo_pipeline.domain.models import Dataset, Pharmacy
from hippo_pipeline.metrics.pharmacy_performance import pharmacy_performance

from .conftest import claim

PHARMACIES = {
    "0123456789": Pharmacy(npi="0123456789", chain="saint"),
    "3333333333": Pharmacy(npi="3333333333", chain="health"),
}


def run(claims):
    return pharmacy_performance(Dataset(claims=tuple(claims), reverts=(), pharmacies=PHARMACIES))


def test_volume_revenue_and_reversal_rate_per_pharmacy():
    rows = run(
        [
            claim("C1", price="10.00"),
            claim("C2", price="30.00"),
            replace(claim("C3", price="99.00"), reverted=True),
        ]
    )

    assert rows[0]["claims"] == 3
    assert rows[0]["fills"] == 2
    assert rows[0]["reverted"] == 1
    assert rows[0]["reversal_rate"] == Decimal("0.333333")
    assert rows[0]["revenue"] == Decimal("40.00")


def test_a_reverted_fill_leaves_revenue_but_stays_in_the_claim_count():
    rows = run([replace(claim("C1", price="99.00"), reverted=True)])

    assert rows[0]["claims"] == 1
    assert rows[0]["fills"] == 0
    assert rows[0]["revenue"] == Decimal("0.00")


def test_the_lower_bound_is_always_below_the_raw_rate():
    rows = run([claim("C1"), replace(claim("C2"), reverted=True)])

    assert rows[0]["reversal_rate_lower_95"] < rows[0]["reversal_rate"]


def test_distinct_drugs_counts_reverted_fills_too():
    """The pharmacy dispensed it; the patient not collecting does not change the range."""
    rows = run(
        [
            claim("C1", ndc="00054027225"),
            claim("C2", ndc="00054027225"),
            replace(claim("C3", ndc="99999999999"), reverted=True),
        ]
    )

    assert rows[0]["distinct_drugs"] == 2


def test_rows_are_one_per_pharmacy_sorted_by_npi():
    rows = run([claim("C1", npi="3333333333"), claim("C2", npi="0123456789")])

    assert [r["npi"] for r in rows] == ["0123456789", "3333333333"]
    assert [r["chain"] for r in rows] == ["saint", "health"]
