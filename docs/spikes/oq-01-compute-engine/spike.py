#!/usr/bin/env python3
"""Spike for OQ-01 (compute engine). Evidence, not a decision.

Runs four experiments against the real sample dataset plus one synthetic file
containing the breakage a real event stream produces. Every claim in
`README.md` in this directory is produced by this script.

The candidate libraries are NOT project dependencies and must never become
project dependencies without an ADR. Run it with uv's ephemeral environment:

    uv run --with duckdb --with polars --with pandas \
        python docs/spikes/oq-01-compute-engine/spike.py

Exit code is 0 whatever the engines do - a spike reports, it does not gate.
"""

from __future__ import annotations

import json
import resource
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from csv import DictReader
from glob import glob
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE = REPO_ROOT / "data" / "sample-data"

# The breakage a schema check must survive. Every element here is a class of
# defect that appears in real event streams, not an invented edge case.
NASTY = [
    {"id": "ok-1", "npi": "0123456789", "ndc": "00054027225",
     "quantity": 10, "price": 21.0, "timestamp": "2026-03-01T10:00:00"},
    {"id": "bad-str-qty", "npi": "0123456789", "ndc": "00054027225",
     "quantity": "ten", "price": 21.0, "timestamp": "2026-03-01T10:00:00"},
    {"id": "bad-null-price", "npi": "0123456789", "ndc": "00054027225",
     "quantity": 10, "price": None, "timestamp": "2026-03-01T10:00:00"},
    {"id": "bad-ts", "npi": "0123456789", "ndc": "00054027225",
     "quantity": 10, "price": 21.0, "timestamp": "not-a-date"},
    {"id": "extra-field", "npi": "0123456789", "ndc": "00054027225",
     "quantity": 10, "price": 21.0, "timestamp": "2026-03-01T10:00:00",
     "pharmacist": "jane"},
    "i am not an object",
]

CLAIM_FIELDS = frozenset({"id", "npi", "ndc", "price", "quantity", "timestamp"})


def banner(text: str) -> None:
    print("\n" + "=" * 72)
    print(text)
    print("=" * 72)


def build_workspace(tmp: Path) -> Path:
    """Copy the sample data and add the nasty file. Originals are never touched."""
    work = tmp / "sample-data"
    shutil.copytree(SAMPLE, work)
    (work / "claims" / "output-nasty.json").write_text(json.dumps(NASTY, indent=1))
    return work


# --------------------------------------------------------------- experiment 1
def stdlib_baseline() -> None:
    """The floor every other option has to beat. Streaming, zero dependencies."""
    banner("1. STDLIB BASELINE - full pass over the real dataset")

    start = time.perf_counter()

    npis = set()
    for path in glob(f"{SAMPLE}/pharmacies/*.csv"):
        with open(path, newline="") as fh:
            npis.update(row["npi"] for row in DictReader(fh))

    reverted = set()
    for path in glob(f"{SAMPLE}/reverts/*.json"):
        with open(path) as fh:
            reverted.update(r["claim_id"] for r in json.load(fh))

    agg: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0, 0, 0.0, 0.0])
    read = rejected = 0
    for path in sorted(glob(f"{SAMPLE}/claims/*.json")):
        with open(path) as fh:
            for record in json.load(fh):
                read += 1
                if CLAIM_FIELDS - record.keys():
                    rejected += 1
                    continue
                qty = record["quantity"]
                if not isinstance(qty, (int, float)) or qty <= 0:
                    rejected += 1
                    continue
                if record["npi"] not in npis:
                    continue
                bucket = agg[(record["npi"], record["ndc"])]
                if record["id"] in reverted:
                    bucket[1] += 1
                else:
                    bucket[0] += 1
                    bucket[2] += record["price"]
                    bucket[3] += qty

    elapsed = time.perf_counter() - start
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"  records read : {read:,}")
    print(f"  groups       : {len(agg):,}")
    print(f"  rejected     : {rejected}")
    print(f"  wall time    : {elapsed:.3f}s")
    print(f"  throughput   : {read / elapsed:,.0f} records/sec")
    print(f"  peak RSS     : {peak_mb:.0f} MB")
    print("\n  Conclusion: throughput does not select the engine. Anything that "
          "argues\n  'it scales better' is arguing about a constraint that does not bind.")


