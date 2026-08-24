#!/usr/bin/env bash
# Syntax-validates a YAML or JSON file on save. Fast, always useful, catches the
# cryptic-runtime-failure class early.
set -uo pipefail
f="${1:-}"
[ -n "$f" ] && [ -f "$f" ] || exit 0

case "$f" in
  *.yml|*.yaml)
    python3 -c "import sys,yaml; yaml.safe_load(open(sys.argv[1]))" "$f" \
      && echo "YAML OK: $f" || { echo "YAML INVALID: $f"; exit 1; } ;;
  *.json)
    python3 -c "import sys,json; json.load(open(sys.argv[1]))" "$f" \
      && echo "JSON OK: $f" || { echo "JSON INVALID: $f"; exit 1; } ;;
esac
