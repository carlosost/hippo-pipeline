"""The types every layer passes around.

All frozen: a metric cannot mutate what the next metric reads, and a frozen input is one
fewer thing to reason about when output must be byte-identical (charter 1.3.4).

Money and quantity are `Decimal`, never `float` (ADR-009). Timestamps are timezone-aware
UTC (ADR-013) - the gateway converts once, at the boundary.

`source_file` and `record_index` are lineage, carried on the record itself. The charter
asks that every number be traceable to the records that produced it, and provenance that
lives beside the value is provenance that cannot be lost in a join.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

UNKNOWN_SOURCE = "<unknown>"


@dataclass(frozen=True, slots=True)
class Pharmacy:
    """A pharmacy we are in scope for. Absence from the reference file means out of scope."""

    npi: str
    chain: str


@dataclass(frozen=True, slots=True)
class Claim:
    """A prescription fill.

    `reverted` and `reverted_at` are set by revert resolution (ADR-012). A reverted claim
    is *retained* rather than deleted: it leaves revenue and fill counts but enters
    reversal metrics, and deleting it would make the reversal rate uncomputable.
    """

    id: str
    npi: str
    ndc: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    reverted: bool = False
    reverted_at: datetime | None = None
    source_file: str = UNKNOWN_SOURCE
    record_index: int = -1


@dataclass(frozen=True, slots=True)
class Revert:
    """A reversal of a claim.

    `id` is **not** unique in real data - three ids in the sample dataset appear twice
    with different timestamps. The reversal key is `claim_id` (ADR-012).
    """

    id: str
    claim_id: str
    timestamp: datetime
    source_file: str = UNKNOWN_SOURCE
    record_index: int = -1


@dataclass(frozen=True, slots=True)
class QuarantinedRecord:
    """A record that did not make it through, and why.

    `raw` is the record verbatim so it can be corrected and re-fed. `source_file` is a
    basename rather than a path, because paths differ per machine and the file is what
    identifies the record.
    """

    source_file: str
    record_index: int
    reasons: tuple[str, ...]
    raw: str


@dataclass(frozen=True, slots=True)
class ExcludedRevert:
    """A revert that could not be linked to an accepted claim.

    Deliberately *not* a `QuarantinedRecord`: rendering the revert back to text is
    serialization, and serialization lives in the gateway (ADR-003). The domain says
    which revert and why; the gateway decides what that looks like on disk.
    """

    revert: Revert
    reason: str


@dataclass(frozen=True, slots=True)
class Dataset:
    """What every metric receives (ADR-008).

    One frozen argument rather than a bare claim list, because several metrics worth
    writing need chain membership or revert timing.
    """

    claims: tuple[Claim, ...]
    reverts: tuple[Revert, ...]
    pharmacies: Mapping[str, Pharmacy]


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """The output of revert resolution."""

    claims: tuple[Claim, ...]
    excluded: tuple[ExcludedRevert, ...]
    counts: Mapping[str, int]
