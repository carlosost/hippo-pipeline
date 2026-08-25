# Project Memory Asset — `hippo-pipeline`

> **This document is the source of truth for the project.** Read it in full before any
> structural change. Every ADR, data contract and open question lives here. Decisions
> are append-only: a superseded ADR is marked `Superseded` and kept, never deleted —
> the *reason* a decision was made is usually worth more than the decision.
>
> Process: `docs/GENERAL_ENGINEERING_PLAYBOOK.md`. Agent contract: `CLAUDE.md`.
> Session history: `docs/DECISION_LOG.md`.

**Last updated:** 2026-08-25 (session 004) · **Phase:** fully specified — every structural decision made, implementation not started

---

## 1. Charter

### 1.1 The problem

A Pharmacy Benefit Manager needs trustworthy aggregates over two event streams:
**claims** (a pharmacy filled a prescription — real money, real volume) and **reverts**
(the fill did not complete, most often because the patient never collected the drug).
A reverted claim must be treated as though the fill never happened for revenue and
volume purposes, while the reversal itself remains a measurable operational signal.

Full brief: `docs/ASSIGNMENT.md`.

### 1.2 Who consumes the output

| Consumer | What they need | Design consequence |
|---|---|---|
| Business analysts | Correct, explainable aggregates per pharmacy, chain and drug | Every number must be traceable to the records that produced it |
| **AI agents acting for those analysts** | To answer new questions and add metrics *without reading the ingestion code* | The metric layer must be declarative and separately addressable; column meanings must be machine-readable, not folklore |
| Data engineers | To extend the pipeline with new sources and metrics | Layer boundaries enforced by tooling, not by convention |

The second row is the one that changes the architecture. A pipeline that only a human
who has read `gateway/` can extend does not satisfy the brief.

### 1.3 Success criteria

1. The required metrics are correct and the correctness is demonstrable from tests.
2. Malformed and out-of-scope records are handled by a **stated, tested policy** — never
   silently dropped.
3. A new metric can be added without touching ingestion or IO code.
4. Re-running the pipeline over the same inputs produces byte-identical outputs.
5. The reasoning — trade-offs, alternatives rejected, where this goes next — is legible
   in this document.

### 1.4 Explicit non-goals (for now)

- Real-time / streaming ingestion. Inputs are directories of files; this is batch.
- A serving API or dashboard. The deliverable is a pipeline and its outputs.
- Distributed execution. Justified only if OQ-01 concludes the data volume needs it.
- Anything resembling PHI handling. The sample data carries none, and inventing a
  compliance layer for data that does not exist is scope theatre.

---

## 2. Canonical data contracts

### 2.1 Input — pharmacy reference data (CSV)

Slowly-changing reference data. Header order in the sample file is `chain,npi`, **not**
the order given in the brief — column access is by name, never by position.

| field | type | notes |
|---|---|---|
| `npi` | string | pharmacy identifier. **Leading zeros are significant — must never be parsed as a number.** |
| `chain` | string | chain the pharmacy belongs to |

