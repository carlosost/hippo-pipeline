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

### Session 003 addendum — OQ-02 resolved (ADR-011), ADR-008 amended

**Decision.** Quarantine — with the distinction that actually mattered: **rejection and
exclusion are different things and get different sinks.**

3 of 27,076 claims are schema-invalid. 4,085 (15.1%) reference NPIs absent from the
pharmacy file — and those records are not defective, they are simply not ours. A single
quarantine sink would have reported a 15.1% reject rate for a source whose real defect
rate is 0.011%, and buried three genuine defects under 4,085 healthy records. So:
`out/_rejected.csv` for defects, `out/_excluded.csv` for out-of-scope, counted separately
in `out/_manifest.json`.

The rest of ADR-011: machine-readable reason codes rather than prose; a revert orphaned by
its target's quarantine is itself excluded with `claim_not_accepted` (45 records here);
the run exits non-zero above `--max-reject-rate`, default 1%, while exclusion is never a
failure; and a metric that raises fails the run, because a defect in our code is not a
data-quality event.

`read == accepted + rejected + excluded` is now an invariant with a test behind it.

**ADR-008 amended** to pin the metric signature: `(data: Dataset) -> Sequence[Mapping[str,
object]]`, where `Dataset` is frozen and exposes `.claims`, `.reverts`, `.pharmacies`. A
bare claim list was rejected because reversal-rate-per-chain cannot be written against it.
The O(metrics × claims) cost is recorded along with its escape hatch (a fold protocol),
which is a future ADR taken on measurement, not now.

**§2.5 of the PMA is no longer empty.** The output contract is defined: one CSV and one
JSON per metric, the two quarantine sinks, and the manifest.

**F-04 re-sequenced, correcting my own claim.** Session 003 recorded F-04 as depending on
no open question. True of the mechanism, and it dodged the fact that until the domain types
exist the registry's only caller would be its own tests — AP-11 exactly, and the anti-pattern
`CLAUDE.md` forbids. F-04 now ships with F-02 or not at all.

**Next action.** **OQ-03, OQ-04, OQ-10 and OQ-11 in one spec session** — four facets of one
question: what a revert actually invalidates. Concretely to decide: whether a revert
timestamped *before* its claim is honoured (2 records); what happens to a revert whose
`claim_id` is unknown (0 in the sample, so unexercised and still needing a policy); whether
a revert `id` is an identity, given three ids appear twice with *different* timestamps;
what the naive timestamps mean when pharmacies span time zones; and whether pharmacy
reference data is point-in-time or current-state. These are the highest-risk correctness
decisions in the project.

---

## Session 004 — 2026-08-25 — Revert and reference-data semantics; the spec is complete

**Goal.** Resolve the four questions that define what a reversal actually means. These were
the highest-risk correctness decisions in the project — the ones a reviewer will probe,
because every one of them is a place where a plausible-looking number can be wrong.

**Decisions.**

| ADR | Decision | The trap it avoids |
|---|---|---|
| 012 | The reversal key is `claim_id`, not the revert `id`. A claim is reverted at most once; earliest timestamp wins | Three revert ids appear twice with *different* timestamps. Keying on `id` discards a real reversal; keying on the whole record counts three claims as reverted twice. Keying on `claim_id` makes reversal count and reverted-claim count agree by construction |
| 012 | A revert timestamped *before* its claim is honoured and flagged | Rejecting it leaves reversed revenue in the totals — strict on data, wrong on money |
| 012 | An orphan revert is excluded with `claim_not_found`, counted, never fatal | Unobserved in the sample and decided anyway: a missing `claim_id` most likely means a file this run was not given |
| 013 | All timestamps are UTC, and the assumption is published in the manifest and METRICS.md | Silently assuming a zone is how a day-boundary bug ships and survives for months |
| 014 | Pharmacy reference data is current-state | Point-in-time would need effective dates the source does not carry — fabricated provenance is worse than stated simplicity |

**The modelling decision underneath all of it:** a reverted claim is **retained**, carrying
`reverted` and `reverted_at`, not deleted. It leaves revenue and fill counts and enters
reversal metrics. Deleting it would make the reversal rate uncomputable, and the brief calls
the reversal itself a signal worth measuring.

