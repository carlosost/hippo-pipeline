#!/usr/bin/env python3
"""Architectural constraint lint. Enforces ADR-003 and the logging rule in 4.1.

Rules
-----
1. Only ``src/hippo_pipeline/gateway/`` may import raw IO / parsing modules or call
   ``open()``. Everything else receives already-parsed domain objects, which is what
   lets the domain and metrics layers be unit-tested with zero mocks.
2. Only ``cli.py`` may call ``print()``. Everything else emits structured log records.
3. **No module may import anything outside the standard library** (ADR-009). The
   pipeline has zero runtime dependencies. A stray ``import polars`` now fails
   ``make lint`` and CI rather than quietly becoming a dependency nobody decided on.

Implemented over the AST rather than grep on purpose: a regex over Python source
matches its own documentation, and a lint that cries wolf gets disabled within a week.

Usage:  python3 scripts/lint_architecture.py [--root DIR] [file ...]
        no args = whole package tree. --root points the same rules at another
        package directory, which is how the rules are unit-tested (tests/unit/
        test_lint_architecture.py) - a lint nobody tests is a lint that silently
        passes everything.
Exit:   0 clean, 1 violations found, 2 file could not be parsed.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "src" / "hippo_pipeline"
GATEWAY_ROOT = PACKAGE_ROOT / "gateway"
CLI_MODULE = PACKAGE_ROOT / "cli.py"

FORBIDDEN_IMPORTS = frozenset(
    {"json", "csv", "glob", "pathlib", "shutil", "tarfile", "gzip", "open"}
)

# ADR-009: zero runtime dependencies. sys.stdlib_module_names is exact for the running
# interpreter (3.10+), which beats maintaining a hand-written allowlist that rots.
FIRST_PARTY = frozenset({"hippo_pipeline"})


def _is_third_party(root: str) -> bool:
    return (
        bool(root)
        and root not in FIRST_PARTY
        and root not in sys.stdlib_module_names
        and not root.startswith("_")
    )


def _violations(path: Path, tree: ast.AST) -> list[str]:
    in_gateway = GATEWAY_ROOT in path.parents
    is_cli = path == CLI_MODULE
    found: list[str] = []

    for node in ast.walk(tree):
        if not in_gateway:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in FORBIDDEN_IMPORTS:
                        found.append(
                            f"{path}:{node.lineno}: ADR-003 - 'import {alias.name}' "
                            f"outside gateway/; parse in the gateway, pass domain objects"
                        )
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    found.append(
                        f"{path}:{node.lineno}: ADR-003 - 'from {node.module} import ...' "
                        f"outside gateway/; parse in the gateway, pass domain objects"
                    )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
            ):
                found.append(
                    f"{path}:{node.lineno}: ADR-003 - open() outside gateway/; "
                    f"the gateway owns every filesystem handle"
                )
        # Rule 3 applies everywhere, gateway/ included - ADR-009 admits no exemption.
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_third_party(alias.name.split(".")[0]):
                    found.append(
                        f"{path}:{node.lineno}: ADR-009 - 'import {alias.name}' is not in "
                        f"the standard library; this pipeline has zero runtime dependencies"
                    )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and _is_third_party((node.module or "").split(".")[0])
        ):
            found.append(
                f"{path}:{node.lineno}: ADR-009 - 'from {node.module} import ...' is not "
                f"in the standard library; this pipeline has zero runtime dependencies"
            )

        if (
            not is_cli
            and isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "print"
        ):
            found.append(
                f"{path}:{node.lineno}: 4.1 - print() outside cli.py; "
                f"emit a structured log record instead"
            )
    return found


def main(argv: list[str]) -> int:
    global PACKAGE_ROOT, GATEWAY_ROOT, CLI_MODULE

    args = list(argv)
    if args and args[0] == "--root":
        if len(args) < 2:
            print("ARCH ERROR: --root requires a directory")
            return 2
        PACKAGE_ROOT = Path(args[1]).resolve()
        GATEWAY_ROOT = PACKAGE_ROOT / "gateway"
        CLI_MODULE = PACKAGE_ROOT / "cli.py"
        args = args[2:]

    candidates = [Path(a).resolve() for a in args] if args else sorted(PACKAGE_ROOT.rglob("*.py"))

    targets = [
        p for p in candidates if p.suffix == ".py" and PACKAGE_ROOT in p.parents and p.is_file()
    ]
    if not targets:
        print("ARCH OK: no in-scope files to check")
        return 0

    all_found: list[str] = []
    for path in targets:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            print(f"ARCH ERROR: cannot parse {path}: {exc}")
            return 2
        all_found.extend(_violations(path, tree))

    if all_found:
        for line in all_found:
            print(f"ARCH VIOLATION: {line}")
        return 1

    print(f"ARCH OK: {len(targets)} file(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
