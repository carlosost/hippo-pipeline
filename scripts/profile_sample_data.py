#!/usr/bin/env python3
"""Profile the provided sample dataset and print the facts recorded in the PMA.

This exists so that section 2.4 of docs/PROJECT_MEMORY.md is *reproducible* rather than
asserted. Any number in that section should be regenerable with:

    python3 scripts/profile_sample_data.py

It is a throwaway analysis tool, deliberately kept out of src/: it uses stdlib json/csv
directly, which the architectural lint forbids inside the package (ADR-003). Nothing in
the pipeline may import it.
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import glob
import json
import sys

CLAIM_FIELDS = frozenset({"id", "npi", "ndc", "price", "quantity", "timestamp"})
REVERT_FIELDS = frozenset({"id", "claim_id", "timestamp"})


def _load_json_records(pattern: str) -> tuple[list[dict], collections.Counter, int]:
    records: list[dict] = []
    problems: collections.Counter = collections.Counter()
    files = sorted(glob.glob(pattern))
    for path in files:
        try:
            with open(path) as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            problems["file_unparseable"] += 1
            continue
        if not isinstance(payload, list):
            problems["file_not_a_list"] += 1
            continue
        for record in payload:
            if not isinstance(record, dict):
                problems["record_not_an_object"] += 1
                continue
            records.append(record)
    return records, problems, len(files)


def main(root: str = "data/sample-data") -> int:
    print(f"=== profiling {root} ===\n")

    pharmacies: list[dict] = []
    for path in sorted(glob.glob(f"{root}/pharmacies/*.csv")):
        with open(path, newline="") as fh:
            pharmacies.extend(csv.DictReader(fh))
    npis = {row.get("npi") for row in pharmacies}
    chains = collections.Counter(row.get("chain") for row in pharmacies)
    print(f"PHARMACIES  rows={len(pharmacies)}  distinct npi={len(npis)}  chains={dict(chains)}")

    claims, claim_problems, claim_files = _load_json_records(f"{root}/claims/*.json")
    valid = [c for c in claims if not (CLAIM_FIELDS - c.keys())]
    for c in claims:
        missing = CLAIM_FIELDS - c.keys()
        if missing:
            claim_problems[f"missing:{','.join(sorted(missing))}"] += 1

    quantities = collections.Counter(type(c["quantity"]).__name__ for c in valid)
    non_positive_qty = [
        c for c in valid if isinstance(c["quantity"], (int, float)) and c["quantity"] <= 0
    ]
    claim_ids = collections.Counter(c["id"] for c in valid)
    unknown_npi = collections.Counter(c["npi"] for c in valid if c["npi"] not in npis)
    stamps = [dt.datetime.fromisoformat(c["timestamp"]) for c in valid]

    print(f"\nCLAIMS      files={claim_files}  schema-valid={len(valid)}")
    print(f"            anomalies={dict(claim_problems)}")
    print(f"            quantity python types={dict(quantities)}")
    print(
        f"            quantity <= 0: {len(non_positive_qty)} (division-by-zero risk for unit price)"
    )
    print(f"            duplicate claim ids: {sum(1 for v in claim_ids.values() if v > 1)}")
    print(
        f"            claims for an npi absent from the pharmacy file: "
        f"{sum(unknown_npi.values())} across {len(unknown_npi)} npis {dict(unknown_npi)}"
    )
    print(f"            distinct ndc={len({c['ndc'] for c in valid})}")
    print(f"            timestamp range {min(stamps)} .. {max(stamps)}  (all naive, no offset)")

    reverts, revert_problems, revert_files = _load_json_records(f"{root}/reverts/*.json")
    rvalid = [r for r in reverts if not (REVERT_FIELDS - r.keys())]
    revert_ids = collections.Counter(r["id"] for r in rvalid)
    repeated_ids = {k for k, v in revert_ids.items() if v > 1}
    by_claim = collections.Counter(r["claim_id"] for r in rvalid)
    orphans = [r for r in rvalid if r["claim_id"] not in claim_ids]
    claim_by_id = {c["id"]: c for c in valid}
    out_of_order = [
        r
        for r in rvalid
        if (c := claim_by_id.get(r["claim_id"]))
        and dt.datetime.fromisoformat(r["timestamp"]) < dt.datetime.fromisoformat(c["timestamp"])
    ]
    against_unknown_npi = [
        r for r in rvalid if (c := claim_by_id.get(r["claim_id"])) and c["npi"] not in npis
    ]

    print(
        f"\nREVERTS     files={revert_files}  schema-valid={len(rvalid)}"
        f"  anomalies={dict(revert_problems)}"
    )
    print(
        f"            repeated revert ids: {len(repeated_ids)}"
        f" (same id, DIFFERENT timestamp - not exact duplicates)"
    )
    print(
        f"            claims reverted more than once: {sum(1 for v in by_claim.values() if v > 1)}"
    )
    print(f"            reverts for an unknown claim_id: {len(orphans)}")
    print(f"            reverts timestamped BEFORE the claim they cancel: {len(out_of_order)}")
    print(f"            reverts against claims of an unknown npi: {len(against_unknown_npi)}")
    print(f"            revert rate over schema-valid claims: {len(rvalid) / len(valid):.4%}")

    for _id in sorted(repeated_ids):
        for r in rvalid:
            if r["id"] == _id:
                print(f"              repeated -> {json.dumps(r)}")

    print("\nUNIT PRICE (price / quantity) per ndc  -- note the identical bounds across every ndc")
    spread: dict[str, list[float]] = collections.defaultdict(list)
    for c in valid:
        q = c["quantity"]
        if isinstance(q, (int, float)) and q > 0:
            spread[c["ndc"]].append(c["price"] / q)
    for ndc, values in sorted(spread.items()):
        values.sort()
        print(
            f"  {ndc}  n={len(values):5d}  min={values[0]:8.2f}  "
            f"median={values[len(values) // 2]:8.2f}  max={values[-1]:8.2f}"
        )

    print("\nSchema-invalid claim records, verbatim:")
    for c in claims:
        if (CLAIM_FIELDS - c.keys()) or (
            isinstance(c.get("quantity"), (int, float)) and c["quantity"] <= 0
        ):
            print(f"  {json.dumps(c)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