**Assumptions stated rather than hidden.** Three ADRs this session each name something that
is a choice, not a truth: earliest-timestamp-wins affects `reverted_at` and therefore
time-to-revert (ADR-012); UTC is almost certainly wrong for some pharmacies (ADR-013);
history is not stable across runs if the reference file changes (ADR-014). Each is written
into the ADR that causes it, so a reader meets the caveat next to the number rather than
after it.

**Three new reason codes**, added additively to ADR-011: `duplicate_revert_for_claim` (3
records here), `revert_precedes_claim` (2), `claim_not_found` (0). Small numbers, deliberately
visible — they are exactly the signals that would grow quietly if an upstream system started
misbehaving.

**The specification is now complete.** Every structural decision that shapes the code is
made: 14 ADRs, and the only open questions left are OQ-09 (idempotency — one engineering
call), OQ-06 and OQ-08 (which metrics, and how unit price is defined — cheap to change by
construction, since ADR-008 gives each metric its own module), and OQ-12 (deployment prose).

**Verification.** Full gate green: ruff, format, architectural lint (4 rules), doc drift,
fixture integrity, mypy strict, 5/5 deterministic tests.

**Next action.** **Specify F-01, F-02 and F-04 together** — ingestion and quarantine, the
domain model and revert resolution, and the metric registry. One spec session producing three
feature files in `memory/features/` plus their Gherkin, failure scenarios first. They are
specified together because F-04 built alone would have only its own tests as callers (AP-11),
and because F-01's quarantine sinks and F-02's revert resolution share the reason-code
contract. Implementation follows in a separate session, per playbook §2.5.

---

## Session 005 — 2026-08-25 — F-01, F-02 and F-04 specified

**Goal.** Turn fourteen ADRs into executable acceptance criteria. Spec only — no
implementation, per playbook §2.5.

**Produced.** Three feature files in `memory/features/` and three Gherkin files carrying
**41 scenarios**, failure paths first:

| Feature | Scenarios | What it pins down |
|---|---|---|
| F-01 ingestion | 17 | Every reason code, leading-zero preservation, int-or-float quantity, exact `Decimal`, UTC conversion, header-by-name, `read == accepted + rejected + excluded`, the reject-rate threshold, and that exclusions never trip it |
| F-02 revert resolution | 11 | All six ADR-012 rules, including the sample's exact case — one revert id, two timestamps — plus determinism and claim-order preservation |
| F-04 metric registry | 13 | Import-time declaration checks, row-schema validation, a raising metric failing the run, sorted execution, `Decimal` surviving export, catalogue generation and drift, byte-identical reruns |

**Three Conflict Checks run against all 14 ADRs** (playbook §1.5). No conflicts. Four traps
surfaced that would otherwise have been discovered during implementation:

1. **`json.load` converts numbers to `float` before any code sees them**, so `Decimal(str(v))`
   inherits the float's error and quietly violates ADR-009. The fix is
   `json.loads(..., parse_float=Decimal, parse_int=Decimal)` — recorded in F-01's Conflict
   Check.
2. **The metric writers perform IO, so they belong in `gateway/`, not `metrics/`.** The
   instinct is to put them beside the registry; the arch lint would reject it. Recorded in
   F-04.
3. **Revert grouping must emit in sorted order**, not dict-insertion order, or the quarantine
   file is not byte-stable. Recorded in F-02.
4. **`discover()` makes import side effects load-bearing**, so it must be idempotent and
   order-independent — hence execution sorted by name. Recorded in F-04.

**Split of quarantine responsibility, pinned.** F-01 quarantines on *record shape and
pharmacy scope*; F-02 quarantines on *linkage*. So `claim_not_found` and `claim_not_accepted`
are produced by F-02, and F-01 knows nothing about revert semantics. That keeps the gateway
free of domain rules and gives each layer one reason to reject.

**Two tooling additions.**

- `scripts/check_gherkin.py` parses every `.feature` file in `make lint` and CI. Gherkin
  written before the implementation is only useful if it is real Gherkin, and a malformed
  feature file should fail at spec time rather than in the session that tries to bind steps
  to it.
- `make test-bdd` now tolerates pytest's exit code 5 — and *only* 5 — because `tests/bdd`
  legitimately collects nothing until step definitions exist. The guard carries its own
  deletion condition: remove it the moment the first step definition lands.

**What was deliberately NOT done.** No step definitions, no `src/` code. The spec session
produces the contract; the implementation session is told the tests are the specification and
is done when they pass.

