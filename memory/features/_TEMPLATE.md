# Feature NN — <short name>

**Status:** Specified | In progress | Done
**PMA feature ID:** F-NN
**ADRs this depends on:** ADR-NNN, ADR-NNN
**Open questions this requires resolved:** OQ-NN

## Purpose

One paragraph: the business question this answers, or the capability it unlocks. If it
cannot be written without naming a consumer, the feature is not ready to specify.

## Input contract

What this reads, with types and source. Name the module it comes from — not "the data".

## Output contract

What this writes or returns, with types and destination. Every field named, every field
typed. Additive-only per ADR-005.

## Acceptance criteria

Gherkin lives in `tests/bdd/features/<name>.feature`. Write the **failure** scenarios
first — the security and correctness boundaries are the ones the happy path hides.

- [ ] Scenario: <happy path>
- [ ] Scenario: <malformed input>
- [ ] Scenario: <boundary named by the ADR>

## Non-goals

What this feature explicitly does not do, and which feature will. This section is what
stops scope creep during implementation.

## Conflict Check

Run before implementation. One row per existing ADR and data contract.

| ADR / Contract | Touched? | How | Verdict |
|---|---|---|---|

## Definition of Done

- [ ] PMA updated in the same change as the code
- [ ] All Gherkin scenarios pass
- [ ] Unit tests cover the contract *and* the failure path
- [ ] `make check` output pasted into the session
- [ ] This file marked `Status: Done`
