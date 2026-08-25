# Specification for F-04. The registry is the whole of ADR-008's "framework".
Feature: Registering and running metrics
  As an analyst or an agent
  I want to add a metric by writing one module and one test
  So that extending this pipeline never requires reading its ingestion code

  # ------------------------------------------------- declaration is checked --
  Scenario: A metric declared without a business question cannot be imported
    Given a metric module declaring an empty question
    When the metrics package is discovered
    Then discovery raises, naming the offending module

  Scenario: Two metrics cannot share a name
    Given a metric module declaring the name "revenue"
    And another metric module declaring the name "revenue"
    When the metrics package is discovered
    Then discovery raises, naming both modules

  # ------------------------------------------------------- rows are checked --
  Scenario: A row containing a column that was not declared fails the run
    Given a metric declaring columns "npi, fills" that returns a row with key "revenue"
    When the metrics are run
    Then the run fails, naming the metric and the key "revenue"

  Scenario: A row missing a declared column fails the run
    Given a metric declaring columns "npi, fills" that returns a row with only "npi"
    When the metrics are run
    Then the run fails, naming the metric and the column "fills"

  Scenario: A metric that raises fails the run and is not quarantined
    Given a metric that raises ValueError
    When the metrics are run
    Then the run fails
    And nothing is written to the rejected sink

  # ---------------------------------------------------------- happy paths --
  Scenario: Metrics run in sorted name order regardless of import order
    Given a metric named "zebra" imported first
    And a metric named "alpha" imported second
    When the metrics are run
    Then the results are ordered "alpha", "zebra"

  Scenario: Each metric writes one CSV and one JSON named after it
    Given a metric named "pharmacy_ndc_summary" returning 3 rows
    When the metrics are run and written to the output directory
    Then "out/pharmacy_ndc_summary.csv" contains a header and 3 rows
    And "out/pharmacy_ndc_summary.json" contains 3 objects

  Scenario: Decimal values survive export exactly
    Given a metric returning a revenue of Decimal("1667262.6000")
    When the metrics are run and written to the output directory
    Then the JSON contains "1667262.6000" and not a float

  Scenario: A metric receives the dataset and never opens a file
    Given a metric that inspects its argument
    When the metrics are run
    Then it receives a Dataset exposing claims, reverts and pharmacies

  # ------------------------------------------------------------- catalogue --
  Scenario: The catalogue is generated from the registry
    Given a metric named "reversal_rate" with a question, a grain and a measure formula
    When the catalogue is rendered
    Then it lists "reversal_rate" with its question, its grain, its columns and the formula

  Scenario: A stale catalogue fails the lint
    Given docs/METRICS.md does not match the registry
    When the lint runs
    Then it fails and prints the command that regenerates the catalogue

  # ------------------------------------------------------------ invariants --
  Scenario: Two runs over identical inputs produce identical bytes
    Given a dataset and a set of metrics
    When the metrics are run and written twice to different directories
    Then every output file is byte-identical between the two runs

  Scenario: The tested path is the shipped path
    Given the CLI is invoked against the sample data
    Then it executes the same run_all used by the tests
