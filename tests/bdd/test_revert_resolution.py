"""Step definitions for tests/bdd/features/revert_resolution.feature (F-02, ADR-012)."""

from datetime import datetime
from decimal import Decimal

from pytest_bdd import given, parsers, scenarios, then, when

from hippo_pipeline.domain.models import Claim, Revert
from hippo_pipeline.domain.resolution import resolve_reverts

scenarios("revert_resolution.feature")


def at(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def find(context, claim_id):
    return next(c for c in context["result"].claims if c.id == claim_id)


# ------------------------------------------------------------------- given --
@given(parsers.parse('an accepted claim "{claim_id}" for npi "{npi}" timestamped "{stamp}"'))
def _accepted_claim(context, claim_id, npi, stamp):
    context.setdefault("claims", []).append(
        Claim(
            id=claim_id,
            npi=npi,
            ndc="00054027225",
            price=Decimal("10.00"),
            quantity=Decimal("5"),
            timestamp=at(stamp),
        )
    )


@given(parsers.parse('claim "{claim_id}" was rejected during ingest'))
@given(parsers.parse('claim "{claim_id}" was excluded during ingest as out of scope'))
def _quarantined_claim(context, claim_id):
    context.setdefault("quarantined", set()).add(claim_id)


@given(parsers.parse('a revert for claim "{claim_id}" timestamped "{stamp}"'))
def _revert(context, claim_id, stamp):
    reverts = context.setdefault("reverts", [])
    reverts.append(
        Revert(
            id=f"R{len(reverts) + 1}",
            claim_id=claim_id,
            timestamp=at(stamp),
            source_file="reverts-a.json",
            record_index=len(reverts),
        )
    )


@given(parsers.parse('a revert with id "{revert_id}" for claim "{claim_id}" timestamped "{stamp}"'))
def _revert_with_id(context, revert_id, claim_id, stamp):
    reverts = context.setdefault("reverts", [])
    reverts.append(
        Revert(
            id=revert_id,
            claim_id=claim_id,
            timestamp=at(stamp),
            source_file="reverts-a.json",
            record_index=len(reverts),
        )
    )


# -------------------------------------------------------------------- when --
@when("the reverts are resolved")
def _resolve(context):
    context["result"] = resolve_reverts(
        context.get("claims", []),
        context.get("reverts", []),
        context.get("quarantined", set()),
    )


@when("the reverts are resolved twice")
def _resolve_twice(context):
    claims = context.get("claims", [])
    reverts = context.get("reverts", [])
    quarantined = context.get("quarantined", set())
    context["result"] = resolve_reverts(claims, reverts, quarantined)
    # Reversed input: the answer must not depend on the order records arrived in.
    context["second"] = resolve_reverts(claims, list(reversed(reverts)), quarantined)


# -------------------------------------------------------------------- then --
@then(parsers.parse('claim "{claim_id}" is reverted'))
@then(parsers.parse('claim "{claim_id}" is reverted exactly once'))
def _is_reverted(context, claim_id):
    assert find(context, claim_id).reverted is True
    assert sum(1 for c in context["result"].claims if c.id == claim_id and c.reverted) == 1


@then(parsers.parse('claim "{claim_id}" is not reverted'))
def _not_reverted(context, claim_id):
    assert find(context, claim_id).reverted is False


@then(parsers.parse('claim "{claim_id}" has reverted_at "{stamp}"'))
def _reverted_at(context, claim_id, stamp):
    assert find(context, claim_id).reverted_at == at(stamp)


@then(parsers.parse('claim "{claim_id}" has no reverted_at'))
def _no_reverted_at(context, claim_id):
    assert find(context, claim_id).reverted_at is None


@then(parsers.parse('claim "{claim_id}" still carries its price and quantity'))
def _money_intact(context, claim_id):
    claim = find(context, claim_id)
    assert claim.price == Decimal("10.00")
    assert claim.quantity == Decimal("5")


@then(parsers.parse('{count:d} record is counted under "{code}"'))
def _counted_under(context, count, code):
    assert context["result"].counts.get(code) == count


@then(parsers.parse('the revert appears in the excluded sink with reason "{code}"'))
def _excluded_with(context, code):
    assert [e.reason for e in context["result"].excluded] == [code]


@then("the revert is not excluded")
def _not_excluded(context):
    assert context["result"].excluded == ()


@then("the run does not fail")
def _no_failure(context):
    assert context["result"] is not None


@then(parsers.parse("{count:d} claims are returned"))
def _claims_returned(context, count):
    assert len(context["result"].claims) == count


@then("the returned claims are in the same order they were given")
def _order_preserved(context):
    assert [c.id for c in context["result"].claims] == [c.id for c in context["claims"]]


@then("both results are identical, including the order of excluded records")
def _identical(context):
    assert context["result"] == context["second"]
