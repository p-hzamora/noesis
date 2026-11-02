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
- Never edit files under a vault's `auto/` folders by hand and never write notes yourself;
  noesis owns them. Read them freely.
- Costly or settings-changing commands (`knowledge curate`, `integrate … --yes`) only when
  the user asked for them.

## Which env file

The env file decides the state dir (where capture flags and the journal live), the vault
and the capture thresholds. The Claude Code hooks read only the env file in their own
command. If you run `capture on` against a different env file, the flag goes into a state
dir the hooks never read. The commit is then ignored, and no error is shown.

1. Look in `<repo>/.claude/settings.json` and `<repo>/.claude/settings.local.json` for a
   hook command that runs `noesis` with `--env-file <path>`, for example
   `/home/me/.local/bin/noesis --env-file /home/me/lab/noesis.env hook claude-code`.
   Remove any shell quotes from the path. Resolve a relative path against the repo root.
2. If you find one, pass that same `--env-file <path>` on every noesis command in this
   session: `capture`, `knowledge`, `config show` and `doctor`. It is a global flag, so it
   goes before the subcommand: `noesis --env-file <path> capture on …`, never after.
3. If you find none, leave the flag out. noesis then uses its default env file
   (`~/.config/noesis/.env`, or `$NOESIS_ENV_FILE`). Tell the user the default is in use.

In the examples below, `[--env-file <path>]` means: include the flag when step 2 applies.

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
noesis [--env-file <path>] knowledge search "<words>" --repo <repo> --json   # best match first
noesis [--env-file <path>] knowledge list --repo <repo> --origin auto --json  # auto | manual
```

If the user set `NOESIS_SEARCH_BACKEND=obsidian-mcp`, search goes through Obsidian (it also finds
notes noesis did not write; those have `kind: null`). When Obsidian is closed the same command
still exits 0 with file results and the message `Obsidian MCP unreachable, searched files instead`
(in `--json`, as `result.notice`): tell the user, do not retry. `noesis doctor` shows whether the
MCP answers and serves the vault of `NOESIS_VAULT_DIR`.

Results carry each note's `path`. For the full text, read that file under the vault
folder (`noesis [--env-file <path>] config show --json` -> `settings.knowledge.vault_dir`).

## Failed curations

```bash
noesis [--env-file <path>] knowledge parked --json           # tickets of briefs whose curation failed
noesis [--env-file <path>] knowledge retry <TICKET> --json   # retry one, in the foreground
```

## Setup and diagnosis

```bash
noesis [--env-file <path>] doctor --json                       # vault, state dir, git, curator CLI, hooks, search backend
noesis [--env-file <path>] config show --json                  # effective settings and their file
noesis [--env-file <path>] config init --vault-dir <folder>    # create the env file (default ~/.config/noesis/.env)
noesis integrate claude-code status --json             # hooks in the user settings file only
noesis integrate claude-code install                   # preview; add --yes to write
```

`integrate claude-code status` and `doctor` inspect only the user settings file
(`~/.claude/settings.json`) by default. Project hooks in `<repo>/.claude/settings*.json`
are not included. To inspect a project file, pass
`integrate claude-code status --settings <repo>/.claude/settings.json`.

Common error codes: `CORE_002_VAULT_NOT_CONFIGURED` (run `config init`),
`CAPTURE_001_INVALID_SESSION_ID`, `KNOWLEDGE_201_CURATION_FAILED` (see `knowledge parked`),
`INTEGRATION_101_AGENT_SETTINGS_INVALID` (the settings file is not valid JSON).
