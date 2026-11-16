# noesis: guide for agents

noesis captures finished work from agent sessions, lets a curator decide what is worth
keeping, and stores it as proposed records in the user's Neo4j knowledge store. This guide matches the
installed noesis version. Use `noesis <command> --help` for anything not covered here.

## Rules

- Always add `--json`. Parse the envelope: `{"ok": true, "result": ...}` or
  `{"ok": false, "error": {"code", "message", "next_steps"}}`. Branch on `error.code`;
  follow `next_steps` when the user agrees.
- Exit codes: 0 ok, 1 the operation failed, 2 invalid command line (a flag you can fix: a blank
  `--session` or `--parent`, a missing `--session`, `--parent` equal to the session, running
  outside a git repository).
- Never guess commands or flags. If something is not in this guide, run `--help`.
- To record something yourself, use `record capture` or `curate apply` (below); records start
  `proposed` and a person decides later. Never edit the store by other means.
- Costly or settings-changing commands (`curate brief`, `curate apply`, `integrate … --yes`)
  only when the user asked for them. `--dry-run` on both shows the result without writing.
- Recalling notes before a task (a briefing) is not available in this version; it returns with a
  later release. Use `noesis search` meanwhile.

## Which env file

The env file decides the state dir (where capture flags and the journal live), the store
connection and the capture thresholds. noesis picks it from the repository, so no flag is needed:

1. Look for `<repo>/.noesis-config` (the nearest one, up to the git root). It holds one line,
   `profile = <name>`. The profile file is
   `~/.config/noesis/profiles/<main repo folder name>/<name>.env`. In a linked git worktree
   the file is usually missing (it is gitignored), so noesis reads the main checkout's
   `.noesis-config` and uses the main checkout's folder name: a worktree and its main
   checkout share one profile.
2. If it exists, run noesis from inside that repo and do not pass any env flag. Every
   command, the Claude Code hooks included, then reads the same profile.
3. If there is no `.noesis-config`, noesis uses `~/.config/noesis/.env`. Tell the user the
   default is in use.
4. Pass `--env-file <path>` only when the user asks for a specific file. It is a global flag,
   so it goes before the subcommand: `noesis --env-file <path> capture on …`. It overrides
   the repository profile.

`NOESIS_ENV_FILE` no longer exists; do not set it. In the examples below, every command runs
from the repository, so no flag appears.

## Capture this session's work

Capture is off by default. When the user asks to record this session's work in the knowledge store:

```bash
noesis [--env-file <path>] capture on --session <SESSION_ID> --json            # live: curate into the store
noesis [--env-file <path>] capture on --session <SESSION_ID> --mode dry-run --json   # only store briefs
noesis [--env-file <path>] capture status --session <SESSION_ID> --json        # on/off, pending commits
noesis [--env-file <path>] capture runs --session <SESSION_ID> --json          # journal + curation results
noesis [--env-file <path>] capture off --session <SESSION_ID> --json
```

### The session id

noesis stores the session under its own id, `<repo>-<12 hex>`, derived from the id you give it
and from the repository, so the CLI and the hooks always agree. `result.session_id` of every
capture command is that stored id; passing it back as `--session` is stable.

- Claude Code: pass `${CLAUDE_SESSION_ID}`, as in the examples.
- Codex: leave `--session` out. noesis reads the Codex thread id (`CODEX_THREAD_ID`, then
  `CODEX_SESSION_ID`), which stays the same after `codex resume`, so every command finds the
  same session.
- A harness with no session id of its own: leave `--session` out of `capture on`. If
  `NOESIS_SESSION_ID` is exported noesis uses it; otherwise it starts a fresh session and prints
  its id in `result.session_id`. Pass that id as `--session` to every later command (`status`,
  `runs`, `off`); without one they fail with `CAPTURE_202_SESSION_ID_MISSING` (exit 2).
