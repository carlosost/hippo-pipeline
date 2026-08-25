# Specification for F-03. These scenarios state what the metrics promise a business
# reader, in the language the brief uses.
Feature: The exported metric set
  As a business analyst
  I want aggregates that answer the questions in the brief
  So that I can act on them without being misled by small samples or synthetic spread

  # ------------------------------------------- which pharmacies underperform --
  Scenario: Reversal rate is reported with a confidence bound, not on its own
    Given a pharmacy with 1 reversal in 10 claims
    And a pharmacy with 40 reversals in 1000 claims
    When pharmacy performance is computed
    Then the first has the higher reversal rate
    But the second has the higher lower bound
    And ranking by the bound puts the larger sample first

  Scenario: A reverted fill counts as a claim but produces no revenue
    Given a pharmacy with 2 completed fills worth 40.00 and 1 reverted fill worth 99.00
    When pharmacy performance is computed
    Then it reports 3 claims, 2 fills and revenue of 40.00

  # ------------------------------------------------ where prices are out of line --
  Scenario: Price dispersion leads with quantiles because min and max are degenerate here
    Given the sample dataset
    When drug price dispersion is computed
    Then every drug has the same max_over_min ratio
    And the median unit price falls into more than one band

  Scenario: A price nobody paid is not a price
    Given a drug with a completed fill at 10.00 per unit and a reverted fill at 9999.00
    When drug price dispersion is computed
    Then the maximum unit price is 10.0000

  # -------------------------------------------------- which chain is cheapest --
  Scenario: Chains are ranked by what was actually paid per unit
    Given a chain that filled 1 unit at 100.00 and 100 units at 100.00
    When chain price ranking is computed
    Then its average unit price is 1.9802 rather than 50.5000

  Scenario: The cheapest chain for a drug is ranked first
    Given three chains dispensing one drug at 25.00, 10.00 and 5.00 per unit
    When chain price ranking is computed
    Then rank 1 is the chain at 5.00 per unit

  # ------------------------------------------------------------- extensibility --
  Scenario: Every metric declares the business question it answers
    When the catalogue is rendered
    Then every registered metric has a non-empty question

  Scenario: Every figure with more than one definition states which one it used
    When the catalogue is rendered
    Then the unit price columns say they are quantity-weighted
