# Feature 03 — The exported metric set

**Status:** Done
**PMA feature ID:** F-03
**ADRs this depends on:** ADR-008 (registry), ADR-012 (reverted claims retained), ADR-015 (unit price), ADR-016 (which metrics)
**Open questions required:** none — ADR-015 and ADR-016 closed OQ-08 and OQ-06

## Purpose

Answer the three questions the brief names — which pharmacies underperform, where prices
are out of line, and which chain is cheapest — and refuse to answer the ones this data
cannot support.

## How this feature was specified

**Expected values were derived independently before the code was written**, by a throwaway
script that re-read the raw files and re-applied the rules of ADR-011 and ADR-012 without
importing anything from `hippo_pipeline`. The system-tier tests assert those numbers.

This substitutes deliberately for the usual spec-session / implementation-session split
(playbook §2.5). The split exists to stop tests that merely confirm what the code already
does. For aggregations, an independent derivation is a stronger guard than a session
boundary: a Gherkin scenario written the day before can still be written to match whatever
the function will compute, but a number produced by a different program cannot.

## Output contract

Four metrics, each `out/<name>.csv` and `out/<name>.json`:

| Metric | Grain | Rows on the sample |
|---|---|---|
| `pharmacy_ndc_summary` | npi × ndc | 170 |
| `pharmacy_performance` | npi | 17 |
| `drug_price_dispersion` | ndc | 10 |
| `chain_ndc_price_rank` | ndc × chain | 30 |

Column definitions are generated into [`docs/METRICS.md`](../../docs/METRICS.md).

## The two judgement calls

**Reversal rate ships with a Wilson 95% lower bound.** Measured on the sample: raw rates
span `0.008451`–`0.016181` and the bounds span `0.003879`–`0.010499`, overlapping heavily.
Ranking on the raw rate would put a pharmacy with 20 reversals in 1,236 fills at the top of
an "operational problem" list. The bound says plainly that no pharmacy here is an outlier.

**Dispersion leads with quantiles.** Minimum `0.30` and maximum `884.60` for **all ten**
drugs — a max/min ratio of exactly `2948.6667` every time. Min and max distinguish nothing
in this data; the medians fall into three bands and do.

## Non-goals

- `drug_common_quantity` — rejected with a measurement, see ADR-016. Nine quantities per
  drug at roughly 11% each; a modal quantity that beats its runner-up by half a point is
  noise with a schema.
- Time-to-revert and claims-per-month — deferred until the source carries real timezone
  offsets (ADR-013).
- Revenue per chain — one `GROUP BY` over the exported fact table. ADR-008 exists so that
  questions like this need no code.

## Conflict Check

| ADR / Contract | Touched? | How | Verdict |
|---|---|---|---|
| ADR-003 pure metrics | **yes** | Four modules over `Dataset`, no IO | compatible |
| ADR-005 additive | **yes** | Four new output schemas | compatible — new files, nothing renamed |
| ADR-008 registry | **yes** | Four `@metric` declarations | compatible — demonstrates the one-module cost |
| ADR-009 stdlib, `Decimal` | **yes** | Wilson bound uses `Decimal.sqrt()` | compatible — **`math.sqrt` deliberately avoided**: a float in the middle of a figure the pipeline promises to reproduce byte for byte is a cross-platform risk for no benefit |
| ADR-012 reverted claims retained | **yes** | Reverted fills leave revenue, stay in claim counts | compatible |
| ADR-015 unit price | **yes** | Quantity-weighted everywhere; percentile method declared | compatible |
| ADR-016 metric set | **yes** | Implements it | compatible |
| §1.3.4 byte-identical | **yes** | All rounding explicit; ties broken on name | compatible |

## Definition of Done

- [x] PMA updated in the same change as the code
- [x] All `metric_set.feature` scenarios pass (8)
- [x] Unit tests cover each metric and the statistical helpers (27)
- [x] System-tier tests assert the independently-derived figures
- [x] `docs/METRICS.md` regenerated and drift-checked
- [x] `make check` output pasted into the session
- [x] This file marked `Status: Done`