- `result.generated` is `true` when noesis had to choose the id itself (nothing was given and
  nothing was in the environment); it also prints a `warning:` on stderr. No hook can match a
  generated id, because the hooks only know the agent's own session id: the session would never
  be captured. Do not report success; run `capture on --session <the agent's session id>`
  instead (in Claude Code: `${CLAUDE_SESSION_ID}`). Use a generated id only on a harness that
  gives hooks nothing to match, and say so to the user.
- A blank value is never an id. `--session ""` or `--session "  "` (and a blank `--parent`)
  fails with `INTERFACE_003_BLANK_SESSION_ID` (exit 2) before anything is read or written; it is
  not replaced by the environment. A blank `NOESIS_SESSION_ID` or Codex variable counts as not
  set. Only a hook payload with a blank id reaches `CAPTURE_001_INVALID_SESSION_ID`, and hooks
  never fail the session.
- Capture commands work only inside a git repository: outside one they fail with
  `INTERFACE_002_NOT_IN_GIT_REPOSITORY` (exit 2), because the session is stored per repository.
- `capture on` is idempotent: a repeat call keeps the pending commits and the transcript
  cursor, keeps the mode unless you pass `--mode`, and changes nothing.
- A sub-agent gets its own session with `capture on --parent <PARENT_SESSION_ID> --json`. It
  keeps its own pending commits, inherits the parent's mode, and is never given the parent's
  id. `capture runs --session <PARENT_SESSION_ID> --children --json` merges its runs in; each
  run carries its `session_id`. The parent must be switched on (`CAPTURE_201_SESSION_NOT_FOUND`,
  exit 1, if not), must not be blank, and must not be the sub-agent's own session
  (`INTERFACE_004_SELF_PARENT_SESSION`, exit 2); the harness' own id is never used as the parent.
- After upgrading from a noesis that derived ids differently, run `capture on` again in each
  session you want captured; sessions switched on by the older version are not found under the
  new ids (their old state stays where it is).

### Worktrees

Every worktree of a repository is one repository: commits made in a linked worktree are
captured (even when the hook reports the main checkout as the working directory), the brief
records the branch the commit was made on, and the records go to the main repository's project,
`<main repo folder name>`. If two worktrees committed within two minutes and the command
does not say which one, noesis records neither and `capture runs` shows `ambiguous_worktree`:
tell the user, and have them commit again.

After `capture on`, always verify before you report success:

1. Run `capture status` with the same `--env-file` (or none, if you used none).
2. Check that `result.enabled` is `true`. If it is not, say that capture is not on and
   stop. Do not tell the user that capture is on.
3. Check `result.generated` of the `capture on` call you made (every capture command has the
   field; `status` reports `false` because it never generates one). If it is `true`, the id was
   invented, no hook can match it, and capture will not happen: say so, then run `capture on`
   again with the agent's own `--session`. Do not tell the user that capture is on.
4. Tell the user which env file and state dir were used. `capture on` and
   `capture status` include them as `env_file` and `state_dir`.

Once on, nothing else is needed. After each `git commit` and at the end of each turn, the
Claude Code hooks hand finished work to the curator in the background. A change counts
when the pending commits together reach the size thresholds (`config show`, run with the
same env file). If `capture runs` shows `handed_over` without a result yet, the curator is
still running.

## Curate work into records

```bash
noesis curate brief --brief-file brief.json --dry-run --json    # the curator judges; nothing written
noesis curate apply --decisions-file draft.json --dry-run --json  # your own candidates; no curator
cat draft.json | noesis curate apply --decisions-file - --session <SESSION_ID> --commit <SHA> --json
```

`curate brief` calls a model, so run it only when the user asks (the capture hooks run it by
themselves). `curate apply` stores candidates you wrote, without the curator. Run it from inside
the repository: records go to the project of its name. Everything lands `proposed`; capture never
accepts. `--session` and `--commit` (repeatable) are provenance sources. The file is:

```json
{"candidates": [{
  "kind": "knowledge", "key": "ttl-cache", "title": "Use a TTL cache",
  "body": "Keep tokens in memory.", "subtype": "decision", "reason": "non-obvious choice"
}]}
```

