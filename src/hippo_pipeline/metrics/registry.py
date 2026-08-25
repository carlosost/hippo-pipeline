"""The metric registry - the whole of ADR-008's "framework", and deliberately small.

A metric is one module plus one test. Everything else - discovery, execution order,
export, documentation - follows from registration. If adding a metric cost more than one
file, an analyst or an agent would not do it, and the pipeline would be a report generator
rather than a foundation.

Declaration errors raise at **import time**, not at run time: a malformed metric should be
impossible to ship, not caught by the run that needed it.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from hippo_pipeline.domain.models import Dataset

MetricFn = Callable[[Dataset], Sequence[Mapping[str, object]]]

_INTERNAL_MODULES = frozenset({"registry", "catalog"})


class MetricDeclarationError(ValueError):
    """A metric is declared wrongly. Raised at import time."""


class MetricOutputError(ValueError):
    """A metric returned rows that do not match its declared columns. Raised at run time."""


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """A registered metric: its declaration plus the function that computes it."""

    name: str
    question: str
    grain: tuple[str, ...]
    columns: tuple[str, ...]
    measures: Mapping[str, str]
    fn: MetricFn
    module: str


@dataclass(frozen=True, slots=True)
class MetricOutput:
    name: str
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, object], ...]


_REGISTRY: dict[str, MetricSpec] = {}


def metric(
    *,
    name: str,
    question: str,
    grain: Sequence[str],
    columns: Sequence[str],
    measures: Mapping[str, str] | None = None,
) -> Callable[[MetricFn], MetricFn]:
    """Declare and register a metric.

    Args:
        name: identifier and output filename. A public contract - renaming it is a
            breaking change under ADR-005.
        question: the business question this answers. **Mandatory.** A metric without one
            is decoration, and the declaration is the cheapest place to say so.
        grain: the columns that make a row unique.
        columns: every column, in output order.
        measures: column -> the formula behind it, in words. Required for any figure with
            more than one defensible definition - unit price above all (OQ-08), where
            mean-of-ratios and ratio-of-sums differ materially on this data.
    """

    def register(fn: MetricFn) -> MetricFn:
        module = getattr(fn, "__module__", "<unknown>")
        _validate(name, question, grain, columns, measures or {}, module)
        if name in _REGISTRY:
            raise MetricDeclarationError(
                f"duplicate metric name {name!r}: declared in {_REGISTRY[name].module} "
                f"and again in {module}"
            )
        _REGISTRY[name] = MetricSpec(
            name=name,
            question=" ".join(question.split()),
            grain=tuple(grain),
            columns=tuple(columns),
            measures={k: measures[k] for k in sorted(measures)} if measures else {},
            fn=fn,
            module=module,
        )
        return fn

    return register


def _validate(
    name: str,
    question: str,
    grain: Sequence[str],
    columns: Sequence[str],
    measures: Mapping[str, str],
    module: str,
) -> None:
    where = f"(declared in {module})"
    if not name or not name.replace("_", "").isalnum():
        raise MetricDeclarationError(
            f"metric name {name!r} must be alphanumeric with underscores {where}; "
            f"it becomes a filename"
        )
    if not question.strip():
        raise MetricDeclarationError(
            f"metric {name!r} has no question {where}; a metric without a stated business "
            f"question is decoration"
        )
    if not columns:
        raise MetricDeclarationError(f"metric {name!r} declares no columns {where}")
    if len(set(columns)) != len(columns):
        raise MetricDeclarationError(f"metric {name!r} declares a duplicate column {where}")
    if not grain:
        raise MetricDeclarationError(f"metric {name!r} declares no grain {where}")
    unknown_grain = [c for c in grain if c not in columns]
    if unknown_grain:
        raise MetricDeclarationError(
            f"metric {name!r} grain {unknown_grain} is not among its columns {where}"
        )
    unknown_measures = [c for c in measures if c not in columns]
    if unknown_measures:
        raise MetricDeclarationError(
            f"metric {name!r} declares formulas for non-columns {unknown_measures} {where}"
        )


def registered() -> tuple[MetricSpec, ...]:
    """Every registered metric, sorted by name.

    Sorted, not insertion-ordered: `discover()` makes import side effects load-bearing, so
    execution order must not depend on which module happened to be imported first.
    """
    return tuple(_REGISTRY[name] for name in sorted(_REGISTRY))


def reset_registry() -> None:
    """Empty the registry. For tests only - production never unregisters a metric."""
    _REGISTRY.clear()


def discover(package_name: str | None = None) -> None:
    """Import every metric module so its decorator runs. Idempotent.

    `package_name` exists so the acceptance tests can point the real discovery at a
    throwaway package. Testing it by calling the decorator directly would verify the
    decorator, not discovery.
    """
    package = importlib.import_module(package_name or __package__ or "hippo_pipeline.metrics")
    for info in sorted(pkgutil.iter_modules(list(package.__path__)), key=lambda m: m.name):
        if info.name.startswith("_") or info.name in _INTERNAL_MODULES:
            continue
        importlib.import_module(f"{package.__name__}.{info.name}")


def run_all(dataset: Dataset) -> tuple[MetricOutput, ...]:
    """Execute every registered metric and validate its rows against its declaration.

    A metric that raises is *not* quarantined. Quarantine is for data (ADR-011); a defect
    in our own code is not a data-quality event, and routing it into a rejects file is how
    a bug ships disguised as a bad record.
    """
    outputs: list[MetricOutput] = []
    for spec in registered():
        rows = tuple(spec.fn(dataset))
        expected = set(spec.columns)
        for index, row in enumerate(rows):
            keys = set(row)
            unexpected = sorted(keys - expected)
            missing = sorted(expected - keys)
            if unexpected:
                raise MetricOutputError(
                    f"metric {spec.name!r} row {index} has undeclared key(s) {unexpected}; "
                    f"declared columns are {list(spec.columns)}"
                )
            if missing:
                raise MetricOutputError(
                    f"metric {spec.name!r} row {index} is missing declared column(s) {missing}"
                )
        outputs.append(MetricOutput(name=spec.name, columns=spec.columns, rows=rows))
    return tuple(outputs)
