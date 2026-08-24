---
description: Run the pre-implementation Conflict Check (playbook 1.5)
argument-hint: [what you are about to build]
---

Before writing any code for: **$ARGUMENTS**

Produce a table with one row per existing ADR and per existing data contract in
`docs/PROJECT_MEMORY.md`:

| ADR / Contract | Does this change touch it? | How | Verdict |
|---|---|---|---|

Verdict is one of: `no interaction`, `compatible`, or `CONFLICT`.

Then cross-reference specifically:

- New or changed schema fields against every existing consumer and query pattern.
- New CLI arguments or output files against the existing output contract.
- New failure modes against the malformed-record policy.
- New aggregations against the revert-semantics rules — most correctness bugs in this
  pipeline will live here.

If any row is `CONFLICT`, stop. Propose the ADR amendment and wait for approval.
Do not write code in this response under any circumstance.
