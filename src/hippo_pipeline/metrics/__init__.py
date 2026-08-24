"""Aggregations over domain types (ADR-003).

Pure functions, individually addressable, each one answering a stated business question.
This is the layer analysts and AI agents extend, so a new metric must cost one
declaration and one test - never a change to ingestion.

Empty until OQ-06 (which metrics), OQ-07 (the extension surface) and OQ-08 (how unit
price is defined) are resolved by ADR.
"""
