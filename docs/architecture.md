# Architecture

noesis follows tactical DDD with a strict hexagonal (ports and adapters) layout, in the
context-first topology described in ADR-0001. For what each command does step by step, see
[workflows/](workflows/README.md).

```text
src/noesis/
  core/            settings (pydantic-settings, one AppBaseSettings policy) and env loading
  exceptions/      AppException tree, error codes, exit codes
  shared_kernel/   entity/aggregate/value-object/event/specification bases, IHandler,
                   IUnitOfWork, IClock, BaseDto, shared adapters, published contracts
  bounded_context/
    capture/       sessions, commits, gating, work briefs, agent hooks (see below)
    knowledge/     notes, curation, storage (see below)
  diagnostics/     host-level checks behind `noesis doctor` (not a bounded context, not kernel)
    application/     RunDiagnosticsHandler, IEnvironmentProbe, DiagnosticReportDto
    infrastructure/  SystemEnvironmentProbeAdapter
  interfaces/cli/  Typer CLI: the composition root (`bootstrap/`, one `<context>_handlers_builder.py`
                   per context) and the only delivery adapter
    skill_guides/    Markdown guides served by `noesis skills get` (documents the CLI surface)
```

Rules (enforced by import-linter, see `pyproject.toml`):

- Dependencies point inward: interfaces -> infrastructure -> application -> domain.
- Nothing below `interfaces` imports it (this includes `core`, `diagnostics` and the kernel).
- `diagnostics` knows no bounded context and no settings: the composition root hands it plain
  values (paths, binary name, installed hook events).
- The domain imports no delivery framework, no subprocess, no settings.
- Bounded contexts never import each other; Capture hands Knowledge a versioned work-brief
  contract across a process boundary.

Output contract of the CLI: `emit()` prints either text or the JSON envelope; deliberate
errors are `AppException`s with a stable `__error_code__`, an `__exit_code__`, and
`next_steps`.

## Knowledge context

```text
WorkBriefContract ──► CurateWorkBriefHandler
                        ├─ WorkBriefMapper.to_domain(contract) -> WorkBrief      ACL into Knowledge's model
                        ├─ INoteReadRepository.search(brief.search_text())       related notes
                        ├─ ICurator.curate(brief, related)                       LLM judgment (retry once)
                        ├─ AutoCurationPolicy.apply(decision, existing notes)    domain rules
                        └─ IKnowledgeUnitOfWork: notes.save(...) + commit        all or nothing
                      on repeated curator failure: IParkedCurationQueue.park -> `noesis knowledge retry`
```

