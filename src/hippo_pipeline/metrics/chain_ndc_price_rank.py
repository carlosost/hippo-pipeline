"""Which chain is cheapest for a given drug - the PBM's core job."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from hippo_pipeline.domain.models import Dataset
from hippo_pipeline.metrics.registry import metric

UNIT_PRICE = Decimal("0.0001")


@dataclass
class _Bucket:
    fills: int = 0
    revenue: Decimal = field(default_factory=lambda: Decimal(0))
    quantity: Decimal = field(default_factory=lambda: Decimal(0))


@metric(
    name="chain_ndc_price_rank",
    question=(
        "For each drug, which chain dispenses it most cheaply? Chains ranked by the unit "
        "price actually paid."
    ),
    grain=("ndc", "chain"),
    columns=("ndc", "chain", "fills", "total_quantity", "revenue", "avg_unit_price", "price_rank"),
    measures={
        "fills": "completed fills only (ADR-015)",
        "avg_unit_price": (
            "sum(price) / sum(quantity) - quantity-weighted, so it answers what was paid per "
            "unit rather than what the average fill charged (ADR-015)"
        ),
        "price_rank": (
            "1 = cheapest chain for this drug. Ties break on chain name so the ranking is "
            "reproducible rather than dependent on iteration order"
        ),
    },
)
def chain_ndc_price_rank(data: Dataset) -> Sequence[Mapping[str, object]]:
    """Rank chains by quantity-weighted unit price, within each drug."""
    buckets: dict[tuple[str, str], _Bucket] = {}

    for claim in data.claims:
        if claim.reverted:
            continue
        pharmacy = data.pharmacies.get(claim.npi)
        chain = pharmacy.chain if pharmacy else ""
        bucket = buckets.setdefault((claim.ndc, chain), _Bucket())
        bucket.fills += 1
        bucket.revenue += claim.price
        bucket.quantity += claim.quantity

    by_ndc: dict[str, list[tuple[str, _Bucket]]] = {}
    for (ndc, chain), bucket in buckets.items():
        by_ndc.setdefault(ndc, []).append((chain, bucket))

    rows: list[Mapping[str, object]] = []
    for ndc, entries in sorted(by_ndc.items()):
        priced = [
            (chain, bucket, bucket.revenue / bucket.quantity)
            for chain, bucket in entries
            if bucket.quantity > 0
        ]
        # Rank on the exact quotient, then break ties on chain name: rounding first would
        # let two genuinely different prices tie at the fourth decimal place.
        priced.sort(key=lambda item: (item[2], item[0]))
        for rank, (chain, bucket, unit_price) in enumerate(priced, start=1):
            rows.append(
                {
                    "ndc": ndc,
                    "chain": chain,
                    "fills": bucket.fills,
                    "total_quantity": bucket.quantity,
                    "revenue": bucket.revenue.quantize(Decimal("0.01"), ROUND_HALF_UP),
                    "avg_unit_price": unit_price.quantize(UNIT_PRICE, ROUND_HALF_UP),
                    "price_rank": rank,
                }
            )
    return rows
