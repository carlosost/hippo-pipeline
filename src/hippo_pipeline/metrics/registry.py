"""The metric registry - the whole of ADR-008's "framework", and deliberately small.

A metric is one module plus one test. Everything else - discovery, execution order,
export, documentation - follows from registration. If adding a metric cost more than one
file, an analyst or an agent would not do it, and the pipeline would be a report generator
rather than a foundation.

Declaration errors raise at **import time**, not at run time: a malformed metric should be
impossible to ship, not caught by the run that needed it.

===============================================================================
IF YOU HAVE NOT MET DECORATORS BEFORE, READ THIS FIRST
===============================================================================

Everything clever in this file rests on three ordinary Python facts. None of them is
magic; the syntax just hides the plumbing.

--- 1. Functions are objects -------------------------------------------------

In Python a function is a value like any other. You can put it in a variable, in a list,
pass it as an argument, and return it from another function:

    def shout(text):
        return text.upper()

    f = shout                 # no parentheses: this is the function itself, not a call
    print(f("hi"))            # -> "HI"      f and shout are the SAME object

    handlers = [shout, str.strip]      # functions stored in a list
    def pick():
        return shout                    # a function returned from a function

That last one is the door everything else walks through.

--- 2. A decorator is a function that takes a function and returns a function -

That is the entire definition. There is no other rule.

    def announce(func):           # takes a function
        def wrapper(text):
            print("about to run", func.__name__)
            return func(text)
        return wrapper            # returns a function

The `@` syntax is *only* shorthand. These two snippets are identical - same objects, same
result, no difference whatsoever:

    @announce                     |    def shout(text):
    def shout(text):              |        return text.upper()
        return text.upper()       |    shout = announce(shout)

Read `@d` above `def f` as "after defining f, do `f = d(f)`". Whatever `d` returns is what
the name `f` now points at.

--- 3. A decorator WITH ARGUMENTS needs one more layer ------------------------

Look closely at how this file's decorator is used:

    @metric(name="revenue", question="How much?", grain=("npi",), columns=("npi", "rev"))
    def revenue(data):
        ...

There are two sets of parentheses, so there are two steps. `metric(...)` is *called
first*, all by itself, before any decorating happens. Whatever it returns is then used as
the decorator. Desugared, the snippet above is exactly:

    def revenue(data):
        ...
    decorator = metric(name="revenue", question="How much?", ...)   # step 1: call it
    revenue   = decorator(revenue)                                  # step 2: decorate

So `metric` is not itself a decorator. It is a **decorator factory**: a function whose job
is to build and hand back a decorator. That is why it has a function nested inside it
(`register`), and why its return type is written `Callable[[MetricFn], MetricFn]` - "a
callable that takes a metric function and gives back a metric function".

Three layers, then:

    metric(...)        the factory        you call this        returns ->
      register(fn)     the decorator      Python calls this    returns ->
        fn             the metric itself  the pipeline calls this

--- 4. Why `register` can still see `name` --------------------------------------

`metric` has already returned by the time Python calls `register`. Its local variables
should be gone. They are not, because `register` was *defined inside* `metric` and refers
to them - so Python keeps them alive, attached to `register`. A function bundled together
with the variables it captured is called a **closure**.

This is what lets one shared `register` handle every metric: each call to `metric(...)`
produces a *different* `register` closure, each remembering its own `name`, `question`,
`columns`, and so on.

--- 5. The part that makes discovery possible ---------------------------------

Both steps in section 3 run **when Python imports the module** - not when anything calls
the metric. Importing `metrics/pharmacy_performance.py` is enough to put that metric in
the dictionary below.

That is the whole trick behind `discover()`: import every module in this package, and the
decorators register everything as a side effect of the import. Nothing keeps a list of
metrics by hand, so nobody can forget to update it.

--- 6. Why this decorator returns the function UNCHANGED ----------------------

Most tutorial decorators (timing, caching, retries) build a *new* wrapper function and
return that instead of the original. Ours does not: it records the function in a
dictionary and hands the very same object back (`return fn` at the end of `register`).

The decoration is a pure side effect. The function you wrote is the function that runs,
undisturbed - which is why it stays trivially unit-testable by importing and calling it
directly, and why `fn.__module__` below still reports the real file it was defined in.

If you ever *do* write a wrapping decorator, remember `functools.wraps`: without it the
wrapper replaces the original's `__name__` and `__doc__`, and error messages, `help()` and
debuggers all start lying to you. We need no such thing here, precisely because we wrap
nothing.
===============================================================================
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from hippo_pipeline.domain.models import Dataset

# The shape every metric function must have, given a name so it can be written once.
# Read it as: "takes a Dataset, returns a sequence of rows; a row maps column name -> value".
# `object` rather than a narrower type because a row legitimately mixes str, int, Decimal
# and None.
MetricFn = Callable[[Dataset], Sequence[Mapping[str, object]]]

# Modules in this package that are machinery, not metrics. `discover()` skips them, or it
# would import the registry from inside the registry.
_INTERNAL_MODULES = frozenset({"registry", "catalog"})


class MetricDeclarationError(ValueError):
    """A metric is declared wrongly. Raised at import time."""


class MetricOutputError(ValueError):
    """A metric returned rows that do not match its declared columns. Raised at run time."""


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """A registered metric: its declaration plus the function that computes it.

    `frozen=True` makes instances immutable - assigning to a field raises. That matters
    because this object is shared: the runner, the catalogue renderer and the tests all
    read the same instance, and none of them should be able to change what another sees.

    `slots=True` tells Python to store the fields in a fixed layout instead of a per-object
    dictionary. Slightly smaller and faster, and it makes a typo like `spec.colums = ...`
    an immediate error rather than a silently created new attribute.
    """

    name: str
    question: str
    grain: tuple[str, ...]
    columns: tuple[str, ...]
    measures: Mapping[str, str]
    fn: MetricFn  # the decorated function itself, stored so run_all can call it later
    module: str  # where it was defined, so error messages can point at the right file


@dataclass(frozen=True, slots=True)
class MetricOutput:
    """One metric's computed result, ready to be written out."""

    name: str
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, object], ...]


