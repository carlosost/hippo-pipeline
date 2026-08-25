"""System-behavior tier (ADR-004): real files, the provided fixture, end to end.

Not a merge gate. These assertions pin the numbers in PMA section 2.4 to the code that
produces them, so a change that silently moves a headline figure cannot pass unnoticed.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = REPO_ROOT / "data" / "sample-data"

pytestmark = pytest.mark.system


@pytest.fixture(scope="module")
def run_output(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hippo_pipeline.cli",
            "run",
            "--pharmacies",
            str(SAMPLE / "pharmacies"),
            "--claims",
            str(SAMPLE / "claims"),
            "--reverts",
            str(SAMPLE / "reverts"),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    return out


@pytest.fixture(scope="module")
def manifest(run_output):
    return json.loads((run_output / "_manifest.json").read_text())


def test_the_ingest_counts_match_the_recorded_profile(manifest):
    """PMA 2.4, reproducible with scripts/profile_sample_data.py."""
    records = manifest["records"]

    assert manifest["claims"]["read"] == 27076
    assert manifest["claims"]["accepted"] == 22988
    assert records["rejected"] == 3
    assert records["excluded_at_ingest"] == 4085
    assert records["files_unreadable"] == 0
    assert records["balances"] is True


def test_the_three_known_defects_are_the_only_rejections(manifest):
    assert manifest["by_reason"]["missing_field:quantity"] == 2
    assert manifest["by_reason"]["non_positive:quantity"] == 1


def test_the_out_of_scope_claims_are_excluded_not_rejected(manifest):
    """15.1% of claims, across exactly three NPIs. Defects would be a different story."""
    assert manifest["by_reason"]["npi_not_in_pharmacy_dataset"] == 4085
    assert manifest["reject_rate"] < 0.0002


def test_the_revert_anomalies_match_the_profile(manifest):
    """Three repeated revert ids, two impossible orderings, no orphans (ADR-012)."""
    assert manifest["by_reason"]["duplicate_revert_for_claim"] == 3
    assert manifest["by_reason"]["revert_precedes_claim"] == 2
    assert manifest["by_reason"]["claim_not_accepted"] == 45
    assert "claim_not_found" not in manifest["by_reason"]


def test_every_accepted_revert_is_either_linked_or_accounted_for(manifest):
    reverts = manifest["reverts"]

    assert reverts["read"] == reverts["accepted"] == 308
    assert reverts["linked"] + manifest["records"]["excluded_at_resolution"] + 3 == 308


def test_the_metric_output_is_readable_and_exact(run_output):
    rows = json.loads((run_output / "pharmacy_ndc_summary.json").read_text())

    assert len(rows) == 170  # 17 pharmacies x 10 drugs, per PMA 2.4
    assert all(isinstance(r["npi"], str) for r in rows)
    assert any(r["npi"].startswith("0") for r in rows)
    assert all(isinstance(r["revenue"], str) for r in rows)  # Decimal, not float


def test_reruns_are_byte_identical(tmp_path):
    outputs = []
    for name in ("a", "b"):
        target = tmp_path / name
        subprocess.run(
            [
                sys.executable,
                "-m",
                "hippo_pipeline.cli",
                "run",
                "--pharmacies",
                str(SAMPLE / "pharmacies"),
                "--claims",
                str(SAMPLE / "claims"),
                "--reverts",
                str(SAMPLE / "reverts"),
                "--out",
                str(target),
            ],
            check=True,
            capture_output=True,
            cwd=REPO_ROOT,
        )
        outputs.append(target)

    for name in (
        "pharmacy_ndc_summary.csv",
        "pharmacy_ndc_summary.json",
        "_rejected.csv",
        "_excluded.csv",
        "_excluded_reverts.csv",
    ):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes(), name


# ---------------------------------------------------------------- the metric set --
# Every figure below was derived independently of the implementation, by re-reading the
# raw files and re-applying the rules from ADR-011/012 in a throwaway script. Asserting
# against numbers the code produced would test that the code agrees with itself.


def test_pharmacy_performance_matches_the_independent_derivation(run_output):
    rows = json.loads((run_output / "pharmacy_performance.json").read_text())

    assert len(rows) == 17
    row = next(r for r in rows if r["npi"] == "4444444444")
    assert (row["claims"], row["reverted"]) == (1236, 20)
    assert row["reversal_rate"] == "0.016181"
    assert row["reversal_rate_lower_95"] == "0.010499"


def test_no_pharmacy_is_a_statistical_outlier_in_this_sample(run_output):
    """The reason the bound is exported at all (ADR-016). If this ever fails, the data
    changed and somebody should look - not the code."""
    rows = json.loads((run_output / "pharmacy_performance.json").read_text())

    rates = sorted(float(r["reversal_rate"]) for r in rows)
    bounds = sorted(float(r["reversal_rate_lower_95"]) for r in rows)

    assert rates[0] == pytest.approx(0.008451, abs=1e-6)
    assert rates[-1] == pytest.approx(0.016181, abs=1e-6)
    # The highest lower bound sits below the lowest raw rate's neighbours: the intervals
    # overlap, so no pharmacy is separated from the pack.
    assert bounds[-1] < rates[-1]


def test_price_dispersion_shows_min_and_max_are_degenerate_here(run_output):
    rows = json.loads((run_output / "drug_price_dispersion.json").read_text())

    assert len(rows) == 10
    assert {r["max_over_min"] for r in rows} == {"2948.6667"}
    # The medians are what carry signal - three bands across ten drugs.
    assert len({r["median_unit_price"] for r in rows}) == 3


def test_chain_price_ranking_matches_the_independent_derivation(run_output):
    rows = json.loads((run_output / "chain_ndc_price_rank.json").read_text())

    assert len(rows) == 30  # 10 drugs x 3 chains
    drug = sorted((r for r in rows if r["ndc"] == "00054027225"), key=lambda r: r["price_rank"])
    assert [(r["chain"], r["avg_unit_price"], r["fills"]) for r in drug] == [
        ("doctor", "368.9120", 748),
        ("health", "517.7575", 594),
        ("saint", "647.4117", 1023),
    ]


def test_every_metric_writes_both_formats(run_output):
    expected = {
        "chain_ndc_price_rank",
        "drug_price_dispersion",
        "pharmacy_ndc_summary",
        "pharmacy_performance",
    }
    for name in expected:
        assert (run_output / f"{name}.csv").exists()
        assert (run_output / f"{name}.json").exists()

    manifest = json.loads((run_output / "_manifest.json").read_text())
    assert set(manifest["metrics"]) == expected
