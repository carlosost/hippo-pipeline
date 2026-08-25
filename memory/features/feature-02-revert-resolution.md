# Feature 02 — Domain model and revert resolution

**Status:** Done
**PMA feature ID:** F-02
**ADRs this depends on:** ADR-003 (pure domain layer), ADR-009 (`Decimal`), ADR-011 (quarantine), ADR-012 (revert resolution), ADR-013 (UTC), ADR-014 (current-state)
**Open questions required:** none — all resolved

## Purpose

Define the types the whole system passes around, and answer the one question every metric
depends on: **is this claim reverted?**

This is the highest-risk code in the project. Not because it is hard — it is a dictionary and
a loop — but because every plausible-looking wrong answer here produces a plausible-looking
wrong number downstream, and nothing crashes.

## Input contract

```python
def resolve_reverts(
    claims: Sequence[Claim],
    reverts: Sequence[Revert],
    quarantined_claim_ids: Set[str] = frozenset(),
) -> ResolutionResult: ...
```

> **Refined during implementation.** The spec originally passed `accepted_claim_ids`.
> That set is derivable from `claims`, so it carried no information; what resolution
> actually cannot derive is which claims the gateway *quarantined*, which is what
> separates `claim_not_accepted` from `claim_not_found`. Recorded here rather than left
> as a spec that disagrees with the code.

Pure. No IO, no clock, no randomness (ADR-003). `accepted_claim_ids` is passed in rather than
derived from `claims`, because a revert may point at a claim that was rejected or excluded
during ingest — and those two outcomes need different reason codes.

## The domain types

```python
@dataclass(frozen=True, slots=True)
class Pharmacy:
    npi: str
    chain: str

@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    npi: str
    ndc: str
    price: Decimal
    quantity: Decimal          # guaranteed > 0 by F-01
    timestamp: datetime        # tz-aware, UTC
    reverted: bool = False
    reverted_at: datetime | None = None

@dataclass(frozen=True, slots=True)
class Revert:
    id: str                    # NOT unique - see ADR-012
    claim_id: str
    timestamp: datetime

@dataclass(frozen=True, slots=True)
class Dataset:
    claims: tuple[Claim, ...]
    reverts: tuple[Revert, ...]
    pharmacies: Mapping[str, Pharmacy]
```

`Dataset` is what every metric receives (ADR-008). Frozen, so a metric cannot mutate what the
next metric reads.

**A reverted claim is retained, not removed** (ADR-012). It carries `reverted=True` and
`reverted_at`, leaves revenue and fill counts, and enters reversal metrics. Deleting it would
make the reversal rate uncomputable.

## Output contract

```python
@dataclass(frozen=True)
class ResolutionResult:
    claims: tuple[Claim, ...]                # same order in, reverted flags applied
    excluded: tuple[QuarantinedRecord, ...]  # reverts that could not be linked
    counts: ResolutionCounts                 # per data-quality code
```

## The rules, restated as code would see them

Every one of these comes from ADR-012:

1. Group reverts by `claim_id`. **The revert `id` is not a key** — three ids in the sample
   appear twice with different timestamps.
2. A claim is reverted **at most once**. Where several reverts target one claim, `reverted_at`
   is the **earliest** timestamp and each extra is counted under
   `duplicate_revert_for_claim`.
3. A revert timestamped **before** its claim still counts. The claim is reverted; the record
   is counted under `revert_precedes_claim`.
4. A revert whose `claim_id` is in **no** ingest outcome is excluded with `claim_not_found`.
5. A revert whose `claim_id` was **rejected or excluded** during ingest is excluded with
   `claim_not_accepted`. Different cause from (4), so a different code — one is a missing
   input file, the other is a scope decision.
6. Neither (4) nor (5) fails the run.

## Acceptance criteria

`tests/bdd/features/revert_resolution.feature`. Failure paths first.

## Non-goals

- Reading anything. F-01 supplies the records.
- Any metric. F-03 and F-04 consume `Dataset`.
- Deciding *what* a reverted claim means for revenue — that is each metric's business rule,
  stated in its `@metric` declaration.

## Conflict Check

| ADR / Contract | Touched? | How | Verdict |
|---|---|---|---|
| ADR-003 pure domain | **yes** | Defines the layer | compatible — arch lint already forbids IO here |
| ADR-004 two tiers | yes | Every rule is a deterministic unit test | compatible — this layer needs no fixtures on disk |
| ADR-005 additive | yes | `Claim` gains `reverted`/`reverted_at` | compatible — both have defaults |
| ADR-008 metric signature | **yes** | Defines `Dataset`, the metric argument | compatible — frozen, as ADR-008's amendment requires |
| ADR-009 stdlib, `Decimal` | yes | `decimal`, `datetime`, `dataclasses` | compatible |
| ADR-011 quarantine | **yes** | Emits `QuarantinedRecord` with new codes | compatible — additive per ADR-005 |
| ADR-012 revert resolution | **yes** | Implements it in full | compatible |
| ADR-013 UTC | yes | Comparing `revert.timestamp < claim.timestamp` needs one basis | compatible — F-01 already made every timestamp UTC-aware |
| ADR-014 current-state | yes | Reverts for out-of-scope claims vanish with them | compatible — code `claim_not_accepted` |
| §1.3.4 byte-identical output | **yes** | Claim order must be preserved and revert grouping must be deterministic | compatible — **watch item:** iterate `sorted()` groups, never raw dict order, and never rely on set iteration order |

**One watch item, recorded so it is not rediscovered:** grouping by `claim_id` in a `dict` is
insertion-ordered in CPython but that is an implementation detail to lean on only
deliberately. Emit excluded records in sorted `(claim_id, revert.id, timestamp)` order so the
quarantine file is byte-stable regardless.

## Definition of Done

- [x] PMA updated in the same change as the code
- [x] All `revert_resolution.feature` scenarios pass
- [x] Unit tests cover all six rules and both orphan causes separately
- [x] A test asserts resolution is pure: same inputs, same outputs, no clock
- [x] System-tier test reproduces the sample's 3 duplicates, 2 out-of-order, 0 not-found, 45 not-accepted
- [x] `make check` output pasted into the session
- [x] This file marked `Status: Done`
