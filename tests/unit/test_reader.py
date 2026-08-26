"""F-01: the gateway is where every decision about what the bytes mean lives."""

from decimal import Decimal

from hippo_pipeline.domain import reasons
from hippo_pipeline.gateway import ingest

from .conftest import at, valid_claim_record


def _codes(records):
    return sorted(code for r in records for code in r.reasons)


# ------------------------------------------------------------------- defects --
def test_a_claim_missing_a_field_is_rejected_with_its_provenance(dirs):
    dirs.claims([valid_claim_record(quantity=...)], name="claims-a.json")

    result = ingest(*dirs.args)

    assert result.claims == ()
    assert _codes(result.rejected) == [reasons.missing_field("quantity")]
    assert result.rejected[0].source_file == "claims-a.json"
    assert result.rejected[0].record_index == 0


def test_zero_quantity_is_rejected_separately_from_a_type_error(dirs):
    """It passes every type check and still divides by zero in any unit-price metric."""
    dirs.claims([valid_claim_record(quantity=0)])

    result = ingest(*dirs.args)

    assert _codes(result.rejected) == [reasons.NON_POSITIVE_QUANTITY]


def test_a_non_numeric_quantity_is_rejected(dirs):
    dirs.claims([valid_claim_record(quantity="ten")])

    result = ingest(*dirs.args)

    assert _codes(result.rejected) == [reasons.not_a_number("quantity")]


def test_an_element_that_is_not_an_object_is_rejected_and_the_rest_survive(dirs):
    dirs.claims([valid_claim_record(id="C1"), "oops", valid_claim_record(id="C2")])

    result = ingest(*dirs.args)

    assert [c.id for c in result.claims] == ["C1", "C2"]
    assert _codes(result.rejected) == [reasons.NOT_AN_OBJECT]


def test_an_unparseable_file_does_not_stop_the_run(dirs):
    dirs.claims("{not json", name="broken.json")
    dirs.claims([valid_claim_record(id="C1"), valid_claim_record(id="C2")], name="good.json")

    result = ingest(*dirs.args)

    assert len(result.claims) == 2
    assert _codes(result.rejected) == [reasons.FILE_UNPARSEABLE]
    assert result.counts.files_unreadable == 1
    # A file contributes no records to `read`, so it must not count as a rejected record.
    assert result.counts.balances()


def test_a_record_accumulates_every_reason_not_just_the_first(dirs):
    dirs.claims([valid_claim_record(price=..., timestamp="not-a-date")])

    result = ingest(*dirs.args)

    assert set(result.rejected[0].reasons) == {
        reasons.missing_field("price"),
        reasons.UNPARSEABLE_TIMESTAMP,
    }


# ---------------------------------------------------------------- exclusions --
def test_a_claim_for_an_unknown_pharmacy_is_excluded_not_rejected(dirs):
    """4,085 sample claims land here. Calling them defects would report a 15% error rate
    for a source whose real defect rate is 0.011% (ADR-011)."""
    dirs.claims([valid_claim_record(npi="9999999999")])

    result = ingest(*dirs.args)

    assert result.claims == ()
    assert result.rejected == ()
    assert _codes(result.excluded) == [reasons.NPI_NOT_IN_PHARMACY_DATASET]


# ---------------------------------------------------------------- type rules --
def test_identifiers_keep_their_leading_zeros(dirs):
    dirs.claims([valid_claim_record(npi="0123456789", ndc="00054027225")])

    claim = ingest(*dirs.args).claims[0]

    assert claim.npi == "0123456789"
    assert claim.ndc == "00054027225"


def test_quantity_is_accepted_as_an_integer_or_a_float(dirs):
    dirs.claims(
        [
            valid_claim_record(id="C1", quantity=15),
            valid_claim_record(id="C2", quantity=90.0),
            valid_claim_record(id="C3", quantity=8.5),
        ]
    )

    quantities = [c.quantity for c in ingest(*dirs.args).claims]

    assert quantities == [Decimal("15"), Decimal("90.0"), Decimal("8.5")]


def test_money_is_exact_and_never_round_tripped_through_a_float(dirs):
    """json.load would have made this 0.1000000000000000055511151231257827 (ADR-009)."""
    dirs.claims([valid_claim_record(price=0.1)])

    price = ingest(*dirs.args).claims[0].price

    assert price == Decimal("0.1")
    assert str(price) == "0.1"


def test_naive_timestamps_are_read_as_utc(dirs):
    dirs.claims([valid_claim_record(timestamp="2026-03-01T14:40:11")])

    assert ingest(*dirs.args).claims[0].timestamp == at("2026-03-01T14:40:11")