Check `result.items`: each has an `ordinal`, an `outcome` (`recorded`, `proposed`, `revised`,
`successor_proposed`, `skipped`) and the `record_id`. Running the same work again writes nothing
new (`result.replayed`). Outside a git repository `apply` fails with
`INTERFACE_002_NOT_IN_GIT_REPOSITORY` (exit 2).

`apply` is strict: one flawed entry fails the whole call with `KNOWLEDGE_243_CURATION_REJECTED`
(exit 1) and writes nothing; the payload is kept, `error.metadata` lists each rejected entry.
Fix the entries and run `apply` again.

## The record store (Neo4j)

`record` and `store` keep structured records in a local Neo4j database, separate from the vault.
They need `NOESIS_NEO4J_PASSWORD` in the user's profile or environment; never put it in a file
inside a repository. Run from inside the repository: the record's project defaults to its name.

```bash
noesis store init --json                                  # once: applies schema steps, creates the default space
noesis record capture --type knowledge --title "<short>" --body "<text>" --subtype decision \
  --source commit:<full sha> --tag area:billing --idempotency-key <key> --json
noesis record capture --type experience --body "<what happened>" --subtype failure \
  --source agent_session:<id> --occurred <ISO time> --idempotency-key <key> --json
noesis record revise <ID> --expected-revision <N> --body "<new text>" --idempotency-key <key> --json
noesis record get <ID> [--revision <N>] --json
```

- `--idempotency-key` is required on every `record capture` and `record revise` (a missing one is
  exit 2 and nothing is touched). Make it deterministic from the work (for example
  `<session id>-<commit sha>-<slug>`), not random: a retry must repeat it. The same key and request
  returns the first record (`result.replayed: true`) without writing; the same key with another
  request fails with `KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED` (pick a new key only if you really
  changed the request).
- On `INTEGRATION_103_GRAPH_STORE_UNAVAILABLE` the outcome may be unknown
  (`error.metadata.commit_outcome: unknown`): retry with the same key; if the record exists you get
  it back, otherwise it is written once. Do not report the record as stored until a call succeeds.
  Never loop: tell the user to start Neo4j and run `noesis doctor`.
- At least one source is required: `--source <kind>:<locator>` (repeatable; kinds `commit` with the
  full sha, `agent_session`, `file_version` as `vault://<vault_key>/<path>`, `url`, `work_brief`) and
  `--source-id <ULID>` for a source already stored. `--body -` reads the text from stdin; the body
  is never read from stdin implicitly.
- The actor is set by noesis: `agent` when you run inside a harness, never a flag. Do not try to
  pass yourself off as the user.
- Knowledge is captured as `proposed`; a person decides later. `record revise` works on proposed
  knowledge only and needs `--expected-revision` (the head from `record get`):
  `KNOWLEDGE_202_REVISION_CONFLICT` means someone else revised it, so `record get`, re-apply, retry
  with a new key. Experiences cannot be revised (`KNOWLEDGE_207_RECORD_NOT_REVISABLE`).
- `noesis store init` is for a person or setup step, and only when `KNOWLEDGE_204_STORE_NOT_INITIALISED`
  says so (its `next_steps` name the command; run it if the user agrees). Its result lists
  `applied_steps`, `already_applied_steps` and the `default_space`; there is no schema version.
- Codes you may meet (all exit 1): `INTEGRATION_103` store unreachable, `INTEGRATION_104` wrong
  user or password (tell the user; do not retry), `INTEGRATION_105` busy (retry once with the same
  key), `INTEGRATION_106`/`INTEGRATION_107` store defects (report them), `KNOWLEDGE_201` unknown
  id or another space, `KNOWLEDGE_202` stale revision, `KNOWLEDGE_203` key reused,
  `KNOWLEDGE_204` store not initialised, `KNOWLEDGE_205` a `--source-id` not in the space,
  `KNOWLEDGE_207` not revisable, `KNOWLEDGE_208` space missing (`store init`).

## Search the record store

