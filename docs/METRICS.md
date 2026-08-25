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
| [`pharmacy_ndc_summary`](#pharmacy_ndc_summary) | `npi, ndc` | For each pharmacy and drug: how many fills completed, how many were reverted, what revenue did the completed fills produce, and at what average unit price? |

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
