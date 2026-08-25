"""Quarantine reason codes (ADR-011, ADR-012).

Codes, never prose: a reason a human wrote as a sentence cannot be aggregated, and the
first question anyone asks of a quarantine file is "how many of each?".

This list is a data contract and is **additive only** (ADR-005). Adding a code is free;
renaming one breaks whoever aggregates by it.
"""

from __future__ import annotations

# --- record shape, produced by the gateway (ADR-011) -------------------------
FILE_UNPARSEABLE = "file_unparseable"
NOT_AN_OBJECT = "not_an_object"
NON_POSITIVE_QUANTITY = "non_positive:quantity"
UNPARSEABLE_TIMESTAMP = "unparseable_timestamp"

# --- scope, produced by the gateway (ADR-011, ADR-014) -----------------------
NPI_NOT_IN_PHARMACY_DATASET = "npi_not_in_pharmacy_dataset"

# --- linkage, produced by revert resolution (ADR-012) ------------------------
CLAIM_NOT_FOUND = "claim_not_found"
CLAIM_NOT_ACCEPTED = "claim_not_accepted"
DUPLICATE_REVERT_FOR_CLAIM = "duplicate_revert_for_claim"
REVERT_PRECEDES_CLAIM = "revert_precedes_claim"


def missing_field(name: str) -> str:
    """A required field is absent from the record."""
    return f"missing_field:{name}"


def not_a_number(field: str) -> str:
    """A numeric field is present but is not a number."""
    return f"not_a_number:{field}"
