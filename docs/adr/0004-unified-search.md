# ADR-0004: one read command — `search` absorbs `recall`

Status: accepted, 2026-11-22.

## Context

`search` ranked Knowledge and Experience records. `recall` reused the same pipeline
(`RecordSearcher`) and added review admission, body hydration under a character budget, a digest
or a model briefing, and tools reached through `recommends` assertions with runtime
availability. Agents had to know which of two overlapping commands to call, and neither returned
installed skills.

## Decision

`noesis search` is the single read, discovery and briefing entry point. It keeps `ok`,
`result.scope`, `result.hits`, `result.index`, `result.warnings` and the record-only meaning of
`--limit` unchanged, and adds `requirements`, `resources`, `next_actions` and an optional
`briefing`.

- `--briefing none|digest|synthesis`, default `none`; `digest` is the former
  `recall --no-synthesis`, `synthesis` the former `recall`. `--budget-chars` bounds hydration.
- `--resource-limit` (default 8) bounds selected resources; prerequisites of a selected resource
  are added within depth 3 and 10 items, truncation is warned.
- Requirement facets come from `--need` (the agent decomposes its own task) or, without it, from
  salient query terms. No topic vocabulary lives in code.
- The recall pipeline moves into `TaskBriefingService`; `RecallHandler` is removed; the `recall`
  shim calls `TaskBriefingService` directly. Nothing is copied.
- `next_actions` uses a closed action enum (`load_skill`, `use_agent`, `use_cli_tool`,
  `use_mcp_server`, `read_record`) and canonical refs (`catalog:<kind>:<name>`,
  `record:<ulid>@<rev>`); no shell text from stored content.

## Consequences

One retrieval contract to document and test. Consumers that relied on `recall`'s envelope keep it
through the shim (ADR-0008). Default searches return no bodies, so agents that want the old
briefing must ask for it. Additive JSON keeps existing parsers working.
