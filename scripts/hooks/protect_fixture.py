#!/usr/bin/env python3
"""PreToolUse gate: refuse writes to the provided sample dataset.

The other five hooks are PostToolUse - they report after the fact. This one is the
exception the playbook calls out (5.4): when a write must be *prevented* rather than
noticed, it has to fire before the tool runs.

The fixture is what every result is judged against. A well-meaning reformat changes its
bytes, and a fixture whose bytes drift is one you can no longer prove your results came
from.

Exit 2 blocks the tool call and returns stderr to the assistant. Exit 0 allows it.
"""

import json
import sys

PROTECTED = "data/sample-data"

try:
    event = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    raise SystemExit(0)  # never block on an event we could not parse

path = (event.get("tool_input") or {}).get("file_path") or ""

if PROTECTED in path.replace("\\", "/"):
    sys.stderr.write(
        f"BLOCKED: {path}\n"
        f"data/sample-data is the provided fixture and is read-only (CLAUDE.md 4).\n"
        f"Derive a new file elsewhere instead of editing it. If the fixture genuinely "
        f"must change, that is an ADR, not an edit.\n"
    )
    raise SystemExit(2)
