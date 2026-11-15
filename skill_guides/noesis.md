# noesis: guide for agents

noesis captures finished work from agent sessions, lets a curator decide what is worth
keeping, and stores it as Markdown notes in the user's vault. This guide matches the
installed noesis version. Use `noesis <command> --help` for anything not covered here.

## Rules

- Always add `--json`. Parse the envelope: `{"ok": true, "result": ...}` or
  `{"ok": false, "error": {"code", "message", "next_steps"}}`. Branch on `error.code`;
  follow `next_steps` when the user agrees.
- Exit codes: 0 ok, 1 the operation failed, 2 invalid command line (a flag you can fix: a blank
  `--session` or `--parent`, a missing `--session`, `--parent` equal to the session, running
  outside a git repository).
- Never guess commands or flags. If something is not in this guide, run `--help`.
- Never edit a note whose frontmatter says `origin: auto` by hand. To record a note yourself, use
  `notes apply` (below); noesis picks the path. Read the notes freely. A note is identified by the
  `noesis:` block in its frontmatter (id, scope, kind, origin), never by its folder.
- Costly or settings-changing commands (`notes curate`, `notes apply`, `integrate … --yes`)
  only when the user asked for them. `--dry-run` on both shows the result without writing.

## Which env file

The env file decides the state dir (where capture flags and the journal live), the vault
and the capture thresholds. noesis picks it from the repository, so no flag is needed:

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

Capture is off by default. When the user asks to record this session's work in the vault:

