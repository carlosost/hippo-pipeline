"""Aggregations over domain types (ADR-003).

Pure functions, individually addressable, each one answering a stated business question.
This is the layer analysts and AI agents extend, and a new metric costs one module and one
test - never a change to ingestion.

Adding a metric: copy `pharmacy_ndc_summary.py`, change the declaration and the function.
Discovery, execution, export and documentation follow from the decorator.
"""

from hippo_pipeline.metrics.catalog import render_catalog
from hippo_pipeline.metrics.registry import (
    MetricDeclarationError,
    MetricOutput,
    MetricOutputError,
    MetricSpec,
    discover,
    metric,
    registered,
    reset_registry,
    run_all,
)

__all__ = [
    "MetricDeclarationError",
    "MetricOutput",
    "MetricOutputError",
    "MetricSpec",
    "discover",
    "metric",
    "registered",
    "render_catalog",
    "reset_registry",
    "run_all",
]
