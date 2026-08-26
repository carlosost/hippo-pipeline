# Operations: deploying and owning this pipeline

Answers OQ-12. The brief invites assumptions about how this would run in a company where
teams are multidisciplinary and collaborate, so this is written as prose and reasoning
rather than as infrastructure nobody asked for. What is deliberately absent, and the
conditions under which it should stop being absent, is in [ADR-018](PROJECT_MEMORY.md).

---

## 1. What the deployment unit actually is

A batch job with **no server, no database, no state between runs and zero runtime
dependencies** (ADR-009, ADR-017). That makes the deployment story unusually short:

```
inputs (three directory lists)  →  one process  →  out/  →  object storage
```

There is nothing to keep running, nothing to fail over, nothing to back up. The only
long-lived artefacts are the input files and the published outputs.

**Container image.** The image would be a `python:3.12-slim` base, `uv sync --frozen`, and
`ENTRYPOINT ["uv", "run", "hippo"]`. About eight lines.

**No Dockerfile is committed, and that is deliberate.** It could not be built here, so it
could not be tested. An untested container recipe is playbook **AP-13** by construction —
"works under the test runner, fails under the production launcher" — and the gap between
"the tests pass" and "the deploy path ran" is exactly where first-boot failures live. A
recipe nobody has executed is a claim, not a deliverable.

Precisely why, since the reason matters to whoever finishes the job: a Docker daemon *does*
start in the build environment (`dockerd --storage-driver=vfs`, verified). What is missing
is a reachable **container registry** — Docker Hub, `ghcr.io`, `public.ecr.aws`,
`mirror.gcr.io` and `quay.io` are all outside the network egress allowlist, and nothing is
cached, so `FROM python:3.12-slim` has nothing to resolve against.

Adding it is a ten-minute job for anyone whose environment can pull a base image, and **the
first thing they should do is run the suite inside the image** — `uv run pytest tests/unit
tests/bdd` as a build step, so the artifact that ships is the artifact the tests ran in.

## 2. Where it runs, and on what schedule

Full recompute (ADR-017) means the job needs the complete history every run, so the
scheduling question is really "how often is the full history worth reprocessing".

At the sample's scale — 27,076 claims in **69 ms** — the answer is "as often as you like".
The realistic triggers:

| Trigger | Fits when |
|---|---|
| Scheduled (nightly / hourly) | Files land continuously and the business reads yesterday's numbers |
| On arrival (object-storage event) | Files land in batches and freshness matters |
| On demand | An analyst wants numbers for a corrected input set |

**The orchestrator is deliberately not chosen here.** Airflow, Dagster, an ECS scheduled
task, a Kubernetes CronJob and a GitHub Actions schedule all run this identically, because
the job is a process that reads files and writes files. Picking one in this repository
would impose a decision that belongs to whoever already runs one — and would be the first
thing thrown away on contact with a real platform team.

## 3. Who owns what

The layer split in ADR-003 was chosen for testability. Its second payoff is that it makes
**shared ownership possible without shared confusion**:

| Layer | Owner | Why that team |
|---|---|---|
| `gateway/` | Data engineering | The only place that knows about file formats, encodings and source-system quirks. Changing it needs nobody's business knowledge |
| `domain/` | Data engineering **and** analytics, jointly | The revert rules are business rules wearing code. ADR-012 was a business decision; changing it is another ADR, not a refactor |
| `metrics/` | Analytics engineering | One module and one test per metric. No ingestion knowledge required, by construction |
| `docs/METRICS.md` | Nobody — it is generated | Reviewed by everybody; `make lint` fails if it drifts |
| `docs/PROJECT_MEMORY.md` | Whoever makes a structural decision | Append-only. The rule is the ownership |

The architectural lint (`scripts/lint_architecture.py`) is what keeps these boundaries real
rather than aspirational. It has already rejected one violation written by the author of
the rule.

## 4. How a business user gets a new number

Three paths, and **most requests never reach engineering**:

| # | The request | Who does it | Turnaround |
|---|---|---|---|
| 1 | *"What's the reversal rate for chain saint in March?"* — the data answers it, no metric emits it | The analyst, or an agent on their behalf, queries `out/` directly | Minutes, nobody blocked |
| 2 | *"Emit that every run from now on"* | One module and one test in `metrics/`, reviewed by analytics engineering | A PR |
| 3 | *"We need a field we don't ingest"* | A `gateway/` change, an ADR, and data engineering | A design conversation first |

