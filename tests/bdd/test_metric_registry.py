"""Step definitions for tests/bdd/features/metric_registry.feature (F-04)."""

import json
import subprocess
import sys
import textwrap
from decimal import Decimal
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from hippo_pipeline import cli
from hippo_pipeline.domain.models import Dataset
from hippo_pipeline.gateway import write_table
from hippo_pipeline.metrics import registry
from hippo_pipeline.metrics.catalog import render_catalog
from hippo_pipeline.metrics.registry import (
    MetricDeclarationError,
    MetricOutputError,
    discover,
    metric,
    reset_registry,
    run_all,
)

scenarios("metric_registry.feature")

REPO_ROOT = Path(__file__).resolve().parents[2]
EMPTY = Dataset(claims=(), reverts=(), pharmacies={})

MODULE_TEMPLATE = """
from hippo_pipeline.metrics.registry import metric


@metric(name={name!r}, question={question!r}, grain=("npi",), columns=("npi",))
def compute(data):
    return []
"""


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(registry._REGISTRY)
    reset_registry()
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)


def _make_package(tmp_path, modules, name):
    """A real, importable package so `discover()` is exercised rather than simulated."""
    package = tmp_path / name
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("")
    for module_name, body in modules.items():
        (package / f"{module_name}.py").write_text(textwrap.dedent(body))
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    return name


# ---------------------------------------------------- declaration is checked --
@given(parsers.parse("a metric module declaring an empty question"))
def _empty_question(context, tmp_path):
    context["package"] = _make_package(
        tmp_path,
        {"bad": MODULE_TEMPLATE.format(name="broken", question="   ")},
        "pkg_empty_question",
    )


@given(parsers.parse('a metric module declaring the name "{name}"'))
def _first_module(context, tmp_path, name):
    context["modules"] = {"one": MODULE_TEMPLATE.format(name=name, question="How many?")}
    context["duplicate_name"] = name


@given(parsers.parse('another metric module declaring the name "{name}"'))
def _second_module(context, tmp_path, name):
    context["modules"]["two"] = MODULE_TEMPLATE.format(name=name, question="How many?")
    context["package"] = _make_package(tmp_path, context["modules"], "pkg_duplicate")


@when("the metrics package is discovered")
def _discover(context):
    try:
        discover(context["package"])
        context["error"] = None
    except MetricDeclarationError as exc:
        context["error"] = exc


@then("discovery raises, naming the offending module")
def _raises_naming_module(context):
    assert context["error"] is not None
    assert "bad" in str(context["error"])


@then("discovery raises, naming both modules")
def _raises_naming_both(context):
    message = str(context["error"])
    assert context["error"] is not None
    assert "one" in message and "two" in message


# ------------------------------------------------------- rows are checked --
@given(parsers.parse('a metric declaring columns "{columns}" that returns a row with key "{key}"'))
def _row_with_extra_key(context, columns, key):
    names = tuple(c.strip() for c in columns.split(","))
    metric(name="example", question="q", grain=(names[0],), columns=names)(
        lambda data: [{**{c: 1 for c in names}, key: 2}]
    )


@given(
    parsers.parse('a metric declaring columns "{columns}" that returns a row with only "{kept}"')
)
def _row_missing_column(context, columns, kept):
    names = tuple(c.strip() for c in columns.split(","))
    metric(name="example", question="q", grain=(names[0],), columns=names)(lambda data: [{kept: 1}])


@given("a metric that raises ValueError")
def _raising_metric(context):
    def broken(data):
        raise ValueError("boom")

    metric(name="example", question="q", grain=("npi",), columns=("npi",))(broken)


@when("the metrics are run")
def _run(context):
    try:
        context["outputs"] = run_all(EMPTY)
        context["error"] = None
    except (MetricOutputError, ValueError) as exc:
        context["error"] = exc


@then(parsers.parse('the run fails, naming the metric and the key "{key}"'))
def _fails_naming_key(context, key):
    assert isinstance(context["error"], MetricOutputError)
    assert "example" in str(context["error"]) and key in str(context["error"])


@then(parsers.parse('the run fails, naming the metric and the column "{column}"'))
def _fails_naming_column(context, column):
    assert isinstance(context["error"], MetricOutputError)
    assert "example" in str(context["error"]) and column in str(context["error"])


@then("the run fails")
def _fails(context):
    assert context["error"] is not None


@then("nothing is written to the rejected sink")
def _no_quarantine(context, tmp_path):
    """Quarantine is for data. A defect in our code is not a data-quality event."""
    assert not (tmp_path / "_rejected.csv").exists()


# ---------------------------------------------------------------- ordering --
@given(parsers.parse('a metric named "{name}" imported first'))
@given(parsers.parse('a metric named "{name}" imported second'))
def _named_metric(context, name):
    metric(name=name, question="q", grain=("npi",), columns=("npi",))(lambda data: [])


