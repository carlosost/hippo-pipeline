# Data Engineer — Take-Home Assignment

## What we're asking you to do

Architect and build a data pipeline that processes pharmacy **claims** and their
**reversals**. Beyond producing correct numbers, the pipeline should be a
foundation others can build on — a clean base that business teams, and AI agents
working on their behalf, can use autonomously to extract metrics or extend with
new functionality. Additionally, propose and export useful metrics for the data.

We're interested in both the working code *and* the thinking behind it: how you
structured the pipeline, the tradeoffs you weighed, and where you'd take it
next. How you present that reasoning is up to you, and you're welcome to include
anything you think matters for a high-performing, scalable solution. Feel free to
include assumptions or details on how this solution would be deployed and work in
a company where teams are multidisciplinary and collaborate with each other.

You don't need any prior healthcare experience — the next section gives you the
background you need. Feel free to reach out for any questions.

---

## A short primer on the PBM world

### What is a PBM?

A **Pharmacy Benefit Manager (PBM)** sits in the middle of the prescription-drug
supply chain. It connects the parties that make a prescription fill happen —
patients, pharmacies, drug manufacturers, and payers — and negotiates prices on
drugs. We work to offer the lowest possible price on generic and branded
medications, whether or not the patient has insurance.

The core flow:

1. A patient gets a **prescription** for a drug. A drug is identified by an **NDC** (National Drug Code) and a **quantity** (how many units to dispense).
2. The patient takes that prescription to a **pharmacy**, identified by its **NPI** (National Provider Identifier).
3. The pharmacist tells the patient the **price** and submits a **claim** — a record that this drug was filled at this pharmacy for this price.

### What is a claim?

A **claim** is the event generated when a pharmacy fills a prescription. It
captures *which* drug (`ndc`) was filled, *at which* pharmacy (`npi`), at *what*
total `price`, in *what* `quantity`, and *when* (`timestamp`). Claims are the
primary unit of activity in our data: each one represents real money and a real
fill.

### What is a reversal (revert)?

Sometimes a fill doesn't complete. The most common reason: the patient never
comes back to pick up the medication. When that happens, the pharmacist submits
a **reversal** (also called a *revert*) that **invalidates** the original claim.
A reversal points back at the claim it cancels (`claim_id`) and records *when* it
happened (`timestamp`).

A reverted claim should be treated as if the fill never happened for the purpose
of revenue and volume metrics — but the fact that it was reverted is itself a
signal worth measuring (for example, a pharmacy with a high reversal rate may
have an operational problem).

### Why we care

Clean, trustworthy aggregates over claims and reversals let our business team
spot opportunities and problems — which pharmacies are performing well, which
are underperforming, and where prices are out of line. Your pipeline is the
foundation those decisions sit on, so correctness and clear reasoning matter
more than cleverness.

---

## Inputs

Your application should accept **three lists of directory paths**: one for the
pharmacy dataset, one for claims events, and one for reverts events.

- The pharmacy dataset changes rarely — treat it as slowly-changing reference data.
- Claims and reverts arrive as a **stream of events**, split across many files.
- Some events do **not** comply with the schema below. Your pipeline must handle malformed or invalid records sensibly — how is your call.
- We're only interested in events for pharmacies that exist in the pharmacy dataset.

Sample data is provided in [`data/sample-data.tar.gz`](data/sample-data.tar.gz).
Extract it to find `claims/`, `reverts/`, and `pharmacies/` directories.

### Data schemas

**Pharmacy** (CSV)

| field | type | notes |
|-------|------|-------|
| `npi` | string | identifier of the pharmacy |
| `chain` | string | the chain the pharmacy belongs to |

**Claim event** (JSON)

| field | type | notes |
|-------|------|-------|
| `id` | string | UUID identifying the claim |
| `npi` | string | pharmacy that filled the claim |
| `ndc` | string | drug identifier |
| `price` | float | total price charged (`unit_price` × `quantity`) |
| `quantity` | integer/float | amount of the drug filled |
| `timestamp` | datetime | when the claim was filled |

**Revert event** (JSON)

| field | type | notes |
|-------|------|-------|
| `id` | string | UUID identifying the revert |
| `claim_id` | string | the claim being invalidated |
| `timestamp` | datetime | when the revert happened |

---

## Technical requirements

- Write the application in **Python**. Any build tool is fine.
- Deliver as a **git repository** with a README explaining how to run it against the sample files.

---

## Using AI tools

**Using AI tools (Claude, ChatGPT, Copilot, Cursor, etc.) is encouraged.** We
use them every day and we want to see how you work *with* them.

You own every line you submit and should be able to explain any part of it in a
follow-up conversation.
