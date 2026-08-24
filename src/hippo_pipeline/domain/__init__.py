"""Pure types and transformation rules (ADR-003).

No IO, no logging, no clock, no randomness. Everything here is a function of its
arguments, which is what lets the deterministic test tier stay fast enough to run on
every file save.

Empty until OQ-03 (what a revert invalidates), OQ-04 (revert identity), OQ-10 (timestamp
semantics) and OQ-11 (reference-data currency) are resolved by ADR.
"""
