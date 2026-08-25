#!/usr/bin/env bash
# The provided sample dataset is the fixture every result is judged against, so it is
# read-only by rule (CLAUDE.md 4). Until now that rule had no enforcement - which is
# exactly the gap ADR-007 warns about, and it let an editor silently reformat five files.
#
# Reformatting is not harmless: it changes bytes, and a fixture whose bytes drift is a
# fixture you can no longer prove your results came from.
set -uo pipefail
cd "$(dirname "$0")/.."

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "SKIP: not a git work tree"; exit 0
fi

drift=$(git status --porcelain -- data/sample-data)
if [ -n "$drift" ]; then
  echo "FIXTURE DRIFT: data/sample-data has been modified. It is read-only by rule."
  echo "$drift" | sed 's/^/    /'
  echo
  echo "  Inspect:  git diff -- data/sample-data"
  echo "  Restore:  git checkout -- data/sample-data"
  echo "  If an editor reformatted it, disable format-on-save for this directory."
  exit 1
fi

echo "FIXTURE OK: data/sample-data matches HEAD ($(git ls-files data/sample-data | wc -l | tr -d ' ') files)"
