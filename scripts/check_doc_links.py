#!/usr/bin/env python3
"""Check that Markdown links point at something that exists.

The retrospective's sharpest lesson was that this project built four lint checks for code
and none for prose - and then shipped an ADR promising behaviour the code never had, plus
two dead anchors in its own index. Documentation that lies is worse than documentation that
is missing, because it is believed.

Two checks:
  1. every relative file link resolves to a real path
  2. every in-page anchor link matches a real heading in that file

Links inside fenced code blocks are ignored: a code sample containing `[name](args)` is not
a link. Inherited documents are skipped - the assignment brief and the playbooks came from
outside this repository and are not ours to correct.

Usage:  python3 scripts/check_doc_links.py
Exit:   0 clean, 1 broken links found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Documents this project did not write and must not rewrite.
INHERITED = {
    "docs/ASSIGNMENT.md",
    "docs/ENGINEERING_PLAYBOOK.md",
    "docs/GENERAL_ENGINEERING_PLAYBOOK.md",
}
SKIP_DIRS = (".git", ".venv", "node_modules")

LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
FENCE = re.compile(r"^\s*```")


def strip_code_blocks(text: str) -> str:
    """Blank out fenced blocks so code samples are not read as links."""
    out, inside = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            inside = not inside
            out.append("")
            continue
        out.append("" if inside else line)
    return "\n".join(out)


def slug(heading: str) -> str:
    """GitHub's heading anchor, near enough: lowercase, punctuation dropped, spaces to -."""
    text = heading.lstrip("#").strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s+", "-", text)


def main() -> int:
    problems: list[str] = []

    for path in sorted(REPO_ROOT.rglob("*.md")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if any(part in SKIP_DIRS for part in path.parts) or relative in INHERITED:
            continue

        body = strip_code_blocks(path.read_text(encoding="utf-8"))
        anchors = {slug(line) for line in body.splitlines() if line.startswith("#")}

        for text, target in LINK.findall(body):
            if target.startswith(("http://", "https://", "mailto:")):
                continue

            file_part, _, anchor = target.partition("#")

            if file_part and not (path.parent / file_part).resolve().exists():
                problems.append(f"{relative}: missing file {target!r}  [{text[:40]}]")
                continue

            # Only in-page anchors are checkable without parsing the other file.
            if anchor and not file_part and anchor not in anchors:
                problems.append(f"{relative}: no heading for #{anchor}  [{text[:40]}]")

    if problems:
        for problem in problems:
            print(f"DOC LINK BROKEN: {problem}")
        return 1

    print("DOC LINKS OK: every relative link and in-page anchor resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
