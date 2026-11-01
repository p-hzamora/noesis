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

## Capture this session's work

Capture is off by default. When the user asks to record this session's work in the vault:

```bash
noesis capture on --session <SESSION_ID> --json            # live: curate into the vault
noesis capture on --session <SESSION_ID> --mode dry-run --json   # only store briefs
noesis capture status --session <SESSION_ID> --json        # on/off, pending commits
noesis capture runs --session <SESSION_ID> --json          # journal + curation results
noesis capture off --session <SESSION_ID> --json
```

Once on, nothing else is needed: after each `git commit` and at the end of each turn, the
Claude Code hooks hand finished work to the curator in the background. A change counts
when the pending commits together reach the size thresholds (`noesis config show`).
If `capture runs` shows `handed_over` without a result yet, the curator is still running.

## Look up what the vault already knows

```bash
noesis knowledge search "<words>" --repo <repo> --json   # best match first
noesis knowledge list --repo <repo> --origin auto --json  # auto | manual
```

If the user set `NOESIS_SEARCH_BACKEND=obsidian-mcp`, search goes through Obsidian (it also finds
notes noesis did not write; those have `kind: null`). When Obsidian is closed the same command
still exits 0 with file results and the message `Obsidian MCP unreachable, searched files instead`
(in `--json`, as `result.notice`): tell the user, do not retry. `noesis doctor` shows whether the
MCP answers and serves the vault of `NOESIS_VAULT_DIR`.

Results carry each note's `path`; read the file under the vault folder
(`noesis config show --json` -> `settings.knowledge.vault_dir`) for the full text.

## Failed curations

```bash
noesis knowledge parked --json           # tickets of briefs whose curation failed
noesis knowledge retry <TICKET> --json   # retry one, in the foreground
```

## Setup and diagnosis

```bash
noesis doctor --json                                   # vault, state dir, git, curator CLI, hooks, search backend
noesis config show --json                              # effective settings and their file
noesis config init --vault-dir <folder>                # create ~/.config/noesis/.env
noesis integrate claude-code status --json             # are the hooks registered?
noesis integrate claude-code install                   # preview; add --yes to write
```

Common error codes: `CORE_002_VAULT_NOT_CONFIGURED` (run `config init`),
`CAPTURE_001_INVALID_SESSION_ID`, `KNOWLEDGE_201_CURATION_FAILED` (see `knowledge parked`),
`INTEGRATION_101_AGENT_SETTINGS_INVALID` (the settings file is not valid JSON).
