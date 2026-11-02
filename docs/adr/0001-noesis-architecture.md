# ADR-0001: noesis as a standalone, hexagonal tool

## Status

Accepted (2026-10-30).

## Context

The capture logic lived in a Claude Code plugin (`hook-vault-log` in claude-flow) and
leaned on a second plugin (`obsidian-vault`) whose agent both judged and wrote notes
through the Obsidian MCP. Plugins cannot ship Python dependencies, the vault location was
hard-coded, and storage was welded to Obsidian.

## Decision

- noesis is its own repository, installed as a tool with `uv tool install`.
- Two bounded contexts, Capture and Knowledge, plus a small shared kernel. They meet
  only through a versioned work-brief contract.
- The curator (an LLM) only judges and drafts; Python validates and writes through a
  storage port. Storage adapters: filesystem first (Obsidian vaults, plain folders, NFS).
- Async handlers with a local kernel that mirrors the shapes of the author's
  `ddd-contracts` library (`IHandler`, `IUnitOfWork`, `Entity`, `AggregateRoot`,
  `ValueObject`, `DomainEvent`), without depending on its private index.
- Pydantic is allowed in the domain for value objects (as in `ddd-contracts`).
- Errors declare `__exit_code__` instead of `__http_error__`: the CLI is the delivery
  adapter, and exit codes are its status codes.
- Settings: one `AppBaseSettings` policy, one `*Settings` class per concern, a single
  user-level `.env` (`~/.config/noesis/.env`) plus `NOESIS_*` variables. A `.env` in the
  current directory is deliberately not read, because hooks run inside arbitrary repositories.
- Agents learn the CLI through a thin installable skill stub that loads a version-matched
  guide from `noesis skills get`, the same pattern Orca uses.

## Consequences

- Users install a tool and run `noesis integrate claude-code install` instead of a plugin.
- The note rules live in noesis (curator prompt and domain invariants), not in a plugin skill.
- The claude-flow plugins are retired in a separate, explicitly approved step.

## Amendment 1 (2026-10-31): where integration and diagnostics code lives

A review found delivery-adjacent logic inside `interfaces/cli`. It moved as follows.

- **Hook ACL is Capture inbound infrastructure.** The Claude Code hook payload model and
  the router that turns it into `RecordCommitCommand`/`FlushCaptureCommand` now live in
  `capture/infrastructure/inbound/claude_code/`. They translate a foreign format into
  Capture's own commands, which is what an anti-corruption layer is. The CLI command keeps
  only process concerns (recursion guard, stdin, exit 0, error log).
- **Agent hook registry port.** Editing the agent's settings file is behind
  `IAgentHookRegistry` (`status`, `plan`, `apply`), implemented by
  `ClaudeCodeSettingsAdapter`, with install, uninstall and status handlers in Capture. No
  unit of work: the settings file is not an aggregate. `integrate_commands.py` is now only
  argv, `--yes`, hook-command detection and formatting. The `CLAUDE_CONFIG_DIR` rule moved to
  `core/configurations/claude_code_settings.py`; the composition root injects the path because
  bounded contexts never import `noesis.core`.
- **Diagnostics is a host package.** `noesis/diagnostics/` holds the `doctor` checks as a
  use case with an `IEnvironmentProbe` port. It is neither a bounded context (it has no
  domain) nor shared kernel (it is not shared). It imports no Capture type: the composition
  root passes primitives, including the installed hook events obtained through Capture's
  status query. Import-linter keeps it below the interface layer, layered, and I/O-free in
  its application layer.
- **`config init` writes through core.** The env-file rendering and write moved to
  `core/env_template.py`.
- **`skill_guides/` lives at the repository root.** They are Markdown served by `noesis skills
  get`; they document the CLI surface but hold no code, so they sit beside `skills/` and
  `.env.example`. Wheels carry a copy inside the package (hatch `force-include`); a source
  checkout reads the root folder.
