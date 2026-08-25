"""Render the metric catalogue from the registry (ADR-008).

Generated, never hand-written: a stale catalogue is worse than no catalogue, because it is
believed. `make lint` regenerates this and fails on any difference, which makes staleness
impossible rather than unlikely.

Returns a string. Writing it is IO and therefore the gateway's job (ADR-003).
"""

from __future__ import annotations

from hippo_pipeline.metrics.registry import registered

HEADER = """# Metrics

**Generated from the registry - do not edit by hand.**
Regenerate with `make catalog`; `make lint` fails if this file has drifted.

Every metric below is one module in `src/hippo_pipeline/metrics/`. Adding one costs a
module and a test: no ingestion code, no configuration, no registration list to update.

Each run also writes the rows behind these numbers to `out/`, so a question no metric
answers can be asked of the exported fact table directly.

**Time basis:** all timestamps are interpreted as UTC. The source carries no offset, so
this is a declared assumption, not a measurement (ADR-013).
"""


def render_catalog() -> str:
    """The catalogue as Markdown."""
    specs = registered()
    if not specs:
        return HEADER + "\n_No metrics are registered._\n"

    parts = [HEADER, "\n| Metric | Grain | Question |", "|---|---|---|"]
    parts.extend(
        f"| [`{s.name}`](#{s.name}) | `{', '.join(s.grain)}` | {s.question} |" for s in specs
    )

    for spec in specs:
        parts.append(f"\n---\n\n## {spec.name}\n")
        parts.append(f"**Question.** {spec.question}\n")
        parts.append(f"**Grain.** `{', '.join(spec.grain)}`\n")
        parts.append(f"**Output.** `out/{spec.name}.csv` and `out/{spec.name}.json`\n")
        parts.append("**Columns.**\n")
        parts.append("| Column | Definition |")
        parts.append("|---|---|")
        for column in spec.columns:
            definition = spec.measures.get(column, "")
            if not definition:
                definition = "part of the grain" if column in spec.grain else "—"
            parts.append(f"| `{column}` | {definition} |")
        parts.append(f"\n_Defined in `{spec.module.replace('.', '/')}.py`._")

    return "\n".join(parts) + "\n"
