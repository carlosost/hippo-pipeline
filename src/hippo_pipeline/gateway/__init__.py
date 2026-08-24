"""The IO chokepoint (ADR-003).

This is the ONLY package permitted to touch the filesystem or parse raw bytes. It owns
every file handle, decode, timeout and retry, and hands everything downstream as
already-parsed domain objects.

Three properties follow, and they are the reason the boundary exists:
  - testability: `domain/` and `metrics/` need no mocks and no fixtures on disk
  - swappability: changing the compute engine (OQ-01) touches this package and the
    factories, and nothing else
  - observability: tracing, timeouts and structured logging are injected once, here,
    never re-implemented at a call site

Empty until OQ-01 (compute engine) and OQ-02 (malformed-record policy) are resolved by
ADR. Implementing before then means implementing twice.
"""
