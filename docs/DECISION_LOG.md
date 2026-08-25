# Decision Log

One entry per working session, newest last. Each entry ends with **the exact next
action**, so the following session can start without reconstructing context
(playbook §2.5, checkpoint-and-continue).

This log records *what happened*. `PROJECT_MEMORY.md` records *what was decided*. When
they disagree, the PMA wins and this log gets a correction entry.

---

## Session 001 — 2026-08-24 — Repository foundation

**Goal.** Turn a folder holding a brief, two playbooks and a sample dataset into a git
repository with a working spec-driven development environment, before any pipeline code
exists.

**Decisions taken** (all recorded as ADRs in `PROJECT_MEMORY.md`):

| ADR | Decision | Why this one |
|---|---|---|
| 001 | PMA as single source of truth | Multi-session AI work without accumulated context contradicts itself |
| 002 | Python ≥3.10 + uv + committed lockfile | A green CI must prove something about the reviewer's machine |
| 003 | Layered package, IO chokepoint in `gateway/` | Makes `domain/`/`metrics/` testable with zero mocks; makes OQ-01 reversible |
| 004 | Two test tiers, Gherkin first | Fast gate stays fast; tests specify rather than confirm |
| 005 | Additive-only output contracts | Agent consumers are the least able to notice a silent rename |
| 006 | Trunk-based, Conventional Commits | History is part of the deliverable |
| 007 | Repository as an enforced agent contract | A rule without enforcement is followed until the first deadline |

**Work done.**

1. Restructured the folder: `docs/`, `src/hippo_pipeline/`, `tests/{unit,bdd,system}/`,
   `scripts/`, `memory/features/`, `data/sample-data/`. Initialised git on `main`.
2. Built the Claude environment: `CLAUDE.md`, `.claude/settings.json` with five
   `PostToolUse` hooks, and four slash commands (`/session-start`, `/conflict-check`,
   `/new-feature`, `/pre-merge`).
3. Wrote `scripts/lint_architecture.py` — AST-based, not grep. The first grep version
   flagged its own docstring, which is exactly why the playbook's regex pattern was
   replaced here. Gave it unit tests against a fixture package that violates all three
   rules, plus a test that the real package is clean.
4. Wrote `scripts/profile_sample_data.py` and profiled the dataset, so §2.4 of the PMA is
   reproducible rather than asserted.
5. Wrote the PMA: charter, three input contracts, 14 measured facts, 7 ADRs, 12 open
   questions, feature log.
6. Toolchain: `pyproject.toml` (runtime `dependencies` deliberately **empty**),
   `Makefile`, GitHub Actions pipeline ordered fast-to-slow.

**What the data profiling changed.** Four findings became open questions that would
otherwise have been silently mis-answered in code:

- 15.1% of claims reference NPIs absent from the pharmacy file → filtering is a headline
  concern, not an edge case (OQ-03).
- Three revert `id`s repeat with *different* timestamps → revert `id` is not an identity;
  both obvious dedupe policies are wrong in different ways (OQ-04).
- One claim has `quantity == 0`, at a *valid* pharmacy → unit-price metrics divide by
  zero, and NPI validity does not screen it out (OQ-02, OQ-08).
- Unit price ranges `0.30`–`884.60` identically for every NDC → `mean(price/qty)` and
  `sum(price)/sum(qty)` will differ materially, so "average price" must be defined
  before it is computed (OQ-08).

**What was deliberately NOT done.** No ingestion, no domain model, no metrics, no runtime
dependency. Adding any of those requires answering OQ-01, OQ-02 and OQ-03 first, and
those answers are decisions to be made with the reviewer's eyes open, not defaults that
leak in through an import.

**Verification.** `bash scripts/lint_architecture.sh` clean on the package and correctly
failing on the fixture; `bash scripts/check_docs_commands.sh` clean; hook scripts
exercised with synthetic tool events; `.claude/settings.json` parses.

