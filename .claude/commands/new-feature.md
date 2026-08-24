---
description: Open a new feature — spec only, no implementation
argument-hint: NN short-name
---

Feature: **$ARGUMENTS**

This is a **spec-only** session. Writing implementation code here is a process
violation (playbook §2.5, "split by concern, not by time").

Produce, in one response:

1. Any new ADR(s) required, in the template in `docs/PROJECT_MEMORY.md` — Context,
   Decision, Consequences, Alternatives considered, Status.
2. `memory/features/feature-$ARGUMENTS.md`: purpose, input contract, output contract,
   acceptance criteria, explicit non-goals, `Status: Specified`.
3. `tests/bdd/features/<name>.feature`: Gherkin covering the happy path, **each**
   failure path, and every boundary the ADR names. Write the failure scenarios first.
4. The PMA feature-log row for this feature.
5. The exact next action for the implementation session, with file paths.

Then stop. Await review of the spec before any code is written.
