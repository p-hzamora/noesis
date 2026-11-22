# ADR-0007: `remember` replaces `record capture`

Status: accepted, 2026-11-22.

## Context

Intentional capture lived under `noesis record capture` (knowledge or experience, required
idempotency key and sources). Nothing compared a new record with what the store already held, and
there was no way to say that a memory refines a skill.

## Decision

`noesis remember --as knowledge|experience` is the write command. It reuses the capture
handlers, so validation, redaction, sources, actor detection and scope are identical, and adds:

- reconciliation before writing, through the similar-record finder: likely `duplicates` and
  `related` records are reported, never merged; a duplicate suggests `consolidation propose`;
- `--check` to preview reconciliation without writing;
- `--refines <ref>` and `--supersedes <id>`, which propose assertions with the new record as
  subject and its sources as evidence (`refines` is a new assertion predicate);
- an optional `--idempotency-key`, defaulting to `remember:<sha256 of the normalised request>` so
  a retried identical request replays.

Knowledge is always written `proposed`; promotion stays an explicit review decision.

## Consequences

One write command for agents. Two intentionally identical captures replay instead of
duplicating. Session capture (`noesis capture`) and curation (`noesis curate`) are unchanged.
