"""Writing outputs (F-05, and the writer half of F-04).

Serialization lives here rather than beside the registry because writing a file is IO,
and IO is the gateway's job (ADR-003). The instinct to put the metric writers in
`metrics/` is exactly what the architectural lint exists to catch.

Two rules govern every function in this module:
  - `Decimal` is rendered from its own string form, never via `float`. Anything else
    undoes ADR-009 at the last possible step.
  - Nothing is sorted here. Callers decide order, because they are the ones who know what
    "deterministic" means for their data (charter 1.3.4).
"""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from hippo_pipeline.domain.models import ExcludedRevert, QuarantinedRecord

STAGING_SUFFIX = ".staging"
PREVIOUS_SUFFIX = ".previous"

QUARANTINE_COLUMNS = ("source_file", "record_index", "reasons", "raw")
EXCLUDED_REVERT_COLUMNS = (
    "source_file",
    "record_index",
    "reason",
    "revert_id",
    "claim_id",
    "timestamp",
)


def _render(value: object) -> str:
    """One cell, as text. Exactness first, readability second."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _encode(value: object) -> str:
    """JSON fallback for types json does not know. Decimal keeps its exact digits."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_text(path: str, text: str) -> None:
    """Write UTF-8 text with a trailing newline, creating parent directories.

    Takes a string rather than a `Path` because callers live outside the gateway, and
    ADR-003 reserves `pathlib` for this package. Path handling is IO handling.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_encode) + "\n",
        encoding="utf-8",
    )


def write_manifest(out_dir: str, payload: object) -> None:
    """Write the run manifest - the machine-readable account of what happened."""
    _write_json(Path(out_dir) / "_manifest.json", payload)


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" per the csv docs; lineterminator pinned so output does not depend on the
    # platform the run happened on.
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows([[_render(cell) for cell in row] for row in rows])


def write_table(
    out_dir: str,
    name: str,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    """Write one metric as `<name>.csv` and `<name>.json`.

    Takes primitives rather than a metric object so the gateway never imports `metrics/`.
    """
    root = Path(out_dir)
    _write_csv(root / f"{name}.csv", columns, [[row.get(c) for c in columns] for row in rows])
    _write_json(root / f"{name}.json", [{c: row.get(c) for c in columns} for row in rows])


def write_quarantine(out_dir: str, name: str, records: Sequence[QuarantinedRecord]) -> None:
    """Write a rejected or excluded sink (ADR-011)."""
    _write_csv(
        Path(out_dir) / f"{name}.csv",
        QUARANTINE_COLUMNS,
        [[r.source_file, r.record_index, "|".join(r.reasons), r.raw] for r in records],
    )


def write_excluded_reverts(out_dir: str, name: str, records: Sequence[ExcludedRevert]) -> None:
    """Write reverts that could not be linked to an accepted claim (ADR-012).

    A separate shape from `write_quarantine`: these records are well-formed, so their
    fields are more useful than their raw text.
    """
    _write_csv(
        Path(out_dir) / f"{name}.csv",
        EXCLUDED_REVERT_COLUMNS,
        [
            [
                e.revert.source_file,
                e.revert.record_index,
                e.reason,
                e.revert.id,
                e.revert.claim_id,
                e.revert.timestamp,
            ]
            for e in records
        ],
    )


def begin_staged_output(out_dir: str) -> str:
    """Start a run's output in a staging directory beside the target (ADR-017).

    Returns the path everything should be written to. Any leftover staging from a crashed
    previous run is discarded first - a partial directory is never reused, because reusing
    one is how a stale file survives into a fresh run.
    """
    staging = Path(out_dir + STAGING_SUFFIX)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    return str(staging)


def commit_staged_output(out_dir: str) -> None:
    """Swap the staging directory into place, replacing any previous output.

    Two renames rather than one, because a directory cannot be renamed over a non-empty
    directory. That leaves a brief window in which `out/` does not exist - and that is the
    point: the failure mode is an obviously missing directory next to `out.previous`,
    never a directory holding half of one run and half of another.

    Not called when the run raises, so a crash leaves the previous complete output intact
    and the partial work in `<out>.staging` for inspection.
    """
    target = Path(out_dir)
    staging = Path(out_dir + STAGING_SUFFIX)
    previous = Path(out_dir + PREVIOUS_SUFFIX)

    if not staging.exists():  # pragma: no cover - defensive; commit follows begin
        raise FileNotFoundError(f"nothing staged at {staging}")

    if previous.exists():
        shutil.rmtree(previous)
    if target.exists():
        target.rename(previous)
    staging.rename(target)
    if previous.exists():
        shutil.rmtree(previous)
