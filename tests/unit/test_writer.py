"""Exactness at the last step: anything that reaches float here undoes ADR-009."""

import csv
import json
from datetime import datetime, timezone
from decimal import Decimal

from hippo_pipeline.domain.models import ExcludedRevert, QuarantinedRecord, Revert
from hippo_pipeline.gateway import (
    write_excluded_reverts,
    write_manifest,
    write_quarantine,
    write_table,
)

COLUMNS = ("npi", "revenue", "avg_unit_price", "reverted", "seen_at")
ROW = {
    "npi": "0123456789",
    "revenue": Decimal("1667262.6000"),
    "avg_unit_price": None,
    "reverted": True,
    "seen_at": datetime(2026, 3, 1, 14, 40, 11, tzinfo=timezone.utc),
}


def test_decimal_keeps_its_exact_digits_in_both_formats(tmp_path):
    write_table(str(tmp_path), "m", COLUMNS, [ROW])

    csv_text = (tmp_path / "m.csv").read_text()
    json_text = (tmp_path / "m.json").read_text()

    assert "1667262.6000" in csv_text
    assert '"1667262.6000"' in json_text
    assert "1667262.6" not in json_text.replace("1667262.6000", "")


def test_the_csv_carries_the_declared_columns_in_order(tmp_path):
    write_table(str(tmp_path), "m", COLUMNS, [ROW])

    rows = list(csv.reader((tmp_path / "m.csv").read_text().splitlines()))

    assert rows[0] == list(COLUMNS)
    assert rows[1] == ["0123456789", "1667262.6000", "", "true", "2026-03-01T14:40:11+00:00"]


def test_leading_zeros_survive_the_round_trip(tmp_path):
    write_table(str(tmp_path), "m", COLUMNS, [ROW])

    assert json.loads((tmp_path / "m.json").read_text())[0]["npi"] == "0123456789"


def test_output_is_byte_identical_across_runs(tmp_path):
    write_table(str(tmp_path / "a"), "m", COLUMNS, [ROW])
    write_table(str(tmp_path / "b"), "m", COLUMNS, [ROW])

    for name in ("m.csv", "m.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_line_endings_do_not_depend_on_the_platform(tmp_path):
    write_table(str(tmp_path), "m", COLUMNS, [ROW])

    assert b"\r\n" not in (tmp_path / "m.csv").read_bytes()


def test_quarantine_records_carry_provenance_and_every_reason(tmp_path):
    record = QuarantinedRecord("claims-a.json", 7, ("missing_field:price", "not_an_object"), "{}")

    write_quarantine(str(tmp_path), "_rejected", [record])

    rows = list(csv.reader((tmp_path / "_rejected.csv").read_text().splitlines()))
    assert rows[0] == ["source_file", "record_index", "reasons", "raw"]
    assert rows[1] == ["claims-a.json", "7", "missing_field:price|not_an_object", "{}"]


def test_unlinkable_reverts_are_written_as_fields_not_raw_text(tmp_path):
    """These records are well-formed, so their fields are more useful than their text."""
    excluded = ExcludedRevert(
        revert=Revert(
            id="R1",
            claim_id="GHOST",
            timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
            source_file="reverts-a.json",
            record_index=3,
        ),
        reason="claim_not_found",
    )

    write_excluded_reverts(str(tmp_path), "_excluded_reverts", [excluded])

    rows = list(csv.reader((tmp_path / "_excluded_reverts.csv").read_text().splitlines()))
    assert rows[1] == [
        "reverts-a.json",
        "3",
        "claim_not_found",
        "R1",
        "GHOST",
        "2026-03-01T09:00:00+00:00",
    ]


def test_the_manifest_has_stable_key_order(tmp_path):
    write_manifest(str(tmp_path), {"b": 2, "a": 1})

    assert (tmp_path / "_manifest.json").read_text() == '{\n  "a": 1,\n  "b": 2\n}\n'