This file defines the universe: an event whose `npi` is absent from it is out of scope
(brief: *"We're only interested in events for pharmacies that exist in the pharmacy
dataset"*).

### 2.2 Input — claim event (JSON array per file)

| field | type | notes |
|---|---|---|
| `id` | string (UUID) | claim identifier |
| `npi` | string | pharmacy that filled the claim |
| `ndc` | string | drug identifier. **Leading zeros significant** (9 of 10 sample NDCs start with `0`). |
| `price` | float | **total** price charged = `unit_price × quantity` |
| `quantity` | int **or** float | units dispensed — both appear in the sample data |
| `timestamp` | datetime | naive ISO-8601, no offset |

### 2.3 Input — revert event (JSON array per file)

| field | type | notes |
|---|---|---|
| `id` | string (UUID) | revert identifier — **not unique in the sample data** (see 2.4) |
| `claim_id` | string (UUID) | the claim being invalidated |
| `timestamp` | datetime | naive ISO-8601, no offset |

### 2.4 Observed reality of the sample dataset

Reproduce every number here with `python3 scripts/profile_sample_data.py`. These are
measurements, not assumptions — each one either constrains the design or seeds an open
question.

| Observation | Value | Why it matters |
|---|---|---|
| Pharmacies | 17 NPIs across 3 chains (`health`, `saint`, `doctor`) | Tiny reference dimension — always broadcastable, never a join bottleneck |
| Claim files / schema-valid claims | 28 files / 27,074 records | Small enough that a single process is viable; see OQ-01 |
| Claims referencing an NPI **not** in the pharmacy file | 4,085 (15.1%), across exactly 3 NPIs (`0000000000`, `6789012345`, `2345678901`) | Filtering is not an edge case — it moves every headline number by ~15% |
| Claims missing `quantity` | 2 | Schema violation, must be quarantined not crashed on |
| Claims with `quantity == 0` | 1 | **Division by zero** in any unit-price metric. Passes a naive schema check. |
| The 3 bad claims | all `npi=3333333333`, all `price=159228.0`, all `timestamp=2026-01-01T12:12:22` | Deliberately injected. `3333333333` **is** a valid pharmacy, so "bad NPI" is not a usable filter for them. |
| Duplicate claim `id`s | 0 | Claim id is a usable primary key *in this sample*; do not assume it holds |
| Distinct NDCs | 10, all 11 characters | |
| Timestamps | `2026-01-01T00:00:07` .. `2026-05-01T23:59:57`, all naive | No timezone to reason about, but also no timezone recorded — see OQ-10 |
| Revert files / records | 4 files / 308 records | |
| Repeated revert `id`s | **3 ids appear twice, each with a *different* `timestamp`** | Revert `id` is **not** a primary key. Deduplicating on `id` alone silently discards a record; not deduplicating double-counts a reversal. See OQ-04. |
| Reverts pointing at an unknown `claim_id` | 0 | The sample does not exercise orphan reverts. The pipeline must still decide — see OQ-03 |
| Reverts timestamped **before** the claim they cancel | 2 | Physically impossible. Data-quality signal, not a crash |
| Reverts against claims of an out-of-scope NPI | 45 | These must disappear with their claims, or reversal counts break |
| Revert rate | 1.14% of schema-valid claims | Any per-pharmacy reversal-rate metric will have small denominators — significance matters |
| Unit price (`price/quantity`) | min `0.30`, max `884.60`, **identical bounds for every NDC** | Synthetic, heavy-tailed. `mean(price)/mean(quantity)` and `mean(price/quantity)` will differ materially — see OQ-08 |

### 2.5 Output contracts

Fixed by ADR-008 (format and layout) and ADR-011 (the quarantine sinks and the manifest).
What each metric's columns are remains open — that is OQ-06 and OQ-08, and each metric
declares its own.

Every run writes to `out/`:

| Path | Contents | Fixed by |
|---|---|---|
| `out/<metric_name>.csv` | one file per registered metric, columns as declared in `@metric` | ADR-008 |
| `out/<metric_name>.json` | the same rows, for consumers that prefer JSON | ADR-008 |
| `out/_rejected.csv` | schema-invalid records: source file, record index, reason codes, raw record | ADR-011 |
| `out/_excluded.csv` | valid records outside our pharmacy scope, same shape | ADR-011 |
| `out/_manifest.json` | records read / accepted / rejected / excluded, counts per reason code, counts per source file, reject rate, and the run's parameters | ADR-011 |

Two invariants hold across every run and are tests, not comments:

- `read == accepted + rejected + excluded`
- identical inputs produce byte-identical outputs (charter §1.3.4) — which is why metrics
  execute in sorted name order and emit sorted rows, and why money is `Decimal`

The rule is fixed by ADR-005: output schemas are **additive only**. New fields arrive with
a default; existing fields are never removed or retyped without an ADR naming the affected
consumers. Reason codes are part of that contract — adding one is free, renaming one breaks
whoever aggregates by it.

---

## 3. Architecture Decision Records

Numbering is sequential and permanent. A superseded ADR keeps its number, is marked
`Superseded`, and points at its replacement.

| ADR | Title | Status |
|---|---|---|
| [ADR-001](#adr-001-this-document-is-the-source-of-truth-spec-driven-development) | This document is the source of truth (spec-driven development) | Accepted |
| [ADR-002](#adr-002-python--310-with-uv-as-the-toolchain) | Python ≥3.10 with uv as the toolchain | Accepted |
| [ADR-003](#adr-003-layered-package-with-a-single-io-chokepoint) | Layered package with a single IO chokepoint | Accepted |
| [ADR-004](#adr-004-two-tier-tests-with-acceptance-criteria-written-first) | Two-tier tests, acceptance criteria written first | Accepted |
| [ADR-005](#adr-005-output-contracts-are-additive-only) | Output contracts are additive only | Accepted |
| [ADR-006](#adr-006-trunk-based-development-with-conventional-commits) | Trunk-based development with Conventional Commits | Accepted |
| [ADR-007](#adr-007-the-repository-is-an-agent-contract-enforced-by-tooling) | The repository is an agent contract, enforced by tooling | Accepted (amended) |
| [ADR-008](#adr-008-metrics-are-registered-python-functions-over-an-exported-fact-table) | Metrics are registered Python functions over an exported fact table | Accepted |
| [ADR-009](#adr-009-the-python-standard-library-is-the-compute-engine-zero-runtime-dependencies) | The Python standard library is the compute engine; zero runtime dependencies | Accepted |
| [ADR-010](#adr-010-no-metric-definition-language-no-mcp-server-no-semantic-layer) | No metric definition language, no MCP server, no semantic layer | Accepted |
| [ADR-011](#adr-011-malformed-records-are-quarantined-out-of-scope-records-are-excluded-separately) | Malformed records are quarantined; out-of-scope records are excluded separately | Accepted (amended) |
| [ADR-012](#adr-012-revert-resolution--a-claim-is-reverted-at-most-once-keyed-on-claim_id) | Revert resolution — a claim is reverted at most once, keyed on `claim_id` | Accepted |
| [ADR-013](#adr-013-all-timestamps-are-interpreted-as-utc-and-the-assumption-is-published) | All timestamps are interpreted as UTC, and the assumption is published | Accepted |
| [ADR-014](#adr-014-pharmacy-reference-data-is-current-state-not-point-in-time) | Pharmacy reference data is current-state, not point-in-time | Accepted |

**On numbering.** Session 001 pre-assigned ADR numbers to decisions that had not been made
(`OQ-07 → ADR-013`). That was a mistake: numbers are assigned when an ADR is *written*, and
questions are not answered in ID order. OQ-07 was decided first and therefore holds ADR-008.
Reserving numbers for unwritten decisions guarantees gaps and misleading cross-references.

---

### ADR-001: This document is the source of truth (spec-driven development)

**Date:** 2026-08-24 · **Status:** Accepted

**Context.** The work is done across many sessions with an AI assistant that starts each
session with no memory. Without a single accumulated context file, session 8 contradicts
decisions made in session 2, and the contradiction surfaces only after tests, docs and
follow-on features have been built on the wrong assumption. Rework cost compounds per
layer.

**Decision.** `docs/PROJECT_MEMORY.md` is the authoritative record of the charter, all
ADRs, all data contracts, the feature log and all open questions. Every session begins
by reading it. Every structural change updates it **in the same response as the code**,
never deferred. Decisions are append-only.

**Consequences.** Any change to a contract requires an ADR before the code. A PMA two
sessions behind is worse than no PMA — it is misleading context — so freshness is
enforced mechanically by a `PostToolUse` hook (ADR-007) and by the pre-merge checklist.

**Alternatives considered.** *ADRs as separate files under `docs/adr/`* — better for a
large team with parallel ADR authorship; worse here, because the whole value is that one
file can be read into context in one action. *Git history as the record* — `git blame`
tells you what changed, never why the alternative was rejected.

---

### ADR-002: Python ≥3.10 with uv as the toolchain

**Date:** 2026-08-24 · **Status:** Accepted

**Context.** The brief requires Python and leaves the build tool open. A reviewer must be
able to clone and run. CI and the reviewer's machine must resolve to the same
dependency versions, or a green CI proves nothing about their run.

**Decision.** `uv` with `pyproject.toml` and a committed `uv.lock`. `requires-python =
">=3.10"`. Dev tooling lives in a PEP 735 dependency group: ruff (lint + format), mypy
(strict), pytest, pytest-bdd, pip-audit.

**Consequences.** A reviewer needs `uv` installed — one curl command, and the README says
so. The lockfile is a reviewed artifact: a dependency bump is a visible diff. Runtime
`dependencies` stays **empty** until OQ-01 is resolved, so the choice of compute engine
is a deliberate, ADR-backed act rather than an import that crept in.

**Alternatives considered.** *Poetry* — mature and widely recognised, but slower to
resolve and heavier in CI. *pip + requirements.txt* — nothing to install, but no real
lockfile, so transitive versions drift between the reviewer's machine and CI, which is
precisely the failure this ADR exists to prevent.

---

### ADR-003: Layered package with a single IO chokepoint

**Date:** 2026-08-24 · **Status:** Accepted

**Context.** The pipeline's testability, its swappability of compute engine (still open,
OQ-01), and the brief's requirement that others extend it, all depend on the same thing:
business rules must not be entangled with file reading and parsing.

**Decision.** Four layers inside `src/hippo_pipeline/`:

```
gateway/   the ONLY code permitted to touch the filesystem or parse raw bytes.
           Owns every file handle, every decode, every retry and timeout.
domain/    pure types and transformation rules. No IO, no logging, no clock.
metrics/   aggregations over domain types. Pure functions, individually addressable.
cli.py     the single production entry point. The only place print() is allowed.
```

Every external dependency is obtained from a **factory function**; no module constructs
a client directly. Tests mock the factory, never an implementation class.

**Consequences.** `domain/` and `metrics/` are unit-testable with zero mocks and zero
fixtures on disk — which is what makes the deterministic tier fast enough to run on
every save. Swapping the compute engine touches `gateway/` and the factories only.
Enforced on every file save and in CI by `scripts/lint_architecture.py`, which parses the
AST (not a regex — a grep-based lint matches its own documentation and gets disabled
within a week). The lint has its own unit tests: an unverified linter fails open.

**Alternatives considered.** *Convention documented in the README* — the exact discipline
that erodes the first time a deadline appears. *A framework-imposed structure (dbt,
Dagster, Kedro)* — real structure, but it decides OQ-01 by the back door and adds a
runtime dependency before an ADR justifies it.

---

### ADR-004: Two-tier tests, acceptance criteria written first

**Date:** 2026-08-24 · **Status:** Accepted

**Context.** Tests written after the implementation confirm what the code does rather
than what it should do. And a suite that mixes 5-second unit tests with 3-minute
full-dataset runs gets skipped, which makes it worthless as a gate.

**Decision.** Acceptance criteria are written as Gherkin in `tests/bdd/features/` before
implementation, failure paths first. Tests are split into two tiers:

| Tier | Location | Dependencies | Gate |
|---|---|---|---|
| Deterministic | `tests/unit`, `tests/bdd` | none — no IO, no network, no clock | **100%, blocks merge** |
| System-behavior | `tests/system` | real files from `data/sample-data/` | compared to a recorded baseline; **not** a merge gate |

System-tier assertions are never `==` on timing; they are `>= baseline` or
`within 20% of baseline`.

**Consequences.** `make test` runs only the deterministic tiers and must stay fast enough
to run on every save. A test needing more than two mocked collaborators is a signal it is
testing implementation, and belongs in the system tier with real ones. At least one test
must drive `cli.py` itself — the tested path has to be the shipped path (AP-11).

**Alternatives considered.** *One suite, no tiers* — simpler until the day the slow tests
make the fast gate unusable. *Coverage percentage as the gate* — measures lines executed,
not contracts honoured, and is trivially satisfied by tests that assert nothing.

---

### ADR-005: Output contracts are additive only

**Date:** 2026-08-24 · **Status:** Accepted

**Context.** The brief asks for a foundation that others — including AI agents — build
on. Anything built on an output becomes a consumer, and a consumer that breaks silently
is worse than one that breaks loudly.

**Decision.** Once an output schema ships, fields are added with a default and are never
removed or retyped. A breaking change requires a new versioned output alongside the old
one plus an ADR naming every affected consumer. Every output carries a `schema_version`.

**Consequences.** Field naming deserves real thought the first time, because it is
effectively permanent. Deprecation is an explicit, dated act rather than a deletion.

**Alternatives considered.** *Break freely while pre-1.0* — defensible if there were no
consumers, but the brief's premise is that consumers appear immediately, and agent
consumers are the least able to notice a silent rename.

---

### ADR-006: Trunk-based development with Conventional Commits

**Date:** 2026-08-24 · **Status:** Accepted

**Context.** Long-lived branches accumulate merge conflicts and diverge from `main`; a
repository that is also a work sample must have history a reviewer can read.

**Decision.** `main` is always releasable. Branches live 1–3 days. Commit messages follow
Conventional Commits, imperative mood, one logical change per commit; a commit carrying
an ADR names the ADR in its body. Partially-built behaviour is hidden behind a flag
rather than parked on a branch.

**Consequences.** The commit log is a readable narrative of the project. Squash-merging
is deliberate: the branch's noise is dropped, the message is not.

**Alternatives considered.** *Git Flow* — built for versioned releases with support
branches; unnecessary weight for a single-deliverable pipeline.

---

### ADR-007: The repository is an agent contract, enforced by tooling

**Date:** 2026-08-24 · **Amended:** 2026-08-25 · **Status:** Accepted

**Context.** Every rule in this document is worth exactly as much as its enforcement. A
convention that lives only in prose is followed until the first deadline. This applies
with more force to AI assistants than to people: an assistant will produce confident,
locally-coherent code that violates a global constraint it was never mechanically
reminded of.

**Decision.** Three layers of enforcement:

1. **`CLAUDE.md`** — the session contract: read the PMA, run the Conflict Check, spec
   before code, Definition of Done. Loaded automatically at session start.
2. **`.claude/settings.json`** — five `PostToolUse` hooks firing on every write/edit:
   architectural lint (ADR-003), auto-run of the matching unit test, config syntax
   validation, Makefile↔README drift, and a PMA freshness reminder.
3. **`.claude/commands/`** — `/session-start`, `/conflict-check`, `/new-feature`,
   `/pre-merge`: the playbook's prompt templates as executable slash commands, so the
   process is invoked rather than remembered.

**Amendment, 2026-08-25.** A fourth layer: one `PreToolUse` hook that **blocks** writes
to `data/sample-data`, plus `scripts/check_fixture_integrity.sh` in `make lint` and CI.
Added after five fixture files were found reformatted by an editor — identical content,
different bytes. The rule already existed in `CLAUDE.md`; only the enforcement was
missing, which is this ADR's own thesis turned on itself. Post-hooks report after the
fact; a fixture has to be protected before the write lands (playbook §5.4).

**Consequences.** Hooks fire **only in Claude Code CLI sessions** — not in Cowork, not on
claude.ai. Enforcement therefore cannot live in hooks alone: every hook check is also a
`make` target and a CI job, and CI is the real gate. Hooks must stay under ~2s or they
become latency that invites disabling them.

**Alternatives considered.** *Pre-commit hooks only* — fire once per commit, after a
whole session of drift; hooks fire per edit, when the context to fix it is still loaded.
*CI only* — correct but slow; a violation found 10 minutes later has already been built
on.

---

---

### ADR-008: Metrics are registered Python functions over an exported fact table

**Date:** 2026-08-25 · **Amended:** 2026-08-25 · **Status:** Accepted · **Resolves:** OQ-07

**Context.** The brief asks for a foundation that business teams *and AI agents working on
their behalf* can use autonomously to "extract metrics or extend with new functionality."
That sentence contains two different requests, and conflating them is what makes the
question feel unanswerable:

| | The request | Who asks | What actually satisfies it |
|---|---|---|---|
| **Read path** | "What's the reversal rate for chain *saint* in March?" — a question the data answers but no metric emits | an analyst, or an agent for them | a queryable output artifact; nothing in the repo changes |
| **Write path** | "From now on always emit reversal rate per chain per month" | whoever maintains the pipeline | a place to add a metric that requires no knowledge of ingestion |

Answering both with one mechanism is what pushes people toward a server or a definition
language. They are different problems and take different answers.

**Decision.** Two surfaces, one per path, plus a generated catalog.

**(A) Write path — metrics are plain Python functions, self-registering.** One metric per
module in `src/hippo_pipeline/metrics/`, declared with a decorator:

```python
@metric(
    name="pharmacy_ndc_summary",
    question="Per pharmacy and drug: how many fills, at what revenue, at what unit price?",
    grain=("npi", "ndc"),
    measures={"avg_unit_price": "sum(price) / sum(quantity)"},
)
def pharmacy_ndc_summary(claims: Sequence[Claim]) -> Sequence[Row]:
    ...
```

The registry is the entire framework. Adding a metric is **one module plus one unit test**;
discovery, execution, export and documentation follow from registration.

A metric receives an immutable, already-validated, already-revert-resolved dataset and
returns rows. It performs no IO, opens no files, and never sees a raw record.

**Amendment, 2026-08-25 — the signature is now fixed:**

```python
def <name>(data: Dataset) -> Sequence[Mapping[str, object]]: ...
```

`Dataset` is a frozen object exposing `.claims`, `.reverts` and `.pharmacies`. One
argument rather than a bare claim list, because several metrics worth proposing need chain
membership or revert timing — a reversal-rate-per-chain metric cannot be written against
`Sequence[Claim]` alone.

The cost, stated rather than discovered: every metric re-scans the claims, so the runner is
O(metrics × claims). At 27,076 records and 69 ms per pass, ten metrics cost under a second.
At 100M records with twenty metrics it is a problem, and the escape hatch is a fold/reducer
protocol where each metric declares an accumulator and one pass feeds them all. That is a
future ADR, taken when a measurement demands it — not now, because it makes writing a metric
materially harder and that works directly against this ADR's purpose.

**(B) Read path — every run writes a flat, self-describing export to `out/`:** the cleaned
fact table, one file per metric, and the quarantine table carrying each rejected record with
its reason. CSV and JSON only — the reader is not made to install anything. Any tool reads
it: the DuckDB CLI, pandas, Excel, `jq`.

**(C) `docs/METRICS.md` is generated from the registry**, and CI fails if it is out of date.
A stale catalog is worse than no catalog; generating it plus a drift check makes staleness
impossible rather than unlikely.

**Consequences.**

- The metric signature is a contract. Changing it is an ADR, not a refactor.
- The registry is the only dynamic behaviour in the codebase, so it must be import-order
  independent: metrics execute and export sorted by name, or output is not byte-identical
  (charter §1.3.4).
- `question=` is mandatory and `@metric` raises at import time when it is empty. A metric
  without a stated business question is decoration, and this is the cheapest possible place
  to enforce that.
- Any measure with more than one defensible definition — unit price above all, see OQ-08 —
  must carry its formula in `measures=`. The formula then appears in `METRICS.md` and beside
  the column in the export, so the definition travels with the number instead of living in a
  reviewer's memory.
- Adding a metric touches neither `gateway/` nor `domain/`. Guaranteed by ADR-003's lint plus
  the fact that metrics only ever receive domain objects.
- **The honest cost:** an agent extending this writes Python and runs the test suite. That is
  not a lower bar than a declaration language — it is a better one. The failure mode of a
  wrong function is a failing test; the failure mode of a wrong declaration is a plausible
  number nobody questions.

**Alternatives considered.**

| Option | What the extender must know | What we must build | Verdict |
|---|---|---|---|
| Ad-hoc functions, no registry | Python, the repo, and which function the runner calls | nothing | Rejected — no catalog, no discovery; the runner drifts from the functions |
| **Registered functions (chosen)** | Python and the `@metric` contract | ~20 lines | **Accepted** |
| **Exported artifact (chosen, complementary)** | SQL, or Excel | a writer | **Accepted** — answers the read path with no repo access at all |
| SQL views over a materialised table | SQL | an engine, plus SQL testing discipline | Rejected — requires a compute engine chosen *because* of this decision, which is circular; see ADR-009 |
| Declarative YAML/dataclass metric DSL | our invented schema | a language, an interpreter, its docs and its escape hatches | Rejected — see ADR-010 |
| MCP server exposing metrics as tools | all of the above, plus running a server | a server | Rejected — see ADR-010 |

Parquet was considered for the export and rejected: it needs `pyarrow`, which contradicts
ADR-009, and CSV plus JSON is readable by strictly more tools. Parquet is the obvious first
upgrade the day volume makes CSV painful, and it changes one writer.

---

### ADR-009: The Python standard library is the compute engine; zero runtime dependencies

**Date:** 2026-08-25 · **Status:** Accepted · **Resolves:** OQ-01 · **Depends on:** ADR-008

**Context.** OQ-01 was evaluated with the requirements-first method (playbook §1.2) and the
evaluation is committed and reproducible at
[`docs/spikes/oq-01-compute-engine/`](spikes/oq-01-compute-engine/README.md). Measured, not
assumed:

- A pure-stdlib streaming pass over all 27,076 records takes **69 ms** at 391k records/sec in
  39 MB. Throughput does not select the engine, and never did.
- pandas types `npi` as `int64` by default and turns `'0987654321'` into `987654321`.
- Polars' lazy path (`scan_ndjson`) cannot read JSON *array* files at all, and `read_json`
  loses an entire file to one non-object element.
- DuckDB satisfies every requirement natively and was the spike's leading recommendation —
  **explicitly conditional on OQ-07 landing on SQL.**

ADR-008 resolved OQ-07 to Python functions plus a flat export. DuckDB's decisive advantage,
SQL as the metric surface, no longer applies. What remained were per-record rejection with
reasons (natural in Python), larger-than-memory aggregation (not demonstrated — the whole
dataset aggregates in 39 MB), and throughput (not binding).

This is the sequencing correction from session 002 paying for itself: deciding the engine
first would have produced a different and worse answer.

**Decision.** The pipeline is implemented against the Python standard library only.
`[project] dependencies` in `pyproject.toml` stays empty, permanently, until an ADR
supersedes this one. Third-party packages remain permitted in the dev dependency group
(test, lint, type-check) and in spikes run under `uv run --with` — never in
`src/hippo_pipeline/`.

**Consequences.**

- `git clone && make setup && make run` installs nothing at runtime. For a deliverable
  somebody else has to run, that is the single strongest signal available.
- We own every line, and must test every line: reading, validation, the anti-join, the
  group-by, the writers. Deliberately accepted, and bounded — the whole pipeline is a few
  hundred lines. It also satisfies the brief's "you should be able to explain any part of
  it": there is no library behaviour to explain, only code.
- **Money uses `decimal.Decimal`, never `float`.** Float summation is order-dependent, which
  breaks byte-identical output. Prices are parsed from their string form so the value never
  round-trips through a float.
- Memory ceiling is O(reverted claim ids + output groups), not O(claims): files are read one
  at a time and only aggregate state is retained.
- **Known limitation, stated rather than discovered later:** `json.load` reads a whole file
  into memory, so the pipeline streams *across* files but not *within* one. Today the largest
  input file is 157 KB. A single file too large to hold is the first hard constraint that
  breaks this decision, and the stdlib has no good incremental JSON-array reader — that day
  needs a dependency, and therefore a new ADR.
- Enforced mechanically: `scripts/lint_architecture.py` gains a rule rejecting any non-stdlib
  import under `src/hippo_pipeline/`. Adding a runtime dependency now fails `make lint` and
  CI. A rule with no enforcement is followed until the first deadline (ADR-007).
- Reversal is cheap and scoped: the spike is committed, so re-deciding costs a reading, not a
  re-evaluation. By ADR-003 the rewrite lands in `gateway/`; nothing outside it changes.

**Alternatives considered.**

| Option | Complexity | Cost to reviewer | Where it fails here |
|---|---|---|---|
| **stdlib (chosen)** | Medium — we write the joins and the group-by | **Zero** | Whole-file JSON reads; no free spill-to-disk |
| DuckDB | Low — SQL does the work | One dependency | Its winning argument was SQL as the metric surface; ADR-008 removed it. Logic in SQL strings is logic outside mypy and ruff |
| Polars | Medium | One dependency | Lazy path cannot read JSON arrays; one bad record loses a file. Needs a Python pre-pass, after which the stdlib ingest already exists |
| pandas | Low | One dependency | Silently corrupts leading-zero identifiers by default; eager and memory-hungry |
| PySpark | High | JVM + cluster mental model | Justified by no measurement here; hostile test loop for a 69 ms workload |

The risk this decision carries — that a reviewer reads "stdlib" as unfamiliarity with the
ecosystem — is answered by the spike being in the repository. Evaluating four engines against
measured failure modes and choosing the simplest for stated reasons is a stronger signal than
reaching for the fashionable one.

---

### ADR-010: No metric definition language, no MCP server, no semantic layer

**Date:** 2026-08-25 · **Status:** Accepted · **Relates to:** ADR-008

**Context.** Both were live candidates for OQ-07, and both are what a reader might expect
given the brief names AI agents explicitly. Recording *why they were rejected* is worth more
than the rejection, because the same debate will otherwise recur the first time someone says
"shouldn't this expose an MCP server?"

**Decision.** We will not build (a) a declarative metric definition language, (b) an MCP
server or any other RPC surface over the metrics, or (c) a semantic layer / metrics store.

**Consequences.**

- **Against a DSL:** it is a language you invent, version, document and debug. Every metric
  that does not fit the schema produces an escape hatch, and escape hatches are how
  definition languages die. It also creates a second execution path exercised only by its own
  tests — AP-11 in the playbook, built deliberately rather than by accident. The `@metric`
  decorator gives the declarative *metadata* a DSL is usually wanted for, with none of the
  interpreter.
- **Against an MCP server:** a server wrapping a fixed set of metrics demonstrates nothing
  about extensibility — it is transport over whatever sits underneath. It also cannot be run
  by a reviewer without configuration, so it adds surface without adding evidence.
- **Against a semantic layer:** it is the correct answer at an organisation's scale, where
  many teams disagree about what "revenue" means. Here there is one pipeline and one
  definition per measure, already carried in `measures=`.
- All three would be built before a single consumer exists. The mechanism is provisional
  until measured against real use (playbook §4.5, generalised).

**Reversal conditions — the point of writing this down.**

- **MCP becomes right** when there is a live consumer that cannot run Python — an agent in
  someone else's runtime. It would then wrap the registry, which already holds exactly the
  metadata a tool schema needs: name, question, grain, columns, measure formulas. ADR-008's
  registry is shaped so this addition is additive and small, which is the responsible way to
  reject a feature.
- **A DSL becomes right** when non-engineers author metrics fast enough that PR review is the
  bottleneck. Not at five metrics. Plausibly at fifty.
- **A semantic layer becomes right** when a second pipeline computes an overlapping measure
  and the two disagree.

**Alternatives considered.** Building either "because the brief mentions AI agents" — rejected.
The brief asks for a foundation agents can use, and asks to see the trade-offs that were
weighed. A documented rejection with named reversal conditions answers both; a half-built
server answers neither.


---

### ADR-011: Malformed records are quarantined; out-of-scope records are excluded separately

**Date:** 2026-08-25 · **Amended:** 2026-08-25 · **Status:** Accepted · **Resolves:** OQ-02

**Context.** The brief states that some events do not comply with the schema and leaves the
handling to us. Measured against the provided data (§2.4):

- **3 of 27,076 claims are schema-invalid** — two missing `quantity`, one with
  `quantity == 0`. All three belong to a **valid** pharmacy (`3333333333`), so pharmacy
  validity cannot be used to screen them out.
- **4,085 claims (15.1%) reference an NPI absent from the pharmacy file**, across exactly
  three NPIs. These records are **not defective**. They are well-formed events for
  pharmacies outside our scope.

Three candidate policies existed. Dropping invalid records silently makes every downstream
number unexplainable — the classic pipeline horror story, where a total changes because
records vanished and nobody can say which. Failing the run on any invalid record lets one
bad record in a million block the business, and would fail on the provided sample as
shipped. That leaves quarantine.

The decision that matters is not "quarantine" — it is **refusing to conflate a defect with
an exclusion**. One sink would report a 15.1% reject rate for a source whose actual defect
rate is 0.011%, and would bury three real defects under 4,085 records that are perfectly
fine.

**Decision.**

1. **Two sinks, two meanings.**

   | File | Contains | Sample data |
   |---|---|---|
   | `out/_rejected.csv` | records that violate the schema — **data defects** | 3 |
   | `out/_excluded.csv` | records that are valid but out of scope — **not our pharmacies** | 4,085 |

2. **Reason codes, not prose.** Every quarantined record carries a list of machine-readable
   codes plus its source filename and record index: `missing_field:<name>`,
   `not_a_number:<field>`, `non_positive:quantity`, `unparseable_timestamp`,
   `not_an_object`, `npi_not_in_pharmacy_dataset`, `claim_not_accepted`. Codes aggregate;
   sentences do not. A record may carry several — the first failure is not necessarily the
   interesting one.

   **Amendment, 2026-08-25:** ADR-012 adds `duplicate_revert_for_claim`,
   `revert_precedes_claim` and `claim_not_found`. Additive per ADR-005 — the code list grows,
   never renames.

3. **A revert whose target claim was rejected or excluded is itself excluded**, with code
   `claim_not_accepted`. The revert is not malformed; its target simply is not in scope.
   Counting it anyway would make reversal counts disagree with claim counts, which is worse
   than either number being absent. In the provided data this covers 45 reverts.

4. **Every run writes `out/_manifest.json`:** records read, accepted, rejected and excluded;
   counts per reason code; counts per source file; and the reject rate. The manifest is what
   makes the two sinks discoverable and the totals auditable.

5. **The run exits non-zero when `rejected / read` exceeds `--max-reject-rate`, default
   `0.01`.** Exclusion is **never** a failure condition — being out of scope is not a defect,
   and a threshold on it would fail this dataset at 15%.

6. **A metric that raises fails the run.** Quarantine is for *data*. A defect in our own code
   is not a data-quality event, and routing it into a quarantine file is how a bug ships
   disguised as a bad record.

**Consequences.**

- **`read == accepted + rejected + excluded`, always.** This identity is the reason every
  headline number is explainable, and it is a test, not a comment.
- Reason codes are a data contract and are therefore additive-only under ADR-005. Adding a
  code is free; renaming one breaks whoever aggregates by it.
- `out/` now holds files that are not metrics. The manifest is what distinguishes them;
  the leading underscore is a convention, not a guarantee.
- The 1% threshold is a **placeholder until measured** (playbook §4.5). It is not derived
  from anything — it is chosen because the sample sits at 0.011%, three orders of magnitude
  below it, so the gate is not load-bearing today. The number is provisional until real
  traffic gives it meaning.
- Writing `_excluded.csv` costs 4,085 rows of output on the sample. Accepted deliberately:
  "which pharmacies are sending us claims that we have no record of?" is a real business
  question, and three unknown NPIs carrying 4,085 claims is a data-onboarding lead, not
  noise.

**Alternatives considered.**

| Policy | Verdict |
|---|---|
| Drop invalid records silently | Rejected — makes totals unexplainable and unauditable |
| Fail the run on any invalid record | Rejected — fails on the provided sample as shipped; demands an allowlist from day one |
| Quarantine, single sink | Rejected — reports a 15.1% reject rate for a source with 0.011% defects, burying three real defects under 4,085 healthy records |
| Quarantine, exclusions counted but not written | Rejected — the count answers "how many?" but not "which pharmacies?", and the second question is the one with business value |
| **Quarantine, two sinks (chosen)** | **Accepted** |


---

### ADR-012: Revert resolution — a claim is reverted at most once, keyed on `claim_id`

**Date:** 2026-08-25 · **Status:** Accepted · **Resolves:** OQ-03, OQ-04

**Context.** A reverted claim must be treated as though the fill never happened for revenue
and volume, while the reversal itself stays measurable. Making that precise means answering
three things the sample data forces (§2.4):

- **Revert `id` is not unique.** Three ids each appear twice, with the **same `claim_id` but
  different timestamps** — e.g. `44425520…` at `2026-01-01T12:31:37` and at
  `2026-05-01T22:38:13`. Neither obvious policy is free: keying on `id` discards a real
  record, keying on the whole record counts one reversal twice.
- **Two reverts are timestamped *before* the claim they cancel.** Physically impossible. The
  `claim_id` linkage is unambiguous; only the clock disagrees.
- **Zero reverts point at an unknown `claim_id`** in this sample, so the orphan case is
  entirely unexercised — and still needs a policy, because "unexercised" is not "impossible".

**Decision.**

1. **The reversal key is `claim_id`, not the revert `id`. A claim is reverted at most once.**
   Where several reverts target one claim, the **earliest** timestamp wins and the extras are
   counted under `duplicate_revert_for_claim`. Reversal count and reverted-claim count then
   agree *by construction* and cannot silently diverge — which is the property that matters,
   because every reversal-rate metric divides one by the other.

2. **A reverted claim is retained, not deleted.** It stays in the fact table carrying
   `reverted: bool` and `reverted_at: datetime | None`. It is excluded from revenue and fill
   counts, and included in reversal metrics. Deleting it would make the reversal rate
   uncomputable, and the brief explicitly calls the reversal itself a signal worth measuring.

3. **A revert timestamped before its claim is honoured, and flagged.** The pharmacist did
   submit a reversal; the linkage is sound and only the clock is wrong. The claim counts as
   reverted, and the record is counted under `revert_precedes_claim`. Rejecting the revert
   instead would leave money in the totals that somebody reversed — strict on data, wrong on
   revenue.

4. **A revert whose `claim_id` is unknown is excluded with `claim_not_found`, counted, and
   never fails the run.** *This case was not observed and is decided anyway.* The rationale:
   the pipeline is a full recompute over whatever files it is handed, so an unmatched
   `claim_id` most likely means the claim is in a file this run was not given — an input
   error, not a data defect. It becomes suspicious in bulk, which is why the manifest counts
   it. (A revert orphaned because its target was itself rejected or excluded keeps the
   distinct code `claim_not_accepted` from ADR-011 — different cause, different diagnosis.)

**Consequences.**

- Reversal resolution is a pure function of (claims, reverts) with no clock and no IO, so it
  is unit-testable exhaustively. Every case above becomes a named test.
- `duplicate_revert_for_claim`, `revert_precedes_claim` and `claim_not_found` join the reason
  codes in ADR-011 — additive, per ADR-005.
- The manifest reports all three counts. On this dataset that is 3, 2 and 0 respectively:
  small numbers, deliberately visible, because they are exactly the signals that would grow
  quietly if an upstream system started misbehaving.
- **Choosing the earliest timestamp is an assumption, not a truth.** With `id` non-unique and
  no sequence number, there is no way to tell which of two timestamps is real. Earliest is
  chosen because a reversal is more plausibly recorded near its claim; it affects only
  `reverted_at`, never whether the claim is reverted, so the blast radius is limited to
  time-to-revert metrics.

**Alternatives considered.**

| Option | Verdict |
|---|---|
| Key on revert `id` | Rejected — three ids denote two events each; deduping discards a genuine reversal |
| Key on the whole record `(id, claim_id, timestamp)` | Rejected — three claims would count as reverted twice, so reversal count exceeds reverted-claim count. Faithful to the raw stream, wrong for every rate |
| Quarantine repeated revert ids entirely | Rejected — discards three real reversals to avoid choosing a timestamp; understates the rate to dodge a decision |
| **Key on `claim_id`, earliest wins (chosen)** | **Accepted** |
| Reject reverts that precede their claim | Rejected — leaves reversed revenue in the totals |
| Reject both the revert and its claim | Rejected — discards a valid claim because a downstream record has a bad clock |
| Fail the run on an orphan revert | Rejected — a missing input file is an operator error, and failing hard makes partial reprocessing impossible |

---

### ADR-013: All timestamps are interpreted as UTC, and the assumption is published

**Date:** 2026-08-25 · **Status:** Accepted · **Resolves:** OQ-10

**Context.** Every timestamp in the sample is naive ISO-8601 with no offset
(`2026-01-01T00:00:07` … `2026-05-01T23:59:57`). Pharmacies span time zones, so any metric
bucketed by day or month is ambiguous: two claims one minute apart can fall on different
calendar days depending on the zone assumed. Silently picking one is how a day-boundary bug
ships and survives for months.

**Decision.** All timestamps are interpreted as **UTC**. The assumption is recorded
explicitly in `out/_manifest.json` (`"time_basis": "UTC (assumed; source carries no offset)"`)
and in `docs/METRICS.md`, so it travels with the numbers rather than living in a reviewer's
memory.

**Consequences.**

- Day- and month-bucketed metrics are computable, which keeps claims-per-month and
  time-to-revert on the table — two of the metrics most worth proposing (OQ-06).
- Ordering comparisons (`revert_at < claim_at`, ADR-012) are well defined, because a single
  basis applies to every record.
- **The assumption is almost certainly wrong for at least some pharmacies.** It is stated
  rather than hidden precisely so a reader can judge whether it matters for their question.
  Where it does matter, the fix is real offsets in the source, not a heuristic here.
- If the source ever supplies offsets, this ADR is superseded and the naive path becomes a
  compatibility branch, not a rewrite.

**Alternatives considered.**

| Option | Verdict |
|---|---|
| Carry naive timestamps, forbid date-bucketed metrics | The most technically correct answer, and rejected: it rules out the most useful proposed metrics to avoid an assumption that can simply be declared |
| Derive the zone from the pharmacy | Rejected — needs an NPI-to-timezone mapping the pharmacy file does not contain. Inventing or fetching one adds a dependency and a new error source the brief never asked for |
| **Declare UTC and publish the assumption (chosen)** | **Accepted** |

---

### ADR-014: Pharmacy reference data is current-state, not point-in-time

**Date:** 2026-08-25 · **Status:** Accepted · **Resolves:** OQ-11

**Context.** The pharmacy dataset is described as slowly-changing reference data. That raises
a question the file itself cannot answer: if a pharmacy is removed next month, do its past
claims disappear from history? The file carries only `npi` and `chain` — no effective dates,
no validity window.

**Decision.** The pharmacy file supplied to a run is the truth **for the whole of that run**.
Claims join it as current-state. A pharmacy absent from the file is out of scope for every
claim in that run regardless of when the claim occurred, and is excluded per ADR-011.

**Consequences.**

- **History is not stable across runs.** Removing a pharmacy from the reference file changes
  historical numbers on the next run. That is a real property of this design and is stated
  here so nobody discovers it during a quarter-end reconciliation.
- Byte-identical output (charter §1.3.4) holds for identical inputs — and the pharmacy file
  is an input. Same files in, same bytes out; different reference file, legitimately
  different history.
- The manifest records a digest of the pharmacy file used, so any two runs that disagree can
  be explained rather than argued about.
- Point-in-time remains available later without a redesign: it needs effective-dated
  reference data, and the join moves from `npi` to `npi` plus a validity window. That is a
  source-data change first and a code change second.

**Alternatives considered.**

| Option | Verdict |
|---|---|
| Point-in-time join on an effective-dated dimension | Correct for auditability and rejected: the source provides no effective dates, so they would have to be invented — fabricated provenance is worse than stated simplicity |
| **Current-state (chosen)** | **Accepted** |


## 4. Open Questions

Every one of these is a decision **not yet made**. Recording them as questions rather
than quietly resolving them in code is the point: each will become an ADR, and the ADR
will record why the alternative lost. Nothing in `src/` may assume an answer to an open
question.

### Decision order

Open questions are **not** answered in ID order. IDs are permanent labels, assigned when
the question was first noticed; the sequence below is the order in which they are
decided, and it changes as evidence arrives.

| # | Decide | Why it comes here |
|---|---|---|
| ~~1~~ | ~~**OQ-07** — the extension surface~~ | **Resolved by ADR-008 + ADR-010** (session 003). It dominated OQ-01, which is why it went first. |
| ~~2~~ | ~~**OQ-01** — compute engine~~ | **Resolved by ADR-009** (session 003). Took ten minutes once OQ-07 was fixed, and landed on the opposite answer from the spike's provisional lean — which is the sequencing correction paying for itself. |
| ~~3~~ | ~~**OQ-02** — malformed-record policy~~ | **Resolved by ADR-011** (session 003). Quarantine, with rejection and exclusion kept apart. |
| ~~4~~ | ~~**OQ-03, OQ-04, OQ-10, OQ-11**~~ | **Resolved by ADR-012, ADR-013, ADR-014** (session 004). |
| **1** | **F-01 + F-02 + F-04** — ingestion, domain model, metric registry | Next, and specified together. Every structural decision they depend on is now made. F-04 in particular ships with a real caller or not at all — built alone its only caller would be its own tests, which is AP-11 and `CLAUDE.md` forbids it. |
| **2** | **OQ-09** — idempotency and late-arriving reverts | The last genuinely open engineering question. ADR-014's "the reference file is an input" already leans full-recompute; this makes it explicit. |
| **3** | **OQ-06, OQ-08** — the metric set and the unit-price definition | Cheapest to change, and ADR-008 gives them a place to live. Decided with F-03 and F-04 in hand. |
| **4** | **OQ-12** — deployment and ownership model | Prose in the README, written once the system it describes exists. |

**Every decision that shapes the code is now made.** What remains is one engineering question
(OQ-09), the metric set itself (OQ-06, OQ-08 — cheap to change by construction), and prose.

> **Correction (session 002).** Session 001 recorded OQ-01 as the next action. That was
> the wrong order: the engine choice is downstream of the extension surface, not upstream
> of it. Recorded here rather than silently re-sequenced — a sequencing mistake is worth
> as much to a future reader as the decision itself.
>
> **Outcome (session 003).** The reorder changed the answer. With OQ-07 resolved to Python
> functions, the spike's leading recommendation (DuckDB) lost its decisive argument and
> OQ-01 landed on the standard library instead. Had OQ-01 been decided first, the engine
> would have chosen the extension surface by default.

Numbers are **not** reserved for unwritten ADRs — see the note under the ADR index. The
"Blocks" column names the code that cannot be written, not a future ADR number.

| ID | Question | Blocks | Status |
|---|---|---|---|
| OQ-01 | Which compute engine? | all of `gateway/` | **Resolved — ADR-009** |
| OQ-02 | What happens to a malformed record? | ingestion, the quarantine export | **Resolved — ADR-011** |
| OQ-03 | What exactly does a revert invalidate? | every metric | **Resolved — ADR-012** |
| OQ-04 | Is a revert `id` an identity? How are repeats handled? | revert resolution | **Resolved — ADR-012** (it is not) |
| OQ-05 | Output format and destination? | the writers | **Resolved — ADR-008, ADR-011** (see §2.5) |
| OQ-06 | Which metrics beyond the required set? | `metrics/` | Open |
| OQ-07 | How do agents extend this without reading ingestion code? | the whole shape of `metrics/` | **Resolved — ADR-008, ADR-010** |
| OQ-08 | How is unit price defined? | `metrics/` | Open |
| OQ-09 | Are re-runs idempotent? What about late-arriving files? | the runner | Open — *last open engineering question* |
| OQ-10 | What do the naive timestamps mean? | any time-bucketed metric | **Resolved — ADR-013** |
| OQ-11 | Is pharmacy reference data point-in-time or current-state? | the pharmacy join | **Resolved — ADR-014** |
| OQ-12 | Deployment, orchestration and team ownership model? | README prose only | Open |

---

**OQ-01 — Which compute engine?** — **RESOLVED by [ADR-009](#adr-009-the-python-standard-library-is-the-compute-engine-zero-runtime-dependencies): the Python standard library, zero runtime dependencies.** Retained below as the record of what the question was.
27,074 claims is trivially small; the design question is what the pipeline must survive
when a real month arrives. Candidates: pure stdlib streaming (zero dependencies, total
control, most code to write); Polars (lazy execution, excellent single-node scaling,
one dependency); DuckDB (SQL as the metric language — which interacts directly with
OQ-07, since SQL is a surface agents already speak); PySpark (justifiable only at a
volume nothing here demonstrates). Decide with the requirements-first table in playbook
§1.2, not by preference.

**Evidence — see [`docs/spikes/oq-01-compute-engine/`](spikes/oq-01-compute-engine/README.md).**
Measured, not assumed: a pure-stdlib pass over the whole dataset takes **69 ms** at
391k records/sec, so throughput does not select the engine. pandas silently turns
`'0987654321'` into `987654321`. Polars loses an entire file to one non-object record,
and its lazy/streaming path cannot read JSON *array* files at all. DuckDB reads lists of
directory globs in place, survives malformed records, and produces a per-record
rejection reason in one pass. The spike's leading recommendation is DuckDB — **but it is
explicitly conditional on OQ-07**, which is why OQ-07 was decided first. OQ-07 landed on
Python functions (ADR-008), the condition failed, and ADR-009 chose the standard library.

**OQ-02 — What happens to a malformed record?** — **RESOLVED by [ADR-011](#adr-011-malformed-records-are-quarantined-out-of-scope-records-are-excluded-separately): quarantine, with rejection and exclusion in separate sinks.** Retained below as the record of what the question was.
The sample contains 2 claims missing `quantity` and 1 with `quantity == 0`. Options:
drop silently (never — it makes totals unexplainable); fail the run (safe, but one bad
record in a million blocks the business); or **quarantine**: exclude from metrics, write
to a rejects sink with the reason and the source file, and report counts alongside the
results. Whichever is chosen, the rejected count must appear in the output, because a
number that changed because records vanished is a number nobody can trust.

**OQ-03 — What exactly does a revert invalidate?** — **RESOLVED by [ADR-012](#adr-012-revert-resolution--a-claim-is-reverted-at-most-once-keyed-on-claim_id).** Retained below as the record of what the question was.
Three concrete cases the sample forces: (a) 2 reverts are timestamped *before* the claim
they cancel — honour or reject? (b) 45 reverts point at claims of an out-of-scope NPI —
they must vanish with those claims, but must the count of "reverts processed" say so?
(c) the sample has 0 orphan reverts, so the policy for a revert whose `claim_id` is
unknown is unexercised and must be decided anyway — the claim may simply be in a file
that has not arrived yet (see OQ-09).

**OQ-04 — Is a revert `id` an identity?** — **RESOLVED by [ADR-012](#adr-012-revert-resolution--a-claim-is-reverted-at-most-once-keyed-on-claim_id): it is not. The reversal key is `claim_id`.** Retained below as the record of what the question was.
Three revert ids each appear twice with *different* timestamps. So the same id denotes
two different events, and neither obvious policy is free: deduplicating on `id`
discards a real record; not deduplicating counts one reversal twice. Options: treat
`claim_id` as the reversal key (a claim is reverted at most once); dedupe on the full
record; or quarantine repeated ids as a data-quality defect. This decides whether the
per-pharmacy reversal *rate* is right or wrong — with 308 reverts total, 3 records is
1% of the numerator.

**OQ-05 — Output format and destination?**
JSON is what the brief's shape implies; Parquet is what a downstream analyst wants; a
DuckDB file is what an agent can query without any pipeline code at all. Not mutually
exclusive — the metric layer could emit one canonical form with thin serializers — but
the canonical form must be chosen before anything is written.

**OQ-06 — Which metrics beyond the required set?**
The brief asks us to *propose* useful metrics. Grounded candidates from §2.4: reversal
rate per pharmacy and per chain (with an explicit small-denominator rule — 1.14% overall
means many pharmacies will have single-digit reversals); unit-price dispersion per NDC
(the sample's identical `0.30`–`884.60` range across every drug is exactly the "prices
out of line" signal the brief describes); claim volume and revenue per chain; time-to-
revert distribution. Each proposed metric needs a stated business question, or it is
decoration.

**OQ-07 — How do agents extend this without reading ingestion code?** — **RESOLVED by [ADR-008](#adr-008-metrics-are-registered-python-functions-over-an-exported-fact-table) and [ADR-010](#adr-010-no-metric-definition-language-no-mcp-server-no-semantic-layer).**
Answer: registered Python metric functions for the write path, a flat CSV/JSON export for
the read path, a generated `docs/METRICS.md` as the catalog — and an explicit refusal to
build a metric DSL, an MCP server or a semantic layer, with the conditions that would
reverse each. Retained below as the record of what the question was. Candidates: a declarative metric registry (YAML or
dataclasses) that the pipeline executes and that also generates documentation; a SQL
semantic layer over a materialised table; an MCP server exposing metrics as tools. The
test for any answer: *can a new metric be added by writing one declaration and one test,
touching no IO code?*

**OQ-08 — How is unit price defined?**
`mean(price_i / quantity_i)` and `sum(price) / sum(quantity)` are different numbers, and
with this dataset's dispersion (min `0.30`, max `884.60` for the same NDC) they differ
materially. The second weights by quantity and is usually what "average price paid"
means commercially; the first treats every fill equally. Whichever is chosen must be
named in the output field itself, not in a footnote.

**OQ-09 — Are re-runs idempotent? What about late-arriving files?**
The brief describes a *stream* of events split across many files. If reverts can arrive
after the claim window has been aggregated, the pipeline is either full-recompute
(simple, correct, re-reads everything) or incremental (fast, and now carries state,
watermarks and a whole class of bugs). Success criterion 4 — byte-identical outputs for
identical inputs — is a hard constraint on either.

**OQ-10 — What do the naive timestamps mean?** — **RESOLVED by [ADR-013](#adr-013-all-timestamps-are-interpreted-as-utc-and-the-assumption-is-published): UTC by declaration, published in the manifest.** Retained below as the record of what the question was.
Every timestamp in the sample lacks an offset. Pharmacies span time zones, so "claims
per day" is ambiguous. Options: declare all timestamps UTC and say so in the output;
carry them as naive local and forbid date-bucketed metrics until a zone is available;
or derive the zone from the pharmacy. Silently calling them UTC without recording the
assumption is how a day-boundary bug ships.

**OQ-11 — Is pharmacy reference data point-in-time or current-state?** — **RESOLVED by [ADR-014](#adr-014-pharmacy-reference-data-is-current-state-not-point-in-time): current-state.** Retained below as the record of what the question was.
The file is described as slowly changing. If a pharmacy is removed next month, do its
past claims disappear from history? Current-state joins are simple and rewrite history;
point-in-time joins preserve history and need effective dating the file does not
currently carry.

**OQ-12 — Deployment, orchestration and team ownership?**
The brief explicitly invites assumptions about deployment in a multidisciplinary team.
To settle: where it runs (container on a schedule, orchestrator task, serverless job);
who owns which layer (data engineering owns `gateway/`, analytics owns `metrics/` — the
layer split in ADR-003 is what makes shared ownership possible); how a business user
requests a new metric; and how outputs are versioned and published. Answer this in prose
in the README rather than by building infrastructure nobody asked for.

---

## 5. Feature log

Keyed to spec files in `memory/features/`. A feature is `Done` only when its spec file
says so and the Definition of Done in `CLAUDE.md` is satisfied.

| ID | Feature | Spec file | Depends on | Status |
|---|---|---|---|---|
| F-00 | Repository foundation: layout, toolchain, hooks, PMA | — (this document) | — | **Done** (session 001) |
| F-01 | Ingestion gateway: read pharmacies, claims, reverts; validate; quarantine | `feature-01-ingestion.md` | ~~OQ-01~~, ~~OQ-02~~ | **Ready to specify** |
| F-02 | Domain model and revert resolution | `feature-02-revert-resolution.md` | ~~OQ-03, OQ-04, OQ-10, OQ-11~~ | **Ready to specify** |
| F-03 | Required metrics | `feature-03-required-metrics.md` | F-02, F-04, OQ-08 | Blocked on F-02/F-04 |
| F-04 | The metric registry (`@metric`, discovery, `METRICS.md` generation) | `feature-04-metric-registry.md` | ~~OQ-07~~, F-02 | Ready — but **specified and built with F-02**, never alone (AP-11) |
| F-05 | Output serialization and run manifest | `feature-05-outputs.md` | OQ-09 (format fixed by ADR-008/011) | Not specified |

---

## 6. Retrospective

To be written as the project matures. It records what the ADRs got wrong, not what they
got right — a retrospective that only lists successes teaches nothing.

---

## Appendix — ADR template

```markdown
### ADR-NNN: [Title]

**Date:** YYYY-MM-DD · **Status:** Accepted | Superseded by ADR-MMM

**Context.**
[What problem or gap triggered this decision. What forces are in tension.]

**Decision.**
[The concrete, binding choice, in the present tense: "We use X for Y."]

**Consequences.**
[What this constrains. What future decisions must not contradict it. What migration
would be required to reverse it.]

**Alternatives considered.**
[Why each alternative lost. This is the section that stops the same debate recurring
in six months.]
```
