# noesis remember

Capture knowledge or an experience on purpose: with its scope and sources, checked against what
the store already holds, and with optional proposed relations to other records. It replaces
the capture subcommand of `record` ([ADR-0007](../adr/0007-remember.md)); the old command still
works and forwards here (see [record.md](record.md)). Needs `NOESIS_NEO4J_PASSWORD` like every record command;
`--help` and usage errors never connect.

```text
noesis remember --as knowledge  --subtype <slug> --title <text> --body <text|->
                (--source <kind>:<locator> | --source-id <id>)...
                [--project <key> | --target-root <path> | --space-wide] [--tag <tag>]...
                [--refines <ref>]... [--supersedes <record-id>]
                [--idempotency-key <key>] [--check] [--json]
noesis remember --as experience --body <text|-> [--subtype observation|outcome|failure]
                (--source <kind>:<locator> | --source-id <id>)...
                [--occurred <ISO 8601>] [--session <id>] [--environment <text>]
                [--project <key> | --target-root <path> | --space-wide]
                [--idempotency-key <key>] [--check] [--json]
```

## What it does

1. Validates, redacts secrets, resolves the actor, scope and sources exactly as the old
   capture command did: it calls the same capture handlers. Knowledge is always written `proposed`; an
   experience has no status.
2. Looks for records that resemble the new one (same space, applicable scope). A record whose
   word overlap with the new text is at least 0.80 and of the same type is listed under
   `reconciliation.duplicates`; at least 0.30, under `reconciliation.related`. Nothing is merged,
   retracted, accepted or superseded. For a duplicate, `next_steps` points at
   `noesis consolidation propose` (both records must be accepted first).
3. Writes the record, then proposes one assertion per `--refines` / `--supersedes`, with the new
   record as subject and its sources as evidence. They are `proposed`; review decides.

Retrieval never changes a record: reading it with `search` leaves its status and authority as they
were.

## Options

- `--as knowledge|experience` (required). `--title` and `--subtype` are required for knowledge.
- `--source <kind>:<locator>` / `--source-id <ULID>`: at least one; same kinds and rules as
  the old capture command. `--body -` reads stdin.
- Scope: `--space-wide` (no project), `--project <key>`, `--target-root <path>` (the repository
  name of that checkout; none when it has no repository), else the git repository of the working
  directory. They are mutually exclusive. `result.scope` says which one applied.
- `--refines <ref>` (repeatable): the new record refines a knowledge record or a catalog entry.
  `<ref>` is a record id, `record:<id>`, or `catalog:<kind>:<name>`. An unknown ref fails before
  anything is written (`KNOWLEDGE_201_RECORD_NOT_FOUND` or `KNOWLEDGE_261_CATALOG_ENTRY_NOT_FOUND`).
  A refinement is scoped by the project of the memory.
- `--supersedes <record-id>`: knowledge only. Proposes a `supersedes` assertion; the old record is
  unchanged until a review accepts it. It must have the same project as the new record.
- `--idempotency-key <key>`: optional. By default the key is `remember:<sha256 of the normalised
  request>` (trimmed, redacted text; sorted tags and refs), so repeating the same command replays
  the first result (`replayed: true`) and writes nothing. The same key with a different request
  fails with `KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED`.
- `--check`: report `reconciliation` and the planned assertions, write nothing, exit 0.

## Result

`written`, `record_id` (absent with `--check`), `record_type`, `revision`, `status`, `space_id`,
`project_id`, `replayed`, `idempotency_key`, `scope` (`project_key`, `source`), `reconciliation`
(`duplicates[]`, `related[]`: `{id, score, authority, title}`; `warnings[]`), `assertions[]`
(`{id, predicate, object_ref, status}`; `planned` with `--check`) and `next_steps`.

`score` is the share of distinct words the two texts have in common, 0..1 (Retrieval ranks
candidates but reports no similarity). If the lookup cannot run (for example the index steps are
missing), `reconciliation.warnings` says so and the record is written anyway.

## Failures

| Condition | Result |
|---|---|
| no `--source` | usage error, exit 2 |
| a `--refines` or `--supersedes` target is unknown or of a kind the predicate does not allow | exit 1 before any write |
| the record was written but an assertion failed | `KNOWLEDGE_296_REMEMBER_PARTIALLY_APPLIED`, exit 1; `error.metadata` lists the record and each assertion; the record is kept. Fix the cause and rerun the same command with the same `--idempotency-key`: the record replays and only the missing assertions are created |
| same key, different request | `KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED`, exit 1 |

## Examples

```bash
noesis remember --as knowledge --subtype gotcha --title "uv sync drops extras" \
  --body "Run uv sync --all-extras in CI." --source commit:$(git rev-parse HEAD) --json

noesis remember --as knowledge --subtype decision --title "Pin ruff" --body "Pin ruff to 0.8." \
  --source url:https://example.test/adr --refines catalog:skill:python-syntax --check --json
```
