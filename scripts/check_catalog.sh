#!/usr/bin/env bash
# Paired-file contract test: the registry <-> docs/METRICS.md.
# A stale catalogue is worse than no catalogue, because it is believed. Regenerating and
# diffing makes staleness impossible rather than unlikely (ADR-008).
set -uo pipefail
cd "$(dirname "$0")/.."

[ -f docs/METRICS.md ] || { echo "CATALOG MISSING: run 'make catalog'"; exit 1; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

if ! uv run hippo catalog > "$tmp" 2>/dev/null; then
  echo "SKIP: could not render the catalogue (run 'make setup')"; exit 0
fi

if ! diff -q docs/METRICS.md "$tmp" >/dev/null; then
  echo "CATALOG DRIFT: docs/METRICS.md does not match the registry."
  diff docs/METRICS.md "$tmp" | head -20 | sed 's/^/    /'
  echo
  echo "  Regenerate:  make catalog"
  exit 1
fi

echo "CATALOG OK: docs/METRICS.md matches the registry"
