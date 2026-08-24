#!/usr/bin/env bash
# Thin wrapper so hooks, the Makefile and CI all call one implementation.
# The real rules live in lint_architecture.py (AST-based - see the note in that file).
exec python3 "$(dirname "$0")/lint_architecture.py" "$@"
