"""Step definitions for tests/bdd/features/ingestion.feature (F-01)."""

import json
from decimal import Decimal

from pytest_bdd import given, parsers, scenarios, then, when

from hippo_pipeline.gateway import ingest

scenarios("ingestion.feature")

OUT_OF_SCOPE = "9999999999"


def _reasons(records):
    return sorted(code for r in records for code in r.reasons)


# ------------------------------------------------------------------- given --
@given(parsers.parse('the pharmacy dataset contains npi "{npi}" in chain "{chain}"'))
def _pharmacy(workspace, npi, chain):
    workspace.add_pharmacy(npi, chain)


@given(parsers.parse('a pharmacy file whose header is "{header}"'))
def _pharmacy_header(workspace, header):
    assert header == "chain,npi"  # the sample file's order, reversed from the brief


@given(parsers.parse('a claims file "{name}" containing a claim with no "{field}"'))
def _claim_missing_field(workspace, name, field):
    workspace.write_claims([workspace.claim(**{field: ...})], name=name)


@given(parsers.parse('a claims file containing a claim with quantity "{value}"'))
def _claim_quantity_text(workspace, value):
    workspace.write_claims([workspace.claim(quantity=value)])


@given(parsers.parse("a claims file containing a claim with quantity {value:d}"))
def _claim_quantity_number(workspace, value):
    workspace.write_claims([workspace.claim(quantity=value)])


@given(
    parsers.parse('a claims file containing a claim with no "{field}" and an unparseable timestamp')
)
def _claim_two_defects(workspace, field):
    workspace.write_claims([workspace.claim(**{field: ...}, timestamp="not-a-date")])


@given(parsers.parse('a claims file containing a valid claim for npi "{npi}"'))
def _claim_for_npi(workspace, npi):
    workspace.write_claims([workspace.claim(npi=npi)])


@given(parsers.parse('a claims file containing a valid claim timestamped "{stamp}"'))
def _claim_timestamped(workspace, stamp):
    workspace.write_claims([workspace.claim(timestamp=stamp)])


@given(parsers.parse('a claims file containing a valid claim with {field} "{value}"'))
def _claim_with_field(workspace, field, value):
    workspace.write_claims([workspace.claim(**{field: value})])


@given(parsers.parse("a claims file containing a valid claim with quantity {value}"))
def _claim_with_quantity(workspace, value):
    parsed = int(value) if "." not in value else float(value)
    workspace.write_claims([workspace.claim(quantity=parsed)])


@given(
    parsers.parse(
        "a claims file containing a valid claim with price {price:g} and quantity {qty:d}"
    )
)
def _claim_price_quantity(workspace, price, qty):
    workspace.write_claims([workspace.claim(price=price, quantity=qty)])


@given(parsers.parse('a claims file whose third element is the string "{text}"'))
def _claim_non_object(workspace, text):
    workspace.write_claims([workspace.claim(), workspace.claim(), text])


@given(parsers.parse('a claims file "{name}" containing invalid JSON'))
def _claim_file_broken(workspace, name):
    workspace.write_claims_raw("{not json", name)


@given(parsers.parse('a claims file "{name}" containing {count:d} valid claims'))
def _claim_file_valid(workspace, name, count):
    workspace.write_claims([workspace.claim() for _ in range(count)], name=name)


@given(parsers.parse("a claims file containing {ok:d} valid and {bad:d} invalid claims"))
def _claims_valid_and_invalid(workspace, ok, bad):
    workspace.write_claims(
        [workspace.claim() for _ in range(ok)] + [workspace.claim(quantity=...) for _ in range(bad)]
    )


@given(parsers.parse("a claims file containing {ok:d} valid and {out:d} out-of-scope claims"))
def _claims_valid_and_out_of_scope(workspace, ok, out):
    workspace.write_claims(
        [workspace.claim() for _ in range(ok)]
        + [workspace.claim(npi=OUT_OF_SCOPE) for _ in range(out)]
    )


