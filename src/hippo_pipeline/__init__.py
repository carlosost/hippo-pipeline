"""Pharmacy claims & reverts pipeline.

Structure is fixed by ADR-003 (dependency chokepoint):

    gateway/    the ONLY place allowed to touch the filesystem or parse raw bytes
    domain/     pure data types and transformation rules - no IO, no logging
    metrics/    aggregations over domain types - pure functions
    cli.py      the single production entry point (AP-11: tested path == shipped path)

Modules outside gateway/ must not import json, csv, pathlib, glob or call open().
scripts/lint_architecture.sh enforces this on every save.
"""

__version__ = "0.1.0"
