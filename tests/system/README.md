# System-behavior tier

Real files, real IO, run against `data/sample-data/`. Measures throughput, memory
ceiling and end-to-end correctness. Gated against a recorded baseline
(">= baseline" / "within 20%"), never with `==` on timing.

Marked `@pytest.mark.system`. Runs in its own CI job. **Not** a merge gate (ADR-004).
