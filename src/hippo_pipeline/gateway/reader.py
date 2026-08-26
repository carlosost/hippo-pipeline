"""Reading and validating the input files (F-01).

Every decision about what the bytes mean lives here and nowhere else. Downstream code may
assume its inputs are already valid; a validation error surfacing in `domain/` means this
boundary let something through.

The one non-obvious thing in this module: **numbers are parsed from their text form.**
`json.load` converts every number to `float` before any code sees it, so `Decimal(str(v))`
would inherit the float's error and quietly violate ADR-009. `parse_float` and `parse_int`
intercept the token itself.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from hippo_pipeline.domain import reasons
from hippo_pipeline.domain.models import (
    Claim,
    Pharmacy,
    QuarantinedRecord,
    Revert,
)

CLAIM_FIELDS = ("id", "npi", "ndc", "price", "quantity", "timestamp")
REVERT_FIELDS = ("id", "claim_id", "timestamp")


@dataclass(frozen=True, slots=True)
class InputFile:
    """One input file and its content digest (ADR-017).

    Two runs with the same `inputs_digest` saw byte-identical inputs and must therefore
    produce byte-identical outputs. When two runs disagree, this is what turns an argument
    into a diff.
    """

    path: str
    sha256: str
    bytes: int


class _Digests:
    """Collects a digest per file as it is read, so hashing costs no extra pass."""

    def __init__(self) -> None:
        self._files: dict[str, InputFile] = {}

    def record(self, path: Path, data: bytes) -> None:
        self._files[str(path)] = InputFile(
            path=str(path), sha256=hashlib.sha256(data).hexdigest(), bytes=len(data)
        )

    def files(self) -> tuple[InputFile, ...]:
        return tuple(self._files[key] for key in sorted(self._files))

    def combined(self) -> str:
        """One digest for the whole input set: sha256 over each file's path and digest.

        Path is included deliberately. Two runs over the same bytes in different files are
        not the same run - record indices, and therefore the quarantine files, differ.
        """
        joined = "\n".join(f"{f.path}:{f.sha256}" for f in self.files())
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IngestCounts:
    """Everything the run manifest needs, and the invariant it must satisfy."""

    claims_read: int
    claims_accepted: int
    reverts_read: int
    reverts_accepted: int
    rejected: int
    excluded: int
    files_unreadable: int
    by_reason: Mapping[str, int]
    by_file: Mapping[str, int]

    @property
    def read(self) -> int:
        return self.claims_read + self.reverts_read

    @property
    def accepted(self) -> int:
        return self.claims_accepted + self.reverts_accepted

    @property
    def reject_rate(self) -> float:
        """Rejections over records read. Exclusions are not defects and are not counted."""
        return self.rejected / self.read if self.read else 0.0

    def balances(self) -> bool:
        """read == accepted + rejected + excluded.

        The reason every total is explainable. `files_unreadable` sits outside the
        identity on purpose: a file that could not be parsed contributed no records to
        read, so counting its quarantine entry as a rejected record would break the sum
        and hide the difference between one bad record and one bad file.
        """
        return self.read == self.accepted + self.rejected + self.excluded


@dataclass(frozen=True, slots=True)
class IngestResult:
    pharmacies: Mapping[str, Pharmacy]
    claims: tuple[Claim, ...]
    reverts: tuple[Revert, ...]
    rejected: tuple[QuarantinedRecord, ...]
    excluded: tuple[QuarantinedRecord, ...]
    counts: IngestCounts
    quarantined_claim_ids: frozenset[str]
    inputs: tuple[InputFile, ...]
    inputs_digest: str


# --------------------------------------------------------------- file access --
def _files(dirs: Sequence[str], suffix: str) -> list[Path]:
    """Every matching file across every directory, in sorted order.

    Sorted so record indices - and therefore the quarantine files - are stable across
    runs (charter 1.3.4). A missing directory yields nothing rather than raising: the
    brief passes lists of directories and an empty one is not an error.
    """
    found: list[Path] = []
    for directory in dirs:
        root = Path(directory)
        if root.is_dir():
            found.extend(sorted(p for p in root.iterdir() if p.is_file() and p.suffix == suffix))
    return sorted(found)


def _json_records(path: Path, digests: _Digests) -> tuple[list[object] | None, str | None]:
    """Return the array in `path`, or None plus the reason it could not be read.

    Reads bytes once: the digest is taken from the same buffer that is parsed, so hashing
    adds no second pass over the input. A file that cannot be decoded is still hashed -
    knowing exactly which bytes failed is the point.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None, reasons.FILE_UNPARSEABLE
    digests.record(path, data)
    try:
        payload = json.loads(
            data.decode("utf-8"),
            parse_float=Decimal,
            parse_int=Decimal,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, reasons.FILE_UNPARSEABLE
    if not isinstance(payload, list):
        # A valid JSON document of the wrong shape is unusable in exactly the same way.
        return None, reasons.FILE_UNPARSEABLE
    return payload, None


# ---------------------------------------------------------------- field rules --
def _string(record: Mapping[str, object], field: str, problems: list[str]) -> str | None:
    value = record.get(field)
    if value is None:
        problems.append(reasons.missing_field(field))
        return None
    if not isinstance(value, str) or not value:
        problems.append(reasons.missing_field(field))
        return None
    return value


def _decimal(record: Mapping[str, object], field: str, problems: list[str]) -> Decimal | None:
    if field not in record or record[field] is None:
        problems.append(reasons.missing_field(field))
        return None
    value = record[field]
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is an int subclass; a boolean price is not a price
        problems.append(reasons.not_a_number(field))
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        problems.append(reasons.not_a_number(field))
        return None


def _timestamp(record: Mapping[str, object], field: str, problems: list[str]) -> datetime | None:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        problems.append(reasons.missing_field(field))
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        problems.append(reasons.UNPARSEABLE_TIMESTAMP)
        return None
    # ADR-013: the source carries no offset, so naive means UTC by declaration.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _raw(record: object) -> str:
    """The record as text, for the quarantine file, so it can be corrected and re-fed."""
    try:
        return json.dumps(record, default=str, sort_keys=True)
    except (TypeError, ValueError):
        return repr(record)


# ------------------------------------------------------------------- records --
def _elements(
    paths: Sequence[Path], digests: _Digests
) -> Iterator[tuple[Path, int, object, str | None]]:
    """Yield (file, index, record, file_level_reason) for every element of every file."""
    for path in paths:
        payload, failure = _json_records(path, digests)
        if payload is None:
            yield path, 0, None, failure
            continue
        for index, record in enumerate(payload):
            yield path, index, record, None


def _read_pharmacies(dirs: Sequence[str], digests: _Digests) -> dict[str, Pharmacy]:
    """Reference data. Columns by NAME - the sample file's header is `chain,npi`."""
    pharmacies: dict[str, Pharmacy] = {}
    for path in _files(dirs, ".csv"):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digests.record(path, data)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for row in csv.DictReader(text.splitlines()):
            npi = (row.get("npi") or "").strip()
            chain = (row.get("chain") or "").strip()
            if npi:
                pharmacies[npi] = Pharmacy(npi=npi, chain=chain)
    return pharmacies


def _validate_claim(record: object, path: Path, index: int) -> tuple[Claim | None, tuple[str, ...]]:
    """Return the claim, or None plus every reason it failed.

    Every applicable reason is collected, not just the first - the first failure is not
    necessarily the interesting one.
    """
    if not isinstance(record, dict):
        return None, (reasons.NOT_AN_OBJECT,)

    problems: list[str] = []
    claim_id = _string(record, "id", problems)
    npi = _string(record, "npi", problems)
    ndc = _string(record, "ndc", problems)
    price = _decimal(record, "price", problems)
    quantity = _decimal(record, "quantity", problems)
    stamp = _timestamp(record, "timestamp", problems)

    # Separate from not_a_number on purpose: a zero quantity passes every type check and
    # still divides by zero in any unit-price metric.
    if quantity is not None and quantity <= 0:
        problems.append(reasons.NON_POSITIVE_QUANTITY)

    if problems or claim_id is None or npi is None or ndc is None:
        return None, tuple(problems)
    if price is None or quantity is None or stamp is None:  # pragma: no cover - defensive
        return None, tuple(problems)

    return (
        Claim(
            id=claim_id,
            npi=npi,
            ndc=ndc,
            price=price,
            quantity=quantity,
            timestamp=stamp,
            source_file=path.name,
            record_index=index,
        ),
        (),
    )


def _validate_revert(
    record: object, path: Path, index: int
) -> tuple[Revert | None, tuple[str, ...]]:
    if not isinstance(record, dict):
        return None, (reasons.NOT_AN_OBJECT,)

    problems: list[str] = []
    revert_id = _string(record, "id", problems)
    claim_id = _string(record, "claim_id", problems)
    stamp = _timestamp(record, "timestamp", problems)

    if problems or revert_id is None or claim_id is None or stamp is None:
        return None, tuple(problems)

    return (
        Revert(
            id=revert_id,
            claim_id=claim_id,
            timestamp=stamp,
            source_file=path.name,
            record_index=index,
        ),
        (),
    )


def ingest(
    pharmacy_dirs: Sequence[str],
    claim_dirs: Sequence[str],
    revert_dirs: Sequence[str],
) -> IngestResult:
    """Turn three lists of directories into validated records plus an audit of the rest.

    Rejection and exclusion are kept apart (ADR-011). A schema violation is a defect; a
    claim for a pharmacy outside our reference file is a perfectly good record that is
    simply not ours. One sink for both would report a 15% defect rate for a source whose
    real defect rate is three orders of magnitude lower.
    """
    digests = _Digests()
    pharmacies = _read_pharmacies(pharmacy_dirs, digests)

    claims: list[Claim] = []
    reverts: list[Revert] = []
    rejected: list[QuarantinedRecord] = []
    excluded: list[QuarantinedRecord] = []
    by_reason: dict[str, int] = {}
    by_file: dict[str, int] = {}
    quarantined_claim_ids: set[str] = set()
    claims_read = 0
    reverts_read = 0
    files_unreadable = 0

    def note(record: QuarantinedRecord) -> None:
        for code in record.reasons:
            by_reason[code] = by_reason.get(code, 0) + 1
        by_file[record.source_file] = by_file.get(record.source_file, 0) + 1

    for path, index, record, file_failure in _elements(_files(claim_dirs, ".json"), digests):
        if file_failure is not None:
            files_unreadable += 1
            entry = QuarantinedRecord(path.name, index, (file_failure,), "")
            rejected.append(entry)
            note(entry)
            continue

        claims_read += 1
        claim, problems = _validate_claim(record, path, index)
        if claim is None:
            entry = QuarantinedRecord(path.name, index, problems, _raw(record))
            rejected.append(entry)
            note(entry)
            if isinstance(record, dict) and isinstance(record.get("id"), str):
                quarantined_claim_ids.add(record["id"])
            continue

        if claim.npi not in pharmacies:
            entry = QuarantinedRecord(
                path.name, index, (reasons.NPI_NOT_IN_PHARMACY_DATASET,), _raw(record)
            )
            excluded.append(entry)
            note(entry)
            quarantined_claim_ids.add(claim.id)
            continue

        claims.append(claim)

    for path, index, record, file_failure in _elements(_files(revert_dirs, ".json"), digests):
        if file_failure is not None:
            files_unreadable += 1
            entry = QuarantinedRecord(path.name, index, (file_failure,), "")
            rejected.append(entry)
            note(entry)
            continue

        reverts_read += 1
        revert, problems = _validate_revert(record, path, index)
        if revert is None:
            entry = QuarantinedRecord(path.name, index, problems, _raw(record))
            rejected.append(entry)
            note(entry)
            continue
        reverts.append(revert)

    counts = IngestCounts(
        claims_read=claims_read,
        claims_accepted=len(claims),
        reverts_read=reverts_read,
        reverts_accepted=len(reverts),
        rejected=len(rejected) - files_unreadable,
        excluded=len(excluded),
        files_unreadable=files_unreadable,
        by_reason={code: by_reason[code] for code in sorted(by_reason)},
        by_file={name: by_file[name] for name in sorted(by_file)},
    )

    return IngestResult(
        pharmacies=pharmacies,
        claims=tuple(claims),
        reverts=tuple(reverts),
        rejected=tuple(rejected),
        excluded=tuple(excluded),
        counts=counts,
        quarantined_claim_ids=frozenset(quarantined_claim_ids),
        inputs=digests.files(),
        inputs_digest=digests.combined(),
    )
