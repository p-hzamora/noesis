# ADR-0001: noesis as a standalone, hexagonal tool

## Status

Accepted (2026-10-30).

Note (2026-11-11): the note layout described below (areas such as `repos/<repo>`, `auto/`
folders, `NoteArea`) is superseded. Notes are now identified by a `noesis:` frontmatter block,
not by their path, and their folders come from a manifest (`noesis.yaml`). The rest of this ADR is unchanged.

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

## Amendment 2 (2026-11-03): pluggable writer backend

`knowledge curate` always wrote notes as files, a storage failure lost the brief, and
`NOESIS_VAULT_DIR` was mandatory even when nothing local was used. The writer behind
`IKnowledgeUnitOfWork` is now selectable (issue #2). The domain, the application ports and the
curator are unchanged.

Decisions:

- **D-006** `WriterBackendEnum` (`filesystem` default, `mcp`) lives in `shared_kernel/enums.py`,
  next to `SearchEngineEnum`; `NOESIS_WRITER_BACKEND` is the only new setting.
- **D-007** A composition-root function (`match` + `assert_never`) selects the unit of work; no
  application resolver. One `build_obsidian_mcp_client` builds the client for search, writer and
  doctor and is the only place that unwraps the token.
- **D-008** The MCP writer opens one session per operation, because `session()` relabels
  exceptions thrown into its body as "unreachable".
- **D-009** `ObsidianMcpToolError` (subtype of `ObsidianMcpError`) and `call_text` on the
  client: a tool refusal differs from a transport failure, and `vault_write` answers plain text.
- **D-010** `get` treats a tool error plus an absent name in the parent `vault_list` as "no such
  note"; a listed file that cannot be read is a storage error.
- **D-011** MCP pre-validation is render + non-blank; path rules stay in the domain value objects.
- **D-012** Only `NoteStorageError` is parked.
- **D-013** `needs_vault` is the single owner of the vault requirement; a vault-less read
  repository fails `list` lazily and has no MCP-to-files fallback.
- **D-014** `doctor` gets a `writer` check; on `mcp` it writes `noesis-doctor-probe.md`
  at the vault root, then deletes it.
- **D-015** `NoteMapper` stays in infrastructure `storage/mappers/` (it imports `yaml`), shared
  by every writer and reader.

Rules (also in `docs/architecture.md`, "Writer backend"):

- R1 The writer is chosen by a composition-root function from `NOESIS_WRITER_BACKEND`; no
  application resolver.
- R2 `uow.notes` reads from the backend it writes; search, list and related notes follow
  `NOESIS_SEARCH_BACKEND`.
- R3 The MCP writer uses one session per operation; `ObsidianMcpToolError` separates "tool said
  no" from "unreachable".
- R4 Only `NoteStorageError` leaves a writer; MCP commit = pre-validate, send sequentially, not
  atomic, convergent on retry.
- R5 A storage failure parks as `KNOWLEDGE_201`; `KNOWLEDGE_102` remains with `--no-park`; retry
  keeps the ticket on failure.
- R6 A vault is required only where files are used (`needs_vault`); `list` always needs it; no
  MCP fallback without a vault.
- R7 Search and writer share `NOESIS_OBSIDIAN_MCP_*` and one client builder that unwraps the
  secret.
- R8 `NoteMapper` is the single renderer, in infrastructure `storage/mappers/`.
- R9 The doctor writer probe writes `noesis-doctor-probe.md` at the vault root, then deletes it.

Behaviour change: a storage failure during `curate` now parks the brief and fails with
`KNOWLEDGE_201` (ticket and `knowledge retry` next step), including on the default filesystem
backend, where it used to fail with `KNOWLEDGE_102` and lose the brief. `--no-park` keeps
`KNOWLEDGE_102`. NFS stays the filesystem backend pointed at a mount; no separate backend.

## Amendment 3: per-repository profiles (supersedes the cwd `.env` rule)

Hooks and CLI calls ran with the default `~/.config/noesis/.env` unless the agent remembered
`--env-file`, so a fresh session with another model could silently lose the configuration in
use. The "a `.env` in the current directory is never read" rule above stays for `.env` files.
It no longer blocks a repository from selecting a profile.

Decisions:

- R1 A repository selects its profile with `.noesis-config` at its root, one line:
  `profile = <name>`. That is the only key allowed; any other line is an error.
- R2 Profiles live outside the repository, in `~/.config/noesis/profiles/<repo>/<name>.env`,
  one folder per repository (`<repo>` is the repository's folder name). Secrets and executable
  or file-path settings (`NOESIS_CURATOR_CLAUDE_BIN`, `NOESIS_CURATOR_SYSTEM_PROMPT_FILE`,
  `NOESIS_OBSIDIAN_MCP_TOKEN`) are only ever read from a user-side profile, so a cloned
  repository cannot run a binary, read a file or send a token through its own files.
- R3 The `.noesis-config` search starts at the working directory and stops at the first
  directory that contains `.git`; a parent repository's file is never used.
- R4 Precedence: `--env-file`, then the repository profile, then the default
  `~/.config/noesis/.env`. Environment variables still override every file. The `NOESIS_ENV_FILE`
  variable is removed: a shell-wide default would silently override every repository profile.
- R5 A missing profile file is not an error (same as a missing `.env`); `config show` reports the
  resolved `env_file`, so a wrong profile is visible.
- R6 The resolution lives in `core/repo_config.py` and is called only by `CliState.environment()`;
  the hook command keeps its explicit `--env-file` only when one was given at install time.

Consequences: a repository's metadata can grow beside `profile` later, in the same
`profiles/<repo>/` folder, without changing the repository file.

## Amendment 4 (2026-11-05): update check

A noesis installed with `uv tool install` from a checkout silently falls behind its origin. The
user needs a way to see that, and `doctor` is where they already look.

Decisions:

- R1 No new context. The check lives in `noesis/diagnostics/` (Amendment 1): it reads the host,
  not notes or sessions. `CheckForUpdateHandler` and the pure `assess_update` policy are
  application code; the verdict is `UpdateVerdictEnum` (`up_to_date`, `behind`, `ahead`,
  `diverged`, `unknown`).
- R2 The port is `ICheckoutInspector.inspect(package_dir) -> CheckoutSnapshot`, in
  `diagnostics/application/ports/updates/`. Its adapter, `GitCheckoutInspectorAdapter`, runs the
  `git` executable with `asyncio` subprocesses and never raises: a missing checkout, no
  `origin`, an unreachable origin or a timeout leave snapshot fields as None, and the verdict is
  `unknown` with a named reason. The package folder only counts as a checkout when it is the
  `src/noesis` of the repository root, so a package inside an unrelated repository's `.venv` is
  not mistaken for one.
- R3 `noesis update check [--json]` always exits 0, whatever the verdict. For `behind` and
  `diverged` it prints `git -C <checkout> pull` and `uv tool install --reinstall <checkout>`.
- R4 `doctor` gets a warn-only `update` check: it is always `ok`, so the doctor exit code does
  not change, and it renders `warn` (JSON: `warning: true`) for `behind`, `ahead`, `diverged` and
  `unknown`, with the fix command as next step where one exists (`behind`, `diverged`); only
  `up_to_date` renders as a plain `ok`.
- R5 Telling `behind`, `ahead` and `diverged` apart needs origin's commit in the local object
  store. When it is missing after `git ls-remote --symref origin HEAD`, the adapter runs
  `git fetch --quiet --no-tags --no-write-fetch-head --refmap= origin <default-branch>` and then
  `git merge-base --is-ancestor` in both directions. The fetch only adds objects: HEAD, the
  working tree, `FETCH_HEAD` and every ref (the empty `--refmap=` stops git from also moving
  `refs/remotes/origin/*`) stay as they were. If the fetch fails or times out the verdict is
  `unknown`, never a guess. The strictly read-only alternative would report `unknown` in the most
  common `behind` case, so it was rejected.
- R6 Time budgets are constants in `bootstrap/diagnostics_handlers_builder.py`: 15 s for
  `update check` and 3 s for `doctor`. They cover the whole inspection, network included. There
  is no setting for them.

Consequences: `doctor` makes one short network call to origin when run from a checkout; outside a
checkout it makes none. The user's own git configuration (credentials, URL rewrites) decides
whether origin is reachable, and prompts are disabled (`GIT_TERMINAL_PROMPT=0`).

## Amendment 5 (2026-11-05): `notes`, and a store step of its own

`knowledge curate` was the only writer, and "curate" named both the whole flow and the model
step. The store step is now separate and reachable without a model, and the context is renamed
for what it owns: a note from its creation through validation to storing it or not.

Decisions:

- **D-016** The bounded context, package, CLI group, builder (`build_notes`), settings key and
  glossary term `Knowledge` become `Notes` / `notes`. No alias, no migration.
- **D-017** Error codes `KNOWLEDGE_xxx` become `NOTES_xxx` (same numbers), the state folder
  `<state>/knowledge/` becomes `<state>/notes/`, and `config show` reports `settings.notes`.
  Anything that branched on the old codes, read the old key, or kept parked tickets under the
  old folder must be updated or discarded.
- **D-018** `ICurator.curate` is `ICurator.judge`: the curator only judges and drafts.
  `notes curate` keeps its name and means judge + apply.
- **D-019** `ApplyCurationHandler` runs the auto-curation policy and the unit of work. It needs
  no brief and no model. `CurateWorkBriefHandler` calls it, so curate's behaviour, parking and
  `notes retry` are unchanged.
- **D-020** `noesis notes apply --decisions-file F|-` stores drafts written by a person or an
  agent. The area is the git root of the working directory (`repos/<repo>`); there is no
  `--path` or `--area`, so the scaffold and the manual-wins rule cannot be bypassed. Outside a
  git repository it fails with `INTERFACE_002_NOT_IN_GIT_REPOSITORY` (exit 2). Provenance
  (`--session`, `--commit`) is optional.
- **D-021** `apply` reuses the curator's entry model but is strict (`apply_input_schema.py`): any
  malformed entry fails the whole call before anything is written.
- **D-022** `apply` never parks briefs. A rejected payload or a storage failure is kept by
  `IApplyFailureLog` (`<state>/notes/apply-failed/<ticket>.json` plus the payload verbatim) and
  reported as `NOTES_203_APPLY_FAILED`; if the record cannot be written either, the payload is
  returned in the error. Re-applying the payload is the retry. A list or replay command is left
  for a later change.
- **D-023** `--dry-run` on `notes apply` and `notes curate` runs the policy against the existing
  notes and reports paths and outcomes without writing, parking or recording a failure.

Capture is unchanged except for the command string its detached publisher spawns (`notes
curate`). The hook entries in Claude Code's settings (`noesis ... hook claude-code`) are
untouched.
