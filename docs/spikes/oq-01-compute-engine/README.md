# Spike — OQ-01: compute engine

**Date:** 2026-08-25 · **Status:** evidence gathered, decision NOT taken
**Reproduce:**

```bash
uv run --with duckdb --with polars --with pandas \
    python docs/spikes/oq-01-compute-engine/spike.py
```

None of these libraries is a project dependency, and none may become one without an
ADR (see `pyproject.toml`). `uv run --with` installs them into a throwaway environment
and leaves the manifest untouched.

Measured on Python 3.10.12 with duckdb 1.5.5, polars 1.44.0, pandas 2.3.3. Rerun the
script rather than trusting the numbers below — that is the point of committing it.

---

## 1. The question is not throughput

A pure-stdlib streaming pass over the entire dataset:

```
records read : 27,076      wall time  : 0.069s
groups       : 170         throughput : 391,175 records/sec
rejected     : 3           peak RSS   : 39 MB
```

Single-threaded CPython. Linear extrapolation puts 100M claims at roughly 4.5 minutes
with flat memory. **Throughput does not select the engine here**, and any argument that
rests on "it scales better" is arguing about a constraint that does not bind.

What OQ-01 actually decides is two things that cannot be changed later without a
rewrite:

1. **Where per-record rejection lives** (OQ-02). If the engine cannot say *which record
   failed and why*, a Python pre-pass gets bolted on — and then the engine is only doing
   an aggregation that takes 69 ms and needs no engine.
2. **What surface the metric layer lives on** (OQ-07). A metric written as a Python
   function is extended by someone who can read the ingestion code. A metric written as
   SQL over a published artifact is extended by anyone, including an agent with no repo
   access.

Point 2 is why the decision order was corrected: **OQ-07 is decided before OQ-01.**

## 2. pandas — eliminated on a concrete hazard

```
default dtypes : {'chain': dtype('O'), 'npi': dtype('int64')}
npi, inferred  : [1234567890, 987654321, 5678901234, 4567890123]
npi, dtype=str : ['1234567890', '0987654321', '5678901234', '4567890123']
```

`'0987654321'` silently became `987654321`. This project's pharmacy file contains
`0123456789` and `0987654321`, and 9 of its 10 NDCs are leading-zero. Type inference
destroys the join keys by default. Survivable with `dtype=str` everywhere — but a
default that corrupts identifiers is a default that eventually will.

## 3. Polars — one disqualifying finding

| Test | Result |
|---|---|
| `read_json` on the file missing `quantity` | Reads fine, field becomes `null` — **no reason recorded**, indistinguishable from a legitimate null |
| `read_json` on a file with one non-object element | `ComputeError: can only deserialize json objects` — **one bad record loses all 6** |
| `scan_ndjson` glob (the lazy/streaming path) | `ComputeError: NDJSON line expected to contain JSON object: list[struct[6]]` |
| `read_json` with a glob | `FileNotFoundError` — no glob support |

Row 3 is the disqualifying one. The input format is **JSON arrays per file**, and the
Polars streaming engine reads NDJSON only. Using lazy Polars requires walking every file
in Python and converting first — at which point the stdlib ingest is already written and
Polars is performing a group-by over 27k rows.

Row 2 is the failure mode OQ-02 exists to prevent: one malformed record blocking the
business.

## 4. DuckDB — every requirement satisfied natively

```
[a] glob over JSON ARRAY files, nasty file included : 27,082 rows, no error
[b] lists of directory globs in one call            : 27,390 rows across both lists
[c] one-pass accepted / rejected split              : accepted=27,075  rejected=7
[e] CSV with forced VARCHAR                         : ['0123456789', '0987654321', ...]
[g] persisted artifact                              : 1,292 KB, queryable read-only
```

Every rejected record carries its reason and its source file:

```
output-d3b4f4d8…  0fdbb8bc…       ['missing_or_invalid:quantity']
output-f6320eed…  69077695…       ['non_positive:quantity']
output-f6320eed…  c331a516…       ['missing_or_invalid:quantity']
output-nasty      bad-null-price  ['missing_or_invalid:price']
output-nasty      bad-str-qty     ['missing_or_invalid:quantity']
output-nasty      bad-ts          ['missing_or_invalid:timestamp']
output-nasty      NULL            ['not_an_object', 'missing_or_invalid:id', …]
```

### The pattern that produces that