# --------------------------------------------------------------- experiment 2
def pandas_leading_zeros() -> None:
    """The identifier-corruption hazard, on this project's actual data."""
    banner("2. PANDAS - type inference destroys leading-zero identifiers")
    import pandas as pd

    csv_path = next(iter(glob(f"{SAMPLE}/pharmacies/*.csv")))
    inferred = pd.read_csv(csv_path)
    explicit = pd.read_csv(csv_path, dtype=str)

    print(f"  default dtypes    : {dict(inferred.dtypes)}")
    print(f"  npi, inferred     : {inferred['npi'].head(4).tolist()}")
    print(f"  npi, dtype=str    : {explicit['npi'].head(4).tolist()}")
    print("\n  '0987654321' becomes 987654321. The pharmacy file contains "
          "0123456789 and\n  0987654321; 9 of 10 NDCs are leading-zero. A default that "
          "corrupts join keys\n  is a default that will corrupt them.")


# --------------------------------------------------------------- experiment 3
def polars_behaviour(work: Path) -> None:
    """Three questions: does it survive bad records, and can it read this format?"""
    banner("3. POLARS - malformed records and the JSON-array input format")
    import polars as pl

    missing_qty_file = next(
        p for p in glob(f"{work}/claims/*.json")
        if p.endswith("output-f6320eed-35a7-46bb-8c57-59be6146e31f.json")
    )

    print("\n  [a] read_json on the file whose record is missing 'quantity':")
    try:
        frame = pl.read_json(missing_qty_file)
        nulls = frame.null_count().to_dicts()[0]
        print(f"      OK  shape={frame.shape}  nulls={nulls}")
        print("      -> the field becomes null. No reason recorded, and "
              "indistinguishable\n         from a legitimately null value.")
    except Exception as exc:  # noqa: BLE001 - a spike reports, it does not gate
        print(f"      RAISED {type(exc).__name__}: {str(exc)[:160]}")

    print("\n  [b] read_json on the nasty file (one element is not an object):")
    try:
        frame = pl.read_json(f"{work}/claims/output-nasty.json")
        print(f"      OK  shape={frame.shape}")
    except Exception as exc:  # noqa: BLE001
        print(f"      RAISED {type(exc).__name__}: {str(exc)[:160]}")
        print("      -> one bad record loses all 6. This is the failure mode "
              "OQ-02 forbids.")

    print("\n  [c] scan_ndjson glob - the lazy/streaming path:")
    try:
        print(f"      OK  {pl.scan_ndjson(f'{work}/claims/*.json').collect().shape}")
    except Exception as exc:  # noqa: BLE001
        print(f"      RAISED {type(exc).__name__}: {str(exc)[:160]}")
        print("      -> the streaming engine reads NDJSON only. Our input is JSON "
              "arrays,\n         so lazy Polars needs a Python conversion pre-pass "
              "first.")

    print("\n  [d] read_json over a glob:")
    try:
        print(f"      OK  {pl.read_json(f'{work}/claims/*.json').shape}")
    except Exception as exc:  # noqa: BLE001
        print(f"      RAISED {type(exc).__name__}: {str(exc)[:160]}")