def test_pharmacy_columns_are_read_by_name_not_position(dirs):
    """The sample file's header is `chain,npi` - the reverse of the brief's table."""
    dirs.pharmacy_csv("chain,npi\nsaint,0123456789\n")

    pharmacies = ingest(*dirs.args).pharmacies

    assert pharmacies["0123456789"].chain == "saint"


# ---------------------------------------------------------------- run rules --
def test_several_directories_in_one_list_are_all_read(dirs, tmp_path):
    (tmp_path / "claims-2").mkdir()
    dirs.claims([valid_claim_record(id="C1"), valid_claim_record(id="C2")])
    (tmp_path / "claims-2" / "more.json").write_text(
        '[{"id":"C3","npi":"0123456789","ndc":"00054027225","quantity":1,'
        '"price":1.0,"timestamp":"2026-02-01T10:00:00"}]'
    )
    pharmacy_dirs, claim_dirs, revert_dirs = dirs.args

    result = ingest(pharmacy_dirs, [*claim_dirs, str(tmp_path / "claims-2")], revert_dirs)

    assert sorted(c.id for c in result.claims) == ["C1", "C2", "C3"]


def test_an_empty_directory_is_not_an_error(dirs):
    result = ingest(*dirs.args)

    assert result.claims == ()
    assert result.counts.balances()


def test_every_record_is_accounted_for(dirs):
    dirs.claims(
        [valid_claim_record(id=f"OK{i}") for i in range(10)]
        + [valid_claim_record(id=f"BAD{i}", quantity=...) for i in range(2)]
        + [valid_claim_record(id=f"OUT{i}", npi="9999999999") for i in range(3)]
    )

    counts = ingest(*dirs.args).counts

    assert counts.read == 15
    assert (counts.accepted, counts.rejected, counts.excluded) == (10, 2, 3)
    assert counts.balances()


def test_exclusions_do_not_move_the_reject_rate(dirs):
    """Being out of scope is not a defect, so it can never trip the threshold."""
    dirs.claims(
        [valid_claim_record(id="OK")]
        + [valid_claim_record(id=f"OUT{i}", npi="9999999999") for i in range(99)]
    )

    assert ingest(*dirs.args).counts.reject_rate == 0.0


def test_reverts_are_validated_too(dirs):
    dirs.reverts(
        [
            {"id": "R1", "claim_id": "C1", "timestamp": "2026-02-02T09:00:00"},
            {"id": "R2", "timestamp": "2026-02-02T09:00:00"},
        ]
    )

    result = ingest(*dirs.args)

    assert [r.id for r in result.reverts] == ["R1"]
    assert _codes(result.rejected) == [reasons.missing_field("claim_id")]


def test_a_rejected_claims_id_is_remembered_so_its_reverts_can_be_diagnosed(dirs):
    dirs.claims([valid_claim_record(id="C-BAD", quantity=0)])

    assert ingest(*dirs.args).quarantined_claim_ids == frozenset({"C-BAD"})


# ------------------------------------------------------------ input digests --
def test_every_input_file_is_hashed_as_it_is_read(dirs):
    dirs.claims([valid_claim_record()])
    dirs.reverts([{"id": "R1", "claim_id": "C1", "timestamp": "2026-02-02T09:00:00"}])

    result = ingest(*dirs.args)

    assert len(result.inputs) == 3  # one pharmacy csv, one claims json, one reverts json
    assert all(len(f.sha256) == 64 for f in result.inputs)
    assert all(f.bytes > 0 for f in result.inputs)
    assert [f.path for f in result.inputs] == sorted(f.path for f in result.inputs)


def test_the_combined_digest_is_stable_across_runs(dirs):
    dirs.claims([valid_claim_record()])

    assert ingest(*dirs.args).inputs_digest == ingest(*dirs.args).inputs_digest


def test_the_combined_digest_changes_when_any_input_changes(dirs):
    dirs.claims([valid_claim_record(id="C1")])
    before = ingest(*dirs.args).inputs_digest

    dirs.claims([valid_claim_record(id="C2")])

    assert ingest(*dirs.args).inputs_digest != before


def test_an_unparseable_file_is_still_hashed(dirs):
    """Knowing exactly which bytes failed is the point of recording the digest."""
    dirs.claims("{not json", name="broken.json")

    result = ingest(*dirs.args)

    assert any(f.path.endswith("broken.json") for f in result.inputs)
