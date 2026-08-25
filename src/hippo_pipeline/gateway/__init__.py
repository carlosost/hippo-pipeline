"""The IO chokepoint (ADR-003).

This is the ONLY package permitted to touch the filesystem or parse raw bytes. It owns
every file handle, decode, timeout and retry, and hands everything downstream as
already-parsed domain objects.

Three properties follow, and they are the reason the boundary exists:
  - testability: `domain/` and `metrics/` need no mocks and no fixtures on disk
  - swappability: changing the compute engine (ADR-009 could be superseded) touches this
    package and nothing else
  - observability: tracing, timeouts and structured logging are injected once, here
"""

from hippo_pipeline.gateway.reader import IngestCounts, IngestResult, ingest
from hippo_pipeline.gateway.writer import (
    write_excluded_reverts,
    write_manifest,
    write_quarantine,
    write_table,
    write_text,
)

__all__ = [
    "IngestCounts",
    "IngestResult",
    "ingest",
    "write_excluded_reverts",
    "write_manifest",
    "write_quarantine",
    "write_table",
    "write_text",
]