```bash
noesis [--env-file <path>] capture on --session <SESSION_ID> --json            # live: curate into the vault
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
  new ids (their old state and notes stay where they are).

### Worktrees

Every worktree of a repository is one repository: commits made in a linked worktree are
captured (even when the hook reports the main checkout as the working directory), the brief
records the branch the commit was made on, and the notes go to the main repository's scope,
`repo:<main repo folder name>`. If two worktrees committed within two minutes and the command
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
4. Tell the user which env file, state dir and vault were used. `capture on` and
   `capture status` include them as `env_file`, `state_dir` and `vault_dir`.

Once on, nothing else is needed. After each `git commit` and at the end of each turn, the
Claude Code hooks hand finished work to the curator in the background. A change counts
when the pending commits together reach the size thresholds (`config show`, run with the
same env file). If `capture runs` shows `handed_over` without a result yet, the curator is
still running.

## Look up what the vault already knows

```bash
noesis [--env-file <path>] notes search "<words>" --repo <repo> --json   # best match first
noesis [--env-file <path>] notes list --repo <repo> --origin auto --json  # auto | manual
```

Search scans the vault's Markdown files by default. With `NOESIS_SEARCH_BACKEND=vectra` it
searches a vectra collection and, when vectra fails, the same command still exits 0 with file
results and the message `vectra could not search, searched files instead` (in `--json`, as
`result.notice`): tell the user, do not retry. The values `obsidian-mcp` (search) and `mcp`
(writer) were removed; a configuration naming one fails with `CORE_006_REMOVED_BACKEND` and its
`next_steps` say to use `filesystem`.

Results carry each note's `path`. For the full text, read that file under the vault
folder (`noesis [--env-file <path>] config show --json` -> `settings.notes.vault_dir`).

## Recall notes before a task

Run it once, when you start a task that touches code the vault may already cover (a bug, a
design choice, an unfamiliar area). Do not run it for trivial edits.

```bash
noesis notes recall "<one sentence on the task>" --repo <repo> --json
```

It searches the notes, reads the best ones in full and has an agent write a briefing for the
task. It takes up to about a minute and calls a model, so run it once.

- Pass one sentence about the task, not a pasted prompt. A sentence with no usable keyword fails
  with `NOTES_204_NO_RECALL_TERMS` (exit 1), a blank task with `INTERFACE_005_EMPTY_RECALL_TASK`
  (exit 2).
- Without `--repo` or `--scope` (`repo:<name>` or `topic:<name>`) the repository you are in is used; outside a git repository it
  fails with `INTERFACE_002_NOT_IN_GIT_REPOSITORY`.
- Read `result.synthesis`:
  - `briefing`: use `result.briefing`. `constraints`, `decisions`, `gotchas` and `context` each
    carry `sources` (note paths) that were read and checked. `inferences` are the agent's own
    reasoning, not facts from the notes; `unsupported` are statements dropped for lacking a valid
    citation; `not_covered` is what the notes do not say. `briefing.markdown` is the whole thing
    as a document you can show the user.
  - `no_evidence`: nothing in the vault matched. Say so and go on. Do not retry with other wording.
  - `digest`: only with `--no-synthesis`; `entries` are pointers and snippets, no model ran.
- Tell the user which notes you relied on (their `sources`) and keep inferences labelled as such.
  Check `result.warnings` (notes unreadable, text cut, secrets masked) and `notice` (the search backend
  failed and files were searched); mention them, do not retry.
- `--limit` (1..20, default 5) is how many notes are read; `--budget-tokens` (default 1000, `0`
  none) is the length asked of the briefing. `--no-synthesis` lists the best notes only, with no
  model and no cost.
- `NOTES_103_RECALL_AGENT_FAILED` (exit 1): the briefing could not be written (agent missing,
  model rejected, timeout, unusable answer). `error.metadata.candidates` lists the notes that
  would have been read; rerun with `--no-synthesis` or read them yourself. Do not report the
  recall as done.

## Record a note yourself

When the user asks you to record something in the vault, write the draft and let noesis store
it. No curator runs. Run it from inside the repository: the note goes to
the path the vault's `noesis.yaml` layout gives (by default
`repos/<repo folder name>/<kind folder>/<slug>.md`, with a `-2`, `-3` suffix instead of overwriting
anything), and a manual note on the same topic is never touched (it is reported as skipped, `covered by <path>`).

```bash
noesis notes apply --decisions-file draft.json --dry-run --json     # preview: paths, created/updated/skipped
noesis notes apply --decisions-file draft.json --json               # write
cat draft.json | noesis notes apply --decisions-file - --session <SESSION_ID> --commit <SHA> --json
```

`--session` and `--commit` (repeatable) are optional provenance; without them the note simply
has no `session` / `commits`. The file is:

```json
{"decisions": [{
  "action": "create", "candidate": "TTL cache for logins", "reason": "non-obvious choice",
  "kind": "decision", "slug": "use-ttl-cache", "title": "Use a TTL cache",
  "sections": [{"heading": "Decision", "body": "Keep tokens in memory."}]
}]}
```

`kind` is `decision`, `gotcha`, `run` or `glossary`; missing required sections are filled with
`Not recorded`. Check `result.skipped` after every call. Outside a git repository the command
fails with `INTERFACE_002_NOT_IN_GIT_REPOSITORY` (exit 2).

`apply` is strict: one malformed entry fails the whole call with `NOTES_203_APPLY_FAILED`
(exit 1) and writes nothing. A storage failure fails the same way. Either way the payload you
sent is kept, so nothing is lost: `error.metadata` has `rejected` (entry `index` and `reason`),
`written` / `not_written` (storage), `ticket`, `record_path` and `payload_path`. Fix the entries
and run `apply` again with `--decisions-file <payload_path>`. If the record itself cannot be
kept, the payload is in `error.metadata.raw_payload`.

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

## Failed curations

```bash
noesis [--env-file <path>] notes parked --json           # tickets of briefs whose curation failed
noesis [--env-file <path>] notes retry <TICKET> --json   # retry one, in the foreground
```

`notes curate --dry-run` runs the curator and shows what it would store, without writing and
without parking. A brief is parked when the curator keeps failing and also when storing the notes fails (vault
folder not writable): both are `NOTES_201_CURATION_FAILED` with a
`ticket` in `error.metadata`. Follow its `next_steps`: fix the cause, then `notes retry
<TICKET>`. A storage failure may carry `written` and `not_written` paths (some notes were stored
before it failed); retry overwrites them all, so do not write notes by hand.

## Where notes are stored

`NOESIS_WRITER_BACKEND` selects the writer: `filesystem` (default; files under
`NOESIS_VAULT_DIR`, which can be an NFS mount) or `vectra` (files, then synced into a vectra
collection). Search follows `NOESIS_SEARCH_BACKEND` independently. The vault folder is required.

## Setup and diagnosis

```bash
noesis [--env-file <path>] doctor --json                       # vault, state dir, git, curator CLI, hooks, writer, search backend, graph_store (Neo4j reachable + schema steps; warn only without a password), update (warn only)
noesis [--env-file <path>] config show --json                  # effective settings and their file
noesis [--env-file <path>] config init --vault-dir <folder>    # create the env file (default ~/.config/noesis/.env)
noesis update check --json                             # behind / ahead / diverged / up_to_date / unknown vs origin; exit 0 always
noesis integrate claude-code status --json             # hooks in the user settings file only
noesis integrate claude-code install                   # preview; add --yes to write
```

`integrate claude-code status` and `doctor` inspect only the user settings file
(`~/.claude/settings.json`) by default. Project hooks in `<repo>/.claude/settings*.json`
are not included. To inspect a project file, pass
`integrate claude-code status --settings <repo>/.claude/settings.json`.

Common error codes: `CORE_002_VAULT_NOT_CONFIGURED` (run `config init`),
`INTERFACE_003_BLANK_SESSION_ID` (a blank `--session` or `--parent`; exit 2),
`INTERFACE_004_SELF_PARENT_SESSION` (`--parent` is the session itself; exit 2),
`INTERFACE_005_EMPTY_RECALL_TASK` (`notes recall` got a blank task; exit 2),
`CAPTURE_001_INVALID_SESSION_ID` (a blank id that reached the domain, in practice a hook payload),
`CAPTURE_202_SESSION_ID_MISSING` (no `--session` and none in the environment, exit 2; run
`capture on` and pass back `result.session_id`),
`CAPTURE_201_SESSION_NOT_FOUND` (`--parent` names a session that was never switched on),
`NOTES_201_CURATION_FAILED` (curation or storage failed; see `notes parked`),
`NOTES_203_APPLY_FAILED` (`notes apply` rejected an entry or could not store; the payload was kept),
`INTERFACE_002_NOT_IN_GIT_REPOSITORY` (run `capture`, `notes apply` and `notes recall` from inside the repository),
`NOTES_204_NO_RECALL_TERMS` (`notes recall` task has no usable keyword),
`NOTES_103_RECALL_AGENT_FAILED` (`notes recall` could not write the briefing; `--no-synthesis` still works),
`INTEGRATION_101_AGENT_SETTINGS_INVALID` (the settings file is not valid JSON).
