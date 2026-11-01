# noesis developer and playground commands. `make` alone lists them.
.DEFAULT_GOAL := help
ARGS ?= --help
MODE ?= dry-run

.PHONY: help init check lint format format-fix typecheck imports test cov clean \
        run install uninstall sandbox sandbox-hook sandbox-curate sandbox-env sandbox-clean

help: ## List targets
	@awk -F':.*## ' '/^[a-z-]+:.*## /{printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

## --- quality ----------------------------------------------------------------
init: ## Create the venv and install dev dependencies
	uv sync

check: lint format typecheck imports cov ## Everything CI runs

lint: ## Ruff lint
	uv run ruff check .

format: ## Ruff format check
	uv run ruff format --check .

format-fix: ## Apply ruff format and safe fixes
	uv run ruff format . && uv run ruff check --fix .

typecheck: ## mypy --strict
	uv run mypy

imports: ## Layer contracts (import-linter)
	uv run lint-imports

test: ## Tests without coverage
	uv run pytest -q

cov: ## Tests with the coverage gate
	uv run pytest -q --cov --cov-report=term-missing

clean: ## Remove caches and build output
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov dist

## --- run the CLI -----------------------------------------------------------
run: ## Run noesis from the source tree: make run ARGS="doctor --json"
	uv run noesis $(ARGS)

install: ## Install `noesis` on your PATH (editable: source edits apply at once)
	uv tool install --force --editable .

uninstall: ## Remove the `noesis` command from your PATH
	uv tool uninstall noesis

## --- playground (never touches your real config, vault, or Claude settings) --
sandbox: ## Create .sandbox/ with its own vault, state and config
	scripts/sandbox.sh init

sandbox-hook: ## Simulate a Claude Code commit + Stop hook: make sandbox-hook MODE=live|dry-run
	scripts/sandbox.sh hook $(MODE)

sandbox-curate: ## Run the real curator (haiku) on docs/examples/work-brief.json
	scripts/sandbox.sh curate

sandbox-env: ## Print the export line to point noesis at the sandbox
	@scripts/sandbox.sh shell

sandbox-clean: ## Delete .sandbox/
	scripts/sandbox.sh clean
