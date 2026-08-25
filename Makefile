# Commands referenced by the Definition of Done in CLAUDE.md.
# Every target named in README.md must exist here - scripts/check_docs_commands.sh enforces it.
.DEFAULT_GOAL := help
.PHONY: help setup lint typecheck test test-unit test-bdd test-system audit check run clean tree

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## Create .venv and install locked dependencies
	uv sync --all-groups

lint:  ## Ruff + architectural constraint lint (ADR-003)
	uv run ruff check src tests scripts
	uv run ruff format --check src tests scripts
	bash scripts/lint_architecture.sh
	bash scripts/check_docs_commands.sh
	bash scripts/check_fixture_integrity.sh

typecheck:  ## mypy strict
	uv run mypy

test-unit:  ## Deterministic tier - must be 100%, no IO, no network (ADR-004)
	uv run pytest tests/unit -m "not system"

test-bdd:  ## Gherkin acceptance scenarios (ADR-004)
	uv run pytest tests/bdd -m "not system"

test-system:  ## System-behavior tier - real files, baseline-gated, NOT a merge gate
	uv run pytest tests/system -m system

test: test-unit test-bdd  ## Deterministic tiers only (the merge gate)

audit:  ## Dependency vulnerability audit (direct runtime deps are blocking; see AP-14)
	uv run pip-audit --strict || true

check: lint typecheck test  ## Everything the merge gate requires

run:  ## Run the pipeline CLI (see README for arguments)
	uv run hippo $(ARGS)

tree:  ## Show the repo layout, excluding sample data and caches
	@find . -not -path './.git/*' -not -path './data/sample-data/*' -not -path '*/__pycache__/*' -not -path './.venv/*' | sort

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage build dist out
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