| Piece | Where | Notes |
|---|---|---|
| `Note` aggregate | `domain/entities/note.py` | Required sections per kind, canonical headings, `Not recorded` filler; manual notes cannot be revised by automation. |
| `WorkBrief` | `domain/value_objects/work_brief.py`, `application/mappers/` | Knowledge's own copy of the brief, translated from the contract by `WorkBriefMapper`; owns the rules on it (area, search text, provenance). The contract stays data-only; the parked queue stores the contract so a retry re-enters through the command. |
| `NoteLocation` | `domain/value_objects/` | Auto: `<area>/auto/<kind>s/<slug>.md`; manual: `<area>/<kind>s/<slug>.md`. |
| `AutoCurationPolicy` | `domain/services/` | Manual note on the same topic wins (`covered by <path>`); create/update both upsert the auto note. |
| `ClaudeCliCuratorAdapter` | `infrastructure/outbound/curation/` | `claude -p --output-format json --json-schema` with no tools, no settings, no saved session, a budget cap; prompt on stdin; reads `structured_output`. The system prompt holds the admission rule; the adapter receives it as text from the composition root (`build_curator`), which reads `NOESIS_CURATOR_SYSTEM_PROMPT_FILE` or falls back to the packaged `prompts/curator_system.md` (`default_system_prompt()`). |
| `curator_response_schema.py` | same folder | Anti-corruption layer: pydantic schema sent to the CLI, translated into domain decisions; malformed entries become reported skips. |
| Filesystem adapters | `infrastructure/outbound/storage/` | Markdown + YAML frontmatter under `NOESIS_VAULT_DIR`; writes are staged and committed atomically. Works for Obsidian vaults, plain folders and NFS. |
| Obsidian MCP search | `infrastructure/outbound/storage/` | `ObsidianMcpNoteReadRepositoryAdapter` implements `INoteReadRepository` over the official `mcp` SDK (streamable HTTP, client in `shared_kernel/infrastructure/outbound/mcp/`); `FallbackNoteReadRepositoryAdapter` degrades to the filesystem adapter on `ObsidianMcpError`. Selected by `NOESIS_SEARCH_BACKEND` in `build_knowledge` (default `filesystem`: no MCP call). Read side only; the curate handler shares it (so related notes come from Obsidian too, with the same fallback); `list` and every write stay on files. See [knowledge workflow](workflows/knowledge.md#search-backend). |
| Parked queue | `infrastructure/outbound/queue/` | One JSON file per failed brief under `$NOESIS_STATE_DIR/knowledge/parked/`. |

Tuning the curator: read the `skipped` list of `noesis knowledge curate --json`, copy
`prompts/curator_system.md` to a file of your own, edit it, and point
`NOESIS_CURATOR_SYSTEM_PROMPT_FILE` at it (an installed package is overwritten on upgrade).
An unreadable or empty file fails with `CORE_005_CURATOR_PROMPT_UNREADABLE`. Storage and
validation do not change.

## Capture context

```text
Claude Code hook JSON ─► infrastructure/inbound/claude_code (ACL: payload -> command)
   PostToolUse git commit ─► RecordCommitHandler   (lock session, git HEAD, mark pending)
   Stop / SessionEnd      ─► FlushCaptureHandler   (lock session, rules, brief, publish)

FlushCaptureHandler, cheapest check first:
   opted in? ─ pending? ─ outside debounce? ─ significant (summed)? ─ transcript has real work?
   └─► WorkBriefContract ─► IWorkBriefPublisherFactory.for_mode(session.mode)
          live:    DetachedProcess…Adapter  -> `python -m noesis knowledge curate --brief-file … --json`
          dry-run: DryRun…Adapter           -> brief file only
```

| Piece | Where | Notes |
|---|---|---|
| `CaptureSession` aggregate | `domain/entities/` | Opt-in + mode, pending commits (one repository per batch), transcript cursor, failed hand-overs (retry once, then abandon; abandon at once at session end). |
| Specifications | `domain/specifications/` | `PendingWork`, `OutsideDebounce` (ignored by the final flush), `SignificantChange` (summed size; type irrelevant). |
| Unit of work | `infrastructure/outbound/persistence/` | One JSON file per session, held under an `flock` while open, so concurrent hooks of a session take turns. |
| Transcript reader | `infrastructure/outbound/transcript/` | Claude Code JSONL: real work = Edit/Write or `git commit` (quote-aware); excerpt = prompts and prose only, 4 KB. |
| Publishers | `infrastructure/outbound/publishing/` | Live spawns the curator with `os.posix_spawn(setsid=True)` and returns at once; the child writes `<brief>.result.json`. |
| Journal | `infrastructure/outbound/journal/` | `<state>/capture/journal/<session>.jsonl`; `noesis capture runs` shows it with the curation results. |
| Hook ACL | `infrastructure/inbound/claude_code/` | `ClaudeCodeHookPayload` (tolerant model of the hook JSON) and `route()`, which returns a `RecordCommitCommand` or `FlushCaptureCommand`, or None for irrelevant events. |
| Agent hook registry | `application/ports/agent_hooks/`, `infrastructure/outbound/agent_hooks/` | `IAgentHookRegistry` (`status`, `plan`, `apply`) and `ClaudeCodeSettingsAdapter`; see the next section. |

Capture and Knowledge never import each other (import-linter "independence" contract);
the work-brief contract in `shared_kernel/contracts/` is their only shared language.

## Integration with agents

```text
noesis integrate claude-code install|uninstall|status
   integrate_commands (argv, --yes, hook command detection, formatting)
     └─► Install/UninstallAgentHooksHandler, GetAgentHooksStatusHandler   (no unit of work)
           └─► IAgentHookRegistry.plan(command | None) -> AgentHookPlanDto (before/after, diff)
               IAgentHookRegistry.apply(plan)          -> backup path
                 └─► ClaudeCodeSettingsAdapter(settings_file): timestamped backup + atomic write
```

| Piece | Where | Notes |
|---|---|---|
| `noesis hook claude-code` | `interfaces/cli/commands/hook_commands.py` + Capture `infrastructure/inbound/claude_code/` | Inbound adapter. The CLI command keeps the process concerns: the `NOESIS_HOOK=1` guard (set for the curator's own run), reading stdin, exiting 0 always, the error log at `<state>/capture/hook-errors.log`, and dispatching to the handler. Payload model and router (the anti-corruption layer) live in Capture. |
| `noesis integrate claude-code` | `commands/integrate_commands.py`, Capture `application/handlers/` and `infrastructure/outbound/agent_hooks/` | Adds, removes, or reports the three hooks in Claude Code's settings. Preview by default, `--yes` writes after a timestamped backup; foreign hooks are never touched. The CLI does no file I/O. `claude_code_hook_settings.py` holds `HOOK_SPECS` and the pure `with_noesis`/`without_noesis`/`installed_commands` functions. |
| Settings location | `core/configurations/claude_code_settings.py` | `ClaudeCodeSettings.config_dir` (`CLAUDE_CONFIG_DIR`, default `~/.claude`); `settings_file` is `<config_dir>/settings.json`. Bounded contexts cannot import `noesis.core`, so `bootstrap.build_agent_hooks` injects the resolved path; `--settings` overrides it. |
| `noesis doctor` | `commands/doctor_commands.py`, `noesis/diagnostics/` | `bootstrap.run_diagnostics` builds a `RunDiagnosticsQuery` of primitives (env file, vault dir, state dir, curator binary, installed hook events from `GetAgentHooksStatusQuery`); `RunDiagnosticsHandler` applies the rules through `IEnvironmentProbe`; `format_report` renders the text. An unreadable agent settings file becomes a failed `claude_code_hooks` check. |
| `noesis config init` | `commands/config_commands.py`, `core/env_template.py` | `write_env_file` renders the template and writes the file; the command decides whether overwriting is allowed. |
| `noesis skills get` | `commands/skills_commands.py`, `skill_guides/*.md` | Version-matched agent guide packaged with the CLI. |
| Skill stub | `skills/noesis/SKILL.md` | Installed with `npx skills add`; only resolves the CLI and loads the guide, so it never goes stale. |
