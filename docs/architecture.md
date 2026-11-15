# Architecture

This page describes the running implementation. The
[knowledge and memory direction](design/knowledge-memory-direction.md) records the verified
gaps, full capability map and proposed Neo4j/Vectra alternatives. Those storage ownership
choices remain open. [ADR-0002](adr/0002-recall-record-identity.md) describes the implemented
first step: recall preserves stable record IDs through resolution and citation checking.

noesis follows tactical DDD with a strict hexagonal (ports and adapters) layout, in the
context-first topology described in ADR-0001. For what each command does step by step, see
[workflows/](workflows/README.md); for each command's options and output, see
[commands/](commands/README.md).

Project-wide rules, one section each, are in [architecture-rules.md](architecture-rules.md).

```text
src/noesis/
  core/            settings (pydantic-settings, one AppBaseSettings policy) and env loading
  exceptions/      AppException tree, error codes, exit codes
  shared_kernel/   entity/aggregate/value-object/event/specification bases, IHandler,
                   IUnitOfWork, IClock, BaseDto, shared adapters, published contracts
                   (`contracts/<publisher>/`), the shared Neo4j client
                   (`infrastructure/outbound/neo4j/`)
  bounded_context/
    capture/       sessions, commits, gating, work briefs, agent hooks (see below)
    notes/         notes, curation, storage (see below)
    knowledge/     records, spaces, projects, revisions, Neo4j record store (see below)
      domain/          aggregates, value objects, events, repository ports
      application/     handlers, DTOs, ports (unit of work, ledger, schema, read, ids), services
      infrastructure/  outbound/persistence (Neo4j adapters, mappers), outbound/ids
  diagnostics/     host-level checks behind `noesis doctor` (not a bounded context, not kernel)
    application/     RunDiagnosticsHandler, CheckForUpdateHandler, assess_update (policy),
                     IEnvironmentProbe, ICheckoutInspector, DiagnosticReportDto, UpdateCheckDto
    infrastructure/  SystemEnvironmentProbeAdapter, GitCheckoutInspectorAdapter
  interfaces/cli/  Typer CLI: the composition root (`bootstrap/`, one `<context>_handlers_builder.py`
                   per context) and the only delivery adapter
```

Rules (enforced by import-linter, see `pyproject.toml`):

- Dependencies point inward: interfaces -> infrastructure -> application -> domain.
- Nothing below `interfaces` imports it (this includes `core`, `diagnostics` and the kernel).
- `diagnostics` knows no bounded context and no settings: the composition root hands it plain
  values (paths, binary name, installed hook events).
- The domain imports no delivery framework, no subprocess, no settings.
- Bounded contexts never import each other (`capture`, `knowledge`, `notes` are an independence
  contract); Capture hands Notes a versioned work-brief contract across a process boundary.
- `shared_kernel.contracts` imports no bounded context.
- The `neo4j` driver is imported only by infrastructure; no domain or application layer imports it.

Output contract of the CLI: `emit()` prints either text or the JSON envelope; deliberate
errors are `AppException`s with a stable `__error_code__`, an `__exit_code__`, and
`next_steps`.

## Knowledge context

`knowledge` is the new record store beside `notes` (ADR-0003). It is additive: Notes and Capture
are unchanged and later chunks move behaviour across. Notes model documents and paths; Knowledge
models records, revisions and spaces and keeps them in Neo4j.

```text
CaptureKnowledgeHandler / CaptureExperienceHandler            (`record capture`)
  ├─ IIdempotencyLedger.get(space, key)            read first: replay the result or reject a reused key
  ├─ ensure project (by key), ensure each Source (by natural key)   one unit of work each
  └─ IKnowledgeUnitOfWork: repository.add(new aggregate) + ledger entry + commit   one aggregate per transaction
ReviseKnowledgeHandler                                        (`record revise`)
  └─ IKnowledgeUnitOfWork: lock record, check status `proposed` and expected head, append revision n+1, ledger, commit
GetRecordHandler -> IRecordReadRepository.get_by_id(id, space_id)  (`record get`; another space's id is "not found")
InitialiseStoreHandler -> IStoreSchema.apply_step(...)        (`store init`)
```

