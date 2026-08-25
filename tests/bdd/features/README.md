# Gherkin acceptance scenarios

One `.feature` file per feature in `memory/features/`. Written **before** the
implementation (GENERAL_ENGINEERING_PLAYBOOK.md 1.6) and bound to step definitions in
`tests/bdd/` via pytest-bdd.

| Feature | Scenarios | Steps |
|---|---|---|
| `ingestion.feature` | 17 | `../test_ingestion.py` |
| `revert_resolution.feature` | 11 | `../test_revert_resolution.py` |
| `metric_registry.feature` | 13 | `../test_metric_registry.py` |

The step definitions drive the real gateway, the real resolver and the real registry. A
BDD suite that exercises stand-ins tests a different program.

`scripts/check_gherkin.py` parses every file here in `make lint` and CI, so a malformed
feature file fails at spec time rather than when someone tries to bind steps to it.