**Verification.** Full gate green: ruff, format, architectural lint (4 rules), doc drift,
fixture integrity, Gherkin parse (41 scenarios), mypy strict, 5/5 deterministic tests.

**Next action.** **Implement F-01, F-02 and F-04.** Order within the session: step definitions
for all three feature files (red) → `domain/` types → `gateway/` readers and validation →
revert resolution → registry and writers → one real metric wired to the real CLI, so the
tested path is the shipped path before the session closes. Delete the `test-bdd` exit-5 guard
in the same change.

### Session 005 addendum — ADR-010 amended: no LLM framework

Asked directly whether the pipeline would use LangChain or LangGraph. It will not, and the
reasoning is now recorded rather than left to be re-litigated — a reviewer will likely ask
the same thing, since the brief names AI agents explicitly.

The confusion the amendment resolves: the brief's agent clause is about **consumption, not
implementation**. Agents should be able to use the output and extend the metric set, which is
ADR-008. An agent inside the pipeline would make it worse — there is nothing to orchestrate
in a straight-line batch job, and a non-deterministic component is incompatible with charter
§1.3.4's byte-identical output. ADR-009 forbids the dependency in any case.

Recorded as an amendment to ADR-010 rather than a new ADR: ADR-009 already implied it, and
the decision is the same shape as the MCP and DSL refusals it sits beside — including the
same reversal condition, a live consumer that cannot run Python. ADR-010's title and anchor
are unchanged so existing cross-references keep working; the index row carries the scope
extension.

Also noted in the ADR: `docs/ENGINEERING_PLAYBOOK.md` (LLM agentic systems, LangGraph, RAG,
eval sets) is the right playbook for a different class of project;
`docs/GENERAL_ENGINEERING_PLAYBOOK.md` governs this one.

The README now carries a short "Why there is no LLM in here" section, because this is a
question the deliverable should answer without the reader having to open the PMA.

---

## Session 006 — 2026-08-25 — F-01, F-02 and F-04 implemented

**Goal.** Write the code. Separate session from the spec, per playbook §2.5: mixing them
produces code that confirms the spec rather than testing it.

**Result.** The pipeline runs end to end and reproduces PMA §2.4 exactly — 27,076 claims
read, 22,988 accepted, 3 rejected, 4,085 excluded, 308 reverts, 260 linked, 3
`duplicate_revert_for_claim`, 2 `revert_precedes_claim`, 45 `claim_not_accepted`, 0
`claim_not_found`. 122 tests: 71 unit, 44 acceptance scenarios, 7 system-tier.

**Three things the specification predicted, and one it did not.**

1. **`json.load` converts numbers to `float` before any code sees them.** Caught by F-01's
   Conflict Check at spec time. The fix — `json.loads(parse_float=Decimal,
   parse_int=Decimal)` — has a test that would fail loudly with the naive
   `Decimal(str(value))`: a price of `0.1` would otherwise arrive as
   `0.1000000000000000055511151231257827`. This is the bug that would have produced
   correct-looking money that was quietly wrong.
2. **The metric writers belong in `gateway/`**, not beside the registry. Predicted, and
   the code follows it.
3. **Revert grouping emits in sorted order**, so the quarantine file is byte-stable.
   Predicted; there is a test that resolves the same reverts in reversed input order and
   asserts identical results.
4. **Not predicted:** the architectural lint rejected `cli.py` importing `pathlib`. That
   is the rule working rather than a false positive — path handling *is* IO handling — so
   the writers now take strings and own `Path` themselves. The alternative, exempting
   `cli.py`, would have put the first crack in the boundary.

**Two design refinements, recorded rather than hidden.**

- `resolve_reverts` takes `quarantined_claim_ids`, not the `accepted_claim_ids` the spec
  named. The accepted set is derivable from `claims` and so carried no information; what
  resolution cannot derive is which claims the *gateway* quarantined, which is exactly
  what separates `claim_not_accepted` from `claim_not_found`. F-02's spec file records the
  change beside the original.
- Unlinkable reverts are returned as `ExcludedRevert`, not `QuarantinedRecord`. The domain
  was about to build JSON by string concatenation to fill a `raw` field — which is
  serialization, and serialization belongs to the gateway (ADR-003). The layer boundary
  caught a design mistake before it was written.