# The registry itself: metric name -> its spec. Module-level, so there is exactly one per
# process, and every import of this module sees the same dictionary.
#
# A module-level mutable like this is global state, which is usually worth being nervous
# about. It is acceptable here for two reasons: it is written only during imports (never
# during a run), and `reset_registry()` gives tests a way to isolate themselves. If it were
# written while the pipeline was running, this would be a bug waiting to happen.
_REGISTRY: dict[str, MetricSpec] = {}


def metric(
    # The bare `*` means everything after it is KEYWORD-ONLY: callers must write
    # `metric(name="revenue", ...)` and cannot write `metric("revenue", ...)`. Deliberate -
    # six positional arguments in a fixed order is a call site nobody can read, and it
    # would make reordering the parameters a silent breaking change.
    *,
    name: str,
    question: str,
    grain: Sequence[str],
    columns: Sequence[str],
    measures: Mapping[str, str] | None = None,
) -> Callable[[MetricFn], MetricFn]:
    """Declare and register a metric.

    This is the **decorator factory** described in section 3 of the module docstring: you
    call it, and it returns the actual decorator (`register`) for Python to apply.

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

    Returns:
        The decorator. Python applies it to the function written directly below the `@`.
    """

    # Defined *inside* `metric`, so it closes over name/question/grain/columns/measures.
    # See section 4 of the module docstring: those values stay alive for as long as this
    # function does, even though `metric` itself has already returned by the time Python
    # calls this.
    def register(fn: MetricFn) -> MetricFn:
        # `fn` is the function written under the `@`. Python passes it in automatically.
        # `__module__` is set by Python at definition time and still holds the real
        # defining module, because we never wrap the function (module docstring, section 6).
        # `getattr` with a default keeps this safe for anything callable that lacks it.
        module = getattr(fn, "__module__", "<unknown>")

        # Validate NOW, while the module is being imported. A malformed declaration then
        # fails at startup instead of during the run that needed the number.
        _validate(name, question, grain, columns, measures or {}, module)

        if name in _REGISTRY:
            # Two metrics writing to `out/revenue.csv` would silently overwrite each other,
            # so name collisions are fatal. The message names both files: whoever hits this
            # needs to know which two are fighting, not merely that a fight happened.
            raise MetricDeclarationError(
                f"duplicate metric name {name!r}: declared in {_REGISTRY[name].module} "
                f"and again in {module}"
            )

        _REGISTRY[name] = MetricSpec(
            name=name,
            # Collapse any run of whitespace to single spaces. Questions are written as
            # multi-line strings in the source, and the catalogue renders them into a
            # Markdown table where a stray newline would break the row.
            question=" ".join(question.split()),
            # Convert to tuples: MetricSpec is frozen, and a frozen dataclass holding a
            # mutable list is only shallowly immutable - a caller could still append to it.
            grain=tuple(grain),
            columns=tuple(columns),
            # Sorted so the catalogue renders identically on every run. Byte-identical
            # output is a project-wide guarantee (charter 1.3.4), and dictionary order
            # here would otherwise follow however the author happened to type them.
            measures={k: measures[k] for k in sorted(measures)} if measures else {},
            fn=fn,
            module=module,
        )

        # Hand back the ORIGINAL function, unchanged. Registration was the point; wrapping
        # was never needed. See section 6 of the module docstring.
        return fn

    # `metric(...)` evaluates to this. Note: no parentheses - we are returning the function
    # object itself for Python to call later, not calling it now.
    return register


