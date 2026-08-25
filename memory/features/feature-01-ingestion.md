# Feature 01 — Ingestion gateway and quarantine

**Status:** Done
**PMA feature ID:** F-01
**ADRs this depends on:** ADR-003 (IO chokepoint), ADR-009 (stdlib, `Decimal`), ADR-011 (quarantine), ADR-013 (UTC), ADR-014 (current-state reference data)
**Open questions required:** none — all resolved

## Purpose

Turn three lists of directory paths into validated domain objects plus an auditable record
of everything that did not make it through. This is the only code in the system permitted to
touch the filesystem (ADR-003), so every decision about *what the bytes mean* lives here and
nowhere else.

The consumer is `domain/` (F-02), which must be able to assume its inputs are already valid.
A validation error surfacing downstream means this boundary let something through.

## Input contract

```python
def ingest(
    pharmacy_dirs: Sequence[str],
    claim_dirs: Sequence[str],
    revert_dirs: Sequence[str],
) -> IngestResult: ...
```

Three **lists** of directories, per the brief. Each directory is scanned non-recursively for
`*.csv` (pharmacies) or `*.json` (claims, reverts). Files are read in sorted path order so
record indices are stable across runs (charter §1.3.4).

| Source | Format | Parsing rules |
|---|---|---|
| pharmacies | CSV with header | Columns accessed **by name**, never by position — the sample file's header is `chain,npi`, the reverse of the brief's table. Every value stays a string. |
| claims | JSON array per file | Each element must be an object carrying `id`, `npi`, `ndc`, `price`, `quantity`, `timestamp` |
| reverts | JSON array per file | Each element must be an object carrying `id`, `claim_id`, `timestamp` |

**Type rules that are not negotiable:**

- `npi`, `ndc`, `id`, `claim_id` are **strings**. Leading zeros are significant (`0123456789`
  is a real NPI in the sample; 9 of 10 NDCs begin with `0`). Nothing may coerce them to int.
- `price` and `quantity` become `Decimal`, parsed **from the raw JSON text**, not via `float`
  (ADR-009). `quantity` legitimately arrives as either int or float — both are accepted.
- `timestamp` parses to a timezone-aware `datetime` in UTC (ADR-013).

## Output contract

```python
@dataclass(frozen=True)
class IngestResult:
    pharmacies: Mapping[str, Pharmacy]      # keyed by npi
    claims: tuple[Claim, ...]               # accepted, in file-then-index order
    reverts: tuple[Revert, ...]             # accepted
    rejected: tuple[QuarantinedRecord, ...] # schema violations
    excluded: tuple[QuarantinedRecord, ...] # valid, out of scope
    counts: IngestCounts                    # read / accepted / rejected / excluded, per code, per file
```

```python
@dataclass(frozen=True)
class QuarantinedRecord:
    source_file: str          # basename, not the absolute path - paths differ per machine
    record_index: int         # 0-based position within its file
    reasons: tuple[str, ...]  # one or more codes; never prose
    raw: str                  # the record verbatim, so it can be re-fed after a fix
```

## Reason codes produced here

Record shape and pharmacy scope only. Linkage codes (`claim_not_found`,
`claim_not_accepted`) belong to F-02 — this feature knows nothing about revert semantics.

| Code | Sink | Meaning |
|---|---|---|
| `file_unparseable` | rejected | The file is not valid JSON/CSV. One record emitted for the file; the run continues |
| `not_an_object` | rejected | An array element is not a JSON object |
| `missing_field:<name>` | rejected | A required field is absent |
| `not_a_number:<field>` | rejected | `price` or `quantity` is present but not numeric |
| `non_positive:quantity` | rejected | `quantity <= 0`. Separated from `not_a_number` because it passes a naive type check and still divides by zero |
| `unparseable_timestamp` | rejected | `timestamp` is present but not ISO-8601 |
| `npi_not_in_pharmacy_dataset` | **excluded** | Well-formed and not ours. **Not a defect** (ADR-011) |

A record accumulates **every** applicable code, not just the first. The first failure is not
necessarily the interesting one.

## Acceptance criteria

`tests/bdd/features/ingestion.feature`. Failure paths first.

## Non-goals

- Revert linkage — F-02.
- Writing any file — F-05 owns the writers. `ingest` returns data; the manifest is assembled
  downstream from `IngestCounts`.
- Recursive directory walking, archives, compression. The brief supplies flat directories.
- Incremental or resumable reads — that is OQ-09, still open.

## Conflict Check

Run before implementation, per playbook §1.5.

| ADR / Contract | Touched? | How | Verdict |
|---|---|---|---|
| ADR-001 PMA is source of truth | yes | Adds the ingest contract | compatible — recorded here and in §2.5 |
| ADR-002 uv toolchain | no | — | no interaction |
| ADR-003 IO chokepoint | **yes** | This *is* the chokepoint; all parsing lives in `gateway/` | compatible — the arch lint permits `json`/`csv`/`pathlib` only here |
| ADR-004 two test tiers | yes | Unit tests must run without touching disk | compatible — `ingest` takes directory paths, so unit tests use `tmp_path`; the sample-data run is system tier |
| ADR-005 additive contracts | yes | `IngestResult` and the reason codes are contracts | compatible — codes grow, never rename |
| ADR-006 commits | no | — | no interaction |
| ADR-007 enforced by tooling | yes | New module triggers the arch lint and the matching-unit-test hook | compatible |
| ADR-008 metric signature | no | Metrics never see raw records | no interaction |
| ADR-009 stdlib, `Decimal` | **yes** | `json`, `csv`, `decimal`, `datetime` only | compatible — **watch item:** `Decimal(str(x))` after `json.load` already lost precision. Must parse numbers from text, via `json.loads(..., parse_float=Decimal, parse_int=Decimal)` |
| ADR-010 no DSL/MCP | no | — | no interaction |
| ADR-011 quarantine | **yes** | Implements it | compatible — two sinks, codes not prose |
| ADR-012 revert resolution | yes | Produces the reverts it consumes | compatible — linkage codes deliberately excluded from here |
| ADR-013 UTC | **yes** | Naive timestamps become UTC-aware at parse time | compatible — conversion happens once, at the boundary |
| ADR-014 current-state pharmacies | **yes** | Pharmacy file read first; scope decided against it for the whole run | compatible |
| §2.4 observed data | yes | 3 rejects, 4,085 exclusions expected on the sample | compatible — becomes a system-tier assertion |

**One item found, not a conflict but a trap:** `json.load` converts numbers to `float` before
any code sees them, so `Decimal(str(value))` inherits the float's error. ADR-009 requires
parsing from the text. Recorded here so the implementation session does not rediscover it.

## Definition of Done

- [x] PMA updated in the same change as the code
- [x] All `ingestion.feature` scenarios pass
- [x] Unit tests cover every reason code and the `read == accepted + rejected + excluded` invariant
- [x] System-tier test asserts 27,076 accepted / 3 rejected / 4,085 excluded on the sample
- [x] `make check` output pasted into the session
- [x] This file marked `Status: Done`
