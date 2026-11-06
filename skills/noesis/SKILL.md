---
name: noesis
description: Capture finished work into the notes vault, write notes directly, search past decisions and gotchas, and manage failed curations with the `noesis` CLI.
when_to_use: Use when the user asks to record work or a note in the vault, turn capture on or off, check what was captured, search past decisions and gotchas, or retry a parked curation.
argument-hint: "[capture on|off|status|runs | apply | search <text> | list | parked]"
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
   `~/.config/noesis/profiles/<main repo folder name>/<name>.env`. In a linked git worktree
   the file is usually missing (it is gitignored), so noesis falls back to the
   main checkout's `.noesis-config` and the main checkout's folder name.
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
If `enabled` is not `true`, say that capture is not on. Do not report success. Also check
`generated` in the `capture on` result: `true` means noesis invented the session id, no hook can
match it, and capture will not happen (it prints a warning on stderr too); redo `capture on`
with `--session`.

## This session

Session id for `--session`: `${CLAUDE_SESSION_ID}`

noesis derives the id it stores from this value and the repository, and prints it as
`result.session_id`; pass that value back as `--session` for later commands. A blank
`--session` is an error (exit 2). Non-Claude agents (Codex reads its own thread id) omit
`--session` on `capture on` and pass back `result.session_id`; if `result.generated` is `true`
the id was invented and no hook can match it. A sub-agent uses
`capture on --parent <parent session id>`. After upgrading noesis, run `capture on` again;
sessions switched on by an older version are not found.
