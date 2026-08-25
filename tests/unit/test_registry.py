"""F-04: declaration errors raise at import time, row errors at run time."""

import pytest

from hippo_pipeline.domain.models import Dataset
from hippo_pipeline.metrics.registry import (
    MetricDeclarationError,
    MetricOutputError,
    metric,
    registered,
    reset_registry,
    run_all,
)

EMPTY = Dataset(claims=(), reverts=(), pharmacies={})


def declare(
    name="example",
    question="How many?",
    grain=("npi",),
    columns=("npi", "fills"),
    measures=None,
):
    """Declare a metric with sensible defaults, so each test varies one thing."""

    def build(fn=lambda data: []):
        return metric(
            name=name, question=question, grain=grain, columns=columns, measures=measures
        )(fn)

    return build


# ------------------------------------------------- the declaration is checked --
def test_a_metric_without_a_question_cannot_be_declared():
    reset_registry()

    with pytest.raises(MetricDeclarationError, match="has no question"):
        declare(question="   ")()


def test_two_metrics_cannot_share_a_name():
    reset_registry()
    declare(name="revenue")()

    with pytest.raises(MetricDeclarationError, match="duplicate metric name 'revenue'"):
        declare(name="revenue")()


def test_a_name_that_could_not_be_a_filename_is_rejected():
    reset_registry()

    with pytest.raises(MetricDeclarationError, match="becomes a filename"):
        declare(name="revenue/by-chain")()


def test_a_grain_outside_the_columns_is_rejected():
    reset_registry()

    with pytest.raises(MetricDeclarationError, match="is not among its columns"):
        declare(grain=("chain",))()


def test_a_formula_for_a_column_that_does_not_exist_is_rejected():
    reset_registry()

    with pytest.raises(MetricDeclarationError, match="non-columns"):
        declare(measures={"revenue": "sum(price)"})()


def test_the_declaration_error_names_the_module():
    reset_registry()

    with pytest.raises(MetricDeclarationError, match=r"tests\.unit\.test_registry"):
        declare(question="")()


# --------------------------------------------------------- the rows are checked --
def test_an_undeclared_key_fails_the_run():
    reset_registry()
    declare()(lambda data: [{"npi": "1", "fills": 1, "revenue": 2}])

    with pytest.raises(MetricOutputError, match=r"undeclared key\(s\) \['revenue'\]"):
        run_all(EMPTY)


def test_a_missing_declared_column_fails_the_run():
    reset_registry()
    declare()(lambda data: [{"npi": "1"}])

    with pytest.raises(MetricOutputError, match=r"missing declared column\(s\) \['fills'\]"):
        run_all(EMPTY)


def test_a_metric_that_raises_fails_the_run_and_is_not_quarantined():
    """Quarantine is for data. A defect in our own code is not a data-quality event."""
    reset_registry()

    def broken(data):
        raise ValueError("boom")

    declare()(broken)

    with pytest.raises(ValueError, match="boom"):
        run_all(EMPTY)


# ------------------------------------------------------------------ ordering --
def test_metrics_run_in_sorted_name_order_regardless_of_declaration_order():
    reset_registry()
    declare(name="zebra")()
    declare(name="alpha")()

    assert [o.name for o in run_all(EMPTY)] == ["alpha", "zebra"]
    assert [s.name for s in registered()] == ["alpha", "zebra"]


def test_the_question_is_normalised_so_the_catalogue_is_stable():
    reset_registry()
    declare(question="How   many\n   fills?")()

    assert registered()[0].question == "How many fills?"


def test_a_metric_receives_the_dataset():
    reset_registry()
    seen = {}

    def spy(data):
        seen["arg"] = data
        return []

    declare()(spy)
    run_all(EMPTY)

    assert seen["arg"] is EMPTY
