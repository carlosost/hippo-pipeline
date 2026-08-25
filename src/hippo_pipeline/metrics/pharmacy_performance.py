"""Which pharmacies are underperforming - with a confidence bound, not just a rate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from hippo_pipeline.domain.models import Dataset
from hippo_pipeline.metrics._stats import rate, wilson_lower_bound
from hippo_pipeline.metrics.registry import metric

CENTS = Decimal("0.01")


@dataclass
class _Bucket:
    fills: int = 0
    reverted: int = 0
    revenue: Decimal = field(default_factory=lambda: Decimal(0))
    drugs: set[str] = field(default_factory=set)


@metric(
    name="pharmacy_performance",
    question=(
        "Which pharmacies are underperforming? Volume, revenue and reversal rate per "
        "pharmacy, with a confidence bound so small samples are not mistaken for problems."
    ),
    grain=("npi",),
    columns=(
        "npi",
        "chain",
        "claims",
        "fills",
        "reverted",
        "reversal_rate",
        "reversal_rate_lower_95",
        "revenue",
        "distinct_drugs",
    ),
    measures={
        "claims": "fills + reverted; every accepted claim for this pharmacy",
        "reversal_rate": "reverted / claims, rounded to 6 decimal places",
        "reversal_rate_lower_95": (
            "lower bound of the 95% Wilson score interval on reverted/claims. Rank by this, "
            "not by reversal_rate: with unequal denominators the raw rate puts 1-in-10 above "
            "40-in-1000. On the sample dataset every pharmacy's interval overlaps every "
            "other's, which is the honest answer - no pharmacy is an outlier"
        ),
        "revenue": "sum(price) over completed fills only, exact Decimal (ADR-015)",
        "distinct_drugs": "count of distinct NDCs dispensed, reverted fills included",
    },
)
def pharmacy_performance(data: Dataset) -> Sequence[Mapping[str, object]]:
    """Aggregate every accepted claim to its pharmacy."""
    buckets: dict[str, _Bucket] = {}

    for claim in data.claims:
        bucket = buckets.setdefault(claim.npi, _Bucket())
        bucket.drugs.add(claim.ndc)
        if claim.reverted:
            bucket.reverted += 1
            continue
        bucket.fills += 1
        bucket.revenue += claim.price

    rows: list[Mapping[str, object]] = []
    for npi, bucket in sorted(buckets.items()):
        pharmacy = data.pharmacies.get(npi)
        claims = bucket.fills + bucket.reverted
        rows.append(
            {
                "npi": npi,
                "chain": pharmacy.chain if pharmacy else "",
                "claims": claims,
                "fills": bucket.fills,
                "reverted": bucket.reverted,
                "reversal_rate": rate(bucket.reverted, claims),
                "reversal_rate_lower_95": wilson_lower_bound(bucket.reverted, claims),
                "revenue": bucket.revenue.quantize(CENTS, ROUND_HALF_UP),
                "distinct_drugs": len(bucket.drugs),
            }
        )
    return rows
