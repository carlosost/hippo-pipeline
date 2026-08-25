"""ADR-015: quantity-weighted, because a PBM negotiates price per unit dispensed."""

from dataclasses import replace
from decimal import Decimal

from hippo_pipeline.domain.models import Dataset, Pharmacy
from hippo_pipeline.metrics.chain_ndc_price_rank import chain_ndc_price_rank

from .conftest import claim

PHARMACIES = {
    "1111111111": Pharmacy(npi="1111111111", chain="saint"),
    "2222222222": Pharmacy(npi="2222222222", chain="health"),
    "3333333333": Pharmacy(npi="3333333333", chain="doctor"),
}


def run(claims):
    return chain_ndc_price_rank(Dataset(claims=tuple(claims), reverts=(), pharmacies=PHARMACIES))


def test_rank_one_is_the_cheapest_chain_for_that_drug():
    rows = run(
        [
            claim("C1", npi="1111111111", price="100.00", quantity="10"),  # 10.00/unit
            claim("C2", npi="2222222222", price="100.00", quantity="20"),  # 5.00/unit
            claim("C3", npi="3333333333", price="100.00", quantity="4"),  # 25.00/unit
        ]
    )

    assert [(r["chain"], r["price_rank"]) for r in rows] == [
        ("health", 1),
        ("saint", 2),
        ("doctor", 3),
    ]


def test_the_unit_price_is_quantity_weighted_not_a_mean_of_ratios():
    """sum(100+100)/sum(1+100) = 1.9802, not mean(100.0, 1.0) = 50.5 (ADR-015)."""
    rows = run(
        [
            claim("C1", npi="1111111111", price="100.00", quantity="1"),
            claim("C2", npi="1111111111", price="100.00", quantity="100"),
        ]
    )

    assert rows[0]["avg_unit_price"] == Decimal("1.9802")


def test_reverted_fills_are_excluded():
    rows = run(
        [
            claim("C1", npi="1111111111", price="10.00", quantity="1"),
            replace(claim("C2", npi="1111111111", price="9999.00", quantity="1"), reverted=True),
        ]
    )

    assert rows[0]["fills"] == 1
    assert rows[0]["avg_unit_price"] == Decimal("10.0000")


def test_ties_break_on_chain_name_so_the_ranking_is_reproducible():
    rows = run(
        [
            claim("C1", npi="1111111111", price="10.00", quantity="1"),  # saint
            claim("C2", npi="2222222222", price="10.00", quantity="1"),  # health
        ]
    )

    assert [(r["chain"], r["price_rank"]) for r in rows] == [("health", 1), ("saint", 2)]


def test_ranking_is_per_drug_not_global():
    rows = run(
        [
            claim("C1", npi="1111111111", ndc="AAA", price="100.00", quantity="1"),
            claim("C2", npi="2222222222", ndc="BBB", price="1.00", quantity="1"),
        ]
    )

    assert all(r["price_rank"] == 1 for r in rows)
    assert [r["ndc"] for r in rows] == ["AAA", "BBB"]