```text
noesis search <query> [--project <key> | --all-projects] [--tag <t>]... [--type knowledge|experience]...
                      [--status <s>]... [--limit 1..50] [--include-stale] [--require-semantic] [--json]
```

- Scope: the active space. Default project: the git repository you run it in (the same name
  `record capture` uses), plus space-wide records. `--project` names another one; `--all-projects`
  searches every project (not together with `--project`). Outside a repository, or for a project the
  space does not have, it searches space-wide records only and says so in `result.warnings`
  (`result.scope.space_wide_only: true`). Search never creates a project.
- Hits (`result.hits[]`, best first): `id`, `type`, `subtype`, `title`, `revision`, `status`,
  `authority`, `project`, `sources`, `revised_at`, `rank`. `authority` is a label, in this order:
  `authoritative`, `experience`, `proposed` / `unreviewed`, `superseded`, `retracted`. Retracted records
  are left out unless `--status retracted`. Treat only `authoritative` as settled; `proposed` is a
  proposal.
- `result.index`: `pending_changes`, `stale_hits`, `filter_shortfall` (fewer hits than `--limit`
  matched the filters) and `semantic.state` (`absent` today: only text and shared-source search run).
- Errors: `RETRIEVAL_101_SEMANTIC_INDEX_UNAVAILABLE` (`--require-semantic` while the state is `absent` or
  `unavailable`), `RETRIEVAL_202_INDEX_REBUILD_REQUIRED` (run `noesis index rebuild --yes`),
  `INTEGRATION_103_GRAPH_STORE_UNAVAILABLE` (Neo4j is down). An empty query, `--limit` outside 1..50, or
  `--project` with `--all-projects` is a usage error (exit 2).

## Index commands

`noesis index sync [--wait-seconds <n>]`, `noesis index rebuild [--projection <name>] --yes` and
`noesis index status [--verify]` keep search projections up to date. This release registers no
projection, so each one reports `projections: []`, the feed's `head_sequence` and a warning, writes
nothing and exits 0. `rebuild` without `--yes`, or naming an unregistered `--projection`, is a usage
error (exit 2). Normal use needs none of them: text search reads the record store directly.

## Assertions and review (Neo4j)

An assertion says how two records relate; every proposal waits in a queue for a decision. Both
need the `review` schema step (`noesis store init`; without it every command below exits 1 with
`KNOWLEDGE_204`, `metadata.missing_steps: ["review"]`).

```bash
noesis assertion propose --predicate supports|contradicts|supersedes|recommends \
  --subject <ID> --object <ID> [--evidence <ID>]... --rationale "<why>" \
  --source <kind>:<locator> [--project <key>] [--tag <tag>]... --idempotency-key <key> --json
noesis assertion list --about <ID> [--role subject|object|evidence|any] [--predicate <p>]... [--status <s>]... --json
noesis review queue [--project <key> | --global] [--type knowledge|assertion] [--predicate <p>] [--limit <n>, default 50] [--cursor <c>] --json
noesis review accept <ID> [--expected-revision <N>] [--reason "<why>"] [--yes --idempotency-key <key>] --json
noesis review retract <ID> --reason "<why>" [--yes --idempotency-key <key>] --json
noesis review log <ID> --json
noesis review repair [--yes] --json
```

- `assertion propose` is space-wide unless you pass `--project` (there is no git fallback here).
  It needs `--idempotency-key`, `--rationale` and at least one `--source`. Evidence ids are
  Experience, Knowledge or Source records. A `supersedes` is Knowledge over Knowledge or Assertion
  over Assertion, in one project; it may be proposed while its subject is still `proposed`.
- Without `--yes`, `review accept`, `review retract` and `review repair` only preview: they run
  every check, print the result with `applied: false` and write nothing. Accepting Knowledge needs
  `--expected-revision` (the head from `record get`); accepting an Assertion does not.
- What you may decide: an agent accepts, rejects or retracts only a record whose project is named
  (for `supersedes`, the same project on both ends), and accepts an assertion only with at least one
  evidence record. Everything space-wide is the user's. `review queue` shows `requires`
  (`user` or `agent_or_user`) and `decidable_by_caller` for each item; leave the others alone.
