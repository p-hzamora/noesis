# ADR-0008: removal of `recall` and `record capture`

Status: accepted, 2026-11-22; amended 2026-11-23.

## Context

`search` replaces `recall` and `remember` replaces `record capture`. The first plan retired the old
commands in stages, because docs, skill guide, scripts and tests used them. Those consumers have
all moved, and the consumer guard (`tests/architecture/test_legacy_command_consumers.py`) finds no
first-party use left.

## Decision

Both commands are removed outright. There is no deprecation stage and no exit-2 stub: with no
consumer left, a warning protects nobody. `noesis recall` and `noesis record capture` now fail as
any unknown command does (exit 2, "No such command"). `record revise` and `record get` stay.

The consumer guard stays as a permanent check: only the historical files may mention the old
commands.

## Consequences

No data migrates: both paths wrote the same records. `notes` stays retired.