**Next action.** Resolve **OQ-01 (compute engine)** using the requirements-first method
in playbook §1.2: enumerate the non-negotiable behaviours first (streaming over many
files, deterministic output, no state between runs unless OQ-09 says otherwise,
metric layer readable by non-engineers), then map stdlib / Polars / DuckDB / PySpark
against them in a table, then write ADR-008. Spec session only — no implementation in
the same session.

---

## Session 002 — 2026-08-25 — OQ-01 spike, and a sequencing correction

**Goal.** Give OQ-01 (compute engine) enough context to be decided, rather than argued.

**Method.** Ran the candidates against the real dataset plus a synthetic file carrying
the breakage a real event stream produces — a string where a number belongs, a null
price, an unparseable timestamp, an extra field, and an array element that is not an
object at all. Committed as `docs/spikes/oq-01-compute-engine/`, runnable:

```
uv run --with duckdb --with polars --with pandas \
    python docs/spikes/oq-01-compute-engine/spike.py
```

None of those libraries is a project dependency, and `uv run --with` keeps it that way.

**What the measurements changed.**

1. **Throughput is not the deciding factor and never was.** A pure-stdlib streaming pass
   over all 27,076 records takes **69 ms** at 391k records/sec in 39 MB. Linear
   extrapolation puts 100M claims at ~4.5 minutes. Every "it scales better" argument was
   about a constraint that does not bind.
2. **pandas is out on a concrete hazard, not on taste.** Default `read_csv` typed `npi`
   as `int64` and turned `'0987654321'` into `987654321`. The pharmacy file contains two
   leading-zero NPIs and 9 of 10 NDCs are leading-zero.
3. **Polars is out on the input format.** `scan_ndjson` — the lazy/streaming path —
   cannot read JSON *array* files, and `read_json` has no glob support and loses an
   entire file to a single non-object element. Using it requires a Python pre-pass, after
   which the stdlib ingest is already written.
4. **DuckDB satisfies OQ-01, OQ-02 and OQ-07 with one mechanism**: parse permissively via
   `read_json_objects`, type with `TRY_CAST` so a bad cast yields NULL instead of
   aborting the file, and quarantine in SQL so every rejected record carries a reason
   list and its source filename. Verified: 27,075 accepted / 7 rejected, each with a
   reason, from a directory list read in place.

**PostgreSQL was raised and is recorded as rejected-with-reasons** in §6 of the spike
README, so it is not re-litigated later. Short form: DuckDB is a compute engine that
happens to persist, Postgres is a system of record that happens to compute, and this
pipeline needs the former. Postgres becomes correct with concurrent writers, a networked
serving layer, governance requirements, or an incremental pipeline (OQ-09).

**The correction.** Session 001 ended by naming OQ-01 as the next action. That was the
wrong order. The engine choice is *downstream* of OQ-07 (how analysts and agents extend
the pipeline): if metrics are Python functions, the zero-dependency option wins; if they
are SQL over a published artifact, an engine that speaks SQL wins. Deciding the engine
first would have settled OQ-07 by accident — which is exactly the "confident code
satisfying an ambiguous spec" failure the playbook opens with.

The PMA now carries an explicit **decision order** (§4) separate from ID order. IDs stay
permanent; the sequence is what changes as evidence arrives.

**What was deliberately NOT done.** ADR-008 was not written. The spike's leading
recommendation is DuckDB, and it is explicitly conditional — recording it as a decision
before OQ-07 is settled would be the same mistake in a different place.

**Verification.** Spike runs end to end against the full dataset from a clean checkout;
`make check` green.

**Next action.** Resolve **OQ-07 — the extension surface**. Spec session only, no
implementation. Enumerate what "a business analyst or an agent adds a metric
autonomously" concretely requires, then map the candidates against it: a declarative
Python metric registry, SQL views over a published artifact, and an MCP server exposing
metrics as tools. The acceptance test for any answer is fixed in the PMA: *can a new
metric be added by writing one declaration and one test, touching no IO code?* Output is
ADR-013 plus the revised text of OQ-01, which then becomes a short decision.

### Session 002 addendum — the fixture drifted

While committing, `git status` showed five `data/sample-data` files modified. Verified
semantically identical — same records, same values, only re-indented — and the mtimes
were later than the last commit, so an editor wrote them, not the pipeline. Restored
byte-exact from HEAD.

