"""The single production entry point.

The orchestration lives here rather than in a separate `pipeline` module on purpose:
AP-11 says the tested path must be the shipped path, and the surest way to guarantee that
is to give the sequence exactly one home. Tests drive `main()`, which is what a user runs.

This is also the only module permitted to `print()` (playbook 4.1). Everything a machine
should read goes to `out/_manifest.json`; what goes to stdout is for a human watching a
run.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from hippo_pipeline import __version__
from hippo_pipeline.domain.models import Dataset
from hippo_pipeline.domain.resolution import resolve_reverts
from hippo_pipeline.gateway import (
    begin_staged_output,
    commit_staged_output,
    ingest,
    write_excluded_reverts,
    write_manifest,
    write_quarantine,
    write_table,
    write_text,
)
from hippo_pipeline.metrics import (
    MetricOutput,
    discover,
    registered,
    render_catalog,
    run_all,
)

DEFAULT_MAX_REJECT_RATE = 0.01

EXIT_OK = 0
EXIT_TOO_MANY_REJECTS = 1
EXIT_USAGE = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hippo",
        description="Process pharmacy claims and reverts into auditable metrics.",
    )
    parser.add_argument("--version", action="version", version=f"hippo-pipeline {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the pipeline and write metrics to --out")
    run.add_argument("--pharmacies", nargs="+", required=True, metavar="DIR")
    run.add_argument("--claims", nargs="+", required=True, metavar="DIR")
    run.add_argument("--reverts", nargs="+", required=True, metavar="DIR")
    run.add_argument("--out", default="out", metavar="DIR")
    run.add_argument(
        "--max-reject-rate",
        type=float,
        default=DEFAULT_MAX_REJECT_RATE,
        help=(
            "fail the run when rejected/read exceeds this. Exclusions never count "
            "(ADR-011). Provisional until measured against real traffic"
        ),
    )

    sub.add_parser("metrics", help="list the registered metrics and what they answer")

    catalog = sub.add_parser("catalog", help="render the metric catalogue")
    catalog.add_argument("--write", metavar="PATH", default=None)

    return parser


def run_pipeline(
    pharmacy_dirs: Sequence[str],
    claim_dirs: Sequence[str],
    revert_dirs: Sequence[str],
    out_dir: str,
    max_reject_rate: float,
) -> int:
    """Read, resolve, aggregate, write. The whole pipeline, in one readable sequence.

    Two ordering decisions from ADR-017 are visible here and are not accidental:

      - the reject threshold is checked **before** metrics are computed, so a run that
        fails its own quality gate cannot leave numbers behind for someone to consume
      - everything is written to a staging directory and swapped in at the end, so `out/`
        is either the previous complete run or this one, never a mixture
    """
    discover()

    ingested = ingest(pharmacy_dirs, claim_dirs, revert_dirs)
    resolution = resolve_reverts(ingested.claims, ingested.reverts, ingested.quarantined_claim_ids)
    counts = ingested.counts
    over_threshold = counts.reject_rate > max_reject_rate

    staging = begin_staged_output(out_dir)

    # Quarantine is written on both paths: it is the one thing that explains a failure.
    write_quarantine(staging, "_rejected", ingested.rejected)
    write_quarantine(staging, "_excluded", ingested.excluded)
    write_excluded_reverts(staging, "_excluded_reverts", resolution.excluded)

    outputs: tuple[MetricOutput, ...] = ()
    if not over_threshold:
        dataset = Dataset(
            claims=resolution.claims,
            reverts=ingested.reverts,
            pharmacies=ingested.pharmacies,
        )
        outputs = run_all(dataset)
        for output in outputs:
            write_table(staging, output.name, output.columns, output.rows)

    manifest = {
        "schema_version": 2,
        "status": "failed_reject_threshold" if over_threshold else "ok",
        "time_basis": "UTC (assumed; source carries no offset)",
        "recompute_model": "full (ADR-017): every run rebuilds every output from every "
        "file it is given; no state is carried between runs",
        "inputs": {
            "pharmacies": list(pharmacy_dirs),
            "claims": list(claim_dirs),
            "reverts": list(revert_dirs),
        },
        # Two runs with the same inputs_digest saw byte-identical inputs and must produce
        # byte-identical outputs. This is what turns "our numbers disagree" into a diff.
        "inputs_digest": ingested.inputs_digest,
        "input_files": [
            {"path": f.path, "sha256": f.sha256, "bytes": f.bytes} for f in ingested.inputs
        ],
        # Two stages exclude records, so the manifest reports them separately. Lumping
        # them together would give a number that no stated identity accounts for, and an
        # unexplainable total is the thing this pipeline exists to avoid.
        "records": {
            "read": counts.read,
            "accepted_at_ingest": counts.accepted,
            "rejected": counts.rejected,
            "excluded_at_ingest": counts.excluded,
            "excluded_at_resolution": len(resolution.excluded),
            "usable": counts.accepted - len(resolution.excluded),
            "files_unreadable": counts.files_unreadable,
            "identity": "read == accepted_at_ingest + rejected + excluded_at_ingest",
            "balances": counts.balances(),
        },
        "claims": {"read": counts.claims_read, "accepted": counts.claims_accepted},
        "reverts": {
            "read": counts.reverts_read,
            "accepted": counts.reverts_accepted,
            "linked": sum(1 for c in resolution.claims if c.reverted),
        },
        "pharmacies": len(ingested.pharmacies),
        "reject_rate": round(counts.reject_rate, 8),
        "max_reject_rate": max_reject_rate,
        "by_reason": {**counts.by_reason, **resolution.counts},
        "by_file": counts.by_file,
        "metrics": [o.name for o in outputs],
        "metrics_skipped_reason": (
            "reject rate exceeded --max-reject-rate; metrics are not computed for a run "
            "that failed its own quality gate (ADR-017)"
        )
        if over_threshold
        else None,
    }
    write_manifest(staging, manifest)
    commit_staged_output(out_dir)

    print(
        f"read {counts.read}  accepted {counts.accepted}  rejected {counts.rejected}  "
        f"excluded {counts.excluded} (+{len(resolution.excluded)} unlinkable reverts)"
    )
    for code, total in sorted({**counts.by_reason, **resolution.counts}.items()):
        print(f"  {code}: {total}")

    if over_threshold:
        print(
            f"FAILED: reject rate {counts.reject_rate:.4%} exceeds "
            f"{max_reject_rate:.4%}. No metrics were written. "
            f"Inspect {out_dir}/_rejected.csv",
            file=sys.stderr,
        )
        return EXIT_TOO_MANY_REJECTS

    print(f"wrote {len(outputs)} metric(s) to {out_dir}/")
    return EXIT_OK


def _list_metrics() -> int:
    discover()
    specs = registered()
    if not specs:
        print("no metrics registered")
        return EXIT_OK
    for spec in specs:
        print(f"{spec.name}")
        print(f"  question : {spec.question}")
        print(f"  grain    : {', '.join(spec.grain)}")
        print(f"  columns  : {', '.join(spec.columns)}")
        for column, formula in spec.measures.items():
            print(f"  {column} = {formula}")
        print()
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code; never raises for control flow."""
    args = _parser().parse_args(list(argv) if argv is not None else None)

    if args.command == "run":
        return run_pipeline(
            args.pharmacies, args.claims, args.reverts, args.out, args.max_reject_rate
        )
    if args.command == "metrics":
        return _list_metrics()
    if args.command == "catalog":
        discover()
        text = render_catalog()
        if args.write:
            write_text(args.write, text)
            print(f"wrote {args.write}")
        else:
            print(text, end="")
        return EXIT_OK
    return EXIT_USAGE  # pragma: no cover - argparse rejects unknown commands first


if __name__ == "__main__":
    raise SystemExit(main())
