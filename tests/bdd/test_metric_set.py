"""Step definitions for tests/bdd/features/metric_set.feature (F-03, ADR-015, ADR-016)."""

from dataclasses import replace
from decimal import Decimal

from pytest_bdd import given, parsers, scenarios, then, when

from hippo_pipeline.domain.models import Claim, Dataset, Pharmacy
from hippo_pipeline.metrics.catalog import render_catalog
from hippo_pipeline.metrics.chain_ndc_price_rank import chain_ndc_price_rank
from hippo_pipeline.metrics.drug_price_dispersion import drug_price_dispersion
from hippo_pipeline.metrics.pharmacy_performance import pharmacy_performance
from hippo_pipeline.metrics.registry import discover, registered

scenarios("metric_set.feature")

CHAINS = ("saint", "health", "doctor")


def make_claim(
    index, npi="0123456789", ndc="00054027225", price="10.00", quantity="1", reverted=False
):
    from datetime import datetime, timezone

    claim = Claim(
        id=f"C{index}",
        npi=npi,
        ndc=ndc,
        price=Decimal(price),
        quantity=Decimal(quantity),
        timestamp=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    return replace(claim, reverted=True) if reverted else claim


def dataset(context):
    return Dataset(
        claims=tuple(context.get("claims", [])),
        reverts=(),
        pharmacies=context.get("pharmacies", {}),
    )


# ------------------------------------------------------- pharmacy performance --
@given(parsers.parse("a pharmacy with {reversals:d} reversal in {claims:d} claims"))
@given(parsers.parse("a pharmacy with {reversals:d} reversals in {claims:d} claims"))
def _pharmacy_with_reversals(context, reversals, claims):
    npi = f"{len(context.get('pharmacies', {})) + 1}" * 10
    context.setdefault("pharmacies", {})[npi] = Pharmacy(npi=npi, chain="saint")
    context.setdefault("order", []).append(npi)
    rows = context.setdefault("claims", [])
    start = len(rows)
    for i in range(claims):
        rows.append(make_claim(start + i, npi=npi, reverted=i < reversals))


@given(
    parsers.parse(
        "a pharmacy with {fills:d} completed fills worth {revenue:f} and "
        "{reverted:d} reverted fill worth {lost:f}"
    )
)
def _pharmacy_with_revenue(context, fills, revenue, reverted, lost):
    npi = "0123456789"
    context.setdefault("pharmacies", {})[npi] = Pharmacy(npi=npi, chain="saint")
    rows = context.setdefault("claims", [])
    each = Decimal(str(revenue)) / fills
    for i in range(fills):
        rows.append(make_claim(i, npi=npi, price=str(each)))
    for i in range(reverted):
        rows.append(make_claim(100 + i, npi=npi, price=str(lost), reverted=True))


@when("pharmacy performance is computed")
def _run_performance(context):
    context["rows"] = pharmacy_performance(dataset(context))


@then("the first has the higher reversal rate")
def _first_higher_rate(context):
    by_npi = {r["npi"]: r for r in context["rows"]}
    first, second = context["order"]
    assert by_npi[first]["reversal_rate"] > by_npi[second]["reversal_rate"]


@then("the second has the higher lower bound")
def _second_higher_bound(context):
    by_npi = {r["npi"]: r for r in context["rows"]}
    first, second = context["order"]
    assert by_npi[second]["reversal_rate_lower_95"] > by_npi[first]["reversal_rate_lower_95"]


@then("ranking by the bound puts the larger sample first")
def _bound_ranks_larger_first(context):
    ranked = sorted(context["rows"], key=lambda r: -r["reversal_rate_lower_95"])
    assert ranked[0]["claims"] > ranked[1]["claims"]


@then(parsers.parse("it reports {claims:d} claims, {fills:d} fills and revenue of {revenue:f}"))
def _reports_counts(context, claims, fills, revenue):
    row = context["rows"][0]
    assert row["claims"] == claims
    assert row["fills"] == fills
    assert row["revenue"] == Decimal(str(revenue)).quantize(Decimal("0.01"))


# ------------------------------------------------------------ price dispersion --
@given("the sample dataset")
def _sample_dataset(context):
    """Reproduces the shape PMA 2.4 records: identical bounds, differing medians."""
    rows = context.setdefault("claims", [])
    for drug, band in (("AAA", "2.1"), ("BBB", "2.9"), ("CCC", "676.1")):
        for i, price in enumerate(["0.3", band, band, "884.6"]):
            rows.append(make_claim(f"{drug}{i}", ndc=drug, price=price, quantity="1"))


@given(
    parsers.parse(
        "a drug with a completed fill at {paid:f} per unit and a reverted fill at {unpaid:f}"
    )
)
def _drug_with_reverted_fill(context, paid, unpaid):
    rows = context.setdefault("claims", [])
    rows.append(make_claim(0, price=str(paid), quantity="1"))
    rows.append(make_claim(1, price=str(unpaid), quantity="1", reverted=True))


@when("drug price dispersion is computed")
def _run_dispersion(context):
    context["rows"] = drug_price_dispersion(dataset(context))


@then("every drug has the same max_over_min ratio")
def _same_ratio(context):
    assert len({r["max_over_min"] for r in context["rows"]}) == 1


@then("the median unit price falls into more than one band")
def _median_bands(context):
    assert len({r["median_unit_price"] for r in context["rows"]}) > 1


@then(parsers.parse("the maximum unit price is {value:f}"))
def _max_unit_price(context, value):
    assert context["rows"][0]["max_unit_price"] == Decimal(str(value)).quantize(Decimal("0.0001"))


# ---------------------------------------------------------------- chain ranking --
@given(
    parsers.parse(
        "a chain that filled {qty_a:d} unit at {price_a:f} and {qty_b:d} units at {price_b:f}"
    )
)
def _chain_two_fills(context, qty_a, price_a, qty_b, price_b):
    npi = "1111111111"
    context.setdefault("pharmacies", {})[npi] = Pharmacy(npi=npi, chain="saint")
    rows = context.setdefault("claims", [])
    rows.append(make_claim(0, npi=npi, price=str(price_a), quantity=str(qty_a)))
    rows.append(make_claim(1, npi=npi, price=str(price_b), quantity=str(qty_b)))


@given(parsers.parse("three chains dispensing one drug at {a:f}, {b:f} and {c:f} per unit"))
def _three_chains(context, a, b, c):
    rows = context.setdefault("claims", [])
    pharmacies = context.setdefault("pharmacies", {})
    for i, price in enumerate((a, b, c)):
        npi = f"{i + 1}" * 10
        pharmacies[npi] = Pharmacy(npi=npi, chain=CHAINS[i])
        rows.append(make_claim(i, npi=npi, price=str(price), quantity="1"))
    context["cheapest"] = min(zip((a, b, c), CHAINS, strict=True))


@when("chain price ranking is computed")
def _run_ranking(context):
    context["rows"] = chain_ndc_price_rank(dataset(context))


@then(parsers.parse("its average unit price is {weighted:f} rather than {unweighted:f}"))
def _weighted_price(context, weighted, unweighted):
    actual = context["rows"][0]["avg_unit_price"]
    assert actual == Decimal(str(weighted)).quantize(Decimal("0.0001"))
    assert actual != Decimal(str(unweighted)).quantize(Decimal("0.0001"))


@then(parsers.parse("rank 1 is the chain at {price:f} per unit"))
def _rank_one(context, price):
    first = next(r for r in context["rows"] if r["price_rank"] == 1)
    assert first["chain"] == context["cheapest"][1]
    assert first["avg_unit_price"] == Decimal(str(price)).quantize(Decimal("0.0001"))


# ----------------------------------------------------------------- catalogue --
@when("the catalogue is rendered")
def _render_catalogue(context):
    discover()
    context["catalogue"] = render_catalog()


@then("every registered metric has a non-empty question")
def _every_question(context):
    specs = registered()
    assert specs
    for spec in specs:
        assert spec.question.strip()
        assert spec.question in context["catalogue"]


@then("the unit price columns say they are quantity-weighted")
def _weighted_stated(context):
    assert "quantity-weighted" in context["catalogue"]
