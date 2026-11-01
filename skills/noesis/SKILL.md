---
name: noesis
description: Capture this session's finished work into the user's knowledge vault, look up what the vault already records (decisions, gotchas, run outcomes), and manage failed curations, through the `noesis` CLI. Use when the user asks to record work in the vault, turn capture on or off, check what was captured, or search past decisions and gotchas.
---

# noesis

This stub only finds the CLI and loads the guide that matches the installed version.

## 1. Resolve the CLI

Run `noesis --version`. If it fails with "command not found", tell the user noesis is not
installed (`uv tool install <path-or-url-of-the-noesis-repo>`) and stop. Do not try other
executables and do not guess commands.

## 2. Load the version-matched guide before running any other noesis command

```text
noesis skills get noesis
```

Follow that guide. Prefer `--json`; use `noesis <command> --help` for anything it does not
cover. If `skills get` is unknown, the installed noesis is too old: say so and use
`--help` for read-only discovery only.

## This session

Session id for `--session`: `${CLAUDE_SESSION_ID}`
