#!/usr/bin/env python3
"""Parse every .feature file and report its scenarios.

Gherkin written before the implementation is only useful if it is real Gherkin. This
catches a malformed feature file at spec time rather than in the session that tries to
bind step definitions to it.

Uses the `gherkin-official` parser that ships with pytest-bdd, so it is a dev-time check
only - nothing here is imported by the package (ADR-009).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES = REPO_ROOT / "tests" / "bdd" / "features"


def main() -> int:
    try:
        from gherkin.parser import Parser  # type: ignore[import-untyped]
    except ImportError:
        print("SKIP: gherkin parser not installed (run `make setup`)")
        return 0

    parser = Parser()
    files = sorted(FEATURES.glob("*.feature"))
    if not files:
        print("GHERKIN OK: no feature files yet")
        return 0

    total = 0
    for path in files:
        try:
            doc = parser.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:  # report, never mask
            print(f"GHERKIN INVALID: {path.name}: {exc}")
            return 1
        children = doc.get("feature", {}).get("children", [])
        scenarios = [c["scenario"] for c in children if "scenario" in c]
        outlines = sum(1 for s in scenarios if s.get("examples"))
        total += len(scenarios)
        print(f"  {path.name:<28} {len(scenarios):>3} scenarios ({outlines} outlines)")

    print(f"GHERKIN OK: {len(files)} feature file(s), {total} scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
