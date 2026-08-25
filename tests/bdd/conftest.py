"""Shared machinery for the acceptance tier.

The step definitions drive the real gateway, the real resolver and the real CLI. A BDD
suite that exercises stand-ins tests a different program.
"""

import json

import pytest


@pytest.fixture
def context():
    """One mutable bag per scenario. Steps put things in it; assertions take them out."""
    return {}


@pytest.fixture
def workspace(tmp_path):
    """Input directories plus the helpers the steps need to populate them."""

    class Workspace:
        def __init__(self):
            self.root = tmp_path
            self.pharmacies = tmp_path / "pharmacies"
            self.claims = tmp_path / "claims"
            self.reverts = tmp_path / "reverts"
            for d in (self.pharmacies, self.claims, self.reverts):
                d.mkdir()
            self.pharmacy_rows = []
            self.claim_dirs = [str(self.claims)]
            self.max_reject_rate = 1.0
            self._counter = 0

        def next_id(self):
            self._counter += 1
            return f"C{self._counter}"

        def add_pharmacy(self, npi, chain):
            self.pharmacy_rows.append((chain, npi))
            text = "chain,npi\n" + "".join(f"{c},{n}\n" for c, n in self.pharmacy_rows)
            (self.pharmacies / "pharmacies.csv").write_text(text)

        def write_claims(self, records, name="claims-a.json"):
            (self.claims / name).write_text(
                records if isinstance(records, str) else json.dumps(records)
            )

        def write_claims_raw(self, text, name):
            (self.claims / name).write_text(text)

        def add_claims_dir(self, name):
            target = self.root / name
            target.mkdir(exist_ok=True)
            self.claim_dirs.append(str(target))
            return target

        @property
        def in_scope_npi(self):
            return self.pharmacy_rows[0][1] if self.pharmacy_rows else "0123456789"

        def claim(self, **overrides):
            record = {
                "id": self.next_id(),
                "npi": self.in_scope_npi,
                "ndc": "00054027225",
                "quantity": 5,
                "price": 10.0,
                "timestamp": "2026-02-01T10:00:00",
            }
            record.update(overrides)
            return {k: v for k, v in record.items() if v is not ...}

    return Workspace()
