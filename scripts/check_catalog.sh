#!/usr/bin/env bash
# Paired-file contract test: the registry <-> docs/METRICS.md.
# A stale catalogue is worse than no catalogue, because it is believed. Regenerating and
# diffing makes staleness impossible rather than unlikely (ADR-008).
set -uo pipefail
cd "$(dirname "$0")/.."

catalog="${1:-docs/METRICS.md}"

[ -f "$catalog" ] || { echo "CATALOG MISSING: run 'make catalog'"; exit 1; }

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

if ! uv run hippo catalog > "$tmp" 2>/dev/null; then
  echo "SKIP: could not render the catalogue (run 'make setup')"; exit 0
fi

if ! diff -q "$catalog" "$tmp" >/dev/null; then
  echo "CATALOG DRIFT: $catalog does not match the registry."
  diff "$catalog" "$tmp" | head -20 | sed 's/^/    /'
  echo
  echo "  Regenerate:  make catalog"
  exit 1
fi

echo "CATALOG OK: $catalog matches the registry"
