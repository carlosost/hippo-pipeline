"""The architectural lint is a merge gate, so it gets tested like one.

An unverified linter fails open: it reports OK forever and nobody notices until a
violation ships. These two tests pin both directions - it flags the fixture, and it
stays quiet on the real package.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LINTER = REPO_ROOT / "scripts" / "lint_architecture.py"
BAD_PACKAGE = REPO_ROOT / "tests" / "fixtures" / "badpkg"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LINTER), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_flags_every_rule_in_the_fixture_package():
    result = _run("--root", str(BAD_PACKAGE))

    assert result.returncode == 1, result.stdout
    assert "ADR-003 - 'import json'" in result.stdout
    assert "open() outside gateway/" in result.stdout
    assert "print() outside cli.py" in result.stdout


def test_real_package_is_clean():
    result = _run()

    assert result.returncode == 0, result.stdout
    assert "ARCH OK" in result.stdout
