# ADR-0008: staged retirement of `recall` and `record capture`

Status: accepted, 2026-11-22.

## Context

Both commands have first-party consumers (docs, skill guide, scripts, tests). Removing them at
once would break agents and scripts silently.

## Decision

| Stage | Behaviour | Release |
| --- | --- | --- |
| A | new commands and fields; old commands unchanged | 0.2.0 |
| D | old commands forward to the new implementation, stdout unchanged, stderr `DEPRECATED: use ...` (silenced by `NOESIS_SILENCE_DEPRECATION=1`) | 0.2.0 |
| R | old commands exit 2 naming the replacement | 0.3.0 |

Stage R requires all of: Stage D shipped in a tagged release; the consumer guard
(`tests/architecture/test_legacy_command_consumers.py`) lists no `PENDING_MIGRATION` file; the
golden scenarios pass through `search` and `remember` alone; the digest equivalence test passes;
the user approves in the CHANGELOG entry.

## Consequences

Consumers get one release of warnings. No data migrates: both paths write the same records.
`notes` stays retired.