def _validate(
    name: str,
    question: str,
    grain: Sequence[str],
    columns: Sequence[str],
    measures: Mapping[str, str],
    module: str,
) -> None:
    """Reject a malformed declaration, naming the module that wrote it.

    Leading underscore = private by convention. Python does not enforce it, but it tells
    every reader that nothing outside this file should call it.

    Every message says what is wrong *and* why the rule exists. An error that only says
    "invalid name" sends the reader here to find out what "valid" means.
    """
    where = f"(declared in {module})"

    # The name becomes `out/<name>.csv`, so anything a filesystem would object to - a
    # slash, a space, an accent - has to be rejected before it becomes a path.
    if not name or not name.replace("_", "").isalnum():
        raise MetricDeclarationError(
            f"metric name {name!r} must be alphanumeric with underscores {where}; "
            f"it becomes a filename"
        )

    # `.strip()` so a question of "   " counts as absent. ADR-008 makes this mandatory:
    # a metric nobody can state a purpose for should not reach a reviewer.
    if not question.strip():
        raise MetricDeclarationError(
            f"metric {name!r} has no question {where}; a metric without a stated business "
            f"question is decoration"
        )

    if not columns:
        raise MetricDeclarationError(f"metric {name!r} declares no columns {where}")

    # A set discards duplicates, so a shorter set means the original had repeats. A
    # duplicated column would quietly overwrite itself in the output row.
    if len(set(columns)) != len(columns):
        raise MetricDeclarationError(f"metric {name!r} declares a duplicate column {where}")

    if not grain:
        raise MetricDeclarationError(f"metric {name!r} declares no grain {where}")

    # The grain is what makes a row unique, so every grain column must actually be output.
    # Collect all the offenders rather than raising on the first: fixing declarations one
    # error per run is a miserable loop.
    unknown_grain = [c for c in grain if c not in columns]
    if unknown_grain:
        raise MetricDeclarationError(
            f"metric {name!r} grain {unknown_grain} is not among its columns {where}"
        )

    # A formula documenting a column that is not emitted is a stale comment with a schema.
    # Iterating a dict yields its keys, so this checks the measure names.
    unknown_measures = [c for c in measures if c not in columns]
    if unknown_measures:
        raise MetricDeclarationError(
            f"metric {name!r} declares formulas for non-columns {unknown_measures} {where}"
        )


def registered() -> tuple[MetricSpec, ...]:
    """Every registered metric, sorted by name.

    Sorted, not insertion-ordered: `discover()` makes import side effects load-bearing, so
    execution order must not depend on which module happened to be imported first.

    Returns a tuple rather than the dictionary itself. Handing out the live `_REGISTRY`
    would let any caller mutate the registry by accident; a tuple cannot be changed.
    """
    return tuple(_REGISTRY[name] for name in sorted(_REGISTRY))


def reset_registry() -> None:
    """Empty the registry. For tests only - production never unregisters a metric.

    Tests declare throwaway metrics, and without this each test would inherit whatever the
    previous one registered - including duplicate-name collisions that have nothing to do
    with the behaviour under test.
    """
    _REGISTRY.clear()


def discover(package_name: str | None = None) -> None:
    """Import every metric module so its decorator runs. Idempotent.

    This is section 5 of the module docstring turned into code. It does not read the
    metrics - it merely *imports* them, and the `@metric` decorators do the registering as
    a side effect of being imported.

    Idempotent because Python caches imports in `sys.modules`: importing a module a second
    time returns the cached object without re-executing it, so decorators run exactly once
    and no metric is ever registered twice.

    `package_name` exists so the acceptance tests can point the real discovery at a
    throwaway package. Testing it by calling the decorator directly would verify the
    decorator, not discovery.
    """
    # `__package__` is "hippo_pipeline.metrics" when this file is imported normally; the
    # final fallback covers exotic execution contexts where it is unset.
    package = importlib.import_module(package_name or __package__ or "hippo_pipeline.metrics")

    # `__path__` is the directory (or directories) a package lives in. `pkgutil.iter_modules`
    # lists the modules inside it without importing them, so we can filter first.
    # Sorted for determinism, though registration order does not matter - `registered()`
    # sorts again. Two cheap guarantees are better than one clever one.
    for info in sorted(pkgutil.iter_modules(list(package.__path__)), key=lambda m: m.name):
        # Skip private helpers (`_stats`) and the machinery in this package.
        if info.name.startswith("_") or info.name in _INTERNAL_MODULES:
            continue
        # The import itself is the whole operation. Nothing is done with the returned module
        # object, because the decorator has already put what we need into `_REGISTRY`.
        importlib.import_module(f"{package.__name__}.{info.name}")


def run_all(dataset: Dataset) -> tuple[MetricOutput, ...]:
    """Execute every registered metric and validate its rows against its declaration.

    A metric that raises is *not* quarantined. Quarantine is for data (ADR-011); a defect
    in our own code is not a data-quality event, and routing it into a rejects file is how
    a bug ships disguised as a bad record. So no try/except here on purpose: the exception
    propagates, the run fails, and the CLI writes no metric files at all (ADR-017).
    """
    outputs: list[MetricOutput] = []

    for spec in registered():
        # `spec.fn` is the original decorated function. Calling it here is the only place
        # a metric is ever executed. `tuple(...)` forces the result now, so a metric that
        # returns a lazy generator cannot defer its work - or its exceptions - to some
        # later point where the error would be much harder to attribute.
        rows = tuple(spec.fn(dataset))

        expected = set(spec.columns)
        for index, row in enumerate(rows):
            keys = set(row)
            # Set difference both ways answers two different questions:
            #   keys - expected  -> columns the metric produced but never declared
            #   expected - keys  -> columns it declared but forgot to produce
            # Sorted so the message reads the same on every run.
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
