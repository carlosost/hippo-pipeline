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