The interesting part is not the reformat, it is that `CLAUDE.md` already said the
fixture is read-only and nothing enforced it. That is ADR-007's own thesis turned on
itself: a convention living only in prose is followed until something automatic ignores
it. Two layers added, and ADR-007 amended to record them:

- `scripts/check_fixture_integrity.sh` fails `make lint` and CI on any drift, and prints
  the restore command.
- A `PreToolUse` hook blocks writes to `data/sample-data` before they land — the one
  check that must gate rather than report.

Worth checking locally whether an editor has format-on-save active for JSON in this
folder, or the same reformat will return.

---

## Session 003 — 2026-08-25 — OQ-07 and OQ-01 resolved; ADR-008, ADR-009, ADR-010

**Goal.** Decide the extension surface, then the compute engine that follows from it.
Spec session — no pipeline implementation.

**Decisions.**

| ADR | Decision |
|---|---|
| 008 | Metrics are registered Python functions (`@metric`) over an exported CSV/JSON fact table; `docs/METRICS.md` generated from the registry |
| 009 | The Python standard library is the compute engine; zero runtime dependencies, permanently |
| 010 | Negative: no metric definition language, no MCP server, no semantic layer — each with named reversal conditions |

**The reorder paid for itself.** Session 002 moved OQ-07 ahead of OQ-01 on the argument
that the engine choice is downstream of the extension surface. That turned out to be
load-bearing rather than tidy: with metrics resolved to Python functions, DuckDB lost its
decisive advantage — SQL as the metric surface — and OQ-01 landed on the **standard
library**, the opposite of the spike's provisional lean. Deciding OQ-01 first would have
let the engine choose the extension surface by default, which is exactly the "confident
code satisfying an ambiguous spec" failure the playbook opens with.

**ADR numbering corrected.** Session 001 pre-assigned ADR numbers to unwritten decisions
(`OQ-07 → ADR-013`). Numbers are assigned when an ADR is *written*, and questions are not
answered in ID order — so OQ-07, decided first, holds ADR-008. Reserving numbers for
decisions not yet made guarantees gaps and misleading cross-references. The PMA now says
so under the ADR index, and the "Blocks" column names the code that cannot be written
rather than a future ADR number.

**Enforcement added, per ADR-007's thesis.** An ADR nobody can violate accidentally is
worth more than one everybody agrees with:

- `scripts/lint_architecture.py` gained a fourth rule: no module under `src/hippo_pipeline/`
  may import anything outside the standard library, checked against
  `sys.stdlib_module_names`. A stray `import polars` now fails `make lint` and CI instead
  of quietly becoming a dependency nobody decided on. The rule applies to `gateway/` too —
  ADR-009 admits no exemption.
- A fixture module importing `polars` and `duckdb` was added, and the linter's own tests
  now assert both directions for all four rules.
- `scripts/` is now linted by ruff. It had been excluded, which meant the architectural
  linter — a merge gate with its own tests — was itself unlinted. `T20` and `ANN` are
  ignored there because printing to stdout is those tools' interface.

**What was deliberately NOT done.** No `metrics/` implementation, no `@metric` decorator,
no registry. ADR-008 fixes the contract; F-04 implements it, in its own session, after its
spec and Gherkin exist.

**Verification.** `ruff check src tests scripts` clean, `ruff format --check` clean,
architectural lint clean on the package and failing on the fixture for all four rules,
fixture integrity OK, mypy strict clean over 11 files, 5/5 deterministic tests passing,
`profile_sample_data.py` still runs.

**Next action.** **OQ-02 — the malformed-record policy.** Now a small decision: ADR-009
makes it plain Python and ADR-008 fixed where rejects are exported, so what remains is the
policy (drop / fail the run / quarantine) and the shape of the reason record. The sample
data gives three concrete cases to decide against — two claims missing `quantity` and one
with `quantity == 0`, all three belonging to a *valid* pharmacy. Then **F-04**, the metric
registry, which ADR-008 already unblocked and which depends on no open question.