**Manifest accounting corrected mid-session.** The first version reported a single
`excluded` count combining ingest exclusions with resolution exclusions, while `balances`
asserted an identity over only the first. A number that no stated identity accounts for is
precisely what this pipeline exists to avoid, so the manifest now reports
`excluded_at_ingest` and `excluded_at_resolution` separately and states its identity
inline.

**AP-11 gate passed.** `grep -rn "run_all" src/ | grep -v tests` returns
`cli.py:87: outputs = run_all(dataset)`. There is also an acceptance scenario asserting
`cli.run_all is registry.run_all` — the same object, not a similar function.

**Tooling.** The `make test-bdd` exit-5 guard was removed; it carried its own deletion
condition and step definitions now exist. `discover()` and `check_catalog.sh` each gained
one optional argument so the acceptance tests exercise the real mechanism against a
throwaway package and a throwaway catalogue, rather than testing them by proxy.

**Verification.** `make check` green: ruff, format, architectural lint (4 rules), doc
drift, fixture integrity, Gherkin parse (41 scenarios), catalogue drift, mypy strict over
31 files, 71 unit + 44 acceptance tests. `make test-system` green: 7 tests.

**Next action.** **OQ-06 and OQ-08 — the metric set.** One reference metric ships and
declares its own unit-price formula in `measures=`. What remains is which further metrics
earn their place, each with a stated business question: reversal rate per pharmacy and per
chain with an explicit small-denominator rule, unit-price dispersion per NDC, revenue per
chain, time-to-revert distribution. Then OQ-09, which today is answered by accident —
reruns are byte-identical and full-recompute — and should be answered on purpose.

---

## Session 007 — 2026-08-25 — The metric set: ADR-015 and ADR-016

**Goal.** Answer OQ-08 (how unit price is defined) and OQ-06 (which metrics ship).

**Method — and a deliberate deviation from §2.5.** The playbook splits spec and
implementation across sessions so that tests specify rather than confirm. For
aggregations that split is the weaker guard: a scenario written the day before can still
be written to match whatever the function will compute. So the expected values were
**derived independently first**, by a throwaway script that re-read the raw files and
re-applied the rules of ADR-011 and ADR-012 without importing anything from
`hippo_pipeline`. The system-tier tests assert those numbers. A figure produced by a
different program cannot be quietly bent to match the implementation.

Every one matched on the first run: 17 pharmacy rows, `4444444444` at 1,236 claims /
20 reversals / rate `0.016181` / bound `0.010499`; 10 dispersion rows with an identical
`2948.6667` ratio; 30 chain-drug rows with `00054027225` ranking doctor `368.9120`,
health `517.7575`, saint `647.4117`.

**ADR-015 — unit price is quantity-weighted.** `sum(price)/sum(quantity)`, not
`mean(price/quantity)`. A PBM negotiates what is paid per unit dispensed, and with unit
price spanning `0.30`–`884.60` for every drug and quantities from 1 to 180 the two
definitions differ materially rather than marginally. Any metric may use the other
definition and must then declare it in `measures=`, so the definition travels with the
number.

**ADR-016 — four metrics ship, and one candidate is rejected with a measurement.**

The two judgement calls are the interesting part:

- **Reversal rate ships with a Wilson 95% lower bound.** Raw rates span
  `0.008451`–`0.016181`; the bounds span `0.003879`–`0.010499` and overlap heavily.
  Ranking on the raw rate would put a pharmacy with 20 reversals in 1,236 fills at the top
  of an "operational problem" list. The bound says plainly that **no pharmacy in this
  sample is an outlier**, which is the honest answer. A metric that invites the business to
  act on noise is worse than no metric.
- **Dispersion leads with quantiles.** Minimum `0.30` and maximum `884.60` for all ten
  drugs — a max/min ratio of exactly `2948.6667` every time. Min and max distinguish
  nothing here; the medians fall into three bands and do. Both are still emitted, because
  on real data min and max matter.

**`drug_common_quantity` rejected.** Measured: nine distinct quantities per drug, each
around 11% of fills, top beating runner-up by roughly half a percentage point. A "most
common quantity" built on that is noise with a schema, and the next refresh would reorder
it. The ADR records the reversal condition — ship it when the modal quantity exceeds ~30%
of fills.

