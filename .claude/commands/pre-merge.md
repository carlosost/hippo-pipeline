---
description: Pre-merge verification checklist
---

Run and paste real output for each. Do not report a line as passing without its output.

```
[ ] make lint        — ruff clean, zero architectural violations, no doc drift
[ ] make typecheck   — mypy strict, zero errors
[ ] make test        — deterministic tier, N/N passing, 0 errors
[ ] make audit       — no advisory in a direct runtime dependency (AP-14: do not
                       auto-fix; read the advisory and decide)
```

Then confirm, each with evidence:

- [ ] `docs/PROJECT_MEMORY.md` updated in the same change as the code.
- [ ] Every new output field is additive with a default; nothing removed or retyped.
- [ ] Every new abstraction has a non-test caller (`grep -rn "<name>" src/ | grep -v tests`).
- [ ] Feature file marked `Status: Done`.
- [ ] `docs/DECISION_LOG.md` has this session's entry, ending with the next action.
- [ ] `git status --short` is clean apart from the intended change.
