"""Shared fixtures for the deterministic tier."""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from hippo_pipeline.domain.models import Claim, Pharmacy, Revert
from hippo_pipeline.metrics import registry


def at(text: str) -> datetime:
    """A UTC timestamp, written the way the source writes it."""
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def claim(
    claim_id: str,
    *,
    npi: str = "0123456789",
    ndc: str = "00054027225",
    price: str = "10.00",
    quantity: str = "5",
    ts: str = "2026-02-01T10:00:00",
) -> Claim:
    return Claim(
        id=claim_id,
        npi=npi,
        ndc=ndc,
        price=Decimal(price),
        quantity=Decimal(quantity),
        timestamp=at(ts),
    )


def revert(revert_id: str, claim_id: str, ts: str, index: int = 0) -> Revert:
    return Revert(
        id=revert_id,
        claim_id=claim_id,
        timestamp=at(ts),
        source_file="reverts.json",
        record_index=index,
    )


@pytest.fixture
def pharmacies() -> dict[str, Pharmacy]:
    return {
        "0123456789": Pharmacy(npi="0123456789", chain="saint"),
        "3333333333": Pharmacy(npi="3333333333", chain="health"),
    }


@pytest.fixture
def dirs(tmp_path):
    """Three input directories, and helpers to drop files into them."""

    class Dirs:
        def __init__(self):
            for name in ("pharmacies", "claims", "reverts"):
                (tmp_path / name).mkdir()

        @property
        def args(self):
            return (
                [str(tmp_path / "pharmacies")],
                [str(tmp_path / "claims")],
                [str(tmp_path / "reverts")],
            )

        def pharmacy_csv(
            self, text="chain,npi\nsaint,0123456789\nhealth,3333333333\n", name="pharmacies.csv"
        ):
            (tmp_path / "pharmacies" / name).write_text(text)
            return self

        def claims(self, records, name="claims-a.json"):
            (tmp_path / "claims" / name).write_text(
                records if isinstance(records, str) else json.dumps(records)
            )
            return self

        def reverts(self, records, name="reverts-a.json"):
            (tmp_path / "reverts" / name).write_text(
                records if isinstance(records, str) else json.dumps(records)
            )
            return self

    return Dirs().pharmacy_csv()


def valid_claim_record(**overrides):
    record = {
        "id": "C1",
        "npi": "0123456789",
        "ndc": "00054027225",
        "quantity": 5,
        "price": 10.0,
        "timestamp": "2026-02-01T10:00:00",
    }
    record.update(overrides)
    return {k: v for k, v in record.items() if v is not ...}


@pytest.fixture(autouse=True)
def _isolate_registry():
    """The registry is module-global. Restore it so tests cannot leak into each other."""
    saved = dict(registry._REGISTRY)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
