# CLAUDE.md — agent operating contract for `hippo-pipeline`

Read this file first, then `docs/PROJECT_MEMORY.md` in full, **before** proposing or
writing anything structural. This file says *how to work here*; the Project Memory
Asset (PMA) says *what has already been decided*.

---

## 1. What this repository is

A data pipeline that ingests pharmacy **claims** and **reverts** (reversals) and emits
auditable metrics for a PBM business team. The brief is `docs/ASSIGNMENT.md`.

Two constraints shape every decision and are worth stating up front, because they pull
in different directions:

- **Correctness over cleverness.** Every number the pipeline emits must be traceable to
  the records that produced it. A metric nobody can audit is a metric nobody will trust.
- **It must be a base others extend.** Business analysts and AI agents should be able to
  add a metric without reading the ingestion code. Resolved by ADR-008: metrics are
  registered Python functions over an exported fact table, and the IO layer is invisible
  to them.

## 2. The working method (non-negotiable)

This project follows Spec-Driven Development as described in
`docs/GENERAL_ENGINEERING_PLAYBOOK.md`. In order, every time:

1. **Read the PMA.** `docs/PROJECT_MEMORY.md`.
2. **Conflict Check.** Before writing code, list every existing ADR and data contract
   the change could contradict, and say so explicitly. Playbook §1.5. If a conflict
   exists, the ADR is amended *first*; the code follows.
3. **Spec.** New ADR(s) + Gherkin scenarios in `tests/bdd/features/` + a feature file in
   `memory/features/feature-NN-name.md`. Spec and implementation do not share a session.
4. **Failing tests.** Deterministic-tier tests that mirror the Gherkin, written before
   the implementation. A scenario you cannot write a test for means the spec is
   ambiguous — fix the spec, not the test.
5. **Implement.** The tests are the specification; done means they pass.
6. **Verify programmatically.** Run `make check` and paste the output. "This should
   work" is not a result.
7. **Update the PMA in the same response as the code.** Never defer it.

## 3. Definition of Done

A change is done only when all of the following are true:

1. `docs/PROJECT_MEMORY.md` reflects any new/changed ADR, contract, or feature status.
2. Every Gherkin scenario for the feature has a passing step definition.
3. Unit tests cover the input → output contract *and* the failure path, not just the
   happy path.
4. `make check` passes: ruff, architectural lint, mypy strict, deterministic tests at
   100%.
5. `memory/features/feature-NN-*.md` is marked `Status: Done`.
6. The output of the test run is pasted into the response.

## 4. Hard constraints

- **Zero runtime dependencies (ADR-009).** `src/hippo_pipeline/` imports the standard
  library and nothing else. `pyproject.toml` `dependencies` stays empty. Third-party
  packages are allowed in the dev group and in spikes run under `uv run --with`, never in
  the package. Enforced by `scripts/lint_architecture.py`; adding one fails `make lint`.
- **Money is `decimal.Decimal`, never `float` (ADR-009).** Float summation is
  order-dependent and breaks byte-identical output. Parse prices from their string form so
  the value never round-trips through a float.
- **A metric is one module in `metrics/` plus one unit test (ADR-008).** It carries a
  `@metric` decorator with a mandatory `question=`, receives already-validated,
  already-revert-resolved domain objects, and performs no IO. Any measure with more than
  one defensible definition states its formula in `measures=`.
- **No metric DSL, no MCP server, no semantic layer (ADR-010).** If you think one is
  needed, read ADR-010's reversal conditions first.
- **Only `src/hippo_pipeline/gateway/` may touch the filesystem or parse raw bytes.**
  No `open()`, no `import json`/`csv`/`pathlib`/`glob` anywhere else. Everything
  downstream receives already-parsed domain objects. Enforced by
  `scripts/lint_architecture.py` — see ADR-003.
- **Every external dependency is obtained through a factory function**, never
  constructed at a call site. Tests mock the factory, never the implementation class
  (playbook AP-02).
- **The tested path is the production path.** Before accepting any new abstraction,
  grep for non-test callers. If only tests call it, wire it in or delete it (AP-11).
- **`print()` only in `cli.py`.** Everything else emits structured log records with a
  `run_id` (playbook §4.1).
- **Data contracts are additive.** New output fields get a default; existing fields are
  never removed or retyped without an ADR that names the blast radius.
- **Never edit files under `data/sample-data/`.** It is the fixture the results are
  judged against.

## 5. Commands

| Command | What it does |
|---|---|
| `make setup` | Create `.venv`, install locked deps (uv) |
| `make lint` | ruff + architectural lint + docs/Makefile drift check |
| `make typecheck` | mypy strict |
| `make test` | Deterministic tiers — the merge gate, must be 100% |
| `make test-system` | System-behavior tier, baseline-gated, not a merge gate |
| `make check` | lint + typecheck + test |
| `make run ARGS="..."` | Run the CLI |

## 6. Hooks

`.claude/settings.json` defines five `PostToolUse` hooks — architectural lint, auto-run
of the matching unit test, config syntax validation, Makefile↔README drift, and a PMA
freshness reminder — plus one `PreToolUse` gate that **blocks** writes to
`data/sample-data`. Post hooks report after the fact; the fixture is the one thing that
has to be protected before the write lands.

**They fire only in Claude Code CLI sessions.** In Cowork, claude.ai, or any other
interface nothing runs automatically — run `make check` yourself. CI runs all of it
either way.

## 7. Commit convention

Conventional Commits, imperative mood, one logical change per commit:

```
feat(metrics): add per-chain top-2 cheapest pharmacy metric
fix(gateway): tolerate quantity serialized as a float
docs(pma): record ADR-008 (compute engine = <choice>)
chore(ci): split system-behavior tier into its own job
```

An ADR-bearing change references the ADR number in the body.

## 8. Where things live

```
docs/PROJECT_MEMORY.md   the PMA — charter, contracts, ADRs, open questions. Source of truth.
docs/DECISION_LOG.md     what happened in each session, in order.
docs/ASSIGNMENT.md       the original brief.
docs/*PLAYBOOK.md        the engineering practices this repo follows.
memory/features/         one spec file per feature, keyed to the PMA feature log.
src/hippo_pipeline/      gateway/ | domain/ | metrics/ | cli.py
tests/unit/              deterministic tier — no IO, no network, 100% required
tests/bdd/               Gherkin features + step definitions
tests/system/            real data, baseline-gated
scripts/                 lint + hook implementations
data/sample-data/        provided fixture — read-only
```
