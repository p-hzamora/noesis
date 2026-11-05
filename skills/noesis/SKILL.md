---
name: noesis
description: Capture finished work into the notes vault, search past decisions and gotchas, and manage failed curations with the `noesis` CLI.
when_to_use: Use when the user asks to record work in the vault, turn capture on or off, check what was captured, search past decisions and gotchas, or retry a parked curation.
argument-hint: "[capture on|off|status|runs | search <text> | list | parked]"
---

# noesis

This stub finds the CLI, finds the env file this repo's hooks use, and loads the guide
that matches the installed version.

## 1. Resolve the CLI

Run `noesis --version`. If it fails with "command not found", tell the user noesis is not
installed (`uv tool install <path-or-url-of-the-noesis-repo>`) and stop. Do not try other
executables and do not guess commands.

## 2. Check which config the repo selects

noesis picks its config from the repo itself. The env file sets the state dir, the vault and
the capture thresholds. The hooks use the same lookup, so no flag is needed.

1. Look for `<repo>/.noesis-config` (or the nearest one up to the git root). It holds
   `profile = <name>`, and the profile file is
   `~/.config/noesis/profiles/<repo folder name>/<name>.env`.
2. If it exists, run noesis from inside the repo with no env flag.
3. If it does not exist, noesis uses `~/.config/noesis/.env`. Tell the user the default is
   in use.
4. Pass `--env-file <path>` only when the user asks for a specific file. It is a global
   flag, so it goes before the subcommand: `noesis --env-file <path> capture on …`.
   `NOESIS_ENV_FILE` no longer exists; do not set it.

## 3. Load the version-matched guide before running any other noesis command

```text
noesis skills get noesis
```

Follow that guide. Prefer `--json`; use `noesis <command> --help` for anything it does not
cover. If `skills get` is unknown, the installed noesis is too old: say so and use
`--help` for read-only discovery only.

## 4. After `capture on`, verify

Run `capture status` from the same repo, with the same `--env-file` (or none). Check that
`enabled` is `true`. Then tell the user which env file, state dir and vault were used.
If `enabled` is not `true`, say that capture is not on. Do not report success.

## This session

Session id for `--session`: `${CLAUDE_SESSION_ID}`
