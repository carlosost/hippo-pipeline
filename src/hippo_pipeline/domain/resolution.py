"""Revert resolution - the six rules of ADR-012.

The highest-risk code in the project. Not because it is hard, but because every
plausible-looking wrong answer here produces a plausible-looking wrong number downstream
and nothing crashes.

Pure: no IO, no clock, no randomness. Every rule below is a named unit test.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import replace

from hippo_pipeline.domain import reasons
from hippo_pipeline.domain.models import (
    Claim,
    ExcludedRevert,
    ResolutionResult,
    Revert,
)


def _revert_order(revert: Revert) -> tuple[object, ...]:
    """Total order over reverts.

    Timestamp first, then id, then source position. Two reverts sharing a timestamp *and*
    an id is exactly the sample data's case, so the tie-break has to reach provenance or
    the winner depends on which file happened to be read first.
    """
    return (revert.timestamp, revert.id, revert.source_file, revert.record_index)


def resolve_reverts(
    claims: Sequence[Claim],
    reverts: Sequence[Revert],
    quarantined_claim_ids: Set[str] = frozenset(),
) -> ResolutionResult:
    """Apply reversals to claims.

    Args:
        claims: accepted claims, in the order the gateway produced them.
        reverts: accepted reverts, in any order.
        quarantined_claim_ids: ids of claims the gateway rejected or excluded. Needed to
            tell `claim_not_accepted` (a scope or defect decision we made) apart from
            `claim_not_found` (most likely a file this run was not given). Same symptom,
            different diagnosis, so different codes.

    Returns:
        Claims in their original order with reversal flags applied, the reverts that
        could not be linked, and a count per data-quality code.
    """
    by_claim: dict[str, list[Revert]] = {}
    for revert in reverts:
        by_claim.setdefault(revert.claim_id, []).append(revert)

    counts: dict[str, int] = {}

    def bump(code: str, by: int = 1) -> None:
        counts[code] = counts.get(code, 0) + by

    resolved: list[Claim] = []
    for claim in claims:
        group = by_claim.pop(claim.id, None)
        if not group:
            resolved.append(claim)
            continue

        # Rules 1 and 2: claim_id is the key, earliest wins, extras are counted.
        ordered = sorted(group, key=_revert_order)
        winner = ordered[0]
        if len(ordered) > 1:
            bump(reasons.DUPLICATE_REVERT_FOR_CLAIM, len(ordered) - 1)

        # Rule 3: an impossible timestamp still reverts the claim. Rejecting it would
        # leave reversed revenue in the totals - strict on data, wrong on money.
        for revert in ordered:
            if revert.timestamp < claim.timestamp:
                bump(reasons.REVERT_PRECEDES_CLAIM)

        resolved.append(replace(claim, reverted=True, reverted_at=winner.timestamp))

    # Rules 4 and 5: whatever is left points at no accepted claim.
    excluded: list[ExcludedRevert] = []
    for claim_id in sorted(by_claim):
        code = (
            reasons.CLAIM_NOT_ACCEPTED
            if claim_id in quarantined_claim_ids
            else reasons.CLAIM_NOT_FOUND
        )
        for revert in sorted(by_claim[claim_id], key=_revert_order):
            bump(code)
            excluded.append(ExcludedRevert(revert=revert, reason=code))

    return ResolutionResult(
        claims=tuple(resolved),
        excluded=tuple(excluded),
        counts=_sorted_counts(counts),
    )


def _sorted_counts(counts: dict[str, int]) -> Mapping[str, int]:
    """Return counts in sorted key order so any rendering of them is byte-stable."""
    return {code: counts[code] for code in sorted(counts)}
