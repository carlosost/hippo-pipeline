# Specification for F-01. Written before the implementation (playbook 1.6).
# Step definitions land in the implementation session; until then this file is the contract.
Feature: Ingesting claims, reverts and pharmacies
  As the pipeline
  I want every input record either accepted or quarantined with a reason
  So that no number I produce is unexplainable

  Background:
    Given the pharmacy dataset contains npi "0123456789" in chain "saint"
    And the pharmacy dataset contains npi "3333333333" in chain "health"

  # ---------------------------------------------------------------- defects --
  Scenario: A claim missing a required field is rejected
    Given a claims file "claims-a.json" containing a claim with no "quantity"
    When the directories are ingested
    Then the claim is not accepted
    And it appears in the rejected sink with reason "missing_field:quantity"
    And the rejected record records source file "claims-a.json" and its index

  Scenario: A claim with zero quantity is rejected, not silently divided by
    Given a claims file containing a claim with quantity 0
    When the directories are ingested
    Then it appears in the rejected sink with reason "non_positive:quantity"

  Scenario: A claim whose quantity is not numeric is rejected
    Given a claims file containing a claim with quantity "ten"
    When the directories are ingested
    Then it appears in the rejected sink with reason "not_a_number:quantity"

  Scenario: An array element that is not an object is rejected
    Given a claims file whose third element is the string "oops"
    When the directories are ingested
    Then it appears in the rejected sink with reason "not_an_object"
    And the other elements of that file are still accepted

  Scenario: An unparseable file does not stop the run
    Given a claims file "broken.json" containing invalid JSON
    And a claims file "good.json" containing 2 valid claims
    When the directories are ingested
    Then one rejected record has reason "file_unparseable" and source file "broken.json"
    And 2 claims are accepted

  Scenario: A record accumulates every applicable reason, not just the first
    Given a claims file containing a claim with no "price" and an unparseable timestamp
    When the directories are ingested
    Then its reasons include "missing_field:price" and "unparseable_timestamp"

  # ------------------------------------------------------------- exclusions --
  Scenario: A claim for a pharmacy we do not have is excluded, not rejected
    Given a claims file containing a valid claim for npi "9999999999"
    When the directories are ingested
    Then the claim is not accepted
    And it appears in the excluded sink with reason "npi_not_in_pharmacy_dataset"
    And the rejected sink is empty

  # ------------------------------------------------------------ type rules --
  Scenario Outline: Identifiers keep their leading zeros
    Given a claims file containing a valid claim with <field> "<value>"
    When the directories are ingested
    Then the accepted claim's <field> is exactly "<value>"

    Examples:
      | field | value       |
      | npi   | 0123456789  |
      | ndc   | 00054027225 |

  Scenario Outline: Quantity arrives as an integer or a float and both are accepted
    Given a claims file containing a valid claim with quantity <quantity>
    When the directories are ingested
    Then the accepted claim's quantity equals <quantity>

    Examples:
      | quantity |
      | 15       |
      | 90.0     |
      | 8.5      |

  Scenario: Money is exact, never round-tripped through a float
    Given a claims file containing a valid claim with price 0.1 and quantity 3
    When the directories are ingested
    Then the accepted claim's price is exactly Decimal("0.1")

  Scenario: Naive timestamps are read as UTC
    Given a claims file containing a valid claim timestamped "2026-03-01T14:40:11"
    When the directories are ingested
    Then the accepted claim's timestamp is "2026-03-01T14:40:11+00:00"

  Scenario: Pharmacy columns are read by name, not by position
    Given a pharmacy file whose header is "chain,npi"
    When the directories are ingested
    Then the pharmacy with npi "0123456789" is in chain "saint"

  # -------------------------------------------------------------- run rules --
  Scenario: Several directories in one list are all read
    Given claims directory "batch-1" containing 2 valid claims
    And claims directory "batch-2" containing 3 valid claims
    When the directories are ingested
    Then 5 claims are accepted

  Scenario: An empty directory is not an error
    Given an empty claims directory
    When the directories are ingested
    Then 0 claims are accepted
    And the run does not fail

  Scenario: Every record is accounted for
    Given a claims file containing 10 valid, 2 invalid and 3 out-of-scope claims
    When the directories are ingested
    Then records read equals accepted plus rejected plus excluded

  Scenario: A high defect rate stops the run
    Given a claims file containing 1 valid and 9 invalid claims
    And a maximum reject rate of 0.01
    When the directories are ingested
    Then the run exits non-zero
    And the counts are still reported

  Scenario: Out-of-scope records never trip the reject threshold
    Given a claims file containing 1 valid and 99 out-of-scope claims
    And a maximum reject rate of 0.01
    When the directories are ingested
    Then the run does not fail