**One implementation choice worth noting.** The Wilson bound uses `Decimal.sqrt()` rather
than `math.sqrt`. A float in the middle of a figure the pipeline promises to reproduce
byte for byte is a cross-platform risk for no benefit, and `Decimal` keeps the whole
calculation in exact arithmetic.

**What ADR-008's amendment bought.** Two of the four metrics need chain membership, which
is why metrics receive the whole `Dataset` rather than a bare claim list. That decision,
made three sessions ago on an argument about metrics that did not exist yet, is now
load-bearing.

**Verification.** `make check` green: 4 feature files / 49 scenarios parse, catalogue
matches the registry, mypy strict over 40 files, 97 unit + 52 acceptance tests.
`make test-system` green: 12 tests, every headline figure matching the independent
derivation.

**Next action.** **OQ-09 — idempotency and late-arriving reverts.** The last open
engineering question. The pipeline is full-recompute today and reruns are byte-identical,
proven by test — the ADR turns that from an accident into a decision, and states what
happens when a revert arrives after the window it belongs to has already been aggregated.
Then OQ-12, which is README prose about deployment and ownership, not code.

---

## Session 008 — 2026-08-25 — OQ-09 resolved, and an ADR caught not keeping its promise

**Goal.** Answer the last open engineering question. It turned out to be four questions
wearing one label, and separating them was most of the work.

**The defect this session found.** ADR-014 states that *"the manifest records a digest of
the pharmacy file used, so any two runs that disagree can be explained rather than argued
about."* **It did not.** The manifest recorded directory paths only. The promise had been
written in session 004 and never implemented.

That is ADR-007's own thesis turned on itself for the second time in this project — a rule
with no enforcement is followed until it isn't — except here the gap was in a *document*
rather than in code, where no lint can see it. It is recorded as an amendment on ADR-014
rather than quietly fixed, because a PMA is only trustworthy if its own defects are
visible.

**ADR-017 — four decisions.**

| # | Decision | Why not the alternative |
|---|---|---|
| 1 | Full recompute, no state between runs | Incremental is faster and is the only option that contradicts charter §1.3.4 — re-runs stop being reproducible. The cost of full recompute is stated: the operator must pass the complete history, or a late revert is correctly reported as `claim_not_found` |
| 2 | Stage output, then swap | Overwriting in place leaves a crashed run's partial files indistinguishable from good ones. Two renames leave a window where `out/` is missing — deliberately, because an obviously absent directory beats a directory holding half of two runs |
| 3 | A failed run writes quarantine and manifest, no metrics | An exit code is easy to ignore in a cron job that only checks whether files appeared. An absent metrics file is not |
| 4 | Hash every input file, plus one combined `inputs_digest` | ADR-014 asked for the pharmacy file only. Once the bytes are in hand the marginal cost of the rest is zero, and claims files change far more often than reference data |

Decision 4 buys a testable invariant: **same `inputs_digest` → byte-identical outputs**,
now asserted in both tiers.

**Implementation notes.**

- Hashing happens on the same buffer that is parsed, so it costs no second pass over the
  input. A file that fails to decode is still hashed — knowing exactly which bytes failed
  is the point.
- The digest covers path as well as content, deliberately: the same bytes in a different
  file is not the same run, because record indices and therefore the quarantine files
  differ.
- The threshold check moved *above* the metric computation. That is the whole of decision 3
  — the ordering is the mechanism.
- Manifest `schema_version` goes to 2. Every field added is additive, so ADR-005 holds; the
  bump is the signal, not a break.

**A second self-inflicted defect, also recorded.** The decision-order table in the PMA had
carried a **duplicate OQ-09 row for two sessions**, from an edit that appended where it
should have replaced. Fixed, and noted in the table itself.

**Verification.** `make check` green: 4 feature files / 49 scenarios, catalogue matches the
registry, mypy strict over 40 files, 110 unit + 52 acceptance tests. `make test-system`
green: 14 tests, including two runs of the sample data agreeing on `inputs_digest`.

**Next action.** **OQ-12 — deployment and ownership.** The last open question, and the only
one that is prose rather than code: where this runs, who owns `gateway/` versus `metrics/`,
how a business user requests a new metric, and how outputs are versioned and published. The
brief explicitly invites assumptions about working in a multidisciplinary team, so this is
answered in the README rather than by building infrastructure nobody asked for.
