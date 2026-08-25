# Feature 04 — The metric registry

**Status:** Specified
**PMA feature ID:** F-04
**ADRs this depends on:** ADR-005 (additive contracts), ADR-008 (the extension surface), ADR-009 (stdlib), ADR-010 (no DSL), ADR-011 (a raising metric fails the run)
**Open questions required:** none — all resolved

## Purpose

Make ADR-008 real: **a metric is one module plus one test.** Everything else — discovery,
execution order, export, documentation — follows from registration.

This is the feature the brief's differentiator rests on. If adding a metric costs more than
one file, a business analyst or an agent will not do it, and the pipeline is a report
generator rather than a foundation.

**It is specified and built together with F-01 and F-02, never alone.** A registry whose only
caller is its own test suite is AP-11 — the anti-pattern `CLAUDE.md` forbids, and the one
coding agents produce most reliably.

## Input contract

```python
def metric(
    *,
    name: str,                              # also the output filename - a public contract
    question: str,                          # MANDATORY, non-empty
    grain: tuple[str, ...],                 # the columns that make a row unique
    columns: tuple[str, ...],               # every column, in output order
    measures: Mapping[str, str] = {},       # column -> the formula behind it, in words
) -> Callable[[MetricFn], MetricFn]: ...

MetricFn = Callable[[Dataset], Sequence[Mapping[str, object]]]
```

`measures` exists for one reason: any figure with more than one defensible definition must
carry its definition. `avg_unit_price` is the live case (OQ-08) — `mean(price/quantity)` and
`sum(price)/sum(quantity)` differ materially on this data, where unit price spans 0.30–884.60
for every NDC. The formula appears in `docs/METRICS.md` and beside the column in the export,
so the definition travels with the number.

## What the feature comprises

| Piece | Responsibility |
|---|---|
| `@metric` | Validate the declaration **at import time**. Register the function |
| `registry` | Name → declaration + function. Rejects duplicate names |
| `discover()` | Import every module in `metrics/` via `pkgutil.iter_modules` so decorators fire |
| `run_all(dataset)` | Execute metrics in **sorted name order**, validate every returned row against `columns` |
| writers | `out/<name>.csv` and `out/<name>.json` per metric |
| `render_catalog()` | Produce `docs/METRICS.md` from the registry |

## Output contract

```python
@dataclass(frozen=True)
class MetricOutput:
    name: str
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, object], ...]
```

Files land per §2.5 of the PMA. `Decimal` serializes to its exact string form in JSON — never
via `float`, which would undo ADR-009 at the last step.

## Failure policy

Per ADR-011, quarantine is for **data**. A metric is **code**:

| Failure | When | Result |
|---|---|---|
| Empty `question` | import | raises, naming the module |
| Duplicate `name` | import | raises, naming both modules |
| Row has a key not in `columns` | run | run fails, naming metric and key |
| Row missing a declared column | run | run fails, naming metric and column |
| Metric raises | run | run fails, exception propagates |
| `docs/METRICS.md` out of date | `make lint` | lint fails, prints the regeneration command |

Import-time failures are deliberate: a malformed declaration should be impossible to ship,
not caught on the run that needed it.

## Acceptance criteria

`tests/bdd/features/metric_registry.feature`. Failure paths first.

## Non-goals

- Any actual metric — F-03 and the proposed set (OQ-06) supply those. This feature ships with
  the registry plus **at least one real metric wired to the real CLI**, so the tested path is
  the production path.
- A metric definition language, an MCP server, a semantic layer — refused by ADR-010.
- Parallel or incremental execution. Metrics are pure; parallelism is available later and
  buys nothing at 69 ms per pass.

## Conflict Check

| ADR / Contract | Touched? | How | Verdict |
|---|---|---|---|
| ADR-003 layers | **yes** | `metrics/` may not import `gateway/` or touch IO | compatible — **watch item:** the *writers* do IO, so they belong in `gateway/`, not `metrics/`. The arch lint will enforce this and it is easy to get wrong |
| ADR-004 two tiers | yes | Registry behaviour is deterministic and needs no disk | compatible — writer tests use `tmp_path`; the sample-data run is system tier |
| ADR-005 additive | **yes** | `name` is the output filename, `columns` is the schema | compatible — renaming either is a breaking change requiring an ADR |
| ADR-008 extension surface | **yes** | Implements it | compatible — signature exactly as amended |
| ADR-009 stdlib | yes | `pkgutil`, `importlib`, `csv`, `json`, `decimal` | compatible |
| ADR-010 no DSL | **yes** | The decorator carries declarative metadata without an interpreter | compatible — this is the line ADR-010 draws; adding conditional logic to `@metric` arguments would cross it |
| ADR-011 failure policy | **yes** | A raising metric fails the run | compatible |
| ADR-012/013/014 | no | Metrics receive an already-resolved `Dataset` | no interaction |
| §1.3.4 byte-identical | **yes** | Execution order, row order, `Decimal` serialization | compatible — sorted names, metrics return sorted rows, `Decimal` via `str` |
| AP-11 tested path == shipped path | **yes** | The whole risk of this feature | compatible **only if** shipped with F-01/F-02 and a real metric on the real CLI path |

**Two watch items recorded:** (1) writers belong in `gateway/`, because they perform IO —
the natural instinct is to put them next to the registry, and the arch lint will reject it;
(2) `discover()` importing modules makes import side effects load-bearing, so it must be
idempotent and independent of import order — hence execution sorted by name.

## Definition of Done

- [ ] PMA updated in the same change as the code
- [ ] All `metric_registry.feature` scenarios pass
- [ ] Unit tests cover every row in the failure-policy table
- [ ] `grep -rn "run_all" src/ | grep -v tests` shows a non-test caller (AP-11 gate)
- [ ] `docs/METRICS.md` is generated, and its drift check runs in `make lint` and CI
- [ ] `make check` output pasted into the session
- [ ] This file marked `Status: Done`