Path 1 exists because ADR-008 exports a flat fact table alongside the metrics. It is the
reason this is a foundation rather than a report generator, and it is what the brief's "AI
agents working on their behalf" actually needs.

For path 2, the `question=` field in the `@metric` declaration doubles as the ticket
description. A metric that cannot be given a business question does not get merged, and the
decorator enforces that at import time rather than at review time.

## 5. How outputs are versioned and published

Every run is identified by `inputs_digest` — a SHA-256 over every input file's path and
content (ADR-017). The publication scheme follows from it:

```
s3://<bucket>/hippo/runs/<inputs_digest>/     the full output set, immutable
s3://<bucket>/hippo/latest                    a pointer to the current digest
```

Three properties fall out:

- **Two consumers disagreeing is a diff, not an argument.** Compare digests; if they match,
  the inputs were byte-identical and so are the outputs.
- **Re-publishing is idempotent.** The same inputs produce the same digest and the same
  bytes, so a re-run overwrites itself harmlessly.
- **Nothing is ever silently replaced.** A corrected input file produces a new digest and a
  new prefix; the old run stays readable for anyone who cited it.

Metric schema changes are additive (ADR-005), and `_manifest.json` carries a
`schema_version` so a consumer can tell what it is reading.

## 6. What to watch, and what to alert on

The pipeline already exits non-zero when the reject rate exceeds its threshold (ADR-017),
and writes no metrics when it does. Beyond that, three signals — the playbook's §4.1 set,
adapted to a batch job:

| Signal | Where it comes from | Alert when |
|---|---|---|
| Run outcome | Exit code, and `status` in the manifest | Any non-zero exit, or two consecutive runs with `status != "ok"` |
| Reject rate | `reject_rate` in the manifest | Above the configured threshold — already fatal — **or** a step change from the previous run even while under it |
| Volume | `records.read` and `by_file` in the manifest | `records.read` moves more than ~20% against the previous run, or `by_file` loses an entry |

The third is the one that catches the quiet disaster: an upstream system that stops
delivering a file produces a run that is *entirely successful* and *silently missing 4% of
the business*. Nothing else in the manifest would flag it.

## 7. What breaks at 100×, and what to do about it

Every wall is already named in an ADR with a reversal condition, so none of this is a
surprise:

| Wall | First symptom | The ADR that names it |
|---|---|---|
| A single input file too large to hold in memory | `MemoryError` on one file; `json.load` reads whole files | ADR-009 — the stdlib has no good incremental JSON-array reader, so that day needs a dependency and a new ADR |
| Full recompute no longer fits its window | Run duration approaching the schedule interval | ADR-017 — the `--known-claims` side input, then watermark state, in that order |
| Metric execution time | O(metrics × claims); each metric re-scans | ADR-008 amendment — a fold protocol where one pass feeds every metric |
| SQL-shaped questions from analysts outgrow CSV | People asking for a database | ADR-009 — DuckDB was evaluated and rejected only because the metric surface is Python. The spike is committed and re-deciding costs a reading, not a re-evaluation |

Nothing here is close at the sample's scale, and none of it should be built before its
symptom appears.

## 8. What is deliberately not in this repository

| Absent | Why | When to add it |
|---|---|---|
| Dockerfile | No reachable container registry here, so no base image and no build; an unverified recipe is AP-13 | Immediately, by anyone who can pull a base image — running the suite inside the image as a build step |
| Orchestrator DAG | Belongs to whoever already runs a platform | When there is a platform to target |
| Terraform / IaC | Same reason, more so | Same |
| MCP server, metric DSL, semantic layer | ADR-010, with named reversal conditions | When a live consumer cannot run Python |
| Secrets handling | The pipeline reads files and writes files. It has no credentials to manage | When an input or output moves behind an authenticated service |
| PHI / compliance controls | The sample data carries none, and inventing a compliance layer for data that does not exist is scope theatre | Before the first real claim file, with someone who knows the regulatory perimeter |
