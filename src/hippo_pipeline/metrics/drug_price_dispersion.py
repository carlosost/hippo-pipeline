"""Where prices are out of line - the spread of unit price within one drug."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal

from hippo_pipeline.domain.models import Dataset
from hippo_pipeline.metrics._stats import percentile
from hippo_pipeline.metrics.registry import metric

UNIT_PRICE = Decimal("0.0001")
RATIO = Decimal("0.0001")

P25 = Decimal("0.25")
P50 = Decimal("0.50")
P75 = Decimal("0.75")


@metric(
    name="drug_price_dispersion",
    question=(
        "Where are prices out of line? For each drug, how widely does the unit price vary "
        "across the fills we paid for?"
    ),
    grain=("ndc",),
    columns=(
        "ndc",
        "fills",
        "min_unit_price",
        "p25_unit_price",
        "median_unit_price",
        "p75_unit_price",
        "max_unit_price",
        "max_over_min",
    ),
    measures={
        "fills": "completed fills only; a reverted fill is a price nobody paid (ADR-015)",
        "min_unit_price": "price / quantity per fill, then the minimum",
        "p25_unit_price": "nearest-rank 25th percentile: sorted values at index floor(n*0.25)",
        "median_unit_price": (
            "nearest-rank 50th percentile. On the sample dataset this is the column that "
            "carries signal - medians fall into three bands while min and max are identical "
            "for all ten drugs"
        ),
        "p75_unit_price": "nearest-rank 75th percentile",
        "max_over_min": (
            "max_unit_price / min_unit_price. Kept because it matters on real data, but on "
            "the sample it is exactly 2948.6667 for every drug and so distinguishes nothing"
        ),
    },
)
def drug_price_dispersion(data: Dataset) -> Sequence[Mapping[str, object]]:
    """Unit-price quantiles per drug, over completed fills."""
    by_ndc: dict[str, list[Decimal]] = {}

    for claim in data.claims:
        if claim.reverted or claim.quantity <= 0:
            continue
        by_ndc.setdefault(claim.ndc, []).append(claim.price / claim.quantity)

    rows: list[Mapping[str, object]] = []
    for ndc, prices in sorted(by_ndc.items()):
        prices.sort()
        low, high = prices[0], prices[-1]
        rows.append(
            {
                "ndc": ndc,
                "fills": len(prices),
                "min_unit_price": low.quantize(UNIT_PRICE, ROUND_HALF_UP),
                "p25_unit_price": _q(percentile(prices, P25)),
                "median_unit_price": _q(percentile(prices, P50)),
                "p75_unit_price": _q(percentile(prices, P75)),
                "max_unit_price": high.quantize(UNIT_PRICE, ROUND_HALF_UP),
                "max_over_min": (high / low).quantize(RATIO, ROUND_HALF_UP) if low > 0 else None,
            }
        )
    return rows


def _q(value: Decimal | None) -> Decimal | None:
    return value.quantize(UNIT_PRICE, ROUND_HALF_UP) if value is not None else None
