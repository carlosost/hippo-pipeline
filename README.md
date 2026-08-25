# hippo-pipeline

A data pipeline over pharmacy **claims** and **reverts** (reversals), producing auditable
metrics for a PBM business team — and built so that analysts and AI agents can extend it
without reading the ingestion code.

Brief: [`docs/ASSIGNMENT.md`](docs/ASSIGNMENT.md).

---

## Status

**Working.** The pipeline runs end to end against the provided sample data, and every
number it produces matches the profile recorded in
[`docs/PROJECT_MEMORY.md` §2.4](docs/PROJECT_MEMORY.md):

```
read 27384  accepted 23296  rejected 3  excluded 4085 (+45 unlinkable reverts)
  claim_not_accepted: 45          npi_not_in_pharmacy_dataset: 4085
  duplicate_revert_for_claim: 3   revert_precedes_claim: 2
  missing_field:quantity: 2       non_positive:quantity: 1
```

Four metrics ship, and **161 tests** — 149 deterministic (97 unit + 52 acceptance
scenarios) and 12 system-tier. Zero runtime dependencies.

| Metric | Answers |
|---|---|
| `pharmacy_ndc_summary` | The base fact table: fills, reversals, revenue and unit price per pharmacy-drug pair |
| `pharmacy_performance` | Which pharmacies are underperforming — with a Wilson 95% lower bound, because ranking on the raw rate puts 1-in-10 above 40-in-1000 |
| `drug_price_dispersion` | Where prices are out of line — quantiles, because min and max are identical for all ten drugs in this data |
| `chain_ndc_price_rank` | Which chain is cheapest for a given drug — the PBM's core job |

Two metrics carry a judgement worth reading [ADR-016](docs/PROJECT_MEMORY.md) for, and one
candidate — most-common-quantity — was **rejected with a measurement**: nine quantities per
drug at roughly 11% each, so a modal quantity beating its runner-up by half a point is
noise with a schema.

Fourteen ADRs were written, conflict-checked and recorded **before** the first line of
implementation. That ordering is the method, not ceremony: it is why the Conflict Check
caught, at spec time, that `json.load` converts numbers to `float` before any code can
wrap them in `Decimal` — a bug that would have produced correct-looking money that was
quietly wrong.

One open question remains: whether re-runs stay full-recompute (OQ-09). They are today,
and reruns are byte-identical — the ADR would make that a decision rather than an
accident.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python ≥3.10.

```bash
git clone <this repo> && cd hippo
make setup          # create .venv, install locked dependencies
make check          # lint + typecheck + 115 deterministic tests — the merge gate

make run ARGS="run \
  --pharmacies data/sample-data/pharmacies \
  --claims     data/sample-data/claims \
  --reverts    data/sample-data/reverts \
  --out        out"
```

Then look at `out/`:

| File | What it holds |
|---|---|
| `pharmacy_ndc_summary.csv` / `.json` | one file per metric, in CSV and JSON |
| `_rejected.csv` | the 3 records that violate the schema, each with machine-readable reason codes |
| `_excluded.csv` | the 4,085 valid records for pharmacies outside the reference file |
| `_excluded_reverts.csv` | the 45 reverts whose claim was never accepted |
| `_manifest.json` | every count, the reject rate, the time-basis assumption, and the identity `read == accepted + rejected + excluded` |

`make run ARGS="metrics"` lists what each metric answers.
`make run ARGS="catalog"` prints [`docs/METRICS.md`](docs/METRICS.md), which is generated
from the registry — `make lint` fails if it has drifted.

## Adding a metric

One module and one test. No ingestion code, no configuration, no registration list:

```python
# src/hippo_pipeline/metrics/reversal_rate_by_chain.py
@metric(
    name="reversal_rate_by_chain",
    question="Which chains reverse the most fills?",
    grain=("chain",),
    columns=("chain", "fills", "reverted", "rate"),
    measures={"rate": "reverted / (fills + reverted)"},
)
def reversal_rate_by_chain(data: Dataset) -> Sequence[Mapping[str, object]]:
    ...
```

Discovery, execution order, CSV/JSON export and the catalogue entry all follow from the
decorator. `question` is mandatory and `@metric` raises at import time without it — a
metric with no stated business question is decoration.

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
