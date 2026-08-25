# hippo-pipeline

A data pipeline over pharmacy **claims** and **reverts** (reversals), producing auditable
metrics for a PBM business team — and built so that analysts and AI agents can extend it
without reading the ingestion code.

Brief: [`docs/ASSIGNMENT.md`](docs/ASSIGNMENT.md).

---

## Status

**Specified, not yet implemented.** This is the method, not a delay: the decisions that
determine the shape of every line of pipeline code are made, written down and
conflict-checked before the first line is written.

Two of them are now settled, in [`docs/PROJECT_MEMORY.md`](docs/PROJECT_MEMORY.md):

- **ADR-008 — how this gets extended.** A metric is one Python module plus one test,
  registered by a `@metric` decorator that carries its business question, its grain and the
  formula for any ambiguous measure. Every run also exports a flat CSV/JSON fact table, so
  a question the pipeline does not answer can be asked of the output directly, with no
  repo access. `docs/METRICS.md` is generated from the registry, so the catalog cannot go
  stale.
- **ADR-009 — what it runs on.** The Python standard library. **Zero runtime
  dependencies.** Chosen after benchmarking DuckDB, Polars and pandas against the real
  failure modes — the evaluation is committed at
  [`docs/spikes/oq-01-compute-engine/`](docs/spikes/oq-01-compute-engine/README.md), and
  ADR-009 names the conditions that would reverse it.
- **ADR-010 — what this deliberately will not have:** no metric definition language, no
  MCP server, no semantic layer, each with the conditions under which it becomes right.

What remains open is the malformed-record policy and the revert semantics — the highest-risk
correctness decisions in the project, and the reason no ingestion code exists yet.

What exists today:

- The full engineering scaffold: layout, toolchain, two-tier test harness, CI, lint.
- An architectural lint that is itself unit-tested, enforcing the IO chokepoint on every
  file save.
- A **profiled** sample dataset — 14 measured facts about the provided data, each one
  either constraining the design or opening a question. Reproduce them with
  `python3 scripts/profile_sample_data.py`.
- A Project Memory Asset carrying 7 accepted ADRs and 12 open questions, with an
  explicit **decision order** separate from ID order.
- A committed, runnable spike for the compute-engine question —
  [`docs/spikes/oq-01-compute-engine/`](docs/spikes/oq-01-compute-engine/README.md) —
  so the ADR that follows cites measurements rather than opinion.

Running the CLI today exits `2` and tells you which open questions block it.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python ≥3.10.

```bash
git clone <this repo> && cd hippo
make setup          # create .venv, install locked dependencies
make check          # lint + typecheck + deterministic tests — the merge gate
make run            # currently exits 2: scaffolding only
```

Other targets:

| Command | What it does |
|---|---|
| `make help` | List every target |
| `make lint` | ruff, architectural constraint lint, README/Makefile drift check |
| `make typecheck` | mypy, strict |
| `make test` | Deterministic tier — no IO, no network, must be 100% |
| `make test-unit` | Deterministic unit tests only |
| `make test-bdd` | Gherkin acceptance scenarios |
| `make test-system` | System-behavior tier against the real sample data |
| `make audit` | Dependency vulnerability audit |
| `make tree` | Show the repo layout |
| `make clean` | Remove caches and build artifacts |

## The sample data

`data/sample-data/` holds the provided fixture: 17 pharmacies across 3 chains, 27,074
schema-valid claims across 28 files, and 308 reverts across 4 files. **Never edit it** —
it is what results are judged against.

Three findings from profiling it that shape the design more than anything else:

1. **15.1% of claims reference an NPI absent from the pharmacy file** (3 NPIs, 4,085
   claims). Filtering out-of-scope events is not an edge case; it moves every headline
   number.
2. **Three revert `id`s each appear twice with different timestamps.** A revert `id` is
   therefore not an identity. Deduplicating on it discards a real record; not
   deduplicating counts a reversal twice.
3. **One claim has `quantity == 0`** and two are missing `quantity` entirely — all three
   belonging to a *valid* pharmacy, so "bad NPI" cannot be used to filter them. Any
   unit-price metric divides by zero unless the policy is explicit.

Full profile and the rest of the findings: [`docs/PROJECT_MEMORY.md` §2.4](docs/PROJECT_MEMORY.md).

## How this repository is organised

```
CLAUDE.md                 operating contract for AI-assisted sessions
docs/PROJECT_MEMORY.md    source of truth: charter, contracts, ADRs, open questions
docs/DECISION_LOG.md      what happened each session, and the exact next action
docs/ASSIGNMENT.md        the original brief
docs/*PLAYBOOK.md         the engineering practices this repo follows
memory/features/          one spec file per feature, written before implementation
src/hippo_pipeline/
  gateway/                the ONLY code allowed to touch the filesystem or parse bytes
  domain/                 pure types and rules — no IO, no logging, no clock
  metrics/                pure aggregations over domain types
  cli.py                  the single production entry point
tests/unit/               deterministic tier — 100% required, blocks merge
tests/bdd/                Gherkin features and step definitions
tests/system/             real data, baseline-gated, not a merge gate
scripts/                  architectural lint, hooks, sample-data profiler
data/sample-data/         provided fixture — read-only
```

The layer boundary in `src/` is not a convention. `scripts/lint_architecture.py` parses
the AST of every file under `src/hippo_pipeline/` and fails the build if anything outside
`gateway/` imports `json`, `csv`, `pathlib`, `glob`, `shutil`, `tarfile` or `gzip`, calls
`open()`, or (outside `cli.py`) calls `print()`. That lint has its own tests, because an
unverified linter fails open.

## How the work is done

Spec-driven, following [`docs/GENERAL_ENGINEERING_PLAYBOOK.md`](docs/GENERAL_ENGINEERING_PLAYBOOK.md):
read the Project Memory Asset → run a Conflict Check against every existing ADR → write
the ADR and the Gherkin → write failing tests → implement → update the PMA in the same
change. Sessions run in Claude Code with `.claude/settings.json` hooks that lint
architecture, run the matching unit test, and flag a stale PMA on every file save — and
one that blocks writes to `data/sample-data` outright.

Those hooks fire only in the Claude Code CLI. Every check they run is also a `make`
target and a CI job, so enforcement never depends on which interface was used.
