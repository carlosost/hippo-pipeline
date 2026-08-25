"""Fills, revenue and unit price per pharmacy and drug.

The reference example of ADR-008's contract: one module, one declaration, one pure
function over `Dataset`, and a matching unit test. Every other metric copies this shape.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from hippo_pipeline.domain.models import Dataset
from hippo_pipeline.metrics.registry import metric

CENTS = Decimal("0.01")
UNIT_PRICE_PRECISION = Decimal("0.0001")


@dataclass
class _Bucket:
    fills: int = 0
    reverted: int = 0
    revenue: Decimal = field(default_factory=lambda: Decimal(0))
    quantity: Decimal = field(default_factory=lambda: Decimal(0))


@metric(
    name="pharmacy_ndc_summary",
    question=(
        "For each pharmacy and drug: how many fills completed, how many were reverted, "
        "what revenue did the completed fills produce, and at what average unit price?"
    ),
    grain=("npi", "ndc"),
    columns=("npi", "chain", "ndc", "fills", "reverted", "revenue", "avg_unit_price"),
    measures={
        "fills": "count of claims that were not reverted",
        "reverted": "count of claims that were reverted; a reverted fill is treated as "
        "though it never happened for revenue and volume (ADR-012)",
        "revenue": "sum(price) over completed fills only, exact Decimal",
        "avg_unit_price": "sum(price) / sum(quantity) over completed fills only - "
        "quantity-weighted, so it answers 'what was actually paid per unit', not "
        "'what did the average fill charge'. Null when no completed fill has quantity",
    },
)
def pharmacy_ndc_summary(data: Dataset) -> Sequence[Mapping[str, object]]:
    """Aggregate completed and reverted fills at the (pharmacy, drug) grain."""
    buckets: dict[tuple[str, str], _Bucket] = {}

    for claim in data.claims:
        bucket = buckets.setdefault((claim.npi, claim.ndc), _Bucket())
        if claim.reverted:
            bucket.reverted += 1
            continue
        bucket.fills += 1
        bucket.revenue += claim.price
        bucket.quantity += claim.quantity

    rows: list[Mapping[str, object]] = []
    # Sorted, so two runs over identical inputs produce identical bytes (charter 1.3.4).
    for (npi, ndc), bucket in sorted(buckets.items()):
        pharmacy = data.pharmacies.get(npi)
        unit_price = (
            (bucket.revenue / bucket.quantity).quantize(UNIT_PRICE_PRECISION, ROUND_HALF_UP)
            if bucket.quantity > 0
            else None
        )
        rows.append(
            {
                "npi": npi,
                "chain": pharmacy.chain if pharmacy else "",
                "ndc": ndc,
                "fills": bucket.fills,
                "reverted": bucket.reverted,
                "revenue": bucket.revenue.quantize(CENTS, ROUND_HALF_UP),
                "avg_unit_price": unit_price,
            }
        )
    return rows
