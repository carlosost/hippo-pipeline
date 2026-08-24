#!/usr/bin/env python3
"""Living-Memory rule (GENERAL_ENGINEERING_PLAYBOOK.md 2.3), made mechanical.

If the working tree has changes under src/ but docs/PROJECT_MEMORY.md is untouched,
print a reminder. A PMA two sessions behind is unreliable as context and defeats its
own purpose - and the moment it is unreliable, nobody reads it.

Advisory only: always exits 0. This is a nudge, not a gate; gating every edit on a
doc update would just teach you to route around the hook.
"""

import subprocess
import sys

sys.stdin.read()  # drain the event; this hook is not path-specific

try:
    changed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.split()
except (OSError, subprocess.SubprocessError):
    raise SystemExit(0)

src_touched = [f for f in changed if f.startswith("src/")]
pma_touched = "docs/PROJECT_MEMORY.md" in changed

if src_touched and not pma_touched:
    print(
        "PMA REMINDER: "
        f"{len(src_touched)} file(s) under src/ changed but docs/PROJECT_MEMORY.md "
        "has not. If this introduced or changed a contract, record the ADR now - "
        "not next session."
    )
