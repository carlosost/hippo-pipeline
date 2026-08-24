#!/usr/bin/env python3
"""Extract the edited file path from a Claude Code tool event on stdin.

The playbook's examples use `jq`; this uses python3 instead, which is guaranteed to
exist wherever the project runs. A hook that fails because a tool is missing is worse
than no hook - it trains you to ignore hook output.

Prints the path (or an empty line) and always exits 0.
"""

import json
import sys

try:
    event = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    event = {}

path = (event.get("tool_input") or {}).get("file_path") or (
    event.get("tool_response") or {}
).get("filePath") or ""

print(path)
