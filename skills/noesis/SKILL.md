---
name: noesis
description: Capture this session's finished work into the user's knowledge vault, look up what the vault already records (decisions, gotchas, run outcomes), and manage failed curations, through the `noesis` CLI. Use when the user asks to record work in the vault, turn capture on or off, check what was captured, or search past decisions and gotchas.
---

# noesis

This stub finds the CLI, finds the env file this repo's hooks use, and loads the guide
that matches the installed version.

## 1. Resolve the CLI

Run `noesis --version`. If it fails with "command not found", tell the user noesis is not
installed (`uv tool install <path-or-url-of-the-noesis-repo>`) and stop. Do not try other
executables and do not guess commands.

## 2. Find the env file the repo's hooks use

A repo can pin its own noesis config. The env file sets the state dir, the vault and the
capture thresholds. The hooks read only their own env file. If `capture on` uses a
different one, commits are ignored and no error is shown.

1. Read `<repo>/.claude/settings.json` and `<repo>/.claude/settings.local.json`, if they
   exist. Look for a hook command that contains `noesis` and `--env-file <path>`.
   Remove any shell quotes from the path.
2. If you find one, pass that same `--env-file <path>` on every noesis command in this
   session. It is a global flag, so it goes before the subcommand:
   `noesis --env-file <path> capture on …`. This covers `capture on|off|status|runs`,
   `knowledge search|list|parked|retry`, `config show` and `doctor`.
3. If you find none, leave the flag out and tell the user the default env file is in use.

## 3. Load the version-matched guide before running any other noesis command

```text
noesis skills get noesis
```

Follow that guide. Prefer `--json`; use `noesis <command> --help` for anything it does not
cover. If `skills get` is unknown, the installed noesis is too old: say so and use
`--help` for read-only discovery only.

## 4. After `capture on`, verify

Run `capture status` with the same `--env-file` (or none, if you used none). Check that
`enabled` is `true`. Then tell the user which env file, state dir and vault were used.
If `enabled` is not `true`, say that capture is not on. Do not report success.

## This session

Session id for `--session`: `${CLAUDE_SESSION_ID}`
