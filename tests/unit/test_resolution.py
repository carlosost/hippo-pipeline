"""ADR-012, rule by rule.

The highest-risk code in the project: every plausible-looking wrong answer here produces
a plausible-looking wrong number downstream, and nothing crashes.
"""

from hippo_pipeline.domain import reasons
from hippo_pipeline.domain.resolution import resolve_reverts

from .conftest import at, claim, revert


def test_a_claim_with_no_revert_is_not_reverted():
    result = resolve_reverts([claim("C1")], [])

    assert result.claims[0].reverted is False
    assert result.claims[0].reverted_at is None
    assert result.counts == {}


def test_a_claim_with_one_revert_is_reverted_at_that_time():
    result = resolve_reverts([claim("C1")], [revert("R1", "C1", "2026-02-02T09:00:00")])

    assert result.claims[0].reverted is True
    assert result.claims[0].reverted_at == at("2026-02-02T09:00:00")


def test_a_reverted_claim_is_retained_with_its_money_intact():
    """Deleting it would make the reversal rate uncomputable (ADR-012)."""
    original = claim("C1", price="99.50", quantity="7")

    result = resolve_reverts([original], [revert("R1", "C1", "2026-02-02T09:00:00")])

    assert len(result.claims) == 1
    assert result.claims[0].price == original.price
    assert result.claims[0].quantity == original.quantity


def test_two_reverts_for_one_claim_revert_it_once_keeping_the_earliest():
    result = resolve_reverts(
        [claim("C1")],
        [
            revert("R1", "C1", "2026-05-01T22:38:13"),
            revert("R2", "C1", "2026-03-01T08:25:49"),
        ],
    )

    assert result.claims[0].reverted is True
    assert result.claims[0].reverted_at == at("2026-03-01T08:25:49")
    assert result.counts[reasons.DUPLICATE_REVERT_FOR_CLAIM] == 1


def test_the_sample_datas_case_one_revert_id_two_timestamps():
    """Three ids in the provided data appear twice with different timestamps (PMA 2.4).

    Keying on `id` would discard a real reversal; keying on the whole record would count
    this claim as reverted twice. Keying on claim_id makes both impossible.
    """
    result = resolve_reverts(
        [claim("C1")],
        [
            revert("R-DUP", "C1", "2026-01-01T12:31:37", index=0),
            revert("R-DUP", "C1", "2026-05-01T22:38:13", index=1),
        ],
    )

    assert sum(1 for c in result.claims if c.reverted) == 1
    assert result.claims[0].reverted_at == at("2026-01-01T12:31:37")
    assert result.counts[reasons.DUPLICATE_REVERT_FOR_CLAIM] == 1


def test_a_revert_before_its_claim_still_reverts_it():
    """Rejecting it would leave reversed revenue in the totals (ADR-012 rule 3)."""
    result = resolve_reverts(
        [claim("C1", ts="2026-02-01T10:00:00")],
        [revert("R1", "C1", "2026-01-15T08:00:00")],
    )

    assert result.claims[0].reverted is True
    assert result.claims[0].reverted_at == at("2026-01-15T08:00:00")
    assert result.counts[reasons.REVERT_PRECEDES_CLAIM] == 1
    assert result.excluded == ()


def test_a_revert_for_an_unknown_claim_is_excluded_not_fatal():
    result = resolve_reverts([claim("C1")], [revert("R1", "GHOST", "2026-03-01T09:00:00")])

    assert [e.reason for e in result.excluded] == [reasons.CLAIM_NOT_FOUND]
    assert result.counts[reasons.CLAIM_NOT_FOUND] == 1


def test_a_revert_for_a_quarantined_claim_gets_a_different_code():
    """Same symptom, different diagnosis: a scope decision we made, not a missing file."""
    result = resolve_reverts(
        [claim("C1")],
        [revert("R1", "C-REJECTED", "2026-03-01T09:00:00")],
        quarantined_claim_ids={"C-REJECTED"},
    )

    assert [e.reason for e in result.excluded] == [reasons.CLAIM_NOT_ACCEPTED]


def test_claim_order_is_preserved():
    claims = [claim("C1"), claim("C2"), claim("C3")]

    result = resolve_reverts(claims, [revert("R1", "C2", "2026-03-01T09:00:00")])

    assert [c.id for c in result.claims] == ["C1", "C2", "C3"]


def test_resolution_is_deterministic_including_excluded_order():
    claims = [claim("C1")]
    reverts = [
        revert("R2", "GHOST-B", "2026-02-02T09:00:00"),
        revert("R1", "GHOST-A", "2026-02-02T09:00:00"),
    ]

    first = resolve_reverts(claims, reverts)
    second = resolve_reverts(claims, list(reversed(reverts)))

    assert first == second
    assert [e.revert.claim_id for e in first.excluded] == ["GHOST-A", "GHOST-B"]


def test_counts_are_returned_in_sorted_key_order():
    result = resolve_reverts(
        [claim("C1", ts="2026-02-01T10:00:00")],
        [
            revert("R1", "C1", "2026-01-15T08:00:00"),
            revert("R2", "C1", "2026-03-01T08:00:00"),
            revert("R3", "GHOST", "2026-03-01T08:00:00"),
        ],
    )

    assert list(result.counts) == sorted(result.counts)
