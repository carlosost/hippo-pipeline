# Metrics

**Generated from the registry - do not edit by hand.**
Regenerate with `make catalog`; `make lint` fails if this file has drifted.

Every metric below is one module in `src/hippo_pipeline/metrics/`. Adding one costs a
module and a test: no ingestion code, no configuration, no registration list to update.

Each run also writes the rows behind these numbers to `out/`, so a question no metric
answers can be asked of the exported fact table directly.

**Time basis:** all timestamps are interpreted as UTC. The source carries no offset, so
this is a declared assumption, not a measurement (ADR-013).


| Metric | Grain | Question |
|---|---|---|
| [`chain_ndc_price_rank`](#chain_ndc_price_rank) | `ndc, chain` | For each drug, which chain dispenses it most cheaply? Chains ranked by the unit price actually paid. |
| [`drug_price_dispersion`](#drug_price_dispersion) | `ndc` | Where are prices out of line? For each drug, how widely does the unit price vary across the fills we paid for? |
| [`pharmacy_ndc_summary`](#pharmacy_ndc_summary) | `npi, ndc` | For each pharmacy and drug: how many fills completed, how many were reverted, what revenue did the completed fills produce, and at what average unit price? |
| [`pharmacy_performance`](#pharmacy_performance) | `npi` | Which pharmacies are underperforming? Volume, revenue and reversal rate per pharmacy, with a confidence bound so small samples are not mistaken for problems. |

---

## chain_ndc_price_rank

**Question.** For each drug, which chain dispenses it most cheaply? Chains ranked by the unit price actually paid.

**Grain.** `ndc, chain`

**Output.** `out/chain_ndc_price_rank.csv` and `out/chain_ndc_price_rank.json`

**Columns.**

| Column | Definition |
|---|---|
| `ndc` | part of the grain |
| `chain` | part of the grain |
| `fills` | completed fills only (ADR-015) |
| `total_quantity` | — |
| `revenue` | — |
| `avg_unit_price` | sum(price) / sum(quantity) - quantity-weighted, so it answers what was paid per unit rather than what the average fill charged (ADR-015) |
| `price_rank` | 1 = cheapest chain for this drug. Ties break on chain name so the ranking is reproducible rather than dependent on iteration order |

_Defined in `hippo_pipeline/metrics/chain_ndc_price_rank.py`._

---

## drug_price_dispersion

**Question.** Where are prices out of line? For each drug, how widely does the unit price vary across the fills we paid for?

**Grain.** `ndc`

**Output.** `out/drug_price_dispersion.csv` and `out/drug_price_dispersion.json`

**Columns.**

| Column | Definition |
|---|---|
| `ndc` | part of the grain |
| `fills` | completed fills only; a reverted fill is a price nobody paid (ADR-015) |
| `min_unit_price` | price / quantity per fill, then the minimum |
| `p25_unit_price` | nearest-rank 25th percentile: sorted values at index floor(n*0.25) |
| `median_unit_price` | nearest-rank 50th percentile. On the sample dataset this is the column that carries signal - medians fall into three bands while min and max are identical for all ten drugs |
| `p75_unit_price` | nearest-rank 75th percentile |
| `max_unit_price` | — |
| `max_over_min` | max_unit_price / min_unit_price. Kept because it matters on real data, but on the sample it is exactly 2948.6667 for every drug and so distinguishes nothing |

_Defined in `hippo_pipeline/metrics/drug_price_dispersion.py`._

---

## pharmacy_ndc_summary

**Question.** For each pharmacy and drug: how many fills completed, how many were reverted, what revenue did the completed fills produce, and at what average unit price?

**Grain.** `npi, ndc`

**Output.** `out/pharmacy_ndc_summary.csv` and `out/pharmacy_ndc_summary.json`

**Columns.**

| Column | Definition |
|---|---|
| `npi` | part of the grain |
| `chain` | — |
| `ndc` | part of the grain |
| `fills` | count of claims that were not reverted |
| `reverted` | count of claims that were reverted; a reverted fill is treated as though it never happened for revenue and volume (ADR-012) |
| `revenue` | sum(price) over completed fills only, exact Decimal |
| `avg_unit_price` | sum(price) / sum(quantity) over completed fills only - quantity-weighted, so it answers 'what was actually paid per unit', not 'what did the average fill charge'. Null when no completed fill has quantity |

_Defined in `hippo_pipeline/metrics/pharmacy_ndc_summary.py`._

---

## pharmacy_performance

**Question.** Which pharmacies are underperforming? Volume, revenue and reversal rate per pharmacy, with a confidence bound so small samples are not mistaken for problems.

**Grain.** `npi`

**Output.** `out/pharmacy_performance.csv` and `out/pharmacy_performance.json`

**Columns.**

| Column | Definition |
|---|---|
| `npi` | part of the grain |
| `chain` | — |
| `claims` | fills + reverted; every accepted claim for this pharmacy |
| `fills` | — |
| `reverted` | — |
| `reversal_rate` | reverted / claims, rounded to 6 decimal places |
| `reversal_rate_lower_95` | lower bound of the 95% Wilson score interval on reverted/claims. Rank by this, not by reversal_rate: with unequal denominators the raw rate puts 1-in-10 above 40-in-1000. On the sample dataset every pharmacy's interval overlaps every other's, which is the honest answer - no pharmacy is an outlier |
| `revenue` | sum(price) over completed fills only, exact Decimal (ADR-015) |
| `distinct_drugs` | count of distinct NDCs dispensed, reverted fills included |

_Defined in `hippo_pipeline/metrics/pharmacy_performance.py`._