| Piece | Where | Notes |
|---|---|---|
| Aggregates | `domain/entities/` | Seven roots, each with its own repository and transaction, referencing each other by id: `KnowledgeSpace`, `Project`, `Source` (write-once), `Knowledge` (immutable numbered revisions, status `proposed` at creation, revise only while `proposed`), `Experience` (write-once, at least one source), `Assertion` (a type only: storage arrives with a later chunk) and `CatalogEntry` (immutable numbered revisions, unique by `catalog_key`). |
| Ownership | `Knowledge.ownership` | `file`-owned revisions carry only the content hash, the file-version `Source` id and the title as read, never editable text; `graph`-owned revisions carry title and body (after redaction). Fixed at creation. |
| Value objects | `domain/value_objects/` | `RecordId` (ULID, unique across record types; existing frontmatter ULIDs accepted), `SpaceId`, `Key`, `Revision`, `ContentHash`, `Applicability`, `Tag`, `Actor`, `Slug`. |
| Domain events | `domain/events/` | Past tense, internal to the context; no outbox yet. |
| Repository ports | `domain/repositories/` | `IKnowledgeSpaceRepository`, `IProjectRepository`, `ISourceRepository`, `IKnowledgeRepository`, `IExperienceRepository`. |
| Unit of work | `application/ports/uow/IKnowledgeUnitOfWork` | One explicit transaction, explicit commit, rollback on exit without commit. Exposes `spaces`, `projects`, `sources`, `knowledge`, `experiences` and the ledger. Later chunks add members only. |
| Idempotency ledger | `application/ports/ledger/` | `IIdempotencyLedger` keeps one `LedgerEntry` per (space, key): command name (an open set), request fingerprint, record id, revision, extra result data. Same key and request replays the result without writing; same key and another request is `KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED`. Keys are kept indefinitely. |
| Read port | `application/ports/read_repositories/IRecordReadRepository` | `get_by_id`, `get_revision`, returning DTOs, within a space. |
| Schema steps | `application/ports/schema/IStoreSchema`, `services/schema_steps.py` | `store init` applies an ordered list of named, idempotent steps and records them in `:StoreMeta`; Knowledge registers `core`. A command may `require_steps(...)` and fails with `StoreNotInitialisedError` naming the missing step. There is no numeric schema version. |
| Services | `application/services/` | `SecretRedactor` (Knowledge's own), idempotency fingerprinting, `RecordReferenceResolver` (existence and same-space checks are made first in the handlers; the adapters re-check inside the write transaction as defence in depth). |
| Neo4j adapters | `knowledge/infrastructure/outbound/persistence/` | Unit of work, repositories, ledger, read repository and schema adapters with node mappers (spaces are nodes in one database). Only single-property uniqueness constraints (Community edition). Revise moves head n to n+1; the uniqueness constraint on the revision key is the concurrency guard. |
| Neo4j client | `shared_kernel/infrastructure/outbound/neo4j/` | `Neo4jClient` builds the async driver lazily per invocation, closes it when the command ends, and translates driver errors into typed ones; `Neo4jConnectionSettings` is its only input. Any context's adapters may use it. |
| Settings | `core/configurations/knowledge_settings.py` | `KnowledgeSettings`, read as `load_environment().knowledge`: `NOESIS_NEO4J_URI`, `NOESIS_NEO4J_USER`, `NOESIS_NEO4J_PASSWORD` (secret, user-side profile only), `NOESIS_NEO4J_DATABASE`, `NOESIS_NEO4J_CONNECT_TIMEOUT_SECONDS` (default 5), `NOESIS_KNOWLEDGE_SPACE` (default `personal`). `neo4j_connection()` builds the client's settings and names the variable when the password is missing. |
| CLI | `commands/record_commands.py`, `commands/store_commands.py`, `bootstrap/knowledge_handlers_builder.py`, `interfaces/cli/actor.py` | `open_knowledge` builds one `Neo4jClient` from `KnowledgeSettings.neo4j_connection()` per invocation (no connection until the first query), wires the handlers and closes the client when the command's `asyncio.run` ends. Usage errors (a missing `--idempotency-key`, source, title) are raised by the command before settings are loaded, so they exit 2 with no I/O. The actor is resolved in `interfaces/cli/actor.py` from `Environment.identity` and never from an option: any harness marker (`CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `AI_AGENT`, `CODEX_THREAD_ID`, `CODEX_SESSION_ID`, `NOESIS_SESSION_ID`) means `agent`, none means `user`. The marker variables are listed once, in `core/configurations/session_identity_settings.py`, which Capture's session chain also reads. |

**Fail closed.** When Neo4j cannot be reached, every store command fails with
`INTEGRATION_103_GRAPH_STORE_UNAVAILABLE` (exit 1, next steps), before any side effect and within
the connect timeout. There is no fallback, no partial result and no cached answer. The shared
client raises the same code for later retrieval. A wrong password is
`INTEGRATION_104_GRAPH_STORE_AUTHENTICATION_FAILED`. Driver exceptions are caught only in the
shared client.

**Extension points.** Later chunks extend Knowledge additively: new unit-of-work members, new
schema steps registered in the composition root, new error blocks, labels and edges. The names
below are reserved (a later chunk never changes the meaning of an existing member, label or code).

| Kind | Reserved | For |
|---|---|---|
| Unit-of-work members | `changes`; `assertions`, `record_references`; `catalog_entries` (used by the catalog); `link_sets`; `consolidations`, `consolidation_guard` | change feed; review; catalog; import links; consolidation |
| Labels | `:Change`, `:ChangeCounter`, `Index*` prefix | change feed and indexing |
| Labels | `:LinkSet` | file import |
| Labels | `:Decision` | review |
| Labels | `:Consolidation`, `:ConsolidationMembership` | consolidation |
| Edges | `LINKS_TO`, `EMBEDS` (import); `DECIDES` (review); `CONSOLIDATES`, `PRODUCED`, `OF` (consolidation); `SUBJECT`, `OBJECT`, `EVIDENCED_BY` (assertions) | - |
| Error blocks, `KNOWLEDGE` | 020-029 and 220-229 (review); x61-x69 (catalog: 061, 062, 261, 262 used); 14x and 24x (work briefs); x9x (consolidation) | C2's own codes stay outside these |

Other points: the ledger command name is an open set; a Source's observed time is set by
Knowledge's clock, never by the caller; `revise` locks the record node before checking status and
head; contracts for other contexts follow the [integration rule](architecture-rules.md).

## Notes context

```text
WorkBriefContract ──► CurateWorkBriefHandler                  (`notes curate`: judge, then apply)
                        ├─ WorkBriefMapper.to_domain(contract) -> WorkBrief      ACL into Notes' model
                        ├─ INoteReadRepository.search(brief.search_text())       related notes
                        ├─ ICurator.judge(brief, related)                        LLM judgment (retry once)
                        └─ ApplyCurationHandler.handle(scope, decisions, provenance)
                             ├─ AutoCurationPolicy.apply(decision, existing)     domain rules
                             └─ INotesUnitOfWork: notes.save(...) + commit       all or nothing
                      on repeated curator failure, or a storage failure (NoteStorageError):
                        IParkedCurationQueue.park -> `noesis notes retry`

drafts written by a person or an agent ──► ApplyCurationHandler      (`notes apply`: no curator)
                        scope = `repo:<git root name of the cwd>`; strict parse; `--dry-run` skips save + commit
                      on a rejected entry or a storage failure:
                        IApplyFailureLog.record(raw payload, errors) -> NOTES_203, kept for a second try
```

| Piece | Where | Notes |
|---|---|---|
| `Note` aggregate | `domain/entities/note.py` | Required sections per kind, canonical headings, `Not recorded` filler; manual notes cannot be revised by automation. |
| `WorkBrief` | `domain/value_objects/work_brief.py`, `application/mappers/` | Notes' own copy of the brief, translated from the contract by `WorkBriefMapper`; owns the rules on it (scope, search text, provenance). The contract stays data-only; the parked queue stores the contract so a retry re-enters through the command. |
| `NoteId`, `NoteScope`, `NoteKind`, `NotePath`, `NoteFrontmatter` | `domain/value_objects/` | Identity lives in the `noesis:` frontmatter block (ULID id, `repo:<name>`/`topic:<name>` scope, kind name, origin); `NotePath` is a free, safe relative path that carries no meaning. Kind membership is checked in the application against the manifest. |
| `Manifest`, `KindCatalog`, `NotePathResolver` | `application/services/manifest/` | The merged `noesis.yaml` (packaged default under `infrastructure/outbound/manifest/` plus the vault's own): sources (exactly one primary), layout templates for new notes, kinds with folder, description, sections and recall weight. `YamlManifestProviderAdapter` is the only loader. |
| `MultiSourceNoteReadRepositoryAdapter` | `infrastructure/outbound/storage/` | Fans recall out over the manifest's sources and fuses the rankings by note id (reciprocal rank, primary wins). Every source is an `INoteReadRepository`; a `vector` source is a `VectraNoteReadRepositoryAdapter` over its folder, wrapped in a fallback to those files. |
| `VectraCliClient` | `infrastructure/outbound/vectra/` | The only code that runs the `vectra` program (`search`, `sync`, `--json`). Raises `VectraClientError`; storage adapters decide what a failure means. |
| Vectra adapters | `infrastructure/outbound/storage/` | `VectraNoteReadRepositoryAdapter` searches a collection and resolves hit paths to notes through the files of the same folder (scope from frontmatter, hits over-fetched 3x). `VectraNoteRepositoryAdapter` + `VectraNotesUnitOfWorkAdapter` write files, then `vectra sync`; a failed sync keeps the files and is reported as a notice. Vectra stores chunks, not notes, so files stay the record. |
| `AutoCurationPolicy` | `domain/policies/` | Manual note on the same topic wins (`covered by <path>`); create/update both upsert the auto note. |
| `ClaudeCliCuratorAdapter` | `infrastructure/outbound/curation/` | `claude -p --output-format json --json-schema` with no tools, no settings, no saved session, a budget cap; prompt on stdin; reads `structured_output`. The system prompt holds the admission rule; the adapter receives it as text from the composition root (`build_curator`), which reads `NOESIS_CURATOR_SYSTEM_PROMPT_FILE` or falls back to the packaged `prompts/curator_system.md` (`default_system_prompt()`). |
| `ClaudeCliRecallAgentAdapter` | `infrastructure/outbound/recall/` | `IRecallAgent` for `notes recall`: `claude -p` with no tools, no MCP servers, no settings, no saved session, a budget cap; notes and task on stdin; reads `structured_output` (`recall_response_schema.py`). Packaged instructions in `prompts/recall_system.md`; `NOESIS_RECALL_MODEL` and `_EFFORT` go to the CLI verbatim; `build_recall_agent` picks the runtime. See [notes recall](workflows/notes-recall.md). |
| `apply_input_schema.py` | same folder | Strict reader of `notes apply` input. Reuses the curator's entry model but never downgrades: every flawed entry is reported with its index, and any one fails the call before anything is written. |
| `curator_response_schema.py` | same folder | Anti-corruption layer: pydantic schema sent to the CLI, translated into domain decisions; malformed entries become reported skips. |
| Filesystem adapters | `infrastructure/outbound/storage/` | Markdown + YAML frontmatter under `NOESIS_VAULT_DIR`; each file is written atomically, staged notes are written on commit (not all-or-nothing across files; a retry overwrites). Works for Obsidian vaults, plain folders and NFS (a mount). The default writer (`NOESIS_WRITER_BACKEND=filesystem`). |
| Search backend selection | `interfaces/cli/bootstrap/notes_handlers_builder.py` | `NOESIS_SEARCH_BACKEND` (`filesystem` default, or `vectra`) is chosen in `build_read_repository`; `FallbackNoteReadRepositoryAdapter` degrades the Vectra reader to the filesystem adapter on `NoteStorageError`. The curate handler shares the reader; `list` always reads files, and writes follow `NOESIS_WRITER_BACKEND`, not the search backend. A configuration naming a removed value fails with `RemovedBackendError` (`CORE_006`) at settings validation. See [notes workflow](workflows/notes.md#search-backend). |
| Failure log | `infrastructure/outbound/failures/` | `JsonFileApplyFailureLogAdapter`: for each failed `notes apply`, `<state>/notes/apply-failed/<ticket>.json` (report) and `<ticket>.payload.json|txt` (the input, verbatim, ready to re-apply). Failures never park a brief: only `curate` parks. |
| Parked queue | `infrastructure/outbound/queue/` | One JSON file per failed brief under `$NOESIS_STATE_DIR/notes/parked/`. A brief is parked when the curator keeps failing and when storing the notes fails (`NoteStorageError`); both surface as `NOTES_201`. |

### Writer backend

`NOESIS_WRITER_BACKEND` (`filesystem` default, or `vectra`) chooses where curated notes are stored.
Rules, recorded here and in ADR-0001 Amendment 2 (R3, R7 and R9 were retired with the Obsidian MCP
backends, ADR-0001 Amendment 6):

- R1. The writer is chosen by a composition-root function (`build_unit_of_work_factory` in
  `interfaces/cli/bootstrap/notes_handlers_builder.py`, `match` + `assert_never`) from
  `NOESIS_WRITER_BACKEND`. There is no application-layer resolver.
- R2. `uow.notes` reads from the backend it writes (the manual-wins lookup sees the same notes the
  writer stores). Search, `list` and the curator's related notes follow `NOESIS_SEARCH_BACKEND`.
- R3. Retired (it governed the MCP writer's sessions).
- R4. Only `NoteStorageError` leaves a writer. `commit` is not atomic across notes and is
  convergent on retry; the error lists the `written` and `not_written` paths.
- R5. A storage failure parks the brief and fails with `NOTES_201`; `--no-park` keeps
  `NOTES_102`. `notes retry` keeps the ticket when storage fails again.
- R6. A vault is required where files are used (`needs_vault`: writer or search is
  `filesystem` or `vectra`, which is every remaining backend). `notes list` always needs it.
- R7. Retired (it governed the MCP client builder and its token).
- R8. `NoteMapper` is the single note renderer/parser, in infrastructure
  `storage/mappers/`; every writer and reader uses it.
- R9. Retired (the doctor no longer writes a probe file).

Tuning the curator: read the `skipped` list of `noesis notes curate --json`, copy
`prompts/curator_system.md` to a file of your own, edit it, and point
`NOESIS_CURATOR_SYSTEM_PROMPT_FILE` at it (an installed package is overwritten on upgrade).
An unreadable or empty file fails with `CORE_005_CURATOR_PROMPT_UNREADABLE`. Storage and
validation do not change.

## Capture context

```text
Claude Code hook JSON ─► infrastructure/inbound/claude_code (ACL: payload -> command)
   PostToolUse git commit ─► RecordCommitHandler   (lock session, scan worktree HEADs, mark pending)
   every capture command  ─► ResolveSessionIdentityHandler (stored id; a pure query, the repo is registered by enable and record-commit) first
   Stop / SessionEnd      ─► FlushCaptureHandler   (lock session, rules, brief, publish)

FlushCaptureHandler, cheapest check first:
   opted in? ─ pending? ─ outside debounce? ─ significant (summed)? ─ transcript has real work?
   └─► WorkBriefContract ─► IWorkBriefPublisherFactory.for_mode(session.mode)
          live:    DetachedProcess…Adapter  -> `python -m noesis notes curate --brief-file … --json`
          dry-run: DryRun…Adapter           -> brief file only
```

| Piece | Where | Notes |
|---|---|---|
| `CaptureSession` aggregate | `domain/entities/` | Opt-in + mode, pending commits (one repository per batch), transcript cursor, failed hand-overs (retry once, then abandon; abandon at once at session end). |
| Specifications | `domain/specifications/` | `PendingWork`, `OutsideDebounce` (ignored by the final flush), `SignificantChange` (summed size; type irrelevant), `NewCommitCandidate` (a worktree HEAD that moved since the baseline, committed within 120 s). |
| Identity | `domain/value_objects/`, `domain/services/` | `RepoId` (`<main folder>-<8 hex>`), `SessionIdGenerator` (idempotent, repo-salted sha256), `WorktreeHead`. `IVcsReader.common_dir/worktrees`, `ISessionIdentitySource` (chain: harness sources, then `NOESIS_SESSION_ID`, else a fresh uuid4), write-only `IRepoRegistry` (`repos.json`), `ICaptureSessionTreeReader` (parent links). The repository naming rule has one owner, `core/git_root.py`, injected into the git adapter. |
| Unit of work | `infrastructure/outbound/persistence/` | One JSON file per session, held under an `flock` while open, so concurrent hooks of a session take turns. |
| Transcript reader | `infrastructure/outbound/transcript/` | Claude Code JSONL: real work = Edit/Write or `git commit` (quote-aware); excerpt = prompts and prose only, 4 KB. |
| Publishers | `infrastructure/outbound/publishing/` | Live spawns the curator with `os.posix_spawn(setsid=True)` and returns at once; the child writes `<brief>.result.json`. |
| Journal | `infrastructure/outbound/journal/` | `<state>/capture/journal/<session>.jsonl`; `noesis capture runs` shows it with the curation results. |
| Hook ACL | `infrastructure/inbound/claude_code/` | `ClaudeCodeHookPayload` (tolerant model of the hook JSON) and `route()`, which returns a `RecordCommitCommand` or `FlushCaptureCommand`, or None for irrelevant events. |
| Agent hook registry | `application/ports/agent_hooks/`, `infrastructure/outbound/agent_hooks/` | `IAgentHookRegistry` (`status`, `plan`, `apply`) and `ClaudeCodeSettingsAdapter`; see the next section. |

Capture and Notes never import each other (import-linter "independence" contract);
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
| `noesis doctor` | `commands/doctor_commands.py`, `noesis/diagnostics/` | `bootstrap.run_diagnostics` builds a `RunDiagnosticsQuery` of primitives (env file, vault dir, state dir, curator binary, installed hook events from `GetAgentHooksStatusQuery`, and whether a vault is required); `RunDiagnosticsHandler` applies the rules through `IEnvironmentProbe`; `format_report` renders the text. An unreadable agent settings file becomes a failed `claude_code_hooks` check. The `graph_store` check (after `search_backend`; `IGraphStoreProbe` over the shared Neo4j client, built only when `NOESIS_NEO4J_PASSWORD` is set) reports reachability and the applied schema steps against the names the composition root passes from `registered_schema_step_names()`: unreachable, rejected credentials or a missing step fail it, an unset password is a warning, so existing exit codes hold. The `writer` check sits between `claude_code_hooks` and `search_backend`: it reports the filesystem writer and makes no write; `search_backend` reports `filesystem`. The `vault` check fails on an unset vault only when one is required. The last check, `update`, is warn-only (always `ok`, so the exit code is unchanged; `warning: true` and a `warn` line, with the fix command as next step when there is one, for every verdict except `up_to_date`); it uses the same handler as `noesis update check` with a 3 s budget. |
| `noesis update check` | `commands/update_commands.py`, `noesis/diagnostics/` | `bootstrap.run_update_check` hands the installed package folder to `CheckForUpdateHandler`; `ICheckoutInspector` (`GitCheckoutInspectorAdapter`, `git` through asyncio subprocesses, 15 s budget, never raises) returns a `CheckoutSnapshot`, and the pure `assess_update` picks `up_to_date`, `behind`, `ahead`, `diverged` or `unknown`. Exit 0 for every verdict. When origin's commit is not in the local object store the adapter fetches objects only (`--no-write-fetch-head --refmap=`: no refs, no worktree change) to compare histories; see ADR-0001 Amendment 4. |
| `noesis config init` | `commands/config_commands.py`, `core/env_template.py` | `write_env_file` renders the template and writes the file; the command decides whether overwriting is allowed. |
| `noesis skills get` | `commands/skills_commands.py`, `skill_guides/*.md` (repository root) | Version-matched agent guide packaged with the CLI. |
| Skill stub | `skills/noesis/SKILL.md` | Installed with `npx skills add`; only resolves the CLI and loads the guide, so it never goes stale. |
