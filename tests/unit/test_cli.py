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


# ------------------------------------------------------- ADR-017 behaviour --
def test_a_failed_run_writes_quarantine_but_no_metrics(dirs, tmp_path):
    """A run that failed its own quality gate must not leave numbers to be consumed."""
    dirs.claims(
        [valid_claim_record(id="OK")]
        + [valid_claim_record(id=f"BAD{i}", quantity=...) for i in range(9)]
    )

    assert run_cli(dirs, tmp_path, "--max-reject-rate", "0.01") == 1

    out = tmp_path / "out"
    assert (out / "_rejected.csv").exists()
    assert (out / "_manifest.json").exists()
    assert not (out / "pharmacy_ndc_summary.csv").exists()

    manifest = json.loads((out / "_manifest.json").read_text())
    assert manifest["status"] == "failed_reject_threshold"
    assert manifest["metrics"] == []
    assert "quality gate" in manifest["metrics_skipped_reason"]


def test_a_successful_run_records_ok_and_no_skip_reason(dirs, tmp_path):
    dirs.claims([valid_claim_record()])

    run_cli(dirs, tmp_path)

    manifest = json.loads((tmp_path / "out" / "_manifest.json").read_text())
    assert manifest["status"] == "ok"
    assert manifest["metrics_skipped_reason"] is None


def test_the_manifest_identifies_the_exact_inputs_that_were_read(dirs, tmp_path):
    dirs.claims([valid_claim_record()])

    run_cli(dirs, tmp_path)

    manifest = json.loads((tmp_path / "out" / "_manifest.json").read_text())
    assert len(manifest["inputs_digest"]) == 64
    assert len(manifest["input_files"]) == 2
    assert all(len(f["sha256"]) == 64 for f in manifest["input_files"])


def test_identical_inputs_give_the_same_digest_and_identical_outputs(dirs, tmp_path):
    """The invariant the digest exists to support (ADR-017)."""
    dirs.claims([valid_claim_record(id=f"C{i}", quantity=i + 1) for i in range(10)])

    run_cli(dirs, tmp_path / "a")
    run_cli(dirs, tmp_path / "b")

    first = json.loads((tmp_path / "a" / "out" / "_manifest.json").read_text())
    second = json.loads((tmp_path / "b" / "out" / "_manifest.json").read_text())
    assert first["inputs_digest"] == second["inputs_digest"]

    for name in ("pharmacy_ndc_summary.csv", "pharmacy_performance.csv"):
        assert (tmp_path / "a" / "out" / name).read_bytes() == (
            tmp_path / "b" / "out" / name
        ).read_bytes()


def test_a_run_that_raises_leaves_the_previous_output_intact(dirs, tmp_path, monkeypatch):
    """No commit, no swap: a crash cannot produce a half-updated output directory."""
    dirs.claims([valid_claim_record()])
    run_cli(dirs, tmp_path)
    before = sorted(p.name for p in (tmp_path / "out").iterdir())

    def explode(_dataset):
        raise RuntimeError("metric blew up")

    monkeypatch.setattr(cli, "run_all", explode)
    with pytest.raises(RuntimeError, match="metric blew up"):
        run_cli(dirs, tmp_path)

    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == before
