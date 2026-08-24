"""Deterministic tier. Mirrors the naming convention the auto-test hook relies on:
src/hippo_pipeline/cli.py -> tests/unit/test_cli.py
"""

from hippo_pipeline import cli


def test_main_reports_not_implemented_and_exits_2(capsys):
    """The stub must fail loudly and distinguishably, never exit 0."""
    exit_code = cli.main([])

    assert exit_code == 2
    assert "no pipeline implemented yet" in capsys.readouterr().err


def test_main_does_not_raise_on_arbitrary_argv():
    """Control flow is via return code, not exceptions (typed error contract, 1.4)."""
    assert cli.main(["--anything", "data/sample-data/claims"]) == 2
