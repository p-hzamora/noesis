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
sandbox: ## Create the sandbox git repo (.sandbox/, or FILE=/new/path): make sandbox FILE=~/tmp/noesis-test
	scripts/sandbox.sh init $(if $(FILE),--file "$(FILE)")

sandbox-hook: ## Simulate a Claude Code commit + Stop hook: make sandbox-hook MODE=live|dry-run
	scripts/sandbox.sh hook $(MODE) $(if $(FILE),--file "$(FILE)")

sandbox-curate: ## Run the real curator (haiku) on docs/examples/work-brief.json
	scripts/sandbox.sh curate $(if $(FILE),--file "$(FILE)")

sandbox-env: ## Print the export line to point noesis at the sandbox (FILE=… as above)
	@scripts/sandbox.sh shell $(if $(FILE),--file "$(FILE)")

sandbox-clean: ## Delete the sandbox (FILE=… as above; refuses non-sandbox dirs)
	scripts/sandbox.sh clean $(if $(FILE),--file "$(FILE)")