```sql
-- 1. parse permissively: raw JSON per record. This CANNOT fail on a bad record.
read_json_objects(['claims_dir_a/*.json','claims_dir_b/*.json'], filename=true)

-- 2. type with TRY_CAST: a failed cast yields NULL instead of aborting the file
TRY_CAST(json_extract_string(json,'$.quantity') AS DECIMAL(18,4)) AS quantity

-- 3. quarantine in SQL: every record carries a reason list; empty list = accepted
list_filter([ CASE WHEN quantity IS NULL THEN 'missing_or_invalid:quantity' END, … ],
            x -> x IS NOT NULL) AS reasons
```

Three properties follow: no file is lost to one bad record; every rejection carries a
machine-readable reason plus its source filename; money stays in `DECIMAL(38,4)` and is
exact. Note that **division returns `DOUBLE`**, so ratio metrics need an explicit round
to keep output byte-identical (charter success criterion 4).

## 5. Requirements mapping (playbook §1.2)

| Requirement | stdlib | Polars | DuckDB |
|---|---|---|---|
| Read lists of dirs of JSON **array** files | native | **workaround** (no glob, no lazy array read) | native |
| Survive one malformed record in a file | native | **fails the file** | native |
| Reject with a per-record *reason* | native | workaround (nulls, no reason) | native |
| Preserve leading-zero identifiers | native | native | native (explicit VARCHAR) |
| Exact money arithmetic | native (`Decimal`) | workaround | native (`DECIMAL`) |
| Larger-than-memory joins / aggregations | you write the spill | native | native |
| Metrics extendable without reading ingest code | **cannot** | workaround | native (SQL views) |
| Zero runtime dependencies | native | no | no |

Playbook §1.2: *never select a technology to avoid one column of "no" and then route
around that "no" in code.* stdlib carries one hard **cannot**, in the row that holds the
brief's differentiator.

## 6. PostgreSQL — why it is not on the table

Asked directly, and worth recording so it is not re-litigated.

DuckDB is a **compute engine that happens to persist**; PostgreSQL is a **system of
record that happens to compute**. This pipeline needs the former.

- Postgres adds an operational component — server, credentials, migrations, backups,
  upgrades, on-call — to a batch job with no need for one. `make run` becomes
  `docker compose up && wait && migrate && make run`.
- Ingest becomes the dominant cost, and exists only because a server was chosen: every
  record must be `COPY`ed over a socket into a staging table before the first `SELECT`,
  dragging in a staging schema, an upsert-idempotency problem and a load-failure
  recovery path. DuckDB queried the files in place.
- Row storage is wrong for the query shape. `GROUP BY npi, ndc` over all rows reads
  whole heap tuples in Postgres; DuckDB reads four columns, vectorized.
- Determinism. Files in, file out is trivially reproducible; a long-lived shared server
  holds state nobody put there deliberately.

**Postgres is the right answer** when there are concurrent writers (DuckDB permits one
writer process), when the thing being built is a *serving* layer for many networked
users, when the data needs governance (backups, PITR, access control — DuckDB gives you
a file, and whoever holds it holds everything), or when OQ-09 concludes the pipeline is
incremental with upserts and watermarks. In a production estate you would likely have
both, in different rows of the architecture: something columnar computes, and results
land in Postgres or a warehouse for serving.

**Honest caveat on DuckDB:** it has been 1.x for a couple of years against three decades
of Postgres, and its storage format has moved. Disqualifying for a system of record;
irrelevant for a pipeline that regenerates its output from source files every run. And
since DuckDB reads and writes Parquet, the output is not locked in.

## 7. Leading recommendation, and what would reverse it

**DuckDB**, with the gateway owning ingest as SQL against `read_json_objects`, and
metrics as versioned SQL views over a published artifact. One runtime dependency,
embedded, no server. It answers OQ-02 and OQ-07 with the same mechanism rather than in
two subsystems.

This is **not yet a decision**. It is reversed if:

- **OQ-07 lands on a Python metric registry rather than SQL.** DuckDB's main advantage
  then evaporates and stdlib wins on zero dependencies. This is why OQ-07 is now
  sequenced first.
- **OQ-09 concludes the pipeline is incremental and stateful.** Concurrency control
  starts to matter and the calculus changes.
- **OQ-05 requires an output format DuckDB serves badly.** Unlikely — it writes Parquet,
  CSV and JSON — but it is the constraint to check.

**Risk to manage if DuckDB is chosen.** Logic in SQL strings is logic outside mypy,
outside ruff and easy to leave untested. Non-negotiable mitigations, to be written into
the ADR: SQL lives in `.sql` files and is never inlined; every statement is tested
against fixture tables; the architectural lint gains a rule that no module outside
`gateway/` may `import duckdb`. Without that discipline this choice ages badly.
