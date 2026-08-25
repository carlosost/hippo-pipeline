# Specification for F-02. Every scenario traces to a rule in ADR-012.
Feature: Resolving reverts against claims
  As the pipeline
  I want each claim to be reverted at most once, with every unlinkable revert accounted for
  So that reversal counts and reverted-claim counts can never silently disagree

  Background:
    Given an accepted claim "C1" for npi "0123456789" timestamped "2026-02-01T10:00:00Z"
    And an accepted claim "C2" for npi "0123456789" timestamped "2026-02-01T11:00:00Z"

  # ------------------------------------------------- unlinkable reverts (4,5) --
  Scenario: A revert pointing at a claim nobody has seen is excluded, not fatal
    Given a revert for claim "GHOST" timestamped "2026-03-01T09:00:00Z"
    When the reverts are resolved
    Then the revert appears in the excluded sink with reason "claim_not_found"
    And the run does not fail

  Scenario: A revert whose claim was rejected during ingest gets a different code
    Given claim "C3" was rejected during ingest
    And a revert for claim "C3" timestamped "2026-03-01T09:00:00Z"
    When the reverts are resolved
    Then the revert appears in the excluded sink with reason "claim_not_accepted"

  Scenario: A revert whose claim was excluded as out of scope gets the same code
    Given claim "C4" was excluded during ingest as out of scope
    And a revert for claim "C4" timestamped "2026-03-01T09:00:00Z"
    When the reverts are resolved
    Then the revert appears in the excluded sink with reason "claim_not_accepted"

  # --------------------------------------------------- duplicate reverts (1,2) --
  Scenario: Two reverts for one claim revert it once, keeping the earliest
    Given a revert for claim "C1" timestamped "2026-05-01T22:38:13Z"
    And a revert for claim "C1" timestamped "2026-03-01T08:25:49Z"
    When the reverts are resolved
    Then claim "C1" is reverted
    And claim "C1" has reverted_at "2026-03-01T08:25:49Z"
    And 1 record is counted under "duplicate_revert_for_claim"

  Scenario: The sample data's case - one revert id, two different timestamps
    Given a revert with id "R-DUP" for claim "C1" timestamped "2026-01-01T12:31:37Z"
    And a revert with id "R-DUP" for claim "C1" timestamped "2026-05-01T22:38:13Z"
    When the reverts are resolved
    Then claim "C1" is reverted exactly once
    And claim "C1" has reverted_at "2026-01-01T12:31:37Z"
    And 1 record is counted under "duplicate_revert_for_claim"

  # ------------------------------------------------------ impossible order (3) --
  Scenario: A revert timestamped before its claim still reverts it
    Given a revert for claim "C2" timestamped "2026-01-15T08:00:00Z"
    When the reverts are resolved
    Then claim "C2" is reverted
    And claim "C2" has reverted_at "2026-01-15T08:00:00Z"
    And 1 record is counted under "revert_precedes_claim"
    And the revert is not excluded

  # ------------------------------------------------------------- happy paths --
  Scenario: A claim with no revert is not reverted
    When the reverts are resolved
    Then claim "C1" is not reverted
    And claim "C1" has no reverted_at

  Scenario: A claim with one revert is reverted at that time
    Given a revert for claim "C1" timestamped "2026-02-02T09:00:00Z"
    When the reverts are resolved
    Then claim "C1" is reverted
    And claim "C1" has reverted_at "2026-02-02T09:00:00Z"

  Scenario: A reverted claim is retained, never dropped
    Given a revert for claim "C1" timestamped "2026-02-02T09:00:00Z"
    When the reverts are resolved
    Then 2 claims are returned
    And claim "C1" still carries its price and quantity

  # ------------------------------------------------------------- invariants --
  Scenario: Resolution is deterministic
    Given a revert for claim "C1" timestamped "2026-02-02T09:00:00Z"
    And a revert for claim "GHOST" timestamped "2026-02-02T09:00:00Z"
    When the reverts are resolved twice
    Then both results are identical, including the order of excluded records

  Scenario: Claim order is preserved
    When the reverts are resolved
    Then the returned claims are in the same order they were given
