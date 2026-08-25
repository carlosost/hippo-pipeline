"""The CLI is the production entry point, so the tests drive it rather than its parts.

AP-11: the tested path must be the shipped path. Every scenario here runs `main()`, which
is exactly what a user runs.
"""

import json

import pytest

from hippo_pipeline import cli

from .conftest import valid_claim_record


def run_cli(dirs, tmp_path, *extra):
    pharmacy_dirs, claim_dirs, revert_dirs = dirs.args
    return cli.main(
        [
            "run",
            "--pharmacies",
            *pharmacy_dirs,
            "--claims",
            *claim_dirs,
            "--reverts",
            *revert_dirs,
            "--out",
            str(tmp_path / "out"),
            *extra,
        ]
    )


def test_a_clean_run_exits_zero_and_writes_every_output(dirs, tmp_path):
    dirs.claims([valid_claim_record(id="C1"), valid_claim_record(id="C2")])
    dirs.reverts([{"id": "R1", "claim_id": "C1", "timestamp": "2026-02-02T09:00:00"}])

    assert run_cli(dirs, tmp_path) == 0

    out = tmp_path / "out"
    for name in (
        "pharmacy_ndc_summary.csv",
        "pharmacy_ndc_summary.json",
        "_rejected.csv",
        "_excluded.csv",
        "_excluded_reverts.csv",
        "_manifest.json",
    ):
        assert (out / name).exists(), name


def test_the_manifest_accounts_for_every_record(dirs, tmp_path):
    dirs.claims(
        [valid_claim_record(id=f"OK{i}") for i in range(5)]
        + [valid_claim_record(id="BAD", quantity=...)]
        + [valid_claim_record(id="OUT", npi="9999999999")]
    )

    run_cli(dirs, tmp_path, "--max-reject-rate", "1.0")

    records = json.loads((tmp_path / "out" / "_manifest.json").read_text())["records"]
    assert records["read"] == 7
    assert records["rejected"] == 1
    assert records["excluded_at_ingest"] == 1
    assert records["balances"] is True


def test_a_reject_rate_above_the_threshold_fails_the_run_but_still_reports(dirs, tmp_path):
    dirs.claims(
        [valid_claim_record(id="OK")]
        + [valid_claim_record(id=f"BAD{i}", quantity=...) for i in range(9)]
    )

    assert run_cli(dirs, tmp_path, "--max-reject-rate", "0.01") == 1

    manifest = json.loads((tmp_path / "out" / "_manifest.json").read_text())
    assert manifest["records"]["rejected"] == 9


def test_out_of_scope_records_never_fail_the_run(dirs, tmp_path):
    dirs.claims(
        [valid_claim_record(id="OK")]
        + [valid_claim_record(id=f"OUT{i}", npi="9999999999") for i in range(99)]
    )

    assert run_cli(dirs, tmp_path, "--max-reject-rate", "0.01") == 0


def test_two_runs_over_identical_input_produce_identical_bytes(dirs, tmp_path):
    dirs.claims([valid_claim_record(id=f"C{i}", quantity=i + 1) for i in range(20)])
    dirs.reverts([{"id": "R1", "claim_id": "C3", "timestamp": "2026-02-02T09:00:00"}])

    run_cli(dirs, tmp_path / "first")
    run_cli(dirs, tmp_path / "second")

    for name in ("pharmacy_ndc_summary.csv", "pharmacy_ndc_summary.json"):
        first = (tmp_path / "first" / "out" / name).read_bytes()
        second = (tmp_path / "second" / "out" / name).read_bytes()
        assert first == second, name


def test_metrics_lists_what_each_metric_answers(capsys):
    assert cli.main(["metrics"]) == 0

    out = capsys.readouterr().out
    assert "pharmacy_ndc_summary" in out
    assert "question :" in out
    assert "avg_unit_price = " in out


def test_catalog_renders_to_stdout(capsys):
    assert cli.main(["catalog"]) == 0

    assert "# Metrics" in capsys.readouterr().out


def test_catalog_can_be_written_to_a_file(tmp_path, capsys):
    target = tmp_path / "METRICS.md"

    assert cli.main(["catalog", "--write", str(target)]) == 0
    assert "pharmacy_ndc_summary" in target.read_text()


def test_an_unknown_command_is_rejected_by_the_parser():
    with pytest.raises(SystemExit):
        cli.main(["nonsense"])
