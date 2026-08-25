"""The reference metric. Every other metric copies this shape, so this test does too."""

from decimal import Decimal

from hippo_pipeline.domain.models import Dataset, Pharmacy
from hippo_pipeline.metrics.pharmacy_ndc_summary import pharmacy_ndc_summary

from .conftest import claim

PHARMACIES = {"0123456789": Pharmacy(npi="0123456789", chain="saint")}


def run(claims):
    return pharmacy_ndc_summary(Dataset(claims=tuple(claims), reverts=(), pharmacies=PHARMACIES))


def test_completed_fills_produce_revenue_and_a_quantity_weighted_unit_price():
    rows = run(
        [
            claim("C1", price="20.00", quantity="10"),
            claim("C2", price="30.00", quantity="5"),
        ]
    )

    assert rows[0]["fills"] == 2
    assert rows[0]["revenue"] == Decimal("50.00")
    # sum(price)/sum(quantity) = 50/15, NOT mean(20/10, 30/5) = 4.0 (OQ-08, declared in
    # the metric's `measures`). The two differ materially on this data.
    assert rows[0]["avg_unit_price"] == Decimal("3.3333")


def test_a_reverted_claim_is_excluded_from_money_but_counted():
    from dataclasses import replace

    rows = run(
        [
            claim("C1", price="20.00", quantity="10"),
            replace(claim("C2", price="1000.00", quantity="1"), reverted=True),
        ]
    )

    assert rows[0]["fills"] == 1
    assert rows[0]["reverted"] == 1
    assert rows[0]["revenue"] == Decimal("20.00")
    assert rows[0]["avg_unit_price"] == Decimal("2.0000")


def test_a_group_with_only_reverted_fills_has_no_unit_price_rather_than_a_crash():
    from dataclasses import replace

    rows = run([replace(claim("C1"), reverted=True)])

    assert rows[0]["fills"] == 0
    assert rows[0]["revenue"] == Decimal("0.00")
    assert rows[0]["avg_unit_price"] is None


def test_rows_are_grouped_by_pharmacy_and_drug_and_sorted():
    rows = run(
        [
            claim("C1", ndc="99999999999"),
            claim("C2", ndc="00054027225"),
            claim("C3", ndc="00054027225"),
        ]
    )

    assert [r["ndc"] for r in rows] == ["00054027225", "99999999999"]
    assert [r["fills"] for r in rows] == [2, 1]


def test_the_chain_is_joined_from_the_reference_data():
    assert run([claim("C1")])[0]["chain"] == "saint"


def test_an_unknown_pharmacy_yields_an_empty_chain_rather_than_failing():
    """Cannot happen after ingest filtering, but a metric must not depend on that."""
    assert run([claim("C1", npi="9999999999")])[0]["chain"] == ""