- Accepting a `supersedes` marks the object `superseded` (its `effective_status` reads that at once).
  If the process died in between, repeat the same accept (same key) or run `review repair --yes`.
  Nothing is deleted: `record get` still returns retracted and superseded records, and
  `review log` lists every decision with actor, basis and reason.
- Bulk accept: `noesis review accept --tag <tag> --all` previews the counts (`matched`, `proposed`,
  `skipped_not_proposed`) and a sample of up to 10 records, for any actor. Report them to the user.
  Only the user applies it (`--yes`, in their own terminal): an agent that adds `--yes` gets
  `KNOWLEDGE_022` before the store is touched, and so does an agent that tries to apply it by
  another route. It accepts Knowledge only, one record per transaction, with basis `migration`;
  a rerun finishes what an interruption left. It takes no `<ID>`, `--expected-revision` or
  `--idempotency-key`.
- The user's `--yes` on `review accept` or `review retract` (single or bulk) needs an interactive
  terminal on standard input; otherwise `INTERFACE_006_USER_PRESENCE_REQUIRED`. If you meet it, tell
  the user to run the command themselves; do not look for a way around it.
- Codes (all exit 1): `KNOWLEDGE_020` invalid assertion (`metadata.field` names what to fix; also an
  id that is not in the space), `KNOWLEDGE_021` transition not allowed from the current status
  (`record get`), `KNOWLEDGE_022` not yours to decide (ask the user), `KNOWLEDGE_023` an agent
  accept needs evidence (propose with `--evidence`), `KNOWLEDGE_220` another decision won (`review
  log`, re-evaluate), `KNOWLEDGE_221` the same statement is already live (`metadata.existing_id`),
  `KNOWLEDGE_222` an end is retracted, superseded or, for `supersedes`, not both accepted (accept
  the subject first), `KNOWLEDGE_223` Knowledge accept without `--expected-revision`,
  `KNOWLEDGE_224` the record has no status (an Experience, Source, Project), `INTERFACE_006` above.
  A usage error is exit 2. The same key with another request is `KNOWLEDGE_203`.

## The catalog (what you may use, and what is available now)

`catalog` keeps a record of capabilities (`skill`, `agent`, `cli_tool`, `mcp_server`) in the same
Neo4j store, and checks what is installed right now. A catalog entry never says a thing is available:
only `catalog check` does, for the runtime and machine it ran on.

```bash
noesis catalog register --kind skill --name <plugin>:<name> --purpose "<text>" --location <plugin@marketplace|url> \
  [--declared-version <v>] [--requires <kind>:<name>]... --source <kind>:<locator> --idempotency-key <key> --json
noesis catalog revise <ID|kind:name> --expected-revision <N> [--purpose ..] [--declared-version ..] [--requires ..] [--location ..] \
  --source <kind>:<locator> --idempotency-key <key> --json
noesis catalog list [--kind <kind>] [--name-prefix <text>] --json
noesis catalog show <ID|kind:name> [--revision <N>] --json
noesis catalog check [<ID|kind:name>...] [--kind <kind>] [--runtime claude-code|codex]... --json
noesis catalog scan [--runtime claude-code|codex]... --json
```

- Before relying on a cataloged capability, run `catalog check` and use only what is `available`.
  `unknown` (`probe_failed`, `kind_not_probed`) means not verified; MCP servers are never probed.
  `unavailable` carries a `reason` (`not_installed`, `prerequisite_missing` with
  `missing_prerequisites`); `result.next_steps` names where to install it. `check` and `scan` exit 0
  even when things are unavailable: read the statuses. `version_drift: true` means the installed
  version differs from the declared one; the entry is still `available`.
- With no `--runtime`, the runtime of your session is used (Claude Code, Codex), else both are checked.
- `scan` lists what is installed but not cataloged, version drift and cataloged but not installed. It
  registers nothing: register entries yourself, with values you choose (never an install path in
  `--location`).
