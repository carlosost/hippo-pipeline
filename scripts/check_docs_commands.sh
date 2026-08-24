#!/usr/bin/env bash
# Paired-file contract test: Makefile <-> README.md (playbook Pattern 4).
# Every `make <target>` the README tells a reader to run must actually exist.
# Catches the classic failure: a README whose instructions do not run.
#
# Only *code* references count - backticked `make x` or a line beginning with "make x"
# inside a fence. Prose like "make sure" must not be read as a target, or the check
# becomes noise and gets disabled.
set -uo pipefail
cd "$(dirname "$0")/.."

[ -f README.md ] && [ -f Makefile ] || { echo "SKIP: README.md or Makefile missing"; exit 0; }

status=0
targets=$(grep -oE '^[a-zA-Z_-]+:' Makefile | tr -d ':' | sort -u)

referenced=$( { grep -oE '`make [a-zA-Z_-]+' README.md | sed 's/`make //'
                grep -oE '^make [a-zA-Z_-]+'  README.md | sed 's/^make //'; } | sort -u )

for t in $referenced; do
  if ! echo "$targets" | grep -qx "$t"; then
    echo "DOC DRIFT: README.md documents 'make $t' but the Makefile has no such target"
    status=1
  fi
done

if [ "$status" -eq 0 ]; then
  echo "DOCS OK: $(echo "$referenced" | wc -w | tr -d ' ') documented make target(s), all present"
fi
exit "$status"