@then(parsers.parse('the results are ordered "{first}", "{second}"'))
def _ordered(context, first, second):
    assert [o.name for o in context["outputs"]] == [first, second]


# ------------------------------------------------------------------ output --
@given(parsers.parse('a metric named "{name}" returning {count:d} rows'))
def _metric_with_rows(context, name, count):
    metric(name=name, question="q", grain=("npi",), columns=("npi",))(
        lambda data: [{"npi": f"{i:010d}"} for i in range(count)]
    )


@given(parsers.parse('a metric returning a revenue of Decimal("{value}")'))
def _metric_with_decimal(context, value):
    metric(name="money", question="q", grain=("npi",), columns=("npi", "revenue"))(
        lambda data: [{"npi": "0123456789", "revenue": Decimal(value)}]
    )
    context["decimal"] = value


@given("a metric that inspects its argument")
def _spying_metric(context):
    def spy(data):
        context["seen"] = data
        return []

    metric(name="spy", question="q", grain=("npi",), columns=("npi",))(spy)


@given("a dataset and a set of metrics")
def _dataset_and_metrics(context):
    metric(name="alpha", question="q", grain=("npi",), columns=("npi",))(
        lambda data: [{"npi": "0123456789"}, {"npi": "0987654321"}]
    )


@when("the metrics are run and written to the output directory")
def _run_and_write(context, tmp_path):
    context["out"] = tmp_path / "out"
    for output in run_all(EMPTY):
        write_table(str(context["out"]), output.name, output.columns, output.rows)


@when("the metrics are run and written twice to different directories")
def _run_and_write_twice(context, tmp_path):
    context["dirs"] = []
    for name in ("first", "second"):
        target = tmp_path / name
        for output in run_all(EMPTY):
            write_table(str(target), output.name, output.columns, output.rows)
        context["dirs"].append(target)


@then(parsers.parse('"out/{name}.csv" contains a header and {count:d} rows'))
def _csv_rows(context, name, count):
    lines = (context["out"] / f"{name}.csv").read_text().strip().splitlines()
    assert len(lines) == count + 1


@then(parsers.parse('"out/{name}.json" contains {count:d} objects'))
def _json_rows(context, name, count):
    assert len(json.loads((context["out"] / f"{name}.json").read_text())) == count


@then(parsers.parse('the JSON contains "{value}" and not a float'))
def _decimal_exact(context, value):
    text = (context["out"] / "money.json").read_text()
    assert f'"{value}"' in text


@then("it receives a Dataset exposing claims, reverts and pharmacies")
def _received_dataset(context):
    seen = context["seen"]
    assert isinstance(seen, Dataset)
    assert (seen.claims, seen.reverts) == ((), ())
    assert seen.pharmacies == {}


@then("every output file is byte-identical between the two runs")
def _byte_identical(context):
    first, second = context["dirs"]
    names = sorted(p.name for p in first.iterdir())
    assert names
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


# --------------------------------------------------------------- catalogue --
@given(parsers.parse('a metric named "{name}" with a question, a grain and a measure formula'))
def _catalogued_metric(context, name):
    metric(
        name=name,
        question="What share of fills are reverted?",
        grain=("chain",),
        columns=("chain", "rate"),
        measures={"rate": "reverted / (fills + reverted)"},
    )(lambda data: [])


@when("the catalogue is rendered")
def _render(context):
    context["catalogue"] = render_catalog()


@then(parsers.parse('it lists "{name}" with its question, its grain, its columns and the formula'))
def _catalogue_lists(context, name):
    text = context["catalogue"]
    assert f"## {name}" in text
    assert "What share of fills are reverted?" in text
    assert "`chain`" in text
    assert "`rate`" in text
    assert "reverted / (fills + reverted)" in text


@given("docs/METRICS.md does not match the registry")
def _stale_catalogue(context, tmp_path):
    stale = tmp_path / "STALE.md"
    stale.write_text("# Metrics\n\nthis is not what the registry says\n")
    context["catalogue_path"] = stale


@when("the lint runs")
def _run_lint(context):
    context["lint"] = subprocess.run(
        ["bash", "scripts/check_catalog.sh", str(context["catalogue_path"])],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


@then("it fails and prints the command that regenerates the catalogue")
def _lint_fails(context):
    assert context["lint"].returncode == 1
    assert "make catalog" in context["lint"].stdout


# ------------------------------------------------------ tested == shipped --
@given("the CLI is invoked against the sample data")
def _cli_invoked(context):
    context["cli"] = cli


@then("it executes the same run_all used by the tests")
def _same_function(context):
    """AP-11: not a similar function, the same object."""
    assert context["cli"].run_all is run_all