@given(
    parsers.parse(
        "a claims file containing {ok:d} valid, {bad:d} invalid and {out:d} out-of-scope claims"
    )
)
def _claims_three_ways(workspace, ok, bad, out):
    workspace.write_claims(
        [workspace.claim() for _ in range(ok)]
        + [workspace.claim(quantity=...) for _ in range(bad)]
        + [workspace.claim(npi=OUT_OF_SCOPE) for _ in range(out)]
    )


@given(parsers.parse('claims directory "{name}" containing {count:d} valid claims'))
def _claims_directory(workspace, name, count):
    target = workspace.add_claims_dir(name)
    target.joinpath("claims.json").write_text(json.dumps([workspace.claim() for _ in range(count)]))
    workspace.claim_dirs = [d for d in workspace.claim_dirs if d != str(workspace.claims)]


@given("an empty claims directory")
def _empty_directory(workspace):
    return workspace


@given(parsers.parse("a maximum reject rate of {rate:g}"))
def _max_reject_rate(workspace, rate):
    workspace.max_reject_rate = rate


# -------------------------------------------------------------------- when --
@when("the directories are ingested")
def _ingest(workspace, context):
    context["result"] = ingest(
        [str(workspace.pharmacies)], workspace.claim_dirs, [str(workspace.reverts)]
    )


# -------------------------------------------------------------------- then --
@then("the claim is not accepted")
def _not_accepted(context):
    assert context["result"].claims == ()


@then(parsers.parse("{count:d} claims are accepted"))
def _n_accepted(context, count):
    assert len(context["result"].claims) == count


@then(parsers.parse('it appears in the rejected sink with reason "{code}"'))
def _rejected_with(context, code):
    assert _reasons(context["result"].rejected) == [code]


@then(parsers.parse('it appears in the excluded sink with reason "{code}"'))
def _excluded_with(context, code):
    assert _reasons(context["result"].excluded) == [code]


@then("the rejected sink is empty")
def _rejected_empty(context):
    assert context["result"].rejected == ()


@then(parsers.parse('the rejected record records source file "{name}" and its index'))
def _rejected_provenance(context, name):
    record = context["result"].rejected[0]
    assert record.source_file == name
    assert record.record_index == 0


@then(parsers.parse('its reasons include "{first}" and "{second}"'))
def _reasons_include(context, first, second):
    codes = set(context["result"].rejected[0].reasons)
    assert {first, second} <= codes


@then(parsers.parse('one rejected record has reason "{code}" and source file "{name}"'))
def _file_level_rejection(context, code, name):
    matches = [r for r in context["result"].rejected if r.reasons == (code,)]
    assert [r.source_file for r in matches] == [name]


@then("the other elements of that file are still accepted")
def _others_accepted(context):
    assert len(context["result"].claims) == 2


@then(parsers.parse('the accepted claim\'s {field} is exactly "{value}"'))
def _accepted_field(context, field, value):
    assert getattr(context["result"].claims[0], field) == value


@then(parsers.parse("the accepted claim's quantity equals {value}"))
def _accepted_quantity(context, value):
    assert context["result"].claims[0].quantity == Decimal(value)


@then(parsers.parse('the accepted claim\'s price is exactly Decimal("{value}")'))
def _accepted_price(context, value):
    price = context["result"].claims[0].price
    assert price == Decimal(value)
    assert str(price) == value


@then(parsers.parse('the accepted claim\'s timestamp is "{stamp}"'))
def _accepted_timestamp(context, stamp):
    assert context["result"].claims[0].timestamp.isoformat() == stamp


@then(parsers.parse('the pharmacy with npi "{npi}" is in chain "{chain}"'))
def _pharmacy_chain(context, npi, chain):
    assert context["result"].pharmacies[npi].chain == chain


@then("records read equals accepted plus rejected plus excluded")
def _balances(context):
    assert context["result"].counts.balances()


@then("the run does not fail")
def _run_ok(workspace, context):
    assert context["result"].counts.reject_rate <= workspace.max_reject_rate


@then("the run exits non-zero")
def _run_fails(workspace, context):
    assert context["result"].counts.reject_rate > workspace.max_reject_rate


@then("the counts are still reported")
def _counts_reported(context):
    counts = context["result"].counts
    assert counts.read > 0
    assert counts.by_reason
