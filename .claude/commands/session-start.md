---
description: Load project context before doing anything structural
---

Read, in this order, and confirm each:

1. `CLAUDE.md` — the operating contract.
2. `docs/PROJECT_MEMORY.md` — every ADR, every data contract, every Open Question.
3. `docs/DECISION_LOG.md` — the last two session entries.
4. If continuing a feature: `memory/features/feature-NN-*.md`.

Then report back, in this shape and nothing more:

- **Accepted ADRs:** the numbers and one-line titles.
- **Open Questions still unresolved:** IDs and what each blocks.
- **Last session ended at:** the exact next action recorded in the decision log.
- **Working tree:** output of `git status --short` and `git log --oneline -5`.

Do not propose work, write code, or suggest next steps until I reply.
