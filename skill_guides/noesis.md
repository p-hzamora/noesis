# noesis: guide for agents

noesis captures finished work from agent sessions, lets a curator decide what is worth
keeping, and stores it as Markdown notes in the user's vault. This guide matches the
installed noesis version. Use `noesis <command> --help` for anything not covered here.

## Rules

- Always add `--json`. Parse the envelope: `{"ok": true, "result": ...}` or
  `{"ok": false, "error": {"code", "message", "next_steps"}}`. Branch on `error.code`;
  follow `next_steps` when the user agrees.
- Exit codes: 0 ok, 1 the operation failed, 2 invalid command line.
- Never guess commands or flags. If something is not in this guide, run `--help`.
- Never edit files under a vault's `auto/` folders by hand. To record a note yourself, use
  `notes apply` (below); noesis picks the path. Read the notes freely.
- Costly or settings-changing commands (`notes curate`, `notes apply`, `integrate … --yes`)
  only when the user asked for them. `--dry-run` on both shows the result without writing.

## Which env file

The env file decides the state dir (where capture flags and the journal live), the vault
and the capture thresholds. noesis picks it from the repository, so no flag is needed:

1. Look for `<repo>/.noesis-config` (the nearest one, up to the git root). It holds one line,
   `profile = <name>`. The profile file is
   `~/.config/noesis/profiles/<repo folder name>/<name>.env`.
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

After `capture on`, always verify before you report success:

1. Run `capture status` with the same `--env-file` (or none, if you used none).
2. Check that `result.enabled` is `true`. If it is not, say that capture is not on and
   stop. Do not tell the user that capture is on.
3. Tell the user which env file, state dir and vault were used. `capture on` and
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

If the user set `NOESIS_SEARCH_BACKEND=obsidian-mcp`, search goes through Obsidian (it also finds
notes noesis did not write; those have `kind: null`). When Obsidian is closed the same command
still exits 0 with file results and the message `Obsidian MCP unreachable, searched files instead`
(in `--json`, as `result.notice`): tell the user, do not retry. `noesis doctor` shows whether the
MCP answers and serves the vault of `NOESIS_VAULT_DIR`.

Results carry each note's `path`. For the full text, read that file under the vault
folder (`noesis [--env-file <path>] config show --json` -> `settings.notes.vault_dir`).

## Recall notes before a task

Run it once, when you start a task that touches code the vault may already cover (a bug, a
design choice, an unfamiliar area). Do not run it for trivial edits.

```bash
noesis notes recall "<one sentence on the task>" --repo <repo> --json
```

- Pass one sentence about the task, not a pasted prompt. noesis keeps its keywords (3+ letters,
  no stopwords); a sentence with none fails with `NOTES_204_NO_RECALL_TERMS` (exit 1).
- Without `--repo` or `--area` the repository you are in is used; outside a git repository it
  fails with `INTERFACE_002_NOT_IN_GIT_REPOSITORY`.
- The result has `entries` (`kind`, `title`, `path`, `date`, `snippet`), best first, plus
  `considered` and `omitted`. `--limit` (1..20, default 5) and `--budget-tokens` (default 1000,
  `0` is unlimited) bound it. Bodies are never included.
- Read only the entries that look relevant, by `path`, under the vault folder. Do not open them all.
- Tell the user which notes you used (their paths) and why. If `entries` is empty (exit 0,
  text `no relevant notes`), say so and go on without them.
- Do not loop: one recall per task. Do not retry with other wording when it is empty. If the
  result has `notice`, Obsidian was unreachable and files were searched; tell the user, do not retry.

## Record a note yourself

When the user asks you to record something in the vault, write the draft and let noesis store
it. No curator runs. Run it from inside the repository: the note goes to
`repos/<repo folder name>/auto/<kind>s/<slug>.md`, never anywhere else, and a manual note on
the same topic is never touched (it is reported as skipped, `covered by <path>`).

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

## Failed curations

```bash
noesis [--env-file <path>] notes parked --json           # tickets of briefs whose curation failed
noesis [--env-file <path>] notes retry <TICKET> --json   # retry one, in the foreground
```

`notes curate --dry-run` runs the curator and shows what it would store, without writing and
without parking. A brief is parked when the curator keeps failing and also when storing the notes fails (vault
folder not writable, Obsidian's MCP unreachable): both are `NOTES_201_CURATION_FAILED` with a
`ticket` in `error.metadata`. Follow its `next_steps`: fix the cause, then `notes retry
<TICKET>`. A storage failure may carry `written` and `not_written` paths (some notes were stored
before it failed); retry overwrites them all, so do not write notes by hand.

## Where notes are stored

`NOESIS_WRITER_BACKEND` selects the writer: `filesystem` (default; files under
`NOESIS_VAULT_DIR`, which can be an NFS mount) or `mcp` (through Obsidian's MCP server, using the
`NOESIS_OBSIDIAN_MCP_*` settings). Search follows `NOESIS_SEARCH_BACKEND` independently. The
vault folder is only required where files are used (not with writer `mcp` + search
`obsidian-mcp`, except for `notes list`).

## Setup and diagnosis

```bash
noesis [--env-file <path>] doctor --json                       # vault, state dir, git, curator CLI, hooks, writer, search backend, update (warn only)
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
`CAPTURE_001_INVALID_SESSION_ID`, `NOTES_201_CURATION_FAILED` (curation or storage failed; see `notes parked`),
`NOTES_203_APPLY_FAILED` (`notes apply` rejected an entry or could not store; the payload was kept),
`INTERFACE_002_NOT_IN_GIT_REPOSITORY` (run `notes apply` from inside the repository),
`NOTES_204_NO_RECALL_TERMS` (`notes recall` task has no usable keyword),
`INTEGRATION_101_AGENT_SETTINGS_INVALID` (the settings file is not valid JSON).
