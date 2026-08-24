"""Single production entry point.

Deliberately a stub. The pipeline is not implemented: the compute engine (OQ-01),
the malformed-record policy (OQ-02) and the revert semantics (OQ-03) are still
open questions in docs/PROJECT_MEMORY.md. Implementing before those ADRs exist is
the failure mode the playbook exists to prevent (GENERAL_ENGINEERING_PLAYBOOK.md 1.1).

Exit code 2 = "specified but not implemented", distinct from 1 (runtime failure).
"""

from __future__ import annotations

import sys

NOT_IMPLEMENTED_MESSAGE = (
    "hippo-pipeline: scaffolding only - no pipeline implemented yet.\n"
    "Resolve OQ-01 (compute engine), OQ-02 (malformed records) and OQ-03 "
    "(revert semantics) in docs/PROJECT_MEMORY.md first."
)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code; never raises for control flow."""
    _ = argv if argv is not None else sys.argv[1:]
    sys.stderr.write(NOT_IMPLEMENTED_MESSAGE + "\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
