"""The catalogue is generated. A stale catalogue is worse than none, because it is believed."""

from hippo_pipeline.metrics import render_catalog
from hippo_pipeline.metrics.registry import metric, reset_registry


def test_an_empty_registry_says_so_rather_than_rendering_a_broken_table():
    reset_registry()

    assert "_No metrics are registered._" in render_catalog()


def test_the_catalogue_carries_the_question_grain_columns_and_formulas():
    reset_registry()

    @metric(
        name="reversal_rate",
        question="What share of fills are reverted?",
        grain=("chain",),
        columns=("chain", "rate"),
        measures={"rate": "reverted / (fills + reverted)"},
    )
    def _(data):
        return []

    text = render_catalog()

    assert "## reversal_rate" in text
    assert "What share of fills are reverted?" in text
    assert "`chain`" in text
    assert "reverted / (fills + reverted)" in text
    assert "out/reversal_rate.csv" in text


def test_the_time_basis_assumption_travels_with_the_numbers():
    """ADR-013: UTC is a declared assumption, so it is stated where the metrics are read."""
    reset_registry()

    assert "UTC" in render_catalog()


def test_rendering_twice_produces_identical_text():
    reset_registry()

    @metric(name="a", question="q", grain=("x",), columns=("x",))
    def _(data):
        return []

    assert render_catalog() == render_catalog()