- Names are case-sensitive: letters, digits, `.`, `_`, `-`, `:` (`<plugin>:<name>` for plugin
  artifacts), at most 128 characters. `--requires` and refs split at the first colon.
- `register` and `revise` need `--source` (at least one) and `--idempotency-key`, like `record`.
  `revise` changes only the options you give (`--declared-version ""` clears the version, a lone `--requires ""`
  clears the prerequisites); revising with nothing different writes nothing and returns the head.
  An empty `--purpose` or `--location` is exit 2.
- Codes you may meet (all exit 1): `KNOWLEDGE_061` invalid name, `KNOWLEDGE_062` invalid
  prerequisite or ref, `KNOWLEDGE_261` unknown entry (or another space's), `KNOWLEDGE_262` entry
  exists (use `catalog revise`), plus `KNOWLEDGE_202`, `KNOWLEDGE_203`, `KNOWLEDGE_204` (run
  `noesis store init` to add the `catalog` step) and `INTEGRATION_103` as for `record`. When the store is
  unreachable nothing is probed and nothing is guessed: report that you could not check.

## Failed curations

```bash
noesis [--env-file <path>] curate parked --json            # tickets whose curation failed (works with the store down)
noesis [--env-file <path>] curate retry <TICKET> --json    # retry one, in the foreground
noesis [--env-file <path>] curate retry --all --json       # list what it would retry; add --yes to run
```

`curate brief --dry-run` runs the curator and shows what it would store, without writing and
without parking. A brief is parked when the curator keeps failing or the store cannot be written
(`KNOWLEDGE_241_CURATION_FAILED`, `ticket` in `error.metadata`). Follow its `next_steps`: fix
the cause (the curator `KNOWLEDGE_141`, Neo4j `INTEGRATION_103`, the related lookup
`KNOWLEDGE_245`: run `noesis index sync` or set `NOESIS_CURATOR_RELATED_LOOKUP=off`), then
`curate retry <TICKET>`. A retry resumes at the stage that failed and never writes a record twice.
Old Notes tickets (`<state>/notes/parked`) are not read: drain them with the previous version.

## Setup and diagnosis

```bash
noesis [--env-file <path>] doctor --json                       # state dir, git, curator CLI, hooks, graph_store (Neo4j reachable + schema steps; warn only without a password), update (warn only)
noesis [--env-file <path>] config show --json                  # effective settings and their file
noesis [--env-file <path>] config init [--vault-dir <folder>] # create the env file (default ~/.config/noesis/.env); the vault is read only by `import run`
noesis update check --json                             # behind / ahead / diverged / up_to_date / unknown vs origin; exit 0 always
noesis integrate claude-code status --json             # hooks in the user settings file only
noesis integrate claude-code install                   # preview; add --yes to write
```

`integrate claude-code status` and `doctor` inspect only the user settings file
(`~/.claude/settings.json`) by default. Project hooks in `<repo>/.claude/settings*.json`
are not included. To inspect a project file, pass
`integrate claude-code status --settings <repo>/.claude/settings.json`.

Common error codes: `CORE_002_VAULT_NOT_CONFIGURED` (`import run` needs `NOESIS_VAULT_DIR`; run `config init --vault-dir`),
`INTERFACE_003_BLANK_SESSION_ID` (a blank `--session` or `--parent`; exit 2),
`INTERFACE_004_SELF_PARENT_SESSION` (`--parent` is the session itself; exit 2),
`CAPTURE_001_INVALID_SESSION_ID` (a blank id that reached the domain, in practice a hook payload),
`CAPTURE_202_SESSION_ID_MISSING` (no `--session` and none in the environment, exit 2; run
`capture on` and pass back `result.session_id`),
`CAPTURE_201_SESSION_NOT_FOUND` (`--parent` names a session that was never switched on),
`KNOWLEDGE_241_CURATION_FAILED` (curation failed and the ticket is parked; see `curate parked`),
`KNOWLEDGE_243_CURATION_REJECTED` (`curate apply` rejected an entry; the payload was kept),
`INTERFACE_002_NOT_IN_GIT_REPOSITORY` (run `capture` and `curate apply` from inside the repository),
`INTEGRATION_101_AGENT_SETTINGS_INVALID` (the settings file is not valid JSON).

## Import a vault or a file into the record store

```bash
noesis [--env-file <path>] import run --json --verbose          # preview: reads NOESIS_VAULT_DIR, assesses, writes nothing
noesis [--env-file <path>] import run --yes --json              # apply
noesis [--env-file <path>] import run --yes --update --json     # also revise / supersede records whose note changed
noesis [--env-file <path>] import run --strict --json           # refuse (IMPORT_201) when any note is blocked
noesis [--env-file <path>] import file <path> [--title <text>] [--subtype <slug>] [--project <key>] [--tag <tag>]... [--dry-run] --json
```

`import run` previews unless `--yes` is given; `--verbose` adds one row per note (path order) to
`result.notes`. It needs `NOESIS_VAULT_DIR` (`CORE_002_VAULT_NOT_CONFIGURED` when unset) and the
store (`noesis store init` first, `KNOWLEDGE_204_STORE_NOT_INITIALISED` otherwise). Locators use
`vault://<vault_key>/<relative path>`; the key is `NOESIS_IMPORT_VAULT_KEY` or the vault folder
name (letters, digits, `.`, `_`, `-`; otherwise `CORE_001_INVALID_CONFIGURATION`). Files are only
read, never written. Every imported record is graph-owned, `proposed`, and tagged `origin:migrated`
(`import run`) or `origin:imported` (`import file`); the run is resumable and a rerun is safe.

Per-note `outcome`: `created`, `unchanged`, `changed_in_vault` (the note changed; add `--update` to
act on it), `revised` (a `proposed` record got a new revision), `successor_proposed` (an accepted
record's note changed; a new `proposed` record was linked to it), `skipped_empty` (nothing left
after normalisation, e.g. a links-only index), `blocked`. A note is blocked with `reason`
`not_text`, `invalid_header`, `invalid_id`, `duplicate_id`, `invalid_scope` (interop), or
`id_conflict`, `target_closed`, `revision_conflict`, `idempotency_key_reused`, `invalid_metadata`
(Knowledge, `detail` holds its code). A `successor_proposed` row names the accepted record
(`target_record_id`) and the `supersedes` assertion proposed between them (`assertion_id`); both wait
in `noesis review queue`. With blocked notes the run still exits 0 with `complete: false`; read the
`blocked_reasons` counts and the rows. Wiki links become their text, sections holding only links
are removed, code is left alone.

`import file` registers one file (anywhere on disk) by its resolved path; `--dry-run` shows the
outcome without writing. A header `id` is ignored, so a copy of a migrated note is a new record.
It fails with `IMPORT_102_FILE_READ_FAILED` (path missing, not a file, unreadable) or
`IMPORT_203_FILE_NOT_IMPORTABLE` (`metadata.reason`: `not_text`, `invalid_header`, `empty_body`, or a
Knowledge block reason such as `invalid_metadata` for a bad `--subtype`, `--project` or `--tag`).
Usage errors (exit 2): `import file` without a path, `--update` or `--strict` on `import file`,
`--dry-run` on `import run`.

Codes: `IMPORT_101_VAULT_READ_FAILED` (vault folder missing or a note unreadable; `metadata.path`),
`IMPORT_102_FILE_READ_FAILED`, `IMPORT_201_BLOCKING_FINDINGS` (`--strict` and a blocked note;
`metadata.blocked_reasons`, `metadata.paths`; nothing written), `IMPORT_203_FILE_NOT_IMPORTABLE`.

Next steps: a preview ends with the exact apply command; an apply with `changed_in_vault` notes lists
`noesis import run --yes --update`; with blocked notes, `noesis import run --verbose`. Accepting the
migrated records in bulk (`noesis review accept --tag origin:migrated --all --yes`) exists only once
the review commands (C4) are built; until then the records stay `proposed`.