# --------------------------------------------------------------- experiment 4
def duckdb_behaviour(work: Path, tmp: Path) -> None:
    """Can one engine satisfy OQ-01, OQ-02 and OQ-07 with the same mechanism?"""
    banner("4. DUCKDB - permissive parse, validate in SQL, quarantine with reasons")
    import duckdb

    con = duckdb.connect()

    print("\n  [a] glob over JSON ARRAY files, nasty file included:")
    rows = con.sql(f"SELECT count(*) FROM read_json('{work}/claims/*.json')").fetchone()
    print(f"      {rows[0]:,} rows, no error - one bad record does not lose a file")

    print("\n  [b] lists of directory globs in one call (the brief's input contract):")
    rows = con.sql(f"""
        SELECT count(*) FROM read_json_objects(
            ['{work}/claims/*.json', '{work}/reverts/*.json'])""").fetchone()
    print(f"      {rows[0]:,} rows across both directory lists")

    # The proposal: parse permissively as raw JSON (cannot fail on a bad record),
    # type with TRY_CAST (a failed cast is NULL, not an abort), quarantine in SQL.
    con.sql(f"""
        CREATE OR REPLACE VIEW typed AS
        SELECT regexp_extract(filename, '[^/]+$')                         AS file,
               json_type(json)                                            AS jtype,
               json_extract_string(json, '$.id')                          AS id,
               json_extract_string(json, '$.npi')                         AS npi,
               json_extract_string(json, '$.ndc')                         AS ndc,
               TRY_CAST(json_extract_string(json,'$.price')    AS DECIMAL(18,4)) AS price,
               TRY_CAST(json_extract_string(json,'$.quantity') AS DECIMAL(18,4)) AS quantity,
               TRY_CAST(json_extract_string(json,'$.timestamp') AS TIMESTAMP)    AS ts
        FROM read_json_objects('{work}/claims/*.json', filename=true);

        CREATE OR REPLACE VIEW validated AS
        SELECT *, list_filter([
            CASE WHEN jtype <> 'OBJECT' THEN 'not_an_object' END,
            CASE WHEN id       IS NULL  THEN 'missing_or_invalid:id' END,
            CASE WHEN npi      IS NULL  THEN 'missing_or_invalid:npi' END,
            CASE WHEN ndc      IS NULL  THEN 'missing_or_invalid:ndc' END,
            CASE WHEN price    IS NULL  THEN 'missing_or_invalid:price' END,
            CASE WHEN quantity IS NULL  THEN 'missing_or_invalid:quantity' END,
            CASE WHEN quantity IS NOT NULL AND quantity <= 0
                                        THEN 'non_positive:quantity' END,
            CASE WHEN ts       IS NULL  THEN 'missing_or_invalid:timestamp' END
        ], x -> x IS NOT NULL) AS reasons
        FROM typed;
    """)

    print("\n  [c] one-pass accepted / rejected split:")
    acc, rej = con.sql("""
        SELECT count(*) FILTER (WHERE len(reasons) = 0),
               count(*) FILTER (WHERE len(reasons) > 0) FROM validated""").fetchone()
    print(f"      accepted={acc:,}  rejected={rej}")

    print("\n  [d] every rejected record WITH ITS REASON - what OQ-02 requires:")
    for file, rid, reasons in con.sql("""
            SELECT file, id, reasons FROM validated
            WHERE len(reasons) > 0 ORDER BY file, id""").fetchall():
        print(f"      {file[:38]:<40} {str(rid)[:24]:<26} {reasons}")

    print("\n  [e] CSV with forced VARCHAR - leading zeros preserved:")
    got = con.sql(f"""
        SELECT npi FROM read_csv('{SAMPLE}/pharmacies/*.csv',
            columns={{chain:'VARCHAR', npi:'VARCHAR'}}, header=true)
        ORDER BY npi LIMIT 4""").fetchall()
    print(f"      {[r[0] for r in got]}")

    print("\n  [f] a metric as SQL - exact DECIMAL sums, deterministic with ORDER BY:")
    for row in con.sql("""
            SELECT npi, ndc, count(*) AS fills, sum(price) AS revenue
            FROM validated WHERE len(reasons) = 0
            GROUP BY npi, ndc ORDER BY revenue DESC, npi, ndc LIMIT 3""").fetchall():
        print(f"      npi={row[0]}  ndc={row[1]}  fills={row[2]:>4}  revenue={row[3]}")
    print("      note: sums stay DECIMAL(38,4) and are exact; ratios return DOUBLE")
    print("            and need an explicit round for byte-identical output.")

    print("\n  [g] persist to one file, query it from a fresh read-only connection:")
    out = tmp / "out.duckdb"
    writer = duckdb.connect(str(out))
    writer.sql(f"""
        CREATE TABLE claims AS
        SELECT json_extract_string(json,'$.id')  AS id,
               json_extract_string(json,'$.npi') AS npi,
               TRY_CAST(json_extract_string(json,'$.price')    AS DECIMAL(18,4)) AS price,
               TRY_CAST(json_extract_string(json,'$.quantity') AS DECIMAL(18,4)) AS quantity
        FROM read_json_objects('{work}/claims/*.json');

        CREATE VIEW metric_revenue_by_pharmacy AS
        SELECT npi, count(*) AS fills, sum(price) AS revenue
        FROM claims WHERE quantity > 0 GROUP BY npi ORDER BY revenue DESC, npi;
    """)
    writer.close()

    reader = duckdb.connect(str(out), read_only=True)
    for row in reader.sql("SELECT * FROM metric_revenue_by_pharmacy LIMIT 3").fetchall():
        print(f"      npi={row[0]}  fills={row[1]:>4}  revenue={row[2]}")
    print(f"      artifact size: {out.stat().st_size // 1024} KB")
    print("      -> this file is the answer to OQ-07: a metric is one CREATE VIEW,")
    print("         addable by an analyst or an agent with no repo access at all.")


def main() -> int:
    if not SAMPLE.is_dir():
        print(f"sample data not found at {SAMPLE}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        work = build_workspace(tmp)
        stdlib_baseline()
        pandas_leading_zeros()
        polars_behaviour(work)
        duckdb_behaviour(work, tmp)

    banner("Spike complete. Findings are recorded in README.md in this directory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
